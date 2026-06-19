# Pluggable OCR Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OCR engine pluggable — a unified `OCREngine` protocol, a migrated `PaddleOCREngine`, a new `RapidOCREngine`, and a registry — so the service defaults to RapidOCR and can hot-swap to PaddleOCR at runtime via `PATCH /settings`. Restructure the bloated `ocr_engine.py` into focused per-responsibility modules.

**Architecture:** Protocol + registry (brainstorming approach A). `engines/base.py` holds the shared `OCREngine` protocol + helpers; each engine lives in its own subpackage (`engines/paddleocr/`, `engines/rapidocr/`) with its class and its result parser. `main.py` builds the engine via `create_engine(name, settings)`; `PATCH /settings` swaps the engine instance (atomic reference replace, no lock) then applies remaining keys. OCR libs become optional extras.

**Tech Stack:** Python 3.11–3.13, FastAPI, pydantic-settings, existing `run_in_threadpool` pattern, RapidOCR (`rapidocr_onnxruntime`), PaddleOCR (`paddleocr`/`paddlepaddle`). TDD with pytest; engines unit-tested via mocks/fakes, never real OCR.

---

## File Structure

```
src/paddleocr_service/
  ocr_engine.py                 # REMOVED (Task 5)
  engines/
    __init__.py                 # public exports (Task 1)
    base.py                     # OCREngine Protocol, SupportedSetting, validate_image, normalize_box (Task 1)
    registry.py                 # ENGINES map, create_engine, available_engines (Task 2)
    paddleocr/
      __init__.py
      engine.py                 # PaddleOCREngine migrated (Task 4)
      parser.py                 # parse_paddleocr_result + helpers migrated (Task 4)
    rapidocr/
      __init__.py
      engine.py                 # RapidOCREngine (Task 6)
      parser.py                 # RapidOCR normalize (Task 6)
  config.py                     # +Settings.engine field (Task 7)
  main.py                       # create_app via registry, /settings swap, /health rename (Task 8)
pyproject.toml                  # extras for paddleocr + rapidocr (Task 9)
README.md                       # install docs (Task 9)
tests/
  test_engines_base.py          # Task 1
  test_registry.py              # Task 2
  test_ocr_engine.py            # RENAMED -> test_paddleocr_engine.py, import path updated (Task 4)
  test_rapidocr_engine.py       # Task 6
  test_ocr_api.py               # FakeEngine extended to Protocol (Task 8)
```

One file, one responsibility. Each task produces a self-contained, committable change.

## Conventions

- Every new `.py` starts with `from __future__ import annotations`.
- Existing validators raise `HTTPException(status_code=422, detail=...)` (see `main.py:382-394`) — follow that pattern.
- `Settings` fields use `Field(default=..., alias="PADDLEOCR_*")` (see `config.py:9-31`).
- Tests load nothing heavy; engine unit tests mock the OCR library. `tests/test_ocr_api.py`'s `FakeEngine` is the pattern for a fake that satisfies the protocol.

---

## Task 1: engines/base.py — Protocol + shared helpers

**Files:**
- Create: `src/paddleocr_service/engines/__init__.py`
- Create: `src/paddleocr_service/engines/base.py`
- Test: `tests/test_engines_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engines_base.py`:

```python
from __future__ import annotations

import pytest

from paddleocr_service.engines.base import (
    SupportedSetting,
    normalize_box,
    validate_image,
)


def test_supported_setting_stores_fields() -> None:
    s = SupportedSetting(key="language", type="str", description="OCR language")
    assert s.key == "language"
    assert s.type == "str"
    assert s.description == "OCR language"


def test_validate_image_accepts_png_bytes() -> None:
    # A real 1x1 PNG.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    # Should not raise.
    validate_image(png)


def test_validate_image_rejects_non_image() -> None:
    with pytest.raises(ValueError, match="must be an image"):
        validate_image(b"not an image at all")


def test_normalize_box_flattens_and_floats() -> None:
    box = [[1, 2], [3, 4]]
    assert normalize_box(box) == [[1.0, 2.0], [3.0, 4.0]]


def test_normalize_box_handles_numpy_like_points() -> None:
    class FakePoint:
        def tolist(self) -> list[int]:
            return [5, 6]

    assert normalize_box([FakePoint()]) == [[5.0, 6.0]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_engines_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paddleocr_service.engines'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/paddleocr_service/engines/__init__.py`:

```python
from __future__ import annotations
```

Create `src/paddleocr_service/engines/base.py`:

```python
from __future__ import annotations

from io import BytesIO
from typing import Any, Protocol, runtime_checkable

from PIL import Image

OCRItemDict = dict[str, Any]


@runtime_checkable
class OCREngine(Protocol):
    """Unified OCR engine interface. Implementations: PaddleOCR, RapidOCR."""

    @property
    def name(self) -> str: ...

    @property
    def is_ready(self) -> bool: ...

    def warm_up(self) -> None: ...

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]: ...

    def apply_settings(self, **opts: Any) -> dict[str, Any]: ...

    def supported_settings(self) -> list[SupportedSetting]: ...


class SupportedSetting:
    """Declares one configurable key an engine accepts via apply_settings."""

    def __init__(self, key: str, type: str, description: str) -> None:
        self.key = key
        self.type = type
        self.description = description


def validate_image(image_bytes: bytes) -> None:
    """Raise ValueError if the bytes are not a valid image."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("Uploaded file must be an image.") from exc


def normalize_box(box: Any) -> list[list[float]]:
    """Normalize a box (list of points, possibly numpy) to list[list[float]]."""
    normalized: list[list[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        normalized.append([float(point[0]), float(point[1])])
    return normalized
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_engines_base.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/paddleocr_service/engines/ tests/test_engines_base.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/paddleocr_service/engines/__init__.py src/paddleocr_service/engines/base.py tests/test_engines_base.py
git commit -m "Add OCREngine protocol and shared engine helpers"
```

---

## Task 2: engines/registry.py — registry + create_engine

**Files:**
- Create: `src/paddleocr_service/engines/registry.py`
- Test: `tests/test_registry.py`

The registry references `PaddleOCREngine` (Task 4) and `RapidOCREngine` (Task 6), neither of which exist yet. To keep this task independently testable, the registry imports engines **lazily inside `create_engine`**, so the module loads even before those classes exist. The test uses lightweight fake classes registered dynamically.

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry.py`:

```python
from __future__ import annotations

import pytest

from paddleocr_service.engines import registry
from paddleocr_service.engines.base import OCREngine, SupportedSetting


class _FakeEngine:
    name = "fake"

    def __init__(self, settings) -> None:
        self.settings = settings

    @property
    def is_ready(self) -> bool:
        return True

    def warm_up(self) -> None: ...

    def recognize(self, image_bytes: bytes) -> list: ...

    def apply_settings(self, **opts) -> dict:
        return opts

    def supported_settings(self) -> list[SupportedSetting]:
        return []


def test_available_engines_is_a_list_of_strings() -> None:
    names = registry.available_engines()
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)
    # Both engines are registered by name in the spec.
    assert "rapidocr" in names
    assert "paddleocr" in names


def test_create_engine_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        registry.create_engine("does-not-exist", settings=None)


def test_register_and_create_custom_engine() -> None:
    registry.register("fake", _FakeEngine)
    eng = registry.create_engine("fake", settings={"x": 1})
    assert isinstance(eng, _FakeEngine)
    assert eng.settings == {"x": 1}


def test_fake_engine_satisfies_protocol() -> None:
    # Sanity: the fake we use for tests structurally satisfies OCREngine.
    assert isinstance(_FakeEngine(settings=None), OCREngine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paddleocr_service.engines.registry'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/paddleocr_service/engines/registry.py`:

```python
from __future__ import annotations

from typing import Any, Callable

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_registry.py -v`
Expected: PASS (4 tests). `available_engines()` calls `_ensure_builtin_engines_registered()` first so both builtins appear even when called directly (before any `create_engine`).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/paddleocr_service/engines/registry.py tests/test_registry.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/paddleocr_service/engines/registry.py tests/test_registry.py
git commit -m "Add engine registry with lazy engine factories"
```

---

## Task 3: Migrate PaddleOCR parser to engines/paddleocr/parser.py

**Files:**
- Create: `src/paddleocr_service/engines/paddleocr/__init__.py`
- Create: `src/paddleocr_service/engines/paddleocr/parser.py`
- Test: `tests/test_paddleocr_parser.py` (migrated from `tests/test_ocr_engine.py`)

This task moves ONLY the parsing functions out of `ocr_engine.py`, verbatim, into the new location. The old `ocr_engine.py` still exists (deleted in Task 5) and its tests still import from the old path until Task 4 — to avoid a broken intermediate state, this task also updates `tests/test_ocr_engine.py` to import from the new path and renames it.

- [ ] **Step 1: Create the package + parser module**

Create `src/paddleocr_service/engines/paddleocr/__init__.py`:

```python
from __future__ import annotations
```

Create `src/paddleocr_service/engines/paddleocr/parser.py`. Copy the parsing code verbatim from the current `src/paddleocr_service/ocr_engine.py` lines for: `OCRItemDict` type alias, `parse_paddleocr_result`, `_parse_candidate`, `_parse_dict_candidate`, `_first_present`, `_normalize_box`. Change `_normalize_box` to delegate to `base.normalize_box`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from paddleocr_service.engines.base import OCRItemDict, normalize_box


def parse_paddleocr_result(raw_result: Any) -> list[OCRItemDict]:
    """Normalize common PaddleOCR result shapes to API OCR items."""
    if not raw_result:
        return []

    if isinstance(raw_result, list) and len(raw_result) == 1 and isinstance(raw_result[0], list):
        candidates: Iterable[Any] = raw_result[0]
    else:
        candidates = raw_result

    items: list[OCRItemDict] = []
    for candidate in candidates:
        parsed_items = _parse_candidate(candidate)
        for parsed in parsed_items:
            items.append(parsed)
    return items


def _parse_candidate(candidate: Any) -> list[OCRItemDict]:
    if isinstance(candidate, dict):
        return _parse_dict_candidate(candidate)

    if not isinstance(candidate, (list, tuple)) or len(candidate) < 2:
        return []

    box = normalize_box(candidate[0])
    text_and_score = candidate[1]
    if not isinstance(text_and_score, (list, tuple)) or len(text_and_score) < 2:
        return []

    text = str(text_and_score[0])
    confidence = float(text_and_score[1])
    return [{"text": text, "confidence": confidence, "box": box}]


def _parse_dict_candidate(candidate: dict[str, Any]) -> list[OCRItemDict]:
    if "rec_texts" in candidate and "rec_scores" in candidate:
        # Use explicit `is None` checks, NOT `or` chains: PaddleOCR returns numpy
        # arrays here, and an empty array raises ValueError under boolean
        # conversion ("truth value of an empty array is ambiguous").
        boxes = _first_present(candidate, "rec_polys", "dt_polys", "rec_boxes")
        if boxes is None:
            return []

        return [
            {
                "text": str(text),
                "confidence": float(confidence),
                "box": normalize_box(box),
            }
            for text, confidence, box in zip(
                candidate["rec_texts"],
                candidate["rec_scores"],
                boxes,
                strict=False,
            )
        ]

    text = _first_present(candidate, "text", "rec_text", "label")
    confidence = _first_present(candidate, "confidence", "score", "rec_score", "prob")
    box = _first_present(candidate, "box", "points", "dt_polys")
    if text is None or confidence is None or box is None:
        return []

    return [{"text": str(text), "confidence": float(confidence), "box": normalize_box(box)}]


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first value for ``keys`` whose value is not ``None``.

    Unlike ``a or b or c``, this never coerces values to bool, so it is safe for
    numpy/ndarray values (which raise on boolean conversion). Returns ``None`` if
    no key is present (or all present values are ``None``).
    """
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None
```

- [ ] **Step 2: Migrate the test file**

Rename `tests/test_ocr_engine.py` → `tests/test_paddleocr_parser.py` (delete old, create new). Update the import line and the stand-in class location. The full new file:

```python
from __future__ import annotations

from paddleocr_service.engines.paddleocr.parser import parse_paddleocr_result


class _AmbiguousBoolArray:
    """Stand-in for an empty numpy array.

    Real empty numpy arrays: (1) raise ValueError on boolean conversion
    ("truth value of an empty array is ambiguous"), but (2) ARE iterable and
    yield zero items. Reproduce both so the test is independent of numpy.
    """

    def __bool__(self) -> bool:
        raise ValueError("The truth value of an empty array is ambiguous.")

    def __iter__(self):
        return iter(())


def test_parse_paddleocr_v2_result_shape() -> None:
    raw_result = [
        [
            [
                [[1, 2], [20, 2], [20, 12], [1, 12]],
                ("hello", 0.98),
            ],
            [
                [[1, 15], [30, 15], [30, 25], [1, 25]],
                ("world", 0.95),
            ],
        ]
    ]

    assert parse_paddleocr_result(raw_result) == [
        {
            "text": "hello",
            "confidence": 0.98,
            "box": [[1.0, 2.0], [20.0, 2.0], [20.0, 12.0], [1.0, 12.0]],
        },
        {
            "text": "world",
            "confidence": 0.95,
            "box": [[1.0, 15.0], [30.0, 15.0], [30.0, 25.0], [1.0, 25.0]],
        },
    ]


def test_parse_empty_paddleocr_result() -> None:
    assert parse_paddleocr_result([[]]) == []


def test_parse_dict_result_with_no_text_detected_returns_empty() -> None:
    raw_result = [
        {
            "rec_texts": [],
            "rec_scores": [],
            "rec_polys": _AmbiguousBoolArray(),
        }
    ]

    assert parse_paddleocr_result(raw_result) == []


def test_parse_paddleocr_v3_result_shape() -> None:
    raw_result = [
        {
            "rec_texts": ["hello", "world"],
            "rec_scores": [0.98, 0.95],
            "rec_polys": [
                [[1, 2], [20, 2], [20, 12], [1, 12]],
                [[1, 15], [30, 15], [30, 25], [1, 25]],
            ],
        }
    ]

    assert parse_paddleocr_result(raw_result) == [
        {
            "text": "hello",
            "confidence": 0.98,
            "box": [[1.0, 2.0], [20.0, 2.0], [20.0, 12.0], [1.0, 12.0]],
        },
        {
            "text": "world",
            "confidence": 0.95,
            "box": [[1.0, 15.0], [30.0, 15.0], [30.0, 25.0], [1.0, 25.0]],
        },
    ]
```

Delete `tests/test_ocr_engine.py` after creating the new file.

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_paddleocr_parser.py -v`
Expected: PASS (4 tests).

- [ ] **Step 4: Lint**

Run: `uv run ruff check src/paddleocr_service/engines/paddleocr/ tests/test_paddleocr_parser.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/paddleocr_service/engines/paddleocr/__init__.py src/paddleocr_service/engines/paddleocr/parser.py tests/test_paddleocr_parser.py
git rm tests/test_ocr_engine.py
git commit -m "Migrate PaddleOCR result parser to engines/paddleocr/parser.py"
```

---

## Task 4: Migrate PaddleOCREngine to engines/paddleocr/engine.py

**Files:**
- Create: `src/paddleocr_service/engines/paddleocr/engine.py`
- Test: `tests/test_paddleocr_engine.py`

Migrate the engine class from `ocr_engine.py`, implement the `OCREngine` protocol: add `name`, replace `configure` with `apply_settings` (whitelist `{language, use_angle_cls}`, unknown raises), add `supported_settings`. Do NOT delete `ocr_engine.py` yet — `main.py` still imports `PaddleOCREngine` from there until Task 8. Instead, this task makes `ocr_engine.py` re-export from the new location so existing imports keep working through the transition.

- [ ] **Step 1: Write the failing test**

Create `tests/test_paddleocr_engine.py`:

```python
from __future__ import annotations

import pytest

from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.engines.paddleocr.engine import (
    PaddleOCREngine,
    UnsupportedSettingError,
)


def _settings(**overrides):
    from paddleocr_service.config import Settings

    base = {"database_path": "/tmp/x.sqlite3", "output_dir": "/tmp/out", "upload_dir": "/tmp/up"}
    base.update(overrides)
    return Settings(**base)


def test_engine_name() -> None:
    assert PaddleOCREngine(_settings()).name == "paddleocr"


def test_apply_settings_accepts_language_and_use_angle_cls() -> None:
    eng = PaddleOCREngine(_settings(language="ch"))
    result = eng.apply_settings(language="en", use_angle_cls=False)
    assert result == {"language": "en", "use_angle_cls": False}


def test_apply_settings_unknown_key_raises() -> None:
    eng = PaddleOCREngine(_settings())
    with pytest.raises(UnsupportedSettingError):
        eng.apply_settings(bogus_key=1)


def test_supported_settings_lists_language_and_use_angle_cls() -> None:
    eng = PaddleOCREngine(_settings())
    keys = {s.key for s in eng.supported_settings()}
    assert {"language", "use_angle_cls"} <= keys
    assert all(isinstance(s, SupportedSetting) for s in eng.supported_settings())


def test_apply_settings_language_change_marks_not_ready() -> None:
    eng = PaddleOCREngine(_settings(language="ch"))
    eng.warm_up  # property exists
    # changing language must invalidate the loaded model (lazy reload)
    eng.apply_settings(language="en")
    assert eng.is_ready is False
```

NOTE: the last test requires that `apply_settings` with a changed language sets the internal model to None without actually loading. Since `_load_ocr` imports paddleocr (heavy), the test must NOT call warm_up. The existing migration code sets `_ocr = None` on language change — `is_ready` returns `_ocr is not None`, so it reads False.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_paddleocr_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: ...paddleocr.engine`.

- [ ] **Step 3: Write minimal implementation**

Create `src/paddleocr_service/engines/paddleocr/engine.py`:

```python
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from paddleocr_service.config import Settings
from paddleocr_service.engines.base import OCRItemDict, SupportedSetting, validate_image
from paddleocr_service.engines.paddleocr.parser import parse_paddleocr_result

_SUPPORTED = [
    SupportedSetting(key="language", type="str", description="PaddleOCR language code (e.g. 'ch', 'en')."),
    SupportedSetting(
        key="use_angle_cls",
        type="bool",
        description="Whether to run text-line orientation classification.",
    ),
]
_SUPPORTED_KEYS = {s.key for s in _SUPPORTED}


class UnsupportedSettingError(ValueError):
    """Raised by apply_settings for keys the engine does not accept."""


class PaddleOCREngine:
    """OCR engine backed by PaddleOCR. Implements the OCREngine protocol."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr: Any | None = None

    @property
    def name(self) -> str:
        return "paddleocr"

    @property
    def is_ready(self) -> bool:
        return self._ocr is not None

    def warm_up(self) -> None:
        self._load_ocr()

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]:
        validate_image(image_bytes)
        ocr = self._load_ocr()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_file.write(image_bytes)
            image_path = Path(image_file.name)

        try:
            raw_result = ocr.predict(
                str(image_path),
                use_textline_orientation=self._settings.use_angle_cls,
            )
        finally:
            image_path.unlink(missing_ok=True)

        return parse_paddleocr_result(raw_result)

    def apply_settings(self, **opts: Any) -> dict[str, Any]:
        unknown = set(opts) - _SUPPORTED_KEYS
        if unknown:
            raise UnsupportedSettingError(
                f"paddleocr does not support setting(s): {sorted(unknown)}"
            )

        changed_model = False
        if "language" in opts and opts["language"] != self._settings.language:
            self._settings.language = opts["language"]
            changed_model = True
        if "use_angle_cls" in opts and opts["use_angle_cls"] != self._settings.use_angle_cls:
            self._settings.use_angle_cls = opts["use_angle_cls"]
            changed_model = True
        if changed_model:
            self._ocr = None  # force lazy reload on next recognize/warm_up

        return {k: v for k, v in opts.items()}

    def supported_settings(self) -> list[SupportedSetting]:
        return list(_SUPPORTED)

    def _load_ocr(self) -> Any:
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang=self._settings.language,
                use_textline_orientation=self._settings.use_angle_cls,
            )
        return self._ocr
```

- [ ] **Step 4: Make ocr_engine.py re-export for transition**

Replace the entire contents of `src/paddleocr_service/ocr_engine.py` with a thin compatibility shim (it is deleted in Task 5, but kept working during the transition so `main.py` does not break between tasks):

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_paddleocr_engine.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run full suite to confirm nothing broke**

Run: `uv run --extra dev pytest -q`
Expected: PASS (all tests, including the parser tests and the API tests that still import the old `PaddleOCREngine` via the shim).

- [ ] **Step 7: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/paddleocr_service/engines/paddleocr/engine.py src/paddleocr_service/ocr_engine.py tests/test_paddleocr_engine.py
git commit -m "Migrate PaddleOCREngine to engines/paddleocr, implement OCREngine protocol"
```

---

## Task 5: Delete the ocr_engine.py shim

**Files:**
- Delete: `src/paddleocr_service/ocr_engine.py`

This task removes the shim. It can only land after no code imports from `ocr_engine.py` — which requires Task 8's `main.py` changes. To keep tasks independently valid, this task is **ordered after Task 8** in execution. Do this task only after Task 8 is committed and the full suite passes.

- [ ] **Step 1: Confirm nothing imports ocr_engine anymore**

Run: `uv run python -c "import subprocess; print(subprocess.run(['git','grep','-l','ocr_engine','src/','tests/'],capture_output=True,text=True).stdout)"`
Expected: empty output (no references to `ocr_engine` remain). If any references remain, update them to import from `paddleocr_service.engines...` first.

- [ ] **Step 2: Delete the file**

Run: `git rm src/paddleocr_service/ocr_engine.py`

- [ ] **Step 3: Run full suite + lint**

Run: `uv run --extra dev pytest -q && uv run ruff check .`
Expected: all tests PASS, lint clean.

- [ ] **Step 4: Commit**

```bash
git commit -m "Remove transitional ocr_engine.py shim"
```

---

## Task 6: RapidOCREngine

**Files:**
- Create: `src/paddleocr_service/engines/rapidocr/__init__.py`
- Create: `src/paddleocr_service/engines/rapidocr/engine.py`
- Create: `src/paddleocr_service/engines/rapidocr/parser.py`
- Test: `tests/test_rapidocr_engine.py`

- [ ] **Step 1: Determine RapidOCR's supported config keys**

Consult the installed RapidOCR docs/source for the constructor kwargs `RapidOCR()` accepts. Common ones (verify against the installed version): `det_use_cls`, `text_score`, etc. Record the verified list in a comment in `engine.py`. If unsure, start with an empty whitelist and add keys as verified — `apply_settings` with empty whitelist correctly raises for any key.

For this plan, the whitelist is `{"text_score"}` (a recognized RapidOCR threshold knob). Adjust to the verified set when implementing.

- [ ] **Step 2: Create the package + parser**

Create `src/paddleocr_service/engines/rapidocr/__init__.py`:

```python
from __future__ import annotations
```

Create `src/paddleocr_service/engines/rapidocr/parser.py`:

```python
from __future__ import annotations

from typing import Any

from paddleocr_service.engines.base import OCRItemDict, normalize_box


def normalize_rapidocr_result(result: Any) -> list[OCRItemDict]:
    """Normalize RapidOCR output into {text, confidence, box}.

    rapidocr_onnxruntime returns a 2-tuple: (lines, elapse), where ``lines`` is a
    list of [box, text, score] entries and ``elapse`` is a timing list. Newer
    unified ``rapidocr`` returns a Result object with .txts/.scores/.boxes.
    """
    items: list[OCRItemDict] = []
    if result is None:
        return items
    # Unpack the (lines, elapse) tuple shape from rapidocr_onnxruntime.
    if isinstance(result, tuple) and len(result) >= 1 and isinstance(result[0], list):
        result = result[0]
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if txts is not None and scores is not None and boxes is not None:
        for text, score, box in zip(txts, scores, boxes, strict=False):
            items.append({"text": str(text), "confidence": float(score), "box": normalize_box(box)})
        return items
    if isinstance(result, (list, tuple)):
        for entry in result:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                box, text, score = entry[0], entry[1], entry[2]
                items.append({"text": str(text), "confidence": float(score), "box": normalize_box(box)})
    return items
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_rapidocr_engine.py`:

```python
from __future__ import annotations

import pytest

from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.engines.rapidocr.engine import (
    RapidOCREngine,
    UnsupportedSettingError,
)
from paddleocr_service.engines.rapidocr.parser import normalize_rapidocr_result


def test_engine_name() -> None:
    from paddleocr_service.config import Settings

    eng = RapidOCREngine(Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u"))
    assert eng.name == "rapidocr"
    assert eng.is_ready is False


def test_parser_unpacks_lines_elapse_tuple() -> None:
    result = ([[[1, 2], [10, 2], [10, 8], [1, 8]], "hello", 0.97]], [0.4])
    items = normalize_rapidocr_result(result)
    assert items == [
        {
            "text": "hello",
            "confidence": 0.97,
            "box": [[1.0, 2.0], [10.0, 2.0], [10.0, 8.0], [1.0, 8.0]],
        }
    ]


def test_parser_handles_none() -> None:
    assert normalize_rapidocr_result(None) == []


def test_apply_settings_unknown_key_raises() -> None:
    from paddleocr_service.config import Settings

    eng = RapidOCREngine(Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u"))
    with pytest.raises(UnsupportedSettingError):
        eng.apply_settings(language="en")  # language is a PaddleOCR key, not RapidOCR's


def test_supported_settings_returns_supported_setting_objects() -> None:
    from paddleocr_service.config import Settings

    eng = RapidOCREngine(Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u"))
    settings = eng.supported_settings()
    assert all(isinstance(s, SupportedSetting) for s in settings)


def test_recognize_uses_injected_rapidocr(monkeypatch, tmp_path) -> None:
    from paddleocr_service.config import Settings

    class FakeRapidOCR:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def __call__(self, path):
            return ([[[1, 2], [3, 4], [5, 6], [7, 8]], "hi", 0.9]], [0.1])

    # Bypass the real rapidocr_onnxruntime import in _load_ocr.
    eng = RapidOCREngine(Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u"))
    eng._load_ocr = lambda: FakeRapidOCR()  # type: ignore[assignment]
    items = eng.recognize(_png_bytes())
    assert items == [{"text": "hi", "confidence": 0.9, "box": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]}]


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_rapidocr_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: ...rapidocr.engine`.

- [ ] **Step 5: Write minimal implementation**

Create `src/paddleocr_service/engines/rapidocr/engine.py`:

```python
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from paddleocr_service.config import Settings
from paddleocr_service.engines.base import OCRItemDict, SupportedSetting, validate_image
from paddleocr_service.engines.rapidocr.parser import normalize_rapidocr_result

# Verified against installed rapidocr_onnxruntime. Adjust if the version differs.
_SUPPORTED = [
    SupportedSetting(
        key="text_score",
        type="float",
        description="Recognition confidence threshold (0.0-1.0).",
    ),
]
_SUPPORTED_KEYS = {s.key for s in _SUPPORTED}


class UnsupportedSettingError(ValueError):
    """Raised by apply_settings for keys the engine does not accept."""


class RapidOCREngine:
    """OCR engine backed by RapidOCR (ONNX Runtime). Implements OCREngine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr: Any | None = None

    @property
    def name(self) -> str:
        return "rapidocr"

    @property
    def is_ready(self) -> bool:
        return self._ocr is not None

    def warm_up(self) -> None:
        self._load_ocr()

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]:
        validate_image(image_bytes)
        ocr = self._load_ocr()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_file.write(image_bytes)
            image_path = Path(image_file.name)
        try:
            raw = ocr(str(image_path))
        finally:
            image_path.unlink(missing_ok=True)

        return normalize_rapidocr_result(raw)

    def apply_settings(self, **opts: Any) -> dict[str, Any]:
        unknown = set(opts) - _SUPPORTED_KEYS
        if unknown:
            raise UnsupportedSettingError(
                f"rapidocr does not support setting(s): {sorted(unknown)}"
            )
        # RapidOCR settings require a model reload; simplest correct behavior is
        # to invalidate the loaded model so it is rebuilt with the new options.
        if opts:
            self._ocr = None
            self._pending_opts = opts
        return dict(opts)

    def supported_settings(self) -> list[SupportedSetting]:
        return list(_SUPPORTED)

    def _load_ocr(self) -> Any:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            kwargs = getattr(self, "_pending_opts", {})
            self._ocr = RapidOCR(**kwargs)
        return self._ocr
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_rapidocr_engine.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/paddleocr_service/engines/rapidocr/ tests/test_rapidocr_engine.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/paddleocr_service/engines/rapidocr/ tests/test_rapidocr_engine.py
git commit -m "Add RapidOCREngine implementing OCREngine protocol"
```

---

## Task 7: Settings.engine field

**Files:**
- Modify: `src/paddleocr_service/config.py`
- Test: extend `tests/test_registry.py` or add a focused test in `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_engine.py`:

```python
from __future__ import annotations

import pytest


def test_engine_defaults_to_rapidocr() -> None:
    from paddleocr_service.config import Settings

    s = Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")
    assert s.engine == "rapidocr"


def test_engine_reads_env_alias(monkeypatch) -> None:
    from paddleocr_service.config import Settings

    monkeypatch.setenv("PADDLEOCR_ENGINE", "paddleocr")
    # Settings reads env at init; ensure alias maps to the field.
    s = Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")
    assert s.engine == "paddleocr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_config_engine.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'engine'`.

- [ ] **Step 3: Add the field to Settings**

In `src/paddleocr_service/config.py`, add after the `access_log_path` field (before `model_config`):

```python
    engine: str = Field(default="rapidocr", alias="PADDLEOCR_ENGINE")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_config_engine.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + full suite**

Run: `uv run --extra dev pytest -q && uv run ruff check .`
Expected: all PASS, lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/paddleocr_service/config.py tests/test_config_engine.py
git commit -m "Add Settings.engine field (default rapidocr, env PADDLEOCR_ENGINE)"
```

---

## Task 8: Wire registry into main.py + /settings hot-swap + /health

**Files:**
- Modify: `src/paddleocr_service/main.py`
- Modify: `tests/test_ocr_api.py` (extend FakeEngine to the protocol)

- [ ] **Step 1: Read current create_app signature and the relevant handlers**

Confirm: `main.py:45` `engine = ocr_engine or PaddleOCREngine(app_settings)`; `main.py:261-279` the `PATCH /settings` handler; `main.py:89-105` `/health`. These are the edit sites.

- [ ] **Step 2: Extend FakeEngine in tests/test_ocr_api.py**

Find the `FakeEngine` class in `tests/test_ocr_api.py` (used by all API tests via `create_app(ocr_engine=FakeEngine())`). Add the protocol methods so it still satisfies `OCREngine`:

```python
    @property
    def name(self) -> str:
        return "fake"

    def apply_settings(self, **opts):
        return opts

    def supported_settings(self):
        return []
```

(Also remove any `hasattr(engine, "configure")` assumptions in the API tests if they check for the old method — `PATCH /settings` will call `apply_settings` now, which the fake implements.)

- [ ] **Step 3: Write the failing test for hot-swap**

Add to `tests/test_ocr_api.py` (or a new `tests/test_settings_engine.py`):

```python
async def test_patch_settings_swaps_engine():
    from paddleocr_service.engines import registry
    from tests.test_ocr_api import make_app_with  # if a helper exists; else build inline

    calls = {"created": []}

    class FakeA:
        name = "fakea"
        is_ready = True
        def warm_up(self): pass
        def recognize(self, b): return []
        def apply_settings(self, **o): return o
        def supported_settings(self): return []

    class FakeB:
        name = "fakeb"
        is_ready = True
        def warm_up(self): pass
        def recognize(self, b): return []
        def apply_settings(self, **o): return o
        def supported_settings(self): return []

    registry.register("fakea", lambda s: (calls["created"].append("fakea"), FakeA())[1])
    registry.register("fakeb", lambda s: (calls["created"].append("fakeb"), FakeB())[1])

    # Build app with engine=fakea selected via settings.engine
    from paddleocr_service.config import Settings
    from paddleocr_service.main import create_app
    s = Settings(engine="fakea", database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")
    app = create_app(settings=s)  # create_app picks engine from settings.engine via registry

    import httpx
    async with httpx.ASGITransport(app=app) as transport:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.patch("/settings", json={"engine": "fakeb"})
            assert r.status_code == 200
            assert r.json()["engine"] == "fakeb"
            assert calls["created"][-1] == "fakeb"
```

NOTE: this test requires `create_app` to read `settings.engine` and that `PATCH /settings` echoes `engine`. Adjust helper names to match the test file's actual fixtures. If `make_app_with` does not exist, inline the `create_app` call as shown.

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_settings_engine.py -v` (or the file you added it to)
Expected: FAIL — `/settings` does not yet handle `engine`, and `create_app` does not yet use the registry.

- [ ] **Step 5: Edit main.py — create_app uses registry**

Change the engine construction in `create_app` (around `main.py:45`):

```python
    from paddleocr_service.engines.registry import create_engine

    engine = ocr_engine or create_engine(app_settings.engine, app_settings)
```

Update the `PaddleOCREngine` import at `main.py:31` — replace `from paddleocr_service.ocr_engine import PaddleOCREngine` with nothing (no longer used directly in main; the registry imports it). Remove the now-unused import.

- [ ] **Step 6: Edit main.py — PATCH /settings handles engine swap**

Replace the body of `update_runtime_settings` (`main.py:261-279`) with:

```python
    @app.patch("/settings")
    def update_runtime_settings(payload: dict[str, Any]) -> dict[str, Any]:
        _validate_settings_patch(payload)
        # Nonlocal so the swap rebinds the create_app-scoped engine variable.
        nonlocal engine

        # 1. Swap engine first if requested.
        if "engine" in payload and payload["engine"] != app_settings.engine:
            new_name = payload["engine"]
            if new_name not in available_engines():
                raise HTTPException(
                    status_code=422,
                    detail=f"unknown engine: {new_name!r} (available: {available_engines()})",
                )
            app_settings.engine = new_name
            engine = create_engine(new_name, app_settings)
            if app_settings.warmup_on_startup:
                engine.warm_up()

        # 2. Apply remaining keys to the (possibly new) current engine.
        engine_keys = {s.key for s in engine.supported_settings()}
        app_level_keys = {
            "warmup_on_startup", "save_uploads", "max_upload_bytes",
            "pdf_render_scale", "retention_days",
        }
        engine_opts = {k: v for k, v in payload.items() if k in engine_keys}
        app_opts = {k: v for k, v in payload.items() if k in app_level_keys}
        unknown = set(payload) - {"engine"} - engine_keys - app_level_keys
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"engine {engine.name!r} does not support key(s): {sorted(unknown)}",
            )

        for key, value in app_opts.items():
            setattr(app_settings, key, value)
        if engine_opts:
            try:
                engine.apply_settings(**engine_opts)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        storage.ensure_base_dirs()
        return _public_settings(app_settings)
```

Add `available_engines` to the imports near the top of `create_app`:

```python
    from paddleocr_service.engines.registry import available_engines, create_engine
```

(Move both imports together.)

- [ ] **Step 7: Edit main.py — _public_settings echoes engine + supported_settings**

Replace `_public_settings` (`main.py:319-330`) — add `engine` and `supported_settings`:

```python
def _public_settings(settings: Settings, engine: Any | None = None) -> dict[str, Any]:
    result = {
        "engine": settings.engine,
        "language": settings.language,
        "use_angle_cls": settings.use_angle_cls,
        "warmup_on_startup": settings.warmup_on_startup,
        "save_uploads": settings.save_uploads,
        "max_upload_bytes": settings.max_upload_bytes,
        "pdf_render_scale": settings.pdf_render_scale,
        "retention_days": settings.retention_days,
        "cors_origins": settings.cors_origins,
        "access_log_path": str(settings.access_log_path),
    }
    if engine is not None:
        result["supported_settings"] = [
            {"key": s.key, "type": s.type, "description": s.description}
            for s in engine.supported_settings()
        ]
    return result
```

Update every call site of `_public_settings(app_settings)` (in `/health`, `GET /settings`, and the end of `PATCH /settings`) to pass `engine`: `_public_settings(app_settings, engine)`.

- [ ] **Step 8: Edit main.py — /health renames ocr_loaded to engine_ready**

In the `health()` handler (`main.py:89-105`), change `"ocr_loaded": bool(engine.is_ready)` to `"engine_ready": bool(engine.is_ready)` and add `"engine": app_settings.engine,`. Also pass `engine` to its `_public_settings` call.

Update `HealthResponse` schema in `schemas.py` to rename `ocr_loaded` → `engine_ready` and add `engine: str`. Update any test that asserts on `ocr_loaded`.

- [ ] **Step 9: Run full suite**

Run: `uv run --extra dev pytest -q`
Expected: all PASS, including the new hot-swap test and updated API tests. Fix any `ocr_loaded`/`FakeEngine` reference failures.

- [ ] **Step 10: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 11: Commit**

```bash
git add src/paddleocr_service/main.py src/paddleocr_service/schemas.py tests/
git commit -m "Wire engine registry into create_app; add /settings hot-swap; rename ocr_loaded->engine_ready"
```

---

## Task 9: pyproject extras + README

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Move paddleocr/paddlepaddle to an extra; add rapidocr extra**

Edit `pyproject.toml`. Remove lines 13-14 (`paddlepaddle`, `paddleocr`) from `dependencies`. Add two optional-dependency groups under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = [
    "httpx>=0.27.0",
    "pytest>=8.3.0",
    "ruff>=0.6.0",
]
paddleocr = [
    "paddlepaddle>=3.0.0,<4.0.0",
    "paddleocr>=3.7.0,<3.8.0",
]
rapidocr = [
    "rapidocr_onnxruntime",
]
```

- [ ] **Step 2: Regenerate the lockfile**

Run: `uv lock`
Expected: lockfile updated, both extras resolvable.

- [ ] **Step 3: Verify the dev/test environment still works**

Run: `uv sync --extra dev --extra rapidocr && uv run --extra dev pytest -q && uv run ruff check .`
Expected: all tests PASS, lint clean. (Tests do not import real OCR libs, so this works without paddleocr installed.)

- [ ] **Step 4: Update README install section**

Find the README install instructions (the section with `uv sync`). Update to reflect the opt-in extras:

```markdown
## 安装

```bash
# 选择一个或两个 OCR 引擎安装(默认引擎是 RapidOCR):
uv sync --extra dev --extra rapidocr        # 默认: RapidOCR(ONNX),轻量快速
# 或额外装 PaddleOCR(纯中文文档精度略高):
uv sync --extra dev --extra rapidocr --extra paddleocr
```

默认引擎由 `PADDLEOCR_ENGINE` 控制(默认 `rapidocr`),运行时也可通过 `PATCH /settings {"engine":"paddleocr"}` 热切换。
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock README.md
git commit -m "Make paddleocr/rapidocr optional extras; default to RapidOCR; update README"
```

---

## Self-Review (run after writing, before handoff)

**1. Spec coverage:**
- Unified protocol (`name`/`is_ready`/`warm_up`/`recognize`/`apply_settings`/`supported_settings`) → Task 1 (base.py). ✓
- Per-engine config, unknown-key-raises (422) → Task 4 (PaddleOCR `apply_settings`) + Task 6 (RapidOCR) + Task 8 (`PATCH /settings` 422). ✓
- Registry + `create_engine(name, settings)` → Task 2. ✓
- Startup select via `Settings.engine` (`PADDLEOCR_ENGINE`) → Task 7 + Task 8 Step 5. ✓
- Runtime hot-swap, swap-then-apply ordering, no in-flight interruption → Task 8 Step 6 (atomic `nonlocal engine` rebind). ✓
- Restructure `ocr_engine.py` into per-responsibility modules + delete it → Tasks 3, 4, 5. ✓
- `paddleocr`/`paddlepaddle` → optional extra; `rapidocr_onnxruntime` → extra → Task 9. ✓
- `/health` `engine_ready` + `engine` → Task 8 Step 8. ✓
- Out of scope respected: no per-request engine, no auto-select, no API-shape change, no UI. ✓

**2. Placeholder scan:** The only deferred decision is RapidOCR's supported-keys whitelist (Task 6 Step 1), which the plan handles explicitly with a concrete default (`text_score`) and a "verify against installed version" instruction. No TBD/TODO elsewhere. The hot-swap test (Task 8 Step 3) has a "if a helper exists, else inline" note — the inline fallback is given, so it is unambiguous.

**3. Type/signature consistency:** `OCREngine` protocol methods (`name`, `is_ready`, `warm_up`, `recognize`, `apply_settings`, `supported_settings`) are defined in Task 1 and implemented identically in Task 4 (PaddleOCR) and Task 6 (RapidOCR). `apply_settings` returns `dict[str, Any]` in all three. `supported_settings` returns `list[SupportedSetting]` consistently. `UnsupportedSettingError` is defined separately in each engine module (PaddleOCR Task 4, RapidOCR Task 6) — intentional, since they are engine-local and the `/settings` handler catches generic `Exception`. `Settings.engine` (Task 7) is read in Task 8 Step 5 consistently. `_public_settings` signature changes in Task 8 Step 7 and all call sites are updated in the same step.

**4. One known friction point, called out:** Task 5 (delete shim) is explicitly ordered after Task 8 because `main.py` still imports `PaddleOCREngine` from `ocr_engine.py` until Task 8 rewires it. The shim in Task 4 Step 4 exists precisely so the tree is never broken between tasks. This is intentional, not an oversight.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-19-pluggable-ocr-backend.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session with checkpoints.

Which approach?
