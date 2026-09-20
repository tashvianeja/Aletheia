from __future__ import annotations

import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from runpy import run_path

    run_path(str(ROOT / "scripts/generate_schema.py"), run_name="__main__")
    target = ROOT / "dist"
    target.mkdir(exist_ok=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    for browser in ("chromium", "firefox"):
        with zipfile.ZipFile(
            target / f"aletheia-{browser}.zip", "w", zipfile.ZIP_DEFLATED
        ) as output:
            for path in sorted((ROOT / "extension").rglob("*")):
                if (
                    not path.is_file()
                    or path.name.startswith(".")
                    or path.name == "manifest.firefox.json"
                ):
                    continue
                relative = path.relative_to(ROOT / "extension")
                if path.name == "manifest.json":
                    source = (
                        ROOT
                        / "extension"
                        / ("manifest.firefox.json" if browser == "firefox" else "manifest.json")
                    )
                    manifest = json.loads(source.read_text())
                    manifest["version"] = version
                    output.writestr("manifest.json", json.dumps(manifest, indent=2))
                else:
                    output.write(path, relative)
        print(target / f"aletheia-{browser}.zip")


if __name__ == "__main__":
    main()
