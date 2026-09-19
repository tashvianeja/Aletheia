from __future__ import annotations

import sys
from pathlib import Path

from privacy_guardian.config import Settings


def test_nested_environment_override_preserves_file_llm_values(tmp_path: Path, monkeypatch) -> None:
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        """
retention_days = 45

[llm]
enabled = false
model = "custom-offline-evaluator"
policy_refinement = false
purpose_refinement = false
explanation_polishing = true
deep_check_narrative = false
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRIVACY_GUARDIAN_LLM__ENABLED", "true")

    loaded = Settings.load(settings_file)

    assert loaded.llm.enabled is True
    assert loaded.llm.model == "custom-offline-evaluator"
    assert loaded.llm.policy_refinement is False
    assert loaded.llm.purpose_refinement is False
    assert loaded.llm.deep_check_narrative is False
    assert loaded.retention_days == 45


def test_settings_save_and_load_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PRIVACY_GUARDIAN_LLM__ENABLED", raising=False)
    original = Settings(
        data_dir=tmp_path,
        retention_days=37,
        hotkey="Meta+Alt+P",
        clipboard_allowlist=["com.synthetic.writer"],
        llm={"enabled": False, "model": "offline-only", "policy_refinement": False},
    )
    original.save()
    loaded = Settings.load(tmp_path / "settings.toml")
    assert loaded.model_dump(mode="json") == original.model_dump(mode="json")


def test_settings_file_has_private_permissions(tmp_path: Path) -> None:
    Settings(data_dir=tmp_path).save()
    path = tmp_path / "settings.toml"
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
        return

    import ntsecuritycon
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 0x0008)
    try:
        current_user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    descriptor = win32security.GetFileSecurity(
        str(path),
        win32security.DACL_SECURITY_INFORMATION,
    )
    dacl = descriptor.GetSecurityDescriptorDacl()
    control, _revision = descriptor.GetSecurityDescriptorControl()

    assert dacl is not None and dacl.GetAceCount() == 1
    header, access_mask, sid = dacl.GetAce(0)
    assert header[0] == win32security.ACCESS_ALLOWED_ACE_TYPE
    assert header[1] == 0
    assert win32security.EqualSid(sid, current_user)
    assert access_mask & ntsecuritycon.FILE_ALL_ACCESS == ntsecuritycon.FILE_ALL_ACCESS
    assert control & 0x1000  # SE_DACL_PROTECTED
