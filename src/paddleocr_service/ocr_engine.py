from __future__ import annotations

# Transitional compatibility shim. The engine and parser have moved to
# paddleocr_service.engines.paddleocr. This file is removed in a later task.
from paddleocr_service.engines.paddleocr.engine import (  # noqa: F401
    PaddleOCREngine,
    UnsupportedSettingError,
)
from paddleocr_service.engines.paddleocr.parser import (  # noqa: F401
    parse_paddleocr_result,
)
