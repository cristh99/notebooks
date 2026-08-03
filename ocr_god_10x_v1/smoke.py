"""Fail-closed viability probe for persistent PP-OCRv6 tiny CPU inference."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import time
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

REPORT_SCHEMA = "ocr-god-10x/smoke/1"
NUMERIC_RE = re.compile(r"(?<!\w)[+-]?(?:\d[\d.,:/-]*\d|\d)(?!\w)")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_page(path: Path) -> None:
    width, height = 1800, 1200
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    font_path = next((candidate for candidate in font_candidates if Path(candidate).exists()), None)
    if font_path is None:
        raise RuntimeError("no deterministic TrueType font found")
    title = ImageFont.truetype(font_path, 54)
    body = ImageFont.truetype(font_path, 42)
    small = ImageFont.truetype(font_path, 36)

    rows = [
        (90, "REPÚBLICA DE HONDURAS", title),
        (190, "SECRETARÍA DE INFRAESTRUCTURA", body),
        (300, "Contrato SIT-CO-497-2024", body),
        (390, "Monto total: L 98,765.43", body),
        (480, "Fecha: 03/08/2026   Factura: 000-001-01-00000524", small),
        (570, "RTN: 0801-1990-123456", body),
        (690, "La cifra correcta es 104729, no 104739.", body),
        (800, "PAGO ÚNICO — ESTIMACIÓN No. 7", body),
    ]
    for y, text, font in rows:
        draw.text((90, y), text, fill="black", font=font)
    image.save(path, format="PNG", optimize=False)


def unwrap_result(result: Any) -> Mapping[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise TypeError(f"unexpected result payload type: {type(payload)!r}")
    inner = payload.get("res", payload)
    if not isinstance(inner, Mapping):
        raise TypeError("result payload does not contain a mapping")
    return inner


def predict_once(pipeline: Any, image_path: Path) -> tuple[float, list[str], list[float], list[list[int]]]:
    started = time.perf_counter()
    results = list(pipeline.predict(str(image_path)))
    elapsed = time.perf_counter() - started
    if len(results) != 1:
        raise AssertionError(f"expected one result, observed {len(results)}")
    payload = unwrap_result(results[0])
    texts = [str(value) for value in payload.get("rec_texts", [])]
    scores = [float(value) for value in payload.get("rec_scores", [])]
    boxes = [[int(x) for x in row] for row in payload.get("rec_boxes", [])]
    if not texts:
        raise AssertionError("PP-OCRv6 returned no recognized text")
    if len(scores) != len(texts) or len(boxes) != len(texts):
        raise AssertionError("text, score and box denominators differ")
    return elapsed, texts, scores, boxes


def main() -> int:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")

    output_dir = Path(os.environ.get("OCR_GOD_10X_OUTPUT", "ocr_god_10x_v1/run/smoke"))
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "spanish_numeric_probe.png"
    build_page(image_path)

    from paddleocr import PaddleOCR

    init_started = time.perf_counter()
    pipeline = PaddleOCR(
        text_detection_model_name="PP-OCRv6_tiny_det",
        text_recognition_model_name="PP-OCRv6_tiny_rec",
        lang="es",
        device="cpu",
        enable_hpi=True,
        cpu_threads=4,
        text_recognition_batch_size=16,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    init_seconds = time.perf_counter() - init_started

    first_seconds, first_texts, first_scores, first_boxes = predict_once(pipeline, image_path)
    second_seconds, second_texts, second_scores, second_boxes = predict_once(pipeline, image_path)

    first_joined = "\n".join(first_texts)
    second_joined = "\n".join(second_texts)
    numeric_tokens = NUMERIC_RE.findall(second_joined)
    if not numeric_tokens:
        raise AssertionError("no numeric token was recognized")
    if first_texts != second_texts or first_boxes != second_boxes:
        raise AssertionError("persistent replay changed text or geometry")

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PASS",
        "model": {
            "detector": "PP-OCRv6_tiny_det",
            "recognizer": "PP-OCRv6_tiny_rec",
            "language": "es",
            "enable_hpi": True,
            "device": "cpu",
            "cpu_threads": 4,
        },
        "runtime": {
            "initialization_seconds": init_seconds,
            "first_inference_seconds": first_seconds,
            "second_inference_seconds": second_seconds,
            "second_lines": len(second_texts),
            "second_numeric_tokens": numeric_tokens,
            "mean_recognition_score": sum(second_scores) / len(second_scores),
        },
        "determinism": {
            "text_equal": first_texts == second_texts,
            "boxes_equal": first_boxes == second_boxes,
            "first_text_sha256": sha256_text(first_joined),
            "second_text_sha256": sha256_text(second_joined),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "paddleocr": package_version("paddleocr"),
            "paddlepaddle": package_version("paddlepaddle"),
            "openvino": package_version("openvino"),
            "onnxruntime": package_version("onnxruntime"),
            "paddlex": package_version("paddlex"),
        },
        "recognized": [
            {"text": text, "score": score, "box": box}
            for text, score, box in zip(second_texts, second_scores, second_boxes, strict=True)
        ],
    }
    stable_payload = {key: value for key, value in report.items() if key != "stable_payload_sha256"}
    report["stable_payload_sha256"] = sha256_text(canonical_json(stable_payload))
    report_path = output_dir / "smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "recognized.txt").write_text(second_joined + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "init_seconds": init_seconds,
        "first_seconds": first_seconds,
        "second_seconds": second_seconds,
        "lines": len(second_texts),
        "numeric_tokens": numeric_tokens,
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
