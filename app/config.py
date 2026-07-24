from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./yumn.db"
    api_key: str = "change-this-key"
    allowed_origins: str = "*"
    whatsapp_webhook_url: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    study_access_code: str = ""
    session_hours: int = 12
    max_request_bytes: int = 2_000_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def effective_admin_password(self) -> str:
        return self.admin_password or self.api_key


settings = Settings()
