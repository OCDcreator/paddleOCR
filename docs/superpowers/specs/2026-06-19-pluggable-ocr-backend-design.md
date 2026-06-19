# Pluggable OCR Backend Design

## Goal

Make the OCR engine pluggable so the service can run either RapidOCR (ONNX, the new default) or PaddleOCR (the previous engine) behind a single interface, selectable at startup via `.env` and swappable at runtime via `PATCH /settings`. Restructure the engine code into focused modules so no single file accumulates multiple responsibilities.

## Background

`docs/verification/2026-06-19-engine-benchmark.json` measured both engines on the target Mac (Apple Silicon, Python 3.13):

- RapidOCR: 240 ms median latency, 95.6% character accuracy
- PaddleOCR (default server tier): 786 ms, 47.8%
- PaddleOCR (mobile tier): 535 ms, 47.1%

RapidOCR is ~3x faster and more robust (it is the only engine that does not fail on large/blank images). PaddleOCR retains a small edge on pure-Chinese documents. The decision: **RapidOCR becomes the default; PaddleOCR stays available as an option.**

The current `src/paddleocr_service/ocr_engine.py` (161 lines) mixes four responsibilities — the engine class, PaddleOCR result parsing, box normalization, and image validation. `PaddleOCREngine` already exposes an implicit interface (`is_ready`, `warm_up`, `configure`, `recognize`) and `create_app(ocr_engine=None)` already supports dependency injection. This spec formalizes that interface and decomposes the file.

## Scope

In scope:
- A unified `OCREngine` protocol with per-engine configuration.
- A `RapidOCREngine` implementation.
- A registry that selects an engine by name.
- Startup selection via `Settings.engine` (`PADDLEOCR_ENGINE`) and runtime hot-swap via `PATCH /settings`.
- Restructuring `ocr_engine.py` into per-responsibility modules.
- Making `paddleocr`/`paddlepaddle` and `rapidocr_onnxruntime` optional extras (not forced main deps).

Out of scope (deliberate, YAGNI):
- Per-request engine selection. Only startup-select plus runtime hot-swap.
- Automatic engine choice (picking based on image content or hardware).
- Changing the OCR result API shape — `OCRResponse` / `items` stay identical, transparent to the frontend.
- Engine performance monitoring or automatic degradation.
- A frontend engine-picker UI (API only this round; UI may follow).

## Architecture

A `Protocol`-based interface plus a registry. `PaddleOCREngine` (migrated) and `RapidOCREngine` (new) both implement it. `create_app` builds the engine via the registry instead of hardcoding `PaddleOCREngine`.

## File Structure

```
src/paddleocr_service/
  ocr_engine.py            # REMOVED — responsibilities split into engines/
  engines/
    __init__.py            # public exports: OCREngine, create_engine, get_engine_info
    base.py                # OCREngine Protocol, SupportedSetting, validate_image(), normalize_box()
    registry.py            # ENGINES map, create_engine(name, settings), available_engines()
    paddleocr/
      __init__.py
      engine.py            # PaddleOCREngine (migrated from ocr_engine.py)
      parser.py            # parse_paddleocr_result + _parse_* + _first_present + PaddleOCR-specific normalize
    rapidocr/
      __init__.py
      engine.py            # RapidOCREngine (new)
      parser.py            # RapidOCR result normalization (unpacks the (lines, elapse) tuple)
```

Rationale: one file, one responsibility. Each engine lives in its own subpackage with its class and its result parser, so adding a third engine follows the same pattern. `base.py` holds only what is genuinely shared across engines.

## The OCREngine Interface

Defined as a `Protocol` in `base.py`:

```python
class OCREngine(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def is_ready(self) -> bool: ...
    def warm_up(self) -> None: ...
    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]: ...
    def apply_settings(self, **opts: Any) -> dict[str, Any]: ...
    def supported_settings(self) -> list[SupportedSetting]: ...
```

- `name` — `"rapidocr"` / `"paddleocr"`. Used in `/health`, `/settings`, and logs.
- `is_ready`, `warm_up`, `recognize` — identical contract for every engine.
- `apply_settings(**opts)` — per-engine configuration. Each engine accepts only keys in its own whitelist. **Unknown keys raise** (no silent ignore); `PATCH /settings` catches this and returns 422. Returns the settings that took effect, for `/settings` echo.
- `supported_settings()` — declares which keys the engine accepts (with types/validation hints), so `/settings` GET can report what is configurable for the current engine. Replaces the previously hardcoded field list.

Shared utilities in `base.py`:
- `validate_image(image_bytes)` — PIL verification, used by all engines.
- `normalize_box(box)` — coordinate normalization to `list[list[float]]`, used by all result parsers.

## PaddleOCREngine (migration)

Moved to `engines/paddleocr/engine.py`. Changes:
- Add `name` → `"paddleocr"`.
- Rename `configure(language, use_angle_cls)` → `apply_settings(language=..., use_angle_cls=...)`. Same lazy-reload behavior (set `_ocr = None` when language changes). Whitelist is `{language, use_angle_cls}`; any other key raises `ValueError`/typed error.
- `recognize` unchanged internally but calls `base.validate_image` and `paddleocr.parser.parse_paddleocr_result`.
- `_first_present` (the numpy-safe fix from the prior benchmark work) moves into `paddleocr/parser.py` and keeps its regression test.

`parse_paddleocr_result` and its helpers move to `engines/paddleocr/parser.py`. Existing `tests/test_ocr_engine.py` tests are migrated to test that module's import path (including the no-text numpy regression test).

## RapidOCREngine (new)

`engines/rapidocr/engine.py`:
- Lazy-loads `RapidOCR()` on first `recognize`/`warm_up`.
- `recognize` writes image bytes to a temp PNG, calls `engine(path)`, then normalizes via `rapidocr/parser.py` — which unpacks the `(lines, elapse)` tuple and maps `[box, text, score]` entries into `{text, confidence, box}`. This mirrors the validated `rapidocr_adapter.py` logic from the benchmark.
- `apply_settings` whitelist: RapidOCR's own parameters (e.g. detection/recognition model knobs). The concrete supported set is finalized against RapidOCR's docs during implementation; the spec requires only that the whitelist is explicit and that unknown keys raise.
- `name` → `"rapidocr"`.

## Registry

`engines/registry.py`:
- `ENGINES: dict[str, type[OCREngine]] = {"rapidocr": RapidOCREngine, "paddleocr": PaddleOCREngine}`.
- `create_engine(name, settings)` — looks up the class, constructs it with `settings`. Unknown name raises a clear error.
- `available_engines()` — list of registered names, for `/settings`/docs.
- Importing `rapidocr_engine` and `paddleocr_engine` here is safe even if the underlying library is absent, because each engine imports its library lazily (inside `__init__`/`warm_up`), not at module top. So the registry module loads regardless of which extras are installed; failure surfaces only when an engine is actually selected and its library is missing.

## Startup Selection

- `Settings.engine: str = "rapidocr"` (env `PADDLEOCR_ENGINE`).
- `main.py`'s `create_app` changes from `engine = ocr_engine or PaddleOCREngine(app_settings)` to `engine = ocr_engine or create_engine(app_settings.engine, app_settings)`.
- If the selected engine's library is not installed, `create_engine`/engine init raises a clear message naming the missing package and the install command, and the service fails to start (no silent fallback).

## Runtime Hot-Swap

`PATCH /settings` is extended:
1. If the body includes `engine` and it differs from the current engine, **swap**: replace the engine instance via `create_engine(new_name, app_settings)`, warm it up if `warmup_on_startup` is on. Old engine-specific settings are NOT carried over (different engines have incompatible settings; the caller must re-supply them).
2. All other keys go to `current_engine.apply_settings(**opts)`. Unknown-for-this-engine keys raise → `PATCH /settings` returns **422** with `"engine <name> does not support key <key>"`.
3. `GET /settings` returns `current_engine` plus `supported_settings()` for the active engine, replacing the hardcoded field list.

**Concurrency safety of the swap:** the swap replaces a reference to the engine object. A recognition already in flight (running in a threadpool) keeps its own reference to the old engine and finishes on it; the old object is not GC'd until that call returns. The next recognition uses the new engine. Reference assignment is atomic and there is a single asyncio worker, so no lock is needed. An in-flight OCR is NOT interrupted (single images are ~0.2–5 s; blocking global swap on idle is not worth the complexity).

`/health` reports `engine_ready` (renamed from `ocr_loaded`) and the current `engine` name.

## Dependencies

`pyproject.toml` changes:
- `paddleocr` and `paddlepaddle` move from main dependencies to an optional extra group `paddleocr`.
- `rapidocr_onnxruntime` is added under an optional extra group `rapidocr`.
- Install becomes opt-in per engine: `uv sync --extra rapidocr` or `uv sync --extra paddleocr` (or both).
- Rationale: a "pluggable" backend is only real if choosing RapidOCR does not force installing PaddlePaddle. This is a breaking change to the install path; deployment docs (README) must be updated accordingly.

`uv.lock` is regenerated to reflect the extras. `dev` extra continues to include test/lint tooling.

## Testing

- `tests/test_engines_base.py` — `validate_image`, `normalize_box`, Protocol sanity.
- `tests/test_registry.py` — engine lookup, unknown engine raises, `create_engine` routing.
- `tests/test_rapidocr_engine.py` — `RapidOCREngine.recognize`/`apply_settings` with a mocked RapidOCR; unknown-key-raises; supported_settings.
- `tests/test_paddleocr_engine.py` — migrate existing `test_ocr_engine.py` tests to the new import path, plus `name`/`apply_settings` coverage and the numpy no-text regression test.
- `tests/test_ocr_api.py` — existing `FakeEngine` already implements `recognize`; it is extended to satisfy the Protocol (`name`, `apply_settings`, `supported_settings`) so API tests keep passing unchanged in behavior.
- No unit test imports a real OCR engine — all engine unit tests use mocks/fakes. Real inference is validated only by the existing benchmark (`scripts/benchmark_*`).

## Success Criteria

- `uv sync --extra rapidocr` produces an environment where the service defaults to RapidOCR and runs without PaddlePaddle installed.
- `PATCH /settings {"engine": "paddleocr"}` hot-swaps at runtime; `PATCH /settings {"engine": "rapidocr", "<unknown>": ...}` returns 422 naming the unsupported key.
- `GET /settings` reports the active engine and its supported settings.
- All existing API tests pass (with `FakeEngine` extended to the Protocol); migrated `parse_paddleocr_result` tests (including the numpy no-text regression) pass at the new import path.
- `ocr_engine.py` is removed; no module exceeds its single responsibility.

## Non-Goals / Deferred

- Per-request engine selection.
- Automatic engine selection by image content or hardware.
- Changing the OCR result API shape (`OCRResponse`/`items`).
- Engine performance monitoring or automatic degradation.
- Frontend engine-picker UI.
