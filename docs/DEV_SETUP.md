# Developer setup

## Status of this guide

The repository has an `uv` project for Python 3.12 and declares `make` targets for setup, checks, extension building, and packaging. Python 3.12.13, uv dependencies, Tesseract 5.5.3, `create-dmg` 1.3, and Xcode Command Line Tools were reported present on the current macOS 27 arm64 development machine. Final fresh-clone proof was recorded on 2026-09-19 at `/private/tmp/pg-fresh-s12.bpTXSL/Privacy-Guardian`, source `d3390ba`; the current app/DMG lifecycle passed.

## macOS

Install the tools that the declared development and packaging paths expect:

```sh
xcode-select --install
brew install uv tesseract create-dmg cmake autoconf automake libtool pkg-config
uv sync
make setup
```

`uv sync` also resolves the direct `en_core_web_sm` spaCy-model wheel dependency. Internet access to its GitHub release is required during resolution. Start the app with `make run`; run code checks with `make lint`, `make typecheck`, `make test`, and `make check`.

Tesseract is used only when document extraction needs OCR. Confirm the executable is on `PATH` with `tesseract --version`. The macOS package builds a separate compatible static Tesseract 5.5.3, Leptonica 1.87, and libpng 1.6.58 bundle targeting macOS 13 via `scripts/build_ocr.py`; this needs Xcode compiler tools, CMake, Autotools, libtool, pkg-config, and source downloads. Additional OCR languages are host-installed Tesseract data; the package target currently includes English and OSD.

## Windows

In PowerShell, install the declared tooling, then run the same source commands:

```powershell
winget install --id AstralSoftware.UV -e
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id JRSoftware.InnoSetup -e
winget install --id OpenJS.NodeJS.LTS -e
uv sync
uv run python scripts/setup.py
```

Windows has not been executed on a physical machine or runner for this build. In particular, validate how `make` is provided in the selected shell before relying on these commands; this is a TODO for the Windows CI setup.

## Browser development

Build the extension schemas/package with:

```sh
make build-extension
```

The extension source is in `extension/`. Chromium uses the fixed development extension ID `bfdjphkbgihhbonhnmjbbfhckdddonob`; Firefox uses `privacy-guardian@privacyguardian.local`. The native host name is `com.privacyguardian.host`. Register a development host with `uv run privacy-guardian --install-native-host`, then load the unpacked extension. Chromium/Firefox handshakes and browser recovery are verified; final browser totals are pending.

## Local data and credentials

The data directory defaults to `~/Library/Application Support/PrivacyGuardian` on macOS and `%APPDATA%\\PrivacyGuardian` on Windows. Override it with `PRIVACY_GUARDIAN_DATA_DIR` for a disposable development profile.

Optional OpenAI credentials are stored through the operating-system keychain only, using service `PrivacyGuardian` and account `openai_api_key`. The UI/API rejects unsupported keyring backends. Do not put keys in `.env`, `settings.toml`, or test fixtures.

## Fresh-clone verification procedure

This completed at `d3390ba`: setup, diagnose/smoke, source macOS build, extension archives, packaged install/onboarding/native handshake/PNG and native-JPEG OCR, uninstall/restore, and the 339-Mach-O macOS-13 audit passed. `make check` reported 307 passed and 5 skipped, with two first-phase performance cases deselected; coverage was 85.71% scoped and 75.42% overall.

```sh
git clone https://github.com/tashvianeja/Privacy-Guardian.git
cd Privacy-Guardian
git checkout develop
xcode-select --install
brew install uv tesseract create-dmg cmake autoconf automake libtool pkg-config
uv sync
make setup
export PRIVACY_GUARDIAN_DATA_DIR="$(mktemp -d)"
uv run privacy-guardian --diagnose
QT_QPA_PLATFORM=offscreen uv run privacy-guardian --smoke-test
make lint
make typecheck
make test
make build-extension
make e2e
make build-mac
make uninstall-mac
```

The worker must record command exit codes, test/coverage totals, generated extension/archive and app/DMG paths, and whether the `make e2e` and packaging stages completed. Run the browser E2E only after installing Playwright’s required browser under the environment’s documented process. Do not configure an OpenAI key: the default path must remain offline. A corresponding Windows fresh-clone/installer procedure is pending a green Windows runner.

## Useful commands

| Command | Declared purpose | Verification status |
|---|---|---|
| `make setup` | Sync dependencies and run setup script | Fresh clone passed |
| `make run` | Start the console app | Fresh clone diagnose/smoke passed |
| `make test` | Pytest with coverage | Fresh clone passed within final check |
| `make e2e` | Playwright browser suite | Fresh clone runtime suite passed; Windows browser runtime remains pending |
| `make check` | Lint, typecheck, and test | Fresh clone passed: 307 passed, 5 skipped |
| `make build-extension` | Generate/build extension assets | Fresh clone passed |
| `make build-mac` | macOS app + DMG with bundled compatible OCR | Current lifecycle passed |
| `make build-win` | Intended Windows installer build | TODO; Windows runner pending |
