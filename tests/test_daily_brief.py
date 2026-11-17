"""
Tests for the Daily Brief: the statement-text parser and the if-then rule
engine. Everything runs on synthetic prices — no network, no real statement.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from agents import daily_brief as db
from data.pdf_import import parse_statement_text

TODAY = date(2026, 11, 16)


def _hist(closes, swing=0.01, end=TODAY):
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * (1 + swing), "Low": c * (1 - swing),
                         "Close": c, "Volume": 1_000_000})


def _trend(start, end, n=260):
    return list(np.linspace(start, end, n))


UP = _hist(_trend(60, 100))          # steady climb, at its high
DOWN = _hist(_trend(100, 40))        # steady slide, far below its high
GOOD_INFO = {"shortName": "Up Co", "targetMeanPrice": 125, "numberOfAnalystOpinions": 20,
             "recommendationMean": 1.6, "revenueGrowth": 0.25, "profitMargins": 0.2}
BAD_INFO = {"shortName": "Down Co", "targetMeanPrice": 38, "numberOfAnalystOpinions": 12,
            "recommendationMean": 3.2, "revenueGrowth": -0.2, "profitMargins": -0.3}


def _plan():
    return {"entries": {}, "statement": None, "log": [], "settings": dict(db.DEFAULT_SETTINGS)}


def _brief(positions, hist, infos, plan=None, today=TODAY, cash=0.0, **kw):
    plan = plan if plan is not None else _plan()
    return db.build_brief(positions, cash, plan, hist, infos, today=today, **kw), plan


# ── stance ────────────────────────────────────────────────────────────────────
def test_uptrend_with_good_fundamentals_is_bull():
    s = db.assess_stance(db.compute_metrics(UP, GOOD_INFO))
    assert s["label"] == "Bull" and s["score"] >= 25
    assert s["for"] and all(isinstance(x, str) for x in s["for"])


def test_downtrend_with_bad_fundamentals_is_bear():
    s = db.assess_stance(db.compute_metrics(DOWN, BAD_INFO))
    assert s["label"] == "Bear" and s["score"] <= -25
    assert any("200-day" in x for x in s["against"])


def test_too_little_history_gives_no_metrics():
    assert db.compute_metrics(_hist([10.0] * 10), {}) is None
    assert db.compute_metrics(None, {}) is None


# ── rule construction ─────────────────────────────────────────────────────────
def test_bull_rules_have_floor_below_target_above_and_a_dip_buy():
    m = db.compute_metrics(UP, GOOD_INFO)
    entry = db.build_rules(m, "Bull", gain_pct=0.4, today=TODAY)
    ids = [r["id"] for r in entry["rules"]]
    assert ids == ["floor", "target1", "dip"]
    floor, target, dip = entry["rules"]
    assert floor["price"] < dip["price"] < m["price"] < target["price"]
    assert floor["fraction"] == 0.5 and target["fraction"] == 0.25
    assert dip["guard"] == floor["price"]


def test_bear_rules_sell_everything_at_floor_and_carry_a_deadline_but_never_buy():
    m = db.compute_metrics(DOWN, BAD_INFO)
    entry = db.build_rules(m, "Bear", gain_pct=-0.5, today=TODAY)
    by = {r["id"]: r for r in entry["rules"]}
    assert by["floor"]["fraction"] == 1.0
    assert by["deadline"]["by"] == (TODAY + timedelta(days=30)).isoformat()
    assert by["deadline"]["price"] == by["target1"]["price"]
    assert not any(r["kind"] == "buy" for r in entry["rules"])


def test_neutral_gets_deadline_only_when_sitting_on_a_real_loss():
    m = db.compute_metrics(UP, {})
    assert "deadline" not in [r["id"] for r in db.build_rules(m, "Neutral", 0.10, TODAY)["rules"]]
    assert "deadline" in [r["id"] for r in db.build_rules(m, "Neutral", -0.30, TODAY)["rules"]]


def test_floor_distance_is_clamped_for_wild_and_calm_stocks():
    wild = db.compute_metrics(_hist(_trend(60, 100), swing=0.2), {})
    calm = db.compute_metrics(_hist(_trend(99, 100), swing=0.0005), {})
    for m, lo, hi in ((wild, 0.07, 0.22), (calm, 0.07, 0.22)):
        floor = db.build_rules(m, "Bull", 0.0, TODAY)["rules"][0]["price"]
        assert lo - 1e-3 <= 1 - floor / m["price"] <= hi + 1e-3


# ── the brief ─────────────────────────────────────────────────────────────────
POS = [{"symbol": "UP", "quantity": 10, "cost_basis": 70.0},
       {"symbol": "DOWN", "quantity": 20, "cost_basis": 90.0}]


def test_brief_builds_cards_rules_and_summary():
    brief, plan = _brief(POS, {"UP": UP, "DOWN": DOWN}, {"UP": GOOD_INFO, "DOWN": BAD_INFO}, cash=500)
    assert brief["plan_changed"] and set(plan["entries"]) == {"UP", "DOWN"}
    s = brief["summary"]
    assert s["counts"]["Bull"] == 1 and s["counts"]["Bear"] == 1
    assert abs(s["total"] - (10 * 100 + 20 * 40 + 500)) < 1e-6
    up = next(c for c in brief["cards"] if c["symbol"] == "UP")
    assert up["stance"]["label"] == "Bull" and abs(up["gain_pct"] - (100 / 70 - 1)) < 1e-9
    assert all("→" in r["text"] for r in up["rules"])
    sell_half = next(r for r in up["rules"] if r["id"] == "floor")
    assert "sell half" in sell_half["text"] and "5 shares" in sell_half["text"]


def test_missing_price_data_yields_a_card_without_rules():
    brief, _ = _brief([{"symbol": "ZZZ", "quantity": 3, "cost_basis": 5.0}], {}, {})
    card = brief["cards"][0]
    assert not card["has_data"] and card["rules"] == [] and card["stance"]["label"] == "No data"


def test_rules_stay_anchored_and_floor_triggers_when_price_falls_through():
    brief, plan = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})
    floor0 = plan["entries"]["UP"]["rules"][0]["price"]
    # A sharp drop: 100 → 70 over the next three weeks.
    crashed = _hist(_trend(60, 100) + list(np.linspace(98, 70, 15)))
    later = TODAY + timedelta(days=21)
    brief2, plan = _brief(POS[:1], {"UP": crashed}, {"UP": GOOD_INFO}, plan=plan, today=later)
    assert plan["entries"]["UP"]["rules"][0]["price"] == floor0, "floor must not drift down with price"
    hit = [x for x in brief2["triggered"] if x["symbol"] == "UP" and x["id"] == "floor"]
    assert len(hit) == 1 and "sell" in hit[0]["text"]


def test_a_floor_that_was_broken_stays_hit_even_after_a_bounce():
    _, plan = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})
    floor0 = plan["entries"]["UP"]["rules"][0]["price"]
    later = TODAY + timedelta(days=14)
    # Closes below the floor for two days, then bounces back above it.
    dipped = _hist(_trend(60, 100) + [95, floor0 * 0.97, floor0 * 0.98, 96, 97], end=later)
    brief, plan = _brief(POS[:1], {"UP": dipped}, {"UP": GOOD_INFO}, plan=plan, today=later)
    hit = next(x for x in brief["triggered"] if x["id"] == "floor")
    assert hit["detail"].startswith("hit ") and plan["entries"]["UP"]["rules"][0]["price"] == floor0


def test_floor_trails_upward_as_price_rises():
    brief, plan = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})
    floor0 = plan["entries"]["UP"]["rules"][0]["price"]
    higher = _hist(_trend(60, 100) + list(np.linspace(101, 108, 10)))
    brief2, plan = _brief(POS[:1], {"UP": higher}, {"UP": {**GOOD_INFO, "targetMeanPrice": 140}},
                          plan=plan, today=TODAY + timedelta(days=14))
    assert plan["entries"]["UP"]["rules"][0]["price"] > floor0
    assert brief2["plan_changed"]


def test_take_profit_triggers_and_done_reanchors():
    brief, plan = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})
    target = next(r for r in plan["entries"]["UP"]["rules"] if r["id"] == "target1")["price"]
    spiked = _hist(_trend(60, 100) + [target * 1.01])
    brief2, plan = _brief(POS[:1], {"UP": spiked}, {"UP": GOOD_INFO}, plan=plan, today=TODAY + timedelta(days=1))
    assert any(x["id"] == "target1" for x in brief2["triggered"])
    db.mark_done(plan, "UP", "target1", brief2["metrics"], brief2["stances"], POS[:1],
                 today=TODAY + timedelta(days=1))
    assert plan["log"][-1]["symbol"] == "UP" and plan["log"][-1]["rule"] == "target1"
    new_target = next(r for r in plan["entries"]["UP"]["rules"] if r["id"] == "target1")["price"]
    assert new_target > target


def test_intraday_spike_before_rules_were_set_does_not_trigger_a_target():
    # Today's bar spiked 35% intraday, then closed flat. Rules are set after that.
    h = _hist(_trend(60, 100))
    h.iloc[-1, h.columns.get_loc("High")] = 135.0
    brief, plan = _brief(POS[:1], {"UP": h}, {"UP": {}})
    target = next(r for r in plan["entries"]["UP"]["rules"] if r["id"] == "target1")["price"]
    assert target < 135.0, "test needs the spike to sit above the new target"
    assert brief["triggered"] == []


def test_triggered_items_carry_the_live_price_separately_from_the_level():
    _, plan = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})
    floor0 = plan["entries"]["UP"]["rules"][0]["price"]
    later = TODAY + timedelta(days=7)
    brief, _ = _brief(POS[:1], {"UP": _hist(_trend(60, 100) + [70.0], end=later)}, {"UP": GOOD_INFO},
                      plan=plan, today=later)
    hit = next(x for x in brief["triggered"] if x["id"] == "floor")
    assert hit["now"] == 70.0 and hit["price"] == floor0


def test_deadline_fires_only_after_the_date_and_clears_on_recovery():
    brief, plan = _brief(POS[1:], {"DOWN": DOWN}, {"DOWN": BAD_INFO})
    dl = next(r for r in plan["entries"]["DOWN"]["rules"] if r["id"] == "deadline")
    assert not any(x["id"] == "deadline" for x in brief["triggered"])
    after = date.fromisoformat(dl["by"]) + timedelta(days=1)
    flat = _hist(_trend(100, 40) + [40.0] * 25, end=after)
    brief2, _ = _brief(POS[1:], {"DOWN": flat}, {"DOWN": BAD_INFO}, plan=plan, today=after)
    assert any(x["id"] == "deadline" for x in brief2["triggered"])
    # Same date, but it closed above the bar along the way → cleared, not triggered.
    plan2 = _plan()
    _brief(POS[1:], {"DOWN": DOWN}, {"DOWN": BAD_INFO}, plan=plan2)
    bar = next(r for r in plan2["entries"]["DOWN"]["rules"] if r["id"] == "deadline")["price"]
    recovered = _hist(_trend(100, 40) + [bar * 1.05] * 3 + [40.5] * 22, end=after)
    brief3, _ = _brief(POS[1:], {"DOWN": recovered}, {"DOWN": BAD_INFO}, plan=plan2, today=after)
    card = brief3["cards"][0]
    assert next(r for r in card["rules"] if r["id"] == "deadline")["status"] == "cleared"


def test_sold_holdings_drop_out_and_new_ones_get_rules():
    _, plan = _brief(POS, {"UP": UP, "DOWN": DOWN}, {"UP": GOOD_INFO, "DOWN": BAD_INFO})
    new_pos = [POS[0], {"symbol": "NEW", "quantity": 1, "cost_basis": 95.0}]
    brief, plan = _brief(new_pos, {"UP": UP, "NEW": UP}, {"UP": GOOD_INFO, "NEW": GOOD_INFO}, plan=plan)
    assert set(plan["entries"]) == {"UP", "NEW"} and brief["plan_changed"]


def test_oversized_position_is_flagged_and_its_buy_rule_paused():
    brief, _ = _brief(POS[:1], {"UP": UP}, {"UP": GOOD_INFO})   # one stock = 100% of portfolio
    card = brief["cards"][0]
    assert card["oversized"] and card["trim_to_cap"] > 0
    assert next(r for r in card["rules"] if r["kind"] == "buy")["status"] == "blocked"
    assert brief["summary"]["oversized"] == ["UP"]


def test_plan_round_trips_through_disk():
    _, plan = _brief(POS, {"UP": UP, "DOWN": DOWN}, {"UP": GOOD_INFO, "DOWN": BAD_INFO})
    plan["settings"]["monthly_budget"] = 2000.0
    db.save_plan(7, plan)
    loaded = db.load_plan(7)
    assert loaded["entries"] == plan["entries"] and loaded["settings"]["monthly_budget"] == 2000.0
    assert db.load_plan(8)["entries"] == {}


# ── statement parser ──────────────────────────────────────────────────────────
STATEMENT = """INDIVIDUAL (Acct # 000-00000) TEST USER Statement Period: October 01 - October 30, 2026
ENDING ACCOUNT VALUE $4,449.52 $4,449.52
Holdings
CASH & MONEY MARKETS
CHASE DEPOSIT SWEEP 449.7 1 449.70 --
Symbol: QACDS
TOTAL CASH & MONEY MARKETS $449.70 --
EQUITY
Acquisition Unrealized Est. Accrued Inc.
EXAMPLE WIDGETS INC 10.5 100 1,050.00 80 840.00 210.00 --
Dividend Reinvested EST 10.89
Symbol: EXW 10 Apr 2024 10 1,000.00 79 790.00 210.00 LT
13 Aug 2026 0.5 50.00 100 50.00 0.00 ST
SAMPLE HOLDINGS LLC 03 Jul 2025 5 590 2,950.00 137.89 689.45 2,260.55 LT --
INC COM Dividend Reinvested --
Symbol: SMPL
LOSSMAKER & CO (THE) 28 Sep 2026 10 14.982 149.82 20 200.00 (50.18) ST --
Symbol: LOSS
TOTAL EQUITY $4,149.82 $1,729.45 $2,420.37 --
TRADE AND INVESTMENT ACTIVITY
Symbol: NOPE
"""


def test_statement_parser_reads_positions_lots_cash_and_period():
    res = parse_statement_text(STATEMENT)
    assert [p["symbol"] for p in res["positions"]] == ["EXW", "SMPL", "LOSS"]
    exw = res["positions"][0]
    assert exw["quantity"] == 10.5 and abs(exw["cost_basis"] - 80.0) < 1e-6
    assert res["cash"] == 449.70 and res["warnings"] == []
    stmt = res["statement"]
    assert stmt["period_end"] == "2026-10-30" and stmt["account_value"] == 4449.52
    assert stmt["equity_value"] == 4149.82
    assert [l["term"] for l in stmt["lots"]["EXW"]] == ["LT", "ST"]
    assert stmt["lots"]["SMPL"] == [{"date": "03 Jul 2025", "quantity": 5.0, "cost": 689.45, "term": "LT"}]
    assert stmt["prices"]["LOSS"] == 14.982


def test_statement_parser_warns_when_totals_do_not_add_up():
    res = parse_statement_text(STATEMENT.replace("TOTAL EQUITY $4,149.82", "TOTAL EQUITY $9,999.00"))
    assert res["warnings"] and "add up" in res["warnings"][0]


def test_statement_parser_returns_nothing_for_unrelated_text():
    assert parse_statement_text("Hello\nNot a statement\n")["positions"] == []


def test_long_term_share_from_lots():
    lots = [{"date": "10 Apr 2024", "quantity": 3}, {"date": "13 Aug 2026", "quantity": 1}]
    assert db._long_term_share(lots, TODAY) == 0.75
    assert db._long_term_share([], TODAY) is None
