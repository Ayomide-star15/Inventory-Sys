from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    APP_NAME: str
    DEBUG: bool = False

    # Database
    MONGODB_URL: str
    DATABASE_NAME: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # SendGrid
    SENDGRID_API_KEY: str = ""
    MAIL_FROM: str = ""
    MAIL_FROM_NAME: str = "Inventory Management System"

    # Admin
    ADMIN_EMAIL_1: str | None = None
    ADMIN_PASSWORD_1: str | None = None
    ADMIN_EMAIL_2: str | None = None
    ADMIN_PASSWORD_2: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
