# Changelog

All notable changes will be documented here. This project has not produced a verified release artifact.

## [Unreleased]

### Changed

- Rebuilt both intervention surfaces — the desktop widget and the in-page extension panel — on one
  card design: a headline, a short body, severity-marked finding rows, a subject/destination
  context line, and actions ranked so the protective option is the filled primary button. Both
  render the same structured `Decision`, so the two surfaces can no longer drift apart.
- `Decision` now carries `headline`, `body`, `findings`, `subject`, `destination`, `action_labels`,
  `primary_action`, `tertiary_action`, `layout` and `auto_action` instead of one run-on
  `explanation` string. `explanation` remains as the single-line form used in history and logs.
- Replaced the dashboard's tab strip with sidebar navigation: Overview, Events, Preferences,
  Sites & apps, About. Events gained Intervened/Informed/Ignored tiles and time / what happened /
  site or app / decision columns. Preferences now lists the seven kinds of information a person
  recognises instead of every detector category, plus a Learning card.
- The thorough check reports four grouped sections with per-finding detail lines, shows a live
  checklist while it runs, and hands off to the full report in the dashboard.
- The menu bar icon is a monochrome padlock template with a status dot, and its menu leads with a
  status line and the thorough check.

### Added

- Learned defaults: after the same reversible protective choice on five distinct sites, Privacy
  Guardian offers once to make it automatic, with "Keep asking me" as a real option. Government ID,
  medical, financial and credential data are excluded from automation by construction.
- A compact confirmation bar reporting what an action did, in the page and on the desktop.
- "Show me where" now locates and highlights the flagged clauses on the page.
- `install.sh`: one command to build and install on macOS, with `--skip-ocr`, `--no-autostart` and
  `--uninstall`.
- `learning_enabled` setting and `Store.outcome_counts()`.

### Fixed

- Browser events raised both an in-page widget and a desktop popup. The page now owns events it can
  render; the desktop owns the rest, and picks up browser events only when no extension is live.
- Pausing did not hold for privacy-policy events: a partial document could still raise the outcome
  from Ignore to Inform after the pause check had run.
- A scanned PDF failed the whole document analysis when OCR was unavailable, so the upload
  proceeded unchecked. Scanned pages are now reported as unchecked and the upload is flagged
  partial.
- The macOS bundle failed `codesign --verify --strict` because PySide6 framework directories carry
  `com.apple.FinderInfo`. The build now signs a clean staged copy and verifies it before building
  the DMG.
- "Show me where" on a terms dialog silently swallowed the user's click and did nothing.
- Restarting the service after a worker thread died left the old clipboard monitor running and
  started a second one against a stale backend.
- Each thorough check created a new window instead of reusing one.
- Resolving a decision reset the menu bar icon to idle even while other decisions were pending or
  monitoring was paused.
- Informational in-page toasts kept polling the native host every 300 ms for a full minute after
  they had been dismissed.
- `wallpaper_utility` treated startup and background execution as reasonable, contradicting the
  product's own worked example.
- macOS 13 and later moved the System Settings privacy anchors; the app used the pre-Ventura URL.

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
