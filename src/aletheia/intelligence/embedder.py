from __future__ import annotations

import logging
import threading
import time
from importlib.resources import as_file, files
from pathlib import Path

import numpy as np

from aletheia.intelligence.tokenizer import encode_batch

LOGGER = logging.getLogger("aletheia.intelligence")
DIMENSIONS = 384
MODEL_FILE = "minilm-int8.onnx"

_LOCK = threading.Lock()
_SESSION: object | None = None
_UNAVAILABLE = False
_CACHE: dict[str, np.ndarray] = {}
_CACHE_LIMIT = 4096
_LAST_USED = 0.0
# The weights cost about 95 MB resident. The product has a 200 MB idle target, so the
# session is held only while someone is actually filling in forms and handed back once
# they stop. Reloading costs roughly 150 ms against a 300 ms badge budget.
IDLE_RELEASE_SECONDS = 90.0


def model_path() -> Path | None:
    try:
        with as_file(files("aletheia.data.models").joinpath(MODEL_FILE)) as path:
            return path if path.exists() else None
    except (ModuleNotFoundError, FileNotFoundError, OSError):
        return None


def _session() -> object | None:
    """Load the sentence encoder on first use.

    Deliberately lazy: the tray process must reach ready in under three seconds and hold
    its resident-memory budget, so nothing here is imported or allocated until a page
    actually presents a form. When the runtime or the weights are missing the caller
    falls back to structural inference rather than failing the assessment.
    """
    global _SESSION, _UNAVAILABLE
    if _SESSION is not None or _UNAVAILABLE:
        return _SESSION
    with _LOCK:
        if _SESSION is not None or _UNAVAILABLE:
            return _SESSION
        path = model_path()
        if path is None:
            _UNAVAILABLE = True
            LOGGER.info("embedder_unavailable", extra={"reason": "weights_missing"})
            return None
        global _LAST_USED
        _LAST_USED = time.monotonic()
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            # One thread apiece: this runs inside the analysis worker alongside document
            # extraction, and an unbounded pool starves that path on small machines.
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            options.log_severity_level = 3
            _SESSION = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:  # pragma: no cover - runtime/platform dependent
            _UNAVAILABLE = True
            LOGGER.info("embedder_unavailable", extra={"reason": type(error).__name__})
            return None
    return _SESSION


def available() -> bool:
    return _session() is not None


def release_if_idle(now: float | None = None) -> bool:
    """Drop the loaded weights once nobody has needed them for a while."""
    global _SESSION
    if _SESSION is None:
        return False
    if (now or time.monotonic()) - _LAST_USED < IDLE_RELEASE_SECONDS:
        return False
    with _LOCK:
        if _SESSION is None:
            return False
        _SESSION = None
        _CACHE.clear()
    LOGGER.info("embedder_released", extra={"reason": "idle"})
    return True


def embed(texts: list[str]) -> np.ndarray | None:
    """Mean-pooled, L2-normalised sentence embeddings, or None when unavailable."""
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype=np.float32)
    session = _session()
    if session is None:
        return None
    global _LAST_USED
    _LAST_USED = time.monotonic()
    pending = [text for text in dict.fromkeys(texts) if text not in _CACHE]
    if pending:
        ids, mask = encode_batch(pending)
        arrays = {
            "input_ids": np.asarray(ids, dtype=np.int64),
            "attention_mask": np.asarray(mask, dtype=np.int64),
        }
        names = {item.name for item in session.get_inputs()}  # type: ignore[attr-defined]
        if "token_type_ids" in names:
            arrays["token_type_ids"] = np.zeros_like(arrays["input_ids"])
        try:
            hidden = session.run(["last_hidden_state"], arrays)[0]  # type: ignore[attr-defined]
        except Exception as error:  # pragma: no cover - runtime dependent
            LOGGER.info("embedder_failed", extra={"reason": type(error).__name__})
            return None
        weights = arrays["attention_mask"][..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
        pooled = (pooled / norms).astype(np.float32)
        if len(_CACHE) > _CACHE_LIMIT:
            _CACHE.clear()
        for text, vector in zip(pending, pooled, strict=True):
            _CACHE[text] = vector
    return np.stack([_CACHE[text] for text in texts])


def embed_one(text: str) -> np.ndarray | None:
    result = embed([text])
    return None if result is None else result[0]


def reset_for_tests() -> None:
    global _SESSION, _UNAVAILABLE, _LAST_USED
    with _LOCK:
        _SESSION = None
        _UNAVAILABLE = False
        _LAST_USED = 0.0
        _CACHE.clear()
