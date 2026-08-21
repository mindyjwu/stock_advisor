import pytest

import db.store as S
import data.loader as L


@pytest.fixture
def client():
    # Imported lazily so collection doesn't init the default DB before fixtures.
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _signup(client, username, name=""):
    r = client.post("/api/auth/signup",
                    json={"username": username, "password": "password123", "display_name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["backend"] in ("sqlite", "postgres")


def test_auth_flow(client):
    res = _signup(client, "alice", "Alice")
    h = _auth(res["token"])
    assert client.get("/api/me").status_code == 401              # no token
    assert client.get("/api/me", headers=_auth("garbage")).status_code == 401
    assert client.get("/api/me", headers=h).json()["username"] == "alice"
    assert client.post("/api/auth/signup",
                       json={"username": "alice", "password": "password123"}).status_code == 400
    assert client.post("/api/auth/login",
                       json={"username": "alice", "password": "nope"}).status_code == 401


def test_login_lockout_returns_429(client):
    _signup(client, "victim")
    codes = [client.post("/api/auth/login",
                         json={"username": "victim", "password": "x"}).status_code
             for _ in range(5)]
    assert codes[:4] == [401, 401, 401, 401]
    assert codes[4] == 429
    # correct password is still refused while locked
    assert client.post("/api/auth/login",
                       json={"username": "victim", "password": "password123"}).status_code == 429


def test_profile_counts(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob")
    ha, hb = _auth(a["token"]), _auth(b["token"])
    assert client.get("/api/profile/me", headers=ha).json()["following"] == 0
    client.post(f"/api/community/follow/{b['user']['id']}", headers=ha)
    assert client.get("/api/profile/me", headers=ha).json()["following"] == 1
    assert client.get("/api/profile/me", headers=hb).json()["followers"] == 1


def test_leaderboard_verified_return(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob", "Bob")
    ha, hb = _auth(a["token"]), _auth(b["token"])
    # bob opts in and logs a bought pick at 80 (mock price is 100 -> +25%)
    client.put("/api/profile/me", headers=hb,
               json={"bio": "", "avatar": "🐂", "is_public": True, "share_returns": True})
    S.record_decision(b["user"]["id"], "AAA", "bought", "Buy", 80.0, 80)
    board = client.get("/api/community/leaderboard", headers=ha).json()
    assert len(board) == 1 and board[0]["display_name"] == "Bob"
    assert board[0]["n_picks"] == 1 and abs(board[0]["avg_return"] - 25.0) < 0.01


def test_posts_feed_threads_likes(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob")
    ha, hb = _auth(a["token"]), _auth(b["token"])
    client.post(f"/api/community/follow/{b['user']['id']}", headers=ha)
    assert client.post("/api/community/posts", headers=ha, json={"body": ""}).status_code == 422
    client.post("/api/community/posts", headers=hb, json={"body": "NVDA strong", "ticker": "nvda"})
    assert any(p["body"] == "NVDA strong" for p in client.get("/api/community/feed", headers=ha).json())
    thread = client.get("/api/community/threads/NVDA", headers=ha).json()
    pid = thread[0]["id"]
    client.post(f"/api/community/posts/{pid}/like", headers=ha)
    assert client.get("/api/community/threads/NVDA", headers=ha).json()[0]["likes"] == 1


def test_shared_watchlist_clone_and_delete(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob", "Bob")
    ha, hb = _auth(a["token"]), _auth(b["token"])
    L.save_watchlist(b["user"]["id"], [{"symbol": "NVDA", "industry": "Tech"},
                                       {"symbol": "AMD", "industry": "Tech"}])
    assert client.post("/api/community/watchlists", headers=hb, json={"name": "Bob AI"}).status_code == 200
    lid = client.get("/api/community/watchlists", headers=ha).json()[0]["id"]
    L.save_watchlist(a["user"]["id"], [])
    assert client.post(f"/api/community/watchlists/{lid}/clone", headers=ha).json()["added"] == 2
    assert client.post(f"/api/community/watchlists/{lid}/clone", headers=ha).json()["added"] == 0
    assert client.post("/api/community/watchlists/99999/clone", headers=ha).status_code == 404
    client.delete(f"/api/community/watchlists/{lid}", headers=ha)   # not owner -> no-op
    assert len(client.get("/api/community/watchlists", headers=ha).json()) == 1
    client.delete(f"/api/community/watchlists/{lid}", headers=hb)   # owner
    assert client.get("/api/community/watchlists", headers=ha).json() == []


def test_moderation(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob", "Bob")
    ha, hb = _auth(a["token"]), _auth(b["token"])
    client.post("/api/community/posts", headers=hb, json={"body": "bob post"})
    assert any(p["body"] == "bob post" for p in client.get("/api/community/posts", headers=ha).json())
    pid = [p for p in client.get("/api/community/posts", headers=ha).json()
           if p["body"] == "bob post"][0]["id"]
    assert client.post("/api/community/report", headers=ha,
                       json={"post_id": pid, "reason": "spam"}).status_code == 200
    assert client.post(f"/api/community/block/{b['user']['id']}", headers=ha).status_code == 200
    assert not any(p["body"] == "bob post" for p in client.get("/api/community/posts", headers=ha).json())
    blocked = client.get("/api/community/blocked", headers=ha).json()
    assert len(blocked) == 1 and blocked[0]["display_name"] == "Bob"
    client.delete(f"/api/community/block/{b['user']['id']}", headers=ha)
    assert client.get("/api/community/blocked", headers=ha).json() == []


def test_scorecard_endpoint(client):
    a = _signup(client, "alice")
    b = _signup(client, "bob")               # separate user, untouched cache
    ha, hb = _auth(a["token"]), _auth(b["token"])
    # empty scorecard is well-formed
    empty = client.get("/api/scorecard", headers=hb).json()
    assert empty["n_decisions"] == 0 and empty["decision_accuracy"] is None
    # NVDA mock price is 142 -> a bought pick at 100 is +42%
    S.record_decision(a["user"]["id"], "NVDA", "bought", "Buy", 100.0, 80)
    S.record_decision(a["user"]["id"], "AAA", "passed", "Hold", 100.0, 50)
    sc = client.get("/api/scorecard", headers=ha).json()
    assert sc["n_bought"] == 1 and sc["n_passed"] == 1
    assert abs(sc["bought"]["avg_return"] - 42.0) < 0.01
    assert sc["bought"]["hit_rate"] == 100.0


def test_sell_signals_endpoint(client):
    a = _signup(client, "alice")
    ha = _auth(a["token"])
    L.save_holdings(a["user"]["id"], {"cash": 0.0, "positions": [
        {"symbol": "WEAK", "quantity": 10, "cost_basis": 100, "unrealized_gl_pct": -60},
        {"symbol": "XOM", "quantity": 5, "cost_basis": 90, "unrealized_gl_pct": 11},
    ]})
    sig = {s["symbol"]: s for s in client.get("/api/holdings/sell-signals", headers=ha).json()}
    assert sig["WEAK"]["verdict"] == "Sell"
    assert "stop-loss" in sig["WEAK"]["flags"]["risk"]
