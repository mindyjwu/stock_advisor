"""
Server-side alert runner — the piece that lets alerts reach users who aren't
sitting in front of the app.

Unlike scripts/alert_poller.py (a macOS-only, owner-only, long-running desktop
notifier), this is a ONE-SHOT, MULTI-USER, EMAIL-delivering job meant to be
driven by cron / a systemd timer / a scheduled CI job, e.g. every 15 min during
market hours:

    */15 13-20 * * 1-5   cd /app && python -m scripts.run_alerts

For each account that opted into email alerts (Settings → email), it:
  1. refreshes that user's most recent AI suggestions with live prices,
  2. evaluates the alert triggers (target hit, big move, Strong-Buy flip),
  3. dedupes against the alerts table (so nothing is emailed twice a day),
  4. emails any genuinely new alerts.

It relies on each user's LAST in-app analysis (get_latest_run_suggestions) so
it doesn't need the LLM pipeline or an API key to run — it re-prices and
re-checks. Strong-Buy flips are detected against a per-user snapshot persisted
in settings.json, so a flip is real across separate job runs.

Nothing here fails the whole batch for one user: per-user errors are caught and
reported, and the job exits 0 unless it couldn't start at all.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import data.loader as loader
from agents.alerts import check_triggers
from agents import notifier
from db.store import init_db, log_alert, get_latest_run_suggestions
from db.users import init_users, list_users

# settings.json keys
PREF_ENABLED = "email_alerts_enabled"
PREF_EMAIL = "alert_email"
PREF_LAST_ACTIONS = "last_alert_actions"


def _refresh_prices(suggestions: list) -> list:
    """Re-price stored suggestions with a live quote so target-hit / big-move
    reflect the market right now, not the last in-app run."""
    out = []
    for s in suggestions:
        info = loader.fetch_ticker_info(s["symbol"])
        price = info.get("currentPrice") or info.get("regularMarketPrice") or s.get("current_price")
        chg = info.get("regularMarketChangePercent")
        out.append({
            **s,
            "current_price": price,
            "day_change_pct": (round(float(chg), 2) if chg is not None else s.get("day_change_pct")),
        })
    return out


def collect_new_alerts(user_id: int, previous_actions: dict) -> tuple:
    """Refresh the user's suggestions, evaluate triggers, and keep only alerts
    not already logged today (log_alert dedupes). Returns
    (new_alerts, current_actions)."""
    results = _refresh_prices(get_latest_run_suggestions(user_id))
    triggered = check_triggers(results, previous_actions or {})
    new_alerts = [
        a for a in triggered
        if log_alert(user_id, a["symbol"], a["type"], a["message"], a["dedup_key"])
    ]
    current_actions = {r["symbol"]: r["action"] for r in results}
    return new_alerts, current_actions


def run_for_user(user: dict, send=notifier.send_email) -> dict:
    """Process one user. Returns a summary dict describing what happened."""
    uid = user["id"]
    settings = loader.load_user_settings(uid)
    if not settings.get(PREF_ENABLED):
        return {"user_id": uid, "status": "disabled"}
    to_addr = (settings.get(PREF_EMAIL) or "").strip()
    if not to_addr:
        return {"user_id": uid, "status": "no_email"}

    prev = settings.get(PREF_LAST_ACTIONS) or {}
    new_alerts, current_actions = collect_new_alerts(uid, prev)

    # Persist the latest action snapshot so flips are meaningful next run.
    settings[PREF_LAST_ACTIONS] = current_actions
    loader.save_user_settings(uid, settings)

    if not new_alerts:
        return {"user_id": uid, "status": "no_new_alerts"}

    if not notifier.email_configured():
        # Alerts were still logged (visible in-app); we just can't email them.
        return {"user_id": uid, "status": "logged_email_unconfigured", "n_alerts": len(new_alerts)}

    subject, text, html = notifier.render_alert_email(user.get("display_name"), new_alerts)
    sent = send(to_addr, subject, text, html)
    return {"user_id": uid, "status": "sent" if sent else "send_failed",
            "n_alerts": len(new_alerts), "to": to_addr}


def main() -> int:
    init_users()
    init_db()
    if not notifier.email_configured():
        print("⚠ SMTP not configured (set SMTP_HOST/SMTP_FROM …). Alerts will be "
              "logged in-app but not emailed.")
    summaries = []
    for user in list_users():
        try:
            summaries.append(run_for_user(user))
        except Exception as e:  # one bad user must not sink the batch
            summaries.append({"user_id": user["id"], "status": "error", "error": str(e)})

    sent = sum(1 for s in summaries if s.get("status") == "sent")
    alerts = sum(s.get("n_alerts", 0) for s in summaries if s.get("status") in ("sent", "logged_email_unconfigured"))
    print(f"Alert run complete: {len(summaries)} user(s) checked, "
          f"{alerts} new alert(s), {sent} email(s) sent.")
    for s in summaries:
        if s["status"] not in ("disabled", "no_email", "no_new_alerts"):
            print(f"  · user {s['user_id']}: {s['status']}"
                  + (f" ({s['n_alerts']} alerts)" if s.get("n_alerts") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
