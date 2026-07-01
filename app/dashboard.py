"""Stock Advisor — Streamlit dashboard."""
import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from data.loader import (
    load_watchlist, load_holdings, fetch_ticker_info, fetch_price_history,
    save_watchlist, save_holdings, current_portfolio_value,
)
from db.store import (
    init_db, get_saved_picks, save_pick, remove_pick,
    get_suggestion_history, get_recent_alerts, get_performance_snapshot,
)
from scripts.run_analysis import run_analysis

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  section[data-testid="stSidebar"] {
    background: #0f1117; border-right: 1px solid #1e2130;
  }
  section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
  section[data-testid="stSidebar"] .stButton > button {
    background: #1e2130; border: 1px solid #2d3348;
    color: #e2e8f0 !important; border-radius: 8px;
    width: 100%; transition: background 0.15s;
  }
  section[data-testid="stSidebar"] .stButton > button:hover { background: #2d3348; }

  .main .block-container { padding: 2rem 2.5rem; max-width: 1300px; }

  .metric-card {
    background: #fff; border: 1px solid #e8eaf0;
    border-radius: 12px; padding: 1.2rem 1.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .metric-label { font-size:.78rem; font-weight:600; letter-spacing:.06em;
    color:#6b7280; text-transform:uppercase; }
  .metric-value { font-size:1.7rem; font-weight:700; color:#111827; margin-top:.2rem; }
  .metric-sub   { font-size:.82rem; color:#9ca3af; margin-top:.15rem; }

  .badge { display:inline-block; padding:3px 10px; border-radius:999px;
    font-size:.78rem; font-weight:600; }
  .badge-strong-buy { background:#dcfce7; color:#166534; }
  .badge-buy        { background:#dbeafe; color:#1e40af; }
  .badge-watch      { background:#fef9c3; color:#854d0e; }
  .badge-avoid      { background:#fee2e2; color:#991b1b; }

  .section-header {
    font-size:1.1rem; font-weight:700; color:#111827;
    padding-bottom:.5rem; border-bottom:2px solid #f3f4f6; margin-bottom:1.2rem;
  }

  .score-bar-bg   { background:#f3f4f6; border-radius:999px; height:7px; width:100%; }
  .score-bar-fill { height:7px; border-radius:999px; }

  .regime-banner {
    background: linear-gradient(135deg,#667eea 0%,#764ba2 100%);
    border-radius:12px; padding:.9rem 1.4rem; color:white;
  }
  .regime-key { font-size:1.1rem; font-weight:700; }
  .regime-sub { font-size:.83rem; opacity:.85; }

  .warn-banner {
    background:#fffbeb; border:1px solid #fcd34d;
    border-radius:10px; padding:.8rem 1.2rem;
    font-size:.9rem; color:#92400e;
  }

  thead th { background:#f9fafb !important; }
  .stDataFrame { border-radius:10px; overflow:hidden; }
  #MainMenu, footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# ── Init ──────────────────────────────────────────────────────────────────────
init_db()

ACTION_BADGE = {
    "Strong Buy": "badge-strong-buy",
    "Buy":        "badge-buy",
    "Watch":      "badge-watch",
    "Avoid":      "badge-avoid",
}

INDUSTRIES = [
    "Technology", "Financials", "Healthcare", "Energy",
    "Consumer Staples", "Consumer Discretionary", "Industrials",
    "Materials", "Real Estate", "Utilities", "Communication Services", "Misc",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _badge(action):
    cls = ACTION_BADGE.get(action, "badge-watch")
    return f'<span class="badge {cls}">{action}</span>'

def _score_bar(score, color="#667eea"):
    pct = min(max(score, 0), 100)
    return (f'<div class="score-bar-bg">'
            f'<div class="score-bar-fill" style="width:{pct}%;background:{color}"></div>'
            f'</div>')

def _score_color(score):
    if score >= 75: return "#16a34a"
    if score >= 60: return "#2563eb"
    if score >= 45: return "#d97706"
    return "#dc2626"

def _sparkline(symbol: str) -> go.Figure:
    try:
        hist = fetch_price_history(symbol, "1mo")
        close = hist["Close"]
        color = "#16a34a" if close.iloc[-1] >= close.iloc[0] else "#dc2626"
        fig = go.Figure(go.Scatter(
            x=close.index, y=close.values,
            mode="lines", line=dict(color=color, width=1.5),
        ))
        fig.update_layout(
            height=60, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig
    except Exception:
        return None

# ── Auto-refresh every 5 minutes ─────────────────────────────────────────────
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

# ── Sidebar portfolio snapshot (computed from imported holdings) ───────────────
def _sidebar_snapshot():
    h = load_holdings()
    positions = h.get("positions", [])
    cash = float(h.get("cash", 0))

    equity_val = 0.0
    total_cost = 0.0
    total_gl   = 0.0
    day_gl     = 0.0
    has_rich   = False  # True if at least one position has broker-imported value

    for p in positions:
        qty    = float(p.get("quantity", 0) or 0)
        cb     = float(p.get("cost_basis", 0) or 0)
        cur_v  = p.get("current_value")
        cost_v = p.get("total_cost")
        gl_amt = p.get("unrealized_gl")
        day_v  = p.get("day_change")

        if cur_v is not None:
            has_rich = True
            cur_v  = float(cur_v)
            cost_v = float(cost_v or (cb * qty))
            gl_amt = float(gl_amt if gl_amt is not None else (cur_v - cost_v))
            day_gl += float(day_v or 0)
            equity_val += cur_v
            total_cost += cost_v
            total_gl   += gl_amt
        else:
            # old format — use cost_basis as proxy for value
            equity_val += cb * qty
            total_cost += cb * qty

    total_val    = equity_val + cash
    total_gl_pct = (total_gl / total_cost * 100) if total_cost else 0.0
    day_gl_pct   = (day_gl / (equity_val - day_gl) * 100) if (equity_val - day_gl) else 0.0
    return {
        "total_val":   total_val,
        "equity_val":  equity_val,
        "cash":        cash,
        "total_gl":    total_gl,
        "total_gl_pct":total_gl_pct,
        "day_gl":      day_gl,
        "day_gl_pct":  day_gl_pct,
        "n_positions": len(positions),
        "n_watchlist": len(load_watchlist()),
        "has_rich":    has_rich,
    }

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Stock Advisor")
    st.markdown("---")

    page = st.radio(
        "Navigate",
        ["Dashboard", "Portfolio", "Market Scan", "Alerts", "Saved Lists", "History", "Performance", "Settings"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    if st.button("▶  Run Analysis Now", use_container_width=True):
        st.session_state["run_analysis"] = True

    # ── Portfolio snapshot ─────────────────────────────────────────────────
    snap = _sidebar_snapshot()
    st.markdown("---")

    st.metric(
        label="Portfolio Value",
        value=f"${snap['total_val']:,.0f}",
        help=f"${snap['equity_val']:,.0f} equities · ${snap['cash']:,.0f} cash",
    )

    if snap["has_rich"]:
        gl_delta  = f"{'+' if snap['total_gl'] >= 0 else ''}{snap['total_gl_pct']:.1f}%  (${snap['total_gl']:+,.0f})"
        day_delta = f"{'+' if snap['day_gl'] >= 0 else ''}{snap['day_gl_pct']:.2f}%  (${snap['day_gl']:+,.0f})"
        st.metric("Total Return",   f"${snap['total_gl']:+,.0f}",  delta=gl_delta)
        st.metric("Today's Change", f"${snap['day_gl']:+,.0f}",    delta=day_delta)
    else:
        st.caption("⚠️ Re-import your J.P. Morgan CSV in **Settings** to see live G/L and day change.")

    st.metric("Holdings", f"{snap['n_positions']} positions", delta=f"{snap['n_watchlist']} on watchlist", delta_color="off")

    # ── API key status ─────────────────────────────────────────────────────
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    st.markdown("---")
    status_dot = "🟢" if has_key else "🔴"
    st.caption(f"{status_dot} {'AI active' if has_key else 'No API key — AI off'}")
    refresh_time = datetime.now().strftime("%-I:%M %p")
    st.caption(f"Refreshed {refresh_time} · Not financial advice")


# ── API key warning banner (shown at top of every page) ──────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.markdown("""
    <div class="warn-banner">
      ⚠️ <strong>ANTHROPIC_API_KEY not set</strong> — sentiment scoring and LLM regime detection
      are disabled. Go to <strong>Settings</strong> to add your key.
    </div><br>
    """, unsafe_allow_html=True)


# ── Run analysis if triggered ─────────────────────────────────────────────────
if st.session_state.get("run_analysis"):
    st.session_state["run_analysis"] = False
    with st.spinner("Running analysis…"):
        progress = st.empty()
        def _cb(msg): progress.caption(msg)
        results, regime = run_analysis(status_cb=_cb)
        progress.empty()
    st.session_state["results"] = results
    st.session_state["regime"] = regime
    st.success("Analysis complete!")


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "Dashboard":
    st.markdown("# Portfolio Advisor")
    st.markdown("Your watchlist scored, ranked, and sized — you decide when to act.")

    results = st.session_state.get("results")
    regime  = st.session_state.get("regime")

    # KPI strip
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Watchlist</div>
          <div class="metric-value">{len(load_watchlist())}</div>
          <div class="metric-sub">stocks tracked</div></div>""", unsafe_allow_html=True)
    with col2:
        buys = sum(1 for r in (results or []) if r["action"] in ("Buy","Strong Buy"))
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Buy Signals</div>
          <div class="metric-value">{buys}</div>
          <div class="metric-sub">from last run</div></div>""", unsafe_allow_html=True)
    with col3:
        pv = current_portfolio_value(load_holdings())
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Portfolio Value</div>
          <div class="metric-value">${pv:,.0f}</div>
          <div class="metric-sub">incl. cash</div></div>""", unsafe_allow_html=True)
    with col4:
        vix_val = regime["vix"] if regime else "—"
        regime_lbl = (regime["label"].split(" / ")[0]) if regime else "Run analysis"
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">VIX</div>
          <div class="metric-value">{vix_val}</div>
          <div class="metric-sub">{regime_lbl}</div></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Portfolio industry pie chart
    _h_pie = load_holdings()
    _positions_pie = _h_pie.get("positions", [])
    # Build sector → industry lookup from watchlist as fallback
    _wl_industry = {t["symbol"]: t.get("industry","Other") for t in load_watchlist()}

    if _positions_pie:
        _pie_rows = []
        for _p in _positions_pie:
            _qty = float(_p.get("quantity", 0) or 0)
            _cb  = float(_p.get("cost_basis", 0) or 0)
            _cv  = _p.get("current_value")
            _cp  = _p.get("current_price")
            # Best available value estimate
            if _cv is not None and float(_cv) > 0:
                _v = float(_cv)
            elif _cp is not None and float(_cp) > 0:
                _v = float(_cp) * _qty
            elif _cb > 0:
                _v = _cb * _qty
            else:
                _v = _qty  # at minimum count as 1 unit so it shows up

            # Best available sector: from broker import, then watchlist, then "Other"
            _sector = ((_p.get("sector") or "").strip()
                       or _wl_industry.get(_p["symbol"], "")
                       or "Other")
            if _sector == "":
                _sector = "Other"
            _pie_rows.append({"sector": _sector, "value": _v, "sym": _p["symbol"]})

        _pie_df = pd.DataFrame(_pie_rows).groupby("sector")["value"].sum().reset_index()
        _pie_df = _pie_df[_pie_df["value"] > 0].sort_values("value", ascending=False)

        _COLORS = [
            "#6366f1","#8b5cf6","#3b82f6","#10b981","#f59e0b",
            "#ef4444","#ec4899","#14b8a6","#f97316","#84cc16",
            "#06b6d4","#a78bfa","#fb923c","#4ade80","#e879f9",
        ]

        _pie_fig = go.Figure(go.Pie(
            labels=_pie_df["sector"],
            values=_pie_df["value"],
            hole=0.5,
            marker_colors=_COLORS[:len(_pie_df)],
            textinfo="label+percent",
            textfont_size=11,
            hovertemplate="<b>%{label}</b><br>$%{value:,.0f}  ·  %{percent}<extra></extra>",
            direction="clockwise",
            sort=True,
        ))
        _total_eq = _pie_df["value"].sum()
        _pie_fig.add_annotation(
            text=f"<b>${_total_eq:,.0f}</b><br><span style='font-size:10px;color:#6b7280'>equities</span>",
            x=0.5, y=0.5, showarrow=False, font_size=13, align="center",
        )
        _pie_fig.update_layout(
            height=300,
            margin=dict(l=0, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=True,
            legend=dict(orientation="v", x=1.02, y=0.5, font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        )

        _pie_left, _pie_right = st.columns([1.2, 1.8])
        with _pie_left:
            st.markdown('<div class="section-header">Portfolio by Industry</div>', unsafe_allow_html=True)
            # Show note if values are approximate (no broker import)
            _has_rich_pie = any(p.get("current_value") for p in _positions_pie)
            if not _has_rich_pie:
                st.caption("⚠️ Using cost basis — re-import CSV for live values & sectors")
            st.plotly_chart(_pie_fig, use_container_width=True, config={"displayModeBar": False})

    # Regime banner
    if regime:
        w = regime
        src = "🤖 LLM-classified" if w.get("source") == "llm" else "📊 VIX rule"
        rationale = w.get("rationale", "")
        st.markdown(f"""<div class="regime-banner">
          <div class="regime-key">Market Regime: {w['label']}</div>
          <div class="regime-sub">
            Weights → Fundamentals {w['fund']*100:.0f}% · Technicals {w['tech']*100:.0f}% ·
            Sentiment {w['sent']*100:.0f}% &nbsp;|&nbsp; {src}
          </div>
          <div class="regime-sub" style="margin-top:4px;font-style:italic;">{rationale}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    if not results:
        st.info("Click **▶ Run Analysis Now** in the sidebar to score your watchlist.")
        st.stop()

    st.markdown('<div class="section-header">Ranked Suggestions</div>', unsafe_allow_html=True)
    saved_symbols = {p["symbol"] for p in get_saved_picks()}
    wl_industries = {t["symbol"]: t.get("industry","Misc") for t in load_watchlist()}

    for r in results:
        action = r["action"]
        score  = r["score"]
        color  = _score_color(score)

        with st.container():
            # Row: symbol | badge | score+bar | sparkline | entry→target | qty | actions
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.1, 0.8, 0.9, 1.5, 1.1, 1.2, 1.1, 1.4])

            with c1:
                day_chg = r.get("day_change_pct")
                chg_str = ""
                if day_chg is not None:
                    arrow = "▲" if day_chg >= 0 else "▼"
                    chg_col = "#16a34a" if day_chg >= 0 else "#dc2626"
                    chg_str = f"<span style='color:{chg_col};font-size:.78rem'>{arrow} {abs(day_chg):.1f}% today</span>"
                st.markdown(
                    f"**{r['symbol']}**  \n"
                    f"<small style='color:#6b7280'>{r.get('industry','')}</small>  \n"
                    f"{chg_str}",
                    unsafe_allow_html=True
                )
            with c2:
                st.markdown(_badge(action), unsafe_allow_html=True)
            with c3:
                st.markdown(
                    f"<span style='font-weight:700;color:{color};font-size:1.1rem'>{score}</span>"
                    f"<span style='color:#9ca3af;font-size:.8rem'> /100</span>",
                    unsafe_allow_html=True
                )
                st.markdown(_score_bar(score, color), unsafe_allow_html=True)
                st.markdown(
                    f"<small style='color:#9ca3af'>F{r['fund_score']} T{r['tech_score']} S{r['sent_score']}</small>",
                    unsafe_allow_html=True
                )
            with c4:
                spark = _sparkline(r["symbol"])
                if spark:
                    st.plotly_chart(spark, use_container_width=True, config={"displayModeBar": False})
            with c5:
                st.markdown(f"**${r['current_price']}**  \n<small style='color:#6b7280'>Entry</small>", unsafe_allow_html=True)
            with c6:
                st.markdown(
                    f"**${r['target_price']}**  \n"
                    f"<small style='color:#16a34a'>+{r['upside_pct']}% upside</small>",
                    unsafe_allow_html=True
                )
            with c7:
                qty = r["suggested_quantity"]
                existing = r.get("existing_quantity", 0)
                st.markdown(
                    f"**{qty} shares**  \n"
                    f"<small style='color:#6b7280'>{'holding '+str(existing) if existing else 'not held'}</small>",
                    unsafe_allow_html=True
                )
            with c8:
                sub1, sub2 = st.columns(2)
                with sub1:
                    with st.expander("Why"):
                        for reason in r.get("reasons", []):
                            st.markdown(f"• {reason}")
                with sub2:
                    already_saved = r["symbol"] in saved_symbols
                    btn_label = "★" if already_saved else "☆ Save"
                    if st.button(btn_label, key=f"save_{r['symbol']}"):
                        if already_saved:
                            remove_pick(r["symbol"])
                        else:
                            save_pick(r["symbol"], wl_industries.get(r["symbol"], "Misc"))
                        st.rerun()

        st.divider()

    # Score charts
    st.markdown('<div class="section-header">Score Breakdown</div>', unsafe_allow_html=True)
    df_scores = pd.DataFrame([{
        "Symbol": r["symbol"], "Fundamentals": r["fund_score"],
        "Technicals": r["tech_score"], "Sentiment": r["sent_score"], "Final": r["score"],
    } for r in results]).sort_values("Final", ascending=False)

    col_radar, col_bar = st.columns(2)
    with col_radar:
        fig = go.Figure()
        for r in results[:6]:
            fig.add_trace(go.Scatterpolar(
                r=[r["fund_score"], r["tech_score"], r["sent_score"]],
                theta=["Fundamentals","Technicals","Sentiment"],
                fill="toself", name=r["symbol"],
            ))
        fig.update_layout(
            polar=dict(radialaxis=dict(range=[0,100])), height=380,
            margin=dict(l=20,r=20,t=30,b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=-0.2),
            font=dict(family="Inter"),
        )
        st.plotly_chart(fig, use_container_width=True)
    with col_bar:
        fig2 = px.bar(df_scores, x="Symbol",
                      y=["Fundamentals","Technicals","Sentiment"],
                      barmode="group",
                      color_discrete_sequence=["#667eea","#f59e0b","#10b981"],
                      height=380)
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter"), margin=dict(l=10,r=10,t=30,b=20),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Portfolio":
    st.markdown("# My Portfolio")
    st.markdown("Imported from J.P. Morgan · all figures from your last CSV export.")

    h = load_holdings()
    positions = h.get("positions", [])
    cash = h.get("cash", 0.0)

    if not positions:
        st.info("No positions imported yet. Go to **Settings → Import from Chase** to upload your positions CSV.")
        st.stop()

    # ── Build DataFrame ───────────────────────────────────────────────────────
    rows = []
    for p in positions:
        qty   = float(p.get("quantity", 0) or 0)
        cb    = float(p.get("cost_basis", 0) or 0)
        cur_v = float(p.get("current_value") or (p.get("current_price", cb) * qty) or (cb * qty))
        cost_v = float(p.get("total_cost") or (cb * qty) or cur_v)
        gl_amt = float(p.get("unrealized_gl") or (cur_v - cost_v))
        gl_pct = float(p.get("unrealized_gl_pct") or ((gl_amt / cost_v * 100) if cost_v else 0))
        day_pct = float(p.get("day_change_pct") or 0)
        sector  = (p.get("sector") or "Other").strip() or "Other"
        desc    = (p.get("description") or p["symbol"])[:30]
        rows.append({
            "symbol":   p["symbol"],
            "desc":     desc,
            "sector":   sector,
            "qty":      qty,
            "cost_basis": cb,
            "cost_value": cost_v,
            "cur_value":  cur_v,
            "gl_amt":     gl_amt,
            "gl_pct":     gl_pct,
            "day_pct":    day_pct,
        })

    df = pd.DataFrame(rows)
    total_value    = df["cur_value"].sum() + cash
    total_cost     = df["cost_value"].sum()
    total_gl       = df["gl_amt"].sum()
    total_gl_pct   = (total_gl / total_cost * 100) if total_cost else 0
    winners  = (df["gl_amt"] > 0).sum()
    losers   = (df["gl_amt"] < 0).sum()

    # ── KPI strip ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    def _kpi(col, label, value, sub="", pos=None):
        color = ""
        if pos is True:  color = "color:#16a34a"
        if pos is False: color = "color:#ef4444"
        col.markdown(f"""<div class="metric-card">
          <div class="metric-label">{label}</div>
          <div class="metric-value" style="{color}">{value}</div>
          <div class="metric-sub">{sub}</div></div>""", unsafe_allow_html=True)

    _kpi(k1, "Portfolio Value",  f"${total_value:,.0f}", f"incl. ${cash:,.0f} cash")
    _kpi(k2, "Invested Cost",    f"${total_cost:,.0f}",  f"{len(df)} positions")
    _kpi(k3, "Unrealized G/L",   f"${total_gl:+,.0f}",   f"{total_gl_pct:+.1f}% total return", pos=(total_gl >= 0))
    _kpi(k4, "Winners / Losers", f"{winners} / {losers}", f"{winners/(winners+losers)*100:.0f}% win rate" if (winners+losers) else "")
    _kpi(k5, "Best Today",
         f"+{df['day_pct'].max():.1f}%  {df.loc[df['day_pct'].idxmax(),'symbol']}",
         f"worst: {df['day_pct'].min():.1f}%  {df.loc[df['day_pct'].idxmin(),'symbol']}",
         pos=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 1: Sector Donut + Treemap ─────────────────────────────────────────
    chart_col1, chart_col2 = st.columns([1, 1.3])

    with chart_col1:
        st.markdown('<div class="section-header">Sector Allocation</div>', unsafe_allow_html=True)
        by_sector = df.groupby("sector")["cur_value"].sum().reset_index()
        by_sector.columns = ["sector", "value"]
        by_sector = by_sector.sort_values("value", ascending=False)

        SECTOR_COLORS = [
            "#6366f1","#8b5cf6","#a78bfa","#c4b5fd",
            "#3b82f6","#60a5fa","#93c5fd","#bfdbfe",
            "#10b981","#34d399","#6ee7b7","#a7f3d0",
            "#f59e0b","#fbbf24","#fcd34d",
        ]

        fig_donut = go.Figure(go.Pie(
            labels=by_sector["sector"],
            values=by_sector["value"],
            hole=0.55,
            marker_colors=SECTOR_COLORS[:len(by_sector)],
            textinfo="label+percent",
            textfont_size=11,
            hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<br>%{percent}<extra></extra>",
        ))
        fig_donut.add_annotation(
            text=f"<b>${total_value - cash:,.0f}</b><br><span style='font-size:10px'>Equities</span>",
            x=0.5, y=0.5, showarrow=False, font_size=14, align="center",
        )
        fig_donut.update_layout(
            showlegend=True,
            legend=dict(orientation="v", x=1.02, y=0.5, font_size=11),
            margin=dict(l=10, r=10, t=10, b=10),
            height=360,
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})

    with chart_col2:
        st.markdown('<div class="section-header">Holdings Treemap</div>', unsafe_allow_html=True)
        df_tm = df.copy()
        df_tm["pct"] = df_tm["cur_value"] / df_tm["cur_value"].sum() * 100
        df_tm["label"] = df_tm["symbol"] + "<br>" + df_tm["pct"].map(lambda x: f"{x:.1f}%")
        df_tm["color_val"] = df_tm["gl_pct"].clip(-30, 30)

        fig_tree = go.Figure(go.Treemap(
            ids=df_tm["symbol"],
            labels=df_tm["label"],
            parents=[""] * len(df_tm),
            values=df_tm["cur_value"],
            customdata=df_tm[["symbol","cur_value","gl_pct","sector"]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Value: $%{customdata[1]:,.0f}<br>"
                "G/L: %{customdata[2]:+.1f}%<br>"
                "Sector: %{customdata[3]}<extra></extra>"
            ),
            marker=dict(
                colors=df_tm["color_val"],
                colorscale=[[0,"#ef4444"],[0.5,"#f3f4f6"],[1,"#16a34a"]],
                cmid=0,
                showscale=True,
                colorbar=dict(
                    title="G/L %", thickness=12, len=0.8,
                    tickfont_size=10,
                ),
            ),
            textfont_size=12,
        ))
        fig_tree.update_layout(
            margin=dict(l=5, r=5, t=5, b=5),
            height=360,
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_tree, use_container_width=True, config={"displayModeBar": False})

    # ── Row 2: P&L Waterfall ──────────────────────────────────────────────────
    st.markdown('<div class="section-header">Unrealized Profit & Loss by Position</div>', unsafe_allow_html=True)

    df_pl = df.sort_values("gl_amt", ascending=True).copy()
    colors = ["#16a34a" if v >= 0 else "#ef4444" for v in df_pl["gl_amt"]]

    fig_pl = go.Figure()
    fig_pl.add_trace(go.Bar(
        x=df_pl["symbol"],
        y=df_pl["gl_amt"],
        marker_color=colors,
        text=df_pl["gl_pct"].map(lambda v: f"{v:+.1f}%"),
        textposition="outside",
        textfont_size=10,
        customdata=df_pl[["desc","gl_amt","gl_pct","cur_value","cost_value"]].values,
        hovertemplate=(
            "<b>%{x}</b>  %{customdata[0]}<br>"
            "G/L: $%{customdata[1]:,.0f}  (%{customdata[2]:+.1f}%)<br>"
            "Market value: $%{customdata[3]:,.0f}<br>"
            "Cost: $%{customdata[4]:,.0f}<extra></extra>"
        ),
    ))
    # Zero line
    fig_pl.add_hline(y=0, line_color="#6b7280", line_width=1)
    fig_pl.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickangle=-45, tickfont_size=10, showgrid=False),
        yaxis=dict(
            title="Unrealized G/L ($)",
            tickprefix="$", tickformat=",.0f",
            gridcolor="#f3f4f6", zerolinecolor="#d1d5db",
        ),
        bargap=0.25,
    )
    st.plotly_chart(fig_pl, use_container_width=True, config={"displayModeBar": False})

    # ── Row 3: Sector P&L + Today's movers ───────────────────────────────────
    row3a, row3b = st.columns([1, 1])

    with row3a:
        st.markdown('<div class="section-header">P&L by Sector</div>', unsafe_allow_html=True)
        by_sec_pl = df.groupby("sector").agg(
            gl_amt=("gl_amt","sum"),
            gl_pct=("gl_pct","mean"),
            count=("symbol","count"),
        ).reset_index().sort_values("gl_amt")

        colors_sec = ["#16a34a" if v >= 0 else "#ef4444" for v in by_sec_pl["gl_amt"]]
        fig_sec = go.Figure(go.Bar(
            x=by_sec_pl["gl_amt"],
            y=by_sec_pl["sector"],
            orientation="h",
            marker_color=colors_sec,
            text=by_sec_pl["gl_amt"].map(lambda v: f"${v:+,.0f}"),
            textposition="auto",
            textfont_size=11,
            hovertemplate="<b>%{y}</b><br>G/L: $%{x:,.0f}<extra></extra>",
        ))
        fig_sec.update_layout(
            height=300, margin=dict(l=10,r=10,t=10,b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(tickprefix="$", tickformat=",.0f", gridcolor="#f3f4f6"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_sec, use_container_width=True, config={"displayModeBar": False})

    with row3b:
        st.markdown('<div class="section-header">Today\'s Movers</div>', unsafe_allow_html=True)
        df_day = df[df["day_pct"] != 0].sort_values("day_pct", key=abs, ascending=False).head(20)
        if df_day.empty:
            st.caption("Day change data not available in this import.")
        else:
            colors_day = ["#16a34a" if v >= 0 else "#ef4444" for v in df_day["day_pct"]]
            fig_day = go.Figure(go.Bar(
                x=df_day["day_pct"],
                y=df_day["symbol"],
                orientation="h",
                marker_color=colors_day,
                text=df_day["day_pct"].map(lambda v: f"{v:+.2f}%"),
                textposition="auto",
                textfont_size=11,
                hovertemplate="<b>%{y}</b><br>Day change: %{x:+.2f}%<extra></extra>",
            ))
            fig_day.add_vline(x=0, line_color="#6b7280", line_width=1)
            fig_day.update_layout(
                height=300, margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(ticksuffix="%", gridcolor="#f3f4f6"),
                yaxis=dict(showgrid=False, autorange="reversed"),
            )
            st.plotly_chart(fig_day, use_container_width=True, config={"displayModeBar": False})

    # ── Full holdings table ───────────────────────────────────────────────────
    st.markdown('<div class="section-header">All Positions</div>', unsafe_allow_html=True)
    display_df = df[["symbol","desc","sector","qty","cost_basis","cost_value","cur_value","gl_amt","gl_pct","day_pct"]].copy()
    display_df.columns = ["Ticker","Description","Sector","Qty","Cost/sh ($)","Cost Total ($)","Market Value ($)","G/L ($)","G/L (%)","Day (%)"]
    display_df = display_df.sort_values("Market Value ($)", ascending=False)

    def _color_val(val):
        if isinstance(val, (int, float)):
            if val > 0: return "color: #16a34a"
            if val < 0: return "color: #ef4444"
        return ""

    styled = (display_df.style
        .format({
            "Qty": "{:g}",
            "Cost/sh ($)": "${:,.2f}",
            "Cost Total ($)": "${:,.0f}",
            "Market Value ($)": "${:,.0f}",
            "G/L ($)": "${:+,.0f}",
            "G/L (%)": "{:+.1f}%",
            "Day (%)": "{:+.2f}%",
        })
        .applymap(_color_val, subset=["G/L ($)","G/L (%)","Day (%)"])
        .set_properties(**{"font-size": "12px"})
    )
    st.dataframe(styled, use_container_width=True, height=500)


# ══════════════════════════════════════════════════════════════════════════════
# MARKET SCAN
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Market Scan":
    st.markdown("# Market Scan")
    st.markdown("Two-pass S&P 500 scan — cheap fundamentals+technicals across all ~500 tickers, "
                "then full scoring (incl. sentiment) on the top shortlist only.")

    from scripts.market_scan import scan_market

    col_a, col_b = st.columns([1, 3])
    with col_a:
        shortlist_n = st.number_input("Shortlist size", min_value=5, max_value=50, value=25, step=5)
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True)
        run_scan = st.button("🔍  Run Market Scan")

    if run_scan:
        with st.spinner("Scanning S&P 500… ~3 minutes"):
            progress = st.empty()
            def _cb(msg): progress.caption(msg)
            full_results, pass1_results, regime = scan_market(shortlist_size=int(shortlist_n), status_cb=_cb)
            progress.empty()
        st.session_state["scan_full"] = full_results
        st.session_state["scan_pass1"] = pass1_results
        st.session_state["scan_regime"] = regime
        st.success(f"Scanned {len(pass1_results)} tickers — top {len(full_results)} fully scored.")

    scan_full  = st.session_state.get("scan_full")
    scan_pass1 = st.session_state.get("scan_pass1")
    scan_regime = st.session_state.get("scan_regime")

    if not scan_full:
        st.info("Click **Run Market Scan** to discover ideas beyond your watchlist.")
    else:
        if scan_regime:
            st.caption(f"Regime: **{scan_regime['label']}** — {scan_regime.get('rationale','')}")
        st.markdown('<div class="section-header">Top Shortlist (fully scored)</div>', unsafe_allow_html=True)
        df_full = pd.DataFrame(scan_full)[[
            "symbol","industry","action","score","current_price","target_price","upside_pct","suggested_quantity"
        ]]
        df_full.columns = ["Symbol","Industry","Action","Score","Price","Target","Upside %","Suggested Qty"]
        st.dataframe(df_full, use_container_width=True, height=420)

        with st.expander(f"Pass 1: all {len(scan_pass1)} tickers (cheap score only)"):
            df_p1 = pd.DataFrame(scan_pass1)[["symbol","industry","fund_score","tech_score","cheap_score"]]
            df_p1.columns = ["Symbol","Industry","Fund","Tech","Cheap Score"]
            st.dataframe(df_p1, use_container_width=True, height=400)


# ══════════════════════════════════════════════════════════════════════════════
# ALERTS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Alerts":
    st.markdown("# Real-Time Alerts")
    st.markdown("Desktop notifications fire when a stock flips to Strong Buy, hits its target, "
                "or makes a big intraday move (≥5%). Runs every 5 min during market hours (9:30–16:00 ET).")

    st.code("python3 scripts/alert_poller.py", language="bash")

    st.markdown('<div class="section-header">Recent Alerts</div>', unsafe_allow_html=True)
    alerts = get_recent_alerts(limit=50)
    if not alerts:
        st.info("No alerts fired yet. Start the poller or use the one-off check below.")
    else:
        df_alerts = pd.DataFrame(alerts)[["fired_at","symbol","alert_type","message"]]
        df_alerts.columns = ["Fired At (UTC)","Symbol","Type","Message"]
        st.dataframe(df_alerts, use_container_width=True, height=400)

    if st.button("⚡ Check triggers now (one-off)"):
        from agents.alerts import check_triggers
        from db.store import log_alert
        results = st.session_state.get("results")
        if not results:
            st.warning("Run an analysis on the Dashboard first.")
        else:
            fired = sum(
                1 for a in check_triggers(results, {})
                if log_alert(a["symbol"], a["type"], a["message"], a["dedup_key"])
            )
            st.success(f"{fired} new alert(s) logged.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SAVED LISTS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Saved Lists":
    st.markdown("# Saved Picks")
    st.markdown("Bookmarked stocks organized by industry.")

    picks = get_saved_picks()

    with st.form("add_pick", clear_on_submit=True):
        ca, cb, cc, cd = st.columns([1.5, 1.5, 2.5, 1])
        with ca: new_sym = st.text_input("Ticker", placeholder="AMZN")
        with cb: new_ind = st.selectbox("Industry", INDUSTRIES)
        with cc: new_note = st.text_input("Note (optional)", placeholder="AI moat play")
        with cd:
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Add")
        if submitted and new_sym:
            save_pick(new_sym.upper(), new_ind, new_note)
            st.rerun()

    if not picks:
        st.info("No saved picks yet. Save stocks from the Dashboard or add them above.")
    else:
        for ind in sorted(set(p["industry"] for p in picks)):
            st.markdown(f'<div class="section-header">{ind}</div>', unsafe_allow_html=True)
            for p in [x for x in picks if x["industry"] == ind]:
                c1, c2, c3 = st.columns([1.5, 4, 1])
                with c1: st.markdown(f"**{p['symbol']}**")
                with c2: st.markdown(f"<small style='color:#6b7280'>{p['note'] or '—'} · {p['saved_at'][:10]}</small>", unsafe_allow_html=True)
                with c3:
                    if st.button("Remove", key=f"rm_{p['symbol']}"):
                        remove_pick(p["symbol"]); st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY
# ══════════════════════════════════════════════════════════════════════════════
elif page == "History":
    st.markdown("# Suggestion History")
    st.markdown("Full log of every scored suggestion.")

    sym_filter = (st.text_input("Filter by symbol", placeholder="AAPL").upper() or None)
    history = get_suggestion_history(symbol=sym_filter, limit=100)

    if not history:
        st.info("No history yet. Run an analysis first.")
    else:
        df = pd.DataFrame(history)
        df["run_at"] = pd.to_datetime(df["run_at"]).dt.strftime("%Y-%m-%d %H:%M")
        df = df[["run_at","symbol","action","score","current_price","target_price","upside_pct","regime","fund_score","tech_score","sent_score"]]
        df.columns = ["Date","Symbol","Action","Score","Entry $","Target $","Upside %","Regime","Fund","Tech","Sent"]

        def _color_action(val):
            palette = {
                "Strong Buy": "background-color:#dcfce7;color:#166534",
                "Buy":        "background-color:#dbeafe;color:#1e40af",
                "Watch":      "background-color:#fef9c3;color:#854d0e",
                "Avoid":      "background-color:#fee2e2;color:#991b1b",
            }
            return palette.get(val, "")

        st.dataframe(df.style.applymap(_color_action, subset=["Action"]),
                     use_container_width=True, height=500)

        if sym_filter and len(df) > 1:
            st.markdown(f'<div class="section-header">Score trend — {sym_filter}</div>', unsafe_allow_html=True)
            fig3 = px.line(df.sort_values("Date"), x="Date", y="Score",
                           markers=True, color_discrete_sequence=["#667eea"])
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               font=dict(family="Inter"), height=300,
                               margin=dict(l=10,r=10,t=20,b=20))
            st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE TRACKER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Performance":
    st.markdown("# Suggestion Performance")
    st.markdown("How have past suggestions done? Compares the entry price at suggestion time to today's price.")

    baselines = get_performance_snapshot()
    if not baselines:
        st.info("No suggestion history yet. Run an analysis first to start tracking.")
    else:
        rows = []
        with st.spinner("Fetching current prices…"):
            for b in baselines:
                try:
                    info = fetch_ticker_info(b["symbol"])
                    now = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
                    entry = b["entry_price"] or 0.0
                    ret_pct = round((now - entry) / entry * 100, 1) if entry else None
                    rows.append({
                        "Symbol":       b["symbol"],
                        "Suggested":    b["run_at"][:10],
                        "Action":       b["action"],
                        "Entry $":      entry,
                        "Now $":        round(now, 2),
                        "Return %":     ret_pct,
                        "Target $":     b["target_price"],
                        "To Target %":  round((b["target_price"] - now) / now * 100, 1) if now else None,
                    })
                except Exception:
                    continue

        if not rows:
            st.info("Could not fetch current prices.")
        else:
            df_perf = pd.DataFrame(rows)

            # Summary KPIs
            winners = sum(1 for r in rows if (r["Return %"] or 0) > 0)
            avg_ret = sum(r["Return %"] or 0 for r in rows) / len(rows)
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.markdown(f"""<div class="metric-card">
                  <div class="metric-label">Stocks tracked</div>
                  <div class="metric-value">{len(rows)}</div></div>""", unsafe_allow_html=True)
            with col_b:
                win_color = "#16a34a" if winners > len(rows)/2 else "#dc2626"
                st.markdown(f"""<div class="metric-card">
                  <div class="metric-label">Winners</div>
                  <div class="metric-value" style="color:{win_color}">{winners}/{len(rows)}</div>
                  <div class="metric-sub">up since suggestion</div></div>""", unsafe_allow_html=True)
            with col_c:
                avg_color = "#16a34a" if avg_ret >= 0 else "#dc2626"
                st.markdown(f"""<div class="metric-card">
                  <div class="metric-label">Avg Return</div>
                  <div class="metric-value" style="color:{avg_color}">{avg_ret:+.1f}%</div>
                  <div class="metric-sub">across all suggestions</div></div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Color-coded table
            def _ret_color(val):
                if val is None: return ""
                return "color:#16a34a;font-weight:600" if val > 0 else "color:#dc2626;font-weight:600"

            st.markdown('<div class="section-header">Return Since Suggestion</div>', unsafe_allow_html=True)
            st.dataframe(
                df_perf.style.applymap(_ret_color, subset=["Return %"]),
                use_container_width=True, height=420,
            )

            # Waterfall chart
            st.markdown('<div class="section-header">Return by Stock</div>', unsafe_allow_html=True)
            df_chart = df_perf.dropna(subset=["Return %"]).sort_values("Return %", ascending=False)
            colors = ["#16a34a" if v >= 0 else "#dc2626" for v in df_chart["Return %"]]
            fig_ret = go.Figure(go.Bar(
                x=df_chart["Symbol"], y=df_chart["Return %"],
                marker_color=colors, text=df_chart["Return %"].apply(lambda x: f"{x:+.1f}%"),
                textposition="outside",
            ))
            fig_ret.add_hline(y=0, line_dash="dot", line_color="#9ca3af")
            fig_ret.update_layout(
                height=350, yaxis_title="Return %",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter"), margin=dict(l=10,r=10,t=20,b=20),
            )
            st.plotly_chart(fig_ret, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Settings":
    st.markdown("# Settings")

    # ── API Key ───────────────────────────────────────────────────────────────
    st.markdown("### 🔑 API Key")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_key:
        st.success("ANTHROPIC_API_KEY is set — sentiment scoring and LLM regime detection are active.")
    else:
        with st.form("api_key_form"):
            key_input = st.text_input("Enter your Anthropic API key", type="password",
                                      placeholder="sk-ant-...")
            if st.form_submit_button("Save to .env"):
                if key_input.startswith("sk-"):
                    env_path = pathlib.Path(__file__).parent.parent / ".env"
                    env_path.write_text(f"ANTHROPIC_API_KEY={key_input}\n")
                    st.success("Saved to .env — restart the app for it to take effect.")
                else:
                    st.error("Key should start with sk-ant-...")

    st.markdown("---")

    # ── Watchlist editor ──────────────────────────────────────────────────────
    st.markdown("### 📋 Watchlist")
    wl = load_watchlist()

    with st.form("add_ticker"):
        ca, cb, cc = st.columns([1.5, 2, 1])
        with ca: new_t = st.text_input("Ticker", placeholder="AMZN")
        with cb: new_i = st.selectbox("Industry", INDUSTRIES)
        with cc:
            st.markdown("<br>", unsafe_allow_html=True)
            add_sub = st.form_submit_button("Add ticker")
        if add_sub and new_t:
            sym = new_t.upper().strip()
            if not any(t["symbol"] == sym for t in wl):
                wl.append({"symbol": sym, "industry": new_i})
                save_watchlist(wl)
                st.success(f"Added {sym}")
                st.rerun()
            else:
                st.warning(f"{sym} already in watchlist.")

    st.markdown(f"**{len(wl)} stocks on watchlist:**")
    for i, t in enumerate(wl):
        c1, c2, c3 = st.columns([1.5, 2.5, 1])
        with c1: st.markdown(f"**{t['symbol']}**")
        with c2: st.markdown(f"<small style='color:#6b7280'>{t['industry']}</small>", unsafe_allow_html=True)
        with c3:
            if st.button("Remove", key=f"wl_rm_{t['symbol']}"):
                wl = [x for x in wl if x["symbol"] != t["symbol"]]
                save_watchlist(wl)
                st.rerun()

    st.markdown("---")

    # ── Chase import (CSV or PDF) ─────────────────────────────────────────────
    st.markdown("### 📥 Import from Chase (J.P. Morgan Self-Directed)")
    st.markdown(
        "Upload either a **CSV** or **PDF** from your Chase account.  \n"
        "**CSV:** Portfolio tab → Download icon (↓) → CSV  \n"
        "**PDF:** Portfolio tab → Print/Save as PDF, or your monthly statement PDF"
    )

    import_tab_csv, import_tab_pdf = st.tabs(["📄 CSV upload", "📑 PDF upload"])

    # ── PDF import ────────────────────────────────────────────────────────────
    with import_tab_pdf:
        pdf_file = st.file_uploader("Upload Chase portfolio or statement PDF", type=["pdf"], key="chase_pdf")
        if pdf_file:
            from data.pdf_import import parse_chase_pdf
            with st.spinner("Parsing PDF…"):
                result = parse_chase_pdf(pdf_file.read())

            if result["warnings"]:
                for w in result["warnings"]:
                    st.warning(w)

            positions = result["positions"]
            cash_val  = result["cash"]

            if not positions:
                st.error("No positions could be extracted. Try the CSV export instead, "
                         "or expand 'Raw table' below to see what was found.")
                if result["raw_table"] is not None:
                    with st.expander("Raw table extracted from PDF"):
                        st.dataframe(result["raw_table"], use_container_width=True)
            else:
                st.markdown("**Preview — positions found in PDF:**")
                st.dataframe(pd.DataFrame(positions), use_container_width=True)
                if cash_val:
                    st.caption(f"Cash / money market detected: **${cash_val:,.2f}**")

                col_p1, col_p2 = st.columns([1, 3])
                with col_p1:
                    pdf_import_cash = st.checkbox("Also import cash balance", value=bool(cash_val), key="pdf_cash_chk")
                with col_p2:
                    pdf_overwrite   = st.checkbox("Replace all existing positions", value=True, key="pdf_ow_chk")

                if st.button("✅  Import PDF holdings", type="primary", key="pdf_import_btn"):
                    h = load_holdings()
                    if pdf_overwrite:
                        h["positions"] = positions
                    else:
                        existing = {p["symbol"]: p for p in h.get("positions", [])}
                        for p in positions:
                            existing[p["symbol"]] = p
                        h["positions"] = list(existing.values())
                    if pdf_import_cash and cash_val:
                        h["cash"] = cash_val
                    save_holdings(h)
                    st.success(
                        f"Imported {len(positions)} position(s)"
                        + (f" + ${cash_val:,.0f} cash" if pdf_import_cash and cash_val else "") + "."
                    )
                    st.rerun()

    # ── CSV import ────────────────────────────────────────────────────────────
    with import_tab_csv:
        uploaded = st.file_uploader("Upload Chase / J.P. Morgan positions CSV", type=["csv"], key="chase_upload")
        if uploaded:
            try:
                raw = pd.read_csv(uploaded)
                # Strip footnote rows (lines starting with a single letter code like P, W, X, A, C)
                if "Asset Class" in raw.columns:
                    raw = raw[raw["Asset Class"].notna() & ~raw["Asset Class"].str.strip().str.match(r"^[A-Z]$")]

                raw.columns = [c.strip() for c in raw.columns]
                cols_lower  = {c.lower(): c for c in raw.columns}

                def _col(*candidates):
                    for c in candidates:
                        if c.lower() in cols_lower:
                            return cols_lower[c.lower()]
                    return None

                def _num(v):
                    try: return float(str(v).replace("$","").replace(",","").replace("%","").strip())
                    except: return None

                # Detect JP Morgan detailed export (has "Asset Class" + "Ticker")
                is_jpm = ("asset class" in cols_lower and "ticker" in cols_lower)

                sym_col   = _col("Ticker", "Symbol", "Security Symbol")
                qty_col   = _col("Quantity", "Shares", "Units")
                price_col = _col("Price", "Current Price")
                val_col   = _col("Value", "Current Value", "Market Value")
                cost_col  = _col("Cost", "Total Cost Basis", "Total Cost", "Cost Basis")
                unit_cost_col = _col("Unit Cost", "Average Cost", "Avg Cost", "Cost Basis/Share", "Cost Per Share")
                gl_amt_col    = _col("Unrealized G/L Amt.", "Unrealized G/L", "Gain/Loss")
                gl_pct_col    = _col("Unrealized Gain/Loss (%)", "Unrealized Gain/Loss%", "Gain/Loss %")
                day_chg_col   = _col("Today's Price Change", "Price Change", "Day Change")
                day_pct_col   = _col("Price Change %", "Day Change %", "Today's Change %")
                sector_col    = _col("Asset Strategy", "Asset Class", "Sector", "Industry")
                desc_col      = _col("Description", "Security Name", "Name")
                div_col       = _col("Dividend Yield")
                inc_col       = _col("Est. Annual Income")
                acq_col       = _col("Acquisition Date")
                asset_cls_col = _col("Asset Class")

                if not sym_col:
                    st.error(f"Could not find a Ticker/Symbol column. Columns found: {list(raw.columns)}")
                    st.stop()

                df = raw.copy()
                df["_sym"] = df[sym_col].astype(str).str.strip().str.upper()

                # Separate cash rows
                if asset_cls_col:
                    cash_mask = df[asset_cls_col].astype(str).str.lower().str.contains("cash|money market", na=False)
                else:
                    cash_mask = df["_sym"].str.contains("CASH|SWEEP|USDPR|QACDS", regex=True, na=False)

                cash_rows = df[cash_mask]
                df = df[~cash_mask]

                # Keep only real tickers
                df = df[df["_sym"].str.match(r"^[A-Z]{1,6}$")]

                # Compute cost basis per share
                def _cost_per_share(row):
                    # Try unit cost first (often 0 in JPM export)
                    if unit_cost_col:
                        v = _num(row.get(unit_cost_col))
                        if v and v > 0: return v
                    # Fall back to total_cost / qty
                    if cost_col and qty_col:
                        tot = _num(row.get(cost_col))
                        qty = _num(row.get(qty_col))
                        if tot and qty and qty > 0:
                            return round(tot / qty, 4)
                    return None

                # Build enriched position rows
                positions = []
                for _, row in df.iterrows():
                    sym = row["_sym"]
                    qty = _num(row.get(qty_col)) if qty_col else None
                    if not sym or not qty or qty <= 0:
                        continue

                    price       = _num(row.get(price_col)) if price_col else None
                    cur_val     = _num(row.get(val_col))   if val_col   else None
                    total_cost  = _num(row.get(cost_col))  if cost_col  else None
                    cost_ps     = _cost_per_share(row)
                    gl_amt      = _num(row.get(gl_amt_col))  if gl_amt_col  else None
                    gl_pct      = _num(row.get(gl_pct_col))  if gl_pct_col  else None
                    day_chg     = _num(row.get(day_chg_col)) if day_chg_col else None
                    day_pct     = _num(row.get(day_pct_col)) if day_pct_col else None
                    sector      = str(row.get(sector_col, "")).strip() if sector_col else ""
                    description = str(row.get(desc_col, "")).strip()  if desc_col  else ""
                    div_yield   = _num(row.get(div_col)) if div_col else None
                    ann_income  = _num(row.get(inc_col)) if inc_col else None
                    acq_date    = str(row.get(acq_col, "")).strip()[:10] if acq_col else ""

                    pos = {
                        "symbol":           sym,
                        "description":      description,
                        "quantity":         qty,
                        "cost_basis":       round(cost_ps, 2) if cost_ps else 0.0,
                        "total_cost":       round(total_cost, 2) if total_cost else None,
                        "current_price":    round(price, 4)    if price    else None,
                        "current_value":    round(cur_val, 2)  if cur_val  else None,
                        "unrealized_gl":    round(gl_amt, 2)   if gl_amt   else None,
                        "unrealized_gl_pct":round(gl_pct, 2)   if gl_pct   else None,
                        "day_change":       round(day_chg, 2)  if day_chg  else None,
                        "day_change_pct":   round(day_pct, 2)  if day_pct  else None,
                        "sector":           sector,
                        "dividend_yield":   round(div_yield, 2) if div_yield else None,
                        "est_annual_income":round(ann_income, 2) if ann_income else None,
                        "acquisition_date": acq_date,
                    }
                    positions.append(pos)

                # Tally cash
                csv_cash = 0.0
                if not cash_rows.empty and val_col:
                    for _, cr in cash_rows.iterrows():
                        v = _num(cr.get(val_col))
                        if v: csv_cash += v

                # ── Preview ───────────────────────────────────────────────────
                st.markdown(f"**{len(positions)} positions found** — preview:")
                preview_cols = ["symbol","description","quantity","cost_basis",
                                "current_price","current_value","unrealized_gl","unrealized_gl_pct",
                                "day_change_pct","sector"]
                preview_df = pd.DataFrame(positions)[[c for c in preview_cols if c in pd.DataFrame(positions).columns]]
                preview_df.columns = [c.replace("_"," ").title() for c in preview_df.columns]
                st.dataframe(preview_df, use_container_width=True, height=350)

                if csv_cash:
                    st.info(f"💵 Cash & money market detected: **${csv_cash:,.2f}**")

                # ── Import options ────────────────────────────────────────────
                ci1, ci2, ci3 = st.columns(3)
                with ci1: import_cash   = st.checkbox("Import cash balance", value=bool(csv_cash), key="csv_cash_chk")
                with ci2: overwrite     = st.checkbox("Replace existing positions", value=True, key="csv_ow_chk")
                with ci3: add_to_wl     = st.checkbox("Also add tickers to watchlist", value=True, key="csv_wl_chk")

                if st.button("✅  Import into Stock Advisor", type="primary", key="csv_import_btn"):
                    h = load_holdings()
                    if overwrite:
                        h["positions"] = positions
                    else:
                        ex = {p["symbol"]: p for p in h.get("positions", [])}
                        for p in positions: ex[p["symbol"]] = p
                        h["positions"] = list(ex.values())
                    if import_cash and csv_cash:
                        h["cash"] = csv_cash
                    save_holdings(h)

                    wl_added = 0
                    if add_to_wl:
                        wl = load_watchlist()
                        existing_syms = {t["symbol"] for t in wl}
                        for p in positions:
                            if p["symbol"] not in existing_syms:
                                # Map JPM sector to our industry labels
                                sector = p.get("sector", "Misc") or "Misc"
                                wl.append({"symbol": p["symbol"], "industry": sector})
                                wl_added += 1
                        if wl_added:
                            save_watchlist(wl)

                    st.success(
                        f"✅ Imported **{len(positions)} positions**"
                        + (f" + **${csv_cash:,.0f}** cash" if import_cash and csv_cash else "")
                        + (f" · added **{wl_added}** new tickers to watchlist" if wl_added else "")
                    )
                    st.rerun()

            except Exception as e:
                st.error(f"Could not parse CSV: {e}")
                st.caption("Make sure it's the positions CSV from J.P. Morgan Self-Directed.")

    st.markdown("---")

    # ── Holdings editor ───────────────────────────────────────────────────────
    st.markdown("### 💼 Holdings")
    h = load_holdings()

    with st.form("update_cash"):
        new_cash = st.number_input("Cash balance ($)", min_value=0.0, value=float(h.get("cash", 0)), step=100.0)
        if st.form_submit_button("Update cash"):
            h["cash"] = new_cash
            save_holdings(h)
            st.success(f"Cash updated to ${new_cash:,.0f}")
            st.rerun()

    st.markdown("**Open positions:**")
    positions = h.get("positions", [])
    if not positions:
        st.caption("No positions yet.")
    else:
        # Build a display DataFrame — use imported broker fields when available
        rows = []
        for pos in positions:
            qty   = pos.get("quantity", 0)
            cb    = pos.get("cost_basis", 0.0)
            cur_p = pos.get("current_price")
            cur_v = pos.get("current_value") or (cur_p * qty if cur_p else None)
            cost_v = pos.get("total_cost") or (cb * qty)
            gl_amt = pos.get("unrealized_gl")
            gl_pct = pos.get("unrealized_gl_pct")
            if gl_amt is None and cur_v and cost_v:
                gl_amt = cur_v - cost_v
            if gl_pct is None and cost_v and gl_amt is not None:
                gl_pct = (gl_amt / cost_v * 100) if cost_v else None
            day_pct = pos.get("day_change_pct")

            def _fmt_gl(v):
                if v is None: return "—"
                color = "#22c55e" if v >= 0 else "#ef4444"
                sign  = "+" if v >= 0 else ""
                return f"<span style='color:{color}'>{sign}{v:,.1f}</span>"

            rows.append({
                "Symbol":     f"**{pos['symbol']}**",
                "Desc":       (pos.get("description") or "")[:28],
                "Qty":        f"{qty:g}",
                "Cost/sh":    f"${cb:,.2f}",
                "Price":      f"${cur_p:,.2f}" if cur_p else "—",
                "Value":      f"${cur_v:,.0f}" if cur_v else "—",
                "G/L $":      _fmt_gl(gl_amt) if gl_amt is not None else "—",
                "G/L %":      _fmt_gl(gl_pct) if gl_pct is not None else "—",
                "Day %":      _fmt_gl(day_pct) if day_pct is not None else "—",
                "Sector":     (pos.get("sector") or "")[:22],
                "_sym":       pos["symbol"],
            })

        df_pos = pd.DataFrame(rows)
        # Render as HTML table for colour support
        display_cols = ["Symbol","Desc","Qty","Cost/sh","Price","Value","G/L $","G/L %","Day %","Sector"]
        html_rows = ""
        for _, r in df_pos.iterrows():
            cells = "".join(f"<td style='padding:4px 8px;white-space:nowrap'>{r[c]}</td>" for c in display_cols)
            html_rows += f"<tr>{cells}</tr>"
        header = "".join(f"<th style='padding:4px 8px;text-align:left;color:#9ca3af;font-weight:600;font-size:12px'>{c}</th>" for c in display_cols)
        st.markdown(
            f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:13px'>"
            f"<thead><tr>{header}</tr></thead><tbody>{html_rows}</tbody></table></div>",
            unsafe_allow_html=True
        )
        st.markdown("<br>", unsafe_allow_html=True)

        # Remove buttons below the table
        rm_cols = st.columns(min(len(positions), 8))
        for i, pos in enumerate(positions):
            with rm_cols[i % len(rm_cols)]:
                if st.button(f"✕ {pos['symbol']}", key=f"pos_rm_{pos['symbol']}", help="Remove position"):
                    h["positions"] = [p for p in positions if p["symbol"] != pos["symbol"]]
                    save_holdings(h)
                    st.rerun()

    with st.form("add_position", clear_on_submit=True):
        st.markdown("**Add position:**")
        pa, pb, pc, pd_ = st.columns([1.5, 1.5, 1.5, 1])
        with pa: p_sym = st.text_input("Ticker", placeholder="AAPL")
        with pb: p_qty = st.number_input("Quantity", min_value=1, value=1)
        with pc: p_cost = st.number_input("Cost basis per share ($)", min_value=0.01, value=100.0)
        with pd_:
            st.markdown("<br>", unsafe_allow_html=True)
            add_pos = st.form_submit_button("Add")
        if add_pos and p_sym:
            sym = p_sym.upper().strip()
            h["positions"] = [p for p in h.get("positions",[]) if p["symbol"] != sym]
            h["positions"].append({"symbol": sym, "quantity": int(p_qty), "cost_basis": float(p_cost)})
            save_holdings(h)
            st.success(f"Added {sym}")
            st.rerun()
