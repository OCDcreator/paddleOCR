from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _box(box: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for point in box:
        out.append([float(point[0]), float(point[1])])
    return out


def normalize(result: Any) -> list[dict]:
    """Normalize RapidOCR output into {text, confidence, box}.

    RapidOCR (rapidocr_onnxruntime) RapidOCR().call(img) returns an object whose
    .txts / .scores / .boxes give the recognized lines; older versions return a
    list of [box, text, score]. Handle both.
    """
    items: list[dict] = []
    if result is None:
        return items
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if txts is not None and scores is not None and boxes is not None:
        for text, score, box in zip(txts, scores, boxes, strict=False):
            items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
        return items
    if isinstance(result, (list, tuple)):
        for entry in result:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                box, text, score = entry[0], entry[1], entry[2]
                items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
    return items


def build_engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def run_loop(engine: Any) -> None:
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
            start = time.perf_counter()
            raw = engine(str(image_path))
            result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            items = normalize(raw)
            result["items"] = items
            result["text"] = "\n".join(i["text"] for i in items)
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    argparse.ArgumentParser(description="RapidOCR benchmark adapter subprocess.").parse_args()
    try:
        engine = build_engine()
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"fatal": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()
        return
    run_loop(engine)


if __name__ == "__main__":
    main()
