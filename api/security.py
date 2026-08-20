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
import warnings

_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"
_SECRET_STR = os.environ.get("API_SECRET", _DEFAULT_SECRET)
_SECRET = _SECRET_STR.encode()
TOKEN_TTL_SECONDS = int(os.environ.get("API_TOKEN_TTL", str(30 * 24 * 3600)))  # 30 days

# Refuse to run in production with the shipped dev secret; warn otherwise.
if _SECRET_STR == _DEFAULT_SECRET:
    if os.environ.get("APP_ENV", "").lower() in ("prod", "production"):
        raise RuntimeError(
            "API_SECRET must be set in production — refusing to start with the dev default. "
            "Set a strong, random API_SECRET environment variable."
        )
    warnings.warn(
        "API_SECRET is the insecure development default. Set API_SECRET before deploying.",
        stacklevel=2,
    )


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
