from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PlatformSnapshot(Base):
    __tablename__ = "platform_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    users: Mapped[list] = mapped_column(JSON, default=list)
    responses: Mapped[list] = mapped_column(JSON, default=list)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ParticipantAccount(Base):
    __tablename__ = "participant_accounts"

    username: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(30), default="editor")
    pin_salt: Mapped[str] = mapped_column(String(64))
    pin_hash: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ParticipantResponse(Base):
    __tablename__ = "participant_responses"

    username: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_data: Mapped[dict] = mapped_column(JSON, default=dict)
    response_data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class MessageLog(Base):
    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
