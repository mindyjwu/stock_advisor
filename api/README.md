# Stock Advisor API

A FastAPI backend that exposes the same engine the Streamlit app uses
(`db.users`, `db.store`, `db.community`, `data.loader`) over REST. This is the
Phase-4 "scale-out" seam: Streamlit stays the internal analysis dashboard,
while this API powers the Next.js community frontend in [`../web`](../web).

## Run

```bash
pip install -r requirements.txt          # plus the project's root requirements.txt
uvicorn api.main:app --reload --port 8000
```

Interactive docs (Swagger UI): http://localhost:8000/docs

## Backends

Uses the same `db/connection.py` abstraction as the rest of the app:

- **SQLite** (default) — zero config.
- **Postgres** — set `DATABASE_URL=postgresql://…` (recommended for a real
  deployment with concurrent users).

## Auth

Stateless bearer tokens. `POST /api/auth/login` or `/signup` returns a token;
send it as `Authorization: Bearer <token>` on every other request. Set
`API_SECRET` in the environment for production (the default is a clearly
marked dev value). Accounts are shared with the Streamlit app.

## Config (environment)

| Variable            | Default                  | Purpose                            |
|---------------------|--------------------------|------------------------------------|
| `DATABASE_URL`      | _(unset → SQLite)_       | Postgres connection string         |
| `API_SECRET`        | dev-only value           | HMAC secret for signing tokens     |
| `API_TOKEN_TTL`     | `2592000` (30 days)      | Token lifetime, seconds            |
| `API_CORS_ORIGINS`  | `http://localhost:3000`  | Comma-separated allowed origins    |

## Endpoints (overview)

- `POST /api/auth/signup`, `POST /api/auth/login`, `GET /api/me`
- `GET/PUT /api/profile/me`
- `GET /api/community/leaderboard` — verified returns from members' logged picks
- `GET /api/community/feed`, `GET /api/community/posts`, `POST /api/community/posts`
- `GET /api/community/threads/{ticker}`
- `POST|DELETE /api/community/posts/{id}/like`, `DELETE /api/community/posts/{id}`
- `POST|DELETE /api/community/follow/{user_id}`
- `GET /api/community/members`
- `GET /api/community/watchlists`, `POST /api/community/watchlists`
- `GET /api/watchlist`, `GET /api/holdings`, `GET /api/suggestions`,
  `GET /api/performance/snapshots`, `GET /api/decisions`
- `GET /api/health`
