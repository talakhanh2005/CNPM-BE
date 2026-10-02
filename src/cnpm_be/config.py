from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "cnpm_be"
    jwt_secret_key: SecretStr = SecretStr("local-development-only-change-this-key")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: str | None = None
    cloudinary_api_secret: SecretStr | None = None
    cloudinary_folder: str = "emotion-media"
    cloudinary_max_upload_bytes: int = 10 * 1024 * 1024
    cloudinary_allowed_formats: tuple[str, ...] = ("jpg", "jpeg", "png", "webp", "mp4", "mov")
    stun_urls: tuple[str, ...] = ("stun:stun.l.google.com:19302",)
    turn_urls: tuple[str, ...] = ()
    turn_username: str | None = None
    turn_credential: SecretStr | None = None
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    )
    admin_email: str | None = None
    admin_password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_admin_credentials(self) -> "Settings":
        if bool(self.admin_email) != bool(self.admin_password):
            raise ValueError("ADMIN_EMAIL and ADMIN_PASSWORD must be configured together")
        return self


settings = Settings()