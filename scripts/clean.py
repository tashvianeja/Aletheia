import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ("build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov"):
    path = root / name
    if path.exists() and path.parent == root and not path.is_symlink():
        shutil.rmtree(path)
