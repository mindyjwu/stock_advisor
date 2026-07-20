# Stock Advisor — Community Web App

A Next.js (App Router + TypeScript) frontend for the community features,
talking to the FastAPI backend in [`../api`](../api). This is the Phase-4
proof-of-concept for moving the social experience off Streamlit onto a modern
web stack, while the Streamlit dashboard remains the analysis engine's UI.

## Run

Start the API first (see [`../api/README.md`](../api/README.md)), then:

```bash
cd web
npm install
cp .env.local.example .env.local     # point NEXT_PUBLIC_API_URL at the API
npm run dev                          # http://localhost:3000
```

Production build:

```bash
npm run build && npm start
```

## Screens

- `app/login` — sign in / create account (stores the bearer token).
- `app/page.tsx` (**Feed**) — post composer, feed (Everyone / Following), and
  the verified-return leaderboard with follow buttons.
- `app/discuss` — per-ticker discussion threads: open a ticker, read, and post.
- `app/lists` — browse shared watchlists, publish your own, clone others' into
  your watchlist, delete your own.
- `app/profile` — edit bio/avatar and the two privacy opt-ins, follower/following
  counts, a member directory with follow buttons, and your blocked list.
- `app/portfolio` — your holdings, an equity-curve chart (inline SVG, no chart
  dep), a **When to Sell** review (Hold/Trim/Sell per holding with reasons),
  latest AI suggestions, and your logged decisions. Private to you.
- `app/components/Nav.tsx` — shared top navigation.
- `app/components/PostCard.tsx` — post card with like plus report/block on
  others' posts and delete on your own.
- `lib/api.ts` — typed client for the FastAPI backend; `lib/useAuth.ts` — the
  redirect-if-signed-out guard.

The full community surface plus moderation and a personal portfolio view are
now in the UI.

## Config

| Variable              | Default                  | Purpose               |
|-----------------------|--------------------------|-----------------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`  | Base URL of the API   |
