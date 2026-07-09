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
- `app/profile` — edit bio/avatar and the two privacy opt-ins, see your
  follower/following counts, and a member directory with follow buttons.
- `app/components/Nav.tsx` — shared top navigation.
- `lib/api.ts` — typed client for the FastAPI backend; `lib/useAuth.ts` — the
  redirect-if-signed-out guard.

The full community surface is now in the UI. Not yet surfaced (exists in the
Streamlit app, straightforward to add here): block/report moderation controls
and the personal portfolio/performance views.

## Config

| Variable              | Default                  | Purpose               |
|-----------------------|--------------------------|-----------------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`  | Base URL of the API   |
