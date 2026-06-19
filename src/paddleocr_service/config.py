from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = Field(default="0.0.0.0", alias="PADDLEOCR_SERVICE_HOST")
    port: int = Field(default=8866, alias="PADDLEOCR_SERVICE_PORT")
    language: str = Field(default="ch", alias="PADDLEOCR_LANGUAGE")
    use_angle_cls: bool = Field(default=True, alias="PADDLEOCR_USE_ANGLE_CLS")
    warmup_on_startup: bool = Field(default=False, alias="PADDLEOCR_WARMUP_ON_STARTUP")
    database_path: Path = Field(
        default=Path("data/paddleocr.sqlite3"),
        alias="PADDLEOCR_DATABASE_PATH",
    )
    output_dir: Path = Field(default=Path("outputs"), alias="PADDLEOCR_OUTPUT_DIR")
    upload_dir: Path = Field(default=Path("uploads"), alias="PADDLEOCR_UPLOAD_DIR")
    save_uploads: bool = Field(default=False, alias="PADDLEOCR_SAVE_UPLOADS")
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        alias="PADDLEOCR_MAX_UPLOAD_BYTES",
    )
    pdf_render_scale: float = Field(default=2.0, alias="PADDLEOCR_PDF_RENDER_SCALE")
    retention_days: int = Field(default=0, alias="PADDLEOCR_RETENTION_DAYS")
    cors_origins: list[str] = Field(default_factory=list, alias="PADDLEOCR_CORS_ORIGINS")
    access_log_path: Path = Field(
        default=Path("logs/access.log"),
        alias="PADDLEOCR_ACCESS_LOG_PATH",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        enable_decoding=False,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
