#!/usr/bin/env bash
#
# Build Privacy Guardian from source on macOS and install it for the current user.
#
#   ./install.sh                 build, install to /Applications, register the browser bridge
#   ./install.sh --skip-ocr      much faster build; scanned images are reported as unchecked
#   ./install.sh --no-autostart  do not start Privacy Guardian when you log in
#   ./install.sh --uninstall     remove the app, the browser bridge and the local database
#
# Nothing is uploaded and no account is needed. Everything the app analyses stays on
# this machine.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="PrivacyGuardian.app"
APP_DEST="/Applications/${APP_NAME}"
SKIP_OCR=0
AUTOSTART=1
UNINSTALL=0

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
info() { printf '  %s\n' "$1"; }
warn() { printf '\033[33m  %s\033[0m\n' "$1"; }
die()  { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

for argument in "$@"; do
  case "$argument" in
    --skip-ocr) SKIP_OCR=1 ;;
    --no-autostart) AUTOSTART=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: ${argument} (try --help)" ;;
  esac
done

# ---------------------------------------------------------------- uninstall --
if [[ "${UNINSTALL}" == "1" ]]; then
  bold "Removing Privacy Guardian"
  if [[ -x "${APP_DEST}/Contents/MacOS/PrivacyGuardian" ]]; then
    "${APP_DEST}/Contents/MacOS/PrivacyGuardian" --uninstall || true
  elif [[ -x "${ROOT}/.venv/bin/privacy-guardian" ]]; then
    "${ROOT}/.venv/bin/privacy-guardian" --uninstall || true
  fi
  pkill -f "${APP_DEST}/Contents/MacOS/PrivacyGuardian" 2>/dev/null || true
  rm -rf "${APP_DEST}"
  info "Removed ${APP_DEST}, the browser bridge and the local history database."
  info "Remove the extension yourself from your browser's extensions page."
  exit 0
fi

# ------------------------------------------------------------ prerequisites --
bold "Checking prerequisites"
[[ "$(uname -s)" == "Darwin" ]] || die "this installer is for macOS; see docs/DEV_SETUP.md for Windows"

MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "${MAJOR}" -ge 13 ]] || die "macOS 13 (Ventura) or newer is required; found $(sw_vers -productVersion)"
info "macOS $(sw_vers -productVersion) on $(uname -m)"

xcode-select -p >/dev/null 2>&1 || die "Xcode command line tools are missing. Run: xcode-select --install"

if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv (Python project manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  [[ -f "${HOME}/.local/bin/env" ]] && source "${HOME}/.local/bin/env"
  export PATH="${HOME}/.local/bin:${PATH}"
fi
command -v uv >/dev/null 2>&1 || die "uv is still not on PATH. Open a new terminal and rerun."
info "uv $(uv --version | awk '{print $2}')"

if [[ "${SKIP_OCR}" == "0" ]] && ! command -v cmake >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    info "Installing cmake (needed to build the bundled OCR engine)"
    brew install cmake
  else
    warn "cmake is missing and Homebrew is not installed, so OCR cannot be built."
    warn "Continuing without OCR. Scanned images will be reported as unchecked."
    warn "To include OCR: install Homebrew, then rerun this script."
    SKIP_OCR=1
  fi
fi

# ------------------------------------------------------------------- build ---
cd "${ROOT}"
bold "Installing Python dependencies"
# PyInstaller lives in the dev group, so the build needs the full dependency set.
uv sync
info "Dependencies ready in ${ROOT}/.venv"

bold "Building the browser extension"
uv run python scripts/generate_schema.py
uv run python scripts/build_extension.py >/dev/null
info "dist/privacy-guardian-chromium.zip"
info "dist/privacy-guardian-firefox.zip"

bold "Building ${APP_NAME}"
if [[ "${SKIP_OCR}" == "1" ]]; then
  warn "Building without OCR (--skip-ocr). Scanned images are reported as unchecked."
else
  info "Compiling the bundled OCR engine. First run takes several minutes."
fi
PRIVACY_GUARDIAN_SKIP_OCR="${SKIP_OCR}" uv run python scripts/build.py mac
[[ -d "${ROOT}/dist/${APP_NAME}" ]] || die "the build did not produce dist/${APP_NAME}"

# ----------------------------------------------------------------- install ---
bold "Installing to /Applications"
if pgrep -f "${APP_DEST}/Contents/MacOS/PrivacyGuardian" >/dev/null 2>&1; then
  info "Stopping the running copy"
  pkill -f "${APP_DEST}/Contents/MacOS/PrivacyGuardian" || true
  sleep 1
fi
rm -rf "${APP_DEST}"
# ditto rather than cp: a cloud-synced checkout adds extended attributes that break the
# code signature, and --noextattr leaves them behind.
ditto --norsrc --noextattr "${ROOT}/dist/${APP_NAME}" "${APP_DEST}"
# The build signs ad hoc, so clear the quarantine flag Gatekeeper would otherwise act on.
xattr -dr com.apple.quarantine "${APP_DEST}" 2>/dev/null || true
if codesign --verify --deep --strict "${APP_DEST}" 2>/dev/null; then
  info "Installed ${APP_DEST} (signature verified)"
else
  warn "Installed ${APP_DEST}, but its signature did not verify."
  warn "The app will still run; rebuild from a checkout outside iCloud Drive for a clean signature."
fi

bold "Registering the browser bridge"
REGISTER_ARGS=(--install-native-host)
[[ "${AUTOSTART}" == "0" ]] && REGISTER_ARGS+=(--no-autostart)
"${APP_DEST}/Contents/MacOS/PrivacyGuardian" "${REGISTER_ARGS[@]}"
for browser in Chrome "Microsoft Edge" "Brave-Browser" Firefox; do
  case "${browser}" in
    Chrome) path="${HOME}/Library/Application Support/Google/Chrome/NativeMessagingHosts" ;;
    "Microsoft Edge") path="${HOME}/Library/Application Support/Microsoft Edge/NativeMessagingHosts" ;;
    "Brave-Browser") path="${HOME}/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts" ;;
    Firefox) path="${HOME}/Library/Application Support/Mozilla/NativeMessagingHosts" ;;
  esac
  [[ -f "${path}/com.privacyguardian.host.json" ]] && info "Registered for ${browser}"
done

bold "Starting Privacy Guardian"
open -a "${APP_DEST}"
sleep 2
if "${APP_DEST}/Contents/MacOS/PrivacyGuardian" --diagnose >/dev/null 2>&1; then
  info "The background service answered a diagnostic query."
else
  warn "Could not query the service yet. It may still be starting."
fi

# -------------------------------------------------------------- next steps ---
cat <<NEXT

$(bold "Privacy Guardian is installed.")

  A padlock now sits in your menu bar with a green dot beside it. It stays quiet
  until something is worth telling you about.

$(bold "Finish in the setup window")

  Setup has opened on screen. It walks through the browser extension and the
  optional desktop permissions, and it will not move past the extension step
  until a browser has actually connected.

  Chrome, Edge or Brave
    Open the extensions page, turn on Developer mode, choose "Load unpacked"
    and select:
      ${ROOT}/extension

  Firefox
    Open about:debugging#/runtime/this-firefox, choose "Load Temporary Add-on"
    and select:
      ${ROOT}/extension/manifest.firefox.json

  Packaged copies are in ${ROOT}/dist if you would rather install from a zip.
  Reopen setup any time from the menu bar under "Set up Privacy Guardian".

$(bold "Then try it")

  Click the menu bar padlock and choose "Run thorough check", or drop a document
  containing personal details into any upload box.

  Remove it later with: ./install.sh --uninstall

NEXT
