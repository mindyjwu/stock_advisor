from agents.scorecard import build_scorecard, scorecard
import db.users as U
import db.store as S


# A fake price map for the pure core. Entry prices are all 100 below.
_PRICES = {
    "AAA": 150.0,   # bought, +50%  -> winner, 75+ bucket
    "BBB": 90.0,    # bought, -10%  -> loser,  60–75 bucket
    "CCC": 100.0,   # bought,   0%  -> not a hit, <60 bucket
    "DDD": 120.0,   # passed, +20%  -> missed winner
    "EEE": 80.0,    # passed, -20%  -> avoided loser
    "FFF": None,    # bought, unpriceable -> excluded from stats
}

_DECISIONS = [
    {"symbol": "AAA", "decision": "bought", "price": 100.0, "score": 80, "action": "Strong Buy"},
    {"symbol": "BBB", "decision": "bought", "price": 100.0, "score": 70, "action": "Buy"},
    {"symbol": "CCC", "decision": "bought", "price": 100.0, "score": 55, "action": "Hold"},
    {"symbol": "DDD", "decision": "passed", "price": 100.0, "score": 65, "action": "Buy"},
    {"symbol": "EEE", "decision": "passed", "price": 100.0, "score": 50, "action": "Hold"},
    {"symbol": "FFF", "decision": "bought", "price": 100.0, "score": 90, "action": "Buy"},
]


def _lookup(symbol):
    return _PRICES.get(symbol)


def test_build_scorecard_counts():
    sc = build_scorecard(_DECISIONS, _lookup)
    assert sc["n_decisions"] == 6
    assert sc["n_bought"] == 4 and sc["n_passed"] == 2


def test_build_scorecard_bought_metrics():
    b = build_scorecard(_DECISIONS, _lookup)["bought"]
    assert b["n_priced"] == 3                       # FFF excluded (no price)
    assert abs(b["avg_return"] - 13.33) < 0.01      # (50 - 10 + 0) / 3
    assert abs(b["hit_rate"] - 33.3) < 0.1          # only AAA is > 0
    assert b["best"]["symbol"] == "AAA" and b["best"]["return_pct"] == 50.0
    assert b["worst"]["symbol"] == "BBB" and b["worst"]["return_pct"] == -10.0


def test_build_scorecard_passed_opportunity_cost():
    p = build_scorecard(_DECISIONS, _lookup)["passed"]
    assert p["n_priced"] == 2
    assert p["missed_winners"] == 1                 # DDD rose after passing
    assert p["avoided_losers"] == 1                 # EEE fell after passing
    assert abs(p["avg_move"] - 0.0) < 0.01          # (+20 - 20) / 2


def test_build_scorecard_decision_accuracy():
    sc = build_scorecard(_DECISIONS, _lookup)
    # correct = bought-and-rose (AAA) + passed-and-fell (EEE) = 2, of 5 priced
    assert abs(sc["decision_accuracy"] - 40.0) < 0.01


def test_build_scorecard_score_calibration():
    cal = {c["bucket"]: c for c in build_scorecard(_DECISIONS, _lookup)["score_calibration"]}
    assert cal["75+"]["avg_return"] == 50.0 and cal["75+"]["n"] == 1
    assert cal["60–75"]["avg_return"] == -10.0
    assert cal["<60"]["avg_return"] == 0.0


def test_build_scorecard_empty():
    sc = build_scorecard([], _lookup)
    assert sc["n_decisions"] == 0
    assert sc["decision_accuracy"] is None
    assert sc["bought"]["avg_return"] is None and sc["bought"]["best"] is None
    assert sc["score_calibration"] == []


def test_scorecard_live_uses_loader(monkeypatch):
    """The live wrapper reads real decisions and prices via the (mocked) loader.
    conftest's _fake_info returns 100 for unknown symbols, 142 for NVDA."""
    uid = U.create_user("grader", "password123")["user"]["id"]
    S.record_decision(uid, "NVDA", "bought", "Buy", price=100.0, score=80)   # -> +42%
    S.record_decision(uid, "AAA", "passed", "Hold", price=100.0, score=50)   # 100 -> 0%
    sc = scorecard(uid)
    assert sc["n_bought"] == 1 and sc["n_passed"] == 1
    assert abs(sc["bought"]["avg_return"] - 42.0) < 0.01
    assert sc["passed"]["avoided_losers"] == 1     # flat counts as avoided
