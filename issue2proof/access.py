"""Private-instance authentication, signed sessions and request guards."""

import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

COOKIE = "issue2proof_session"
LOGIN_WINDOW_SECONDS = 300
LOGIN_ATTEMPTS = 5
_attempts = {}
_attempts_lock = threading.Lock()


def public_mode():
    return os.environ.get("ISSUE2PROOF_PUBLIC", "0") == "1"


def configured_token():
    return os.environ.get("ISSUE2PROOF_ACCESS_TOKEN", "")


def validate_configuration():
    token = configured_token()
    if public_mode() and os.environ.get("ISSUE2PROOF_LEGACY_API") == "1":
        raise RuntimeError("Unbudgeted legacy endpoints cannot run in public mode.")
    if public_mode() and len(token) < 24:
        raise RuntimeError(
            "Public mode requires ISSUE2PROOF_ACCESS_TOKEN with at least 24 characters."
        )


def session(token):
    value = f"{int(time.time()) + 43200}.{secrets.token_hex(16)}"
    signature = hmac.new(token.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value + "." + signature


def authorized(request: Request):
    token = configured_token()
    if not token:
        return not public_mode() and request.url.hostname in {
            "127.0.0.1",
            "localhost",
            "testserver",
        }
    bearer = request.headers.get("authorization", "")
    if bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], token):
        return True
    cookie = request.cookies.get(COOKIE, "")
    try:
        expiry, nonce, signature = cookie.split(".")
        expected = hmac.new(
            token.encode(), f"{expiry}.{nonce}".encode(), hashlib.sha256
        ).hexdigest()
        return int(expiry) > time.time() and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


async def guard(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin writes are not permitted."}, status_code=403
            )
    if (
        request.url.path.startswith("/api/")
        and request.url.path
        not in {
            "/api/health",
            "/api/login",
        }
        and not authorized(request)
    ):
        return JSONResponse(
            {"detail": "Sign in with the application access token."},
            status_code=401,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api/") else "no-cache"
    )
    return response


def login(request, token):
    expected = configured_token()
    identity = hashlib.sha256(expected.encode()).hexdigest()[:16]
    address = request.client.host if request.client else "unknown"
    key = (identity, address)
    now = time.monotonic()
    with _attempts_lock:
        recent = [
            value
            for value in _attempts.get(key, [])
            if now - value < LOGIN_WINDOW_SECONDS
        ]
        _attempts[key] = recent
        if len(recent) >= LOGIN_ATTEMPTS:
            raise HTTPException(429, "Too many sign-in attempts. Try again later.")
    if not expected or not hmac.compare_digest(token, expected):
        with _attempts_lock:
            _attempts[key] = [*_attempts.get(key, []), now]
        raise HTTPException(401, "Invalid application access token.")
    with _attempts_lock:
        _attempts.pop(key, None)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        COOKIE,
        session(expected),
        httponly=True,
        samesite="strict",
        secure=public_mode(),
        max_age=43200,
    )
    return response
