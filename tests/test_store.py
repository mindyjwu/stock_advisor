import db.store as S
import db.users as U


def _two_users():
    a = U.create_user("alice", "password123")["user"]["id"]
    b = U.create_user("bob", "password123")["user"]["id"]
    return a, b


def _sugg(symbol="NVDA", score=88, price=120.0):
    return {"symbol": symbol, "action": "Strong Buy", "score": score,
            "current_price": price, "target_price": price * 1.3,
            "upside_pct": 30.0, "suggested_quantity": 5}


def test_suggestions_history_and_latest():
    a, _ = _two_users()
    S.log_suggestion(a, _sugg("NVDA", 88), 90, 85, 80, "calm", ["cheap", "trend"])
    S.log_suggestion(a, _sugg("AAPL", 70, 200.0), 72, 68, 60, "calm", ["steady"])
    hist = S.get_suggestion_history(a)
    assert len(hist) == 2 and hist[0]["reasons"]
    latest = S.get_latest_run_suggestions(a)
    assert latest[0]["score"] == 88 and latest[0]["suggested_quantity"] == 5
    assert {p["symbol"] for p in S.get_performance_snapshot(a)} == {"NVDA", "AAPL"}


def test_saved_picks_are_per_user_unique():
    a, b = _two_users()
    S.save_pick(a, "nvda", "Tech", "moat")
    S.save_pick(a, "NVDA", "Tech", "updated")          # upsert
    assert len(S.get_saved_picks(a)) == 1
    assert S.get_saved_picks(a)[0]["note"] == "updated"
    S.save_pick(b, "NVDA", "Tech")                     # different user, same symbol ok
    assert len(S.get_saved_picks(b)) == 1
    S.remove_pick(a, "NVDA")
    assert S.get_saved_picks(a) == []


def test_alert_dedup():
    a, _ = _two_users()
    key = "NVDA-target-2026-07-09"
    assert S.log_alert(a, "NVDA", "target", "hit", key) is True
    assert S.log_alert(a, "NVDA", "target", "hit", key) is False
    assert len(S.get_recent_alerts(a)) == 1


def test_snapshots_upsert_per_day():
    a, _ = _two_users()
    S.record_portfolio_snapshot(a, 10000, 8000, 2000, 7000, 1000, 3)
    S.record_portfolio_snapshot(a, 11000, 9000, 2000, 7000, 2000, 3)  # same day
    snaps = S.get_portfolio_snapshots(a)
    assert len(snaps) == 1 and snaps[0]["total_value"] == 11000


def test_decisions_upsert_and_map():
    a, _ = _two_users()
    S.record_decision(a, "nvda", "bought", "Strong Buy", 120.0, 88)
    S.record_decision(a, "AAPL", "passed", "Watch", 200.0, 55)
    S.record_decision(a, "NVDA", "passed", "Buy", 130.0, 80)  # overwrite
    assert S.get_decision_map(a) == {"NVDA": "passed", "AAPL": "passed"}
    S.remove_decision(a, "AAPL")
    assert S.get_decision_map(a) == {"NVDA": "passed"}


def test_imports_audit():
    a, _ = _two_users()
    S.log_import(a, "CSV", "positions.csv", 42, 1234.5, "replace", "/tmp/h.bak.json")
    last = S.get_last_import(a)
    assert last["source"] == "CSV" and last["n_positions"] == 42


def test_user_scoping():
    a, b = _two_users()
    S.record_portfolio_snapshot(a, 10000, 8000, 2000, 7000, 1000, 3)
    S.record_decision(a, "NVDA", "bought")
    assert S.get_portfolio_snapshots(b) == []
    assert S.get_decision_map(b) == {}
    assert S.get_suggestion_history(b) == []


def test_claim_legacy_rows():
    a, _ = _two_users()
    with S._conn() as con:
        con.execute(
            "INSERT INTO suggestions (user_id, symbol, run_at, action, score) VALUES (?,?,?,?,?)",
            (None, "LEG", "2020-01-01T00:00:00", "Buy", 50),
        )
    S.claim_legacy_rows(a)
    with S._conn() as con:
        left = con.execute(
            "SELECT COUNT(*) AS n FROM suggestions WHERE user_id IS NULL"
        ).fetchone()["n"]
    assert left == 0
