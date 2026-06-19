from typing import Any

from pydantic import BaseModel, Field


class OCRItem(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    box: list[list[float]]


class OCRResponse(BaseModel):
    text: str
    items: list[OCRItem]
    elapsed_ms: int = Field(ge=0)


class HealthResponse(BaseModel):
    status: str
    engine_ready: bool
    engine: str | None = None
    queue: dict[str, int | bool] | None = None
    version: str | None = None
    settings: dict[str, Any] | None = None
    storage: dict[str, str | int] | None = None
    model_cache_path: str | None = None
