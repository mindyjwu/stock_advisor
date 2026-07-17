# 📈 Stock Advisor

An AI-powered, multi-user stock advisory dashboard built with Streamlit. It grades
every stock on your watchlist with a transparent three-factor model, turns any cash
deposit into a diversified buy plan in plain English, scans the S&P 500 for new ideas,
and traces the supply chains of your best holdings to find niche picks.

> ⚠️ **Educational tool, not financial advice.** The scoring rules are transparent
> heuristics based on common investing conventions — they have not been backtested,
> and AI models can be wrong. Always do your own research before placing real trades.

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
  sell_signals.py   🔻 When-to-sell engine for holdings
  track_record.py   Cached verified-return metric (leaderboard)
  alerts.py         Alert trigger rules
scripts/
  run_analysis.py       Watchlist analysis pipeline (parallel)
  market_scan.py        Two-pass S&P 500 scan (bulk downloads)
  alert_poller.py       Background market-hours alert poller (owner)
  migrate_to_postgres.py  Copy an existing SQLite DB into Postgres
data/
  loader.py         Market data fetching + per-user storage
  sp500.py          S&P 500 universe
  pdf_import.py     Chase/JPM PDF statement parser
db/
  connection.py     Backend abstraction (SQLite default, Postgres via DATABASE_URL)
  store.py          Suggestions, picks, alerts, scans, snapshots, decisions, imports
  users.py          Accounts + PBKDF2 auth + login lockout
  community.py      Profiles, follows, posts, likes, shared lists, blocks, reports
api/                FastAPI backend over the same engine (see api/README.md)
web/                Next.js community frontend (see web/README.md)
tests/              pytest suite (runs on SQLite and Postgres)
```

## Development & testing

```bash
pip install -r requirements-dev.txt
pytest                              # runs against SQLite
DATABASE_URL=postgresql://… pytest  # also runs against Postgres
```

CI (`.github/workflows/ci.yml`) runs the suite on **both** SQLite and a Postgres
service, plus the web `next build`, on every push and PR. Dependencies are
pinned (`requirements.txt`) so installs are reproducible.

## Deployment

- **SQLite (default)** — zero config; state lives in `db/advisor.db` + per-user
  JSON. Host on a machine with a **persistent disk**; ephemeral platforms wipe
  accounts on restart.
- **Postgres** — set `DATABASE_URL`; migrate existing data with
  `python3 scripts/migrate_to_postgres.py`. Recommended for real/concurrent use.
- **Docker** — `cp .env.docker.example .env`, set `API_SECRET` +
  `ANTHROPIC_API_KEY`, then `docker compose up --build` brings up Postgres, the
  API (`:8000`), Streamlit (`:8501`), and the web app (`:3000`).
- **Security** — set a strong `API_SECRET` for the API (it refuses to start with
  the dev default when `APP_ENV=production`); accounts lock for 15 min after 5
  failed logins.

## Configuration notes

- **AI model** — pick Sonnet / Opus / Haiku from the sidebar; the key lives in
  `.env` (`ANTHROPIC_API_KEY`) and is managed by the owner. Without a key the app
  still works: sentiment scores neutral and regime falls back to the VIX rule.
- **Data privacy** — holdings, per-user data, the SQLite DB, and `.env` are all
  gitignored; nothing personal is committed.
- **Costs** — analyses use one batched Claude call for sentiment; the market scan
  adds one more; supply-chain discovery is one call per click. All users share the
  owner's API key.
- **Hosting caveat** — with the default SQLite backend, state lives in SQLite +
  JSON files on disk, so host on a machine with a persistent disk. For
  hosted/ephemeral platforms, use **Postgres** (`DATABASE_URL`) so accounts and
  portfolios survive restarts. See the **Deployment** section above.
