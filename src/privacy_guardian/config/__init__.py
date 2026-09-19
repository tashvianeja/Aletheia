from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def data_directory() -> Path:
    override = os.getenv("PRIVACY_GUARDIAN_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/PrivacyGuardian"
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "PrivacyGuardian"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "PrivacyGuardian"


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    enabled: bool = False
    model: str = "gpt-6-astra"
    policy_refinement: bool = True
    purpose_refinement: bool = True
    explanation_polishing: bool = True
    deep_check_narrative: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRIVACY_GUARDIAN_", env_nested_delimiter="__", extra="forbid"
    )
    data_dir: Path = Field(default_factory=data_directory)
    retention_days: int = Field(default=90, ge=1, le=3650)
    analysis_timeout_seconds: float = Field(default=20, ge=1, le=120)
    popup_timeout_seconds: int = Field(default=60, ge=1, le=60)
    autostart: bool = True
    onboarding_complete: bool = False
    hotkey: str = "Ctrl+Shift+P"
    log_level: str = "INFO"
    reject_optional_cookies: bool = True
    llm: LLMSettings = Field(default_factory=LLMSettings)
    allowed_extension_ids: list[str] = Field(
        default_factory=lambda: [
            "privacy-guardian@privacyguardian.local",
            "bfdjphkbgihhbonhnmjbbfhckdddonob",
        ]
    )
    clipboard_allowlist: list[str] = Field(default_factory=list)

    @field_validator("hotkey")
    @classmethod
    def valid_hotkey(cls, value: str) -> str:
        import re

        if not re.fullmatch(
            r"(?:(?:Ctrl|Control|Cmd|Alt|Option|Shift|Win|Meta)\+)+[A-Za-z0-9]", value, re.I
        ):
            raise ValueError("Use modifiers plus one letter or digit, such as Ctrl+Shift+P")
        return value

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        target = path or data_directory() / "settings.toml"
        data: dict[str, Any] = {}
        if target.exists():
            data = tomllib.loads(target.read_text(encoding="utf-8"))
        for env_key, env_value in os.environ.items():
            if not env_key.startswith("PRIVACY_GUARDIAN_"):
                continue
            keys = env_key.removeprefix("PRIVACY_GUARDIAN_").lower().split("__")
            if keys[0] not in cls.model_fields:
                continue
            target_data = data
            for part in keys[:-1]:
                nested = target_data.get(part)
                if not isinstance(nested, dict):
                    nested = {}
                    target_data[part] = nested
                target_data = nested
            try:
                import json

                parsed = json.loads(env_value)
            except ValueError:
                parsed = env_value
            target_data[keys[-1]] = parsed
        return cls(**data)

    def save(self) -> None:
        import json

        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lines: list[str] = []
        values = self.model_dump(mode="json")
        for key, value in values.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("\n[llm]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in values["llm"].items())
        path = self.data_dir / "settings.toml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)


__all__ = ["LLMSettings", "Settings", "data_directory"]
