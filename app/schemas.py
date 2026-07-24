from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ParticipantLoginPayload(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=8, max_length=32)
    pin: str = Field(min_length=6, max_length=12)
    study_code: str = Field(default="", max_length=64)

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("PIN must contain digits only")
        return value


class AdminLoginPayload(BaseModel):
    username: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class ResponsePayload(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    user: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class SyncPayload(BaseModel):
    users: list[dict[str, Any]] = Field(default_factory=list)
    responses: list[dict[str, Any]] = Field(default_factory=list)
    syncedAt: str | None = None


class ParticipantAdminUpdate(BaseModel):
    active: bool | None = None
    role: Literal["editor", "reviewer", "viewer", "consultant"] | None = None


class WhatsAppPayload(BaseModel):
    phone: str
    message: str
