from __future__ import annotations

import pytest

from privacy_guardian.core import worker_dispatch


@pytest.fixture(autouse=True)
def clear_uploads() -> None:
    worker_dispatch._UPLOADS.clear()
    yield
    worker_dispatch._UPLOADS.clear()


def test_start_upload_rejects_invalid_duplicate_and_full_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Invalid upload"):
        worker_dispatch.start_upload("", "file.txt", 1)
    with pytest.raises(ValueError, match="Invalid upload"):
        worker_dispatch.start_upload("too-large", "file.txt", worker_dispatch.MAX_SIZE + 1)

    monkeypatch.setattr(worker_dispatch, "MAX_UPLOADS", 1)
    worker_dispatch.start_upload("first", "f" * 300, 2, "x" * 200)
    stored = worker_dispatch._UPLOADS["first"]
    assert len(stored.filename) == 255
    assert len(stored.mime) == 128
    with pytest.raises(ValueError, match="queue is full"):
        worker_dispatch.start_upload("second", "file.txt", 1)
    with pytest.raises(ValueError, match="queue is full"):
        worker_dispatch.start_upload("first", "file.txt", 1)


def test_worker_preparation_is_lazy_and_reports_model_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert worker_dispatch.prepare_worker() is True
    monkeypatch.setattr("privacy_guardian.analysis.pii.detector._ner", lambda: object())
    assert worker_dispatch.prepare_upload_model() is True


def test_invalid_chunk_discards_upload() -> None:
    worker_dispatch.start_upload("upload", "file.txt", 3)

    with pytest.raises(ValueError, match="chunk sequence"):
        worker_dispatch.append_upload("upload", 1, b"abc")

    assert "upload" not in worker_dispatch._UPLOADS


def test_small_upload_finishes_with_complete_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    def analyze(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        return {"analyzed": True}

    monkeypatch.setattr("privacy_guardian.analysis.worker.analyze_payload", analyze)
    worker_dispatch.start_upload("small", "synthetic.txt", 6, "text/plain")
    worker_dispatch.append_upload("small", 0, b"abc")
    worker_dispatch.append_upload("small", 1, b"def")

    result = worker_dispatch.finish_upload("small", timeout=4)

    assert result == {"analyzed": True}
    assert captured == [
        {
            "kind": "document",
            "filename": "synthetic.txt",
            "mime": "text/plain",
            "data": b"abcdef",
            "partial": False,
            "original_size": 6,
            "timeout": 4,
        }
    ]


def test_large_upload_keeps_bounded_first_and_tail_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(worker_dispatch, "FULL_SIZE", 5)
    monkeypatch.setattr(worker_dispatch, "SAMPLE_SIZE", 2)
    monkeypatch.setattr(
        "privacy_guardian.analysis.worker.analyze_payload",
        lambda payload: captured.append(payload) or payload,
    )
    worker_dispatch.start_upload("large", "large.bin", 8)
    worker_dispatch.append_upload("large", 0, b"abcd")
    worker_dispatch.append_upload("large", 1, b"efgh")

    worker_dispatch.finish_upload("large")

    assert captured[0]["data"] == b"abgh"
    assert captured[0]["partial"] is True
    assert captured[0]["original_size"] == 8


def test_incomplete_expired_and_aborted_uploads_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_dispatch.start_upload("incomplete", "file.txt", 3)
    worker_dispatch.append_upload("incomplete", 0, b"ab")
    with pytest.raises(ValueError, match="incomplete"):
        worker_dispatch.finish_upload("incomplete")

    now = 1000.0
    monkeypatch.setattr(worker_dispatch.time, "monotonic", lambda: now)
    worker_dispatch._UPLOADS["expired"] = worker_dispatch.Upload(
        filename="old.txt", size=0, mime="", touched=now - worker_dispatch.UPLOAD_TTL - 1
    )
    worker_dispatch.start_upload("fresh", "fresh.txt", 0)
    assert "expired" not in worker_dispatch._UPLOADS
    worker_dispatch.abort_upload("fresh")
    assert worker_dispatch._UPLOADS == {}


def test_refine_context_validates_schema_and_returns_typed_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

    class Client:
        def __init__(self, settings: object) -> None:
            calls.append((settings,))

        def complete(
            self,
            use: object,
            payload: object,
            schema: object,
            fallback: object,
        ) -> Result:
            calls.append((use, payload, schema, fallback))
            return Result(fallback)

    monkeypatch.setattr("privacy_guardian.llm.client.LLMClient", Client)
    result = worker_dispatch.refine_context(
        "purpose_refinement",
        {"origin": "https://synthetic.example"},
        {"enabled": True},
        "purpose",
        {"purpose": "recipe", "confidence": 0.8, "rationale": "Synthetic local result"},
    )

    assert result == {
        "purpose": "recipe",
        "confidence": 0.8,
        "rationale": "Synthetic local result",
    }
    assert len(calls) == 2
