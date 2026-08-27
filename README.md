# 📈 Stock Advisor

I spend a chunk of my actual job reading data and turning it into information a non-analyst can act on — first at KPMG building BI dashboards off retail sales data, now scoping AI systems for media clients. This is that instinct pointed at my own portfolio instead of a client's.

It's a multi-user stock advisory dashboard that grades every stock on your watchlist with a transparent three-factor model, turns a cash deposit into a diversified buy plan in plain English, scans the S&P 500 for new ideas, and traces the supply chains of your best holdings to find smaller companies riding the same trend.

**⚠️ Educational tool, not financial advice.** The scoring rules are heuristics based on common investing conventions — not backtested, and the AI layer can be wrong like any model can. Do your own research before trading on anything this says.

## What it actually does

- **Invest My Cash** — enter a deposit, pick a risk style, get a concrete buy plan: conviction-weighted dollars, per-stock and per-sector caps, a concentration guard so it won't tell you to buy more of what you already hold too much of, and a copy-paste order checklist.
- **Three-factor scoring** — every stock gets 0–100 grades across Company Health (P/E, PEG, revenue growth, margins, debt, ROE), Price Trend (RSI, MACD, moving averages, drawdown), and News Mood (Claude reads recent headlines and grades sentiment). A market-regime detector — VIX plus an AI read on the tape — decides how much weight each factor gets, or you can lock in your own mix.
- **Agreement signal** — when all three models agree, the pick gets flagged; when they disagree, the position size shrinks automatically instead of me having to remember to be cautious.
- **Market Scan** — a two-pass sweep of the S&P 500 (a cheap screen first, then one batched AI call on the shortlist so it doesn't burn API credits scoring 500 stocks individually), tagged by style and checked against what I already hold.
- **Supply-chain discovery** — the part I'm most pleased with. It maps the supply chain behind your best-performing holdings (AI chips → datacenters → electricity, say) and surfaces smaller public companies riding the same trend, with every ticker checked against live data before it's shown to you.
- **Whale Watch** — what well-known funds report owning via their public 13F filings (Buffett, Ackman, Burry, and others), diffed against their last filing so you can see what they added, trimmed, or dropped. Reference only — 13F data is up to 45 days stale by the time it's public, so it never feeds the scoring itself.
- **A performance page that doesn't flatter me** — every past suggestion, tracked against what actually happened. If the model's wrong a lot in some window, that shows up here instead of getting quietly buried.
- **Multi-user accounts**, salted password hashing, fully isolated data per user, and a broker-CSV/PDF import so you're not retyping your holdings by hand.

## Stack

Python + Streamlit for the core app, `yfinance` for market data, Claude (Sonnet/Opus/Haiku, switchable per session) for the AI scoring layer, SQLite by default with an optional Postgres backend. There's also an optional second frontend — a FastAPI + Next.js community app — for the social features (leaderboard, threads, shared watchlists) if you want a lighter browser-native surface for those without the full analysis dashboard. See `api/README.md` and `web/README.md` for that half.

## Quick start

```bash
git clone https://github.com/mindyjwu/stock_advisor.git
cd stock_advisor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# optional but recommended — enables News Mood, regime detection,
# and supply-chain discovery
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

streamlit run app/dashboard.py
```

Open `http://localhost:8501` and create an account. **The first account created becomes the app owner** and inherits any pre-existing single-user data — make your own account before sharing the app with anyone else.

## How the scoring actually blends

```
Market data (yfinance)         Market regime (VIX + AI)
        │                              │
        ├─► Company Health ─┐          │ sets the blend weights
        ├─► Price Trend ────┼─► Blended score 0–100 ─► Strong Buy / Buy / Watch / Avoid
        └─► News Mood ──────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                     ▼
  Invest Cash plan       Scan picks              Alerts
```

| Market mood | Company Health | Price Trend | News Mood |
|---|---|---|---|
| Calm (VIX < 18) | 50% | 30% | 20% |
| Mixed (VIX 18–28) | 35% | 35% | 30% |
| Stormy (VIX > 28) | 20% | 35% | 45% |

Thresholds: 75+ Strong Buy, 60+ Buy, 45+ Watch, below 45 Avoid. Weights are overridable per account.

## What's under the hood, if you want to poke around

```
app/
  dashboard.py        Streamlit UI
  auth.py              Sign-in / sign-up
  agents/              fundamentals.py, technicals.py, sentiment.py, regime.py,
                        allocator.py, screener.py, supply_chain.py,
                        sell_signals.py, track_record.py, alerts.py, whale_watch.py
scripts/               run_analysis.py, market_scan.py, alert_poller.py,
                        run_alerts.py, migrate_to_postgres.py
data/                  loader.py, sp500.py, pdf_import.py
db/                    connection.py, store.py, users.py, community.py
api/ + web/            optional FastAPI + Next.js community frontend
tests/                 pytest, runs against both SQLite and Postgres
```

## Development & CI

```bash
pip install -r requirements-dev.txt
pytest                                    # against SQLite
DATABASE_URL=postgresql://… pytest        # also against Postgres
```

CI runs the suite against both databases plus a `web` build on every push. Dependencies are pinned so installs stay reproducible.

## Deployment notes

- **SQLite** (default) — zero config, but state lives on disk, so host somewhere with a persistent volume. Ephemeral platforms wipe accounts on restart.
- **Postgres** — set `DATABASE_URL`; there's a migration script for moving existing SQLite data over.
- **Docker** — `docker compose up --build` brings up Postgres, the API, Streamlit, and the web app together.
- Set a real `API_SECRET` before running with `APP_ENV=production` — it refuses to boot on the dev default.
- Email alerts are optional (SMTP env vars); without them, alerts still show in-app, they just don't get emailed.

## Honest limitations

- The AI model picked in the sidebar and the API key both live at the owner level right now — every user on a shared deployment shares one key.
- Sentiment scoring falls back to neutral without an API key, and regime detection falls back to the plain VIX rule.
- This has never been backtested against a real trading account. Treat the grades as a structured opinion, not a signal.
