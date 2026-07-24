from typing import Any

from pydantic import BaseModel, Field


class ResponsePayload(BaseModel):
    username: str
    user: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class SyncPayload(BaseModel):
    users: list[dict[str, Any]] = Field(default_factory=list)
    responses: list[dict[str, Any]] = Field(default_factory=list)
    syncedAt: str | None = None


class WhatsAppPayload(BaseModel):
    phone: str
    message: str
