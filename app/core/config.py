from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    """Validated environment configuration shared by API and durable worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    mongo_uri: str = ""
    database_url: str | None = None
    sqlserver_server: str = r"localhost\SQLEXPRESS"
    sqlserver_database: str = "face_emotion"
    sqlserver_driver: str = "ODBC Driver 18 for SQL Server"
    sqlserver_trusted_connection: bool = True
    sqlserver_username: str = ""
    sqlserver_password: SecretStr = SecretStr("")
    sqlserver_encrypt: bool = True
    sqlserver_trust_server_certificate: bool = False

    @property
    def sqlalchemy_url(self) -> URL:
        """Build an ODBC URL without concatenating user/password into URI syntax."""
        if self.database_url:
            return make_url(self.database_url)

        def quote(value: str) -> str:
            # ODBC braced values escape closing braces; semicolons remain literal.
            return "{" + value.replace("}", "}}") + "}"

        parts = [
            "DRIVER=" + quote(self.sqlserver_driver),
            "SERVER=" + quote(self.sqlserver_server),
            "DATABASE=" + quote(self.sqlserver_database),
            "LongAsMax=yes",
            "Encrypt=" + ("yes" if self.sqlserver_encrypt else "no"),
            "TrustServerCertificate="
            + ("yes" if self.sqlserver_trust_server_certificate else "no"),
        ]
        if self.sqlserver_trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            parts.extend(
                [
                    "UID=" + quote(self.sqlserver_username),
                    "PWD=" + quote(self.sqlserver_password.get_secret_value()),
                ]
            )
        return URL.create("mssql+pyodbc", query={"odbc_connect": ";".join(parts)})

    jwt_secret: str = Field(min_length=32)
    jwt_issuer: str = "face-emotion"
    jwt_audience: str = "classroom"
    access_minutes: int = Field(default=15, ge=1)
    refresh_days: int = Field(default=7, ge=1)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    allow_teacher_registration: bool = False
    teacher_registration_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    max_upload_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=90 * 1024 * 1024)
    max_recording_seconds: int = Field(default=7200, ge=1)
    upload_slots: int = Field(default=2, ge=1, le=16)
    upload_timeout_seconds: int = Field(default=120, ge=1)
    ai_mode: str = "mock"
    ai_base_url: str = "http://localhost:9000"
    ai_api_key: str = ""
    ai_timeout_seconds: int = Field(default=120, ge=1)
    frame_timeout_seconds: int = Field(default=10, ge=1)
    max_ai_response_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    job_lease_seconds: int = Field(default=300, ge=10)
    worker_poll_seconds: float = Field(default=2, gt=0)
    max_frame_bytes: int = Field(default=512 * 1024, ge=128)
    frame_interval_seconds: float = Field(default=1, gt=0)
    frame_slots: int = Field(default=8, ge=1)
    max_http_json_bytes: int = Field(default=1024 * 1024, ge=1024)
    ws_max_message_bytes: int = Field(default=64 * 1024, ge=1024)
    max_room_connections: int = Field(default=100, ge=2)

    @model_validator(mode="after")
    def validate_deployment(self):
        if self.database_url and make_url(self.database_url).drivername not in {
            "sqlite",
            "mssql+pyodbc",
        }:
            raise ValueError("Only mssql+pyodbc and isolated SQLite tests are supported")
        if not self.sqlserver_trusted_connection and (
            not self.sqlserver_username or not self.sqlserver_password.get_secret_value()
        ):
            raise ValueError("SQL authentication requires username and password")
        if self.ai_mode not in {"mock", "http"}:
            raise ValueError("AI_MODE must be mock or http")
        if self.job_lease_seconds <= self.ai_timeout_seconds + 30:
            raise ValueError("JOB_LEASE_SECONDS must exceed AI_TIMEOUT_SECONDS + 30")
        if self.environment == "production":
            if self.bcrypt_rounds < 12 or self.ai_mode == "mock":
                raise ValueError("Production requires bcrypt rounds >=12 and AI_MODE=http")
            if not self.ai_base_url.startswith("https://"):
                raise ValueError("Production AI_BASE_URL must use HTTPS")
            if self.allow_teacher_registration:
                raise ValueError("Public teacher registration must be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
