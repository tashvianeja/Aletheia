from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from aletheia.app import diagnose
from aletheia.config import Settings
from aletheia.storage import Store
from aletheia.util.instance import InstanceLock


def test_diagnose_reports_counts_and_status_without_database_content(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    store = Store(tmp_path / "guardian.sqlite3")
    store.set_preference("synthetic-user-secret", {"email": "person@example.test"})
    store.close()
    monkeypatch.setattr(
        "aletheia.sensors.platform.create_adapter",
        lambda: type("Adapter", (), {"permissions_status": lambda self: {"monitor": True}})(),
    )
    monkeypatch.setattr(
        "aletheia.util.installation.manifest_locations",
        lambda: {"chrome": tmp_path / "native-host"},
    )

    result = diagnose(settings)

    assert result["database_present"] is True
    assert result["database_counts"]["preferences"] == 1
    assert result["permissions"] == {"monitor": True}
    assert "person@example.test" not in json.dumps(result)
    assert "synthetic-user-secret" not in json.dumps(result)


def test_diagnose_cli_is_machine_readable(tmp_path: Path) -> None:
    environment = {**os.environ, "ALETHEIA_DATA_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "aletheia", "--diagnose"],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["database_present"] is False
    assert payload["platform"] == sys.platform


def test_qt_smoke_lifecycle_creates_ready_marker_and_exits(tmp_path: Path) -> None:
    environment = {
        **os.environ,
        "ALETHEIA_DATA_DIR": str(tmp_path),
        "QT_QPA_PLATFORM": "offscreen",
    }
    result = subprocess.run(
        [sys.executable, "-m", "aletheia", "--smoke-test", "--no-autostart"],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tray-ready").read_text() == "ready"
    lock = InstanceLock(tmp_path / "guardian.lock")
    assert lock.acquire(), "smoke shutdown must release the single-instance lock"
    lock.release()
