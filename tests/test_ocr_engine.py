from paddleocr_service.ocr_engine import parse_paddleocr_result


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
