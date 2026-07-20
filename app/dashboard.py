"""Stock Advisor — Streamlit dashboard."""
import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import math
import html
import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from data.loader import (
    fetch_ticker_info, fetch_price_history, current_portfolio_value,
    load_watchlist as _load_watchlist, load_holdings as _load_holdings,
    save_watchlist as _save_watchlist, save_holdings as _save_holdings,
    load_user_settings as _load_user_settings, save_user_settings as _save_user_settings,
    live_positions as _live_positions,
    backup_holdings as _backup_holdings, restore_holdings as _restore_holdings,
)
from db.store import (
    init_db,
    get_saved_picks as _get_saved_picks, save_pick as _save_pick,
    remove_pick as _remove_pick, get_suggestion_history as _get_suggestion_history,
    get_recent_alerts as _get_recent_alerts,
    get_performance_snapshot as _get_performance_snapshot,
    get_latest_run_suggestions as _get_latest_run_suggestions,
    get_last_scan as _get_last_scan, log_alert as _log_alert,
    record_portfolio_snapshot as _record_portfolio_snapshot,
    get_portfolio_snapshots as _get_portfolio_snapshots,
    record_decision as _record_decision, remove_decision as _remove_decision,
    get_decisions as _get_decisions, get_decision_map as _get_decision_map,
    log_import as _log_import, get_imports as _get_imports,
    get_last_import as _get_last_import,
)
from agents.screener import STYLE_META
from scripts.run_analysis import run_analysis as _run_analysis
from agents.allocator import build_plan, PROFILES
from agents.sell_signals import evaluate_holdings as _evaluate_holdings
from app.auth import require_login, logout
import db.community as _community
from app.config import (
    INDUSTRIES, AI_MODELS, THEME_MAP, PIE_COLORS, ACTION_COLORS,
    POS_COLOR, NEG_COLOR,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS — "clean & airy" design system ────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* ── Canvas: soft off-white so white cards float ── */
  .stApp { background: #f7f9fc; }
  [data-testid="stMain"] .block-container { padding: 2.2rem 2.8rem 4rem; max-width: 1280px; }

  /* ── Typography rhythm ── */
  [data-testid="stMain"] h1 {
    font-size: 1.8rem; font-weight: 800; letter-spacing: -.025em;
    color: #0f172a; padding-bottom: 0;
  }
  [data-testid="stMain"] h1 + [data-testid="stMarkdownContainer"] p,
  [data-testid="stMain"] h1 + p { color: #64748b; }
  [data-testid="stMain"] h2 { font-size: 1.3rem; font-weight: 800; letter-spacing: -.02em; color: #0f172a; }
  [data-testid="stMain"] h3 { font-size: 1.05rem; font-weight: 700; color: #0f172a; }

  /* ── Sidebar shell ── */
  section[data-testid="stSidebar"] {
    background: #0b0e15 !important;
    border-right: 1px solid #171c2a !important;
  }
  section[data-testid="stSidebar"] * { color: #cbd5e1 !important; }

  /* ── Collapse control: always-visible pill inside the sidebar header ── */
  [data-testid="stSidebarCollapseButton"] { opacity: 1 !important; visibility: visible !important; }
  [data-testid="stSidebarCollapseButton"] button {
    background: #1e2438 !important; color: #a5b4fc !important;
    border: 1px solid #2a3350 !important; border-radius: 8px !important;
    opacity: 1 !important;
  }
  [data-testid="stSidebarCollapseButton"] button:hover {
    background: #312e81 !important; color: #c7d2fe !important;
  }
  /* ── Expand control: prominent floating button when collapsed ── */
  [data-testid="stSidebarCollapsedControl"] button,
  [data-testid="stExpandSidebarButton"] button {
    background: linear-gradient(135deg,#6366f1,#8b5cf6) !important;
    color: #fff !important; border: none !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 10px rgba(99,102,241,.4) !important;
  }
  [data-testid="stSidebarCollapsedControl"] button:hover,
  [data-testid="stExpandSidebarButton"] button:hover { opacity: .88 !important; }
  section[data-testid="stSidebar"] .stRadio { display: none !important; }
  section[data-testid="stSidebar"] .stButton > button {
    background: linear-gradient(135deg,#6366f1,#8b5cf6) !important;
    border: none !important; color: #fff !important;
    border-radius: 10px; width: 100%;
    font-weight: 600; font-size: .88rem;
    padding: .55rem 1rem;
    box-shadow: 0 2px 8px rgba(99,102,241,.35);
    transition: opacity .15s;
  }
  section[data-testid="stSidebar"] .stButton > button:hover { opacity: .85; }

  /* ── Card system ── */
  .metric-card {
    background: #fff; border: 1px solid #e8ecf4;
    border-radius: 16px; padding: 1.15rem 1.4rem;
    box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 2px 6px rgba(16,24,40,.04);
    transition: box-shadow .18s ease, transform .18s ease;
  }
  .metric-card:hover {
    box-shadow: 0 4px 14px rgba(16,24,40,.08);
    transform: translateY(-1px);
  }
  .metric-label { font-size:.72rem; font-weight:700; letter-spacing:.09em;
    color:#64748b; text-transform:uppercase; }
  .metric-value { font-size:1.7rem; font-weight:800; color:#0f172a; margin-top:.3rem;
    line-height:1.1; letter-spacing:-.02em; font-variant-numeric: tabular-nums; }
  .metric-sub   { font-size:.8rem; color:#64748b; margin-top:.35rem; }

  /* ── Badges: softer pastels ── */
  .badge { display:inline-block; padding:3px 11px; border-radius:999px;
    font-size:.75rem; font-weight:600; letter-spacing:.01em; }
  .badge-strong-buy { background:#e7f9ef; color:#127a45; }
  .badge-buy        { background:#e8f0fe; color:#1a56db; }
  .badge-watch      { background:#fdf3d8; color:#a16207; }
  .badge-avoid      { background:#fde8e8; color:#c81e1e; }

  /* ── Section headers: airy eyebrow style ── */
  .section-header {
    font-size:.98rem; font-weight:700; color:#0f172a; letter-spacing:-.01em;
    padding-bottom:.55rem; border-bottom:1px solid #edf1f7;
    margin: 1.4rem 0 1rem 0;
  }

  /* ── Score bars ── */
  .score-bar-bg   { background:#eef1f7; border-radius:999px; height:6px; width:100%; }
  .score-bar-fill { height:6px; border-radius:999px; transition: width .3s ease; }

  /* ── Regime banner: glassy indigo ── */
  .regime-banner {
    background: linear-gradient(120deg,#4f46e5 0%,#7c3aed 90%);
    border-radius:16px; padding:1.1rem 1.5rem; color:white;
    box-shadow: 0 6px 20px rgba(99,102,241,.25);
  }
  .regime-key { font-size:1.05rem; font-weight:700; letter-spacing:-.01em; }
  .regime-sub { font-size:.82rem; opacity:.85; }

  /* ── Warning banner ── */
  .warn-banner {
    background:#fffbeb; border:1px solid #fde68a;
    border-radius:12px; padding:.85rem 1.2rem;
    font-size:.9rem; color:#92400e;
  }

  /* ── Main-area buttons: quiet secondary style ── */
  [data-testid="stMain"] .stButton > button {
    background:#fff; color:#334155;
    border:1px solid #dfe5ef; border-radius:10px;
    font-weight:600; font-size:.85rem;
    box-shadow: 0 1px 2px rgba(16,24,40,.04);
    transition: all .15s ease;
  }
  [data-testid="stMain"] .stButton > button:hover {
    border-color:#a5b4fc; color:#4f46e5; background:#f5f6ff;
  }
  [data-testid="stMain"] .stButton > button[kind="primary"] {
    background: linear-gradient(135deg,#6366f1,#8b5cf6);
    color:#fff; border:none; box-shadow: 0 2px 10px rgba(99,102,241,.3);
  }

  /* ── Tabs → floating pills ── */
  [data-testid="stMain"] .stTabs [data-baseweb="tab-list"] {
    gap:.4rem; background:transparent; border-bottom:1px solid #edf1f7;
    padding-bottom:.4rem;
  }
  [data-testid="stMain"] .stTabs [data-baseweb="tab"] {
    background:#fff; border:1px solid #e8ecf4; border-radius:999px;
    padding:.3rem 1.1rem; font-weight:600; color:#64748b;
  }
  [data-testid="stMain"] .stTabs [aria-selected="true"] {
    background:#eef2ff; border-color:#c7d2fe; color:#4f46e5;
  }
  [data-testid="stMain"] .stTabs [data-baseweb="tab-highlight"],
  [data-testid="stMain"] .stTabs [data-baseweb="tab-border"] { display:none; }

  /* ── Horizontal radios → segmented pills ── */
  [data-testid="stMain"] div[role="radiogroup"] { gap:.45rem; }
  [data-testid="stMain"] div[role="radiogroup"] > label {
    background:#fff; border:1px solid #e2e7f0; border-radius:999px;
    padding:.32rem .85rem .32rem .6rem; margin:0;
    box-shadow: 0 1px 2px rgba(16,24,40,.03);
    transition: all .15s ease; cursor:pointer;
  }
  [data-testid="stMain"] div[role="radiogroup"] > label:hover { border-color:#a5b4fc; }
  [data-testid="stMain"] div[role="radiogroup"] > label:has(input:checked) {
    background:#eef2ff; border-color:#818cf8;
    box-shadow: 0 1px 6px rgba(99,102,241,.18);
  }
  [data-testid="stMain"] div[role="radiogroup"] > label:has(input:checked) p { color:#4338ca; font-weight:600; }

  /* ── Expanders as cards ── */
  [data-testid="stMain"] [data-testid="stExpander"] {
    background:#fff; border:1px solid #e8ecf4 !important;
    border-radius:14px !important;
    box-shadow: 0 1px 2px rgba(16,24,40,.03);
    overflow:hidden;
  }
  [data-testid="stMain"] [data-testid="stExpander"] summary { font-weight:600; color:#334155; }
  [data-testid="stMain"] [data-testid="stExpander"] summary:hover { color:#4f46e5; }

  /* ── Inputs ── */
  [data-testid="stMain"] [data-baseweb="input"],
  [data-testid="stMain"] [data-baseweb="select"] > div,
  [data-testid="stMain"] [data-testid="stNumberInputContainer"] {
    border-radius:10px !important;
  }

  /* ── Data tables & code ── */
  thead th { background:#f8fafc !important; }
  .stDataFrame { border-radius:14px; overflow:hidden; border:1px solid #e8ecf4; }
  [data-testid="stMain"] [data-testid="stCode"] pre,
  [data-testid="stMain"] pre {
    border-radius:12px !important; border:1px solid #e8ecf4;
  }

  /* ── Skeleton shimmer ── */
  @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
  .skeleton {
    background: linear-gradient(90deg,#edf1f8 25%,#f9fbfe 50%,#edf1f8 75%);
    background-size: 200% 100%;
    animation: shimmer 1.3s ease-in-out infinite;
    border-radius: 14px; border: 1px solid #eef1f7;
  }

  /* ── Dialog / misc polish ── */
  div[data-testid="stDialog"] > div { border-radius:18px; }
  [data-testid="stMain"] hr { border-color:#edf1f7; }
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-thumb { background:#d7dce7; border-radius:99px; }
  ::-webkit-scrollbar-track { background:transparent; }
  #MainMenu, footer { visibility:hidden; }

  /* ── Accessibility ── */
  /* Visible keyboard focus for interactive elements */
  button:focus-visible, a:focus-visible, summary:focus-visible,
  [role="button"]:focus-visible, [data-baseweb="input"] input:focus-visible,
  [data-baseweb="select"]:focus-within {
    outline: 2px solid #4f46e5 !important;
    outline-offset: 2px !important;
  }
  /* Honor users who ask the OS to minimize motion (main uses transitions + a
     shimmer keyframe); disable animation so nothing pulses or slides for them */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      transition-duration: .01ms !important;
      animation-duration: .01ms !important;
      animation-iteration-count: 1 !important;
      scroll-behavior: auto !important;
    }
  }
</style>
""", unsafe_allow_html=True)

# ── Init ──────────────────────────────────────────────────────────────────────
init_db()
_community.init_community()

# ── Auth gate: everything below runs for exactly one signed-in user ──────────
USER = require_login()
UID = USER["id"]

# User-scoped shims — every data read/write in this file goes through these,
# so each account only ever sees its own watchlist, portfolio, and history.
def load_watchlist():                  return _load_watchlist(UID)
def save_watchlist(tickers):           return _save_watchlist(UID, tickers)
def load_holdings():                   return _load_holdings(UID)
def save_holdings(holdings):
    _save_holdings(UID, holdings)
    _live_holdings_cached.clear()  # fresh import should show immediately
def get_saved_picks():                 return _get_saved_picks(UID)
def save_pick(symbol, industry, note=""): return _save_pick(UID, symbol, industry, note)
def remove_pick(symbol):               return _remove_pick(UID, symbol)
def get_suggestion_history(*a, **k):   return _get_suggestion_history(UID, *a, **k)
def get_recent_alerts(limit=50):       return _get_recent_alerts(UID, limit)
def get_performance_snapshot():        return _get_performance_snapshot(UID)
def record_portfolio_snapshot(**k):    return _record_portfolio_snapshot(UID, **k)
def get_portfolio_snapshots(limit=365):return _get_portfolio_snapshots(UID, limit)
def record_decision(symbol, decision, **k): return _record_decision(UID, symbol, decision, **k)
def remove_decision(symbol):           return _remove_decision(UID, symbol)
def get_decisions():                   return _get_decisions(UID)
def get_decision_map():                return _get_decision_map(UID)
def log_import(**k):                    return _log_import(UID, **k)
def get_imports(limit=20):             return _get_imports(UID, limit)
def get_last_import():                  return _get_last_import(UID)

# Community shims — the signed-in user is always the actor/viewer.
def get_profile(uid=None):              return _community.get_profile(uid if uid is not None else UID)
def update_profile(**k):                return _community.update_profile(UID, **k)
def get_public_sharers():               return _community.get_public_sharers(exclude_user_id=UID)
def get_public_profiles(limit=100):    return _community.get_public_profiles(UID, limit)
def follow(target):                     return _community.follow(UID, target)
def unfollow(target):                   return _community.unfollow(UID, target)
def is_following(target):               return _community.is_following(UID, target)
def get_following_ids():                return _community.get_following_ids(UID)
def follow_counts(uid=None):            return _community.follow_counts(uid if uid is not None else UID)
def community_block(target):            return _community.block(UID, target)
def community_unblock(target):          return _community.unblock(UID, target)
def get_blocked_ids():                  return _community.get_blocked_ids(UID)
def community_report(**k):              return _community.report(UID, **k)
def create_post(body, ticker=None):     return _community.create_post(UID, body, ticker)
def delete_post(post_id):               return _community.delete_post(UID, post_id)
def get_ticker_posts(ticker, limit=60): return _community.get_ticker_posts(ticker, UID, limit)
def get_feed(limit=50):                 return _community.get_feed(UID, limit)
def get_recent_posts(limit=50):        return _community.get_recent_posts(UID, limit)
def like_post(post_id):                 return _community.like_post(UID, post_id)
def unlike_post(post_id):               return _community.unlike_post(UID, post_id)
def publish_watchlist(name, tickers):   return _community.publish_watchlist(UID, name, tickers)
def delete_shared_watchlist(list_id):   return _community.delete_shared_watchlist(UID, list_id)
def get_shared_watchlists(limit=50):    return _community.get_shared_watchlists(UID, limit)

def verified_return_pct(candidate_id):
    """Average % return across a user's 'bought' decisions, priced live.
    This is the leaderboard's verifiable metric — it comes from timestamped
    decision logs, not self-reported numbers. Returns (avg_pct, n) or (None, 0)."""
    rets = []
    for d in _get_decisions(candidate_id):
        if d.get("decision") != "bought":
            continue
        then = _safe_float(d.get("price"))
        if then <= 0:
            continue
        info = fetch_ticker_info(d["symbol"])
        now = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if now > 0:
            rets.append((now - then) / then * 100)
    if not rets:
        return None, 0
    return sum(rets) / len(rets), len(rets)
def backup_holdings():                  return _backup_holdings(UID)
def restore_holdings(path):             return _restore_holdings(UID, path)
def get_latest_run_suggestions():      return _get_latest_run_suggestions(UID)
def get_last_scan():                   return _get_last_scan(UID)
def run_analysis(status_cb=None, **k): return _run_analysis(UID, status_cb=status_cb, **k)
def load_user_settings():              return _load_user_settings(UID)
def save_user_settings(s):             return _save_user_settings(UID, s)

@st.cache_data(ttl=300, show_spinner=False)
def _live_holdings_cached(uid):
    """Holdings with LIVE prices — re-fetched at most every 5 minutes, which
    matches the page auto-refresh. Falls back to imported values per position."""
    h = _load_holdings(uid)
    pos, asof = _live_positions(h.get("positions", []))
    return dict(h, positions=pos), asof.strftime("%-I:%M %p")

def load_live_holdings():
    return _live_holdings_cached(UID)

ACTION_BADGE = {
    "Strong Buy": "badge-strong-buy",
    "Buy":        "badge-buy",
    "Watch":      "badge-watch",
    "Avoid":      "badge-avoid",
}

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
    # Text-on-white colors — all clear WCAG AA as bold small text
    if score >= 75: return "#15803d"
    if score >= 60: return "#2563eb"
    if score >= 45: return "#b45309"
    return "#dc2626"

PLAIN_VERDICT = {
    "Strong Buy": "Very strong signals",
    "Buy":        "Good signals",
    "Watch":      "Wait and see",
    "Avoid":      "Stay away for now",
}

def _empty_state(emoji, title, body, hint=None):
    """Friendly illustrated placeholder card for empty pages/sections.
    Built as one line — indented lines inside st.markdown HTML become code blocks."""
    hint_html = (f'<div style="margin-top:.9rem"><span style="background:#eef2ff;color:#4f46e5;'
                 f'border:1px solid #dfe4ff;border-radius:999px;padding:4px 14px;font-size:.78rem;'
                 f'font-weight:600">{hint}</span></div>') if hint else ""
    return (
        f'<div style="background:#fff;border:1.5px dashed #d7deeb;border-radius:18px;'
        f'padding:2.6rem 2rem;text-align:center;margin:.8rem 0">'
        f'<div style="width:76px;height:76px;border-radius:50%;margin:0 auto 1rem;'
        f'background:radial-gradient(circle at 30% 30%,#eef2ff,#e0e7ff);display:flex;align-items:center;'
        f'justify-content:center;font-size:2.1rem;box-shadow:inset 0 0 0 9px #f5f7ff">{emoji}</div>'
        f'<div style="font-size:1.05rem;font-weight:800;color:#0f172a;letter-spacing:-.01em">{title}</div>'
        f'<div style="font-size:.86rem;color:#8a94a6;max-width:420px;margin:.45rem auto 0;line-height:1.55">{body}</div>'
        f'{hint_html}</div>'
    )

def _fmt_cap(mc):
    try:
        mc = float(mc)
    except (TypeError, ValueError):
        return None
    if mc >= 1e12: return f"${mc/1e12:.1f}T"
    if mc >= 1e9:  return f"${mc/1e9:.1f}B"
    return f"${mc/1e6:.0f}M"

def _cap_label(mc):
    try:
        mc = float(mc)
    except (TypeError, ValueError):
        return None
    if mc >= 2e11: return "mega-cap"
    if mc >= 1e10: return "large-cap"
    if mc >= 2e9:  return "mid-cap"
    return "small-cap"

def _sv(v, kind="num"):
    """Safe stat formatting for tooltips and stat grids."""
    if v is None: return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v) or math.isinf(v): return "—"
    if kind == "pct_frac": return f"{v*100:+.1f}%"
    if kind == "pct":      return f"{v:+.2f}%"
    if kind == "yield":    return f"{(v*100 if v < 1 else v):.2f}%"
    return f"{v:.1f}"

def _stats_lines(_stats):
    cap_txt = _fmt_cap(_stats.get("market_cap"))
    cap_lbl = _cap_label(_stats.get("market_cap"))
    return [
        f"Market cap: {cap_txt or '—'}" + (f" ({cap_lbl})" if cap_lbl else ""),
        f"P/E ratio: {_sv(_stats.get('pe'))}",
        f"Today: {_sv(_stats.get('day_change_pct'), 'pct')}",
        f"52-week change: {_sv(_stats.get('wk52_change'), 'pct_frac')}",
        f"Profit margin: {_sv(_stats.get('profit_margin'), 'pct_frac')}",
        f"Revenue growth: {_sv(_stats.get('rev_growth'), 'pct_frac')}",
        f"Dividend yield: {_sv(_stats.get('div_yield'), 'yield')}",
        f"Beta (volatility vs market): {_sv(_stats.get('beta'))}",
    ]

def _explain_stats(stats):
    """Turn raw statistics into plain-English teaching moments."""
    out = []
    def _f(k):
        try:
            v = float(stats.get(k))
            return None if math.isnan(v) or math.isinf(v) else v
        except (TypeError, ValueError):
            return None
    pe = _f("pe")
    if pe and pe > 0:
        out.append(f"**Price tag:** you pay ~${pe:.0f} for every $1 of yearly profit — "
                   + ("cheap vs the market average (~25)." if pe < 18
                      else "about market average." if pe <= 30
                      else "pricey — big future growth is already baked into the price."))
    mc = _f("market_cap")
    if mc:
        out.append(f"**Size:** {_fmt_cap(mc)} {_cap_label(mc)} — "
                   + ("a giant; steadier, but slower to double." if mc >= 2e11
                      else "an established large company." if mc >= 1e10
                      else "smaller company — more room to grow, bigger swings."))
    beta = _f("beta")
    if beta:
        if beta >= 1.3:
            out.append(f"**Ride:** beta {beta:.1f} — tends to move ~{beta:.1f}% for every 1% the market moves. A wilder ride.")
        elif beta <= 0.8:
            out.append(f"**Ride:** beta {beta:.1f} — calmer than the overall market.")
    wk52 = _f("wk52_change")
    if wk52 is not None:
        out.append(f"**Past year:** {'up' if wk52 >= 0 else 'down'} {abs(wk52)*100:.0f}% — "
                   + ("momentum is real, but you're not early." if wk52 > 0.4
                      else "solid year." if wk52 > 0
                      else "beaten down — could be a bargain or a warning."))
    dy = _f("div_yield")
    if dy and dy > 0:
        dy_pct = dy * 100 if dy < 1 else dy
        out.append(f"**Gets you paid:** ~{dy_pct:.1f}% a year in dividends just for holding it.")
    return out

def _entry_reasons(r):
    """1-2 plain-English reasons about ENTRY TIMING — is now a decent moment
    to buy, or would you be chasing an all-time high?"""
    out = []
    stats = r.get("stats") or {}
    def _f(v):
        try:
            v = float(v)
            return None if math.isnan(v) or math.isinf(v) else v
        except (TypeError, ValueError):
            return None
    px, hi = _f(r.get("current_price")), _f(stats.get("wk52_high"))
    if px and hi and hi > 0:
        dist = px / hi - 1
        if dist >= -0.02:
            out.append("⚠️ at its 52-week high — you'd be buying the top; a pullback could give a better price")
        elif dist >= -0.08:
            out.append(f"{abs(dist)*100:.0f}% below its 52-week high — near the top, not a bargain entry")
        else:
            out.append(f"{abs(dist)*100:.0f}% below its 52-week high — you're not chasing the top")
    pe = _f(stats.get("pe"))
    if pe and 0 < pe < 20:
        out.append(f"P/E {pe:.0f} — cheaper than the market average (~25)")
    up = _f(r.get("upside_pct"))
    if len(out) < 2 and up and up >= 15:
        out.append(f"analyst targets imply +{up:.0f}% from here")
    return out[:2]


def _skeleton_loader(message):
    """Shimmering placeholder shown while an analysis/scan runs."""
    kpis = "".join('<div class="skeleton" style="height:88px;flex:1"></div>' for _ in range(4))
    rows = "".join(
        f'<div class="skeleton" style="height:62px;margin-top:.6rem;opacity:{1 - i*0.18}"></div>'
        for i in range(4)
    )
    return (
        f'<div style="font-size:.85rem;color:#6366f1;font-weight:600;margin:.2rem 0 .7rem">✨ {message}</div>'
        f'<div style="display:flex;gap:1rem">{kpis}</div>{rows}'
    )

def _sparkline(symbol: str, with_axes: bool = False):
    try:
        hist = fetch_price_history(symbol, "1mo")
        close = hist["Close"]
        color = "#16a34a" if close.iloc[-1] >= close.iloc[0] else "#dc2626"
        fig = go.Figure(go.Scatter(
            x=close.index, y=close.values,
            mode="lines", line=dict(color=color, width=1.5),
            hovertemplate="%{x|%b %d}: $%{y:,.2f}<extra></extra>",
        ))
        if with_axes:
            fig.update_layout(
                height=110, margin=dict(l=0, r=4, t=6, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis=dict(visible=True, nticks=3, tickformat="%b %d",
                           tickfont=dict(size=9, color="#94a3b8"), showgrid=False),
                yaxis=dict(visible=True, nticks=3, tickprefix="$",
                           tickfont=dict(size=9, color="#94a3b8"), gridcolor="#f1f5f9"),
            )
        else:
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

def _safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default

# ── Sidebar portfolio snapshot ────────────────────────────────────────────────
def _sidebar_snapshot():
    h, _asof = load_live_holdings()
    positions = h.get("positions", [])
    cash = _safe_float(h.get("cash", 0))

    equity_val = 0.0
    total_cost = 0.0
    total_gl   = 0.0
    day_gl     = 0.0
    has_rich   = False

    for p in positions:
        qty    = _safe_float(p.get("quantity", 0))
        cb     = _safe_float(p.get("cost_basis", 0))
        cur_v  = p.get("current_value")
        cost_v = p.get("total_cost")
        gl_amt = p.get("unrealized_gl")
        day_v  = p.get("day_change")

        if cur_v is not None:
            has_rich = True
            cv  = _safe_float(cur_v)
            ctv = _safe_float(cost_v) if cost_v is not None else (cb * qty)
            gl  = _safe_float(gl_amt) if gl_amt is not None else (cv - ctv)
            equity_val += cv
            total_cost += ctv
            total_gl   += gl
            day_gl     += _safe_float(day_v)
        else:
            equity_val += cb * qty
            total_cost += cb * qty

    total_val    = equity_val + cash
    total_gl_pct = (total_gl / total_cost * 100) if total_cost > 0 else 0.0
    prev_eq      = equity_val - day_gl
    day_gl_pct   = (day_gl / prev_eq * 100) if prev_eq > 0 else 0.0

    # Sanitise everything before returning
    def _s(v): return _safe_float(v)
    return {
        "total_val":    _s(total_val),
        "equity_val":   _s(equity_val),
        "cash":         _s(cash),
        "total_cost":   _s(total_cost),
        "total_gl":     _s(total_gl),
        "total_gl_pct": _s(total_gl_pct),
        "day_gl":       _s(day_gl),
        "day_gl_pct":   _s(day_gl_pct),
        "n_positions":  len(positions),
        "n_watchlist":  len(load_watchlist()),
        "has_rich":     has_rich,
        "asof":         _asof,
    }

PAGES = ["Dashboard", "Stock Advisor", "Scan & Alerts", "Community", "Lists & History", "How It Works", "Settings"]
PAGE_ICONS = {
    "Dashboard":      "◼",
    "Stock Advisor":  "🎯",
    "Scan & Alerts":  "🔭",
    "Community":      "👥",
    "How It Works":   "📖",
    "Lists & History":"📋",
    "Settings":       "⚙️",
}

if "page" not in st.session_state:
    st.session_state["page"] = "Dashboard"
if "ai_model_label" not in st.session_state:
    st.session_state["ai_model_label"] = "Claude Sonnet 4.6 (fast)"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    snap = _sidebar_snapshot()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    current_page = st.session_state.get("page", "Dashboard")

    gl_sign  = "+" if snap["total_gl"] >= 0 else ""
    day_sign = "+" if snap["day_gl"]   >= 0 else ""
    gl_col   = "#4ade80" if snap["total_gl"] >= 0 else "#f87171"
    day_col  = "#4ade80" if snap["day_gl"]   >= 0 else "#f87171"
    ai_dot   = "🟢" if has_key else "🔴"
    model_short = st.session_state.get("ai_model_label","Claude Sonnet 4.6 (fast)").split(" (")[0]
    refresh_time = datetime.now().strftime("%-I:%M %p")

    # One big HTML block for the entire sidebar — no Streamlit widgets except buttons
    st.markdown(f"""
<style>
  /* Remove ALL default padding/gap between sidebar elements */
  section[data-testid="stSidebar"] .stMarkdown {{ margin:0 !important; padding:0 !important; }}
  section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] > div {{
    gap: 0 !important;
  }}
  /* Nav buttons */
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button {{
    background: transparent !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    border-radius: 0 6px 6px 0 !important;
    color: #64748b !important;
    font-size: .82rem !important;
    font-weight: 400 !important;
    padding: .28rem .75rem !important;
    width: 100% !important;
    text-align: left !important;
    margin: 0 !important;
    line-height: 1.35 !important;
    box-shadow: none !important;
    min-height: 0 !important;
    height: auto !important;
  }}
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {{
    background: rgba(99,102,241,.12) !important;
    color: #a5b4fc !important;
    border-left-color: #6366f1 !important;
  }}
  /* Active nav item */
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button.nav-active {{
    background: linear-gradient(90deg,#1e1b4b,#312e81) !important;
    border-left: 3px solid #6366f1 !important;
    color: #a5b4fc !important;
    font-weight: 700 !important;
  }}
  /* Run button */
  section[data-testid="stSidebar"] div[data-testid="stButton"][data-key="run_btn"] > button {{
    background: linear-gradient(135deg,#6366f1,#8b5cf6) !important;
    color: #fff !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    border-left: none !important;
    padding: .35rem .75rem !important;
    font-size: .82rem !important;
    box-shadow: 0 1px 6px rgba(99,102,241,.3) !important;
  }}
  /* Hide selectbox arrow size / shrink */
  section[data-testid="stSidebar"] div[data-testid="stSelectbox"] {{
    margin: 0 !important;
  }}
  section[data-testid="stSidebar"] div[data-testid="stSelectbox"] label {{
    font-size: .7rem !important;
    color: #475569 !important;
    margin-bottom: 1px !important;
  }}
  section[data-testid="stSidebar"] div[data-testid="stSelectbox"] div[data-baseweb="select"] {{
    font-size: .78rem !important;
    min-height: 28px !important;
  }}
</style>

<div style="padding:.5rem .5rem .2rem .5rem">
  <div style="font-size:1rem;font-weight:800;color:#f1f5f9;letter-spacing:-.01em">📈 Stock Advisor</div>
  <div style="font-size:.65rem;color:#475569">AI portfolio advisor</div>
  <div style="display:flex;align-items:center;gap:.45rem;margin-top:.5rem">
    <div style="width:22px;height:22px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);
      display:flex;align-items:center;justify-content:center;font-size:.68rem;font-weight:700;color:#fff !important;
      box-shadow:0 1px 4px rgba(99,102,241,.4)">{(USER['display_name'] or 'U')[0].upper()}</div>
    <span style="font-size:.75rem;color:#cbd5e1;font-weight:600">{USER['display_name']}</span>
    {'<span style="background:#312e81;color:#a5b4fc;border-radius:99px;padding:1px 7px;font-size:.6rem;font-weight:700;letter-spacing:.04em">OWNER</span>' if USER.get('is_owner') else ''}
  </div>
</div>
<div style="border-top:1px solid #1e2438;margin:.3rem 0 .2rem 0"></div>
""", unsafe_allow_html=True)

    # Nav buttons — purely functional st.button, styled by CSS above
    for _p in PAGES:
        _icon = PAGE_ICONS.get(_p, "·")
        _is_active = (_p == current_page)
        _label = f"{'▶ ' if _is_active else ''}{_icon}  {_p}"
        if st.button(_label, key=f"nav_{_p}", width="stretch"):
            st.session_state["page"] = _p
            st.rerun()

    page = st.session_state.get("page", "Dashboard")

    st.markdown('<div style="border-top:1px solid #1e2438;margin:.2rem 0"></div>', unsafe_allow_html=True)

    if st.button("▶  Run Analysis Now", width="stretch", key="run_btn"):
        st.session_state["run_analysis"] = True

    # ── Portfolio stats — compact HTML rows, no st.metric ────────────────
    if snap["has_rich"]:
        st.markdown(f"""
<div style="margin:.4rem 0 0 0;font-size:.7rem">
  <div style="color:#475569;text-transform:uppercase;font-weight:700;letter-spacing:.06em;padding:.35rem .5rem .1rem .5rem">Portfolio</div>

  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Value</span>
    <span style="color:#f1f5f9;font-weight:600">${snap['total_val']:,.0f}</span>
  </div>
  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Equities</span>
    <span style="color:#94a3b8">${snap['equity_val']:,.0f}</span>
  </div>
  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Cash</span>
    <span style="color:#94a3b8">${snap['cash']:,.0f}</span>
  </div>

  <div style="border-top:1px solid #1e2438;margin:.25rem .5rem"></div>

  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Total G/L</span>
    <span style="color:{gl_col};font-weight:600">{gl_sign}${snap['total_gl']:,.0f} ({gl_sign}{snap['total_gl_pct']:.1f}%)</span>
  </div>
  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Today</span>
    <span style="color:{day_col};font-weight:600">{day_sign}${snap['day_gl']:,.0f} ({day_sign}{snap['day_gl_pct']:.2f}%)</span>
  </div>

  <div style="border-top:1px solid #1e2438;margin:.25rem .5rem"></div>

  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Positions</span>
    <span style="color:#94a3b8">{snap['n_positions']}</span>
  </div>
  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#64748b">Watchlist</span>
    <span style="color:#94a3b8">{snap['n_watchlist']}</span>
  </div>

  <div style="border-top:1px solid #1e2438;margin:.25rem .5rem"></div>
  <div style="display:flex;justify-content:space-between;padding:.18rem .5rem">
    <span style="color:#475569">{ai_dot} {model_short}</span>
    <span style="color:#334155">prices {snap['asof']}</span>
  </div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
<div style="margin:.4rem 0;font-size:.7rem;padding:0 .5rem">
  <div style="color:#475569;text-transform:uppercase;font-weight:700;letter-spacing:.06em;padding:.2rem 0 .1rem 0">Portfolio</div>
  <div style="display:flex;justify-content:space-between;padding:.15rem 0">
    <span style="color:#64748b">Value</span><span style="color:#f1f5f9;font-weight:600">${snap['total_val']:,.0f}</span>
  </div>
  <div style="display:flex;justify-content:space-between;padding:.15rem 0">
    <span style="color:#64748b">Positions</span><span style="color:#94a3b8">{snap['n_positions']}</span>
  </div>
  <div style="color:#475569;font-size:.65rem;margin-top:.3rem">Import CSV in Settings for G/L</div>
  <div style="border-top:1px solid #1e2438;margin:.3rem 0"></div>
  <div style="display:flex;justify-content:space-between;padding:.15rem 0">
    <span style="color:#475569">{ai_dot} {model_short}</span><span style="color:#334155">prices {snap['asof']}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── AI model selector ─────────────────────────────────────────────────
    selected_model_label = st.selectbox(
        "AI Model",
        list(AI_MODELS.keys()),
        index=list(AI_MODELS.keys()).index(st.session_state["ai_model_label"]),
        key="model_selector",
        label_visibility="collapsed",
    )
    if selected_model_label != st.session_state["ai_model_label"]:
        st.session_state["ai_model_label"] = selected_model_label
    st.session_state["ai_model_id"] = AI_MODELS[selected_model_label]

    if st.button("↩  Sign out", key="logout_btn", use_container_width=True):
        logout()


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
    # Push selected model into env so agents pick it up
    os.environ["ADVISOR_AI_MODEL"] = st.session_state.get("ai_model_id", "claude-sonnet-4-6")
    _skel = st.empty()
    _skel.markdown(_skeleton_loader("Scoring your watchlist — company health, price trends, and today's news…"),
                   unsafe_allow_html=True)
    progress = st.empty()
    def _cb(msg): progress.caption(msg)
    results, regime = run_analysis(status_cb=_cb)
    progress.empty()
    _skel.empty()
    st.session_state["results"] = results
    st.session_state["regime"] = regime
    st.success("Analysis complete!")


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "Dashboard":  # ── includes Portfolio ──
    st.markdown("# Portfolio Advisor")
    st.markdown("Your watchlist scored, ranked, and sized — you decide when to act.")

    results = st.session_state.get("results")
    regime  = st.session_state.get("regime")

    # After a restart, fall back to the last saved analysis so the Dashboard
    # (incl. portfolio and performance sections) never comes up blank
    if not results:
        _db_rows_dash = get_latest_run_suggestions()
        if _db_rows_dash:
            _wl_ind_dash = {t["symbol"]: t.get("industry", "Misc") for t in load_watchlist()}
            results = [dict(r, industry=_wl_ind_dash.get(r["symbol"], "Misc")) for r in _db_rows_dash]
            _last_dash = max(r["run_at"] for r in _db_rows_dash)[:16].replace("T", " ")
            st.caption(f"Showing your last saved analysis ({_last_dash} UTC) — "
                       "hit ▶ Run Analysis Now for fresh scores.")

    # KPI strip — all about YOUR money (recommendations live in 🎯 Stock Advisor)
    _snap_kpi = _sidebar_snapshot()
    # Checkpoint today's portfolio value for the equity curve (upserts per day,
    # so viewing the dashboard repeatedly just refreshes today's point).
    if _snap_kpi["has_rich"] and _snap_kpi["total_val"] > 0:
        try:
            record_portfolio_snapshot(
                total_value=_snap_kpi["total_val"], equity_value=_snap_kpi["equity_val"],
                cash=_snap_kpi["cash"], total_cost=_snap_kpi["total_cost"],
                total_gl=_snap_kpi["total_gl"], n_positions=_snap_kpi["n_positions"],
            )
        except Exception:
            pass
    _held_syms_dash = {p["symbol"] for p in load_live_holdings()[0].get("positions", [])}
    col1, col2, col3, col4 = st.columns(4)
    _day_col = "#16a34a" if _snap_kpi["day_gl"] >= 0 else "#dc2626"
    _gl_col2 = "#16a34a" if _snap_kpi["total_gl"] >= 0 else "#dc2626"
    with col1:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Portfolio Value</div>
          <div class="metric-value">${_snap_kpi['total_val']:,.0f}</div>
          <div class="metric-sub">live · as of {_snap_kpi['asof']}</div></div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Today</div>
          <div class="metric-value" style="color:{_day_col}">{'+' if _snap_kpi['day_gl']>=0 else ''}${_snap_kpi['day_gl']:,.0f}</div>
          <div class="metric-sub" style="color:{_day_col};font-weight:600">{_snap_kpi['day_gl_pct']:+.2f}% today</div></div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">Total Return</div>
          <div class="metric-value" style="color:{_gl_col2}">{'+' if _snap_kpi['total_gl']>=0 else ''}${_snap_kpi['total_gl']:,.0f}</div>
          <div class="metric-sub" style="color:{_gl_col2};font-weight:600">{_snap_kpi['total_gl_pct']:+.1f}% since you bought</div></div>""", unsafe_allow_html=True)
    with col4:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">You Hold</div>
          <div class="metric-value">{_snap_kpi['n_positions']}</div>
          <div class="metric-sub">stocks · ${_snap_kpi['cash']:,.0f} cash ready</div></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── The AI's checkup on stocks you OWN ────────────────────────────────────
    _held_results = [r for r in (results or []) if r["symbol"] in _held_syms_dash]
    if _held_results:
        st.markdown('<div class="section-header">🩺 Checkup — what the AI thinks of what you own</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:.8rem;color:#8a94a6;margin:-.4rem 0 .6rem 0">Only stocks you hold. '
                    'Looking for what to buy next? That lives in <b>🎯 Stock Advisor</b> in the sidebar.</div>',
                    unsafe_allow_html=True)
        _rec_rows = []
        for _r in sorted(_held_results, key=lambda x: x["score"]):
            _rec_rows.append({
                "Stock":         _r["symbol"],
                "Verdict":       _r["action"],
                "Score /100":    _r["score"],
                "Price now":     _r["current_price"],
                "Could reach":   _r["target_price"],
                "Possible gain": _r["upside_pct"],
                "Why":           (", ".join(_r.get("reasons", [])[:2]) or "—")[:80],
            })
        _rec_df = pd.DataFrame(_rec_rows)
        def _color_action(v):
            c = ACTION_COLORS.get(v, "#475569")
            return f"color:{c};font-weight:700"
        def _color_upside(v):
            try:
                fv = float(str(v).replace("%",""))
                c = POS_COLOR if fv > 0 else NEG_COLOR
                return f"color:{c};font-weight:600"
            except Exception:
                return ""
        st.dataframe(
            _rec_df.style
                .map(_color_action, subset=["Verdict"])
                .map(_color_upside, subset=["Possible gain"])
                .format({"Score /100": "{:.0f}", "Price now": "${:.2f}", "Could reach": "${:.2f}",
                         "Possible gain": "{:+.1f}%"}, na_rep="—"),
            width="stretch",
            height=min(420, 60 + len(_rec_rows) * 38),
        )
        st.caption("Sorted weakest first — the top rows are the holdings worth a second look.")
        st.markdown("<br>", unsafe_allow_html=True)
    elif not results:
        st.markdown(_empty_state(
            "🩺", "No checkup yet",
            "Run your first analysis and the AI will grade every stock you own — "
            "company health, price trend, and news mood — so you know what's solid and what's shaky.",
            "▶ Run Analysis Now — it's in the sidebar, takes ~15 seconds",
        ), unsafe_allow_html=True)

    # ── Portfolio pie charts ──────────────────────────────────────────────────
    _h_pie, _pie_asof = load_live_holdings()
    _positions_pie = _h_pie.get("positions", [])

    # Thematic industry map (ticker → theme) lives in app/config.py
    _THEME_MAP = THEME_MAP

    def _best_val(p):
        cv = _safe_float(p.get("current_value"))
        if cv > 0: return cv
        cp = _safe_float(p.get("current_price"))
        qty = _safe_float(p.get("quantity"))
        if cp > 0: return cp * qty
        return _safe_float(p.get("cost_basis")) * qty

    if _positions_pie:
        _PIE_COLORS = PIE_COLORS

        def _make_donut(df_in, label_col, val_col, center_text):
            df_in = df_in[df_in[val_col] > 0].sort_values(val_col, ascending=False)
            fig = go.Figure(go.Pie(
                labels=df_in[label_col],
                values=df_in[val_col],
                customdata=df_in[label_col],   # carries label into selection points
                hole=0.54,
                marker_colors=_PIE_COLORS[:len(df_in)],
                textinfo="label+percent",
                textfont_size=10,
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f} · %{percent}<br><i>Click to see stocks</i><extra></extra>",
                sort=True, direction="clockwise",
            ))
            fig.add_annotation(
                text=center_text, x=0.5, y=0.5,
                showarrow=False, font_size=12, align="center",
            )
            fig.update_layout(
                height=320, margin=dict(l=10, r=10, t=30, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(
                    orientation="v", x=1.01, y=0.5,
                    font=dict(size=10), bgcolor="rgba(0,0,0,0)",
                    itemsizing="constant",
                ),
            )
            return fig

        # Pie 1 — JPM strategy (US Large Cap / International / etc.)
        _rows1 = [{"sector": (p.get("sector") or "Other"), "value": _best_val(p)} for p in _positions_pie]
        _df1 = pd.DataFrame(_rows1).groupby("sector")["value"].sum().reset_index()
        _total1 = _df1["value"].sum()

        # Pie 2 — Thematic industry
        _rows2 = [{"theme": _THEME_MAP.get(p["symbol"], "Other"), "value": _best_val(p)} for p in _positions_pie]
        _df2 = pd.DataFrame(_rows2).groupby("theme")["value"].sum().reset_index()

        _total2 = _df2["value"].sum()
        # Build lookup: sector/theme → list of positions
        _sec_to_pos  = {}
        for _p in _positions_pie:
            _s = (_p.get("sector") or "Other").strip() or "Other"
            _sec_to_pos.setdefault(_s, []).append(_p)
        _theme_to_pos = {}
        for _p in _positions_pie:
            _t = _THEME_MAP.get(_p["symbol"], "Other")
            _theme_to_pos.setdefault(_t, []).append(_p)

        # ── Init session state for pie click selections ───────────────────────
        if "pie_strat_sel" not in st.session_state:
            st.session_state["pie_strat_sel"] = []
        if "pie_theme_sel" not in st.session_state:
            st.session_state["pie_theme_sel"] = []

        _pc1, _pc2 = st.columns(2)
        with _pc1:
            st.markdown("""
            <div class="section-header">Portfolio by Strategy</div>
            <div style="font-size:.78rem;color:#94a3b8;margin:-0.8rem 0 .5rem 0">
              JPMorgan asset class — <b>click any slice</b> to filter
            </div>""", unsafe_allow_html=True)
            _ev1 = st.plotly_chart(
                _make_donut(_df1, "sector", "value", f"<b>${_total1:,.0f}</b><br><span style='font-size:9px;color:#94a3b8'>equities</span>"),
                use_container_width=True, config={"displayModeBar": False},
                on_select="rerun", selection_mode="points", key="pie_strategy",
            )
            # Sync pie click → multiselect
            try:
                _pts1 = _ev1.selection.points if hasattr(_ev1, "selection") else []
            except Exception:
                _pts1 = []
            if _pts1:
                _lbl1 = (_pts1[0].get("label") or _pts1[0].get("text") or "").strip()
                if _lbl1 and _lbl1 in _sec_to_pos:
                    if _lbl1 not in st.session_state["pie_strat_sel"]:
                        st.session_state["pie_strat_sel"] = [_lbl1]
                    else:
                        # clicking same slice again toggles it off
                        st.session_state["pie_strat_sel"] = []

        with _pc2:
            st.markdown("""
            <div class="section-header">Portfolio by Theme</div>
            <div style="font-size:.78rem;color:#94a3b8;margin:-0.8rem 0 .5rem 0">
              Industry theme (AI, Semis, Fintech…) — <b>click any slice</b> to filter
            </div>""", unsafe_allow_html=True)
            _ev2 = st.plotly_chart(
                _make_donut(_df2, "theme", "value", f"<b>${_total2:,.0f}</b><br><span style='font-size:9px;color:#94a3b8'>equities</span>"),
                use_container_width=True, config={"displayModeBar": False},
                on_select="rerun", selection_mode="points", key="pie_theme",
            )
            try:
                _pts2 = _ev2.selection.points if hasattr(_ev2, "selection") else []
            except Exception:
                _pts2 = []
            if _pts2:
                _lbl2 = (_pts2[0].get("label") or _pts2[0].get("text") or "").strip()
                if _lbl2 and _lbl2 in _theme_to_pos:
                    if _lbl2 not in st.session_state["pie_theme_sel"]:
                        st.session_state["pie_theme_sel"] = [_lbl2]
                    else:
                        st.session_state["pie_theme_sel"] = []

        # ── Multi-select filters (synced with pie clicks) ──────────────────────
        st.markdown('<div class="section-header" style="margin-top:.5rem">Explore Holdings</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:.78rem;color:#94a3b8;margin-bottom:.5rem">Click a pie slice above or pick from the dropdowns below — select multiple to combine</div>', unsafe_allow_html=True)
        _drillcols = st.columns(2)

        with _drillcols[0]:
            # Write session_state key before widget so widget picks it up
            _chosen_strategies = st.multiselect(
                "Filter by JPM Strategy",
                options=sorted(_sec_to_pos.keys()),
                default=st.session_state["pie_strat_sel"],
                key="ms_strategy",
            )
            st.session_state["pie_strat_sel"] = _chosen_strategies

        with _drillcols[1]:
            _chosen_themes = st.multiselect(
                "Filter by Industry Theme",
                options=sorted(_theme_to_pos.keys()),
                default=st.session_state["pie_theme_sel"],
                key="ms_theme",
            )
            st.session_state["pie_theme_sel"] = _chosen_themes

        def _drill_table(matched, group_label, clicked):
            total_val_slice = sum(_best_val(p) for p in matched)
            total_gl_slice  = sum(_safe_float(p.get("unrealized_gl")) for p in matched)
            gl_col_s = "#16a34a" if total_gl_slice >= 0 else "#ef4444"
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);
              border:1px solid #e2e8f0;border-radius:12px;padding:.9rem 1.2rem;margin:.5rem 0 .8rem 0">
              <div style="font-size:.72rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.07em">
                {group_label}
              </div>
              <div style="font-size:1.1rem;font-weight:700;color:#0f172a;margin:.2rem 0">{clicked}</div>
              <div style="display:flex;gap:2rem;margin-top:.3rem;font-size:.83rem">
                <span><b style="color:#0f172a">{len(matched)}</b> <span style="color:#64748b">positions</span></span>
                <span><b style="color:#0f172a">${total_val_slice:,.0f}</b> <span style="color:#64748b">market value</span></span>
                <span><b style="color:{gl_col_s}">{'+' if total_gl_slice>=0 else ''}${total_gl_slice:,.0f}</b> <span style="color:#64748b">unrealized G/L</span></span>
              </div>
            </div>""", unsafe_allow_html=True)
            drill_rows = []
            for _dp in matched:
                drill_rows.append({
                    "Ticker":      _dp["symbol"],
                    "Description": (_dp.get("description") or "")[:32],
                    "Qty":         _dp.get("quantity"),
                    "Price":       _dp.get("current_price"),
                    "Value":       _best_val(_dp),
                    "G/L $":       _dp.get("unrealized_gl"),
                    "G/L %":       _dp.get("unrealized_gl_pct"),
                    "Day %":       _dp.get("day_change_pct"),
                })
            _ddf = pd.DataFrame(drill_rows).sort_values("Value", ascending=False)
            def _gc(v):
                if v is None or (isinstance(v, float) and math.isnan(v)): return ""
                return "color:#16a34a;font-weight:600" if v > 0 else "color:#ef4444;font-weight:600"
            st.dataframe(
                _ddf.style
                    .map(_gc, subset=["G/L $","G/L %","Day %"])
                    .format({"Qty":"{:g}","Price":"${:,.2f}","Value":"${:,.0f}",
                             "G/L $":"${:+,.0f}","G/L %":"{:+.1f}%","Day %":"{:+.2f}%"}, na_rep="—"),
                width="stretch", height=min(350, 60 + len(matched)*38),
            )

        # Merge all selected positions across both filters
        _combined_positions = []
        _combined_labels = []
        for _s in _chosen_strategies:
            for _p in _sec_to_pos.get(_s, []):
                if _p not in _combined_positions:
                    _combined_positions.append(_p)
            _combined_labels.append(_s)
        for _t in _chosen_themes:
            for _p in _theme_to_pos.get(_t, []):
                if _p not in _combined_positions:
                    _combined_positions.append(_p)
            _combined_labels.append(_t)

        if _combined_positions:
            _drill_table(_combined_positions, "Holdings in selected groups", " + ".join(_combined_labels))

    # ── Portfolio section (bottom of Dashboard) ───────────────────────────────
    st.markdown("---")
    st.markdown("## My Portfolio")
    h, _pf_asof = load_live_holdings()
    st.markdown(f"Live prices as of **{_pf_asof}** (refreshes every 5 min) · cost basis from your CSV import.")
    positions = h.get("positions", [])
    cash = h.get("cash", 0.0)

    if not positions:
        st.markdown(_empty_state(
            "🗂️", "Your portfolio is empty",
            "Import the CSV from your broker and this section fills with charts: what you own, "
            "how it's doing, and where your money is concentrated.",
            "Settings → Import from Chase",
        ), unsafe_allow_html=True)
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
        .map(_color_val, subset=["G/L ($)","G/L (%)","Day (%)"])
        .set_properties(**{"font-size": "12px"})
    )
    st.dataframe(styled, width="stretch", height=500)

    # ── Performance report card — filled at end of script, after its def ─────
    _perf_slot = st.container()


# ══════════════════════════════════════════════════════════════════════════════
# STOCK ADVISOR (recommendations + invest-my-cash planner)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Stock Advisor":
    st.markdown("# 🎯 Stock Advisor")
    st.markdown("Top-down: the market's mood → the AI's best picks you don't own yet → a concrete plan for your cash.")

    # ══ Manage what you own: sell / trim / hold / add ═════════════════════════
    st.markdown('<div class="section-header">🔀 Manage your holdings — sell, hold, or buy more</div>', unsafe_allow_html=True)
    st.caption("A review of the stocks you own: when to take profit or cut losses (with a suggested "
               "price and order type), what's fine to hold, and which winners are worth adding to.")
    _sell_positions = load_holdings().get("positions", [])
    if not _sell_positions:
        st.info("No holdings to review yet — import your portfolio in **Settings**.")
    else:
        if st.button("🔀  Review my holdings", key="run_sell_signals"):
            with st.spinner(f"Reviewing your {len(_sell_positions)} holdings…"):
                _ai_scores = {r["symbol"]: r["score"] for r in get_latest_run_suggestions()}
                st.session_state["sell_signals"] = _evaluate_holdings(UID, _ai_scores)
        _sigs = st.session_state.get("sell_signals")
        # Discard results cached before the order-plan/Add feature existed, so a
        # stale session doesn't show sell rows without their suggested price.
        if _sigs and "order_advice" not in _sigs[0]:
            _sigs = None
            st.session_state.pop("sell_signals", None)
        if _sigs is None:
            st.caption("Click above to review each holding. You'll get a suggested price and order "
                       "type for anything to sell or add. Recommendations sharpen after an analysis "
                       "(adds the AI thesis and buy-more signals).")
        else:
            _V_COLOR = {"Sell": "#dc2626", "Trim": "#b45309", "Hold": "#15803d", "Add": "#4f46e5"}
            _V_WORD  = {"Sell": "cut it", "Trim": "take some profit", "Hold": "sit tight", "Add": "buy more"}
            _n_sell = sum(1 for s in _sigs if s["verdict"] in ("Sell", "Trim"))
            _n_add  = sum(1 for s in _sigs if s["verdict"] == "Add")
            _summary = []
            if _n_sell: _summary.append(f"<b>{_n_sell}</b> to sell/trim")
            if _n_add:  _summary.append(f"<b>{_n_add}</b> worth adding to")
            _summary.append(f"the rest fine to hold")
            st.markdown(f"<div style='font-size:.85rem;color:#334155;margin:.2rem 0 .6rem'>"
                        f"{' · '.join(_summary)}.</div>", unsafe_allow_html=True)

            # ── AI second opinion on the EXTREME sells (reads the news) ───────
            _extreme = [s for s in _sigs if s["verdict"] == "Sell"][:8]
            if _extreme:
                if st.button("🧠  Second opinion on urgent sells — read the news & macro context",
                             key="run_sell_review"):
                    with st.spinner(f"Reading recent headlines & catalysts for {len(_extreme)} urgent sells…"):
                        from agents.sell_signals import ai_sell_review_batch
                        os.environ["ADVISOR_AI_MODEL"] = st.session_state.get("ai_model_id", "claude-sonnet-4-6")
                        st.session_state["sell_review"] = ai_sell_review_batch(
                            [{"symbol": s["symbol"], "reasons": s["reasons"], "gl_pct": s.get("gl_pct")}
                             for s in _extreme])
                        if not st.session_state["sell_review"]:
                            st.warning("Couldn't fetch a news review right now (needs the AI key and recent headlines).")
                st.caption("The mechanical model reads charts, not news. This asks the AI whether each urgent "
                           "sell is a true breakdown or has a real catalyst to hold through (e.g. policy tailwinds).")
            _sreview = st.session_state.get("sell_review") or {}

            # Order the list so action items (sell/trim, then add) float to the top
            _order = {"Sell": 0, "Trim": 1, "Add": 2, "Hold": 3}
            for s in sorted(_sigs, key=lambda x: (_order.get(x["verdict"], 4), -x["urgency"])):
                _col = _V_COLOR[s["verdict"]]
                _gl = s.get("gl_pct")
                _glstr = (f"<span style=\"color:{'#15803d' if _gl >= 0 else '#dc2626'};font-weight:600\">"
                          f"{'+' if _gl >= 0 else ''}{_gl:.1f}%</span>") if _gl is not None else "—"
                _bar = min(max(int(s["urgency"]), 0), 100)
                sc1, sc2, sc3 = st.columns([1.4, 1.2, 3.4])
                with sc1:
                    st.markdown(f"**{s['symbol']}**  \n"
                                f"<small style='color:#64748b'>{s['quantity']:g} sh · {_glstr}</small>",
                                unsafe_allow_html=True)
                with sc2:
                    st.markdown(
                        f"<span style='background:{_col};color:#fff;border-radius:99px;"
                        f"padding:2px 12px;font-weight:700;font-size:.8rem'>{s['verdict']}</span>"
                        f"<div style='color:#94a3b8;font-size:.68rem;margin-top:.3rem'>{_V_WORD[s['verdict']]}</div>"
                        + (f"<div style='color:#94a3b8;font-size:.68rem'>urgency {int(s['urgency'])}/100</div>"
                           f"<div class='score-bar-bg' style='margin-top:2px'>"
                           f"<div class='score-bar-fill' style='width:{_bar}%;background:{_col}'></div></div>"
                           if s["verdict"] in ("Sell", "Trim") else ""),
                        unsafe_allow_html=True)
                with sc3:
                    # Concrete order plan: how many shares + suggested price + order type
                    if s["verdict"] in ("Sell", "Trim") and s.get("suggested_sell_qty"):
                        st.markdown(f"<div style='font-size:.82rem;color:#0f172a;font-weight:700'>"
                                    f"Suggested: sell {s['suggested_sell_qty']:g} of {s['quantity']:g} share(s)</div>",
                                    unsafe_allow_html=True)
                        # What you'd actually walk away with (or lose)
                        _rz = s.get("realized_if_sold")
                        _pr = s.get("proceeds_if_sold")
                        if _rz is not None and _pr is not None:
                            _win = _rz >= 0
                            _mc = "#15803d" if _win else "#dc2626"
                            _verb = "lock in a profit of" if _win else "realize a loss of"
                            _line = (f"If you sell {s['suggested_sell_qty']:g} share(s) at ~&#36;{(s.get('limit_price') or s['current_price']):,.2f}: "
                                     f"you'd receive about <b>&#36;{_pr:,.0f}</b> and {_verb} "
                                     f"<b style='color:{_mc}'>{'+' if _win else '−'}&#36;{abs(_rz):,.0f}</b>.")
                            _rem = s["quantity"] - s["suggested_sell_qty"]
                            if _rem > 0:
                                _line += f" You'd still hold {_rem:g} share(s)."
                            st.markdown(f"<div style='font-size:.8rem;color:#334155;background:{'#f0fdf4' if _win else '#fef2f2'};"
                                        f"border-left:3px solid {_mc};border-radius:6px;padding:.35rem .6rem;margin:.2rem 0'>"
                                        f"💵 {_line}</div>", unsafe_allow_html=True)
                    if s.get("order_advice"):
                        _icon = "🟢" if s["verdict"] == "Add" else "🎫"
                        # Two $ signs in one string get parsed as LaTeX and eat the
                        # price — escape $ to an HTML entity and convert **bold**
                        _adv = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s["order_advice"]).replace("$", "&#36;")
                        st.markdown(f"<div style='font-size:.8rem;color:#334155;background:#f8fafc;"
                                    f"border-left:3px solid {_col};border-radius:6px;padding:.35rem .6rem;margin:.2rem 0'>"
                                    f"{_icon} {_adv}</div>", unsafe_allow_html=True)
                    for _r in s["reasons"][:4]:
                        st.markdown(f"<div style='font-size:.8rem;color:#475569'>• {_r}</div>",
                                    unsafe_allow_html=True)
                    # AI news-aware second opinion (extreme sells only)
                    _rev = _sreview.get(s["symbol"])
                    if _rev:
                        _stance = _rev.get("stance", "Mixed")
                        _sc_col = {"Confirm": "#dc2626", "Reconsider": "#15803d", "Mixed": "#b45309"}.get(_stance, "#b45309")
                        _sc_lbl = {"Confirm": "✅ Confirms the sell", "Reconsider": "🤔 Maybe hold through",
                                   "Mixed": "⚖️ Genuinely mixed"}.get(_stance, _stance)
                        _cat = f" <i>Catalyst: {html.escape(_rev['catalyst'])}.</i>" if _rev.get("catalyst") else ""
                        st.markdown(
                            f"<div style='font-size:.8rem;color:#334155;background:#eef2ff;"
                            f"border-left:3px solid {_sc_col};border-radius:6px;padding:.4rem .6rem;margin:.3rem 0'>"
                            f"🧠 <b>AI second opinion — <span style='color:{_sc_col}'>{_sc_lbl}</span>:</b> "
                            f"{html.escape(_rev['rationale']).replace('$','&#36;')}{_cat}</div>",
                            unsafe_allow_html=True)
                    if s["verdict"] == "Hold" and s.get("stop_loss_price"):
                        st.markdown(f"<div style='font-size:.75rem;color:#94a3b8;margin-top:.2rem'>"
                                    f"🛡️ Protective stop-loss idea: exit if it falls to "
                                    f"~${s['stop_loss_price']:,.2f}</div>", unsafe_allow_html=True)
                st.divider()
            st.caption("Suggested prices are starting points, not guarantees. A **limit** order fills only at "
                       "your price or better; a **market** order fills immediately at whatever's available. "
                       "Profit/loss figures are **before taxes and fees** — realized gains on stocks held under "
                       "a year are usually taxed at a higher rate, so your after-tax number will be lower.")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Get scored results: this session first, then the last saved run ──────
    results   = st.session_state.get("results")
    regime    = st.session_state.get("regime")
    data_note = "using the analysis you just ran"
    if not results:
        _db_rows = get_latest_run_suggestions()
        if _db_rows:
            _wl_ind = {t["symbol"]: t.get("industry", "Misc") for t in load_watchlist()}
            results = [dict(r, industry=_wl_ind.get(r["symbol"], "Misc")) for r in _db_rows]
            _last_run = max(r["run_at"] for r in _db_rows)[:16].replace("T", " ")
            data_note = f"using your last saved analysis ({_last_run} UTC) — run a fresh one for up-to-date prices"

    if not results:
        st.markdown(_empty_state(
            "🧮", "I need scores before I can build your plan",
            "One click and the AI grades every stock on your watchlist — then this page turns "
            "any amount of cash into a simple, diversified buy plan.",
        ), unsafe_allow_html=True)
        if st.button("▶  Run Analysis Now", key="invest_run_now"):
            st.session_state["run_analysis"] = True
            st.rerun()
        st.stop()

    holdings, _ = load_live_holdings()
    _avail_cash = _safe_float(holdings.get("cash", 0))
    _held_syms_sa = {p["symbol"] for p in holdings.get("positions", [])}

    # ══ 1) Market weather ═════════════════════════════════════════════════════
    if regime:
        _rw = regime
        _rsrc = ("🎛 your custom mix" if _rw.get("source") == "user"
                 else "🤖 LLM-classified" if _rw.get("source") == "llm" else "📊 VIX rule")
        st.markdown(f"""<div class="regime-banner">
          <div class="regime-key">Market weather: {_rw['label']}</div>
          <div class="regime-sub">
            Today's recipe → Company Health {_rw['fund']*100:.0f}% · Price Trend {_rw['tech']*100:.0f}% ·
            News Mood {_rw['sent']*100:.0f}% &nbsp;|&nbsp; {_rsrc}
          </div>
          <div class="regime-sub" style="margin-top:4px;font-style:italic;">{_rw.get('rationale','')}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # ══ 2) Today's top picks — stocks you DON'T own yet ══════════════════════
    st.markdown('<div class="section-header">💡 Today\'s top picks — stocks you don\'t own yet</div>', unsafe_allow_html=True)

    # Pool = watchlist analysis + last market scan. The watchlist is mostly
    # stocks already held, so the scan is where fresh names come from.
    _picks_sa = [r for r in results
                 if r["symbol"] not in _held_syms_sa and r.get("action") in ("Strong Buy", "Buy")]
    _scan_last_sa = get_last_scan()
    _n_scan_picks = 0
    if _scan_last_sa and _scan_last_sa.get("full"):
        _known_sa = {r["symbol"] for r in _picks_sa} | _held_syms_sa
        _scan_extra_sa = [dict(r, _from_scan=True) for r in _scan_last_sa["full"]
                          if r["symbol"] not in _known_sa
                          and r.get("action") in ("Strong Buy", "Buy")]
        _n_scan_picks = len(_scan_extra_sa)
        _picks_sa += _scan_extra_sa
    _picks_sa.sort(key=lambda x: x.get("score", 0), reverse=True)

    _pool_note = "your watchlist"
    if _n_scan_picks:
        _pool_note += f" + your last market scan ({_n_scan_picks} discoveries, marked 🔭)"
    st.caption(f"Built {data_note}. Pool: {_pool_note}. "
               "Stocks you already hold are on the Dashboard's checkup instead. "
               "Curious how scoring works? See 📖 How It Works.")

    if not _picks_sa:
        st.info("Nothing you don't already own is scoring Buy or better right now — "
                "run a 🔭 Market Scan to search ~500 stocks beyond your watchlist.")
    elif len(_picks_sa) < 5 and not _n_scan_picks:
        st.info("Slim pickings — your watchlist is mostly stocks you already own. "
                "Run a 🔭 Market Scan and its discoveries will appear here automatically.")
    saved_symbols_sa = {p["symbol"] for p in get_saved_picks()}
    _dec_map_sa = get_decision_map()

    try:
        from agents.blurbs import get_blurbs
        _blurbs_sa = get_blurbs([r["symbol"] for r in _picks_sa[:8]])
    except Exception:
        _blurbs_sa = {}

    for r in _picks_sa[:8]:
        action = r["action"]
        score  = r["score"]
        color  = _score_color(score)
        c1, c2, c3, c4, c5, c6 = st.columns([1.3, 1.1, 1.3, 2.3, 1.5, 0.8])
        with c1:
            _day_chg = r.get("day_change_pct")
            _chg_str = ""
            if _day_chg is not None:
                _arrow = "▲" if _day_chg >= 0 else "▼"
                _chg_c = "#16a34a" if _day_chg >= 0 else "#dc2626"
                _chg_str = f"<span style='color:{_chg_c};font-size:.75rem'>{_arrow} {abs(_day_chg):.1f}% today</span>"
            _src_chip = ("<br><span style='background:#e0f2fe;color:#0369a1;border-radius:99px;padding:1px 8px;"
                         "font-size:.68rem;font-weight:600'>🔭 scan find</span>") if r.get("_from_scan") else ""
            st.markdown(f"**{r['symbol']}**  \n<small style='color:#8a94a6'>{r.get('industry','')}</small>  \n{_chg_str}{_src_chip}",
                        unsafe_allow_html=True)
        with c2:
            st.markdown(_badge(action), unsafe_allow_html=True)
            st.markdown(f"<small style='color:#8a94a6'>{PLAIN_VERDICT.get(action, '')}</small>", unsafe_allow_html=True)
            _cf = r.get("confidence")
            if _cf == "aligned":
                st.markdown("<small style='color:#15803d;font-weight:600'>✅ models agree</small>", unsafe_allow_html=True)
            elif _cf == "mixed":
                st.markdown("<small style='color:#b45309;font-weight:600'>⚠️ mixed signals</small>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<span style='font-weight:800;color:{color};font-size:1.2rem'>{score:.0f}</span>"
                        f"<span style='color:#9ca3af;font-size:.8rem'> /100</span>", unsafe_allow_html=True)
            st.markdown(_score_bar(score, color), unsafe_allow_html=True)
            st.markdown(f"<small style='color:#9ca3af'>Health {r['fund_score']:.0f} · Trend {r['tech_score']:.0f} · News {r['sent_score']:.0f}</small>",
                        unsafe_allow_html=True)
        with c4:
            _spark = _sparkline(r["symbol"], with_axes=True)
            if _spark:
                st.plotly_chart(_spark, use_container_width=True, config={"displayModeBar": False},
                                key=f"sa_spark_{r['symbol']}")
        with c5:
            # Single-line pure-HTML block: bare $ signs in markdown text get
            # parsed as LaTeX math and mangle the whole column
            _qty_line = (f'<div style="font-size:.75rem;color:#8a94a6">{r["suggested_quantity"]:g} share(s) suggested</div>'
                         if _safe_float(r.get("suggested_quantity")) > 0
                         else '<div style="font-size:.75rem;color:#8a94a6">size it in the plan below</div>')
            st.markdown(
                f'<div style="font-weight:800;color:#0f172a">${r["current_price"]} '
                f'<span style="font-weight:400;font-size:.75rem;color:#8a94a6">now</span></div>'
                f'<div style="color:#16a34a;font-weight:700">${r["target_price"]} '
                f'<span style="font-weight:400;font-size:.75rem">target (+{r["upside_pct"]}%)</span></div>'
                f'{_qty_line}',
                unsafe_allow_html=True)
        with c6:
            _saved_sa = r["symbol"] in saved_symbols_sa
            if st.button("★" if _saved_sa else "☆ Save", key=f"sa_save_{r['symbol']}"):
                if _saved_sa:
                    remove_pick(r["symbol"])
                else:
                    save_pick(r["symbol"], r.get("industry", "Misc"))
                st.rerun()
            # Track what you actually did — feeds the Performance page
            _dec_sa = _dec_map_sa.get(r["symbol"])
            if st.button("✅ Bought" if _dec_sa == "bought" else "Bought",
                         key=f"sa_bought_{r['symbol']}",
                         help="Mark that you bought this — tracks your real results"):
                if _dec_sa == "bought":
                    remove_decision(r["symbol"])
                else:
                    record_decision(r["symbol"], "bought", action=r.get("action"),
                                    price=_safe_float(r.get("current_price")),
                                    score=_safe_float(r.get("score")))
                st.rerun()
            if st.button("🚫 Passed" if _dec_sa == "passed" else "Passed",
                         key=f"sa_passed_{r['symbol']}",
                         help="Mark that you skipped this one"):
                if _dec_sa == "passed":
                    remove_decision(r["symbol"])
                else:
                    record_decision(r["symbol"], "passed", action=r.get("action"),
                                    price=_safe_float(r.get("current_price")),
                                    score=_safe_float(r.get("score")))
                st.rerun()

        _blurb_row = _blurbs_sa.get(r["symbol"])
        if _blurb_row:
            st.markdown(f"<div style='font-size:.8rem;color:#334155;margin:-.2rem 0 .3rem 0'>"
                        f"<b>🏢 What they do:</b> {_blurb_row}</div>", unsafe_allow_html=True)
        _entry_row = _entry_reasons(r)
        if _entry_row:
            st.markdown(f"<div style='font-size:.8rem;color:#334155;margin:0 0 .3rem 0'>"
                        f"<b>🎯 Why now:</b> {' · '.join(_entry_row)}</div>", unsafe_allow_html=True)

        # Full-width analysis — never squeezed into a narrow column
        with st.expander(f"🔎 Full analysis — {r['symbol']}"):
            st.markdown(
                f"<div style='font-size:.78rem;margin-bottom:.4rem'>"
                f"<span style='color:#6366f1;font-weight:700'>🏥 Company Health</span> <b>{r['fund_score']:.0f}/100</b> &nbsp; "
                f"<span style='color:#f59e0b;font-weight:700'>📈 Price Trend</span> <b>{r['tech_score']:.0f}/100</b> &nbsp; "
                f"<span style='color:#10b981;font-weight:700'>📰 News Mood</span> <b>{r['sent_score']:.0f}/100</b></div>",
                unsafe_allow_html=True)
            _fund_r = [x for x in r.get("reasons", []) if any(k in x.lower() for k in ("p/e","peg","revenue","margin","debt","valuation","profit","growth","capital","forward"))]
            _tech_r = [x for x in r.get("reasons", []) if any(k in x.lower() for k in ("rsi","macd","sma","volume","trend","crossover","oversold","overbought","high","jumpy","steady"))]
            _sent_r = [x for x in r.get("reasons", []) if x not in _fund_r and x not in _tech_r]
            _rc1, _rc2, _rc3 = st.columns(3)
            for _col_r, _ttl, _items in ((_rc1, "🏥 Company Health", _fund_r),
                                         (_rc2, "📈 Price Trend", _tech_r),
                                         (_rc3, "📰 News & More", _sent_r)):
                with _col_r:
                    st.markdown(f"**{_ttl}**")
                    for _rr in (_items or ["—"]):
                        st.markdown(f"<div style='font-size:.8rem;color:#475569;padding:.1rem 0'>• {_rr}</div>",
                                    unsafe_allow_html=True)
            _st_sa = r.get("stats") or {}
            if _st_sa:
                st.markdown("**📐 By the numbers**")
                _sl_sa = _stats_lines(_st_sa)
                _sac1, _sac2 = st.columns(2)
                for _half, _colx in ((_sl_sa[:4], _sac1), (_sl_sa[4:], _sac2)):
                    with _colx:
                        for _line in _half:
                            st.markdown(f"<div style='font-size:.78rem;color:#475569;padding:.05rem 0'>{_line}</div>",
                                        unsafe_allow_html=True)
                _teach_sa = _explain_stats(_st_sa)
                if _teach_sa:
                    st.markdown("**🎓 What that means**")
                    for _tl in _teach_sa:
                        st.markdown(f"- {_tl}")
            _hl_sa = r.get("headlines", [])
            if _hl_sa:
                st.markdown("**Recent news**")
                for _h in _hl_sa[:4]:
                    st.markdown(f"📰 {_h}")
        st.divider()

    # Near-misses: not buys today, but worth keeping an eye on
    _bench_sa = sorted([r for r in results
                        if r["symbol"] not in _held_syms_sa and r.get("action") == "Watch"],
                       key=lambda x: x.get("score", 0), reverse=True)[:8]
    if _bench_sa:
        st.caption("🪑 On the bench (score 45–59, wait and see): "
                   + " · ".join(f"{r['symbol']} ({r['score']:.0f})" for r in _bench_sa))

    # ══ 3) Score ladder — every candidate at a glance ═════════════════════════
    if _picks_sa:
        with st.expander(f"📶 Score ladder — all {len(_picks_sa)} picks at a glance"):
            _lad = sorted(_picks_sa, key=lambda x: x["score"])
            _fig_lad = go.Figure(go.Bar(
                x=[x["score"] for x in _lad],
                y=[x["symbol"] for x in _lad],
                orientation="h",
                marker_color=[_score_color(x["score"]) for x in _lad],
                text=[f"{x['score']:.0f}" for x in _lad],
                textposition="outside", textfont_size=11,
                customdata=[[x["fund_score"], x["tech_score"], x["sent_score"]] for x in _lad],
                hovertemplate="<b>%{y}</b> — %{x:.0f}/100<br>Health %{customdata[0]:.0f} · "
                              "Trend %{customdata[1]:.0f} · News %{customdata[2]:.0f}<extra></extra>",
            ))
            for _thr, _lbl in ((60, "Buy ↑"), (75, "Strong Buy ↑")):
                _fig_lad.add_vline(x=_thr, line_dash="dot", line_color="#c7d2fe", line_width=1.5)
                _fig_lad.add_annotation(x=_thr, y=1.02, yref="paper", text=_lbl, showarrow=False,
                                        font=dict(size=10, color="#818cf8"))
            _fig_lad.update_layout(
                height=max(220, 36 * len(_lad) + 60), xaxis=dict(range=[0, 108], gridcolor="#f1f5f9"),
                yaxis=dict(showgrid=False), margin=dict(l=10, r=10, t=30, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", size=11),
            )
            st.plotly_chart(_fig_lad, use_container_width=True, config={"displayModeBar": False})

        _wl_all_sa = load_watchlist()
        with st.expander(f"👁 Your watchlist ({len(_wl_all_sa)} stocks the AI scores each run)"):
            _wl_by_ind_sa = {}
            for _wt in _wl_all_sa:
                _ind = (_wt.get("industry") or "Uncategorized").strip() or "Uncategorized"
                _wl_by_ind_sa.setdefault(_ind, []).append(_wt["symbol"])
            for _ind_name in sorted(_wl_by_ind_sa.keys()):
                st.markdown(f"**{_ind_name}** ({len(_wl_by_ind_sa[_ind_name])})  \n"
                            + "  ".join(f"`{s}`" for s in sorted(_wl_by_ind_sa[_ind_name])))
            st.caption("Add or remove stocks in ⚙️ Settings; discover new ones in 🔭 Scan & Alerts.")

    # ══ 4) Turn cash into a plan ══════════════════════════════════════════════
    st.markdown("---")
    st.markdown("## 💰 Invest My Cash")
    st.markdown("Tell me how much you're adding — I'll turn the picks above into a simple, diversified buy plan.")

    # ── Step 1: how much? ─────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Step 1 — How much do you want to invest?</div>', unsafe_allow_html=True)
    _default_dep = round(_avail_cash) if _avail_cash >= 50 else 1000.0
    # Quick-pick buttons can't write to the widget's key after it renders
    # (StreamlitAPIException) — they stage the value here, applied pre-render
    if "deposit_pending" in st.session_state:
        st.session_state["deposit_amt"] = float(st.session_state.pop("deposit_pending"))
    if "deposit_amt" not in st.session_state:
        st.session_state["deposit_amt"] = float(_default_dep)

    dep_col, presets_col = st.columns([1.2, 2])
    with dep_col:
        deposit = st.number_input(
            "Amount in dollars", min_value=50.0, max_value=1_000_000.0,
            step=50.0, key="deposit_amt",
            help="This can be new money you're depositing, or cash already sitting in your account.",
        )
    with presets_col:
        st.markdown('<div style="font-size:.75rem;color:#94a3b8;margin-bottom:.3rem">Quick picks</div>', unsafe_allow_html=True)
        _pcols = st.columns(5)
        _presets = [500, 1000, 2500, 5000]
        for _i, _amt in enumerate(_presets):
            if _pcols[_i].button(f"${_amt:,}", key=f"preset_{_amt}"):
                st.session_state["deposit_pending"] = float(_amt)
                st.rerun()
        if _avail_cash >= 50:
            if _pcols[4].button(f"My cash (${_avail_cash:,.0f})", key="preset_cash"):
                st.session_state["deposit_pending"] = float(round(_avail_cash))
                st.rerun()

    # ── Step 2: risk style ────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Step 2 — Pick your style</div>', unsafe_allow_html=True)
    _profile_keys = list(PROFILES.keys())
    profile_key = st.radio(
        "Risk style",
        _profile_keys,
        index=_profile_keys.index(st.session_state.get("invest_profile", "balanced")),
        format_func=lambda k: f"{PROFILES[k]['emoji']} {PROFILES[k]['label']}",
        horizontal=True,
        key="invest_profile",
        label_visibility="collapsed",
    )
    _prof = PROFILES[profile_key]
    st.caption(f"{_prof['description']}  ·  Up to {_prof['max_positions']} stocks, "
               f"max {_prof['max_stock_pct']*100:.0f}% of your money in any one stock, "
               f"max {_prof['max_sector_pct']*100:.0f}% in any one sector.")

    # ── Advanced: factor weights & options ────────────────────────────────────
    _rw = regime or {}
    _def_fund = int(round(_rw.get("fund", 0.35) * 100))
    _def_tech = int(round(_rw.get("tech", 0.35) * 100))
    _def_sent = max(0, 100 - _def_fund - _def_tech)
    custom_weights = None
    with st.expander("⚙️ Advanced — adjust the recipe (optional)"):
        st.markdown("""<div style="font-size:.82rem;color:#64748b;margin-bottom:.5rem">
          Your plan blends three ingredients: <b>🏥 Company Health</b> (is the business strong?),
          <b>📈 Price Trend</b> (is the stock moving up?), and <b>📰 News Mood</b> (AI reads the
          headlines). Normally the mix adjusts itself to market conditions, but you can
          override it here. Sliders are relative — I balance them for you.
        </div>""", unsafe_allow_html=True)
        _use_custom = st.checkbox("Customize the mix", value=False, key="invest_custom_w")
        _wc1, _wc2, _wc3 = st.columns(3)
        _w_fund = _wc1.slider("🏥 Company Health", 0, 100, _def_fund, disabled=not _use_custom, key="w_fund")
        _w_tech = _wc2.slider("📈 Price Trend", 0, 100, _def_tech, disabled=not _use_custom, key="w_tech")
        _w_sent = _wc3.slider("📰 News Mood (AI)", 0, 100, _def_sent, disabled=not _use_custom, key="w_sent")
        if _use_custom and (_w_fund + _w_tech + _w_sent) > 0:
            custom_weights = {"fund": _w_fund, "tech": _w_tech, "sent": _w_sent}
            _wt = _w_fund + _w_tech + _w_sent
            st.caption(f"Your mix → Health {_w_fund/_wt*100:.0f}% · "
                       f"Trend {_w_tech/_wt*100:.0f}% · News {_w_sent/_wt*100:.0f}%")
        _oc1, _oc2 = st.columns(2)
        allow_frac = _oc1.checkbox(
            "Allow fractional shares", value=True, key="invest_frac",
            help="Most brokers (including J.P. Morgan) let you buy part of a share. Turn off if yours only allows whole shares.",
        )
        max_pos_override = _oc2.slider(
            "Max number of stocks", 2, 10, _prof["max_positions"], key="invest_maxpos",
            help="Fewer stocks = more concentrated. More stocks = more diversified.",
        )

    # The plan draws from the same pool as the picks above: watchlist + last
    # market scan (any risk style — the caps and quality bars still apply)
    plan_candidates = results
    if _scan_last_sa and _scan_last_sa.get("full"):
        _known_syms = {r["symbol"] for r in results}
        _extra = [r for r in _scan_last_sa["full"]
                  if r["symbol"] not in _known_syms and r.get("score", 0) >= 60]
        if _extra:
            plan_candidates = results + _extra
            st.caption(f"Also considering {len(_extra)} scan discoveries: "
                       f"{', '.join(r['symbol'] for r in _extra[:6])}"
                       f"{'…' if len(_extra) > 6 else ''}")

    # ── Build the plan (pure computation — instant) ───────────────────────────
    plan = build_plan(
        deposit, plan_candidates, holdings, profile_key,
        weights=custom_weights, allow_fractional=allow_frac,
        max_positions=max_pos_override,
    )
    picks    = plan["picks"]
    leftover = plan["leftover"]
    invested = plan["invested"]

    st.markdown('<div class="section-header" style="margin-top:1rem">Step 3 — Your plan</div>', unsafe_allow_html=True)
    st.caption(f"Built {data_note}.")

    if not picks:
        st.warning(
            "**I couldn't build a plan with these settings.** Usually this means the deposit is too small "
            "for whole shares (try turning on fractional shares in Advanced), or nothing on your watchlist "
            "currently scores above this style's quality bar. Check *Why aren't other stocks included?* below."
        )
    else:
        # ── Summary strip ─────────────────────────────────────────────────────
        _sectors = plan["stats"]["sectors"]
        s1, s2, s3, s4 = st.columns(4)
        for _col, _lbl, _val, _sub in (
            (s1, "You invest",   f"${invested:,.0f}", f"of your ${deposit:,.0f}"),
            (s2, "Across",       f"{len(picks)} stocks", f"{len(_sectors)} sector{'s' if len(_sectors)!=1 else ''}"),
            (s3, "Cash left over", f"${leftover:,.0f}", "stays uninvested"),
            (s4, "Plan quality", f"{plan['stats']['avg_score']:.0f}/100", "money-weighted score"),
        ):
            _col.markdown(f"""<div class="metric-card">
              <div class="metric-label">{_lbl}</div>
              <div class="metric-value">{_val}</div>
              <div class="metric-sub">{_sub}</div></div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Plan cards + allocation donut ─────────────────────────────────────
        _plan_col, _donut_col = st.columns([1.6, 1])

        with _plan_col:
            try:
                from agents.blurbs import get_blurbs as _get_blurbs_plan
                _blurbs_plan = _get_blurbs_plan([p["symbol"] for p in picks])
            except Exception:
                _blurbs_plan = {}
            for _i, _pk in enumerate(picks, 1):
                _c = _score_color(_pk["score"])
                _shares_txt = (f"{_pk['shares']:g}" if float(_pk['shares']) == int(_pk['shares'])
                               else f"{_pk['shares']:.4f}".rstrip("0"))
                _own_note = ""
                if _pk["existing_pct"] > 0:
                    _own_note = (f'<div style="font-size:.74rem;color:#b45309;margin-top:.3rem">'
                                 f'ℹ️ You already own some {_pk["symbol"]} '
                                 f'({_pk["existing_pct"]:.0f}% of your portfolio) — this tops it up.</div>')
                st.markdown(f"""
<div style="background:#fff;border:1px solid #eef0f6;border-radius:14px;
  padding:1rem 1.3rem;margin-bottom:.7rem;box-shadow:0 1px 6px rgba(0,0,0,.05)">
  <div style="display:flex;align-items:center;gap:.7rem;flex-wrap:wrap">
    <span style="background:#eef2ff;color:#6366f1;font-weight:800;border-radius:8px;
      padding:2px 9px;font-size:.8rem">#{_i}</span>
    <span style="font-size:1.15rem;font-weight:800;color:#0f172a">{_pk['symbol']}</span>
    {_badge(_pk['action'])}
    <span style="color:{_c};font-weight:700;font-size:.85rem">{_pk['score']:.0f}/100 · {_pk['conviction']}</span>
    <span style="margin-left:auto;font-size:.78rem;color:#94a3b8">{_pk['sector']}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:.6rem;margin:.5rem 0 .2rem 0;flex-wrap:wrap">
    <span style="font-size:1.5rem;font-weight:800;color:#0f172a">${_pk['dollars']:,.0f}</span>
    <span style="font-size:.9rem;color:#475569">→ buy <b>{_shares_txt} share{'s' if float(_pk['shares'])!=1 else ''}</b> at ~${_pk['price']:,.2f}</span>
    <span style="font-size:.8rem;color:#94a3b8">({_pk['pct_of_deposit']:.0f}% of your deposit)</span>
  </div>
  {_score_bar(_pk['pct_of_deposit'], _c)}
  {f'<div style="font-size:.78rem;color:#334155;margin-top:.5rem"><b>🏢 What they do:</b> {_blurbs_plan[_pk["symbol"]]}</div>' if _pk['symbol'] in _blurbs_plan else ''}
  {f'<div style="font-size:.78rem;color:#334155;margin-top:.35rem"><b>🎯 Why now:</b> {" · ".join(_entry_reasons(_pk))}</div>' if _entry_reasons(_pk) else ''}
  <div style="font-size:.8rem;color:#64748b;margin-top:.5rem"><b style="color:#334155">Why:</b> {_pk['why']}</div>
  <div style="font-size:.72rem;color:#94a3b8;margin-top:.3rem">
    Health {_pk.get('fund_score') or '—'} · Trend {_pk.get('tech_score') or '—'} · News {_pk.get('sent_score') or '—'}
  </div>
  {_own_note}
</div>""", unsafe_allow_html=True)

        with _donut_col:
            st.markdown('<div style="font-size:.85rem;font-weight:700;color:#0f172a;margin-bottom:.3rem">Where your money goes</div>', unsafe_allow_html=True)
            _dl = [p["symbol"] for p in picks] + (["Cash left over"] if leftover >= 1 else [])
            _dv = [p["dollars"] for p in picks] + ([leftover] if leftover >= 1 else [])
            _dcolors = ["#6366f1","#8b5cf6","#3b82f6","#10b981","#f59e0b",
                        "#ec4899","#14b8a6","#f97316","#84cc16","#06b6d4"][:len(picks)] + ["#e2e8f0"]
            _fig_plan = go.Figure(go.Pie(
                labels=_dl, values=_dv, hole=0.55,
                marker_colors=_dcolors[:len(_dl)],
                textinfo="label+percent", textfont_size=10,
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f} · %{percent}<extra></extra>",
            ))
            _fig_plan.add_annotation(text=f"<b>${deposit:,.0f}</b><br><span style='font-size:9px;color:#94a3b8'>your deposit</span>",
                                     x=0.5, y=0.5, showarrow=False, font_size=13, align="center")
            _fig_plan.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                    paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
            st.plotly_chart(_fig_plan, use_container_width=True, config={"displayModeBar": False})

            st.markdown('<div style="font-size:.85rem;font-weight:700;color:#0f172a;margin:.4rem 0 .3rem 0">Sector mix</div>', unsafe_allow_html=True)
            for _sec, _val in _sectors.items():
                _pctv = _val / invested * 100 if invested else 0
                st.markdown(f"""<div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:.15rem">
                  <span style="color:#475569">{_sec}</span>
                  <span style="color:#0f172a;font-weight:600">{_pctv:.0f}%</span></div>
                  {_score_bar(_pctv, '#8b5cf6')}""", unsafe_allow_html=True)

            # ── Copy-paste order checklist ─────────────────────────────────
            st.markdown('<div style="font-size:.85rem;font-weight:700;color:#0f172a;margin:.8rem 0 .3rem 0">Your order checklist</div>', unsafe_allow_html=True)
            _order_lines = "\n".join(
                f"BUY  {p['symbol']:<6} {p['shares']:g} share(s)  ≈ ${p['dollars']:,.2f}"
                for p in picks
            )
            st.code(_order_lines + f"\n---\nTotal ≈ ${invested:,.2f}  ·  keep ${leftover:,.2f} in cash", language=None)

    # ── Why not others? ───────────────────────────────────────────────────────
    if plan["skipped"]:
        with st.expander(f"🤔 Why aren't other stocks included? ({len(plan['skipped'])} explained)"):
            st.markdown('<div style="font-size:.8rem;color:#64748b;margin-bottom:.5rem">Being left out isn\'t always bad — some are skipped to keep you diversified, not because they\'re weak.</div>', unsafe_allow_html=True)
            _sk_df = pd.DataFrame(plan["skipped"])[["symbol", "score", "reason"]]
            _sk_df.columns = ["Ticker", "Score", "Why it's not in the plan"]
            st.dataframe(_sk_df.style.format({"Score": "{:.0f}"}), width="stretch",
                         height=min(380, 60 + len(plan["skipped"]) * 38))

    # ── Beginner glossary ─────────────────────────────────────────────────────
    with st.expander("📖 New to investing? What these words mean"):
        st.markdown("""
| Term | Plain English |
|---|---|
| **Score (0–100)** | The AI's overall grade for a stock right now. 75+ is a strong signal, below 45 means stay away. It blends the three ingredients below. |
| **🏥 Company Health** | How healthy the company's numbers are — is it profitable, growing, reasonably priced, not drowning in debt? |
| **📈 Price Trend** | What the price chart says — is the stock moving up, and is it overheated (maybe too late) or beaten down (maybe a bargain)? |
| **📰 News Mood** | AI reads recent news headlines and judges whether the mood around the stock is positive or negative. |
| **Market regime** | Whether the overall market is calm or stormy. In stormy markets the recipe trusts news and trends more; in calm markets, company numbers. |
| **Diversification** | Not putting all your eggs in one basket. The plan caps how much goes into any single stock or industry. |
| **Fractional shares** | Buying a piece of a share (e.g. 0.25 shares of a $500 stock for $125). Most big brokers support this. |
| **Cash left over** | Money the plan intentionally doesn't spend — either from rounding to shares, or because nothing else met the quality bar. Leaving cash uninvested is fine. |
""")

    st.caption("⚠️ This is an educational tool, not financial advice. Scores are based on public data and AI "
               "models that can be wrong — always do your own research before placing real trades.")


# ══════════════════════════════════════════════════════════════════════════════
# SCAN & ALERTS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Scan & Alerts":
    scan_tab, alert_tab = st.tabs(["🔭  Market Scan", "🔔  Alerts"])

    with scan_tab:
        st.markdown("### 🔭 Market Scan")
        st.markdown("""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
          padding:.7rem 1rem;margin-bottom:1rem;font-size:.85rem;color:#475569">
          <b style="color:#0f172a">What this does:</b> Scans all ~500 S&P 500 stocks in two passes —
          first a fast fundamentals + technicals screen on every ticker, then deep AI scoring
          (including sentiment) on the top shortlist. Use this to discover buy ideas <i>outside</i>
          your watchlist. Results show action signal, score, entry price, target, and suggested quantity.
        </div>""", unsafe_allow_html=True)
        from scripts.market_scan import scan_market
        col_a, col_b = st.columns([1, 3])
        with col_a:
            shortlist_n = st.number_input("Shortlist size", min_value=5, max_value=50, value=25, step=5)
        with col_b:
            st.markdown("<br>", unsafe_allow_html=True)
            run_scan = st.button("🔍  Run Market Scan")

        if run_scan:
            _skel_scan = st.empty()
            _skel_scan.markdown(_skeleton_loader("Scanning ~500 S&P stocks — bulk prices, health checks, then AI scoring the best…"),
                                unsafe_allow_html=True)
            progress = st.empty()
            def _cb(msg): progress.caption(msg)
            full_results, pass1_results, regime = scan_market(UID, shortlist_size=int(shortlist_n), status_cb=_cb)
            progress.empty()
            _skel_scan.empty()
            st.session_state["scan_full"] = full_results
            st.session_state["scan_pass1"] = pass1_results
            st.session_state["scan_regime"] = regime
            st.session_state["scan_chat"] = []
            st.success(f"Scanned {len(pass1_results)} tickers — top {len(full_results)} fully scored.")

            # Discovery alerts: Strong Buys you don't own or track yet
            from datetime import date as _date
            _wl_syms = {t["symbol"] for t in load_watchlist()}
            _held_syms = {p["symbol"] for p in load_holdings().get("positions", [])}
            _n_disc = 0
            for _r in full_results:
                if (_r["action"] == "Strong Buy"
                        and _r["symbol"] not in _wl_syms and _r["symbol"] not in _held_syms):
                    if _log_alert(UID, _r["symbol"], "scan_discovery",
                                  f"Scan discovery: {_r['symbol']} is a Strong Buy (score {_r['score']}) "
                                  f"and isn't in your watchlist or portfolio yet",
                                  f"{_r['symbol']}:scan_discovery:{_date.today().isoformat()}"):
                        _n_disc += 1
            if _n_disc:
                st.toast(f"🔔 {_n_disc} new discovery alert(s) — see the Alerts tab")

        scan_full   = st.session_state.get("scan_full")
        scan_pass1  = st.session_state.get("scan_pass1")
        scan_regime = st.session_state.get("scan_regime")

        # Fall back to the last saved scan so results survive app restarts
        if not scan_full:
            _saved_scan = get_last_scan()
            if _saved_scan and _saved_scan["full"]:
                scan_full   = _saved_scan["full"]
                scan_pass1  = _saved_scan["pass1"]
                scan_regime = _saved_scan["regime"]
                st.caption(f"Showing your last scan from {_saved_scan['run_at'][:16].replace('T',' ')} UTC — "
                           "click **Run Market Scan** for fresh results.")

        if not scan_full:
            st.markdown(_empty_state(
                "🔭", "Discover ideas beyond your watchlist",
                "One click scans ~500 of America's biggest companies, grades them all, and picks "
                "the standouts — sorted by what kind of pick they are: value, growth, momentum, and more.",
                "🔍 Run Market Scan — the button is just above",
            ), unsafe_allow_html=True)
        else:
            if scan_regime:
                st.caption(f"Regime: **{scan_regime['label']}** — {scan_regime.get('rationale','')}")

            # ── Style filter: what KIND of stock are you shopping for? ────────
            st.markdown('<div class="section-header">Recommendations</div>', unsafe_allow_html=True)
            _styles_present = {r.get("best_style") for r in scan_full if r.get("best_style")}
            _filter_opts = ["All"] + [k for k in STYLE_META if k in _styles_present]
            _style_pick = st.radio(
                "What are you looking for?",
                _filter_opts,
                format_func=lambda k: "⭐ Best overall" if k == "All"
                    else f"{STYLE_META[k]['emoji']} {STYLE_META[k]['label']} — {STYLE_META[k]['blurb']}",
                horizontal=True, key="scan_style_filter",
            )

            if _style_pick == "All":
                _shown = list(scan_full)
            else:
                # rank by that style's score, keep only stocks that genuinely fit it
                _shown = sorted(
                    [r for r in scan_full if r.get("styles", {}).get(_style_pick, 0) >= 65],
                    key=lambda r: r.get("styles", {}).get(_style_pick, 0), reverse=True,
                )
            if not _shown:
                st.info("No stocks in this scan strongly fit that style — try another one or a bigger shortlist.")

            _wl_syms_now  = {t["symbol"] for t in load_watchlist()}
            _saved_now    = {p["symbol"] for p in get_saved_picks()}

            for _i, _r in enumerate(_shown[:15], 1):
                _sc = _r.get("score", 0)
                _c = _score_color(_sc)
                # Portfolio-fit chips, computed against YOUR holdings/watchlist
                _fit = []
                if _r.get("held"):
                    _fit.append('<span style="background:#fef3c7;color:#b45309;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">💼 you own this</span>')
                if _r["symbol"] in _wl_syms_now:
                    _fit.append('<span style="background:#e0e7ff;color:#4338ca;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">👁 on your watchlist</span>')
                if not _r.get("held") and not _r.get("held_in_industry"):
                    _fit.append('<span style="background:#dcfce7;color:#15803d;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">🆕 new industry for you</span>')
                elif not _r.get("held") and _r.get("held_in_industry", 0) >= 3:
                    _fit.append(f'<span style="background:#fee2e2;color:#b91c1c;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">⚠️ you already hold {_r["held_in_industry"]} in {_r.get("industry","this sector")}</span>')
                _style_chips_html = " ".join(
                    f'<span style="background:#f1f5f9;color:#334155;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">{c}</span>'
                    for c in _r.get("style_chips", [])
                )
                _why = " · ".join((_r.get("reasons") or [])[:3]) or "Scored across all factors"
                _stats_r = _r.get("stats") or {}
                _tooltip = "📊 Live stats — " + _r["symbol"] + "&#10;" + "&#10;".join(_stats_lines(_stats_r))
                _cap_chip = ""
                if _cap_label(_stats_r.get("market_cap")):
                    _cap_chip = (f'<span style="background:#ede9fe;color:#6d28d9;border-radius:99px;'
                                 f'padding:2px 9px;font-size:.72rem;font-weight:600">'
                                 f'🏢 {_fmt_cap(_stats_r.get("market_cap"))} {_cap_label(_stats_r.get("market_cap"))}</span>')

                _cc1, _cc2 = st.columns([5, 1])
                with _cc1:
                    # Built as ONE line: indented/blank lines inside st.markdown
                    # HTML get re-parsed as markdown code blocks (raw-HTML bug)
                    _card_html = (
                        f'<div title="{_tooltip}" style="background:#fff;border:1px solid #eef0f6;border-radius:14px;padding:.9rem 1.2rem;margin-bottom:.15rem;box-shadow:0 1px 6px rgba(0,0,0,.05);cursor:help">'
                        f'<div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">'
                        f'<span style="background:#eef2ff;color:#6366f1;font-weight:800;border-radius:8px;padding:2px 9px;font-size:.8rem">#{_i}</span>'
                        f'<span style="font-size:1.1rem;font-weight:800;color:#0f172a">{_r["symbol"]}</span>'
                        f'{_badge(_r.get("action", "Watch"))}'
                        f'<span style="color:{_c};font-weight:700;font-size:.85rem">{_sc:.0f}/100</span>'
                        f'{_style_chips_html}{_cap_chip}'
                        f'<span style="margin-left:auto;font-size:.76rem;color:#94a3b8">{_r.get("industry", "")}</span>'
                        f'</div>'
                        f'<div style="display:flex;align-items:baseline;gap:.8rem;margin-top:.35rem;flex-wrap:wrap">'
                        f'<span style="font-size:.95rem;color:#0f172a"><b>${_r.get("current_price", "—")}</b> <span style="color:#94a3b8;font-size:.78rem">now</span></span>'
                        f'<span style="font-size:.95rem;color:#16a34a"><b>${_r.get("target_price", "—")}</b> <span style="color:#94a3b8;font-size:.78rem">target (+{_r.get("upside_pct", "—")}%)</span></span>'
                        f'<span style="font-size:.74rem;color:#94a3b8">Health {_r.get("fund_score", "—")} · Trend {_r.get("tech_score", "—")} · News {_r.get("sent_score", "—")}</span>'
                        f'<span style="font-size:.72rem;color:#c4b5fd">ℹ️ hover for live stats</span>'
                        f'</div>'
                        f'<div style="font-size:.78rem;color:#64748b;margin-top:.35rem"><b style="color:#334155">Why:</b> {_why}</div>'
                        f'<div style="margin-top:.4rem;display:flex;gap:.4rem;flex-wrap:wrap">{"".join(_fit)}</div>'
                        f'</div>'
                    )
                    st.markdown(_card_html, unsafe_allow_html=True)
                with _cc2:
                    if _r["symbol"] not in _wl_syms_now:
                        if st.button("➕ Watch", key=f"scan_watch_{_r['symbol']}",
                                     help="Add to your watchlist so every analysis scores it"):
                            _wl_new = load_watchlist()
                            _wl_new.append({"symbol": _r["symbol"], "industry": _r.get("industry", "Misc")})
                            save_watchlist(_wl_new)
                            st.rerun()
                    _is_saved = _r["symbol"] in _saved_now
                    if st.button("★" if _is_saved else "☆ Save", key=f"scan_save_{_r['symbol']}"):
                        if _is_saved:
                            remove_pick(_r["symbol"])
                        else:
                            save_pick(_r["symbol"], _r.get("industry", "Misc"))
                        st.rerun()

            # ── Deep-dive dialog (opens when a table row is clicked) ─────────
            @st.dialog("🔎 Stock Deep Dive", width="large")
            def _deep_dive(_rr):
                _s = _rr.get("stats") or {}
                st.markdown(f"## {_rr['symbol']}  ·  {_rr.get('industry','')}")
                try:
                    from agents.blurbs import get_blurbs as _get_blurbs_dd
                    _dd_blurb = _get_blurbs_dd([_rr["symbol"]]).get(_rr["symbol"])
                    if _dd_blurb:
                        st.markdown(f"<div style='font-size:.85rem;color:#334155'><b>🏢 What they do:</b> {_dd_blurb}</div>",
                                    unsafe_allow_html=True)
                except Exception:
                    pass
                _dd_chips = " ".join([_badge(_rr.get("action", "Watch"))] + [
                    f'<span style="background:#f1f5f9;color:#334155;border-radius:99px;padding:2px 9px;font-size:.75rem;font-weight:600">{c}</span>'
                    for c in _rr.get("style_chips", [])
                ])
                st.markdown(_dd_chips + f' <b style="color:{_score_color(_rr.get("score",0))}">{_rr.get("score",0):.0f}/100 overall</b>',
                            unsafe_allow_html=True)

                _g1, _g2, _g3, _g4 = st.columns(4)
                for _col, _lbl, _val in (
                    (_g1, "Price now", f"${_rr.get('current_price','—')}"),
                    (_g2, "Target", f"${_rr.get('target_price','—')} (+{_rr.get('upside_pct','—')}%)"),
                    (_g3, "Market cap", (_fmt_cap(_s.get("market_cap")) or "—")
                        + (f" · {_cap_label(_s.get('market_cap'))}" if _cap_label(_s.get("market_cap")) else "")),
                    (_g4, "Today", _sv(_s.get("day_change_pct"), "pct")),
                ):
                    _col.markdown(f'<div class="metric-card" style="padding:.8rem 1rem"><div class="metric-label">{_lbl}</div>'
                                  f'<div style="font-size:1.05rem;font-weight:700;color:#0f172a">{_val}</div></div>',
                                  unsafe_allow_html=True)

                try:
                    _hist6 = fetch_price_history(_rr["symbol"], "6mo")
                    _hc = "#16a34a" if _hist6["Close"].iloc[-1] >= _hist6["Close"].iloc[0] else "#dc2626"
                    _fig_dd = go.Figure(go.Scatter(x=_hist6.index, y=_hist6["Close"], mode="lines",
                                                   line=dict(color=_hc, width=2), fill="tozeroy",
                                                   fillcolor="rgba(99,102,241,.06)"))
                    _fig_dd.update_layout(height=260, margin=dict(l=10, r=10, t=25, b=10),
                                          title="6-month price", title_font_size=13,
                                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                          yaxis=dict(gridcolor="#f1f5f9", tickprefix="$"), xaxis=dict(showgrid=False))
                    st.plotly_chart(_fig_dd, use_container_width=True, config={"displayModeBar": False})
                except Exception:
                    st.caption("Price chart unavailable right now.")

                _st1, _st2 = st.columns(2)
                with _st1:
                    st.markdown("**Key statistics**")
                    for _line in _stats_lines(_s):
                        st.markdown(f"<div style='font-size:.85rem;color:#475569;padding:.1rem 0'>{_line}</div>",
                                    unsafe_allow_html=True)
                with _st2:
                    st.markdown("**Score ingredients**")
                    for _lbl2, _v2, _c2 in (("🏥 Company Health", _rr.get("fund_score"), "#6366f1"),
                                            ("📈 Price Trend", _rr.get("tech_score"), "#f59e0b"),
                                            ("📰 News Mood (AI)", _rr.get("sent_score"), "#10b981")):
                        _v2 = _safe_float(_v2, 0)
                        st.markdown(f"<div style='font-size:.8rem;color:#475569;margin-top:.3rem'>{_lbl2} — <b>{_v2:.0f}/100</b></div>"
                                    + _score_bar(_v2, _c2), unsafe_allow_html=True)
                    if _rr.get("reasons"):
                        st.markdown("**Why the AI likes / dislikes it**")
                        for _rs in _rr["reasons"][:5]:
                            st.markdown(f"- {_rs}")
                _hl = _rr.get("headlines", [])
                if _hl:
                    st.markdown("**Recent news**")
                    for _h in _hl[:4]:
                        st.markdown(f"📰 {_h}")
                st.caption("Educational tool, not financial advice.")

            # ── Full tables for the detail-oriented ───────────────────────────
            with st.expander(f"Full shortlist table ({len(scan_full)} stocks) — click a row for a deep dive"):
                _df_full = pd.DataFrame(scan_full)
                if "best_style" in _df_full.columns:
                    _df_full["Style"] = _df_full["best_style"].map(
                        lambda k: f"{STYLE_META[k]['emoji']} {STYLE_META[k]['label']}" if k in STYLE_META else "—")
                else:
                    _df_full["Style"] = "—"
                _cols = ["symbol","industry","Style","action","score","current_price","target_price","upside_pct"]
                _df_show = _df_full[[c for c in _cols if c in _df_full.columns]]
                _df_show.columns = ["Symbol","Industry","Style","Action","Score","Price","Target","Upside %"][:len(_df_show.columns)]
                _tbl_sel = st.dataframe(_df_show, width="stretch", height=400,
                                        on_select="rerun", selection_mode="single-row", key="scan_tbl_sel")
                st.caption("👆 Click any row to open a full deep dive: price chart, statistics, model scores, and news.")
                try:
                    _sel_rows = _tbl_sel.selection.rows
                except Exception:
                    _sel_rows = []
                if _sel_rows:
                    _sel_sym = _df_show.iloc[_sel_rows[0]]["Symbol"]
                    if st.session_state.get("deep_dive_last") != _sel_sym:
                        st.session_state["deep_dive_last"] = _sel_sym
                        _sel_match = next((r for r in scan_full if r["symbol"] == _sel_sym), None)
                        if _sel_match:
                            _deep_dive(_sel_match)
                else:
                    st.session_state.pop("deep_dive_last", None)
            with st.expander(f"Pass 1: all {len(scan_pass1)} tickers (cheap score only)"):
                df_p1 = pd.DataFrame(scan_pass1)[["symbol","industry","fund_score","tech_score","cheap_score"]]
                df_p1.columns = ["Symbol","Industry","Fund","Tech","Cheap Score"]
                st.dataframe(df_p1, width="stretch", height=380)

            # ── Niche ideas: AI traces your winners' supply chains ──────────
            st.markdown('<div class="section-header" style="margin-top:1rem">🔗 Niche Ideas From Your Winners</div>', unsafe_allow_html=True)
            st.markdown("""<div style="font-size:.8rem;color:#64748b;margin-bottom:.5rem">
              AI looks at your best-performing holdings, traces their supply chains
              (e.g. AI chips → datacenters → electricity → grid equipment), and finds
              smaller public companies riding the same wave — names a big-cap scan won't surface.
              Every suggestion is validated against live market data before it's shown.
            </div>""", unsafe_allow_html=True)
            if st.button("🔗 Trace my winners' supply chains", key="supply_btn"):
                with st.spinner("Mapping supply chains with AI, then validating every ticker against live data…"):
                    from agents.supply_chain import discover_niche_ideas
                    os.environ["ADVISOR_AI_MODEL"] = st.session_state.get("ai_model_id", "claude-sonnet-4-6")
                    _h_now = load_holdings()
                    _excl = ({p["symbol"] for p in _h_now.get("positions", [])}
                             | {t["symbol"] for t in load_watchlist()})
                    st.session_state["supply_ideas"] = discover_niche_ideas(_h_now, _excl)

            _si = st.session_state.get("supply_ideas")
            if _si:
                if _si.get("error"):
                    st.warning(_si["error"])
                elif not _si.get("ideas"):
                    st.info("The AI's suggestions didn't survive live-data validation — try again in a moment.")
                else:
                    st.caption(f"Traced from your winners: {' · '.join(_si['winners'])}")
                    for _idea in _si["ideas"]:
                        _ic1, _ic2 = st.columns([5, 1])
                        _icap = ""
                        if _cap_label(_idea.get("market_cap")):
                            _icap = (f'<span style="background:#ede9fe;color:#6d28d9;border-radius:99px;padding:2px 9px;'
                                     f'font-size:.72rem;font-weight:600">🏢 {_fmt_cap(_idea.get("market_cap"))} {_cap_label(_idea.get("market_cap"))}</span>')
                        _iwhy = " · ".join(_idea.get("reasons", [])[:2])
                        with _ic1:
                            st.markdown(
                                f'<div style="background:#fff;border:1px solid #eef0f6;border-radius:14px;padding:.8rem 1.1rem;margin-bottom:.15rem;box-shadow:0 1px 6px rgba(0,0,0,.05)">'
                                f'<div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">'
                                f'<span style="font-size:1.05rem;font-weight:800;color:#0f172a">{_idea["symbol"]}</span>'
                                f'<span style="font-size:.8rem;color:#64748b">{_idea.get("company","")}</span>'
                                f'{_icap}'
                                f'<span style="background:#e0f2fe;color:#0369a1;border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:600">🔗 via your {_idea.get("via","winner")}</span>'
                                f'<span style="margin-left:auto;font-weight:700;color:{_score_color(_idea.get("cheap_score",50))}">{_idea.get("cheap_score","—")}/100</span>'
                                f'</div>'
                                f'<div style="font-size:.8rem;color:#334155;margin-top:.3rem"><b>The connection:</b> {_idea.get("connection","")}</div>'
                                f'<div style="display:flex;gap:.8rem;margin-top:.3rem;font-size:.76rem;color:#94a3b8">'
                                f'<span>${_idea.get("price","—")} now</span>'
                                f'<span>Models: F{_idea.get("fund_score","—")} · T{_idea.get("tech_score","—")}</span>'
                                f'{f"<span>{_iwhy}</span>" if _iwhy else ""}'
                                f'</div>'
                                f'</div>', unsafe_allow_html=True)
                        with _ic2:
                            if _idea["symbol"] not in {t["symbol"] for t in load_watchlist()}:
                                if st.button("➕ Watch", key=f"supply_watch_{_idea['symbol']}"):
                                    _wl_new = load_watchlist()
                                    _wl_new.append({"symbol": _idea["symbol"], "industry": "Misc"})
                                    save_watchlist(_wl_new)
                                    st.rerun()
                    st.caption("💡 Add ideas to your watchlist, then run an analysis to get their full scores — "
                               "or switch the Stock Advisor plan to Aggressive to let it consider scan discoveries.")

            # ── Ask AI about the scan results ──────────────────────────────
            st.markdown('<div class="section-header" style="margin-top:1rem">Ask AI About These Results</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:.8rem;color:#64748b;margin-bottom:.5rem">Ask anything about the scan — e.g. "Which AI stocks look strongest?", "Show me value plays under $50", "Why is NVDA ranked high?"</div>', unsafe_allow_html=True)

            if "scan_chat" not in st.session_state:
                st.session_state["scan_chat"] = []

            # Display previous chat
            for _msg in st.session_state["scan_chat"]:
                with st.chat_message(_msg["role"]):
                    st.markdown(_msg["content"])

            _q = st.chat_input("Ask about the market scan results…", key="scan_chat_input")
            if _q:
                st.session_state["scan_chat"].append({"role": "user", "content": _q})
                with st.chat_message("user"):
                    st.markdown(_q)

                # Build context from scan results
                _scan_summary = "\n".join(
                    f"{r['symbol']} ({r.get('industry','?')}): {r['action']}, score={r['score']}, "
                    f"price=${r['current_price']}, target=${r['target_price']}, upside={r['upside_pct']}%, "
                    f"reasons: {'; '.join(r.get('reasons', [])[:2])}"
                    for r in (scan_full or [])[:30]
                )
                _regime_ctx = f"Market regime: {scan_regime['label']}. {scan_regime.get('rationale','')}" if scan_regime else ""

                _sys_prompt = f"""You are a concise financial analyst assistant. The user just ran a stock market scan.
Here are the top results:
{_scan_summary}

{_regime_ctx}

Answer the user's question directly and concisely based on this data. Keep it under 200 words unless asked for more detail."""

                try:
                    from anthropic import Anthropic as _Anthropic
                    _ac = _Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                    _chat_model = st.session_state.get("ai_model_id", "claude-sonnet-4-6")
                    _msgs = [{"role": m["role"], "content": m["content"]}
                             for m in st.session_state["scan_chat"]]
                    _resp = _ac.messages.create(
                        model=_chat_model, max_tokens=600,
                        system=_sys_prompt, messages=_msgs,
                    )
                    _answer = _resp.content[0].text
                except Exception as _e:
                    _answer = f"Could not get AI response: {_e}"

                st.session_state["scan_chat"].append({"role": "assistant", "content": _answer})
                with st.chat_message("assistant"):
                    st.markdown(_answer)

    with alert_tab:
        st.markdown("### 🔔 Alerts")
        st.markdown("""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
          padding:.7rem 1rem;margin-bottom:1rem;font-size:.85rem;color:#475569">
          <b style="color:#0f172a">What this does:</b> Monitors your watchlist every 5 minutes
          during market hours (9:30–16:00 ET) and fires a macOS desktop notification when:
          a stock flips to <b>Strong Buy</b>, a position <b>hits its price target</b>,
          or any stock makes an <b>intraday move ≥5%</b>. Alerts are deduplicated daily so
          you won't get spammed. Run the poller command below in a separate terminal to start it.
        </div>""", unsafe_allow_html=True)
        st.code("python3 scripts/alert_poller.py", language="bash")
        st.markdown('<div class="section-header">Recent Alerts</div>', unsafe_allow_html=True)
        alerts = get_recent_alerts(limit=50)
        if not alerts:
            st.markdown(_empty_state(
                "🔔", "All quiet for now",
                "Alerts appear here when something worth knowing happens: a stock flips to Strong Buy, "
                "hits its target price, jumps ±5% in a day, or a scan discovers a gem you don't own yet.",
            ), unsafe_allow_html=True)
        else:
            df_alerts = pd.DataFrame(alerts)[["fired_at","symbol","alert_type","message"]]
            df_alerts.columns = ["Fired At (UTC)","Symbol","Type","Message"]
            st.dataframe(df_alerts, width="stretch", height=380)
        if st.button("⚡ Check triggers now (one-off)"):
            from agents.alerts import check_triggers
            from db.store import log_alert
            _res = st.session_state.get("results")
            if not _res:
                st.warning("Run an analysis on Dashboard first.")
            else:
                fired = sum(1 for a in check_triggers(_res, {})
                            if log_alert(a["symbol"], a["type"], a["message"], a["dedup_key"]))
                st.success(f"{fired} new alert(s) logged.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# LISTS & HISTORY
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Lists & History":
    list_tab, hist_tab = st.tabs(["📋  Saved Picks", "🕐  History"])

    with list_tab:
        st.markdown("### 📋 Saved Picks")
        st.markdown("""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
          padding:.7rem 1rem;margin-bottom:1rem;font-size:.85rem;color:#475569">
          <b style="color:#0f172a">What this does:</b> Your personal watchlist of stocks you've
          bookmarked for future research. Organize them by industry (AI, Financials, Healthcare…),
          add a personal note for why you're tracking it, and remove picks you're no longer
          interested in. Stocks can be saved here directly from the Dashboard suggestion cards.
        </div>""", unsafe_allow_html=True)
        picks = get_saved_picks()
        with st.form("add_pick", clear_on_submit=True):
            ca, cb, cc, cd = st.columns([1.5, 1.5, 2.5, 1])
            with ca: new_sym  = st.text_input("Ticker", placeholder="AMZN")
            with cb: new_ind  = st.selectbox("Industry", INDUSTRIES)
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

    with hist_tab:
        st.markdown("### 🕐 Suggestion History")
        st.markdown("""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
          padding:.7rem 1rem;margin-bottom:1rem;font-size:.85rem;color:#475569">
          <b style="color:#0f172a">What this does:</b> Full log of every AI suggestion ever generated
          for your watchlist — date, action signal, score breakdown (Fundamentals / Technicals /
          Sentiment), entry price, and target. Filter by ticker to see how a specific stock's
          score has evolved over time, with a trend chart if multiple data points exist.
        </div>""", unsafe_allow_html=True)
        sym_filter = (st.text_input("Filter by symbol", placeholder="AAPL").upper() or None)
        history = get_suggestion_history(symbol=sym_filter, limit=100)
        if not history:
            st.info("No history yet. Run an analysis first.")
        else:
            df_h = pd.DataFrame(history)
            df_h["run_at"] = pd.to_datetime(df_h["run_at"]).dt.strftime("%Y-%m-%d %H:%M")
            df_h = df_h[["run_at","symbol","action","score","current_price","target_price","upside_pct","regime","fund_score","tech_score","sent_score"]]
            df_h.columns = ["Date","Symbol","Action","Score","Entry $","Target $","Upside %","Regime","Fund","Tech","Sent"]

            def _color_action(val):
                return {"Strong Buy":"background-color:#dcfce7;color:#166534",
                        "Buy":"background-color:#dbeafe;color:#1e40af",
                        "Watch":"background-color:#fef9c3;color:#854d0e",
                        "Avoid":"background-color:#fee2e2;color:#991b1b"}.get(val,"")

            st.dataframe(df_h.style.map(_color_action, subset=["Action"]),
                         width="stretch", height=420)
            if sym_filter and len(df_h) > 1:
                st.markdown(f'<div class="section-header">Score trend — {sym_filter}</div>', unsafe_allow_html=True)
                fig3 = px.line(df_h.sort_values("Date"), x="Date", y="Score",
                               markers=True, color_discrete_sequence=["#6366f1"])
                fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                   font=dict(family="Inter"), height=280,
                                   margin=dict(l=10,r=10,t=10,b=20))
                st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE SECTION (renders inside Dashboard via _perf_slot container)
# ══════════════════════════════════════════════════════════════════════════════
def _render_performance_section():
    st.markdown("---")

    # ── Your portfolio over time (equity curve) ──────────────────────────────
    _snaps = get_portfolio_snapshots()
    st.markdown('<div class="section-header">📈 Your Portfolio Over Time</div>', unsafe_allow_html=True)
    if len(_snaps) >= 2:
        _df_eq = pd.DataFrame(_snaps)
        _first_v = _safe_float(_snaps[0]["total_value"])
        _last_v  = _safe_float(_snaps[-1]["total_value"])
        _chg     = _last_v - _first_v
        _chg_pct = (_chg / _first_v * 100) if _first_v else 0.0
        _eq_col  = "#15803d" if _chg >= 0 else "#dc2626"
        st.caption(f"Tracked across {len(_snaps)} day(s) — "
                   f"{'up' if _chg >= 0 else 'down'} ${abs(_chg):,.0f} ({_chg_pct:+.1f}%) since tracking began. "
                   "A point is saved each day you open the dashboard.")
        _fig_eq = go.Figure(go.Scatter(
            x=_df_eq["snap_date"], y=_df_eq["total_value"],
            mode="lines+markers", line=dict(color="#6366f1", width=2.5),
            fill="tozeroy", fillcolor="rgba(99,102,241,.08)",
            marker=dict(size=5),
            hovertemplate="<b>%{x}</b><br>Value: $%{y:,.0f}<extra></extra>",
        ))
        _fig_eq.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=30),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", size=11),
            xaxis=dict(showgrid=False),
            yaxis=dict(tickprefix="$", tickformat=",.0f", gridcolor="#eef1f7",
                       rangemode="tozero"),
        )
        st.plotly_chart(_fig_eq, use_container_width=True, config={"displayModeBar": False})
        with st.expander("View as table"):
            _eq_tbl = _df_eq[["snap_date", "total_value", "equity_value", "cash", "total_gl", "n_positions"]].copy()
            _eq_tbl.columns = ["Date", "Total Value", "Equities", "Cash", "Unrealized G/L", "Positions"]
            st.dataframe(
                _eq_tbl.iloc[::-1].style.format({
                    "Total Value": "${:,.0f}", "Equities": "${:,.0f}", "Cash": "${:,.0f}",
                    "Unrealized G/L": "${:+,.0f}"}, na_rep="—"),
                use_container_width=True, height=min(320, 60 + len(_eq_tbl) * 36),
            )
    elif len(_snaps) == 1:
        st.caption("Your first portfolio value is saved — the equity curve appears once there "
                   "are at least two days of data. Check back tomorrow.")
    else:
        st.caption("Import your holdings, then open the dashboard — each visit saves a daily "
                   "portfolio value point that builds this equity curve.")

    # ── What you actually did (decisions) ────────────────────────────────────
    _decs = get_decisions()
    if _decs:
        st.markdown('<div class="section-header">🧭 Your Decisions</div>', unsafe_allow_html=True)
        _n_bought = sum(1 for d in _decs if d["decision"] == "bought")
        _n_passed = sum(1 for d in _decs if d["decision"] == "passed")
        st.caption(f"You've marked {_n_bought} **bought** and {_n_passed} **passed**. "
                   "Returns are measured from the price when you made the call.")
        _dec_rows = []
        for d in _decs:
            _now_p = _safe_float(fetch_ticker_info(d["symbol"]).get("currentPrice")
                                 or fetch_ticker_info(d["symbol"]).get("regularMarketPrice"))
            _then = _safe_float(d.get("price"))
            _ret = round((_now_p - _then) / _then * 100, 1) if _then and _now_p else None
            _dec_rows.append({
                "Symbol": d["symbol"],
                "Decision": "✅ Bought" if d["decision"] == "bought" else "🚫 Passed",
                "When": (d["decided_at"] or "")[:10],
                "Verdict": d.get("action") or "—",
                "Price then": _then or None,
                "Price now": _now_p or None,
                "Since": _ret,
            })
        _dec_df = pd.DataFrame(_dec_rows)
        def _dec_ret_style(v):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return ""
            return f"color:{POS_COLOR};font-weight:600" if v > 0 else f"color:{NEG_COLOR};font-weight:600"
        st.dataframe(
            _dec_df.style
                .map(_dec_ret_style, subset=["Since"])
                .format({"Price then": "${:,.2f}", "Price now": "${:,.2f}", "Since": "{:+.1f}%"}, na_rep="—"),
            use_container_width=True, height=min(360, 60 + len(_dec_rows) * 36),
        )
        st.caption("For **passed** picks, a positive number is gains you skipped; a negative "
                   "one is a loss you dodged.")

    st.markdown('<div class="section-header">📊 How Past Suggestions Performed</div>', unsafe_allow_html=True)
    st.caption("The honest report card — pick a time window and see how every AI call actually did afterwards.")

    # Timeframe selector
    _tf_opts = ["Since Suggestion", "1 Week", "1 Month", "3 Months", "6 Months"]
    _tf_days = {"Since Suggestion": None, "1 Week": 7, "1 Month": 30, "3 Months": 90, "6 Months": 180}
    _tf = st.radio("Return window:", _tf_opts, horizontal=True, key="perf_tf")
    _lookback_days = _tf_days[_tf]

    baselines = get_performance_snapshot()
    if not baselines:
        st.markdown(_empty_state(
            "📊", "Nothing to track yet",
            "Once you run your first analysis, this page keeps score: how every AI suggestion "
            "actually performed afterwards — the honest report card.",
            "▶ Run Analysis Now in the sidebar",
        ), unsafe_allow_html=True)
    else:
        rows = []
        with st.spinner("Fetching prices…"):
            from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _asc
            import datetime as _dt

            def _fetch_perf(b):
                # Returns None on any failure so one bad ticker can't kill the page
                try:
                    info = fetch_ticker_info(b["symbol"])
                    now_p = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
                    if _lookback_days is None:
                        # Return vs entry price logged at suggestion time
                        entry = _safe_float(b["entry_price"])
                        period_label = b["run_at"][:10]
                    else:
                        # Return vs price N days ago using price history
                        hist = fetch_price_history(b["symbol"], period="1y")
                        if hist is not None and not hist.empty:
                            cutoff = _dt.date.today() - _dt.timedelta(days=_lookback_days)
                            past = hist[hist.index.date <= cutoff]
                            entry = _safe_float(past["Close"].iloc[-1]) if not past.empty else now_p
                        else:
                            entry = now_p
                        period_label = f"{_lookback_days}d ago"
                    ret = round((now_p - entry) / entry * 100, 1) if entry else None
                    target = _safe_float(b.get("target_price"))
                    return {
                        "Symbol":      b["symbol"],
                        "Suggested":   b["run_at"][:10],
                        "Action":      b["action"],
                        "Entry $":     round(entry, 2) if entry else None,
                        "Now $":       round(now_p, 2) if now_p else None,
                        "Return %":    ret,
                        "Window":      period_label,
                        "Target $":    target if target > 0 else None,
                        "To Target %": round((target - now_p) / now_p * 100, 1) if (target > 0 and now_p > 0) else None,
                    }
                except Exception:
                    return None

            with _TPE(max_workers=15) as _ex:
                rows = [r for r in _ex.map(_fetch_perf, baselines) if r is not None]

        if not rows:
            st.info("Could not fetch current prices.")
        else:
            df_perf = pd.DataFrame(rows)
            df_perf["Return %"] = df_perf["Return %"].apply(lambda v: _safe_float(v))

            winners  = sum(1 for r in rows if _safe_float(r["Return %"]) > 0)
            losers   = sum(1 for r in rows if _safe_float(r["Return %"]) < 0)
            avg_ret  = sum(_safe_float(r["Return %"]) for r in rows) / max(len(rows),1)
            best_r   = max(rows, key=lambda r: _safe_float(r["Return %"]))

            col_a, col_b, col_c, col_d, col_e = st.columns(5)
            def _pkpi(c, lbl, val, sub="", col=None):
                color = f"color:{col};" if col else ""
                c.markdown(f"""<div class="metric-card">
                  <div class="metric-label">{lbl}</div>
                  <div class="metric-value" style="{color}">{val}</div>
                  <div class="metric-sub">{sub}</div></div>""", unsafe_allow_html=True)

            _pkpi(col_a, "Tracked", len(rows), "suggestions")
            _pkpi(col_b, "Winners", winners, "positive return", "#16a34a")
            _pkpi(col_c, "Losers",  losers,  "negative return", "#dc2626")
            _pkpi(col_d, "Avg Return", f"{avg_ret:+.1f}%", _tf,
                  "#16a34a" if avg_ret >= 0 else "#dc2626")
            _pkpi(col_e, "Best Pick",
                  f"{_safe_float(best_r['Return %']):+.1f}%",
                  best_r["Symbol"], "#16a34a")

            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown(f'<div class="section-header">Return — {_tf}</div>', unsafe_allow_html=True)
            df_chart = df_perf.dropna(subset=["Return %"]).sort_values("Return %", ascending=False)
            bar_colors = ["#16a34a" if v >= 0 else "#ef4444" for v in df_chart["Return %"]]
            fig_ret = go.Figure(go.Bar(
                x=df_chart["Symbol"], y=df_chart["Return %"],
                marker_color=bar_colors,
                text=df_chart["Return %"].apply(lambda x: f"{x:+.1f}%"),
                textposition="outside", textfont_size=10,
                hovertemplate="<b>%{x}</b><br>Return (" + _tf + "): %{y:+.1f}%<extra></extra>",
            ))
            fig_ret.add_hline(y=0, line_color="#94a3b8", line_width=1)
            fig_ret.update_layout(
                height=360, yaxis_title="Return %",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", size=11),
                margin=dict(l=10, r=10, t=10, b=50),
                xaxis=dict(tickangle=-40, showgrid=False),
                yaxis=dict(gridcolor="#f1f5f9", zerolinecolor="#cbd5e1", ticksuffix="%"),
                bargap=0.3,
            )
            st.plotly_chart(fig_ret, use_container_width=True, config={"displayModeBar": False})

            st.markdown('<div class="section-header">Detail Table</div>', unsafe_allow_html=True)
            def _ret_style(val):
                if val is None or (isinstance(val, float) and math.isnan(val)): return ""
                return "color:#16a34a;font-weight:600" if val > 0 else "color:#ef4444;font-weight:600"

            _show_cols = ["Symbol","Action","Suggested","Window","Entry $","Now $","Return %","Target $","To Target %"]
            st.dataframe(
                df_perf[_show_cols].style
                    .map(_ret_style, subset=["Return %", "To Target %"])
                    .format({"Entry $": "${:.2f}", "Now $": "${:.2f}",
                             "Target $": "${:.2f}", "Return %": "{:+.1f}%",
                             "To Target %": "{:+.1f}%"}, na_rep="—"),
                width="stretch", height=400,
            )


# ══════════════════════════════════════════════════════════════════════════════
# COMMUNITY
# ══════════════════════════════════════════════════════════════════════════════
if page == "Community":
    st.markdown("# 👥 Community")
    st.markdown("Follow other investors, compare verified track records, and talk tickers.")

    st.markdown("""<div class="warn-banner">
      ⚠️ <strong>Not investment advice.</strong> Everything here is opinion and self-directed
      research from other members. Returns are computed from users' own logged picks and are
      <em>not</em> audited. Never post account numbers or personal financial details.
    </div><br>""", unsafe_allow_html=True)

    _esc = lambda s: html.escape(str(s or ""))

    def _fmt_when(iso):
        return (iso or "")[:16].replace("T", " ")

    _me_prof = get_profile()
    if not _me_prof["is_public"]:
        st.info("👋 Your profile is **private** — you can browse and post, but you won't appear "
                "on the leaderboard or member list until you go public under **My Profile**.")

    def _render_post(p, key_prefix):
        _tkr = ""
        if p.get("ticker"):
            _tkr = (f'<span style="background:#eef2ff;color:#4f46e5;border-radius:99px;'
                    f'padding:1px 8px;font-size:.72rem;font-weight:700;margin-left:.4rem">'
                    f'${_esc(p["ticker"])}</span>')
        _body = _esc(p["body"]).replace("\n", "<br>")
        st.markdown(f"""<div class="metric-card" style="padding:.75rem 1rem;margin-bottom:.5rem">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div><b>{_esc(p['avatar'])} {_esc(p['display_name'])}</b>{_tkr}</div>
            <div style="color:#94a3b8;font-size:.72rem">{_fmt_when(p['created_at'])} UTC</div>
          </div>
          <div style="margin-top:.35rem;color:#334155;font-size:.9rem">{_body}</div>
        </div>""", unsafe_allow_html=True)
        _bcols = st.columns([1, 1, 1, 5])
        with _bcols[0]:
            _lbl = f"❤ {p['likes']}" if p["liked"] else f"🤍 {p['likes']}"
            if st.button(_lbl, key=f"{key_prefix}_like_{p['id']}"):
                (unlike_post if p["liked"] else like_post)(p["id"]); st.rerun()
        if p["is_own"]:
            with _bcols[1]:
                if st.button("🗑", key=f"{key_prefix}_del_{p['id']}", help="Delete your post"):
                    delete_post(p["id"]); st.rerun()
        else:
            with _bcols[1]:
                if st.button("🚩", key=f"{key_prefix}_rep_{p['id']}", help="Report this post"):
                    community_report(post_id=p["id"], reason="reported")
                    st.toast("Reported to the moderators.")
            with _bcols[2]:
                if st.button("🚫", key=f"{key_prefix}_blk_{p['id']}",
                             help=f"Block {p['display_name']}"):
                    community_block(p["user_id"]); st.rerun()

    _tab_feed, _tab_board, _tab_discuss, _tab_lists, _tab_profile = st.tabs(
        ["🏠 Feed", "🏆 Leaderboard", "💬 Discuss", "📋 Shared Lists", "👤 My Profile"])

    # ── Feed ────────────────────────────────────────────────────────────────
    with _tab_feed:
        with st.form("compose_post", clear_on_submit=True):
            _pc1, _pc2 = st.columns([4, 1])
            with _pc1:
                _body_in = st.text_area("Share a thought", max_chars=_community.MAX_POST_LEN,
                                        placeholder="What are you watching today?",
                                        label_visibility="collapsed")
            with _pc2:
                _tkr_in = st.text_input("Ticker", placeholder="NVDA (optional)",
                                        label_visibility="collapsed")
            if st.form_submit_button("Post", type="primary"):
                _res = create_post(_body_in, _tkr_in.strip() or None)
                if "error" in _res:
                    st.error(_res["error"])
                else:
                    st.rerun()

        st.markdown('<div class="section-header">From people you follow</div>', unsafe_allow_html=True)
        _feed = get_feed()
        if not _feed:
            st.caption("Nothing here yet — follow members on the Leaderboard, or post something above.")
        for _p in _feed:
            _render_post(_p, "feed")

        st.markdown('<div class="section-header">Recent from everyone</div>', unsafe_allow_html=True)
        _recent = get_recent_posts()
        if not _recent:
            st.caption("Be the first to post!")
        for _p in _recent:
            _render_post(_p, "recent")

    # ── Leaderboard ─────────────────────────────────────────────────────────
    with _tab_board:
        st.caption("Ranked by average return across each member's **logged** buy calls — "
                   "priced live from when they marked the pick. Only members who opted into "
                   "sharing returns appear here.")
        _cands = get_public_sharers()
        _rows = []
        with st.spinner("Scoring track records…"):
            for _u in _cands:
                _avg, _n = verified_return_pct(_u["user_id"])
                if _n > 0:
                    _rows.append((_u, _avg, _n))
        _rows.sort(key=lambda x: x[1], reverse=True)
        if not _rows:
            st.info("No verified track records yet. Mark some suggestions as **Bought** on the "
                    "Stock Advisor page and opt into sharing returns under **My Profile** to appear here.")
        _following = get_following_ids()
        for _rank, (_u, _avg, _n) in enumerate(_rows, 1):
            _c1, _c2, _c3, _c4 = st.columns([0.6, 3, 1.4, 1.2])
            _col = "#15803d" if _avg >= 0 else "#dc2626"
            with _c1:
                st.markdown(f"<div style='font-size:1.3rem;font-weight:800;color:#94a3b8'>#{_rank}</div>",
                            unsafe_allow_html=True)
            with _c2:
                st.markdown(f"**{_esc(_u['avatar'])} {_esc(_u['display_name'])}**  \n"
                            f"<small style='color:#64748b'>{_esc(_u.get('bio') or '')}</small>",
                            unsafe_allow_html=True)
            with _c3:
                st.markdown(f"<div style='font-weight:800;color:{_col};font-size:1.1rem'>{_avg:+.1f}%</div>"
                            f"<small style='color:#94a3b8'>{_n} pick(s)</small>", unsafe_allow_html=True)
            with _c4:
                if _u["user_id"] in _following:
                    if st.button("Following", key=f"lb_unf_{_u['user_id']}"):
                        unfollow(_u["user_id"]); st.rerun()
                else:
                    if st.button("Follow", key=f"lb_f_{_u['user_id']}", type="primary"):
                        follow(_u["user_id"]); st.rerun()
            st.divider()

    # ── Discuss (ticker threads) ────────────────────────────────────────────
    with _tab_discuss:
        _disc_tkr = st.text_input("Ticker to discuss", value=st.session_state.get("discuss_ticker", ""),
                                  placeholder="e.g. NVDA").strip().upper()
        st.session_state["discuss_ticker"] = _disc_tkr
        if _disc_tkr:
            with st.form("thread_post", clear_on_submit=True):
                _tbody = st.text_area(f"Post to the ${_disc_tkr} thread",
                                      max_chars=_community.MAX_POST_LEN,
                                      placeholder=f"Your take on {_disc_tkr}…")
                if st.form_submit_button(f"Post to ${_disc_tkr}", type="primary"):
                    _res = create_post(_tbody, _disc_tkr)
                    if "error" in _res:
                        st.error(_res["error"])
                    else:
                        st.rerun()
            st.markdown(f'<div class="section-header">${_esc(_disc_tkr)} discussion</div>',
                        unsafe_allow_html=True)
            _thread = get_ticker_posts(_disc_tkr)
            if not _thread:
                st.caption("No posts yet — start the conversation above.")
            for _p in _thread:
                _render_post(_p, "thread")
        else:
            st.caption("Enter a ticker to see and join its discussion thread.")

    # ── Shared Lists ────────────────────────────────────────────────────────
    with _tab_lists:
        st.markdown('<div class="section-header">Publish your watchlist</div>', unsafe_allow_html=True)
        _my_wl = load_watchlist()
        st.caption(f"Shares your current watchlist ({len(_my_wl)} tickers) — symbols and industries "
                   "only, no holdings or dollar amounts.")
        with st.form("publish_wl", clear_on_submit=True):
            _wl_name = st.text_input("List name", placeholder="My AI & Semis picks",
                                     max_chars=_community.MAX_WATCHLIST_NAME_LEN)
            if st.form_submit_button("Publish", type="primary"):
                _res = publish_watchlist(_wl_name, _my_wl)
                if "error" in _res:
                    st.error(_res["error"])
                else:
                    st.success("Published!"); st.rerun()

        st.markdown('<div class="section-header">Browse shared lists</div>', unsafe_allow_html=True)
        _shared = get_shared_watchlists()
        if not _shared:
            st.caption("No shared lists yet — publish yours above.")
        for _sl in _shared:
            _syms = [t.get("symbol", "") for t in _sl["tickers"] if isinstance(t, dict)]
            _chips = " ".join(f"<code>{_esc(s)}</code>" for s in _syms[:12])
            st.markdown(f"""<div class="metric-card" style="padding:.8rem 1rem;margin-bottom:.4rem">
              <div style="display:flex;justify-content:space-between">
                <b>{_esc(_sl['name'])}</b>
                <span style="color:#94a3b8;font-size:.72rem">{_esc(_sl['avatar'])} {_esc(_sl['display_name'])} · {len(_syms)} tickers</span>
              </div>
              <div style="margin-top:.35rem;font-size:.8rem">{_chips}</div>
            </div>""", unsafe_allow_html=True)
            _lc1, _lc2, _lc3 = st.columns([1.2, 1, 5])
            with _lc1:
                if st.button("➕ Clone to my watchlist", key=f"clone_{_sl['id']}"):
                    _cur = load_watchlist()
                    _have = {t["symbol"] for t in _cur}
                    _added = 0
                    for _t in _sl["tickers"]:
                        if isinstance(_t, dict) and _t.get("symbol") and _t["symbol"] not in _have:
                            _cur.append({"symbol": _t["symbol"], "industry": _t.get("industry", "Misc")})
                            _have.add(_t["symbol"]); _added += 1
                    save_watchlist(_cur)
                    st.success(f"Added {_added} new ticker(s) to your watchlist.")
            if _sl["is_own"]:
                with _lc2:
                    if st.button("🗑 Delete", key=f"dellist_{_sl['id']}"):
                        delete_shared_watchlist(_sl["id"]); st.rerun()

    # ── My Profile ──────────────────────────────────────────────────────────
    with _tab_profile:
        _counts = follow_counts()
        st.markdown(f"### {_esc(_me_prof['avatar'])} {_esc(_me_prof['display_name'])}")
        st.caption(f"**{_counts['followers']}** followers · **{_counts['following']}** following")
        with st.form("edit_profile"):
            _bio = st.text_area("Bio", value=_me_prof.get("bio") or "",
                                max_chars=_community.MAX_BIO_LEN,
                                placeholder="A line about your investing style…")
            _av = st.text_input("Avatar emoji", value=_me_prof["avatar"], max_chars=8)
            _pub = st.checkbox("Public profile — appear in the member list & be followable",
                               value=_me_prof["is_public"])
            _sr = st.checkbox("Share my track record — show my verified returns on the leaderboard",
                              value=_me_prof["share_returns"])
            if st.form_submit_button("Save profile", type="primary"):
                update_profile(bio=_bio, avatar=_av, is_public=_pub, share_returns=_sr)
                st.success("Profile saved."); st.rerun()

        st.markdown('<div class="section-header">Members</div>', unsafe_allow_html=True)
        _dir = get_public_profiles()
        _following = get_following_ids()
        if not _dir:
            st.caption("No public members yet.")
        for _m in _dir:
            if _m["user_id"] == UID:
                continue
            _m1, _m2 = st.columns([4, 1])
            with _m1:
                st.markdown(f"**{_esc(_m['avatar'])} {_esc(_m['display_name'])}**  \n"
                            f"<small style='color:#64748b'>{_esc(_m.get('bio') or '')}</small>",
                            unsafe_allow_html=True)
            with _m2:
                if _m["user_id"] in _following:
                    if st.button("Following", key=f"dir_unf_{_m['user_id']}"):
                        unfollow(_m["user_id"]); st.rerun()
                else:
                    if st.button("Follow", key=f"dir_f_{_m['user_id']}", type="primary"):
                        follow(_m["user_id"]); st.rerun()

        _blocked = get_blocked_ids()
        if _blocked:
            st.markdown('<div class="section-header">Blocked</div>', unsafe_allow_html=True)
            for _bid in _blocked:
                _bp = get_profile(_bid)
                _b1, _b2 = st.columns([4, 1])
                with _b1:
                    st.markdown(f"{_esc(_bp['avatar'])} {_esc(_bp['display_name'])}")
                with _b2:
                    if st.button("Unblock", key=f"unblk_{_bid}"):
                        community_unblock(_bid); st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# HOW IT WORKS
# ══════════════════════════════════════════════════════════════════════════════
if page == "How It Works":
    st.markdown("# 📖 How It Works")
    st.markdown("What's behind every recommendation — and the dials you can turn yourself.")

    # ── The three ingredients ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">Every score blends three ingredients</div>', unsafe_allow_html=True)
    st.markdown("""<div style="font-size:.85rem;color:#64748b;margin-bottom:.8rem">
      Each stock gets three independent grades from 0–100, blended into one final score.
      These are the exact rules the app uses — nothing hidden.
    </div>""", unsafe_allow_html=True)

    _hc1, _hc2, _hc3 = st.columns(3)
    with _hc1:
        st.markdown("""<div class="metric-card" style="height:100%">
          <div style="font-weight:800;color:#6366f1;font-size:.95rem">🏥 Company Health</div>
          <div style="font-size:.78rem;color:#64748b;margin:.4rem 0 .6rem">Is the business itself strong?</div>
          <div style="font-size:.78rem;color:#475569;line-height:1.7">
            • <b>Price tag (P/E)</b>: under 15 is great, over 40 is expensive<br>
            • <b>Growth vs price (PEG)</b>: under 1 = growth on sale<br>
            • <b>Revenue growth</b>: over 15%/yr is strong<br>
            • <b>Profit margin</b>: over 20% is excellent<br>
            • <b>Debt</b>: low debt/equity earns points<br>
            • <b>Returns on capital (ROE)</b>: over 25% is elite
          </div></div>""", unsafe_allow_html=True)
    with _hc2:
        st.markdown("""<div class="metric-card" style="height:100%">
          <div style="font-weight:800;color:#f59e0b;font-size:.95rem">📈 Price Trend</div>
          <div style="font-size:.78rem;color:#64748b;margin:.4rem 0 .6rem">Is the stock moving the right way?</div>
          <div style="font-size:.78rem;color:#475569;line-height:1.7">
            • <b>RSI</b>: rewards beaten-down bounce setups, flags overheated ones<br>
            • <b>MACD</b>: is momentum turning up or down?<br>
            • <b>Moving averages</b>: price above its 50/200-day lines = uptrend<br>
            • <b>Recent high</b>: near the high = strength; 25%+ below = caution<br>
            • <b>Choppiness</b>: very jumpy prices lose points
          </div></div>""", unsafe_allow_html=True)
    with _hc3:
        st.markdown("""<div class="metric-card" style="height:100%">
          <div style="font-weight:800;color:#10b981;font-size:.95rem">📰 News Mood</div>
          <div style="font-size:.78rem;color:#64748b;margin:.4rem 0 .6rem">What's the story around it?</div>
          <div style="font-size:.78rem;color:#475569;line-height:1.7">
            • AI (Claude) reads each stock's recent headlines<br>
            • Scores the mood 0 (very negative) to 100 (very positive), 50 = neutral<br>
            • The qualitative ingredient — it reads language, not numbers<br>
            • Needs the owner's AI key; falls back to neutral 50 without it
          </div></div>""", unsafe_allow_html=True)

    # ── Regime table ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">The mix changes with the market\'s mood</div>', unsafe_allow_html=True)
    st.markdown("""
| Market mood | 🏥 Health | 📈 Trend | 📰 News | Why |
|---|---|---|---|---|
| **Calm** (VIX < 18) | 50% | 30% | 20% | Quiet markets reward strong businesses |
| **Mixed** (VIX 18–28) | 35% | 35% | 30% | No single force dominates |
| **Stormy** (VIX > 28) | 20% | 35% | 45% | Headlines move prices faster than balance sheets |
""")
    st.caption("The app checks the VIX ('fear index') and has AI read the day's macro headlines to pick the row. "
               "Unless you override it below.")

    # ── Score → action ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">From score to suggestion</div>', unsafe_allow_html=True)
    st.markdown("""
| Final score | Call | Meaning |
|---|---|---|
| 75–100 | 🟢 Strong Buy | Very strong signals — up to 5% of portfolio suggested |
| 60–74 | 🔵 Buy | Good signals — up to 3% suggested |
| 45–59 | 🟡 Watch | Wait and see — no purchase suggested |
| 0–44 | 🔴 Avoid | Stay away for now |
""")
    st.markdown("""<div style="font-size:.8rem;color:#64748b;margin-top:.3rem">
      Extras that adjust the final result: when all three ingredients agree, a pick is marked
      <b style="color:#15803d">✅ models agree</b>; when they clash it's marked
      <b style="color:#b45309">⚠️ mixed signals</b> and the Stock Advisor planner automatically
      bets less on it. The planner also caps any single stock and sector, and won't add to
      positions that are already a big slice of your portfolio.
    </div>""", unsafe_allow_html=True)

    # ── Your factor mix ───────────────────────────────────────────────────────
    st.markdown('<div class="section-header">🎛 Your factor mix</div>', unsafe_allow_html=True)
    st.markdown("""<div style="font-size:.85rem;color:#64748b;margin-bottom:.6rem">
      Prefer to trust company numbers over headlines? Or ride trends? Set your own mix here —
      it applies to <b>every analysis you run</b> from now on (just yours, not other users').
    </div>""", unsafe_allow_html=True)

    _settings = load_user_settings()
    _saved_w = _settings.get("weights") or {}
    _mode_options = ["Auto — adjusts with the market (recommended)", "Custom — my own mix"]
    _mode_idx = 1 if _settings.get("weights_mode") == "custom" else 0
    _mode_pick = st.radio("Weight mode", _mode_options, index=_mode_idx,
                          horizontal=True, key="hiw_mode", label_visibility="collapsed")

    _is_custom = _mode_pick.startswith("Custom")
    _mc1, _mc2, _mc3 = st.columns(3)
    _hw_fund = _mc1.slider("🏥 Company Health", 0, 100, int(_saved_w.get("fund", 35)),
                           disabled=not _is_custom, key="hiw_fund")
    _hw_tech = _mc2.slider("📈 Price Trend", 0, 100, int(_saved_w.get("tech", 35)),
                           disabled=not _is_custom, key="hiw_tech")
    _hw_sent = _mc3.slider("📰 News Mood", 0, 100, int(_saved_w.get("sent", 30)),
                           disabled=not _is_custom, key="hiw_sent")

    if _is_custom:
        _hw_total = _hw_fund + _hw_tech + _hw_sent
        if _hw_total > 0:
            st.caption(f"Your mix → Health {_hw_fund/_hw_total*100:.0f}% · "
                       f"Trend {_hw_tech/_hw_total*100:.0f}% · News {_hw_sent/_hw_total*100:.0f}% "
                       "(sliders are relative — I balance them for you)")
        else:
            st.warning("At least one slider needs to be above zero.")

    if st.button("💾 Save my mix", type="primary", key="hiw_save"):
        if _is_custom and (_hw_fund + _hw_tech + _hw_sent) == 0:
            st.error("At least one slider needs to be above zero.")
        else:
            _settings["weights_mode"] = "custom" if _is_custom else "auto"
            if _is_custom:
                _settings["weights"] = {"fund": _hw_fund, "tech": _hw_tech, "sent": _hw_sent}
            save_user_settings(_settings)
            st.success("Saved! Your next analysis will use "
                       + ("your custom mix." if _is_custom else "the automatic market-aware mix."))

    _current_mode = "custom" if _settings.get("weights_mode") == "custom" else "auto"
    st.caption(f"Currently active: **{'🎛 your custom mix' if _current_mode == 'custom' else '🤖 automatic (market-aware)'}** · "
               "You can also try one-off what-if mixes on the 🎯 Stock Advisor page without saving anything.")

    st.caption("⚠️ This is an educational tool, not financial advice. The scoring rules are transparent "
               "heuristics based on common investing conventions — they have not been backtested, and "
               "AI models can be wrong. Always do your own research.")


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Settings":
    st.markdown("# Settings")

    # ── API Key (owner only — it's shared by the whole app) ──────────────────
    st.markdown("### 🔑 API Key")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not USER.get("is_owner"):
        st.caption("The AI key is managed by the app owner."
                   + (" AI features are active. ✅" if has_key else " AI features are currently off."))
    elif has_key:
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
                        st.dataframe(result["raw_table"], width="stretch")
            else:
                st.markdown("**Preview — positions found in PDF:**")
                st.dataframe(pd.DataFrame(positions), width="stretch")
                if cash_val:
                    st.caption(f"Cash / money market detected: **${cash_val:,.2f}**")

                col_p1, col_p2 = st.columns([1, 3])
                with col_p1:
                    pdf_import_cash = st.checkbox("Also import cash balance", value=bool(cash_val), key="pdf_cash_chk")
                with col_p2:
                    pdf_overwrite   = st.checkbox("Replace all existing positions", value=True, key="pdf_ow_chk")

                if st.button("✅  Import PDF holdings", type="primary", key="pdf_import_btn"):
                    _bkp = backup_holdings()   # snapshot current holdings for undo
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
                    log_import(source="PDF", filename=getattr(pdf_file, "name", "statement.pdf"),
                               n_positions=len(positions),
                               cash=(cash_val if pdf_import_cash and cash_val else 0),
                               mode=("replace" if pdf_overwrite else "merge"), backup_path=_bkp)
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
                st.dataframe(preview_df, width="stretch", height=350)

                if csv_cash:
                    st.info(f"💵 Cash & money market detected: **${csv_cash:,.2f}**")

                # ── Import options ────────────────────────────────────────────
                ci1, ci2, ci3 = st.columns(3)
                with ci1: import_cash   = st.checkbox("Import cash balance", value=bool(csv_cash), key="csv_cash_chk")
                with ci2: overwrite     = st.checkbox("Replace existing positions", value=True, key="csv_ow_chk")
                with ci3: add_to_wl     = st.checkbox("Also add tickers to watchlist", value=True, key="csv_wl_chk")

                if st.button("✅  Import into Stock Advisor", type="primary", key="csv_import_btn"):
                    _bkp = backup_holdings()   # snapshot current holdings for undo
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
                    log_import(source="CSV", filename=getattr(uploaded, "name", "positions.csv"),
                               n_positions=len(positions),
                               cash=(csv_cash if import_cash and csv_cash else 0),
                               mode=("replace" if overwrite else "merge"), backup_path=_bkp)

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

    # ── Import history + undo ─────────────────────────────────────────────────
    _imports = get_imports(limit=10)
    if _imports:
        st.markdown("#### 🧾 Recent imports")
        _last_imp = _imports[0]
        if _last_imp.get("backup_path"):
            _lc1, _lc2 = st.columns([3, 1])
            with _lc1:
                st.caption(f"Last import: **{_last_imp['n_positions']}** position(s) from "
                           f"{_last_imp['source']} ({_last_imp['mode']}) on "
                           f"{(_last_imp['imported_at'] or '')[:16].replace('T',' ')} UTC. "
                           "Undo restores the holdings you had just before it.")
            with _lc2:
                if st.button("↩️ Undo last import", key="undo_import_btn"):
                    if restore_holdings(_last_imp["backup_path"]):
                        st.success("Holdings restored to the pre-import snapshot.")
                        st.rerun()
                    else:
                        st.error("Backup file is no longer available — can't undo.")
        _imp_df = pd.DataFrame(_imports)[["imported_at", "source", "filename", "n_positions", "cash", "mode"]].copy()
        _imp_df["imported_at"] = _imp_df["imported_at"].str[:16].str.replace("T", " ")
        _imp_df.columns = ["When (UTC)", "Source", "File", "Positions", "Cash", "Mode"]
        st.dataframe(
            _imp_df.style.format({"Cash": "${:,.0f}"}, na_rep="—"),
            use_container_width=True, height=min(280, 60 + len(_imp_df) * 36),
        )

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


# ── Fill the Dashboard's performance slot (function is defined above by now) ──
if page == "Dashboard" and "_perf_slot" in globals():
    with _perf_slot:
        _render_performance_section()
