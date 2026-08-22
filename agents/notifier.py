"""
Email delivery for alerts — the server-side half of the alert system.

Until now alerts only surfaced while the user had the Streamlit app open. This
adds an SMTP sender so a scheduled job (scripts/run_alerts.py) can email new
alerts, letting users find out about a target hit or a big move without sitting
in front of the dashboard.

Configuration is entirely via environment variables, so nothing secret is ever
committed:

    SMTP_HOST         e.g. smtp.gmail.com
    SMTP_PORT         default 587 (STARTTLS)
    SMTP_USER         username for the SMTP server
    SMTP_PASSWORD     password / app-password
    SMTP_FROM         From: address (defaults to SMTP_USER)
    SMTP_USE_TLS      "1" (default) to STARTTLS, "0" for a plain connection

If SMTP isn't configured, email_configured() returns False and send_email()
is a graceful no-op — the app and the alert job keep working, just without email.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

# Rendering is pure (no I/O), so it's unit-tested directly.
_ACTION_EMOJI = {
    "strong_buy_flip": "🚀",
    "price_target_hit": "🎯",
    "big_move": "⚡",
}


def _smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from": (os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "").strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "1").strip() != "0",
    }


def email_configured() -> bool:
    """True only if the minimum SMTP settings are present."""
    c = _smtp_config()
    return bool(c["host"] and c["from"])


def render_alert_email(display_name: str, alerts: list) -> tuple:
    """Build (subject, text_body, html_body) for a batch of alert dicts
    ({symbol, type, message}). Pure — no network, no env. Raises ValueError on
    an empty batch so callers don't send blank emails."""
    if not alerts:
        raise ValueError("render_alert_email called with no alerts")

    n = len(alerts)
    subject = (f"📈 {n} new stock alert" + ("s" if n != 1 else "")
               + f" — {alerts[0]['symbol']}"
               + (f" +{n - 1} more" if n > 1 else ""))

    lines = [f"Hi {display_name or 'there'},", "",
             f"{n} new alert{'s' if n != 1 else ''} from your Stock Advisor watchlist:", ""]
    for a in alerts:
        lines.append(f"  {_ACTION_EMOJI.get(a['type'], '•')} {a['message']}")
    lines += ["", "— Stock Advisor",
              "(You can turn these emails off in the app under Settings.)"]
    text_body = "\n".join(lines)

    items = "".join(
        f'<li style="margin:6px 0">{_ACTION_EMOJI.get(a["type"], "•")} '
        f'<strong>{a["symbol"]}</strong> — {a["message"]}</li>'
        for a in alerts
    )
    html_body = (
        f'<div style="font-family:Inter,Arial,sans-serif;color:#0f172a">'
        f'<p>Hi {display_name or "there"},</p>'
        f'<p>{n} new alert{"s" if n != 1 else ""} from your Stock Advisor watchlist:</p>'
        f'<ul style="list-style:none;padding-left:0">{items}</ul>'
        f'<p style="color:#64748b;font-size:12px">— Stock Advisor · '
        f'turn these off anytime in the app under Settings.</p></div>'
    )
    return subject, text_body, html_body


def send_email(to_addr: str, subject: str, text_body: str, html_body: str = None) -> bool:
    """Send one email. Returns True if sent, False if SMTP isn't configured or
    the recipient is missing. Raises on an actual SMTP/connection failure so the
    caller (a job) can log it — it does not silently swallow real errors."""
    if not to_addr or not email_configured():
        return False
    c = _smtp_config()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = c["from"]
    msg["To"] = to_addr
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(c["host"], c["port"], timeout=30) as server:
        if c["use_tls"]:
            server.starttls(context=ssl.create_default_context())
        if c["user"]:
            server.login(c["user"], c["password"])
        server.send_message(msg)
    return True
