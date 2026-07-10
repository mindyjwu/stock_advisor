"""
Stateless bearer-token auth for the API.

Streamlit uses server-side session state; a REST API can't, so we issue a
signed token on login and verify it on each request. The token is
"<user_id>.<issued_ts>.<hmac>" — no server-side storage, tamper-proof via an
HMAC over a server secret. Same accounts as the Streamlit app (db.users).

Set API_SECRET in the environment for production. The default is a clearly
marked dev-only value.
"""
import base64
import hashlib
import hmac
import os
import time

_SECRET = os.environ.get("API_SECRET", "dev-only-insecure-secret-change-me").encode()
TOKEN_TTL_SECONDS = int(os.environ.get("API_TOKEN_TTL", str(30 * 24 * 3600)))  # 30 days


def _sign(msg: str) -> str:
    digest = hmac.new(_SECRET, msg.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_token(user_id: int) -> str:
    payload = f"{int(user_id)}.{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str):
    """Return the user_id for a valid, unexpired token, else None."""
    try:
        uid_s, ts_s, sig = token.split(".")
        payload = f"{uid_s}.{ts_s}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if time.time() - int(ts_s) > TOKEN_TTL_SECONDS:
            return None
        return int(uid_s)
    except (ValueError, AttributeError):
        return None
