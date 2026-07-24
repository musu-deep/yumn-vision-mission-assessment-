from base64 import b64decode
from contextlib import asynccontextmanager
from datetime import datetime
from hmac import compare_digest
from pathlib import Path
import re

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from .models import MessageLog, ParticipantResponse, PlatformSnapshot
from .schemas import ResponsePayload, SyncPayload, WhatsAppPayload


FAVICON_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABVklEQVR42u2bSQ7CMAxFGwsJLsVwdIZLwQpWbColzeDvJO73vpHfy3cUqrIsLBZrzxU0Fjlez99eAJ/HK3QR0BNaU0bwAN4iQrzBl/YZPIHXpEE8w+f0L8vOSzzvfg6HeIff4uEI7GH3U1xMwEzNvu9PvACt+Gs3+1+vdd01nyB3SkvCeh1NuYKOaWuzsee1JIjFjNY2m3rudLuMJyDVVKkEC3jICGhIsIKHHYKaSUDCQ+8Btc3GBCHg4RehWNOlhyUK3uQmmCsBccsb/iqcc2FC7r6ZgNpDEQ1vmoBSGAt48xHIhbKC73IGbMFZwnc7BK0h3bwQoQAKoAAKoAAKoAAKoAAKoAAKoAAKAAlo/fZ29FrzHXo1MspLEY5ATky8xp8JSAnwloIYj9Q85AWeI5AjYPYUbPVfBDfTJ7S5GyeIRWeBL07A6Gkw+dfYaDK8/3ZhscD1A/iOndDEvzLhAAAAAElFTkSuQmCC"
)


def normalize_phone(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def participant_username(phone: str) -> str:
    return f"mobile_{normalize_phone(phone)}"


def has_valid_api_key(value: str | None) -> bool:
    return bool(settings.api_key and value and compare_digest(value, settings.api_key))


def verify_participant_payload(payload: ResponsePayload, x_api_key: str | None) -> None:
    if has_valid_api_key(x_api_key):
        return

    phone = normalize_phone(payload.user.get("phone"))
    role = str(payload.user.get("role") or "")
    if not phone or not 8 <= len(phone) <= 15:
        raise HTTPException(status_code=400, detail="Valid participant phone is required")
    if payload.username != participant_username(phone):
        raise HTTPException(status_code=403, detail="Participant identity mismatch")
    if role not in {"editor", "reviewer", "viewer", "consultant"}:
        raise HTTPException(status_code=403, detail="Participant role is not allowed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Yumn Health Strategy Platform API",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: str | None = Header(default=None)):
    if not has_valid_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1)).scalar_one()
    return {"status": "ok", "service": "yumn-platform", "database": "ok"}


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


@app.post("/api/responses")
def save_response(
    payload: ResponsePayload,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    verify_participant_payload(payload, x_api_key)

    row = db.get(ParticipantResponse, payload.username)
    if row is None:
        row = ParticipantResponse(username=payload.username)
        db.add(row)

    row.user_data = {
        "name": str(payload.user.get("name") or "").strip()[:200],
        "phone": normalize_phone(payload.user.get("phone")),
        "role": str(payload.user.get("role") or "editor"),
    }
    row.response_data = payload.data
    row.updated_at = datetime.utcnow()
    db.commit()
    return {
        "status": "ok",
        "storage": "database",
        "username": payload.username,
        "updatedAt": row.updated_at.isoformat(),
    }


@app.get("/api/responses/{username}")
def get_participant_response(
    username: str,
    phone: str = Query(min_length=8, max_length=32),
    db: Session = Depends(get_db),
):
    normalized_phone = normalize_phone(phone)
    if username != participant_username(normalized_phone):
        raise HTTPException(status_code=403, detail="Participant identity mismatch")

    row = db.get(ParticipantResponse, username)
    if row is None:
        raise HTTPException(status_code=404, detail="Response not found")

    stored_phone = normalize_phone((row.user_data or {}).get("phone"))
    if stored_phone and stored_phone != normalized_phone:
        raise HTTPException(status_code=403, detail="Participant identity mismatch")

    return {
        "username": row.username,
        "user": row.user_data or {},
        "data": row.response_data or {},
        "updatedAt": row.updated_at.isoformat(),
    }


@app.post("/api/sync", dependencies=[Depends(require_api_key)])
def save_snapshot(payload: SyncPayload, db: Session = Depends(get_db)):
    snapshot = PlatformSnapshot(
        users=payload.users,
        responses=payload.responses,
        synced_at=datetime.utcnow(),
    )
    db.add(snapshot)

    for item in payload.responses:
        username = item.get("username")
        if not username:
            continue
        row = db.get(ParticipantResponse, username) or ParticipantResponse(username=username)
        row.user_data = {key: item.get(key) for key in ("name", "phone", "role")}
        row.response_data = item.get("data") or {}
        row.updated_at = datetime.utcnow()
        db.merge(row)

    db.commit()
    return {"status": "ok", "responses": len(payload.responses)}


@app.get("/api/sync", dependencies=[Depends(require_api_key)])
def get_snapshot(db: Session = Depends(get_db)):
    snapshot = db.scalar(
        select(PlatformSnapshot).order_by(PlatformSnapshot.id.desc()).limit(1)
    )
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
            {
                "username": row.username,
                **(row.user_data or {}),
                "data": row.response_data or {},
            }
            for row in rows
        ],
    }


@app.post("/api/whatsapp/send", dependencies=[Depends(require_api_key)])
async def send_whatsapp(payload: WhatsAppPayload, db: Session = Depends(get_db)):
    log = MessageLog(phone=payload.phone, message=payload.message, status="queued")
    db.add(log)
    db.commit()

    if not settings.whatsapp_webhook_url:
        return {"status": "queued", "delivery": "not-configured"}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.whatsapp_webhook_url,
            json=payload.model_dump(),
        )

    log.status = "sent" if response.is_success else "failed"
    db.commit()

    if not response.is_success:
        raise HTTPException(status_code=502, detail="WhatsApp webhook failed")
    return {"status": "sent"}
