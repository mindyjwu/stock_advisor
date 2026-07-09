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

## What's here

- `app/login/page.tsx` — sign in / create account (stores the bearer token).
- `app/page.tsx` — home: post composer, feed (Everyone / Following), and the
  verified-return leaderboard with follow buttons.
- `lib/api.ts` — typed client for the FastAPI backend.

## Scope

This is an intentionally small but real slice — auth, feed, posting, likes,
follow, and leaderboard — proving the API/frontend split end-to-end. Ticker
threads, shared-watchlist browsing, and profile editing already exist in the
API and are natural next additions to the UI.

## Config

| Variable              | Default                  | Purpose               |
|-----------------------|--------------------------|-----------------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`  | Base URL of the API   |
