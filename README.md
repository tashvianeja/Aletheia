# Privacy Guardian

Privacy Guardian is a local-first background app for macOS and Windows that helps people make privacy decisions at the moment a site or application asks for data or access. It examines supported browser and desktop signals, applies a shared decision engine, and stays quiet when the event does not need attention.

The app can classify sensitive categories in documents and forms, inspect consent and tracking signals, and relate a request to the apparent purpose of a site or application. It presents one of three outcomes: **Ignore**, **Inform**, or **Intervene**, with an explanation and an action where one is available.

This repository is an in-progress initial build. The core and analysis test suites have evidence recorded in `docs/PLAN.md`; a complete release build, browser end-to-end run, real Windows run, and fresh-clone verification are still pending. Treat the installation and packaging sections below as build instructions, not a claim that release artifacts exist today.

## Feature matrix

| Capability | Browser extension | macOS desktop | Windows desktop | Offline | Optional LLM-assisted |
|---|---:|---:|---:|---:|---:|
| Document category detection and redaction | Planned bridge | — | — | Yes | No |
| Form field semantics | Planned bridge | — | — | Yes | No |
| Policy and terms clause extraction | Planned bridge | — | — | Yes | Policy refinement only |
| Consent-banner analysis | Planned bridge | — | — | Yes | No |
| Tracker and fingerprinting signal analysis | Planned bridge | — | — | Yes | No |
| Permission, startup, and broad-access observation | — | Implemented adapter; real-run verification pending | Implemented adapter; Windows verification pending | Yes | No |
| Clipboard and screen-access signals | — | Implemented adapter; verification pending | Implemented adapter; Windows verification pending | Yes | No |
| Decision engine, preferences, and local history | Service API | Service API | Service API | Yes | Explanation polish only |
| Deep Check | Service API | UI present; integration verification pending | UI present; integration verification pending | Yes | Narrative only |

“Planned bridge” means the extension/service end-to-end path has not yet been independently verified. A dash means that the capability is outside that surface.

## Screenshots

Screenshot artifacts are not yet generated. When the UI and browser test runs produce them, they will be referenced from `docs/img/`. Until then, see the popup and dashboard source in `src/privacy_guardian/ui/`; no image in this README should be read as evidence of a tested flow.

## Requirements

Supported targets are macOS 13 or later (Apple Silicon or Intel) and Windows 10 21H2 or later / Windows 11 x64. This build has been developed on macOS 27 arm64; real Windows execution remains pending CI.

Source work requires Python 3.12 (the project constrains Python to `>=3.12,<3.13`), [uv](https://docs.astral.sh/uv/), and Tesseract for OCR. Browser integration targets Chrome, Edge, Brave, and Firefox through Manifest V3-style native messaging; installation and an end-to-end browser handshake are pending verification.

On macOS, Homebrew, Xcode Command Line Tools, and `create-dmg` are needed for the intended packaging path. On Windows, use winget for prerequisites and install Inno Setup before attempting an installer build. The repository does not currently contain published installers.

## Install from release

There are no verified release artifacts for version 0.1.0 yet. Once a signed macOS `.dmg` or Windows setup executable has been built and uploaded, the intended steps are:

1. Download the artifact from the project’s GitHub Releases page and verify its release notes/checksum when supplied.
2. On macOS, open the `.dmg`, move `PrivacyGuardian.app` to Applications, then open it. An ad-hoc-signed build may require Control-click → **Open** at first launch.
3. On Windows, run `PrivacyGuardian-Setup-<version>.exe` and accept the installer’s visible autostart option.
4. Install the matching browser extension once its signed/published package is available. Development loading is described below.

macOS monitoring may require Full Disk Access and Accessibility permission. Use the in-app settings action to open the relevant pane; instructions with verified screenshots are pending. These permissions are not a guarantee that every OS signal can be observed; see [Platform limitations](#platform-limitations).

## Build from source

These are the repository’s declared commands. They have **not** yet been verified by a fresh-clone worker, and the packaging helper scripts/artifacts are still pending; use the development path first.

macOS:

```sh
xcode-select --install
brew install uv tesseract create-dmg
uv sync
make setup
make run
make build-extension
make build-mac
```

Windows (PowerShell):

```powershell
winget install --id AstralSoftware.UV -e
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id JRSoftware.InnoSetup -e
uv sync
make setup
make run
make build-extension
make build-win
```

`make build-mac` and `make build-win` name intended output paths under `dist/`; do not expect them to work until the corresponding packaging scripts are present and CI/platform smoke tests pass. For non-English OCR, install the appropriate Tesseract language data in the host operating system; bundling language data for installers is not yet verified.

## Run in development

Start the desktop process with:

```sh
make run
```

The console entry point is `privacy-guardian`; the native host entry point is `privacy-guardian-host`. The intended diagnostic command is `privacy-guardian --diagnose`, but that CLI behavior is not independently verified yet.

After `make build-extension`, load the unpacked output in the target browser’s developer-extension page and configure its native-messaging host registration. Those extension package and registration instructions will be added when the bridge files land; no browser/service reconnect claim has been verified. Runtime data defaults to `~/Library/Application Support/PrivacyGuardian` on macOS, `%APPDATA%\\PrivacyGuardian` on Windows, and `$XDG_DATA_HOME/PrivacyGuardian` on other systems. Logs are configured below that data directory.

## Testing

Run the declared checks with:

```sh
make test
make e2e
make lint
make typecheck
make check
```

The known independently reported baseline is 72 analysis/engine tests passing in 2.05 seconds, with strict mypy clean for 27 files and Ruff clean at commit `bb753bf`. The broader reported test state was 107 passing and one failing redaction-context test; that failure is being fixed. `make check`, Playwright browser tests, platform tests, coverage targets, CI, and fresh-clone commands remain unverified. Use `-m macos`, `-m windows`, `-m e2e`, `-m perf`, and `-m llm` only in an environment that supports those markers; real LLM tests require an explicitly configured keychain key.

## Configuration

Settings are loaded from `settings.toml` in the data directory, then overridden by environment variables beginning with `PRIVACY_GUARDIAN_`. Nested keys use a double underscore. Values are parsed as JSON when possible, so booleans must be `true`/`false`, lists must be JSON arrays, and paths should be JSON strings.

| TOML key | Environment variable | Default | Meaning |
|---|---|---|---|
| `data_dir` | `PRIVACY_GUARDIAN_DATA_DIR` | OS-specific data directory | Local data, settings, token, logs, and SQLite location. |
| `retention_days` | `PRIVACY_GUARDIAN_RETENTION_DAYS` | `90` | Retention period, 1–3650 days. |
| `analysis_timeout_seconds` | `PRIVACY_GUARDIAN_ANALYSIS_TIMEOUT_SECONDS` | `20` | Per-analysis deadline, 1–120 seconds. |
| `popup_timeout_seconds` | `PRIVACY_GUARDIAN_POPUP_TIMEOUT_SECONDS` | `60` | Popup wait/timeout, 1–60 seconds. |
| `autostart` | `PRIVACY_GUARDIAN_AUTOSTART` | `true` | Whether the app should configure startup behavior. |
| `onboarding_complete` | `PRIVACY_GUARDIAN_ONBOARDING_COMPLETE` | `false` | Whether onboarding has been completed. |
| `hotkey` | `PRIVACY_GUARDIAN_HOTKEY` | `"Ctrl+Shift+P"` | Configured hotkey text. |
| `log_level` | `PRIVACY_GUARDIAN_LOG_LEVEL` | `"INFO"` | Application logging level. |
| `reject_optional_cookies` | `PRIVACY_GUARDIAN_REJECT_OPTIONAL_COOKIES` | `true` | Preference for optional-cookie handling. |
| `allowed_extension_ids` | `PRIVACY_GUARDIAN_ALLOWED_EXTENSION_IDS` | `["privacy-guardian@privacyguardian.local"]` | Native-host caller allowlist. |
| `clipboard_allowlist` | `PRIVACY_GUARDIAN_CLIPBOARD_ALLOWLIST` | `[]` | Requester keys permitted to read clipboard without an intervention. |
| `llm.enabled` | `PRIVACY_GUARDIAN_LLM__ENABLED` | `false` | Enables optional cloud assistance. |
| `llm.model` | `PRIVACY_GUARDIAN_LLM__MODEL` | `"gpt-6-astra"` | Model identifier currently supplied by the code. Availability has not been independently verified. |
| `llm.policy_refinement` | `PRIVACY_GUARDIAN_LLM__POLICY_REFINEMENT` | `true` | Allows optional public-policy refinement. |
| `llm.purpose_refinement` | `PRIVACY_GUARDIAN_LLM__PURPOSE_REFINEMENT` | `true` | Allows optional purpose refinement. |
| `llm.explanation_polishing` | `PRIVACY_GUARDIAN_LLM__EXPLANATION_POLISHING` | `true` | Allows optional category-level explanation polish. |
| `llm.deep_check_narrative` | `PRIVACY_GUARDIAN_LLM__DEEP_CHECK_NARRATIVE` | `true` | Allows optional Deep Check narrative generation. |

Example:

```toml
retention_days = 30
reject_optional_cookies = true

[llm]
enabled = false
model = "gpt-6-astra"
policy_refinement = true
purpose_refinement = true
explanation_polishing = true
deep_check_narrative = true
```

Do not place API keys in `settings.toml` or environment variables. When LLM assistance is enabled, the UI/client stores the key in the operating-system keychain under service `PrivacyGuardian`, account `openai_api_key`; unsupported keyring backends are rejected.

## Architecture overview

The service routes typed `PrivacyEvent` objects from platform or browser sensors through local analysis and the decision engine, then records redacted projections in SQLite and emits UI decisions. Native messaging uses length-prefixed JSON and an authenticated local channel. Read [Architecture](docs/ARCHITECTURE.md), [the decision engine](docs/DECISION_ENGINE.md), and [detector scope](docs/DETECTORS.md) for the implemented contracts.

## Privacy statement

The implemented analysis worker returns opaque payload handles plus category findings. Raw file/form values are intended to remain in worker memory, while the transport may carry bytes only for the active upload and discards them after use. The storage contract excludes raw payload references, field labels/names, file names, URL query strings, and raw extracted text.

Privacy Guardian has no telemetry in its declared design. Network use is limited to optional OpenAI API calls when enabled and a user-initiated policy fetch path when browser text is unavailable. Cloud assistance is disabled by default, sanitizes every outbound string, replaces detected values with category tokens, and rejects validated identifiers that survive sanitization. See [LLM usage](docs/LLM_USAGE.md) and [Threat model](docs/THREAT_MODEL.md).

## Platform limitations

Read [Platform limitations](docs/PLATFORM_LIMITATIONS.md) before relying on a signal for security or compliance decisions. Real macOS adapter verification, real Windows execution, browser extension/service end-to-end tests, installer smoke tests, and CI are pending. The tool gives privacy guidance; it cannot guarantee interception of every application, browser, permission change, or network transfer.

## Troubleshooting

If OCR is unavailable, run `tesseract --version`, install Tesseract with the platform command above, and restart the app. If native messaging cannot find the host, rebuild the extension, confirm the browser-specific host registration and allowed extension ID, then inspect the data-directory logs. Those integration steps are not yet independently verified.

If macOS events are missing, grant the requested Full Disk Access or Accessibility permission through System Settings, then restart the monitor. If an extension disconnects, restart the browser and the app; reconnect behavior is a pending resilience test. If `uv sync` fails on the spaCy model dependency, ensure GitHub access is available because the current package declaration uses the model wheel’s direct GitHub URL.

## Uninstall

Uninstallers and native-host deregistration are not yet built or smoke-tested. The declared macOS target is:

```sh
make uninstall-mac
```

Do not manually delete a data directory if you need its local preferences or event history. Once verified installers are available, use the operating-system uninstaller first; final removal paths and registration cleanup evidence are tracked in `docs/PLAN.md`.

### License

MIT. See [LICENSE](LICENSE).
