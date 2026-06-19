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
                items.append(
                    {
                        "text": str(text),
                        "confidence": float(score),
                        "box": normalize_box(box),
                    }
                )
    return items
