import db.users as U
import db.store as S
import data.loader as L
from agents import notifier
from scripts import run_alerts as R


def _mk_user_with_pick(username, *, target_price, action="Buy", enabled=True,
                       email="me@example.com"):
    """Create a user, log one suggestion, and set their alert prefs."""
    uid = U.create_user(username, "password123")["user"]["id"]
    S.log_suggestion(
        uid,
        {"symbol": "AAA", "action": action, "score": 82.0,
         "current_price": 100.0, "target_price": target_price,
         "upside_pct": 5.0, "suggested_quantity": 3},
        fund_score=70, tech_score=65, sent_score=60, regime_key="neutral",
        reasons=["looks good"],
    )
    prefs = {}
    if enabled:
        prefs["email_alerts_enabled"] = True
    if email is not None:
        prefs["alert_email"] = email
    L.save_user_settings(uid, prefs)
    return uid


def test_collect_new_alerts_target_hit_and_dedup(monkeypatch):
    # fake price is 100 (conftest); target 90 -> target hit fires once, then dedupes
    uid = _mk_user_with_pick("trader", target_price=90.0)
    alerts, actions = R.collect_new_alerts(uid, {})
    assert [a["type"] for a in alerts] == ["price_target_hit"]
    assert actions == {"AAA": "Buy"}
    # second run: same day -> already logged -> nothing new
    again, _ = R.collect_new_alerts(uid, actions)
    assert again == []


def test_collect_new_alerts_strong_buy_flip(monkeypatch):
    uid = _mk_user_with_pick("flipper", target_price=999.0, action="Strong Buy")
    # no prior actions -> a Strong Buy is a flip
    alerts, actions = R.collect_new_alerts(uid, {})
    assert any(a["type"] == "strong_buy_flip" for a in alerts)
    assert actions == {"AAA": "Strong Buy"}


def test_run_for_user_sends_and_persists(monkeypatch):
    uid = _mk_user_with_pick("emailer", target_price=90.0)
    monkeypatch.setattr(notifier, "email_configured", lambda: True)
    captured = {}

    def _fake_send(to, subject, text, html=None):
        captured.update(to=to, subject=subject)
        return True

    user = U.get_user(uid)
    res = R.run_for_user(user, send=_fake_send)
    assert res["status"] == "sent" and res["n_alerts"] == 1
    assert captured["to"] == "me@example.com" and "AAA" in captured["subject"]
    # snapshot persisted for next-run flip detection
    assert L.load_user_settings(uid)["last_alert_actions"] == {"AAA": "Buy"}


def test_run_for_user_respects_optout(monkeypatch):
    uid = _mk_user_with_pick("optout", target_price=90.0, enabled=False)
    monkeypatch.setattr(notifier, "email_configured", lambda: True)
    called = []
    res = R.run_for_user(U.get_user(uid), send=lambda *a, **k: called.append(a))
    assert res["status"] == "disabled" and called == []


def test_run_for_user_no_email_address(monkeypatch):
    uid = _mk_user_with_pick("noaddr", target_price=90.0, email=None)
    res = R.run_for_user(U.get_user(uid), send=lambda *a, **k: True)
    assert res["status"] == "no_email"


def test_run_for_user_logged_but_email_unconfigured(monkeypatch):
    uid = _mk_user_with_pick("nosmtp", target_price=90.0)
    monkeypatch.setattr(notifier, "email_configured", lambda: False)
    res = R.run_for_user(U.get_user(uid), send=lambda *a, **k: True)
    assert res["status"] == "logged_email_unconfigured" and res["n_alerts"] == 1
