"""
Background poller: re-scores the watchlist on an interval during US market hours
and fires macOS desktop notifications + a log file when a trigger condition fires.

Run with:  python3 scripts/alert_poller.py
Stop with: Ctrl+C
"""
import sys, pathlib, time, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.run_analysis import run_analysis
from agents.alerts import check_triggers
from db.store import init_db, log_alert

POLL_INTERVAL_SECONDS = 300  # 5 minutes
LOG_PATH = pathlib.Path(__file__).parent.parent / "alerts.log"
ET = ZoneInfo("America/New_York")


def _is_market_hours(now: datetime) -> bool:
    now_et = now.astimezone(ET)
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now_et <= close_t


def _notify(title: str, message: str):
    # macOS desktop notification
    script = f'display notification "{message}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass

    with open(LOG_PATH, "a") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {title}: {message}\n")


def run_once(user_id: int, previous_actions: dict) -> dict:
    results, regime = run_analysis(user_id, status_cb=None, use_llm_regime=True)
    alerts = check_triggers(results, previous_actions)

    for alert in alerts:
        newly_logged = log_alert(user_id, alert["symbol"], alert["type"], alert["message"], alert["dedup_key"])
        if newly_logged:
            _notify("Stock Advisor", alert["message"])

    return {r["symbol"]: r["action"] for r in results}


def main():
    init_db()
    # The poller runs on the owner's machine, so it watches the owner's watchlist
    from db.users import get_owner
    owner = get_owner()
    if not owner:
        print("No accounts yet — sign up in the app first (the first account becomes the owner).")
        return
    print(f"Alert poller started for @{owner['username']}. "
          f"Polling every {POLL_INTERVAL_SECONDS}s during market hours (9:30-16:00 ET).")
    print(f"Logging to {LOG_PATH}")

    previous_actions = {}
    try:
        while True:
            now = datetime.now()
            if _is_market_hours(now):
                print(f"[{now.isoformat()}] Checking triggers...")
                try:
                    previous_actions = run_once(owner["id"], previous_actions)
                except Exception as e:
                    print(f"Error during check: {e}")
            else:
                print(f"[{now.isoformat()}] Outside market hours, sleeping...")
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nAlert poller stopped.")


if __name__ == "__main__":
    main()
