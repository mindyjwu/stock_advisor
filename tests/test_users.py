import db.users as U


def test_signup_and_authenticate():
    res = U.create_user("Alice", "password123", "Alice A")
    assert "user" in res
    u = res["user"]
    assert u["is_owner"] is True  # first account is the owner
    assert U.authenticate("alice", "password123")["id"] == u["id"]  # case-insensitive
    assert U.authenticate("alice", "wrong") is None


def test_duplicate_and_validation():
    U.create_user("bob", "password123")
    assert "error" in U.create_user("bob", "password123")       # exact dup
    assert "error" in U.create_user("BOB", "password123")       # case-insensitive dup
    assert "error" in U.create_user("ab", "password123")        # too short
    assert "error" in U.create_user("gooduser", "short")        # weak password


def test_second_user_not_owner():
    U.create_user("owner", "password123")
    u2 = U.create_user("second", "password123")["user"]
    assert u2["is_owner"] is False
    assert U.get_owner()["username"] == "owner"


def test_lockout_after_repeated_failures():
    U.create_user("victim", "password123")
    for _ in range(U.MAX_FAILED_LOGINS):
        assert U.authenticate("victim", "nope") is None
    assert U.lockout_remaining_seconds("victim") > 0
    # a locked account is rejected even with the correct password
    assert U.authenticate("victim", "password123") is None
    # lock key is case-insensitive
    assert U.lockout_remaining_seconds("VICTIM") > 0


def test_successful_login_clears_failures():
    U.create_user("carol", "password123")
    for _ in range(U.MAX_FAILED_LOGINS - 1):
        U.authenticate("carol", "nope")
    assert U.authenticate("carol", "password123") is not None  # succeeds before lock
    # counter reset — another near-miss streak doesn't instantly lock
    for _ in range(U.MAX_FAILED_LOGINS - 1):
        U.authenticate("carol", "nope")
    assert U.lockout_remaining_seconds("carol") == 0
