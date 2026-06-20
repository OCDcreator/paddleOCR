from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Registered engine factories. Lazily populated so the module loads even if an
# engine's underlying library (paddleocr/rapidocr_onnxruntime) is not installed.
# Values are callables: factory(settings) -> OCREngine.
_ENGINES: dict[str, Callable[[Any], Any]] = {}


def register(name: str, factory: Callable[[Any], Any]) -> None:
    """Register an engine factory under ``name``."""
    _ENGINES[name] = factory


def available_engines() -> list[str]:
    """Return the names of all registered engines."""
    _ensure_builtin_engines_registered()
    return sorted(_ENGINES)


def create_engine(name: str, settings: Any) -> Any:
    """Construct the engine ``name`` with ``settings``.

    Raises ValueError for unknown engine names. The selected engine's library is
    imported lazily inside its factory, so an absent library surfaces as a clear
    error only when that engine is actually selected.
    """
    _ensure_builtin_engines_registered()
    if name not in _ENGINES:
        raise ValueError(f"unknown engine: {name!r} (available: {available_engines()})")
    return _ENGINES[name](settings)


def _paddleocr_factory(settings: Any) -> Any:
    from paddleocr_service.engines.paddleocr.engine import PaddleOCREngine

    return PaddleOCREngine(settings)


def _rapidocr_factory(settings: Any) -> Any:
    from paddleocr_service.engines.rapidocr.engine import RapidOCREngine

    return RapidOCREngine(settings)


_REGISTERED_BUILTINS = False


def _ensure_builtin_engines_registered() -> None:
    global _REGISTERED_BUILTINS
    if _REGISTERED_BUILTINS:
        return
    register("paddleocr", _paddleocr_factory)
    register("rapidocr", _rapidocr_factory)
    _REGISTERED_BUILTINS = True
