from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./yumn.db"
    api_key: str = "change-this-key"
    allowed_origins: str = "*"
    whatsapp_webhook_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


settings = Settings()
