"""Application settings.

All configuration comes from environment variables (12-factor). Nothing that is
environment specific may be hardcoded anywhere else in the codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    ENV: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = False
    PROJECT_NAME: str = "Hamroh"
    API_V1_PREFIX: str = "/api/v1"
    # Data residency: medical data must be stored inside Uzbekistan. This is a
    # legal requirement, not a latency optimisation. The value is surfaced in
    # /health so deployments can be audited.
    DATA_RESIDENCY_REGION: str = "UZ"

    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 60
    ALGORITHM: str = "HS256"

    DEFAULT_LOCALE: Literal["uz", "ru", "en"] = "uz"

    # --------------------------------------------------------------- database
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "hamroh"
    POSTGRES_PASSWORD: str = "hamroh"
    POSTGRES_DB: str = "hamroh"
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SQL_ECHO: bool = False

    # ------------------------------------------------------------------ redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # --------------------------------------------------------------- storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_PUBLIC_ENDPOINT_URL: str | None = None
    S3_REGION: str = "uz-1"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "hamroh-documents"
    S3_PRESIGN_TTL_SECONDS: int = 900
    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024

    # ------------------------------------------------------------------- otp
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_PER_PHONE_PER_DAY: int = 10
    # When set, OTP codes are not sent but returned by the API. local/staging only.
    OTP_DEBUG_RETURN_CODE: bool = False

    # ------------------------------------------------------------------- sms
    SMS_PROVIDER: Literal["eskiz", "playmobile", "console"] = "console"
    SMS_SENDER: str = "4546"
    ESKIZ_BASE_URL: str = "https://notify.eskiz.uz/api"
    ESKIZ_EMAIL: str = ""
    ESKIZ_PASSWORD: str = ""
    PLAYMOBILE_BASE_URL: str = "https://send.smsxabar.uz/broker-api"
    PLAYMOBILE_LOGIN: str = ""
    PLAYMOBILE_PASSWORD: str = ""

    # ------------------------------------------------------------------- ivr
    IVR_PROVIDER: Literal["twilio", "console"] = "console"
    IVR_ENABLED: bool = True
    IVR_DELAY_MINUTES: int = 18
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    IVR_WEBHOOK_BASE_URL: str = "http://localhost:8000"

    # ----------------------------------------------------------------- oauth
    GOOGLE_CLIENT_IDS: str = ""  # comma separated (android, ios, web)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_AUTH_MAX_AGE_SECONDS: int = 86400

    # ----------------------------------------------------------------- push
    PUSH_PROVIDER: Literal["fcm", "console"] = "console"
    FCM_PROJECT_ID: str = ""
    FCM_CREDENTIALS_JSON: str = ""

    # -------------------------------------------------------------- payments
    PLATFORM_FEE_PERCENT: int = 20
    CONSULTATION_SLA_HOURS: int = 24
    WALLET_MIN_PAYOUT_UZS: int = 50_000
    CURRENCY: str = "UZS"

    CLICK_MERCHANT_ID: str = ""
    CLICK_SERVICE_ID: str = ""
    CLICK_MERCHANT_USER_ID: str = ""
    CLICK_SECRET_KEY: str = ""
    CLICK_CHECKOUT_URL: str = "https://my.click.uz/services/pay"

    PAYME_MERCHANT_ID: str = ""
    PAYME_KEY: str = ""
    PAYME_TEST_KEY: str = ""
    PAYME_CHECKOUT_URL: str = "https://checkout.paycom.uz"

    # Doctor subscription (access to patient-management features)
    DOCTOR_SUBSCRIPTION_MONTHLY_UZS: int = 99_000
    DOCTOR_SUBSCRIPTION_YEARLY_UZS: int = 990_000
    DOCTOR_SUBSCRIPTION_TRIAL_DAYS: int = 14
    DOCTOR_SUBSCRIPTION_ENFORCED: bool = True

    # -------------------------------------------------------------------- ai
    AI_PROVIDER: Literal["anthropic", "console"] = "console"
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-opus-5"
    # Patient-facing answers are deliberately short, so the cap stays low.
    AI_MAX_OUTPUT_TOKENS: int = 1000
    # The model only rephrases retrieved protocol text; it does no open reasoning.
    AI_EFFORT: Literal["low", "medium", "high"] = "low"
    AI_RAG_TOP_K: int = 5
    AI_MIN_RELEVANCE: float = 0.12
    AI_DAILY_MESSAGE_LIMIT: int = 60

    # -------------------------------------------------------------- security
    CORS_ORIGINS: str = "*"
    RATE_LIMIT_ENABLED: bool = True
    TRUSTED_HOSTS: str = "*"

    @field_validator("SECRET_KEY")
    @classmethod
    def _no_default_secret(cls, v: str) -> str:
        if v.strip().lower() in {"changeme", "secret", "please-change-me"}:
            raise ValueError("SECRET_KEY must be a real random value")
        return v

    @property
    def sqlalchemy_dsn(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def google_client_ids(self) -> list[str]:
        return [c.strip() for c in self.GOOGLE_CLIENT_IDS.split(",") if c.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [h.strip() for h in self.TRUSTED_HOSTS.split(",") if h.strip()]

    @property
    def s3_public_endpoint(self) -> str:
        return self.S3_PUBLIC_ENDPOINT_URL or self.S3_ENDPOINT_URL

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
