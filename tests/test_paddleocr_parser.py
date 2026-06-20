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
