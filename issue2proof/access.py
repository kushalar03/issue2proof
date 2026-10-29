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
    return os.environ.get("ISSUE2PROOF_ACCESS_TOKEN", "").strip()


def configured_judge_token():
    return os.environ.get("ISSUE2PROOF_JUDGE_TOKEN", "").strip()


def validate_configuration():
    token = configured_token()
    if public_mode() and os.environ.get("ISSUE2PROOF_LEGACY_API") == "1":
        raise RuntimeError("Unbudgeted legacy endpoints cannot run in public mode.")
    if public_mode() and len(token) < 24:
        raise RuntimeError(
            "Public mode requires ISSUE2PROOF_ACCESS_TOKEN with at least 24 characters."
        )
    judge = configured_judge_token()
    if judge and len(judge) < 24:
        raise RuntimeError("ISSUE2PROOF_JUDGE_TOKEN must contain at least 24 characters.")
    if judge and hmac.compare_digest(judge, token):
        raise RuntimeError("Administrator and judge tokens must be different.")


def session(token, role):
    value = f"{int(time.time()) + 43200}.{secrets.token_hex(16)}"
    signed = value + "." + role
    signature = hmac.new(token.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return signed + "." + signature


def access_role(request: Request):
    tokens = (("admin", configured_token()), ("judge", configured_judge_token()))
    bearer = request.headers.get("authorization", "")
    if bearer.startswith("Bearer "):
        supplied = bearer[7:]
        for role, token in tokens:
            if token and hmac.compare_digest(supplied, token):
                return role
    cookie = request.cookies.get(COOKIE, "")
    try:
        expiry, nonce, role, signature = cookie.split(".")
        token = dict(tokens).get(role, "")
        expected = hmac.new(
            token.encode(), f"{expiry}.{nonce}.{role}".encode(), hashlib.sha256
        ).hexdigest()
        if token and int(expiry) > time.time() and hmac.compare_digest(signature, expected):
            return role
    except (ValueError, TypeError):
        pass
    return None


def authorized(request: Request):
    token = configured_token()
    if not token and not configured_judge_token():
        return not public_mode() and request.url.hostname in {
            "127.0.0.1",
            "localhost",
            "testserver",
        }
    return access_role(request) is not None


async def guard(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin writes are not permitted."}, status_code=403
            )
    role = access_role(request)
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
    if role == "judge":
        path = request.url.path
        if request.method == "GET" and path in {"/api/runs", "/api/jobs", "/api/memories"}:
            return JSONResponse([])
        restricted = (
            request.method == "DELETE"
            or (request.method == "GET" and path == "/api/memories/export")
            or (request.method == "POST" and path == "/api/memories/import")
            or (
                request.method == "POST"
                and path.startswith("/api/jobs/")
                and path.rsplit("/", 1)[-1] in {"cancel", "resume", "clarify"}
            )
            or (request.method == "POST" and path.startswith("/api/examples/") and path.endswith("/memory"))
            or (request.method == "POST" and path.startswith("/api/memories/") and (path.endswith("/supersede") or path.endswith("/enrich")))
        )
        if restricted:
            return JSONResponse(
                {"detail": "This action requires the administrator credential."},
                status_code=403,
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
    admin = configured_token()
    judge = configured_judge_token()
    token = token.strip()
    identity = hashlib.sha256((admin + "\0" + judge).encode()).hexdigest()[:16]
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
    role = None
    expected = ""
    for candidate_role, candidate in (("admin", admin), ("judge", judge)):
        if candidate and hmac.compare_digest(token, candidate):
            role, expected = candidate_role, candidate
            break
    if role is None:
        with _attempts_lock:
            _attempts[key] = [*_attempts.get(key, []), now]
        raise HTTPException(401, "Invalid application access token.")
    with _attempts_lock:
        _attempts.pop(key, None)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        COOKIE,
        session(expected, role),
        httponly=True,
        samesite="strict",
        secure=public_mode(),
        max_age=43200,
    )
    return response
