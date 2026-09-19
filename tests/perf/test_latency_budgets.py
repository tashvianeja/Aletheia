from __future__ import annotations

import io
import random
import time
from pathlib import Path

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from privacy_guardian.analysis.consent import ConsentSnapshot, analyze_consent
from privacy_guardian.analysis.forms import analyze_fields
from privacy_guardian.analysis.policy import analyze_policy
from privacy_guardian.analysis.worker import analyze_payload
from privacy_guardian.core.events import FormField
from privacy_guardian.core.pool import AnalysisPool

TOLERANCE = 1.25


def elapsed(function: object, *args: object) -> tuple[object, float]:
    started = time.perf_counter()
    result = function(*args)  # type: ignore[operator]
    return result, time.perf_counter() - started


@pytest.mark.perf
def test_form_analyzer_microbenchmark() -> None:
    fields = [
        FormField(field_id=f"field-{index}", autocomplete="tel" if index % 2 else "email")
        for index in range(40)
    ]
    result, seconds = elapsed(analyze_fields, fields, "free_download")
    assert len(result) == 40  # type: ignore[arg-type]
    assert seconds <= 0.300 * TOLERANCE


@pytest.mark.perf
def test_consent_analyzer_microbenchmark() -> None:
    snapshot = ConsentSnapshot.model_validate(
        {
            "text": "We use necessary, analytics, and advertising cookies.",
            "cmp": "onetrust",
            "buttons": [
                {"text": "Accept all", "visible": True, "area": 4000, "contrast": 7},
                {"text": "Reject all", "visible": True, "area": 4000, "contrast": 7},
            ],
            "toggles": [
                {"purpose": "analytics", "enabled": False, "optional": True},
                {"purpose": "advertising", "enabled": False, "optional": True},
            ],
        }
    )
    result, seconds = elapsed(analyze_consent, snapshot)
    assert result.cmp == "onetrust"  # type: ignore[union-attr]
    assert seconds <= 0.400 * TOLERANCE


@pytest.mark.perf
def test_200kb_policy_offline_latency_budget() -> None:
    clauses = (
        "We collect email to deliver the service. We share data with service providers. "
        "You may request deletion. We retain records until account deletion.\n"
    )
    text = (clauses * (205_000 // len(clauses) + 1))[:205_000]
    result, seconds = elapsed(analyze_policy, text, "account_creation")
    assert result.document_hash  # type: ignore[union-attr]
    assert seconds <= 2.5 * TOLERANCE


@pytest.mark.perf
@pytest.mark.parametrize(("size", "budget"), [(5 * 1024**2, 1.5), (25 * 1024**2, 3.0)])
def test_representative_text_document_analyzer_latency(size: int, budget: float) -> None:
    header = b"Synthetic service export for test@example.test.\n"
    record = (
        b"Ordinary synthetic invoice narrative describing product delivery and account status "
        b"without personal details.\n"
    )
    content = (header + record * (size // len(record) + 1))[:size]
    result, seconds = elapsed(
        analyze_payload,
        {"kind": "document", "filename": "synthetic-records.txt", "data": content},
    )
    assert result.document_type == "generic"  # type: ignore[union-attr]
    assert len(result.findings) == 1  # type: ignore[union-attr]
    assert result.partial is True  # type: ignore[union-attr]
    assert seconds <= budget * TOLERANCE


def synthetic_mixed_pdf(path: Path, minimum_size: int = 25 * 1024**2) -> None:
    """Build a bounded real PDF with readable invoice text and unique synthetic images."""
    for page_count in (30, 36, 42):
        output = io.BytesIO()
        canvas = Canvas(output, pagesize=(612, 792), pageCompression=1)
        for page_number in range(1, page_count + 1):
            pixels = random.Random(page_number).randbytes(1024 * 1024 * 3)
            image = Image.frombytes("RGB", (1024, 1024), pixels)
            encoded = io.BytesIO()
            image.save(encoded, "JPEG", quality=92)
            encoded.seek(0)
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawString(48, 750, f"Synthetic invoice page {page_number}")
            canvas.setFont("Helvetica", 10)
            canvas.drawString(48, 730, "Account status: test record; amount due: 0.00")
            canvas.drawImage(ImageReader(encoded), 48, 80, width=516, height=620)
            canvas.showPage()
        canvas.save()
        content = output.getvalue()
        if len(content) >= minimum_size:
            path.write_bytes(content)
            return
    raise AssertionError(f"bounded synthetic PDF was only {len(content)} bytes")


@pytest.mark.perf
@pytest.mark.asyncio
async def test_25mb_pdf_cold_and_warm_process_worker_latency(tmp_path: Path) -> None:
    document = tmp_path / "synthetic-mixed-invoices.pdf"
    synthetic_mixed_pdf(document)
    content = document.read_bytes()
    assert 25 * 1024**2 <= len(content) <= 40 * 1024**2
    pool = AnalysisPool(timeout=30)
    try:
        started = time.perf_counter()
        cold_result = await pool.run(
            analyze_payload,
            {"kind": "document", "filename": document.name, "data": content},
        )
        cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        warm_result = await pool.run(
            analyze_payload,
            {"kind": "document", "filename": document.name, "data": content},
        )
        warm_seconds = time.perf_counter() - started
    finally:
        pool.close()
    assert cold_result.document_type == "generic"
    assert warm_result.document_type == "generic"
    assert cold_seconds <= 3.0 * TOLERANCE, (cold_seconds, warm_seconds)
    assert warm_seconds <= 3.0 * TOLERANCE, (cold_seconds, warm_seconds)
