"""Precompute sentence-embedding centroids for each form intent.

Run after changing `intelligence/taxonomy.py`. Shipping the centroids keeps first-form
latency to a single ONNX call instead of re-embedding every exemplar at startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aletheia.intelligence.embedder import embed  # noqa: E402
from aletheia.intelligence.taxonomy import EXEMPLARS  # noqa: E402

TARGET = ROOT / "src/aletheia/data/models/intent_centroids.npz"


def main() -> int:
    names = [intent.value for intent in EXEMPLARS]
    centroids = []
    for intent in EXEMPLARS:
        vectors = embed(list(EXEMPLARS[intent]))
        if vectors is None:
            print("embedder unavailable; cannot build centroids", file=sys.stderr)
            return 1
        mean = vectors.mean(axis=0)
        centroids.append(mean / max(float(np.linalg.norm(mean)), 1e-9))
    np.savez_compressed(
        TARGET, names=np.array(names), centroids=np.stack(centroids).astype(np.float32)
    )
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(names)} intents, {TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
