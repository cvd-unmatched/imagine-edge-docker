"""
Single-user session auth: a signed cookie, no session store.

The app has one operator, so this is deliberately minimal: no user table, no
password hashing library dependency, just a constant-time credential
comparison and an HMAC-signed timestamp cookie. Credentials and the signing
key come from settings, which main.py refuses to start without (see the
lifespan startup check), so the app never silently runs wide open.
"""

import hashlib
import hmac
import time

from fastapi import Request

from .config import Settings

COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _sign(value: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def _verify(token: str, secret: str) -> bool:
    try:
        value, mac = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return False
    try:
        issued_at = int(value)
    except ValueError:
        return False
    return (time.time() - issued_at) < SESSION_MAX_AGE_SECONDS


def create_session_cookie(settings: Settings) -> str:
    return _sign(str(int(time.time())), settings.webapp_secret_key)


def is_authenticated(request: Request, settings: Settings) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return _verify(token, settings.webapp_secret_key)


def check_credentials(username: str, password: str, settings: Settings) -> bool:
    user_ok = hmac.compare_digest(username, settings.webapp_username)
    pass_ok = hmac.compare_digest(password, settings.webapp_password)
    return user_ok and pass_ok
