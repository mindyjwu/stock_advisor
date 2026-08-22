"""
Stock Advisor REST API.

A thin FastAPI layer over the exact same engine the Streamlit app uses —
db.users / db.store / db.community / data.loader are imported unchanged. This
is the Phase-4 "scale-out" seam: the Streamlit dashboard stays the internal
analysis UI, while this API powers the Next.js community frontend (web/).

Run locally:
    uvicorn api.main:app --reload --port 8000
Docs (Swagger) at http://localhost:8000/docs
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

import db.users as users
import db.store as store
import db.community as community
from data.loader import (
    load_watchlist, load_holdings, save_watchlist,
)
from db.connection import backend_name
from api.security import issue_token, verify_token

app = FastAPI(title="Stock Advisor API", version="1.0.0")

# CORS — the Next.js client runs on a different origin. Override in prod.
_origins = os.environ.get("API_CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create/upgrade the schema on import, so tables exist however the app is
# launched (uvicorn, gunicorn, or a test client). All three are idempotent.
users.init_users()
store.init_db()
community.init_community()


# ── Auth plumbing ───────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


def get_current_user(cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    uid = verify_token(cred.credentials)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = users.get_user(uid)
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


# ── Schemas ─────────────────────────────────────────────────────────────────
class SignupIn(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    bio: str = ""
    avatar: str = "🙂"
    is_public: bool = False
    share_returns: bool = False


class PostIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=community.MAX_POST_LEN)
    ticker: Optional[str] = None


class PublishIn(BaseModel):
    name: str


class ReportIn(BaseModel):
    target_user_id: Optional[int] = None
    post_id: Optional[int] = None
    reason: str = ""


def _auth_response(user: dict) -> dict:
    return {"token": issue_token(user["id"]), "user": user}


# ── Health & auth ───────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "backend": backend_name()}


@app.post("/api/auth/signup")
def signup(body: SignupIn):
    res = users.create_user(body.username, body.password, body.display_name)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return _auth_response(res["user"])


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = users.authenticate(body.username, body.password)
    if not user:
        locked = users.lockout_remaining_seconds(body.username)
        if locked > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {locked // 60 + 1} minute(s).",
            )
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return _auth_response(user)


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    return user


# ── Profile ─────────────────────────────────────────────────────────────────
def _profile_payload(uid: int) -> dict:
    prof = community.get_profile(uid)
    prof.update(community.follow_counts(uid))  # adds followers / following
    return prof


@app.get("/api/profile/me")
def get_my_profile(user: dict = Depends(get_current_user)):
    return _profile_payload(user["id"])


@app.put("/api/profile/me")
def update_my_profile(body: ProfileIn, user: dict = Depends(get_current_user)):
    community.update_profile(user["id"], body.bio, body.avatar,
                             body.is_public, body.share_returns)
    return _profile_payload(user["id"])


# ── Community: leaderboard, feed, posts, threads, follow, members, lists ─────
def _verified_return(candidate_id: int):
    from agents.track_record import verified_return
    return verified_return(candidate_id)


@app.get("/api/community/leaderboard")
def leaderboard(user: dict = Depends(get_current_user)):
    following = community.get_following_ids(user["id"])
    rows = []
    for u in community.get_public_sharers(exclude_user_id=user["id"]):
        avg, n = _verified_return(u["user_id"])
        if n > 0:
            rows.append({
                "user_id": u["user_id"], "display_name": u["display_name"],
                "avatar": u["avatar"], "bio": u.get("bio") or "",
                "avg_return": avg, "n_picks": n,
                "following": u["user_id"] in following,
            })
    rows.sort(key=lambda r: r["avg_return"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


@app.get("/api/community/feed")
def feed(user: dict = Depends(get_current_user)):
    return community.get_feed(user["id"])


@app.get("/api/community/posts")
def recent_posts(user: dict = Depends(get_current_user)):
    return community.get_recent_posts(user["id"])


@app.post("/api/community/posts")
def create_post(body: PostIn, user: dict = Depends(get_current_user)):
    res = community.create_post(user["id"], body.body, body.ticker)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return {"ok": True}


@app.delete("/api/community/posts/{post_id}")
def delete_post(post_id: int, user: dict = Depends(get_current_user)):
    community.delete_post(user["id"], post_id)
    return {"ok": True}


@app.post("/api/community/posts/{post_id}/like")
def like(post_id: int, user: dict = Depends(get_current_user)):
    community.like_post(user["id"], post_id)
    return {"ok": True}


@app.delete("/api/community/posts/{post_id}/like")
def unlike(post_id: int, user: dict = Depends(get_current_user)):
    community.unlike_post(user["id"], post_id)
    return {"ok": True}


@app.get("/api/community/threads/{ticker}")
def thread(ticker: str, user: dict = Depends(get_current_user)):
    return community.get_ticker_posts(ticker, user["id"])


@app.post("/api/community/follow/{target_id}")
def follow(target_id: int, user: dict = Depends(get_current_user)):
    community.follow(user["id"], target_id)
    return {"ok": True}


@app.delete("/api/community/follow/{target_id}")
def unfollow(target_id: int, user: dict = Depends(get_current_user)):
    community.unfollow(user["id"], target_id)
    return {"ok": True}


# ── Moderation ──────────────────────────────────────────────────────────────
@app.post("/api/community/block/{target_id}")
def block_user(target_id: int, user: dict = Depends(get_current_user)):
    community.block(user["id"], target_id)
    return {"ok": True}


@app.delete("/api/community/block/{target_id}")
def unblock_user(target_id: int, user: dict = Depends(get_current_user)):
    community.unblock(user["id"], target_id)
    return {"ok": True}


@app.get("/api/community/blocked")
def blocked_users(user: dict = Depends(get_current_user)):
    out = []
    for bid in community.get_blocked_ids(user["id"]):
        p = community.get_profile(bid)
        out.append({"user_id": bid, "display_name": p["display_name"], "avatar": p["avatar"]})
    return out


@app.post("/api/community/report")
def report_content(body: ReportIn, user: dict = Depends(get_current_user)):
    community.report(user["id"], body.target_user_id, body.post_id, body.reason)
    return {"ok": True}


@app.get("/api/community/members")
def members(user: dict = Depends(get_current_user)):
    following = community.get_following_ids(user["id"])
    out = []
    for m in community.get_public_profiles(user["id"]):
        if m["user_id"] == user["id"]:
            continue
        m["following"] = m["user_id"] in following
        out.append(m)
    return out


@app.get("/api/community/watchlists")
def shared_watchlists(user: dict = Depends(get_current_user)):
    return community.get_shared_watchlists(user["id"])


@app.post("/api/community/watchlists")
def publish_watchlist(body: PublishIn, user: dict = Depends(get_current_user)):
    res = community.publish_watchlist(user["id"], body.name, load_watchlist(user["id"]))
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return {"ok": True}


@app.post("/api/community/watchlists/{list_id}/clone")
def clone_watchlist(list_id: int, user: dict = Depends(get_current_user)):
    sl = community.get_shared_watchlist(list_id)
    if not sl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    current = load_watchlist(user["id"])
    have = {t["symbol"] for t in current}
    added = 0
    for t in sl["tickers"]:
        if isinstance(t, dict) and t.get("symbol") and t["symbol"] not in have:
            current.append({"symbol": t["symbol"], "industry": t.get("industry", "Misc")})
            have.add(t["symbol"])
            added += 1
    if added:
        save_watchlist(user["id"], current)
    return {"added": added}


@app.delete("/api/community/watchlists/{list_id}")
def delete_watchlist(list_id: int, user: dict = Depends(get_current_user)):
    community.delete_shared_watchlist(user["id"], list_id)
    return {"ok": True}


# ── Personal data ───────────────────────────────────────────────────────────
@app.get("/api/watchlist")
def watchlist(user: dict = Depends(get_current_user)):
    return load_watchlist(user["id"])


@app.get("/api/holdings")
def holdings(user: dict = Depends(get_current_user)):
    return load_holdings(user["id"])


@app.get("/api/suggestions")
def suggestions(user: dict = Depends(get_current_user)):
    return store.get_latest_run_suggestions(user["id"])


@app.get("/api/holdings/sell-signals")
def sell_signals(user: dict = Depends(get_current_user)):
    """For each held stock, whether to Hold / Trim / Sell and why. Combines the
    latest AI scores (if any) with position-aware signals (stop-loss, profit
    taking, target reached)."""
    from agents.sell_signals import evaluate_holdings
    ai_scores = {r["symbol"]: r["score"] for r in store.get_latest_run_suggestions(user["id"])}
    return evaluate_holdings(user["id"], ai_scores)


@app.get("/api/performance/snapshots")
def snapshots(user: dict = Depends(get_current_user)):
    return store.get_portfolio_snapshots(user["id"])


@app.get("/api/decisions")
def decisions(user: dict = Depends(get_current_user)):
    return store.get_decisions(user["id"])


@app.get("/api/scorecard")
def scorecard(user: dict = Depends(get_current_user)):
    """Grades the user's logged decisions: bought-pick paper returns, hit rate,
    opportunity cost of passed picks, AI-score calibration, and an overall
    decision-accuracy figure."""
    from agents.scorecard import scorecard as build
    return build(user["id"])
