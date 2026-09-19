# Developer setup

## Status of this guide

The repository has an `uv` project for Python 3.12 and declares `make` targets for setup, checks, extension building, and packaging. Python 3.12.13, uv dependencies, Tesseract 5.5.3, `create-dmg` 1.3, and Xcode Command Line Tools were reported present on the current macOS 27 arm64 development machine. A clean-clone run of this guide is still TODO; do not treat a command below as fresh-clone verified.

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
uv sync
make setup
```

Windows has not been executed on a physical machine or runner for this build. In particular, validate how `make` is provided in the selected shell before relying on these commands; this is a TODO for the Windows CI setup.

## Browser development

Build the extension schemas/package with:

```sh
make build-extension
```

The extension source is in `extension/`. Chromium uses the fixed development extension ID `bfdjphkbgihhbonhnmjbbfhckdddonob`; Firefox uses `privacy-guardian@privacyguardian.local`. The native host name is `com.privacyguardian.host`. Register a development host with `uv run privacy-guardian --install-native-host`, then load the unpacked extension. A Chromium handshake and fixture badges are verified; full registration/reconnect/action coverage is still pending.

## Local data and credentials

The data directory defaults to `~/Library/Application Support/PrivacyGuardian` on macOS and `%APPDATA%\\PrivacyGuardian` on Windows. Override it with `PRIVACY_GUARDIAN_DATA_DIR` for a disposable development profile.

Optional OpenAI credentials are stored through the operating-system keychain only, using service `PrivacyGuardian` and account `openai_api_key`. The UI/API rejects unsupported keyring backends. Do not put keys in `.env`, `settings.toml`, or test fixtures.

## Useful commands

| Command | Declared purpose | Verification status |
|---|---|---|
| `make setup` | Sync dependencies and run setup script | Local dependency/tool presence reported; fresh clone TODO |
| `make run` | Start the console app | Desktop/UI source present; fresh clone TODO |
| `make test` | Pytest with coverage | Partial suites independently reported; full run TODO |
| `make e2e` | Playwright browser suite | TODO; browser install confirmation pending |
| `make check` | Lint, typecheck, and test | TODO |
| `make build-extension` | Generate/build extension assets | TODO |
| `make build-mac` | macOS app + DMG with bundled compatible OCR | First build/smoke/codesign/UDZO verified; stale final rebuild pending |
| `make build-win` | Intended Windows installer build | TODO; Windows runner pending |
