import db.community as C
import db.users as U


def _users(*names):
    return [U.create_user(n, "password123", n.title())["user"]["id"] for n in names]


def test_profiles_and_public_sharers():
    a, b = _users("alice", "bob")
    p = C.get_profile(a)
    assert p["is_public"] is False and p["avatar"] == "🙂"
    C.update_profile(a, "AI investor", "🦄", True, True)
    C.update_profile(b, "value guy", "🐢", True, False)   # public, not sharing returns
    assert {s["user_id"] for s in C.get_public_sharers()} == {a}
    assert {m["user_id"] for m in C.get_public_profiles(a)} == {a, b}


def test_follows():
    a, b, c = _users("alice", "bob", "carol")
    C.follow(a, b)
    C.follow(a, c)
    C.follow(a, a)  # self-follow ignored
    assert C.is_following(a, b) and not C.is_following(b, a)
    assert C.get_following_ids(a) == {b, c}
    assert C.follow_counts(b)["followers"] == 1
    assert C.follow_counts(a)["following"] == 2
    C.unfollow(a, c)
    assert C.get_following_ids(a) == {b}


def test_posts_feed_threads_likes():
    a, b = _users("alice", "bob")
    C.follow(a, b)
    assert "error" in C.create_post(a, "")
    assert "error" in C.create_post(a, "x" * 600)
    assert C.create_post(b, "NVDA looks strong", "nvda") == {"ok": True}
    thread = C.get_ticker_posts("NVDA", a)
    assert len(thread) == 1 and thread[0]["ticker"] == "NVDA"
    assert {p["body"] for p in C.get_feed(a)} == {"NVDA looks strong"}
    pid = thread[0]["id"]
    C.like_post(a, pid)
    C.like_post(a, pid)  # idempotent
    reread = C.get_ticker_posts("NVDA", a)[0]
    assert reread["likes"] == 1 and reread["liked"] is True
    C.unlike_post(a, pid)
    assert C.get_ticker_posts("NVDA", a)[0]["likes"] == 0


def test_post_rate_limit():
    (a,) = _users("alice")
    for i in range(C._POST_RATE_LIMIT):
        assert C.create_post(a, f"post {i}") == {"ok": True}
    assert "error" in C.create_post(a, "one too many")


def test_blocks_hide_both_directions():
    a, b = _users("alice", "bob")
    C.follow(a, b)
    C.create_post(b, "bob post", "NVDA")
    C.block(a, b)
    assert b in C.get_block_pair_ids(a) and a in C.get_block_pair_ids(b)
    assert C.get_ticker_posts("NVDA", a) == []       # a can't see b
    assert all(p["user_id"] != b for p in C.get_feed(a))
    C.create_post(a, "alice post")
    assert all(p["user_id"] != a for p in C.get_recent_posts(b))  # b can't see a
    C.unblock(a, b)
    assert b not in C.get_block_pair_ids(a)


def test_shared_watchlists():
    a, b = _users("alice", "bob")
    assert "error" in C.publish_watchlist(a, "", [{"symbol": "NVDA"}])
    assert "error" in C.publish_watchlist(a, "Mine", [])
    assert C.publish_watchlist(a, "AI Plays", [{"symbol": "NVDA", "industry": "Tech"}]) == {"ok": True}
    lists = C.get_shared_watchlists(b)
    assert len(lists) == 1 and lists[0]["name"] == "AI Plays"
    assert lists[0]["tickers"][0]["symbol"] == "NVDA"
    one = C.get_shared_watchlist(lists[0]["id"])
    assert one["tickers"][0]["symbol"] == "NVDA"
    C.block(b, a)
    assert C.get_shared_watchlists(b) == []          # blocked author hidden
    C.unblock(b, a)
    C.delete_shared_watchlist(a, lists[0]["id"])
    assert C.get_shared_watchlists(b) == []


def test_report_records():
    a, b = _users("alice", "bob")
    C.create_post(b, "spammy")
    pid = C.get_recent_posts(a)[0]["id"]
    C.report(a, target_user_id=b, reason="spam")
    C.report(a, post_id=pid, reason="bad")  # should not raise
