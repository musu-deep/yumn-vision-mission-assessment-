from base64 import b64decode
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Yumn Health Strategy Platform API",
    version="1.0.0",
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
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok", "service": "yumn-platform"}


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


@app.post("/api/responses", dependencies=[Depends(require_api_key)])
def save_response(payload: ResponsePayload, db: Session = Depends(get_db)):
    row = db.get(ParticipantResponse, payload.username)
    if row is None:
        row = ParticipantResponse(username=payload.username)
        db.add(row)
    row.user_data = payload.user
    row.response_data = payload.data
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "username": payload.username}


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
