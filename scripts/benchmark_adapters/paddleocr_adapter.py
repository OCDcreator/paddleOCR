from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def normalize(raw: Any) -> list[dict]:
    """Normalize PaddleOCR output into the service's {text, confidence, box} shape.

    Mirrors paddleocr_service.ocr_engine.parse_paddleocr_result so adapter output
    is directly comparable to the running service.
    """
    if not raw:
        return []
    candidates = (
        raw[0] if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list) else raw
    )
    items: list[dict] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            texts = candidate.get("rec_texts")
            scores = candidate.get("rec_scores")
            if texts is not None and scores is not None:
                boxes = (
                    candidate.get("rec_polys")
                    or candidate.get("dt_polys")
                    or candidate.get("rec_boxes")
                    or []
                )
                for text, score, box in zip(texts, scores, boxes, strict=False):
                    items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
                continue
            text = candidate.get("text") or candidate.get("rec_text")
            score = candidate.get("confidence") or candidate.get("score")
            box = candidate.get("box") or candidate.get("points") or candidate.get("dt_polys")
            if text is not None and score is not None and box is not None:
                items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
            continue
        if isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
            box = _box(candidate[0])
            tas = candidate[1]
            if isinstance(tas, (list, tuple)) and len(tas) >= 2:
                items.append({"text": str(tas[0]), "confidence": float(tas[1]), "box": box})
    return items


def _box(box: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        out.append([float(point[0]), float(point[1])])
    return out


def build_engine(lang: str, tier: str) -> Any:
    """Build the PaddleOCR engine for the given tier.

    tier='default' mirrors the running service (no extra model args).
    tier='mobile' requests the lightweight detection model via PaddleOCR 3.x's
    documented det model name; if the installed version rejects it, main() catches
    the error and reports it so the driver marks the contender unavailable.
    """
    from paddleocr import PaddleOCR

    kwargs: dict[str, Any] = {"lang": lang, "use_textline_orientation": True}
    if tier == "mobile":
        # PaddleOCR 3.7.0 ships no PP-OCRv5 *mobile* detector (only server), so the
        # newest available lightweight detection model is PP-OCRv4_mobile_det. This
        # is the "mobile tier" used for the speed comparison. If a future PaddleOCR
        # removes this name, main() catches the error and the driver marks the
        # contender unavailable.
        kwargs["text_detection_model_name"] = "PP-OCRv4_mobile_det"
    return PaddleOCR(**kwargs)


def run_loop(engine: Any) -> None:
    """Read image paths from stdin (one JSON request per line), write results to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        image_path = Path(request["image"])
        result: dict[str, Any] = {
            "image": str(image_path),
            "text": "",
            "items": [],
            "elapsed_ms": 0,
            "error": None,
        }
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_path.read_bytes())
                tmp_path = Path(tmp.name)
            try:
                start = time.perf_counter()
                raw = engine.predict(str(tmp_path))
                result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
                items = normalize(raw)
                result["items"] = items
                result["text"] = "\n".join(i["text"] for i in items)
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - report any failure, do not crash the stream
            result["error"] = f"{type(exc).__name__}: {exc}"
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCR benchmark adapter subprocess.")
    parser.add_argument("--tier", choices=["default", "mobile"], default="default")
    parser.add_argument("--lang", default="ch")
    args = parser.parse_args()
    try:
        engine = build_engine(args.lang, args.tier)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"fatal": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()
        return
    run_loop(engine)


if __name__ == "__main__":
    main()
