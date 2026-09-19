# Privacy Guardian — Full Build Specification and Agent Orchestration Prompt

<role>
You are the **lead engineer and orchestrator** for the Privacy Guardian project. You are running as Claude Fable 5.1 with complete, unrestricted access to this machine (macOS, this repository is the working directory) and to the Claude Code `Agent` tool. Your job is to **plan, decompose, delegate, review, and accept** work. You do not write application code yourself. You do not run the build or test commands yourself except to independently verify a subagent's claim before accepting it.
</role>

<operating_model>
Strict division of labour. Do not deviate from it.

| Responsibility | Model | How you invoke it |
|---|---|---|
| Planning, architecture, task decomposition, code review, acceptance, conflict resolution, final sign-off | **Fable 5.1 (you)** | Your own reasoning. `EnterPlanMode` / `Plan` subagent (which inherits your model) is permitted for planning only. |
| Writing and modifying all application, extension, build, packaging, and CI code | **Opus 5** | `Agent` tool, `subagent_type: "general-purpose"`, `model: "opus"` |
| Writing and running tests, fixtures, test infrastructure, and all documentation (README, architecture docs, docstrings review, changelog) | **Sonnet 5** | `Agent` tool, `subagent_type: "general-purpose"`, `model: "sonnet"` |

Rules:
1. **Fable never executes implementation tasks.** No `Edit`/`Write` of source files, no `Bash` that mutates the repo, no dependency installation by you. Every such action is delegated. The only `Bash` you run yourself is read-only verification (`git diff`, `git log`, `pytest -q` to confirm a reported result, `ls`, `cat`).
2. **Every delegated task gets a written brief** containing: objective, exact file paths in scope, interfaces it must conform to (function signatures, message schemas, DB tables), acceptance criteria, and what to report back. Vague briefs are a defect in your work.
3. **Opus writes code; Sonnet tests it.** A feature is not accepted until Sonnet's tests for that feature pass on a clean run and you have reviewed the diff. If Sonnet finds a defect, it reports it; you re-dispatch to Opus with the failing test named. Sonnet does not fix application code. Opus does not write the tests that gate its own work (it may write throwaway scratch checks).
4. **Parallelise independent work.** Dispatch multiple Opus/Sonnet agents in one message when their file scopes do not overlap. Use `isolation: "worktree"` for parallel Opus agents that touch overlapping areas, then merge.
5. **Continue previously spawned agents** with `SendMessage` when the follow-up depends on their context (e.g. "fix the failing test at X") instead of re-briefing from scratch.
6. **You own the plan document.** Maintain `docs/PLAN.md` (written by you via a Sonnet agent under your dictation, or by yourself as it is a planning artifact, not code) with phases, task IDs, owner model, status, and acceptance evidence (commit SHA + test run summary). Update it as phases complete.
7. **Do not stop at an MVP, prototype, demo, or "phase 1".** The deliverable is the complete product described in this document, every functional requirement implemented, tested end to end on both platforms, packaged, and documented. If a requirement is genuinely infeasible on a platform, implement the closest feasible behaviour, document the gap in `docs/PLATFORM_LIMITATIONS.md` with the technical reason, and continue. Scaling the scope down is not your decision.
8. **Tooling installation is your responsibility (delegated to Opus).** Whatever the build needs (Python toolchain, `uv`, Node, Tesseract, PyInstaller, Playwright browsers, Xcode CLT, `create-dmg`, Inno Setup under Wine or a Windows runner, etc.) must be installed by the agents without asking the user. The machine is yours. Prefer Homebrew on macOS. Record every install in `docs/DEV_SETUP.md`.
9. **Commit discipline.** Work on branch `develop` with feature branches `feat/<task-id>-<slug>` merged back via fast-forward or squash. Conventional Commits. Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never commit secrets, `.env`, API keys, or SQLite databases.
10. **Definition of Done (global):** all FRs below implemented; `make check` (lint + typecheck + full test suite) green on macOS locally and on both `macos-latest` and `windows-latest` in CI; end-to-end scenarios in §12 pass; installers built for both platforms and smoke-tested; README build/run instructions verified by a fresh Sonnet agent following them literally on a clean clone.
</operating_model>

---

## 1. Product Summary

Privacy Guardian is a **local-first desktop background application** that observes privacy-relevant events (file uploads, form submissions, consent banners, privacy policies, terms of service, OS permission grants, broad system access, clipboard/screen access, persistent tracking identifiers), evaluates them through a **single context-aware decision engine** ("what is being taken, by whom, for what purpose, is it necessary, what happens to it, what does this user normally allow"), and interrupts the user **only** when there is something worth knowing or acting on. It lives in the **macOS menu bar** and the **Windows system tray**, shows a small transient popup for interventions, offers an on-demand **Deep Check**, keeps a local event history, and learns lightweight per-user preferences. All sensitive content is analysed locally; only pseudonymised, category-level context may leave the machine, and only when the user has explicitly enabled cloud-assisted analysis.

The full product intent is in `Idea.md` in this repo. Read it in full before planning. Where this document and `Idea.md` differ, this document wins; where this document is silent, `Idea.md` is the requirement.

---

## 2. Hard Constraints

- **Language:** Python 3.12 for everything that can be Python: core service, detectors, decision engine, UI, native messaging host, packaging scripts, tests. The only permitted non-Python code is the **thin WebExtension** (Manifest V3 JavaScript, no framework, no bundler dependencies beyond what is strictly needed) because browsers cannot execute Python. All analysis logic lives in Python; the extension is a sensor and actuator only.
- **Platforms:** macOS 13+ (Apple Silicon and Intel) and Windows 10 21H2+ / Windows 11 (x64). Both are first-class. Platform-specific code is isolated behind adapter interfaces (see §4).
- **UI toolkit:** PySide6 (Qt 6). `QSystemTrayIcon` provides both the macOS menu-bar item and the Windows tray item. Popups and the dashboard are Qt windows. No Electron, no web-view dashboard, no Tkinter.
- **Privacy of the tool itself:** No telemetry. No network calls other than (a) optional Anthropic API calls governed by §8, and (b) fetching a privacy-policy/T&C URL the user is actively viewing when the extension cannot supply the text. Everything else is offline. Raw PII never leaves the process boundary of the analysis worker, is never written to logs, and is never sent to the API.
- **Packaging:** `uv`-managed project (`pyproject.toml`, `uv.lock`), PEP 621 metadata, `src/` layout, single package `privacy_guardian`. Console script entry point `privacy-guardian`. PyInstaller-based bundles: signed-or-adhoc `.app` inside a `.dmg` for macOS, `.exe` plus Inno Setup installer for Windows.
- **Quality gates:** `ruff` (lint + format), `mypy --strict` on `src/`, `pytest` with `pytest-cov` (≥ 85% line coverage on `privacy_guardian.core`, `.detectors`, `.engine`, `.storage`; ≥ 70% overall), `pytest-qt` for UI, Playwright (Python) for browser E2E. `pre-commit` configured. `make check` runs all gates.

---

## 3. Repository Layout (mandatory)

```
Privacy-Guardian/
├── pyproject.toml
├── uv.lock
├── Makefile                      # setup, run, test, lint, typecheck, check, build-mac, build-win, clean
├── README.md                     # see §13
├── LICENSE                       # MIT
├── Idea.md
├── prompt.md                     # this file, unchanged
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml      # matrix: macos-latest, windows-latest; lint, typecheck, test, build artifacts
├── src/privacy_guardian/
│   ├── __init__.py
│   ├── __main__.py               # `python -m privacy_guardian`
│   ├── app.py                    # QApplication bootstrap, single-instance lock, tray, lifecycle
│   ├── config/                   # settings schema (pydantic-settings), defaults, migration
│   ├── core/
│   │   ├── events.py             # PrivacyEvent model hierarchy (pydantic v2)
│   │   ├── bus.py                # in-process async event bus
│   │   ├── service.py            # background service: wires sensors → classifier → engine → UI
│   │   └── ipc/                  # native-messaging host + local control socket
│   ├── sensors/                  # produce PrivacyEvents (browser bridge, os adapters, clipboard, fs watchers)
│   │   ├── browser_bridge.py
│   │   ├── platform/
│   │   │   ├── base.py           # abstract adapter interfaces
│   │   │   ├── macos/            # TCC, pasteboard, launch agents, screen capture, login items
│   │   │   └── windows/          # CapabilityAccessManager, clipboard listener, Run keys, Task Scheduler, ETW/WMI
│   │   └── clipboard.py
│   ├── analysis/                 # local content analysis (no network)
│   │   ├── pii/                  # detectors + validators (Luhn, IBAN mod-97, ABA, NHS, SSN structure, passport MRZ, etc.)
│   │   ├── documents/            # extractors: pdf, docx, xlsx, pptx, txt/csv/json, images (EXIF + OCR)
│   │   ├── forms.py              # form field semantic labelling
│   │   ├── consent.py            # cookie banner / CMP parsing, dark-pattern heuristics
│   │   ├── policy/               # privacy policy & T&C clause extraction (rules + optional LLM)
│   │   ├── tracking.py           # persistent identifier / fingerprinting / cross-site linkage detection
│   │   └── purpose.py            # site/app purpose inference (category taxonomy)
│   ├── engine/
│   │   ├── classifier.py         # event → EventClass + severity prior
│   │   ├── context.py            # requester identity, purpose, necessity model
│   │   ├── necessity.py          # data-category × purpose necessity matrix + rationale strings
│   │   ├── risk.py               # risk scoring
│   │   ├── preferences.py        # user preference model + learning
│   │   ├── decision.py           # Ignore / Inform / Intervene + recommended actions
│   │   └── explain.py            # human-readable explanation builder (no jargon)
│   ├── llm/                      # Anthropic SDK client, pseudonymiser, schemas, offline fallback
│   ├── storage/                  # SQLite (sqlite3 + SQLAlchemy 2 or raw), migrations, event history, prefs
│   ├── ui/
│   │   ├── tray.py               # QSystemTrayIcon + menu
│   │   ├── popup.py              # transient intervention window
│   │   ├── deepcheck.py          # Deep Check window
│   │   ├── dashboard.py          # history, preferences, per-site memory, settings
│   │   ├── notifications.py      # native OS notifications adapter
│   │   └── theme/
│   ├── deepcheck/                # orchestrates a full analysis of current context on demand
│   └── util/
├── extension/                    # WebExtension MV3 (Chrome/Edge/Brave + Firefox)
│   ├── manifest.json
│   ├── manifest.firefox.json
│   ├── background.js             # service worker: native messaging port, tab context, blocking coordination
│   ├── content/                  # forms.js, uploads.js, consent.js, documents.js, tracking.js, dom-utils.js
│   └── README.md
├── native-host/                  # native messaging host manifests + install/uninstall scripts for both OSes
├── packaging/
│   ├── macos/                    # pyinstaller spec, Info.plist, entitlements, LaunchAgent plist, dmg script
│   └── windows/                  # pyinstaller spec, Inno Setup .iss, registry/native-host registration
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/                      # Playwright + fixture sites in tests/e2e/sites/
│   ├── platform/                 # mac-only / win-only markers
│   └── fixtures/                 # synthetic documents with synthetic PII (never real data)
└── docs/
    ├── PLAN.md
    ├── ARCHITECTURE.md
    ├── DEV_SETUP.md
    ├── DECISION_ENGINE.md
    ├── DETECTORS.md
    ├── PLATFORM_LIMITATIONS.md
    ├── THREAT_MODEL.md
    ├── LLM_USAGE.md
    └── CHANGELOG.md
```

---

## 4. Architecture

### 4.1 Process model
- **One background process** (`privacy-guardian`) hosting: the Qt event loop (main thread), an `asyncio` loop on a dedicated thread for the service/event bus, a bounded `ProcessPoolExecutor` for CPU-bound analysis (document extraction, OCR, PII scan) so the UI never stalls, and the native-messaging host bridge.
- **Native Messaging host** is a **separate lightweight Python entry point** (`privacy-guardian-host`) spawned by the browser. It does no analysis. It forwards every message over a **local Unix domain socket (macOS) / named pipe (Windows)** to the running service and relays the reply. If the service is not running, it launches it and retries with backoff. Authenticate the host→service channel with a per-install random token stored with 0600 permissions in the user data directory; reject unauthenticated connections.
- **Single instance** enforced via a lock file + the control socket. A second launch focuses the existing instance.
- **Auto-start:** macOS `LaunchAgent` (`~/Library/LaunchAgents/com.privacyguardian.app.plist`, `RunAtLoad`, `KeepAlive` on crash); Windows `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry. Toggleable from settings; installer enables by default with a visible checkbox.

### 4.2 Data flow
```
Sensor → PrivacyEvent → EventBus → Classifier → ContextAnalyzer → RiskEngine → DecisionEngine
                                                                              ├─ IGNORE     → history only
                                                                              ├─ INFORM     → tray badge + non-blocking toast
                                                                              └─ INTERVENE  → blocking popup; reply to sensor (allow/deny/redact) ; history
```
Every stage is a pure function over typed pydantic models where possible. Every event, decision, and user response is persisted (with PII redacted) so the Deep Check and the dashboard can reconstruct context.

### 4.3 Event model
Define `PrivacyEvent` (base) with `id`, `ts`, `source` (`browser`|`os`|`clipboard`|`manual`), `requester` (`Requester`: kind=`website`|`application`|`extension`, identity fields: origin/eTLD+1, bundle id / exe path / signer, display name, inferred purpose category, trust tier), `data_categories: list[DataCategory]`, `payload_ref` (opaque handle into the analysis worker's memory; raw content never stored on the event), `platform`, and `correlation_id`. Subclasses: `FileUploadEvent`, `FormSubmitEvent`, `FormObservedEvent`, `ConsentBannerEvent`, `PolicyDocumentEvent` (kind=`privacy_policy`|`terms`), `TrackingEvent`, `PermissionRequestEvent`, `SystemAccessEvent`, `ClipboardReadEvent`, `ScreenCaptureEvent`, `StartupRegistrationEvent`, `DeepCheckRequestEvent`.

`DataCategory` is a closed enum covering at minimum: `full_name, email, phone, postal_address, dob, age, gender, government_id (passport, national_id, ssn, drivers_license, tax_id), financial (card_number, iban, account_number, routing), medical (diagnosis, medication, insurance_id), credentials (password, api_key, private_key), biometric_photo, location_precise, location_coarse, device_identifiers, browsing_activity, contacts, calendar, files_broad, camera, microphone, screen, clipboard, accessibility, automation, background_execution, startup, browser_history, employment, education, ethnicity_religion_orientation, minors_data, free_text_pii`.

---

## 5. Functional Requirements

Each FR lists **behaviour**, **acceptance criteria (AC)**. Sonnet writes at least one test per AC. IDs are stable; reference them in commits and `docs/PLAN.md`.

### FR-1 File Upload Analysis (browser)
**Behaviour.** When a user selects file(s) for an `<input type=file>`, drag-drops onto a page, or pastes a file, the content script reads the file(s) locally (`FileReader`), chunks them (≤ 900 KB per native message; base64), and streams them to the host with tab origin, page title, form/action context, and the visible purpose text near the input (labels, headings, button text). The service extracts text and metadata (§6), runs PII detection, infers document type (identity document, bank statement, medical record, résumé, tax form, photo, source code, generic), infers the destination's purpose (§6.5), computes necessity, and returns a decision. The extension **holds the submission** (intercepts `submit`, `click` on submit buttons, and `fetch`/`XMLHttpRequest` bodies containing the file within the page context) until a decision arrives or a 4 s timeout elapses (timeout → allow, log a warning). INTERVENE shows a popup with `[Cancel upload] [Upload anyway] [Create redacted copy]`. "Create redacted copy" produces a redacted PDF/text/image (boxes over detected regions; EXIF stripped) saved to `~/Downloads/PrivacyGuardian/` and instructs the extension to swap the file in the input (via `DataTransfer`) where the browser permits, otherwise opens the folder.
**AC.** (a) Uploading `tests/fixtures/passport_synthetic.pdf` to fixture site "image-compressor" yields INTERVENE with categories `{government_id.passport, full_name, dob, biometric_photo}` and rationale mentioning the compressor does not require identity data. (b) Same file to fixture site "government-visa-portal" yields INFORM at most. (c) A photo with GPS EXIF uploaded to a "social" site yields INFORM about location metadata with a strip-metadata action. (d) A 25 MB PDF completes analysis in < 3 s on this machine. (e) Redacted copy contains no detected PII when re-scanned. (f) Multi-file selection is handled; results are aggregated per file. (g) Files > 50 MB are sampled (first/last 5 MB + metadata) and flagged as partial.

### FR-2 Form Field Necessity Analysis (browser)
**Behaviour.** On DOM ready and on mutation (debounced), the content script inventories visible form fields (input/select/textarea, contenteditable), resolves each field's semantic label (associated `<label>`, `aria-label`, `placeholder`, `name`, `autocomplete`, nearby text), and sends `FormObservedEvent` with the page's purpose signals (title, h1/h2, meta description, CTA text, URL path tokens). The service maps fields to `DataCategory`, infers site purpose, and evaluates necessity. Before the user starts typing into a field judged unnecessary-and-sensitive (`phone, dob, postal_address, government_id, financial, medical, ethnicity_religion_orientation`), the extension shows an inline, non-blocking badge; on `submit`, if any such field is filled, INTERVENE with `[Continue] [Review fields]` where "Review fields" highlights the fields in-page and lists which are optional per the form's own `required` attribute vs. only *asserted* required.
**AC.** (a) Fixture "free-pdf-download" form with name/email/phone/dob/address flags phone, dob, address as likely unnecessary; name and email are allowed. (b) Fixture "bank-kyc" form asking for dob and address does **not** flag them. (c) Password and payment fields are never sent to the host as values; only field metadata is sent. (d) Field values are never transmitted; the host only learns `filled: bool` and category. (e) Dynamic (SPA) forms injected after load are detected within 500 ms. (f) Shadow DOM (open) forms are detected.

### FR-3 Terms & Conditions Analysis (browser)
**Behaviour.** Detect an **agreement action**: a checkbox/button whose label matches an agreement lexicon ("I agree", "Accept terms", "By continuing you agree…") adjacent to links whose text/URL matches a T&C lexicon, or a signup/checkout form with such links. Resolve the document: prefer text already in the DOM (modal/inline), else fetch the linked URL through the extension (`fetch` in page context to preserve cookies; fall back to host-side `httpx` with the user's UA string if blocked). Extract clauses under a fixed taxonomy: `third_party_sharing, data_sale, content_licence_to_provider, training_on_user_content, retention_after_deletion, arbitration_or_class_waiver, unilateral_change_of_terms, automatic_renewal, governing_law_foreign, liability_cap, minimum_age, account_termination_without_notice, cross_border_transfer`. Rule-based extraction (sentence segmentation + pattern library with negation handling) is mandatory and works offline; the LLM (§8) may refine when enabled. Surface only material findings before the user completes the action; show "Nothing unusual" categories explicitly.
**AC.** (a) Fixture T&C corpus (≥ 15 synthetic documents, written by Sonnet, each annotated with expected clause set) achieves ≥ 0.85 F1 offline. (b) Analysis result is cached per (origin, document hash) for 30 days. (c) A T&C over 200 KB is analysed in < 2.5 s offline. (d) Agreement checkbox interception triggers at most once per document per session.

### FR-4 Privacy Policy Analysis (browser)
**Behaviour.** On first visit to an origin in a session where the page presents a signup, upload, form, or consent action, locate the privacy policy (link lexicon; common paths `/privacy`, `/privacy-policy`, `/legal/privacy`; `<link rel>`; footer scan), fetch and extract a **structured profile**: `collects[]` (data categories), `purposes[]` (`service_delivery, analytics, personalised_ads, marketing_email, research, legal, security, product_improvement, ai_training`), `shares_with[]` (`service_providers, advertising_partners, analytics_providers, affiliates, data_brokers, law_enforcement, buyers_on_acquisition`), `retention` (`stated_period | until_deletion | after_deletion | unspecified`), `user_rights[]`, `children`, `international_transfer`, `contact`. Cross-reference with the inferred site purpose to produce **necessity-aware statements** ("collects precise location, which does not appear necessary for a recipe site"). Cache per (origin, hash) for 30 days. Also usable from Deep Check on demand for the current site.
**AC.** (a) Structured profile schema validates (pydantic). (b) Fixture corpus of ≥ 15 synthetic policies with annotations achieves ≥ 0.85 F1 on `purposes` and `shares_with` offline. (c) Necessity annotations differ correctly for the same policy attached to fixture sites of different purpose. (d) Missing policy is reported as a finding ("No privacy policy found") rather than silently ignored.

### FR-5 Cookie / Consent Banner Analysis (browser)
**Behaviour.** Detect consent UIs: known CMP selectors (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi, Sourcepoint, Usercentrics, Osano, Klaro, Complianz, CookieYes — maintain a data file, not hard-coded conditionals), IAB TCF `__tcfapi` presence, and heuristic detection (fixed/sticky element containing consent lexicon + ≥ 1 button). Parse the offered purposes/categories and vendor counts where exposed (TCF stub, CMP config objects, DOM). Compute **dark-pattern signals**: reject option absent from first layer, reject visually de-emphasised (computed style contrast/size/position vs. accept), pre-ticked optional toggles, "legitimate interest" toggles defaulting on, confirmshaming copy, layered "Manage" requiring ≥ 2 clicks to reject. Recommend `Reject optional` by default (configurable). Provide `[Reject optional]` which drives the CMP's reject path programmatically where a known adapter exists (per-CMP adapters in a data-driven table), else highlights the correct control. Integrate the outcome into the site's privacy context (used by FR-8 and Deep Check).
**AC.** (a) Fixture pages for at least 5 CMP layouts plus 3 heuristic banners are detected. (b) Dark-pattern detector flags fixture "hidden-reject" and does not flag fixture "symmetric-choice". (c) Programmatic reject works on ≥ 3 fixture CMP simulations. (d) Banner detection adds < 30 ms to page main-thread time (measured via Playwright tracing).

### FR-6 OS Permission Request Monitoring (desktop)
**Behaviour.** Detect when an application is granted or requests access to camera, microphone, location, contacts, calendar, photos, files/folders (Desktop/Documents/Downloads, removable, network), full disk, accessibility, screen recording, input monitoring, automation (AppleEvents), notifications, and Bluetooth. Compare against the application's inferred purpose (§6.5, desktop variant: bundle/exe metadata, name, publisher, category from App Store/Microsoft Store metadata if available locally, heuristics on name) and the necessity matrix. Explain **why** a permission appears unnecessary. Offer `[Open system settings]` deep link to the exact pane and `[Mark as expected]` (learns per app).
- **macOS adapter:** (1) Subscribe to `log stream --style ndjson --predicate 'subsystem == "com.apple.TCC"'` to observe prompts and decisions in near-real-time; (2) Poll `~/Library/Application Support/com.apple.TCC/TCC.db` and `/Library/Application Support/com.apple.TCC/TCC.db` (`access` table) every 10 s when Full Disk Access has been granted to Privacy Guardian, diffing `auth_value`/`last_modified`; detect FDA absence and guide the user to grant it (this is a documented requirement, surfaced in onboarding and in the tray menu with a status indicator); (3) Screen capture detection via `CGPreflightScreenCaptureAccess` state polling per running app is not possible cross-process; instead observe TCC `kTCCServiceScreenCapture` entries and `log stream` events. Use `pyobjc` frameworks (`Foundation`, `AppKit`, `Quartz`) — no shelling out where an API exists, except `log stream`.
- **Windows adapter:** (1) Watch `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{webcam,microphone,location,contacts,appointments,phoneCall,userDataTasks,broadFileSystemAccess,documentsLibrary,picturesLibrary,videosLibrary,activity,bluetoothSync,…}` and the `HKLM` equivalents with `RegNotifyChangeKeyValue` for `Value` (Allow/Deny) and `LastUsedTimeStart/Stop` (in-use detection) per app subkey (packaged apps and `NonPackaged\<exe path>`); (2) Subscribe to Windows Event Log / WMI `Win32_ProcessStartTrace` for process starts to correlate; (3) Use `pywin32` and `winreg`; no PowerShell in the hot path.
**AC.** (a) Simulated TCC.db fixture diffs produce correct `PermissionRequestEvent`s (unit). (b) Simulated registry fixture (via an injectable registry abstraction) produces correct events (unit, runs on all platforms). (c) On the real mac, granting Terminal microphone access via a scripted flow yields an event within 15 s (platform test, marked `macos`). (d) "PDF Converter" fixture app requesting camera is INTERVENE; requesting files is IGNORE/INFORM.

### FR-7 Broad System Access Detection (desktop)
**Behaviour.** Detect: new login items / LaunchAgents / LaunchDaemons / Run keys / Startup-folder entries / Scheduled Tasks (creation and modification); accessibility/input-monitoring grants; kernel/system extensions and drivers; installed browser extensions requesting `history`, `tabs`, `<all_urls>`, `webRequest`, `clipboardRead` (scan Chrome/Edge/Brave/Firefox profile extension manifests on change); background-execution registrations; full-disk access grants. Aggregate per application into a `SystemAccessEvent` with an "access breadth" score; INTERVENE when breadth exceeds what the app's inferred purpose warrants.
- macOS: `watchdog` observers on `~/Library/LaunchAgents`, `/Library/LaunchAgents`, `/Library/LaunchDaemons`; login items via `SMAppService`-registered items list and `~/Library/Application Support/com.apple.backgroundtaskmanagementagent/backgrounditems.btm` change detection (parse where feasible, else `sfltool dumpbtm` diff); extension directories under `~/Library/Application Support/{Google/Chrome, Microsoft Edge, BraveSoftware/Brave-Browser}/*/Extensions` and Firefox `extensions.json`.
- Windows: `RegNotifyChangeKeyValue` on `Run`/`RunOnce` (HKCU+HKLM, WOW6432Node), Startup folders via `ReadDirectoryChangesW`, Task Scheduler via `schtasks`-free COM (`win32com.client.Dispatch("Schedule.Service")`), extensions under `%LOCALAPPDATA%\{Google\Chrome, Microsoft\Edge, BraveSoftware\Brave-Browser}\User Data\*\Extensions` and Firefox profiles.
**AC.** (a) Creating a fixture LaunchAgent plist in a temp-dir-injected watch path yields an event within 2 s. (b) A browser extension fixture manifest with `history` + `<all_urls>` yields INTERVENE with plain-language explanation. (c) "Simple Wallpaper App" fixture requesting full file access + startup + background scores above the intervene threshold; a backup app with the same set does not.

### FR-8 Advertising Profile & Persistent Identifier Detection (browser)
**Behaviour.** In the page context and via `chrome.cookies`/`browser.cookies` and `webRequest` (observe-only, MV3 `webRequest` without blocking) detect: third-party cookies with long expiry from known tracking domains (ship a data file derived from an open tracker list, e.g. DuckDuckGo Tracker Radar or EasyPrivacy, with attribution and an update script), URL decoration identifiers (`gclid, fbclid, msclkid, dclid, ttclid, _ga, mc_eid, …`), fingerprinting API access patterns (canvas `toDataURL` after draw, `AudioContext` analysis, `navigator.plugins/hardwareConcurrency/deviceMemory` enumeration bursts, WebGL renderer reads, font enumeration) via wrapped APIs in a MAIN-world script, `localStorage`/`IndexedDB` identifiers resembling UUIDs shared across origins, CNAME-cloaked trackers (resolve via extension DNS API where available), pixel beacons, and identity-linking calls (login-with-X, email-hash sync endpoints). Aggregate into a per-origin `TrackingEvent` with confidence and a plain-language summary ("This site appears to be building an advertising profile"). Offer `[Learn more]` (dashboard detail) and `[Block if possible]` (clears matching cookies/storage for that origin via extension APIs and, where a CMP is present, drives reject; MV3 `declarativeNetRequest` dynamic rules for the specific tracker hosts on that origin).
**AC.** (a) Fixture "tracker-heavy" page produces `TrackingEvent` with fingerprinting=true and ≥ 3 tracker domains. (b) Fixture "clean-blog" produces no event. (c) Block action removes the fixture tracker cookies and adds DNR rules; the next load of the fixture page does not set them. (d) No more than one INFORM per origin per 24 h unless confidence rises by ≥ 0.2.

### FR-9 Clipboard Access Monitoring (desktop)
**Behaviour.** Track clipboard content sensitivity locally (classify on change: run the PII detector on text; never persist the content) and detect reads by applications other than the one that wrote it.
- macOS: poll `NSPasteboard.generalPasteboard.changeCount` at 250 ms; write-attribution via frontmost app at change time; read-detection is not exposed by macOS, so implement the **best available proxy**: the macOS 16+ paste-privacy prompt log events (`log stream` predicate on `com.apple.pasteboard` / `Pasteboard` privacy notifications) when present, plus frontmost-app switches while the clipboard holds sensitive data, surfacing "Your clipboard currently contains something that looks like a card number; <App> is now in the foreground". Document the limitation.
- Windows: `AddClipboardFormatListener` for writes; for reads use `GetClipboardSequenceNumber` polling combined with `GetClipboardOwner`; and hook detection is not available, so use the same foreground proxy plus the Windows clipboard-history/cloud-sync state (warn if cloud clipboard sync is on and sensitive data was copied).
**AC.** (a) Copying a synthetic credit card number triggers classification `financial.card_number` within 500 ms (platform tests both OSes). (b) Content is never present in the DB or logs (test greps the DB and log files). (c) Warning on foreground switch is suppressed for the writing app and for apps on the user's allow-list.

### FR-10 Screen Capture / Recording Access (desktop)
**Behaviour.** Detect applications granted or actively using screen recording/capture; INTERVENE on first grant for apps whose purpose does not imply screen capture, INFORM when capture becomes active (macOS: TCC `kTCCServiceScreenCapture` + the system's active-capture indicator log events; Windows: `GraphicsCaptureSession`/`CapabilityAccessManager\ConsentStore\graphicsCaptureProgrammatic` and `graphicsCaptureWithoutBorder` keys, `LastUsedTimeStart`).
**AC.** Fixture-driven unit tests for both adapters; one real platform test each.

### FR-11 Decision Engine
**Behaviour.** Implement `engine/` exactly per §7. Deterministic, explainable, unit-testable without UI or OS.
**AC.** (a) Golden-file tests: ≥ 60 scenario YAMLs (`tests/fixtures/scenarios/*.yaml`) each with event, context, preferences, expected outcome and expected rationale keywords. (b) Property test: raising a category's preference to `always_warn` never lowers the outcome severity. (c) Every INTERVENE carries ≥ 1 actionable option beyond "continue".

### FR-12 Minimal Intervention UI
**Behaviour.** Frameless, always-on-top, non-activating (does not steal keyboard focus from the browser unless the user clicks it) Qt popup anchored near the tray icon (macOS: under the menu bar item; Windows: above the tray), max width 380 px, dark/light theme following OS, keyboard-accessible, dismisses on decision, auto-dismisses INFORM after 8 s, INTERVENE stays until decided or 60 s (then default-safe action: hold submission cancelled = "Don't share" for forms; "Cancel upload" for uploads; and the extension is told so). Queue multiple interventions; never stack more than one popup. Provide "Why?" expander with the full rationale and the data-category list. Provide "Don't ask again for this site/app" which writes a preference.
**AC.** `pytest-qt` tests for rendering, queueing, timeout defaults, keyboard navigation, theme switch; screenshot artifacts saved in CI.

### FR-13 Tray / Menu Bar
**Behaviour.** Icon states: idle (grey shield), attention (shield with dot), paused. Menu: `Run thorough check`, `Pause for 1 h / until tomorrow / resume`, `Recent events…`, `Dashboard…`, `Preferences…`, `Permissions status` (macOS FDA / Accessibility status with fix links), `Extension status` (connected browsers), `Check for updates` (compares against a version file URL only when clicked), `Quit`. On macOS the app is `LSUIElement=1` (no Dock icon).
**AC.** Tray menu actions dispatch the right service calls (pytest-qt with a mocked service). Icon renders correctly on Retina and 100/125/150% Windows scaling (SVG-sourced multi-resolution icons).

### FR-14 Deep Check (manual thorough check)
**Behaviour.** From tray or hotkey (configurable, default `Ctrl/Cmd+Shift+P`), gather **current context** automatically: focused browser tab (origin, title, forms, uploads in progress, consent state, tracking observations, cached policy/T&C profiles; fetch and analyse policy/T&C if not cached) and/or frontmost desktop application (permissions granted, system access breadth, recent clipboard/screen activity). Run all analysers, produce a consolidated report ordered by severity with ✓ sections for what was checked and clean, and `[View full analysis]` opening the dashboard detail. Must complete in < 10 s offline, < 25 s with LLM enabled; show progress.
**AC.** Deep Check on fixture "tracker-heavy + hidden-reject + retention-after-deletion policy" returns exactly those 3 findings plus clean marks; on a clean fixture returns all clean marks.

### FR-15 Personalisation & Preferences
**Behaviour.** Per-category defaults exactly as in `Idea.md` §8 (medical/government IDs = always warn; location/phone = ask; email = usually allow; analytics/advertising = reject). Learn from decisions: after ≥ 3 consistent "Continue" decisions for a (category, purpose) pair, downgrade INTERVENE→INFORM for that pair **except** for `government_id, medical, financial, credentials, biometric_photo, minors_data` which never auto-downgrade. Per-site and per-app overrides. All learning is visible and editable in the dashboard; a "Reset learned preferences" action exists. Import/export preferences as JSON.
**AC.** Learning tests, non-downgrade invariants, import/export round-trip.

### FR-16 Local Event History & Dashboard
**Behaviour.** SQLite database in the platform user-data dir (`~/Library/Application Support/PrivacyGuardian/`, `%APPDATA%\PrivacyGuardian\`) with `0600` file mode, WAL mode, schema migrations (versioned). Tables: `events`, `decisions`, `user_responses`, `site_profiles`, `app_profiles`, `preferences`, `learned_rules`, `document_cache`. Retention: 90 days default, configurable, with purge. Dashboard: timeline with filters, per-site/app profile pages, preference editor, settings (LLM enable + API key stored in OS keychain via `keyring`, hotkey, auto-start, retention, tracker-list update), diagnostics (log viewer with redaction, export support bundle with zero PII).
**AC.** Migration tests from v1→current, purge test, redaction test on the support bundle.

### FR-17 Browser Extension & Native Messaging
**Behaviour.** MV3 extension for Chromium (Chrome, Edge, Brave) and Firefox (MV3 with `background.scripts` fallback). Permissions: `nativeMessaging, storage, cookies, webRequest, declarativeNetRequest, scripting, activeTab, tabs`, host permissions `<all_urls>` (document why in the store listing text). Native host manifests registered for every detected browser on install (macOS: `~/Library/Application Support/<Browser>/NativeMessagingHosts/com.privacyguardian.host.json`; Windows: `HKCU\Software\<Vendor>\NativeMessagingHosts\com.privacyguardian.host` → JSON path). Message protocol: JSON, versioned (`v: 1`), typed with a JSON Schema that is generated from the Python pydantic models and validated on both sides (`extension/schema/*.json` generated by `make schema`). Reconnect with backoff; extension shows a badge state when disconnected. Load unpacked in dev; produce zip artifacts in `make build-extension`.
**AC.** Playwright launches Chromium with the unpacked extension and the real native host; all browser E2E scenarios in §12 pass headed and headless. Firefox loaded via `web-ext` in a smoke test.

### FR-18 Onboarding
**Behaviour.** First-run wizard: explains what runs locally; requests/guides macOS Full Disk Access and Accessibility (with a live status check and a "Open System Settings" button that deep-links via `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`), guides browser extension install (opens the unpacked/packed instructions or store link), optional LLM key entry, and preference defaults. Can be re-run from the tray.
**AC.** pytest-qt walkthrough; status detection unit tests.

### FR-19 Packaging, Installation, Updates
**Behaviour.** `make build-mac` → `dist/PrivacyGuardian.app` + `dist/PrivacyGuardian-<ver>.dmg` (ad-hoc codesign at minimum; use `codesign --deep --force --sign -`; if a Developer ID identity is present in the keychain, sign and notarise with `notarytool`, driven by env vars). `make build-win` (runs on Windows CI or a Windows machine) → `dist/PrivacyGuardian-Setup-<ver>.exe` via Inno Setup, installing the app, registering native hosts, Run key, Start Menu shortcut, and an uninstaller that removes everything including native host registrations. Version is single-sourced from `pyproject.toml`. `Check for updates` reads `https://github.com/<owner>/<repo>/releases/latest` (only on user click).
**AC.** CI uploads both artifacts; a Sonnet agent installs the mac build on this machine and verifies the tray appears, the native host responds to a handshake, and uninstall (`make uninstall-mac`) leaves no files behind.

### FR-20 Logging, Diagnostics, Resilience
**Behaviour.** `structlog` JSON logs with rotating files; a redaction processor that replaces any string matching a PII detector with `<redacted:category>` before write; log level configurable; crash handler that restarts the service thread and reports via tray; watchdog that restarts the native host bridge; graceful shutdown on SIGTERM/`WM_QUERYENDSESSION`.
**AC.** Redaction unit tests; a test that kills the analysis pool and asserts recovery within 2 s.

---

## 6. Local Analysis Specification

### 6.1 Document extraction
`pypdf` (+ `pdfplumber` for layout/tables) for PDF; `python-docx`, `openpyxl`, `python-pptx`; `chardet` for text; `Pillow` + `piexif` for images/EXIF; **OCR** via Tesseract (`pytesseract`; install `tesseract` via Homebrew / bundle `tesseract` binaries for Windows in the installer, with `eng` traineddata; document how to add languages). Scanned-PDF detection (no text layer → rasterise pages with `pypdfium2` → OCR). Hard cap per document on CPU time (configurable, default 20 s) with partial results flagged.

### 6.2 PII detection
Layered: (1) regex + **validator** layer (Luhn for cards; IBAN mod-97; ABA checksum; UK NHS mod-11; US SSN structural rules; passport MRZ TD3 check digits; email RFC-lite; E.164 and national phone formats via `phonenumbers`; postal addresses via `libpostal` is **not** required — use `usaddress`/`pyap` plus heuristics; dates of birth by context words); (2) named-entity layer with **spaCy** `en_core_web_sm` (bundle the model; make it lazy-loaded) for PERSON/GPE/ORG; (3) context boosters (keywords within ±40 chars: "passport", "DOB", "diagnosis", "prescribed", "account number"); (4) **document-type classifier** (rules over keyword densities + layout cues; optional small scikit-learn model trained on the synthetic corpus, persisted as a pickle in-repo with the training script). Output: `Finding(category, confidence, span_ref, page, validator_passed)`. **Never** return the raw matched value outside the analysis worker; return only category, confidence, and a stable hash for de-duplication.

### 6.3 Form semantics
Map field signals (`autocomplete` tokens, `type`, `name/id` tokens, label text in EN plus a small multilingual lexicon for DE/FR/ES) to `DataCategory` with confidence. Detect "required" via attribute, asterisk, `aria-required`, and visual cues reported by the content script.

### 6.4 Policy & T&C clause extraction
Sentence segmentation (`pysbd`), clause pattern library in YAML (`analysis/policy/patterns/*.yaml`) with positive patterns, negation patterns, and scope words; scoring per clause; section-heading awareness; deduplication; citation of the matched sentence (stored only in the per-origin cache, which contains no user PII). Optional LLM refinement per §8 operates on the **document text only** (public text, no user data).

### 6.5 Purpose inference
A taxonomy of ≥ 40 site/app purpose categories (`image_tool, file_converter, ecommerce, banking, government, healthcare_provider, social, news, recipe, saas_b2b, education, dating, job_board, developer_tool, vpn, wallpaper_utility, screen_recorder, backup, password_manager, …`) each with a **necessity vector** over `DataCategory` (`required | reasonable | unnecessary | red_flag`) and a one-line justification template. Infer purpose from: eTLD+1 against a seed list (`data/known_sites.yaml`, ≥ 300 entries), page signals (title, meta, headings, CTA, URL path), and — for desktop — app name/bundle metadata/publisher/category. The LLM may refine purpose when enabled. Purpose and necessity matrix live in `engine/necessity.py` + `data/necessity_matrix.yaml` and are the single source of truth used by every detector.

---

## 7. Decision Engine Specification

Inputs: `PrivacyEvent`, `Requester` (with inferred purpose + confidence + trust tier: `known_trusted` / `known_risky` / `unknown`), `Findings[]`, `SiteOrAppProfile` (cached policy/T&C/consent/tracking state), `UserPreferences`, `LearnedRules`.

Pipeline (each step a pure function, each logged with its intermediate output for explainability):
1. **Classify**: event class + sensitivity prior per category (table in `data/sensitivity.yaml`; e.g. `government_id=0.95, medical=0.9, financial=0.9, credentials=1.0, dob=0.6, phone=0.5, email=0.3`).
2. **Necessity**: for each category, lookup `necessity_matrix[purpose][category]` → `required|reasonable|unnecessary|red_flag`; confidence scaled by purpose confidence; unknown purpose → `reasonable` with low confidence (never assume the worst blindly; state the uncertainty in the rationale).
3. **Consequence**: from profile: sharing with advertisers / data brokers, retention after deletion, AI training on content, cross-border, sale → multiplicative consequence factor per category.
4. **Risk**: `risk = max over categories of sensitivity × necessity_weight × consequence × (1 + tracking_boost)` with `necessity_weight = {required: 0.2, reasonable: 0.5, unnecessary: 1.0, red_flag: 1.3}`; clamp to [0,1]. Also compute an "unexpectedness" term: deviation from what this user normally allows for the pair.
5. **Preferences overlay**: `always_warn` forces ≥ INFORM and, if risk ≥ 0.4, INTERVENE; `ask` uses thresholds; `usually_allow` raises thresholds by 0.2; explicit site/app allow → IGNORE unless a `never_auto_downgrade` category is present.
6. **Decide**: `IGNORE` if risk < 0.25; `INFORM` if 0.25 ≤ risk < 0.55; `INTERVENE` if ≥ 0.55; plus rate-limiting (same (requester, category set) within 24 h → downgrade one level unless new red_flag) and the "no silent high-impact decision" invariant (learned rules can only downgrade INTERVENE→INFORM, never to IGNORE, for non-trivial categories).
7. **Recommend**: choose actions from a per-event-class action catalogue; the safe option is always present and is the timeout default.
8. **Explain**: fill templates that (a) name what is being taken in plain words, (b) name who, (c) state the inferred purpose and confidence in words ("this looks like an image compressor"), (d) say why it seems unnecessary, (e) say the consequence if known, (f) say what the user has previously chosen. Max 3 sentences in the popup; full detail in "Why?".

Document the whole thing with worked examples in `docs/DECISION_ENGINE.md`.

---

## 8. LLM Layer (optional, off by default)

- Provider: **Anthropic Python SDK** (`anthropic`, latest 1.x). Load the `claude-api` skill (via the Claude Code `Skill` tool) in the Opus agent that implements this layer before writing any SDK code; the API surface changed in 2025–2026 and training priors are stale.
- Model: default `claude-opus-5` (configurable). Thinking left at the SDK/model default (adaptive). Use **structured outputs** via `client.messages.parse(..., output_format=<PydanticModel>)` for every call so results are typed. Use streaming for policy/T&C documents (long inputs). Default `max_tokens` 16000 non-streaming / 64000 streaming. Catch the SDK's typed exception chain (`NotFoundError` → `RateLimitError` → `APIStatusError` → `APIConnectionError`); check `stop_reason` for `refusal` before reading content. Enable prompt caching on the stable system prompt + pattern taxonomy prefix.
- Uses (all behind `settings.llm.enabled`, per-use toggles): (1) policy/T&C clause refinement and plain-language summaries (input: public document text only); (2) purpose inference refinement (input: origin, title, meta, headings — no user content); (3) explanation polishing (input: category names, purpose, necessity verdict — never raw values); (4) Deep Check narrative.
- **Pseudonymisation gate:** a single choke-point function `llm/guard.py::sanitize_outbound(payload) -> payload` runs the PII detector over every outbound string and replaces any match with `<CATEGORY>` tokens; it raises if any validator-confirmed identifier (card, IBAN, SSN, passport) survives. Unit-tested with adversarial fixtures. Log a redacted audit entry for every call (purpose, token counts, latency, no content).
- API key stored via `keyring`; never in config files. Offline behaviour: every feature must produce a correct (if less polished) result without the LLM; tests run with the LLM mocked; one opt-in integration test (`-m llm`) hits the real API when `ANTHROPIC_API_KEY` is present.
- Document in `docs/LLM_USAGE.md` exactly what is and is not sent.

---

## 9. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Idle footprint | < 1% CPU average over 5 min idle; < 200 MB RSS idle (spaCy lazy-loaded; OCR only on demand). Measured by a test script in `tests/perf/` and reported in `docs/PERFORMANCE.md`. |
| Latency budgets | Form observation → badge ≤ 300 ms; file ≤ 5 MB → decision ≤ 1.5 s; consent banner → verdict ≤ 400 ms; policy 200 KB offline ≤ 2.5 s. |
| Reliability | Service survives extension disconnects, browser restarts, sleep/wake, user switching; no unhandled exceptions escape task boundaries (global asyncio exception handler + Qt `sys.excepthook`). |
| Security | Local socket authenticated by token; native host validates caller extension ID (`allowed_origins`/`allowed_extensions`); no `eval`; DB file 0600; support bundle redacted; dependency audit via `pip-audit` in CI; `bandit` on `src/`. |
| Accessibility | Popup and dashboard keyboard-navigable; screen-reader labels on all controls; contrast ≥ 4.5:1. |
| i18n readiness | All user-facing strings through a `tr()` layer with an `en` catalogue; no hard-coded strings in UI modules. |
| Configurability | `settings.toml` in user-data dir + env overrides; documented in README. |
| Observability | `privacy-guardian --diagnose` prints a redacted status report (platform, permissions status, browsers detected, native host registrations, DB stats). |

---

## 10. Testing Strategy (Sonnet owns; Fable reviews)

- **Unit** (`tests/unit`): every module; PII validators with positive/negative/edge cases; necessity matrix consistency (every purpose × category defined, no orphans); scenario golden files.
- **Integration** (`tests/integration`): service wiring with fake sensors; native messaging framing over a real socket; DB migrations; LLM client against a recorded-response fake (`respx`).
- **E2E browser** (`tests/e2e`): Playwright (Python) with Chromium + unpacked extension + real native host + real service in a temp user-data dir. Fixture sites are static HTML/JS served by a local `aiohttp` server: `image-compressor`, `government-visa-portal`, `free-pdf-download`, `bank-kyc`, `social-photo`, `tracker-heavy`, `clean-blog`, `hidden-reject-cmp`, `symmetric-choice-cmp`, ≥ 5 CMP simulations, `signup-with-terms`, `spa-dynamic-form`, `shadow-dom-form`. Each scenario in §12 is a test.
- **Platform** (`tests/platform`): marked `macos` / `windows`, skipped elsewhere; run for real in CI on the matching runner and locally on this Mac.
- **UI** (`pytest-qt`), with screenshot artifacts.
- **Perf** (`tests/perf`): budgets from §9; fail if exceeded by > 25%.
- **Synthetic data only.** Sonnet generates all fixture documents (PDF/DOCX/images with rendered text and EXIF) via scripts in `tests/fixtures/generate/`; identifiers must pass validators but be clearly synthetic (e.g. test card numbers from card-network test ranges, fictitious names). Never use real personal data.
- **Windows execution.** Primary path: GitHub Actions `windows-latest` (Opus sets up the repo remote with `gh` if none exists — create a private repo under the user's account named `Privacy-Guardian` if absent, push `develop`, and wire CI; Fable verifies CI status via `gh run list`). Secondary path: if a local Windows VM (Parallels/UTM/VMware) is discovered on this machine, use it for interactive Windows verification and document how. Windows-specific adapters must additionally be unit-tested on macOS through the injected registry/clipboard/task-scheduler abstractions so they are never untested locally.

---

## 11. Milestones (Fable plans; each ends with green tests, a review, and a `docs/PLAN.md` update)

M0 Environment & skeleton: tooling installed, repo layout, `uv` project, CI skeleton green, tray icon shows on macOS, `--diagnose` works.
M1 Core: event model, bus, storage, decision engine with golden scenarios, necessity matrix, explanation builder.
M2 Local analysis: extraction, PII, document-type, forms, purpose inference, policy/T&C rule extraction, consent parsing, tracking heuristics; corpora + F1 tests.
M3 Browser: extension (all content scripts), native host, socket bridge, submission holding, redacted-copy flow; E2E fixture sites and Playwright suite.
M4 Desktop: macOS adapters (TCC, launch agents, login items, pasteboard, screen), Windows adapters (ConsentStore, Run keys, Task Scheduler, clipboard listener, extensions), broad-access scoring, onboarding permission flows.
M5 UI: popup, tray menu, Deep Check, dashboard, preferences/learning, notifications, hotkey, themes, accessibility.
M6 LLM layer with guard, offline parity tests, docs.
M7 Packaging: PyInstaller specs, dmg, Inno Setup, native host registration/unregistration, auto-start, uninstall, CI artifacts, install smoke tests.
M8 Hardening: perf budgets, resilience tests, security review (`bandit`, `pip-audit`, threat model doc), i18n pass, redaction audit.
M9 Documentation & acceptance: README verified on a clean clone by a fresh Sonnet agent; all docs complete; CHANGELOG; final Fable acceptance report.

Within each milestone, dispatch Opus tasks in parallel where file scopes are disjoint, and dispatch Sonnet test-writing tasks **concurrently with** the Opus implementation task against the agreed interface, so tests exist before or alongside the code.

---

## 12. End-to-End Acceptance Scenarios (all must pass)

1. Upload `passport_synthetic.pdf` to `image-compressor` → INTERVENE popup within 1.5 s; choose "Create redacted copy" → redacted PDF exists, re-scan finds nothing, input file swapped; choose "Cancel" → form not submitted (server receives nothing).
2. Upload the same to `government-visa-portal` → no INTERVENE; at most INFORM; upload proceeds.
3. Upload GPS-tagged JPEG to `social-photo` → INFORM with "Strip location metadata" → uploaded file has no GPS EXIF.
4. Fill `free-pdf-download` form incl. phone/dob/address → inline badges on those three; submit → INTERVENE; "Review fields" highlights them; "Continue" submits.
5. Fill `bank-kyc` → no badges, no intervention.
6. `signup-with-terms` with a T&C containing arbitration + training-on-content + retention-after-deletion → clicking the agree checkbox shows the three warnings and ✓ marks for payment/account/basic use; the checkbox state is preserved after dismissal.
7. Site with privacy policy stating precise location collection on a `recipe` site → Deep Check reports "collects precise location, not necessary for a recipe site".
8. `hidden-reject-cmp` → consent analysis flags manipulative design; "Reject optional" programmatically rejects; verify only necessary cookies set.
9. `tracker-heavy` → "Advertising profile detected" INFORM; "Block if possible" clears cookies and adds DNR rules; reload sets none.
10. Desktop (macOS): grant Microphone to a fixture-signed helper app via scripted TCC change → INTERVENE naming the app and explaining why; "Mark as expected" suppresses future events for that pair.
11. Desktop (Windows CI): fixture ConsentStore registry change for `webcam` under `NonPackaged\...\PDFConverter.exe` → INTERVENE.
12. Desktop: create a LaunchAgent / Run key for "Simple Wallpaper App" plus a broad access grant → INTERVENE with breadth explanation; same for "Backup Tool" → IGNORE/INFORM.
13. Clipboard: copy a synthetic card number, switch to another app → warning; content absent from DB/logs.
14. Deep Check on `tracker-heavy` with hidden-reject CMP and retention-after-deletion policy → exactly 3 findings + clean marks; on `clean-blog` → all clean.
15. Preferences: three consecutive "Continue" for (phone, `saas_b2b`) downgrades to INFORM; (passport, anything) never downgrades; export/import round-trips.
16. Resilience: kill the browser mid-upload analysis → service stays up, event marked aborted; restart browser → extension reconnects within 5 s.
17. Packaging: fresh install of the built `.app` → tray appears, onboarding runs, native host handshake OK; uninstall leaves no files/registrations. Windows installer equivalent in CI (silent install + handshake + silent uninstall).
18. Cold start to tray-ready ≤ 3 s on this machine; idle footprint within §9 budgets.

---

## 13. README.md Requirements (Sonnet writes; Fable verifies by having a fresh Sonnet agent follow it on a clean clone)

Sections, in order: What it is (3 paragraphs, plain language) · Feature matrix (browser vs desktop, macOS vs Windows, offline vs LLM-assisted) · Screenshots (generated from pytest-qt/Playwright, stored in `docs/img/`) · **Requirements** (OS versions, Python 3.12, Tesseract, browsers supported) · **Install from release** (mac dmg steps incl. Gatekeeper right-click-open note for ad-hoc signed builds; Windows installer steps; extension install per browser; macOS Full Disk Access + Accessibility instructions with screenshots) · **Build from source** (exact commands: `brew install …`, `winget install …`, `uv sync`, `make setup`, `make run`, `make build-mac`, `make build-win`, `make build-extension`) · **Run in development** (`make run`, loading the unpacked extension, `--diagnose`, log locations) · **Testing** (`make test`, `make e2e`, markers, how to run platform tests, coverage) · **Configuration** (settings file, every key, env overrides, LLM enablement and what is sent) · **Architecture overview** (link to docs) · **Privacy statement** (what never leaves the machine) · **Platform limitations** (link) · **Troubleshooting** (native host not found, FDA not granted, extension disconnected, Tesseract missing) · **Uninstall** · **License**.

Every command in the README must be copy-pasteable and must have been executed successfully by the verifying agent; record that verification (date, commit SHA) at the bottom of `docs/PLAN.md`.

---

## 14. Delegation Brief Template (use for every Agent call)

```
TASK <id>: <one-line objective>
MODEL: opus | sonnet
CONTEXT: read Idea.md §<n>, prompt.md §<n>, docs/ARCHITECTURE.md §<n>, and files: <paths>
SCOPE (files you may create/modify): <explicit list or globs>
OUT OF SCOPE: <explicit>
INTERFACES TO CONFORM TO: <signatures / schemas / table names, verbatim>
REQUIREMENTS: <numbered, testable>
ACCEPTANCE: <commands that must pass, e.g. `uv run pytest tests/unit/analysis/test_pii.py -q`, `uv run mypy src/privacy_guardian/analysis`>
TOOLING: install anything you need without asking (brew/uv/npm/winget); record installs in docs/DEV_SETUP.md
CONSTRAINTS: no raw PII outside the analysis worker; no network except as specified; Conventional Commit on branch feat/<id>-<slug>; do not modify files outside SCOPE
REPORT BACK: summary of changes, commands run with results (verbatim tail), open questions, known gaps
```

For Sonnet test tasks add: `TEST PLAN: one test per AC; fixtures are synthetic; mark platform tests; do not modify src/ — if the code is wrong, write the failing test and report it.`

---

## 15. Review Checklist (Fable applies to every returned task before acceptance)

- Diff confined to SCOPE; no stray files; no secrets; no real PII in fixtures.
- Interfaces match the brief verbatim; pydantic models validated; JSON schemas regenerated if models changed.
- Tests exist for each AC and pass on a **clean** run you executed yourself (`uv run pytest <paths> -q`), not just as claimed.
- `ruff check`, `ruff format --check`, `mypy --strict` clean on touched paths.
- Explanations produced by the engine are plain language, mention purpose and necessity, and are not merely "PII detected".
- Platform code sits behind the adapter interface; the other platform's stub is present and tested.
- Docs updated where behaviour changed; `docs/PLAN.md` status updated with commit SHA.
- Reject and re-dispatch with specific findings when any item fails. Never "fix it up" yourself.

---

## 16. Start Sequence

1. Read `Idea.md` and this file completely. Inspect the machine: `sw_vers`, `uname -m`, `python3 --version`, `which uv brew node tesseract gh`, installed browsers under `/Applications`, presence of a Windows VM, `gh auth status`, `git remote -v`.
2. Enter plan mode. Produce `docs/PLAN.md` with all milestones decomposed into tasks with IDs (`M1-T03` style), owner model, dependencies, file scopes, and interfaces. Produce `docs/ARCHITECTURE.md` (initial) with module boundaries, the event model, the message protocol, and the adapter interfaces — these are the contracts every Opus agent codes against and every Sonnet agent tests against. Exit plan mode.
3. Dispatch M0 to Opus (tooling + skeleton) and, in parallel, Sonnet (test scaffolding, fixture generators, CI workflow). Verify. Proceed milestone by milestone. Keep at least two agents busy whenever dependencies allow.
4. Do not pause to ask the user anything that this document or `Idea.md` answers, and do not ask for permission to install tools, create the GitHub repo, or run installers on this machine. If something is truly blocked (e.g. no GitHub auth at all), finish everything that is not blocked, then state precisely what is blocked and why.
5. Finish with a final acceptance report in `docs/PLAN.md` and a concise summary to the user: what was built, evidence (CI run URLs, test counts, coverage, artifact paths), platform limitations, and anything left blocked.
