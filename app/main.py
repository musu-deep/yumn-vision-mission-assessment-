from __future__ import annotations

from base64 import b64decode, urlsafe_b64decode, urlsafe_b64encode
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest, new as hmac_new
import json
from pathlib import Path
import re
import secrets
from threading import Lock
from time import monotonic
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from .models import MessageLog, ParticipantAccount, ParticipantResponse, PlatformSnapshot
from .schemas import (
    AdminLoginPayload,
    ParticipantAdminUpdate,
    ParticipantLoginPayload,
    ResponsePayload,
    SyncPayload,
    WhatsAppPayload,
)


SESSION_COOKIE = "yumn_session"
SESSION_MAX_AGE = max(1, settings.session_hours) * 60 * 60
PIN_ITERATIONS = 310_000
ACCOUNT_LOCK_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5
ALLOWED_PARTICIPANT_ROLES = {"editor", "reviewer", "viewer", "consultant"}
RESTRICTED_DATA_KEYS = {"identity", "objectives", "impact", "targets", "final"}

FAVICON_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABVklEQVR42u2bSQ7CMAxFGwsJLsVwdIZLwQpWbColzeDvJO73vpHfy3cUqrIsLBZrzxU0Fjlez99eAJ/HK3QR0BNaU0bwAN4iQrzBl/YZPIHXpEE8w+f0L8vOSzzvfg6HeIff4uEI7GH3U1xMwEzNvu9PvACt+Gs3+1+vdd01nyB3SkvCeh1NuYKOaWuzsee1JIjFjNY2m3rudLuMJyDVVKkEC3jICGhIsIKHHYKaSUDCQ+8Btc3GBCHg4RehWNOlhyUK3uQmmCsBccsb/iqcc2FC7r6ZgNpDEQ1vmoBSGAt48xHIhbKC73IGbMFZwnc7BK0h3bwQoQAKoAAKoAAKoAAKoAAKoAAKoAAKAAlo/fZ29FrzHXo1MspLEY5ATky8xp8JSAnwloIYj9Q85AWeI5AjYPYUbPVfBDfTJ7S5GyeIRWeBL07A6Gkw+dfYaDK8/3ZhscD1A/iOndDEvzLhAAAAAElFTkSuQmCC"
)


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many attempts. Please try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


rate_limiter = SlidingWindowLimiter()


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_phone(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def participant_username(phone: str) -> str:
    return f"mobile_{normalize_phone(phone)}"


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def has_valid_api_key(value: str | None) -> bool:
    return bool(settings.api_key and value and compare_digest(value, settings.api_key))


def b64url_encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def session_secret() -> bytes:
    return settings.api_key.encode("utf-8")


def create_session_token(username: str, role: str, session_version: int = 1) -> str:
    payload = {
        "sub": username,
        "role": role,
        "ver": session_version,
        "exp": int((utcnow() + timedelta(seconds=SESSION_MAX_AGE)).timestamp()),
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = b64url_encode(hmac_new(session_secret(), encoded.encode("ascii"), sha256).digest())
    return f"{encoded}.{signature}"


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = b64url_encode(hmac_new(session_secret(), encoded.encode("ascii"), sha256).digest())
        if not compare_digest(signature, expected):
            return None
        payload = json.loads(b64url_decode(encoded))
        if int(payload.get("exp", 0)) <= int(utcnow().timestamp()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def hash_pin(pin: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS)
    return b64url_encode(salt), b64url_encode(digest)


def verify_pin(pin: str, salt_value: str, expected_hash: str) -> bool:
    try:
        salt = b64url_decode(salt_value)
        _, candidate = hash_pin(pin, salt)
        return compare_digest(candidate, expected_hash)
    except (ValueError, TypeError):
        return False


def request_is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def delete_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def external_origin(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{scheme}://{host}".rstrip("/")


def origin_allowed(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not origin:
        return request.headers.get("sec-fetch-site") in {None, "same-origin", "same-site", "none"}
    if origin == external_origin(request):
        return True
    return settings.origins != ["*"] and origin in settings.origins


def response_user(account: ParticipantAccount) -> dict[str, str]:
    return {
        "username": account.username,
        "name": account.name,
        "phone": account.phone,
        "role": account.role,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Yumn Health Strategy Platform API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=settings.origins != ["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def platform_security(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        return JSONResponse(status_code=413, content={"detail": "Request body is too large."})

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        if not has_valid_api_key(request.headers.get("x-api-key")) and not origin_allowed(request):
            return JSONResponse(status_code=403, content={"detail": "Cross-site request rejected."})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request_is_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_identity(
    request: Request,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    if has_valid_api_key(x_api_key):
        return {"username": settings.admin_username, "role": "admin", "via": "api-key"}

    token = request.cookies.get(SESSION_COOKIE, "")
    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Authentication required")

    username = str(payload.get("sub") or "")
    role = str(payload.get("role") or "")
    if role == "admin":
        if username != settings.admin_username:
            raise HTTPException(status_code=401, detail="Invalid session")
        return {"username": username, "role": "admin", "via": "session"}

    account = db.get(ParticipantAccount, username)
    if not account or not account.active or account.role not in ALLOWED_PARTICIPANT_ROLES:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    if int(payload.get("ver", 0)) != account.session_version:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    return {**response_user(account), "via": "session"}


def require_admin(identity: dict[str, Any] = Depends(get_identity)) -> dict[str, Any]:
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return identity


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1)).scalar_one()
    security_ready = bool(
        settings.api_key != "change-this-key"
        and settings.effective_admin_password != "change-this-key"
        and settings.origins != ["*"]
    )
    return {
        "status": "ok",
        "service": "yumn-platform",
        "database": "ok",
        "auth": "session-cookie",
        "security": "ok" if security_ready else "configuration-required",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(
        content=FAVICON_PNG,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@app.get("/")
def frontend():
    path = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    return FileResponse(path)


@app.get("/api/public-config")
def public_config():
    return {
        "participantPinRequired": True,
        "pinLength": 6,
        "studyCodeRequired": bool(settings.study_access_code),
        "sessionHours": max(1, settings.session_hours),
    }


@app.post("/api/auth/participant")
def participant_login(
    payload: ParticipantLoginPayload,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    phone = normalize_phone(payload.phone)
    if not 8 <= len(phone) <= 15:
        raise HTTPException(status_code=400, detail="Valid phone number is required")

    ip = client_ip(request)
    rate_limiter.check(f"participant-auth-ip:{ip}", limit=20, window_seconds=600)
    rate_limiter.check(f"participant-auth-phone:{phone}", limit=8, window_seconds=900)

    username = participant_username(phone)
    account = db.get(ParticipantAccount, username)
    created = account is None

    if created:
        if settings.study_access_code and not compare_digest(payload.study_code, settings.study_access_code):
            raise HTTPException(status_code=403, detail="Study access code is invalid")
        salt, pin_digest = hash_pin(payload.pin)
        account = ParticipantAccount(
            username=username,
            name=payload.name.strip(),
            phone=phone,
            role="editor",
            pin_salt=salt,
            pin_hash=pin_digest,
            active=True,
            failed_attempts=0,
            session_version=1,
        )
        db.add(account)
    else:
        if not account.active:
            raise HTTPException(status_code=403, detail="This participation has been disabled")
        if account.locked_until and account.locked_until > utcnow():
            retry_after = max(1, int((account.locked_until - utcnow()).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail="This account is temporarily locked",
                headers={"Retry-After": str(retry_after)},
            )
        if not verify_pin(payload.pin, account.pin_salt, account.pin_hash):
            account.failed_attempts += 1
            if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
                account.locked_until = utcnow() + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
            db.commit()
            raise HTTPException(status_code=401, detail="Phone number or personal PIN is incorrect")
        account.failed_attempts = 0
        account.locked_until = None
        account.name = payload.name.strip()
        account.updated_at = utcnow()

    db.commit()
    db.refresh(account)
    token = create_session_token(account.username, account.role, account.session_version)
    set_session_cookie(response, token)
    return {"status": "ok", "created": created, "user": response_user(account)}


@app.post("/api/auth/admin")
def admin_login(payload: AdminLoginPayload, request: Request, response: Response):
    rate_limiter.check(f"admin-auth-ip:{client_ip(request)}", limit=10, window_seconds=900)
    valid_username = compare_digest(payload.username.strip().lower(), settings.admin_username.lower())
    valid_password = compare_digest(payload.password, settings.effective_admin_password)
    if not (valid_username and valid_password):
        raise HTTPException(status_code=401, detail="Administrator credentials are incorrect")
    token = create_session_token(settings.admin_username, "admin", 1)
    set_session_cookie(response, token)
    return {
        "status": "ok",
        "user": {
            "username": settings.admin_username,
            "name": "مدير منصة يُمن",
            "phone": "",
            "role": "admin",
        },
    }


@app.get("/api/auth/me")
def auth_me(identity: dict[str, Any] = Depends(get_identity)):
    return {"authenticated": True, "user": {key: identity.get(key, "") for key in ("username", "name", "phone", "role")}}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    delete_session_cookie(response)
    return {"status": "ok"}


@app.post("/api/responses")
def save_response(
    payload: ResponsePayload,
    request: Request,
    db: Session = Depends(get_db),
    identity: dict[str, Any] = Depends(get_identity),
):
    if identity["role"] != "admin" and payload.username != identity["username"]:
        raise HTTPException(status_code=403, detail="You can only update your own response")

    rate_limiter.check(
        f"response-write:{identity['username']}:{client_ip(request)}",
        limit=120,
        window_seconds=60,
    )

    row = db.get(ParticipantResponse, payload.username)
    if row is None:
        row = ParticipantResponse(username=payload.username)
        db.add(row)

    if identity["role"] == "admin":
        user_data = {
            "name": str(payload.user.get("name") or "").strip()[:200],
            "phone": normalize_phone(payload.user.get("phone")),
            "role": str(payload.user.get("role") or "editor"),
        }
    else:
        user_data = {
            "name": identity["name"],
            "phone": identity["phone"],
            "role": identity["role"],
        }

    incoming_data = dict(payload.data)
    if identity["role"] != "admin":
        meta = dict(incoming_data.get("meta") or {})
        meta["respondentName"] = identity["name"]
        meta["phone"] = identity["phone"]
        incoming_data["meta"] = meta

    if identity["role"] not in {"admin", "consultant"}:
        existing_data = row.response_data or {}
        for key in RESTRICTED_DATA_KEYS:
            if key in existing_data:
                incoming_data[key] = existing_data[key]
            else:
                incoming_data.pop(key, None)

    row.user_data = user_data
    row.response_data = incoming_data
    row.updated_at = utcnow()
    db.commit()
    return {
        "status": "ok",
        "storage": "database",
        "username": row.username,
        "updatedAt": row.updated_at.isoformat(),
    }


@app.get("/api/responses/me")
def get_my_response(
    db: Session = Depends(get_db),
    identity: dict[str, Any] = Depends(get_identity),
):
    if identity["role"] == "admin":
        raise HTTPException(status_code=400, detail="Administrator must specify a participant")
    row = db.get(ParticipantResponse, identity["username"])
    if row is None:
        raise HTTPException(status_code=404, detail="Response not found")
    return {
        "username": row.username,
        "user": row.user_data or {},
        "data": row.response_data or {},
        "updatedAt": row.updated_at.isoformat(),
    }


@app.get("/api/responses/{username}")
def get_participant_response(
    username: str,
    db: Session = Depends(get_db),
    _: dict[str, Any] = Depends(require_admin),
):
    row = db.get(ParticipantResponse, username)
    if row is None:
        raise HTTPException(status_code=404, detail="Response not found")
    return {
        "username": row.username,
        "user": row.user_data or {},
        "data": row.response_data or {},
        "updatedAt": row.updated_at.isoformat(),
    }


@app.get("/api/admin/participants")
def admin_participants(
    db: Session = Depends(get_db),
    _: dict[str, Any] = Depends(require_admin),
):
    accounts = db.scalars(select(ParticipantAccount).order_by(ParticipantAccount.created_at.desc())).all()
    result = []
    for account in accounts:
        saved = db.get(ParticipantResponse, account.username)
        result.append(
            {
                **response_user(account),
                "active": account.active,
                "createdAt": account.created_at.isoformat(),
                "updatedAt": account.updated_at.isoformat(),
                "hasResponse": saved is not None,
                "responseUpdatedAt": saved.updated_at.isoformat() if saved else None,
            }
        )
    return {"participants": result}


@app.patch("/api/admin/participants/{username}")
def admin_update_participant(
    username: str,
    payload: ParticipantAdminUpdate,
    db: Session = Depends(get_db),
    _: dict[str, Any] = Depends(require_admin),
):
    account = db.get(ParticipantAccount, username)
    if account is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    if payload.active is not None:
        account.active = payload.active
        if not payload.active:
            account.session_version += 1
    if payload.role is not None:
        account.role = payload.role
        account.session_version += 1
    account.updated_at = utcnow()
    db.commit()
    return {"status": "ok", "user": response_user(account), "active": account.active}


@app.post("/api/admin/participants/{username}/reset-pin")
def admin_reset_participant_pin(
    username: str,
    db: Session = Depends(get_db),
    _: dict[str, Any] = Depends(require_admin),
):
    account = db.get(ParticipantAccount, username)
    if account is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    temporary_pin = f"{secrets.randbelow(1_000_000):06d}"
    salt, pin_digest = hash_pin(temporary_pin)
    account.pin_salt = salt
    account.pin_hash = pin_digest
    account.failed_attempts = 0
    account.locked_until = None
    account.session_version += 1
    account.updated_at = utcnow()
    db.commit()
    return {"status": "ok", "temporaryPin": temporary_pin}


@app.delete("/api/admin/responses/{username}")
def admin_delete_response(
    username: str,
    db: Session = Depends(get_db),
    _: dict[str, Any] = Depends(require_admin),
):
    row = db.get(ParticipantResponse, username)
    if row is None:
        raise HTTPException(status_code=404, detail="Response not found")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@app.post("/api/sync", dependencies=[Depends(require_admin)])
def save_snapshot(payload: SyncPayload, db: Session = Depends(get_db)):
    snapshot = PlatformSnapshot(
        users=payload.users,
        responses=payload.responses,
        synced_at=utcnow(),
    )
    db.add(snapshot)
    for item in payload.responses:
        username = item.get("username")
        if not username:
            continue
        row = db.get(ParticipantResponse, username) or ParticipantResponse(username=username)
        row.user_data = {key: item.get(key) for key in ("name", "phone", "role")}
        row.response_data = item.get("data") or {}
        row.updated_at = utcnow()
        db.merge(row)
    db.commit()
    return {"status": "ok", "responses": len(payload.responses)}


@app.get("/api/sync", dependencies=[Depends(require_admin)])
def get_snapshot(db: Session = Depends(get_db)):
    snapshot = db.scalar(select(PlatformSnapshot).order_by(PlatformSnapshot.id.desc()).limit(1))
    if snapshot:
        return {
            "users": snapshot.users,
            "responses": snapshot.responses,
            "syncedAt": snapshot.synced_at.isoformat(),
        }
    rows = db.scalars(select(ParticipantResponse)).all()
    return {
        "users": [],
        "responses": [
            {"username": row.username, **(row.user_data or {}), "data": row.response_data or {}}
            for row in rows
        ],
    }


@app.post("/api/whatsapp/send", dependencies=[Depends(require_admin)])
async def send_whatsapp(payload: WhatsAppPayload, db: Session = Depends(get_db)):
    log = MessageLog(phone=payload.phone, message=payload.message, status="queued")
    db.add(log)
    db.commit()
    if not settings.whatsapp_webhook_url:
        return {"status": "queued", "delivery": "not-configured"}
    async with httpx.AsyncClient(timeout=20) as client:
        webhook_response = await client.post(settings.whatsapp_webhook_url, json=payload.model_dump())
    log.status = "sent" if webhook_response.is_success else "failed"
    db.commit()
    if not webhook_response.is_success:
        raise HTTPException(status_code=502, detail="WhatsApp webhook failed")
    return {"status": "sent"}
