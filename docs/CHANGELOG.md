# Changelog

All notable changes will be documented here. This project has not produced a verified release artifact.

## [Unreleased]

### Added

- Typed privacy events, category-only findings, decision engine, local SQLite storage contract, and authenticated IPC contracts.
- Local PII/document, form, consent, policy/terms, purpose, and tracking analysis modules.
- Optional, disabled-by-default LLM client with a sanitization gate and OS-keychain credentials.
- macOS and Windows adapter implementations plus Qt UI components, with injected/UI coverage and limited real macOS checks.
- WebExtension source for Chromium-family browsers and Firefox, including CMP, Deep Check, tracker DNR/cookie, browser-recovery, and Firefox fixed-ID handshake coverage.
- macOS packaging scripts and a compatible static Tesseract 5.5.3 / Leptonica 1.87 / libpng 1.6.58 build path targeting macOS 13.
- Developer, security, platform, detector, LLM, performance, and product documentation grounded in current code/evidence.

### Verification pending

- Real TCC/Full Disk Access/Accessibility/screen checks, a Windows installed-lifecycle rerun after the fixed PowerShell exit-code gate, green CI (the latest-source run is billing-blocked), and release artifacts.
