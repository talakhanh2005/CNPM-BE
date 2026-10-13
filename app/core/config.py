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
    # Merged from BE A: emails here always register as teacher (comma separated).
    teacher_email_whitelist: str = ""
    # Merged from BE A: seed one admin account at startup when both are set.
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    # Merged from BE A: generic media (recording-file, signed upload, v1 emotions).
    cloudinary_folder: str = "emotion-media"
    cloudinary_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    cloudinary_allowed_formats: list[str] = [
        "jpg",
        "jpeg",
        "png",
        "webp",
        "mp4",
        "mov",
        "webm",
        "mp3",
        "wav",
        "ogg",
        "m4a",
    ]
    cloudinary_upload_timeout: int = Field(default=30, ge=1)
    max_upload_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=90 * 1024 * 1024)
    max_recording_seconds: int = Field(default=7200, ge=1)
    upload_slots: int = Field(default=2, ge=1, le=16)
    upload_timeout_seconds: int = Field(default=120, ge=1)
    ai_mode: str = "http"
    ai_base_url: str = "http://localhost:9000"
    ai_api_key: str = ""
    ai_timeout_seconds: int = Field(default=120, ge=1)
    frame_timeout_seconds: int = Field(default=10, ge=1)
    max_ai_response_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    job_lease_seconds: int = Field(default=300, ge=10)
    worker_poll_seconds: float = Field(default=2, gt=0)
    max_frame_bytes: int = Field(default=512 * 1024, ge=128)
    frame_interval_seconds: float = Field(default=1 / 3, ge=0.2, le=0.5)
    emotion_log_interval_seconds: int = Field(default=90, ge=1)
    max_document_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    # Passed to RTCPeerConnection by the authenticated FE. TURN is infrastructure-owned.
    ice_servers: list[dict] = Field(default_factory=list)
    # Merged from BE A: used only when ICE_SERVERS is empty.
    stun_urls: list[str] = ["stun:stun.l.google.com:19302"]
    turn_urls: list[str] = []
    turn_username: str = ""
    turn_credential: SecretStr = SecretStr("")
    # Chatbot (contract v1 D5): Claude only parses questions; empty key = rules only.
    anthropic_api_key: SecretStr = SecretStr("")
    chat_llm_model: str = "claude-opus-5-5"
    chat_llm_timeout_seconds: float = Field(default=20, gt=0)
    frame_slots: int = Field(default=8, ge=1)
    max_http_json_bytes: int = Field(default=1024 * 1024, ge=1024)
    ws_max_message_bytes: int = Field(default=1024 * 1024, ge=1024)
    # One teacher plus students; mesh WebRTC, so keep it small.
    max_room_connections: int = Field(default=30, ge=2, le=100)
    max_documents_per_meeting: int = Field(default=100, ge=1)

    @property
    def teacher_email_whitelist_list(self) -> list[str]:
        return list(
            dict.fromkeys(
                item.strip().lower()
                for item in self.teacher_email_whitelist.split(",")
                if item.strip()
            )
        )

    @property
    def allowed_formats_list(self) -> list[str]:
        return list(dict.fromkeys(item.strip().lower() for item in self.cloudinary_allowed_formats))

    @property
    def effective_ice_servers(self) -> list[dict]:
        """ICE_SERVERS wins; otherwise build from STUN_URLS/TURN_* like BE A did."""
        if self.ice_servers:
            return self.ice_servers
        servers = [{"urls": list(self.stun_urls)}] if self.stun_urls else []
        credential = self.turn_credential.get_secret_value()
        if self.turn_urls and self.turn_username and credential:
            servers.append(
                {
                    "urls": list(self.turn_urls),
                    "username": self.turn_username,
                    "credential": credential,
                }
            )
        return servers

    @model_validator(mode="after")
    def validate_deployment(self):
        if bool(self.admin_email) != bool(self.admin_password.get_secret_value()):
            raise ValueError("ADMIN_EMAIL and ADMIN_PASSWORD must be configured together")
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
        for server in self.ice_servers:
            urls = server.get("urls", [])
            urls = [urls] if isinstance(urls, str) else urls
            if (
                not isinstance(urls, list)
                or not urls
                or any(
                    not isinstance(url, str)
                    or not url.startswith(("stun:", "stuns:", "turn:", "turns:"))
                    for url in urls
                )
            ):
                raise ValueError("ICE_SERVERS requires valid STUN/TURN urls")
            if any(url.startswith(("turn:", "turns:")) for url in urls) and not (
                server.get("username") and server.get("credential")
            ):
                raise ValueError("TURN requires username and credential")
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
