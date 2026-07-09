# Stock Advisor — Enhancement Roadmap

A review of the current codebase with concrete suggestions across five areas:
customization, trackability, accessibility, secure data handling, and the path
to multi-user login + a social stock community.

**Current architecture (for context):** a Streamlit app backed by JSON files
and a local SQLite database (`db/advisor.db`), yfinance for market data, and
Anthropic models for sentiment/regime analysis.

> **Status note (updated):** since this roadmap was first written, `main` has
> independently landed a **multi-user login** layer (`app/auth.py`,
> `db/users.py`) and moved data into **per-user folders** (`data/users/`) via a
> loader rewrite — i.e. much of Phase 1 hygiene and Phase 2 foundation is
> already underway on `main`. This document is kept as the north-star roadmap;
> the sequencing table at the bottom reflects what's since been superseded.

---

## 1. Customization

Today, a lot of "user preference" material is hardcoded in `app/dashboard.py`:

- `_THEME_MAP` (ticker → industry theme, ~60 tickers) is a hardcoded dict.
- `INDUSTRIES`, action colors, pie colors, and the AI model list are constants.
- Copy is hardwired to one broker ("Imported from J.P. Morgan", "Import from
  Chase").
- The 5-minute auto-refresh interval and score thresholds are fixed.

**Suggestions**

| Area | Change |
|---|---|
| User settings store | Add a `user_settings` table (or `settings.json` per user) for preferences instead of constants in code. |
| Theme mapping | Move `_THEME_MAP` into the DB and add a Settings editor so users can re-tag any ticker's theme. Fall back to yfinance `sector` for unknown tickers instead of "Other". |
| Appearance | Light/dark mode toggle (the sidebar is dark, main panel is light — make it one coherent, switchable theme via `config.toml` + CSS variables). |
| Analysis knobs | Let users override regime weights (fundamentals/technicals/sentiment), risk tolerance for the position sizer, and score thresholds for Buy/Watch/Avoid. |
| Refresh cadence | Make the `st_autorefresh` interval a setting (off / 1m / 5m / 15m) — 5 min of background yfinance calls isn't right for everyone. |
| Multiple watchlists | Support named watchlists ("Dividend", "AI plays", "Speculative") instead of one global list. |
| Broker-agnostic import | Generalize the CSV importer: the column-detection logic in Settings already handles aliases — expose a column-mapping UI when auto-detection fails so Fidelity/Schwab/Robinhood exports work too. |

---

## 2. Trackability (audit trail & performance tracing)

The SQLite layer (`db/store.py`) already logs every suggestion with scores,
regime, and prices — a good foundation. Gaps:

- **No portfolio history.** Portfolio value is computed live from
  `holdings.json`; there's no time series, so no equity curve, no "how has my
  portfolio done since I started using this."
- **No record of what the user actually did.** Suggestions are logged, but
  whether you bought is not — so "Performance" measures the advisor, not you.
- **No import audit.** CSV/PDF imports overwrite `holdings.json` with no
  history and no undo.
- **No model provenance.** `suggestions` stores the regime but not which AI
  model produced the sentiment/regime call, so runs aren't comparable.

**Suggestions**

1. `portfolio_snapshots` table: on every analysis run (and via the alert
   poller daily), store `date, total_value, equity_value, cash, total_gl`.
   Chart it as an equity curve on the Performance page, benchmarked vs SPY.
2. `decisions` table: a "Mark as bought/passed" button on each suggestion
   card, recording price and date. Performance page then gets two tabs:
   *Advisor accuracy* vs *My actual results*.
3. `imports` table: log timestamp, source (CSV/PDF), row count, and keep the
   previous `holdings.json` as a versioned copy (`holdings.2026-07-02.json`)
   so an import is reversible.
4. Add `model_id` and `weights_used` columns to `suggestions`; stamp every
   row with the app git version too.
5. Data export: one-click download of all history (suggestions, snapshots,
   decisions) as CSV — users should own their data.

---

## 3. Accessibility

The UI is visually polished but leans heavily on raw HTML via
`unsafe_allow_html`, which hurts assistive-tech users. Specific issues found:

- **Contrast failures.** Body-copy grays (`#94a3b8`, `#64748b`) at 0.65–0.78rem
  on white fail WCAG AA (4.5:1). Sidebar secondary text (`#475569` on
  `#0a0d14`) is borderline.
- **Tiny fixed font sizes.** Many elements are 0.65–0.72rem (~10px). WCAG
  wants zoom-friendly relative sizes; keep a ~0.8rem floor.
- **Color-only meaning.** G/L and action badges rely on green/red alone —
  problematic for the ~8% of men with color-vision deficiency. The ▲/▼ arrows
  used in some places should be used everywhere a value is color-coded.
- **Custom HTML metric cards** replace `st.metric`, losing Streamlit's
  built-in semantics; screen readers get anonymous `<div>`s.
- **Nav state is CSS-only.** The active page is conveyed by a gradient +
  `▶` prefix; there's no `aria-current`. The hidden radio (`display:none`)
  removed the accessible fallback.
- **Charts have no text alternative.** Pie/radar/sparklines are canvas-only;
  sparklines render with no label at all.
- **Hidden chrome.** `#MainMenu, footer {visibility:hidden}` also removes the
  keyboard-reachable settings/screen-reader toggle.

**Suggestions (roughly in impact order)**

1. Bump minimum text to 0.8rem and darken secondary grays to `#475569`+ on
   white / `#94a3b8`+ on dark; run the palette through a contrast checker.
2. Pair every color signal with a symbol or word (▲/▼, "+"/"−", badge text).
3. Prefer native `st.metric`, `st.dataframe`, and `st.tabs` over hand-rolled
   HTML wherever the styling delta is small.
4. Give each chart a data-table twin (`st.expander("View as table")`) — the
   drill-down table under the pies already does this pattern; extend it.
5. Add visible keyboard focus styles for the nav buttons and keep Streamlit's
   default menu available.
6. Respect `prefers-reduced-motion` for transitions and consider making
   auto-refresh opt-in (unexpected page reruns are disorienting for
   screen-reader users mid-read).

---

## 4. Secure data upload & storage (private user data)

What's good already: `.gitignore` excludes `.env`, `holdings.json`, and
`db/*.db`, so personal holdings and keys aren't committed. Uploads are parsed
in-memory with pandas/pdfplumber and never written to disk raw.

What needs attention **before this app is ever exposed to the internet**:

1. **No authentication at all.** If deployed as-is (Streamlit Cloud, a VPS),
   anyone with the URL sees the full portfolio, can edit holdings, and can
   trigger paid API calls. Auth (section 5) is a hard prerequisite to
   deployment, not a feature.
2. **The API-key form clobbers `.env`.** Settings does
   `env_path.write_text(f"ANTHROPIC_API_KEY={key}\n")` — it overwrites the
   whole file, dropping any other variables, and stores the key in plaintext
   from a browser form. Prefer: keys set server-side only (env var /
   `st.secrets`); if users must paste a key, hold it in
   `st.session_state` for the session and never write it to disk.
3. **`data/watchlist.json` is committed to git.** The personal watchlist
   (which mirrors real holdings after a CSV import) is public if the repo is.
   Move user watchlists out of the repo into the DB and keep only a small
   demo watchlist as a seed file.
4. **Statement parsing should scrub PII.** Chase PDFs contain the account
   number and name; only ticker/qty/cost fields should survive parsing (audit
   `data/pdf_import.py` for this), and the raw upload should never be
   persisted.
5. **Encryption at rest for holdings.** Once multi-user, store holdings in a
   real database (Postgres) with per-user rows; encrypt sensitive columns
   (e.g., Fernet with a server-side key) or use SQLCipher if staying on
   SQLite. Dollar amounts of a person's portfolio are sensitive financial
   data.
6. **Upload hygiene.** Enforce file-size limits (`server.maxUploadSize`),
   validate MIME/type beyond extension, and wrap the PDF parser in a
   timeout — pdfplumber on a hostile PDF is a DoS vector.
7. **Transport & sessions.** HTTPS only (reverse proxy w/ TLS), secure/HTTP-only
   session cookies, and rate-limit the analysis button (each click spends
   Anthropic tokens).

---

## 5. Multi-user login

The data model is the real work — auth itself is a solved problem.

**Auth options, in order of recommendation**

1. **Streamlit native OIDC (`st.login`)** — Streamlit ≥1.42 supports
   Google/Auth0/etc. login out of the box. Least code, no password storage
   liability, and "Sign in with Google" is what most users want anyway.
2. **`streamlit-authenticator`** — bcrypt-hashed local accounts with cookie
   sessions, if you want self-contained email/password.
3. **Supabase Auth + Postgres** — heavier, but you get the database,
   row-level security, and social login in one service, which dovetails with
   the community features below.

**Data-model changes required**

- Add a `users` table (`id, email, display_name, created_at, settings_json`).
- Add `user_id` foreign keys to `suggestions`, `saved_picks`, `alerts`, plus
  new `watchlists`, `holdings`, and `portfolio_snapshots` tables — i.e., the
  JSON files (`watchlist.json`, `holdings.json`) move into the database.
- Every query in `db/store.py` gains a `user_id` filter; every
  `load_*/save_*` in `data/loader.py` becomes DB-backed and user-scoped.
- Replace module-level `lru_cache` with `st.cache_data(ttl=...)` — market
  data is shareable across users (cache by symbol), but the current
  process-wide cache with no TTL serves stale prices and won't scale.
- Per-user API keys (optional): encrypted column, or one server key with
  per-user usage quotas.

SQLite is fine to prototype multi-user, but move to **Postgres** before real
users: concurrent Streamlit sessions writing SQLite will hit lock contention.

---

## 6. Social stock community

Absolutely feasible, and the suggestion/score history gives it a genuinely
interesting hook (verifiable track records). Recommended approach: build the
**community MVP inside Streamlit first**, and only migrate the frontend if it
takes off.

**Phase A — MVP (Streamlit, post-login)**

- **Profiles**: display name, avatar, bio, and an opt-in public track record.
- **Privacy-first sharing**: share *percentages and picks*, never dollar
  amounts — e.g., "up 12.4% since March, top pick NVDA +38%". Private by
  default; each shareable element individually opt-in.
- **Shared watchlists**: publish a watchlist; others can follow or clone it.
- **Leaderboard**: rank by verified return % (computed from logged
  suggestions/decisions, so it can't be self-reported — that's the moat).
- **Ticker discussion**: a comment thread per ticker, shown alongside the
  AI analysis card.
- **Follow feed**: "X saved AAPL", "Y published a new watchlist".

Schema additions: `follows(follower_id, followed_id)`,
`posts(id, user_id, ticker, body, created_at)`, `shared_watchlists`,
`likes`, plus a `visibility` column on shareable entities.

**Phase B — if the community grows**

Streamlit's rerun-the-whole-script model gets awkward for feeds, notifications,
and real-time interaction. The clean migration path:

- Keep `agents/`, `scripts/`, and the DB layer as-is — they're already
  UI-independent.
- Wrap them in a **FastAPI** backend (auth, REST/WebSocket endpoints).
- Build the social frontend in **Next.js/React**; optionally keep Streamlit
  as the internal analysis dashboard.

**Non-negotiables for a social finance product**

- Prominent "not investment advice" disclaimers on all shared picks and on
  signup; AI-generated content clearly labeled.
- Moderation: report/block, rate limits, and spam controls from day one —
  finance communities attract pump-and-dump behavior specifically.
- Terms of service + privacy policy before accepting other people's
  financial data.

---

## Suggested sequencing

| Phase | Scope |
|---|---|
| **1. Hygiene** | Fix `.env` overwrite (merge + immediate activation); un-track `watchlist.json` (seed from `watchlist.example.json`, included here); safe fallbacks for missing data files; accessibility pass (WCAG AA contrast, 0.75rem font floor, `:focus-visible` outlines, `prefers-reduced-motion`); extract hardcoded config to `app/config.py` (included here — not yet wired into `main`'s dashboard). *Note: `main` already addressed parts of this in its own loader/dashboard rewrite; remaining items (accessibility on the new design, wiring `config.py`) are good follow-ups.* |
| **2. Foundation** | Login (`app/auth.py`) and per-user data folders exist. ✅ Added: **portfolio snapshots** (daily equity curve on the Performance page), **decisions** (Bought/Passed tracking → "your actual results"), and an **import audit log** with one-click undo (versioned holdings backup). ⏳ Remaining: **Postgres migration** — deferred as a deploy-time task (needs a provisioned Postgres instance; SQLite is fine for now). |
| **3. Community MVP** | Profiles, opt-in sharing, shared watchlists, leaderboard, ticker threads — all inside Streamlit. |
| **4. Scale-out (if warranted)** | FastAPI backend + Next.js frontend; Streamlit stays as the analysis engine UI. |
