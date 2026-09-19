from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from runpy import run_path

    run_path(str(ROOT / "scripts/generate_schema.py"), run_name="__main__")
    target = ROOT / "dist"
    target.mkdir(exist_ok=True)
    for browser in ("chromium", "firefox"):
        with zipfile.ZipFile(
            target / f"privacy-guardian-{browser}.zip", "w", zipfile.ZIP_DEFLATED
        ) as output:
            for path in sorted((ROOT / "extension").rglob("*")):
                if (
                    not path.is_file()
                    or path.name.startswith(".")
                    or path.name == "manifest.firefox.json"
                ):
                    continue
                relative = path.relative_to(ROOT / "extension")
                if path.name == "manifest.json" and browser == "firefox":
                    manifest = json.loads((ROOT / "extension/manifest.firefox.json").read_text())
                    output.writestr("manifest.json", json.dumps(manifest, indent=2))
                else:
                    output.write(path, relative)
        print(target / f"privacy-guardian-{browser}.zip")


if __name__ == "__main__":
    main()
