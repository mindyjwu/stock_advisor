"""
Daily Brief page — the five-minute read.

Upload a statement PDF → holdings update → every holding shows a stance
(Bull / Neutral / Bear) and a few fixed if-then price rules. The top of the
page answers the only daily question: did anything hit a level?

All HTML is built as single-line strings: Streamlit turns indented or blank
lines inside st.markdown HTML into code blocks.
"""
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pandas as pd
import streamlit as st

from agents.daily_brief import build_brief, load_plan, mark_done, save_plan
from data.loader import fetch_price_history, fetch_price_history_bulk, fetch_ticker_info

STANCE_STYLE = {
    "Bull":    {"fg": "#127a45", "bg": "#e7f9ef", "bar": "#22a565", "icon": "▲"},
    "Neutral": {"fg": "#52607a", "bg": "#eef1f7", "bar": "#a9b4c8", "icon": "●"},
    "Bear":    {"fg": "#c81e1e", "bg": "#fde8e8", "bar": "#e5484d", "icon": "▼"},
    "No data": {"fg": "#8a94a6", "bg": "#f3f5f9", "bar": "#d7deeb", "icon": "?"},
}
INFO_KEYS = ("shortName", "longName", "sector", "targetMeanPrice", "numberOfAnalystOpinions",
             "recommendationMean", "revenueGrowth", "profitMargins", "forwardPE")

CSS = (
    "<style>"
    ".db-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:.4rem 0 1.1rem}"
    ".db-tile{background:#fff;border:1px solid #e6eaf2;border-radius:16px;padding:1rem 1.15rem}"
    ".db-tile .k{font-size:.68rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#8a94a6}"
    ".db-tile .v{font-size:1.65rem;font-weight:800;color:#0f172a;letter-spacing:-.02em;margin-top:.15rem;font-variant-numeric:tabular-nums}"
    ".db-tile .s{font-size:.78rem;color:#64748b;margin-top:.15rem}"
    ".db-tile.hot{border-color:#f3c0c0;background:#fff8f8}.db-tile.warm{border-color:#f3dfae;background:#fffcf3}"
    ".db-split{display:flex;height:9px;border-radius:99px;overflow:hidden;margin-top:.6rem;background:#eef1f7}"
    ".db-h{font-size:.74rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#52607a;margin:1.3rem 0 .5rem}"
    ".db-act{background:#fff;border:1px solid #e6eaf2;border-left:4px solid #e5484d;border-radius:12px;padding:.7rem 1rem;margin-bottom:.5rem}"
    ".db-act.buy{border-left-color:#3b6fe0}.db-act.near{border-left-color:#e0a11b}"
    ".db-act b{color:#0f172a}.db-act .t{font-size:.92rem;color:#1e293b}.db-act .w{font-size:.76rem;color:#8a94a6;margin-top:.15rem}"
    ".db-calm{background:#f1fbf5;border:1px solid #cdeedb;border-radius:14px;padding:1rem 1.2rem;color:#127a45;font-weight:600}"
    ".db-card{background:#fff;border:1px solid #e6eaf2;border-radius:16px;padding:1rem 1.2rem .85rem;margin-bottom:.7rem}"
    ".db-card.trig{border-color:#f0b4b4;box-shadow:0 0 0 3px #fdecec}"
    ".db-top{display:grid;grid-template-columns:minmax(230px,300px) 1fr;gap:1.4rem;align-items:center}"
    ".db-sym{font-size:1.12rem;font-weight:800;color:#0f172a;letter-spacing:-.01em}"
    ".db-name{font-size:.76rem;color:#8a94a6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:280px}"
    ".db-chip{display:inline-block;border-radius:99px;padding:2px 10px;font-size:.68rem;font-weight:800;letter-spacing:.03em;margin-left:.45rem;vertical-align:2px}"
    ".db-nums{display:flex;gap:1.1rem;margin-top:.45rem;font-size:.76rem;color:#64748b;font-variant-numeric:tabular-nums}"
    ".db-nums b{display:block;font-size:.92rem;color:#0f172a;font-weight:700}"
    ".db-ladder{position:relative;height:64px;margin:0 .5rem}"
    ".db-track{position:absolute;left:0;right:0;top:30px;height:8px;border-radius:99px;background:#eef1f7;overflow:hidden}"
    ".db-zone{position:absolute;top:0;height:100%}"
    ".db-mk{position:absolute;top:24px;width:3px;height:20px;border-radius:2px;transform:translateX(-50%)}"
    ".db-lab{position:absolute;top:47px;transform:translateX(-50%);font-size:.64rem;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}"
    ".db-now{position:absolute;top:0;transform:translateX(-50%);text-align:center;font-size:.7rem;font-weight:800;color:#0f172a;white-space:nowrap;font-variant-numeric:tabular-nums}"
    ".db-now i{display:block;width:12px;height:12px;border-radius:50%;background:#0f172a;border:3px solid #fff;box-shadow:0 0 0 1.5px #0f172a;margin:9px auto 0}"
    ".db-rules{margin-top:.55rem;border-top:1px solid #f0f2f7;padding-top:.5rem}"
    ".db-rule{display:flex;align-items:baseline;gap:.6rem;padding:.22rem 0;font-size:.84rem;color:#1e293b}"
    ".db-tag{flex:none;width:38px;text-align:center;border-radius:6px;font-size:.6rem;font-weight:800;letter-spacing:.06em;padding:2px 0}"
    ".db-tag.sell{background:#fdecec;color:#c81e1e}.db-tag.buy{background:#e8f0fe;color:#1a56db}"
    ".db-st{flex:none;margin-left:auto;border-radius:99px;padding:1px 9px;font-size:.66rem;font-weight:700;white-space:nowrap}"
    ".db-st.waiting{background:#f3f5f9;color:#8a94a6}.db-st.near{background:#fdf3d8;color:#a16207}"
    ".db-st.triggered{background:#e5484d;color:#fff}.db-st.triggered.buy{background:#2f6fe4}"
    ".db-st.cleared,.db-st.blocked{background:#f3f5f9;color:#aab2c0}"
    ".db-rule.off{color:#aab2c0}"
    ".db-card details{margin-top:.35rem}.db-card summary{cursor:pointer;font-size:.74rem;font-weight:700;color:#4f46e5;list-style:none}"
    ".db-card summary::-webkit-details-marker{display:none}"
    ".db-why{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-top:.5rem;font-size:.78rem;color:#475569}"
    ".db-why .hd{font-size:.66rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin:0 0 .25rem}"
    ".db-why ul{margin:0;padding-left:1rem}.db-why li{margin:.1rem 0}"
    ".db-stats{display:flex;flex-wrap:wrap;gap:.4rem .5rem;margin-top:.6rem}"
    ".db-stat{background:#f7f9fc;border-radius:8px;padding:3px 9px;font-size:.7rem;color:#64748b}.db-stat b{color:#0f172a}"
    ".db-note{font-size:.72rem;color:#a16207;background:#fdf8e7;border-radius:8px;padding:4px 10px;margin-top:.45rem;display:inline-block}"
    ".db-foot{font-size:.72rem;color:#8a94a6;margin-top:1.4rem;line-height:1.5}"
    "@media (max-width:900px){.db-tiles{grid-template-columns:repeat(2,1fr)}.db-top{grid-template-columns:1fr}.db-why{grid-template-columns:1fr}}"
    "</style>"
)


# ── data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _market_data(symbols: tuple) -> tuple:
    """One year of daily prices + a slim info dict per symbol. Cached 5 minutes."""
    hist = fetch_price_history_bulk(list(symbols), period="1y")
    missing = [s for s in symbols if s not in hist or len(hist[s]) < 30]

    def _one(sym):
        try:
            return sym, fetch_price_history(sym, period="1y")
        except Exception:
            return sym, None

    def _info(sym):
        try:
            full = fetch_ticker_info(sym) or {}
            return sym, {k: full.get(k) for k in INFO_KEYS}
        except Exception:
            return sym, {}

    with ThreadPoolExecutor(max_workers=16) as ex:
        for sym, df in ex.map(_one, missing):
            if df is not None and len(df):
                hist[sym] = df
        infos = dict(ex.map(_info, symbols))
    return hist, infos, datetime.now().strftime("%-I:%M %p")


def _money(v, signed=False):
    if v is None:
        return "—"
    sign = ("+" if v >= 0 else "−") if signed else ("−" if v < 0 else "")
    return f"{sign}&#36;{abs(v):,.0f}"


def _pct(v, signed=True, digits=1):
    if v is None:
        return "—"
    sign = ("+" if v >= 0 else "−") if signed else ""
    return f"{sign}{abs(v) * 100:.{digits}f}%"


def _esc(text: str) -> str:
    """Escape for HTML and stop Streamlit reading '$…$' as LaTeX."""
    return html.escape(str(text)).replace("$", "&#36;")


# ── HTML builders ─────────────────────────────────────────────────────────────
def _tiles(brief: dict) -> str:
    s = brief["summary"]
    n_t, n_n = len(brief["triggered"]), len(brief["near"])
    counts, vals = s["counts"], s["value_by_stance"]
    total_v = sum(vals.values()) or 1
    split = "".join(
        f'<div title="{k}: {counts[k]} holdings, {vals[k] / total_v:.0%} of your money" '
        f'style="width:{vals[k] / total_v * 100:.1f}%;background:{STANCE_STYLE[k]["bar"]}"></div>'
        for k in ("Bull", "Neutral", "Bear", "No data") if vals[k] > 0)
    day_col = "#127a45" if s["day_change"] >= 0 else "#c81e1e"
    return (
        '<div class="db-tiles">'
        f'<div class="db-tile {"hot" if n_t else ""}"><div class="k">Act today</div>'
        f'<div class="v">{n_t}</div><div class="s">{"rule" if n_t == 1 else "rules"} hit a price</div></div>'
        f'<div class="db-tile {"warm" if n_n else ""}"><div class="k">Getting close</div>'
        f'<div class="v">{n_n}</div><div class="s">within 3% of a level</div></div>'
        f'<div class="db-tile"><div class="k">Bull · Neutral · Bear</div>'
        f'<div class="v">{counts["Bull"]} · {counts["Neutral"]} · {counts["Bear"]}</div>'
        f'<div class="db-split">{split}</div></div>'
        f'<div class="db-tile"><div class="k">Portfolio</div><div class="v">{_money(s["total"])}</div>'
        f'<div class="s" style="color:{day_col};font-weight:700">{_money(s["day_change"], True)} '
        f'({_pct(s["day_pct"], digits=2)}) today</div></div>'
        '</div>'
    )


def _action_row(item: dict, near: bool = False) -> str:
    cls = "near" if near else ("buy" if item["kind"] == "buy" else "")
    dist = "" if not near else f' · {abs(item["distance"]):.1%} away'
    return (
        f'<div class="db-act {cls}"><div class="t"><b>{_esc(item["symbol"])}</b> '
        f'<span style="color:#8a94a6">now &#36;{item["now"]:,.2f}{dist}</span> — {_esc(item["text"])}</div>'
        f'<div class="w">{_esc(item["why"])}</div></div>'
    )


def _ladder(card: dict) -> str:
    px = card["price"]
    marks = [r for r in card["rules"] if r["trigger"] != "deadline" and r["status"] not in ("cleared",)]
    levels = [r["price"] for r in marks] + [px]
    lo, hi = min(levels) * 0.965, max(levels) * 1.035
    span = (hi - lo) or 1

    def pos(v):
        return max(1.5, min(98.5, (v - lo) / span * 100))

    floor = next((r for r in marks if r["id"] == "floor"), None)
    targets = [r for r in marks if r["id"].startswith("target")]
    parts = ['<div class="db-track">']
    if floor:
        parts.append(f'<div class="db-zone" style="left:0;width:{pos(floor["price"]):.1f}%;background:#f9d4d4"></div>')
    if targets:
        first = pos(min(t["price"] for t in targets))
        parts.append(f'<div class="db-zone" style="left:{first:.1f}%;width:{100 - first:.1f}%;background:#cdeedb"></div>')
    parts.append('</div>')
    for r in marks:
        if r["id"] == "floor":
            col, word = "#e5484d", "sell below"
        elif r["kind"] == "buy":
            col, word = "#2f6fe4", "buy at"
        else:
            col, word = "#22a565", "take profit"
        p = pos(r["price"])
        tip = _esc(f'{r["text"]} — {abs(r["distance"]):.1%} from today\'s price')
        parts.append(f'<div class="db-mk" title="{tip}" style="left:{p:.1f}%;background:{col}"></div>')
        parts.append(f'<div class="db-lab" title="{tip}" style="left:{p:.1f}%;color:{col}">'
                     f'{word} &#36;{r["price"]:,.2f}</div>')
    parts.append(f'<div class="db-now" style="left:{pos(px):.1f}%">now &#36;{px:,.2f}<i></i></div>')
    return f'<div class="db-ladder">{"".join(parts)}</div>'


def _rule_row(r: dict) -> str:
    st_ = r["status"]
    if st_ == "triggered":
        label = r["detail"] if r["detail"].startswith("hit ") else "hit today"
    elif st_ == "cleared":
        label = "cleared"
    elif st_ == "blocked":
        label = "paused"
    elif r["trigger"] == "deadline":
        label = r["detail"]
    else:
        label = f'{abs(r["distance"]):.1%} away'
    off = " off" if st_ in ("cleared", "blocked") else ""
    buy = " buy" if r["kind"] == "buy" else ""
    return (
        f'<div class="db-rule{off}" title="{_esc(r["why"])}">'
        f'<span class="db-tag {r["kind"]}">{r["kind"].upper()}</span>'
        f'<span>{_esc(r["text"])}</span><span class="db-st {st_}{buy}">{label}</span></div>'
    )


def _stat(label, value):
    return f'<span class="db-stat">{label} <b>{value}</b></span>'


def _card(card: dict, max_weight: float) -> str:
    sty = STANCE_STYLE[card["stance"]["label"]]
    chip = (f'<span class="db-chip" style="background:{sty["bg"]};color:{sty["fg"]}" '
            f'title="Score {card["stance"]["score"]:+d} on a −100 to +100 scale">'
            f'{sty["icon"]} {card["stance"]["label"].upper()}</span>')
    if not card["has_data"]:
        return (f'<div class="db-card"><span class="db-sym">{_esc(card["symbol"])}</span>{chip}'
                f'<div class="db-name">{_esc(card["name"])} · no live price found, so no rules</div></div>')

    gain_col = "#127a45" if (card["gain"] or 0) >= 0 else "#c81e1e"
    day_col = "#127a45" if card["day_pct"] >= 0 else "#c81e1e"
    ident = (
        f'<div><span class="db-sym">{_esc(card["symbol"])}</span>{chip}'
        f'<div class="db-name">{_esc(card["name"])}</div>'
        '<div class="db-nums">'
        f'<span>Today<b style="color:{day_col}">{_pct(card["day_pct"])}</b></span>'
        f'<span>Worth<b>{_money(card["value"])}</b></span>'
        f'<span>Of portfolio<b>{card["weight"]:.1%}</b></span>'
        f'<span>Your gain<b style="color:{gain_col}">{_pct(card["gain_pct"], digits=0)}</b></span>'
        '</div></div>'
    )
    rules = "".join(_rule_row(r) for r in card["rules"])
    notes = []
    if card["oversized"]:
        has_buy = any(r["kind"] == "buy" for r in card["rules"])
        notes.append(f'This is {card["weight"]:.1%} of your portfolio (your cap is {max_weight:.0%}). '
                     f'Trimming about {_money(card["trim_to_cap"])} brings it back'
                     + ("; its buy rule is paused." if has_buy else "."))
    if card.get("stance_changed_from"):
        notes.append(f'Stance changed from {card["stance_changed_from"]} to {card["stance"]["label"]} '
                     f'— rules were rebuilt on {card["plan_date"]}.')
    if card["stance"]["label"] == "Bear" and card["stats"]["sma200"]:
        notes.append(f'No buying while the trend is down. Look again if it closes above '
                     f'&#36;{card["stats"]["sma200"]:,.2f} (its 200-day average).')
    notes_html = "".join(f'<div><span class="db-note">{n}</span></div>' for n in notes)

    s = card["stats"]
    stats = [
        _stat("52-week range", f'&#36;{s["lo52"]:,.2f} – &#36;{s["hi52"]:,.2f}'),
        _stat("3 months", _pct(s["r3m"], digits=0)),
        _stat("12 months", _pct(s["r12m"], digits=0)),
        _stat("Typical daily swing", _pct(s["atr_pct"], signed=False)),
    ]
    if s["target"] and s["n_analysts"]:
        stats.append(_stat(f'{s["n_analysts"]} analysts\' target', f'&#36;{s["target"]:,.2f} ({_pct(s["upside"], digits=0)})'))
    if s["forward_pe"] and s["forward_pe"] > 0:
        stats.append(_stat("Price ÷ next year's earnings", f'{s["forward_pe"]:.0f}×'))
    if card["lt_share"] is not None:
        stats.append(_stat("Held over a year", f'{card["lt_share"]:.0%} of shares'))
    stats.append(_stat("Rules set", card["plan_date"] or "—"))

    def _lis(items, empty):
        return "".join(f"<li>{_esc(x)}</li>" for x in items) or f"<li>{empty}</li>"

    why = (
        f'<details><summary>Why {card["stance"]["label"].lower()}? ▾</summary>'
        '<div class="db-why">'
        f'<div><div class="hd" style="color:#127a45">Working for it</div><ul>{_lis(card["stance"]["for"], "Nothing stands out")}</ul></div>'
        f'<div><div class="hd" style="color:#c81e1e">Working against it</div><ul>{_lis(card["stance"]["against"], "Nothing stands out")}</ul></div>'
        f'</div><div class="db-stats">{"".join(stats)}</div></details>'
    )
    trig = " trig" if card["n_triggered"] else ""
    return (f'<div class="db-card{trig}"><div class="db-top">{ident}{_ladder(card)}</div>'
            f'<div class="db-rules">{rules}</div>{notes_html}{why}</div>')


def _price_table(cards: list) -> pd.DataFrame:
    rows = []
    for c in cards:
        if not c["has_data"]:
            continue
        by = {r["id"]: r for r in c["rules"]}
        deadline = by.get("deadline")
        rows.append({
            "Stock": c["symbol"], "Stance": c["stance"]["label"], "Now": c["price"],
            "Sell below": by["floor"]["price"] if "floor" in by else None,
            "Buy at": by["dip"]["price"] if "dip" in by and by["dip"]["status"] != "blocked" else None,
            "Take profit 1": by["target1"]["price"] if "target1" in by else None,
            "Take profit 2": by["target2"]["price"] if "target2" in by else None,
            "Recover by": deadline["by"] if deadline and deadline["status"] != "cleared" else None,
            "Closest level": (c["closest"] * 100) if c["closest"] is not None else None,
            "Worth": c["value"], "Gain %": (c["gain_pct"] * 100) if c["gain_pct"] is not None else None,
        })
    return pd.DataFrame(rows)


# ── statement upload ──────────────────────────────────────────────────────────
def _upload_box(uid, plan, load_holdings, save_holdings, backup_holdings, log_import, expanded: bool):
    from data.pdf_import import parse_any_pdf

    nonce = st.session_state.get("brief_upload_nonce", 0)
    with st.expander("📄  Upload a new statement (PDF)", expanded=expanded):
        st.caption("Drop your monthly J.P. Morgan statement. Holdings, share counts and costs update; "
                   "your existing price rules stay anchored, new holdings get rules, sold ones disappear.")
        up = st.file_uploader("Statement PDF", type=["pdf"], key=f"brief_pdf_{nonce}",
                              label_visibility="collapsed")
        if not up:
            return
        try:
            res = parse_any_pdf(up.getvalue())
        except Exception as e:
            st.error(f"Could not read that PDF: {e}")
            return
        for w in res["warnings"]:
            st.warning(w)
        positions = res["positions"]
        if not positions:
            st.error("No holdings found in that PDF. Try the positions CSV export in Settings instead.")
            return
        stmt = res.get("statement") or {}
        current = {p["symbol"] for p in load_holdings().get("positions", [])}
        incoming = {p["symbol"] for p in positions}
        added, removed = sorted(incoming - current), sorted(current - incoming)
        bits = [f"**{len(positions)} holdings**"]
        if stmt.get("equity_value"):
            bits.append(f"worth **${stmt['equity_value']:,.0f}**".replace("$", "\\$"))
        if stmt.get("period_end"):
            bits.append(f"as of **{stmt['period_end']}**")
        st.markdown("Found " + ", ".join(bits) + ".")
        if current and (added or removed):
            st.caption((f"New: {', '.join(added)}. " if added else "")
                       + (f"No longer held: {', '.join(removed)}." if removed else ""))
        if st.button("Update my dashboard", type="primary", key="brief_apply"):
            backup = backup_holdings()
            h = load_holdings()
            h["positions"] = positions
            if res.get("cash") is not None:
                h["cash"] = res["cash"]
            save_holdings(h)
            plan["statement"] = res.get("statement")
            save_plan(uid, plan)
            try:
                log_import(source="PDF", filename=getattr(up, "name", "statement.pdf"),
                           n_positions=len(positions), cash=res.get("cash") or 0,
                           mode="replace", backup_path=backup)
            except Exception:
                pass
            _market_data.clear()
            st.session_state["brief_upload_nonce"] = nonce + 1
            st.session_state["brief_flash"] = f"Dashboard updated from {getattr(up, 'name', 'your statement')}."
            st.rerun()


# ── page ──────────────────────────────────────────────────────────────────────
def render(uid: int, load_holdings, save_holdings, backup_holdings, log_import):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Daily Brief")
    st.caption("Five minutes: what hit a price you care about, what is close, and what to leave alone.")

    if st.session_state.get("brief_flash"):
        st.success(st.session_state.pop("brief_flash"))

    plan = load_plan(uid)
    holdings = load_holdings()
    positions = [p for p in holdings.get("positions", []) if p.get("symbol") and (p.get("quantity") or 0) > 0]

    if not positions:
        st.markdown(
            '<div style="background:#fff;border:1.5px dashed #d7deeb;border-radius:18px;padding:2.2rem 2rem;'
            'text-align:center;margin:.8rem 0"><div style="font-size:2.2rem">📄</div>'
            '<div style="font-size:1.05rem;font-weight:800;color:#0f172a">Start with your statement</div>'
            '<div style="font-size:.86rem;color:#8a94a6;max-width:440px;margin:.4rem auto 0;line-height:1.55">'
            'Upload a monthly statement PDF below. Every holding gets a stance and a few simple '
            'if-then price rules, and this page becomes your five-minute daily check.</div></div>',
            unsafe_allow_html=True)
        _upload_box(uid, plan, load_holdings, save_holdings, backup_holdings, log_import, expanded=True)
        return

    symbols = tuple(sorted(p["symbol"] for p in positions))
    with st.spinner("Checking today's prices against your rules…"):
        hist, infos, fetched_at = _market_data(symbols)
        rebuild = st.session_state.pop("brief_rebuild", False)
        brief = build_brief(positions, holdings.get("cash", 0), plan, hist, infos, rebuild=rebuild)
    if brief["plan_changed"]:
        save_plan(uid, plan)

    stmt = plan.get("statement") or {}
    stale = ""
    if stmt.get("period_end"):
        age = (date.today() - date.fromisoformat(stmt["period_end"])).days
        stale = f"Share counts from your statement dated {stmt['period_end']}"
        if age > 35:
            stale += f" ({age} days old — upload the latest to refresh)"
        stale += " · "
    st.caption(f"{stale}{len(positions)} holdings · prices as of {fetched_at} (refresh every 5 min)")

    st.markdown(_tiles(brief), unsafe_allow_html=True)

    # ── 1. Act today ─────────────────────────────────────────────────────────
    st.markdown('<div class="db-h">1 · Act today</div>', unsafe_allow_html=True)
    if not brief["triggered"]:
        st.markdown('<div class="db-calm">Nothing hit a level today. You are done — check back tomorrow.</div>',
                    unsafe_allow_html=True)
    for item in brief["triggered"]:
        left, right = st.columns([9, 1.3], vertical_alignment="center")
        left.markdown(_action_row(item), unsafe_allow_html=True)
        if right.button("Done ✓", key=f"brief_done_{item['symbol']}_{item['id']}",
                        help="I've handled this. Re-anchor this stock's rules at today's price."):
            mark_done(plan, item["symbol"], item["id"], brief["metrics"], brief["stances"], positions)
            save_plan(uid, plan)
            st.rerun()

    # ── 2. Getting close ─────────────────────────────────────────────────────
    if brief["near"]:
        st.markdown('<div class="db-h">2 · Getting close</div>', unsafe_allow_html=True)
        st.markdown("".join(_action_row(x, near=True) for x in brief["near"]), unsafe_allow_html=True)

    oversized = brief["summary"]["oversized"]
    if oversized:
        st.markdown(
            f'<div class="db-note" style="margin-top:.6rem">Size check: {", ".join(oversized)} '
            f'{"is" if len(oversized) == 1 else "are"} above your {plan["settings"]["max_weight"]:.0%} '
            f'per-stock cap.</div>', unsafe_allow_html=True)

    # ── 3. Every holding ─────────────────────────────────────────────────────
    st.markdown(f'<div class="db-h">{3 if brief["near"] else 2} · Your holdings and their rules</div>',
                unsafe_allow_html=True)
    counts = brief["summary"]["counts"]
    f1, f2, f3 = st.columns([2.2, 2.4, 1.6])
    stance_opts = ["All"] + [k for k in ("Bull", "Neutral", "Bear") if counts[k]]
    # st.radio (not segmented_control): AppTest in Streamlit 1.50 cannot rerun a
    # page holding a single-select segmented control.
    stance_pick = f1.radio(
        "Stance", stance_opts, horizontal=True, key="brief_stance",
        format_func=lambda k: f"All ({len(brief['cards'])})" if k == "All" else f"{k} ({counts[k]})")
    show_pick = f2.radio(
        "Show", ["Everything", "Hit or close", "Can buy", "Sell watch"], horizontal=True, key="brief_show")
    view_pick = f3.radio("View", ["Cards", "Price table"], horizontal=True, key="brief_view")
    g1, g2, g3 = st.columns([1.6, 1.6, 1.4])
    sort_pick = g1.selectbox("Sort by", ["Biggest position", "Closest to a level", "Biggest gain",
                                         "Biggest loss", "A to Z"], key="brief_sort")
    query = g2.text_input("Find a stock", placeholder="Ticker or name", key="brief_q").strip().lower()
    min_value = g3.number_input("Hide positions under ($)", min_value=0, step=50,
                                value=int(plan["settings"]["hide_below"]), key="brief_min")
    if min_value != plan["settings"]["hide_below"]:
        plan["settings"]["hide_below"] = float(min_value)
        save_plan(uid, plan)

    cards = brief["cards"]
    if stance_pick and stance_pick != "All":
        cards = [c for c in cards if c["stance"]["label"] == stance_pick]
    if show_pick == "Hit or close":
        cards = [c for c in cards if c["n_triggered"] or c["n_near"]]
    elif show_pick == "Can buy":
        cards = [c for c in cards if any(r["kind"] == "buy" and r["status"] != "blocked" for r in c["rules"])]
    elif show_pick == "Sell watch":
        cards = [c for c in cards if c["stance"]["label"] == "Bear" or c["oversized"]
                 or any(r["kind"] == "sell" and r["status"] in ("near", "triggered") for r in c["rules"])]
    if query:
        cards = [c for c in cards if query in c["symbol"].lower() or query in (c["name"] or "").lower()]
    if min_value:
        cards = [c for c in cards if c["value"] >= min_value]
    keyfn = {
        "Biggest position": lambda c: -c["value"],
        "Closest to a level": lambda c: c["closest"] if c["closest"] is not None else 9,
        "Biggest gain": lambda c: -(c["gain_pct"] if c["gain_pct"] is not None else -9),
        "Biggest loss": lambda c: (c["gain_pct"] if c["gain_pct"] is not None else 9),
        "A to Z": lambda c: c["symbol"],
    }[sort_pick]
    cards = sorted(cards, key=keyfn)

    st.caption(f"Showing {len(cards)} of {len(brief['cards'])}. Hover any marker or rule for the reason behind it.")
    if not cards:
        st.info("No holdings match those filters.")
    elif view_pick == "Price table":
        st.dataframe(
            _price_table(cards), hide_index=True, width="stretch",
            height=min(720, 60 + 35 * len(cards)),
            column_config={
                "Now": st.column_config.NumberColumn(format="$%.2f"),
                "Sell below": st.column_config.NumberColumn(format="$%.2f", help="Close below this → sell half (all, if Bear)"),
                "Buy at": st.column_config.NumberColumn(format="$%.2f", help="Dip to this while above the floor → add"),
                "Take profit 1": st.column_config.NumberColumn(format="$%.2f"),
                "Take profit 2": st.column_config.NumberColumn(format="$%.2f"),
                "Recover by": st.column_config.TextColumn(help="If it hasn't closed above Take profit 1 by this date → sell half"),
                "Closest level": st.column_config.NumberColumn(format="%.1f%%", help="Distance from today's price to the nearest rule"),
                "Worth": st.column_config.NumberColumn(format="$%.0f"),
                "Gain %": st.column_config.NumberColumn(format="%.0f%%"),
            })
    else:
        max_w = plan["settings"]["max_weight"]
        chunk = 12  # a few cards per markdown call keeps reruns snappy
        for i in range(0, len(cards), chunk):
            st.markdown("".join(_card(c, max_w) for c in cards[i:i + chunk]), unsafe_allow_html=True)

    # ── Upload + settings ────────────────────────────────────────────────────
    st.markdown('<div class="db-h">Update</div>', unsafe_allow_html=True)
    _upload_box(uid, plan, load_holdings, save_holdings, backup_holdings, log_import, expanded=False)
    with st.expander("⚙️  How the rules are sized"):
        c1, c2 = st.columns(2)
        budget = c1.number_input("New money per month ($)", min_value=0, step=100,
                                 value=int(plan["settings"]["monthly_budget"]), key="brief_budget",
                                 help="Each buy rule adds a quarter of this.")
        cap = c2.number_input("Largest single position (% of portfolio)", min_value=2, max_value=50, step=1,
                              value=int(round(plan["settings"]["max_weight"] * 100)), key="brief_cap",
                              help="Above this, the page flags the position and pauses its buy rule.")
        if budget != plan["settings"]["monthly_budget"] or abs(cap / 100 - plan["settings"]["max_weight"]) > 1e-9:
            plan["settings"]["monthly_budget"] = float(budget)
            plan["settings"]["max_weight"] = cap / 100
            save_plan(uid, plan)
            st.rerun()
        st.markdown(
            "- **Sell-below floor** sits about 2.5–3 typical daily swings under the price when the rules were set "
            "(tighter for Bear). It only ever moves **up** as a stock rises.\n"
            "- **Take-profit** levels sit above the price; Bull holdings sell less at them, Bear holdings sell more.\n"
            "- **Recover-by** dates appear on Bear holdings and on positions down 15% or more.\n"
            "- **Buy** rules exist only where the trend is up, and add a quarter of your monthly money.")
        if st.button("Rebuild every rule from today's prices", key="brief_rebuild_btn",
                     help="Use sparingly — re-anchoring every day defeats the point of fixed levels."):
            st.session_state["brief_rebuild"] = True
            st.rerun()

    st.markdown(
        '<div class="db-foot">These are mechanical guidelines built from prices, trends and analyst data. '
        'They are not personalised financial advice, they ignore taxes and your wider finances, and nothing '
        'here places an order — you decide and trade in your own brokerage account.</div>',
        unsafe_allow_html=True)
