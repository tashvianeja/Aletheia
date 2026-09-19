from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from privacy_guardian.core.events import DataCategory
from privacy_guardian.engine.explain import category_label
from privacy_guardian.engine.preferences import Preference
from privacy_guardian.ui.theme import stylesheet
from privacy_guardian.util.i18n import tr


class Dashboard(QWidget):
    def __init__(self, service: Any) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle(tr("app_name"))
        self.resize(900, 650)
        self.setStyleSheet(stylesheet())
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        history = QWidget()
        history_layout = QVBoxLayout(history)
        filters = QHBoxLayout()
        self.requester_filter = QLineEdit()
        self.requester_filter.setPlaceholderText(tr("filter"))
        self.outcome_filter = QComboBox()
        self.outcome_filter.addItems([tr("all"), "IGNORE", "INFORM", "INTERVENE"])
        filters.addWidget(self.requester_filter)
        filters.addWidget(self.outcome_filter)
        history_layout.addLayout(filters)
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(
            [tr("status"), tr("foreground"), tr("category"), tr("why")]
        )
        self.history.horizontalHeader().setStretchLastSection(True)
        history_layout.addWidget(self.history)
        self.tabs.addTab(history, tr("history"))
        preferences = QWidget()
        pref_layout = QVBoxLayout(preferences)
        self.category_controls: dict[str, QComboBox] = {}
        self.pref_table = QTableWidget(len(DataCategory) + 2, 2)
        self.pref_table.setHorizontalHeaderLabels([tr("category"), tr("preference")])
        for row, category in enumerate(DataCategory):
            self.pref_table.setItem(row, 0, QTableWidgetItem(category_label(category.value)))
            combo = QComboBox()
            for preference in Preference:
                combo.addItem(tr(preference.value), preference.value)
            combo.setCurrentIndex(
                combo.findData(service.core.preferences.for_category(category).value)
            )
            self.pref_table.setCellWidget(row, 1, combo)
            self.category_controls[category.value] = combo
        for extra_row, category_name in enumerate(
            ("analytics", "advertising"), start=len(DataCategory)
        ):
            self.pref_table.setItem(extra_row, 0, QTableWidgetItem(category_name))
            combo = QComboBox()
            for preference in Preference:
                combo.addItem(tr(preference.value), preference.value)
            combo.setCurrentIndex(
                combo.findData(
                    service.core.preferences.categories.get(category_name, Preference.REJECT).value
                )
            )
            self.pref_table.setCellWidget(extra_row, 1, combo)
            self.category_controls[category_name] = combo
        pref_layout.addWidget(self.pref_table)
        button_row = QHBoxLayout()
        for key, callback in (
            ("save", self.save_preferences),
            ("export", self.export_preferences),
            ("import", self.import_preferences),
            ("reset", self.reset_preferences),
        ):
            button = QPushButton(tr(key))
            button.clicked.connect(callback)
            button_row.addWidget(button)
        pref_layout.addLayout(button_row)
        self.tabs.addTab(preferences, tr("preferences"))
        settings = QWidget()
        form = QFormLayout(settings)
        self.retention = QSpinBox()
        self.retention.setRange(1, 3650)
        self.retention.setValue(service.settings.retention_days)
        self.autostart = QCheckBox()
        self.autostart.setChecked(service.settings.autostart)
        self.llm_enabled = QCheckBox()
        self.llm_enabled.setChecked(service.settings.llm.enabled)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(service.settings.llm.model)
        self.hotkey = QLineEdit(service.settings.hotkey)
        self.theme = QComboBox()
        self.theme.addItems([tr("system"), tr("light"), tr("dark")])
        for key, widget in (
            ("retention", self.retention),
            ("autostart", self.autostart),
            ("llm_enable", self.llm_enabled),
            ("api_key", self.api_key),
            ("llm_model", self.model),
            ("hotkey", self.hotkey),
            ("theme", self.theme),
        ):
            widget.setAccessibleName(tr(key))
            form.addRow(tr(key), widget)
        save = QPushButton(tr("save"))
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        self.llm_toggles: dict[str, QCheckBox] = {}
        for key in (
            "policy_refinement",
            "purpose_refinement",
            "explanation_polishing",
            "deep_check_narrative",
        ):
            toggle = QCheckBox(tr(key))
            toggle.setChecked(getattr(service.settings.llm, key))
            form.addRow(toggle)
            self.llm_toggles[key] = toggle
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(service.settings.log_level)
        form.addRow(tr("log_level"), self.log_level)
        self.reject_optional = QCheckBox(tr("reject_optional"))
        self.reject_optional.setChecked(service.settings.reject_optional_cookies)
        form.addRow(self.reject_optional)
        self.tabs.addTab(settings, tr("settings"))
        memory = QWidget()
        memory_layout = QVBoxLayout(memory)
        self.memory = QTextEdit()
        self.memory.setReadOnly(False)
        memory_layout.addWidget(self.memory)
        memory_save = QPushButton(tr("save_memory"))
        memory_save.clicked.connect(self.save_memory)
        memory_layout.addWidget(memory_save)
        self.profile_key = QLineEdit()
        self.profile_key.setPlaceholderText(tr("profile_key"))
        memory_layout.addWidget(self.profile_key)
        profile_view = QPushButton(tr("view_profile"))
        profile_view.clicked.connect(self.view_profile)
        memory_layout.addWidget(profile_view)
        self.profile_detail = QTextEdit()
        self.profile_detail.setReadOnly(True)
        memory_layout.addWidget(self.profile_detail)
        self.tabs.addTab(memory, tr("site_memory"))
        diag = QWidget()
        diag_layout = QVBoxLayout(diag)
        self.diagnostic_text = QTextEdit()
        self.diagnostic_text.setReadOnly(True)
        diag_layout.addWidget(self.diagnostic_text)
        support = QPushButton(tr("support"))
        support.clicked.connect(self.export_support)
        diag_layout.addWidget(support)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAccessibleName(tr("logs"))
        diag_layout.addWidget(self.log_view)
        self.tabs.addTab(diag, tr("diagnostics"))
        self.history.cellDoubleClicked.connect(self.show_event_detail)
        self.requester_filter.textChanged.connect(self.refresh)
        self.outcome_filter.currentIndexChanged.connect(self.refresh)
        self.theme.currentIndexChanged.connect(
            lambda index: self.setStyleSheet(stylesheet(["system", "light", "dark"][index]))
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def refresh(self) -> None:
        rows = self.service.core.store.history(
            requester=self.requester_filter.text() or None,
            outcome=self.outcome_filter.currentText()
            if self.outcome_filter.currentIndex()
            else None,
        )
        self.history.setRowCount(len(rows))
        for index, row in enumerate(rows):
            event, decision = row["event"], row["decision"] or {}
            for col, value in enumerate(
                (
                    decision.get("outcome", ""),
                    event["requester"].get("display_name", ""),
                    ", ".join(category_label(category) for category in event["data_categories"]),
                    decision.get("explanation", ""),
                )
            ):
                self.history.setItem(index, col, QTableWidgetItem(str(value)))
        self.memory.setPlainText(json.dumps(self.service.core.store.export_preferences(), indent=2))
        self.diagnostic_text.setPlainText(json.dumps(self.service.diagnostics(), indent=2))
        log_file = self.service.settings.data_dir / "logs/guardian.log"
        if log_file.exists():
            from privacy_guardian.util.privacy import redact_text

            self.log_view.setPlainText(
                redact_text(log_file.read_text(encoding="utf-8", errors="replace")[-20000:])
            )

    def save_preferences(self) -> None:
        self.service.core.preferences.categories.update(
            {
                category: Preference(combo.currentData())
                for category, combo in self.category_controls.items()
            }
        )
        self.service.core.store.set_preference(
            "user", self.service.core.preferences.model_dump(mode="json")
        )

    def export_preferences(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("export"), "preferences.json", "JSON (*.json)"
        )
        if filename:
            Path(filename).write_text(
                json.dumps(self.service.core.store.export_preferences(), indent=2), encoding="utf-8"
            )

    def _load_preferences(self, payload: dict[str, Any]) -> None:
        from privacy_guardian.engine.preferences import LearnedRules, UserPreferences

        preferences = UserPreferences.model_validate(payload.get("preferences", {}).get("user", {}))
        learned = LearnedRules.model_validate(payload.get("learned_rules", {}).get("user", {}))
        self.service.core.store.import_preferences(payload)
        self.service.core.preferences = preferences
        self.service.core.learned_rules = learned
        self.service.settings.reject_optional_cookies = preferences.reject_optional_cookies
        self.service.settings.clipboard_allowlist = preferences.clipboard_allowlist
        self.service.settings.save()
        if getattr(self.service, "clipboard", None):
            self.service.clipboard.allowlist = preferences.clipboard_allowlist
        for category, combo in self.category_controls.items():
            preference = preferences.categories.get(
                category, preferences.categories.get(category.split(".")[0], Preference.ASK)
            )
            combo.setCurrentIndex(combo.findData(preference.value))
        self.refresh()

    def import_preferences(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, tr("import"), "", "JSON (*.json)")
        if filename:
            try:
                self._load_preferences(json.loads(Path(filename).read_text()))
            except (OSError, ValueError, TypeError, AttributeError):
                QMessageBox.warning(self, tr("app_name"), tr("invalid_preferences"))

    def save_memory(self) -> None:
        try:
            self._load_preferences(json.loads(self.memory.toPlainText()))
        except (OSError, ValueError, TypeError, AttributeError):
            QMessageBox.warning(self, tr("app_name"), tr("invalid_preferences"))

    def view_profile(self) -> None:
        key = self.profile_key.text().strip()
        profile = self.service.core.store.get_profile(
            "site", key
        ) or self.service.core.store.get_profile("app", key)
        self.profile_detail.setPlainText(json.dumps(profile or {}, indent=2))

    def show_event_detail(self, row: int, _column: int) -> None:
        records = self.service.core.store.history(
            requester=self.requester_filter.text() or None,
            outcome=self.outcome_filter.currentText()
            if self.outcome_filter.currentIndex()
            else None,
        )
        if row < len(records):
            self.profile_detail.setPlainText(json.dumps(records[row], indent=2))
            self.tabs.setCurrentIndex(3)

    def reset_preferences(self) -> None:
        self.service.core.learned_rules.reset()
        self.service.core.store.set_learned_rule(
            "user", self.service.core.learned_rules.model_dump(mode="json")
        )
        self.refresh()

    def save_settings(self) -> None:
        from privacy_guardian.config import Settings

        try:
            Settings.valid_hotkey(self.hotkey.text())
            if self.api_key.text():
                from privacy_guardian.llm.client import set_api_key

                set_api_key(self.api_key.text())
                self.api_key.clear()
        except Exception:
            QMessageBox.warning(self, tr("app_name"), tr("settings_failed"))
            return
        settings = self.service.settings
        settings.retention_days = self.retention.value()
        settings.autostart = self.autostart.isChecked()
        settings.llm.enabled = self.llm_enabled.isChecked()
        settings.llm.model = self.model.text()
        settings.hotkey = self.hotkey.text()
        settings.log_level = self.log_level.currentText()
        settings.reject_optional_cookies = self.reject_optional.isChecked()
        self.service.core.preferences.reject_optional_cookies = settings.reject_optional_cookies
        self.service.core.store.set_preference(
            "user", self.service.core.preferences.model_dump(mode="json")
        )
        for key, toggle in self.llm_toggles.items():
            setattr(settings.llm, key, toggle.isChecked())
        self.service.hotkey.stop()
        from privacy_guardian.sensors.hotkey import GlobalHotkey

        self.service.hotkey = GlobalHotkey(
            settings.hotkey, self.service.bridge.deep_check_requested.emit
        )
        self.service.hotkey.start()
        settings.save()
        if self.service.core.adapter:
            self.service.core.adapter.set_autostart(settings.autostart)
        self.service.core.store.purge(settings.retention_days)

    def export_support(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("support"), "privacy-guardian-support.json", "JSON (*.json)"
        )
        if filename:
            # Counts/configuration status only: no URLs, event prose, paths or user content.
            Path(filename).write_text(
                json.dumps(self.service.diagnostics(), indent=2), encoding="utf-8"
            )
