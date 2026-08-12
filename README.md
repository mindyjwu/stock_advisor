# 📈 Stock Advisor

An AI-powered, multi-user stock advisory dashboard built with Streamlit. It grades
every stock on your watchlist with a transparent three-factor model, turns any cash
deposit into a diversified buy plan in plain English, scans the S&P 500 for new ideas,
and traces the supply chains of your best holdings to find niche picks.

> ⚠️ **Educational tool, not financial advice.** The scoring rules are transparent
> heuristics based on common investing conventions — they have not been backtested,
> and AI models can be wrong. Always do your own research before placing real trades.

## Tech stack

| Layer | Tech |
|---|---|
| Core app | Python, [Streamlit](https://streamlit.io) |
| Market data | [yfinance](https://github.com/ranaroussi/yfinance) |
| AI scoring | [Anthropic Claude](https://www.anthropic.com) (Sonnet / Opus / Haiku) |
| Storage | SQLite by default, optional Postgres (`DATABASE_URL`) |
| Optional API + web frontend | [FastAPI](https://fastapi.tiangolo.com) (`api/`) + [Next.js](https://nextjs.org)/TypeScript (`web/`) |

The Streamlit app (`app/dashboard.py`) is the primary, fully-featured product —
everything in **Features** below lives there. `api/` and `web/` are an optional
second frontend for the community/social features only (see
[Community web app](#community-web-app-optional)).

## Features

- **💰 Invest My Cash** — enter a deposit amount, pick a risk style (Cautious /
  Balanced / Aggressive), and get a concrete buy plan: conviction-weighted dollars,
  per-stock and per-sector caps, a concentration guard against over-buying what you
  already hold, and a copy-paste order checklist.
- **Three-factor scoring** — every stock gets 0–100 grades for
  **🏥 Company Health** (P/E, PEG, revenue growth, margins, debt, ROE),
  **📈 Price Trend** (RSI, MACD, moving averages, drawdown, choppiness), and
  **📰 News Mood** (Claude reads recent headlines). A market-regime detector
  (VIX + AI) sets the blend weights — or each user saves their own custom mix.
- **Agreement signal** — picks where all three models agree are flagged
  ✅; conflicting models flag ⚠️ and automatically shrink the position size.
- **🔭 Market Scan** — two-pass scan of ~500 S&P stocks (cheap screen, then one
  batched AI call for the shortlist), style-tagged (Value / Growth / Momentum /
  Quality / Dividend), sector-diversified, and personalized against your portfolio.
  Click any row for a deep-dive with chart, stats, and news.
- **🔗 Supply-chain discovery** — AI maps the supply chains of your best-performing
  holdings (e.g. AI chips → datacenters → electricity) and suggests smaller public
  companies riding the same trend; every ticker is validated against live data first.
- **🔔 Alerts** — Strong-Buy flips, price-target hits, big daily moves, and scan
  discoveries you don't own yet; optional macOS notification poller.
- **🐋 Whale Watch** — what well-known investors' funds report owning, straight
  from their public SEC 13F filings (Buffett, Ackman, Icahn, Burry, Druckenmiller,
  Dalio, Tepper, Soros), with New/Added/Reduced/Sold-Out badges vs. their prior
  filing and a cross-reference against your own watchlist. Reference only — it
  never feeds into this app's own scoring, and 13F data is up to 45 days stale
  by the time it's public. Includes a Trump/DJT card, since the President doesn't
  file a 13F and there's no equivalent structured feed for his holdings.
- **📊 Performance** — the honest report card: how every past suggestion actually
  did, across multiple time windows.
- **📖 How It Works** — the full scoring rulebook in plain English, plus per-user
  factor-weight controls.
- **Multi-user accounts** — sign-up/sign-in with salted PBKDF2 password hashing;
  every user's watchlist, holdings, history, scans, and settings are fully isolated.
- **Broker import** — upload a Chase / J.P. Morgan positions CSV or PDF to populate
  your portfolio.

## Quick start

Requires **Python 3.9+**.

```bash
git clone https://github.com/mindyjwu/stock_advisor.git
cd stock_advisor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional but recommended — enables News Mood, regime detection,
# and supply-chain discovery:
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

streamlit run app/dashboard.py
```

Then open http://localhost:8501 and **create your account**.

> **Important:** the *first* account ever created becomes the app **owner** and
> inherits any pre-existing single-user data (legacy `data/*.json` files and
> database history). Create your own account before sharing the app with others.
> Later accounts start fresh with a small example watchlist.

## Screens

- **Dashboard** — portfolio KPIs, an equity-curve chart, your logged buy/pass
  decisions, and the performance report card.
- **Stock Advisor** — your watchlist, scored and ranked, with the Invest My
  Cash planner.
- **Scan & Alerts** — the S&P 500 market scan, sell-signal review for your
  holdings, and recent alerts.
- **Community** — opt-in profiles, a verified-returns leaderboard, follow
  feed, per-ticker discussion threads, and shared watchlists.
- **Lists & History** — saved picks and full suggestion history.
- **How It Works** — the scoring rulebook in plain English, plus per-user
  factor-weight controls.
- **Settings** — API key, broker CSV/PDF import, watchlist/holdings editing.

## Community web app (optional)

The social/community features also have a second, standalone frontend: a
[FastAPI](api/) backend and a [Next.js](web/) web app, talking to the same
accounts and database as the Streamlit app. This is optional — the Streamlit
app is fully self-contained — but useful if you want a lighter-weight,
browser-native UI for the community surface (feed, leaderboard, threads,
shared watchlists) without the rest of the analysis dashboard.

```bash
# Terminal 1 — API (from the repo root, after installing requirements.txt)
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000

# Terminal 2 — web app
cd web
npm install
cp .env.local.example .env.local
npm run dev   # http://localhost:3000
```

See [`api/README.md`](api/README.md) and [`web/README.md`](web/README.md) for
endpoints, config, and screen-by-screen details.

## How the recommendation engine works

```
Market data (yfinance)          Market regime (VIX + AI)
   │                                  │
   ├─► 🏥 Company Health ─┐           │  sets the blend weights
   ├─► 📈 Price Trend ────┼─► Blended score 0–100 ─► Strong Buy / Buy / Watch / Avoid
   └─► 📰 News Mood ──────┘           │
                                      ▼
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      Invest Cash plan            Scan picks               Alerts
   (deposit → sized buys)   (styles + portfolio fit)  (flips, targets, finds)
                                      │
                                      ▼
                          Performance report card
```

| Market mood | 🏥 Health | 📈 Trend | 📰 News |
|---|---|---|---|
| Calm (VIX < 18) | 50% | 30% | 20% |
| Mixed (VIX 18–28) | 35% | 35% | 30% |
| Stormy (VIX > 28) | 20% | 35% | 45% |

Score thresholds: **75+** Strong Buy · **60+** Buy · **45+** Watch · below 45 Avoid.
Users can override the weights per-account on the **How It Works** page.

## Project layout

```
app/
  dashboard.py      Streamlit UI — all pages
  auth.py           Sign-in / sign-up gate
agents/
  fundamentals.py   🏥 Company Health rubric
  technicals.py     📈 Price Trend indicators
  sentiment.py      📰 News Mood (batched Claude calls)
  regime.py         Market regime detection + score blending
  allocator.py      Deposit → diversified buy plan
  screener.py       Style tagging + sector-diverse shortlists
  supply_chain.py   AI supply-chain niche discovery
  alerts.py         Alert trigger rules
  whale_watch.py    SEC 13F fetch/parse/diff for the Whale Watch page
scripts/
  run_analysis.py   Watchlist analysis pipeline (parallel)
  market_scan.py    Two-pass S&P 500 scan (bulk downloads)
  alert_poller.py   Background market-hours alert poller (owner)
data/
  loader.py         Market data fetching + per-user storage
  sp500.py          S&P 500 universe
  pdf_import.py     Chase/JPM PDF statement parser
db/
  store.py          SQLite: suggestions, picks, alerts, scans (per user)
  users.py          Accounts + PBKDF2 password auth
  community.py      Profiles, follows, posts, shared watchlists, moderation
  connection.py     Dual-backend (SQLite / Postgres) connection layer
api/
  main.py           FastAPI backend — REST API over the same db/data layer
web/
  app/              Next.js (App Router + TypeScript) community frontend
```

## Configuration notes

- **AI model** — pick Sonnet / Opus / Haiku from the sidebar; the key lives in
  `.env` (`ANTHROPIC_API_KEY`) and is managed by the owner. Without a key the app
  still works: sentiment scores neutral and regime falls back to the VIX rule.
- **Data privacy** — holdings, per-user data, the SQLite DB, and `.env` are all
  gitignored; nothing personal is committed.
- **Costs** — analyses use one batched Claude call for sentiment; the market scan
  adds one more; supply-chain discovery is one call per click. All users share the
  owner's API key.
- **Hosting caveat** — state lives in SQLite + JSON files on disk. Host it on a
  machine with a persistent disk (a small VPS or an always-on Mac). Platforms with
  ephemeral filesystems (e.g. Streamlit Community Cloud) will wipe accounts and
  portfolios on every restart.

## Roadmap / design notes

[`ENHANCEMENTS.md`](ENHANCEMENTS.md) is the original engineering review this
project was built against — customization, trackability, accessibility,
secure data handling, multi-user login, and the social community — with a
sequencing table showing what's shipped vs. still open.
