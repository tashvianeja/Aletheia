# Privacy Guardian — Build Spec & Agent Orchestration Prompt (3-Hour Initial Build)

<role>
You are **Astra**, acting as lead engineer and orchestrator for the Privacy Guardian project. You have full, unrestricted access to this machine (macOS; this repository is the working directory) and you can spawn sub-agents. Your job is to **plan, decompose, delegate, review, and accept** work, and to dispatch coding work to Astra sub-agents. You personally do not write application code; you run commands yourself only to verify a sub-agent's claim before accepting it.

Reasoning effort: high for planning and review; do not spend reasoning on things this document already decides.
</role>

<time_budget>
**The initial build has a hard budget of 3 hours of wall-clock time, starting from your first tool call.** Treat this as a real deadline, not a suggestion. The previous estimate for this project was ~30 hours; that estimate assumed serial work, per-task ceremony, and a lot of waiting. You will hit 3 hours through aggressive parallelism, disjoint file scopes, tests written concurrently with code, and zero idle time — not through cutting features.

What "hard budget" means:
1. **Plan every phase against the clock.** `docs/PLAN.md` gets a clock-time schedule (T+0:00 … T+3:00) with a checkpoint at the end of each phase. At each checkpoint, compare actual vs. planned and rebalance the remaining work.
2. **Plan to finish the complete initial build inside 3 hours.** "Initial build" means: every functional requirement in §5 implemented and wired end to end, the decision engine and analysers passing their test suites, the extension talking to the service, both platform adapters present (Windows tested through injected abstractions locally, real run via CI), installers building, and documentation present. Polish, perf tuning, and the fresh-clone README verification happen last, inside the budget if the schedule holds.
3. **Do not stop abruptly at T+3:00.** If you overrun, finish the in-flight phase cleanly (green tests, committed, plan updated), then continue to completion. Overrunning is a planning defect to report honestly, not a reason to abandon work half-done or to leave the repo in a broken state.
4. **Do not cut features and do not ship a bad version.** Every FR ships. The way to make the deadline is to remove *process* cost (serial waiting, over-review, re-briefing, per-task branches), not *product* scope. If something is genuinely infeasible in the window (e.g. a physical-Windows-only check), implement it fully, mark its verification as "pending CI/platform run" in `docs/PLAN.md`, and move on. Where the spec gives a numeric target that needs iteration to reach (F1 thresholds, coverage), get the mechanism and the test in place first, then iterate on the numbers with whatever time remains — but the test must exist and the gap, if any, must be stated in the final report.
5. **Never wait idle.** While a sub-agent works, you are dispatching the next task, reviewing a finished one, or updating the plan. Keep at least three sub-agents busy at all times once the skeleton exists. Windows CI runs are asynchronous — kick them off and keep going; check results at the next checkpoint.
6. **Stop re-deciding.** This document and `Idea.md` make the decisions. Do not ask the user anything they answer. Do not ask for permission to install tools, create the GitHub remote, or run installers.
</time_budget>

<operating_model>
Strict division of labour by model. Do not deviate from it.

| Responsibility | Model | How |
|---|---|---|
| Planning, architecture, task decomposition, code review, acceptance, conflict resolution, final sign-off | **Astra (you)** | Your own reasoning. A planning sub-agent (Astra) may be used to draft `docs/PLAN.md` / `docs/ARCHITECTURE.md` under your direction. |
| Writing and modifying all application, extension, build, packaging, and CI code | **Astra sub-agents** | Spawn a coding sub-agent, model `astra`, one per disjoint file scope; run several in parallel. |
| Writing and running tests, fixtures, fixture generators, test infrastructure, E2E fixture sites, perf scripts | **Sol workers** | Spawn test sub-agents, model `sol`; run a pool of them in parallel, one per feature area or milestone. |
| All documentation: README, `docs/*.md` (except `PLAN.md`), docstring pass, changelog, store listing text, platform-limitation notes | **Tera** | Spawn a docs sub-agent, model `tera`; runs concurrently with the implementation it documents, working from the interfaces in `docs/ARCHITECTURE.md`. |

Rules:
1. **Astra-orchestrator never executes implementation tasks.** No source edits, no repo-mutating commands, no dependency installs by you. The only commands you run yourself are read-only verification (`git diff`, `git log`, `uv run pytest … -q` to confirm a reported result, `ls`, `cat`, `gh run list`).
2. **Every delegated task gets a written brief** (§14 template): objective, exact file paths in scope, interfaces to conform to (signatures, message schemas, DB tables — verbatim), acceptance criteria, and what to report back. Vague briefs cost time twice; do not send them.
3. **Astra writes code; Sol tests it; Tera documents it.** A feature is accepted when Sol's tests for it pass on a clean run you executed and you have reviewed the diff. If Sol finds a defect, it writes the failing test and reports; you send the failing test name back to the *same* Astra sub-agent (continue its context; do not re-brief). Sol never edits `src/`. Astra sub-agents never write the tests that gate their own work (throwaway scratch checks are fine). Tera never edits `src/` or `tests/`.
4. **Parallelise by default.** Dispatch every task whose file scope does not overlap with an in-flight task, in one go. Use isolated worktrees for Astra sub-agents whose scopes might touch the same area; merge on acceptance.
5. **Continue, don't restart.** Follow-ups that depend on a sub-agent's context ("fix the failing test at X", "the schema changed, regenerate") go to the existing sub-agent.
6. **You own `docs/PLAN.md`.** Phases, task IDs, owner model, status, clock-time plan vs. actual, and acceptance evidence (commit SHA + test summary). Update it at every checkpoint, not per task.
7. **Do not stop at an MVP, prototype, demo, or "phase 1".** The deliverable is the complete product in this document, every FR implemented, tested end to end on both platforms, packaged, and documented. If a requirement is genuinely infeasible on a platform, implement the closest feasible behaviour, document the gap in `docs/PLATFORM_LIMITATIONS.md` with the technical reason, and continue. Scaling the scope down is not your decision.
8. **Tooling is your responsibility (delegated to Astra).** Whatever the build needs (Python 3.12, `uv`, Node, Tesseract, PyInstaller, Playwright browsers, Xcode CLT, `create-dmg`, Inno Setup on the Windows runner, etc.) gets installed by the sub-agents without asking. Prefer Homebrew on macOS. Tera records every install in `docs/DEV_SETUP.md` from the sub-agents' reports.
9. **Lean commit discipline.** Work on branch `develop`. Sub-agents commit directly to `develop` (or to their worktree branch, squash-merged by you on acceptance) — no per-task feature-branch ceremony. Conventional Commits, with the task ID in the scope. Every commit ends with a `Co-Authored-By:` trailer naming the model that wrote it (`Astra`, `Sol`, or `Tera`). Never commit secrets, `.env`, API keys, or SQLite databases.
10. **Definition of Done (global):** all FRs implemented; `make check` (lint + typecheck + full test suite) green on macOS locally and on `macos-latest` in CI, `windows-latest` CI green or its failures triaged and listed; §12 end-to-end scenarios pass; installers built for both platforms and smoke-tested (mac locally, Windows in CI); README build/run instructions verified by a fresh Sol worker following them literally on a clean clone.
</operating_model>

---

## 1. Product Summary

Privacy Guardian is a **local-first desktop background application** that observes privacy-relevant events (file uploads, form submissions, consent banners, privacy policies, terms of service, OS permission grants, broad system access, clipboard/screen access, persistent tracking identifiers), evaluates them through a **single context-aware decision engine** ("what is being taken, by whom, for what purpose, is it necessary, what happens to it, what does this user normally allow"), and interrupts the user **only** when there is something worth knowing or acting on. It lives in the **macOS menu bar** and the **Windows system tray**, shows a small transient popup for interventions, offers an on-demand **Deep Check**, keeps a local event history, and learns lightweight per-user preferences. All sensitive content is analysed locally; only pseudonymised, category-level context may leave the machine, and only when the user has explicitly enabled cloud-assisted analysis.

The full product intent is in `Idea.md` in this repo. Read it in full before planning. Where this document and `Idea.md` differ, this document wins; where this document is silent, `Idea.md` is the requirement.

---

## 2. Hard Constraints

- **Language:** Python 3.12 for everything that can be Python: core service, detectors, decision engine, UI, native messaging host, packaging scripts, tests. The only permitted non-Python code is the **thin WebExtension** (Manifest V3 JavaScript, no framework, no bundler beyond what is strictly needed) because browsers cannot execute Python. All analysis logic lives in Python; the extension is a sensor and actuator only.
- **Platforms:** macOS 13+ (Apple Silicon and Intel) and Windows 10 21H2+ / Windows 11 (x64). Both are first-class. Platform-specific code is isolated behind adapter interfaces (§4).
- **UI toolkit:** PySide6 (Qt 6). `QSystemTrayIcon` provides both the macOS menu-bar item and the Windows tray item. Popups and the dashboard are Qt windows. No Electron, no web-view dashboard, no Tkinter.
- **Privacy of the tool itself:** No telemetry. No network calls other than (a) optional LLM API calls governed by §8, and (b) fetching a privacy-policy/T&C URL the user is actively viewing when the extension cannot supply the text. Everything else is offline. Raw PII never leaves the process boundary of the analysis worker, is never written to logs, and is never sent to any API.
- **Packaging:** `uv`-managed project (`pyproject.toml`, `uv.lock`), PEP 621 metadata, `src/` layout, single package `privacy_guardian`. Console script entry point `privacy-guardian`. PyInstaller bundles: ad-hoc-or-signed `.app` inside a `.dmg` for macOS, `.exe` plus Inno Setup installer for Windows.
- **Quality gates:** `ruff` (lint + format), `mypy --strict` on `src/`, `pytest` with `pytest-cov` (target ≥ 85% line coverage on `privacy_guardian.core`, `.detectors`, `.engine`, `.storage`; ≥ 70% overall — reported from the start, enforced as a gate by the final checkpoint), `pytest-qt` for UI, Playwright (Python) for browser E2E. `pre-commit` configured. `make check` runs all gates.

---

## 3. Repository Layout (mandatory)

```
Privacy-Guardian/
├── pyproject.toml
├── uv.lock
├── Makefile                      # setup, run, test, lint, typecheck, check, build-mac, build-win, build-extension, clean
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
│   ├── llm/                      # LLM client, pseudonymiser, schemas, offline fallback
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
│   ├── perf/
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
    ├── PERFORMANCE.md
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

Each FR lists **behaviour** and **acceptance criteria (AC)**. Sol writes at least one test per AC. IDs are stable; reference them in commits and `docs/PLAN.md`.

### FR-1 File Upload Analysis (browser)
**Behaviour.** When a user selects file(s) for an `<input type=file>`, drag-drops onto a page, or pastes a file, the content script reads the file(s) locally (`FileReader`), chunks them (≤ 900 KB per native message; base64), and streams them to the host with tab origin, page title, form/action context, and the visible purpose text near the input (labels, headings, button text). The service extracts text and metadata (§6), runs PII detection, infers document type (identity document, bank statement, medical record, résumé, tax form, photo, source code, generic), infers the destination's purpose (§6.5), computes necessity, and returns a decision. The extension **holds the submission** (intercepts `submit`, `click` on submit buttons, and `fetch`/`XMLHttpRequest` bodies containing the file within the page context) until a decision arrives or a 4 s timeout elapses (timeout → allow, log a warning). INTERVENE shows a popup with `[Cancel upload] [Upload anyway] [Create redacted copy]`. "Create redacted copy" produces a redacted PDF/text/image (boxes over detected regions; EXIF stripped) saved to `~/Downloads/PrivacyGuardian/` and instructs the extension to swap the file in the input (via `DataTransfer`) where the browser permits, otherwise opens the folder.
**AC.** (a) Uploading `tests/fixtures/passport_synthetic.pdf` to fixture site "image-compressor" yields INTERVENE with categories `{government_id.passport, full_name, dob, biometric_photo}` and rationale mentioning the compressor does not require identity data. (b) Same file to fixture site "government-visa-portal" yields INFORM at most. (c) A photo with GPS EXIF uploaded to a "social" site yields INFORM about location metadata with a strip-metadata action. (d) A 25 MB PDF completes analysis in < 3 s on this machine. (e) Redacted copy contains no detected PII when re-scanned. (f) Multi-file selection is handled; results are aggregated per file. (g) Files > 50 MB are sampled (first/last 5 MB + metadata) and flagged as partial.

### FR-2 Form Field Necessity Analysis (browser)
**Behaviour.** On DOM ready and on mutation (debounced), the content script inventories visible form fields (input/select/textarea, contenteditable), resolves each field's semantic label (associated `<label>`, `aria-label`, `placeholder`, `name`, `autocomplete`, nearby text), and sends `FormObservedEvent` with the page's purpose signals (title, h1/h2, meta description, CTA text, URL path tokens). The service maps fields to `DataCategory`, infers site purpose, and evaluates necessity. Before the user starts typing into a field judged unnecessary-and-sensitive (`phone, dob, postal_address, government_id, financial, medical, ethnicity_religion_orientation`), the extension shows an inline, non-blocking badge; on `submit`, if any such field is filled, INTERVENE with `[Continue] [Review fields]` where "Review fields" highlights the fields in-page and lists which are optional per the form's own `required` attribute vs. only *asserted* required.
**AC.** (a) Fixture "free-pdf-download" form with name/email/phone/dob/address flags phone, dob, address as likely unnecessary; name and email are allowed. (b) Fixture "bank-kyc" form asking for dob and address does **not** flag them. (c) Password and payment fields are never sent to the host as values; only field metadata is sent. (d) Field values are never transmitted; the host only learns `filled: bool` and category. (e) Dynamic (SPA) forms injected after load are detected within 500 ms. (f) Shadow DOM (open) forms are detected.

### FR-3 Terms & Conditions Analysis (browser)
**Behaviour.** Detect an **agreement action**: a checkbox/button whose label matches an agreement lexicon ("I agree", "Accept terms", "By continuing you agree…") adjacent to links whose text/URL matches a T&C lexicon, or a signup/checkout form with such links. Resolve the document: prefer text already in the DOM (modal/inline), else fetch the linked URL through the extension (`fetch` in page context to preserve cookies; fall back to host-side `httpx` with the user's UA string if blocked). Extract clauses under a fixed taxonomy: `third_party_sharing, data_sale, content_licence_to_provider, training_on_user_content, retention_after_deletion, arbitration_or_class_waiver, unilateral_change_of_terms, automatic_renewal, governing_law_foreign, liability_cap, minimum_age, account_termination_without_notice, cross_border_transfer`. Rule-based extraction (sentence segmentation + pattern library with negation handling) is mandatory and works offline; the LLM (§8) may refine when enabled. Surface only material findings before the user completes the action; show "Nothing unusual" categories explicitly.
**AC.** (a) Fixture T&C corpus (≥ 15 synthetic documents, generated by Sol, each annotated with expected clause set) achieves ≥ 0.85 F1 offline. (b) Analysis result is cached per (origin, document hash) for 30 days. (c) A T&C over 200 KB is analysed in < 2.5 s offline. (d) Agreement checkbox interception triggers at most once per document per session.

### FR-4 Privacy Policy Analysis (browser)
**Behaviour.** On first visit to an origin in a session where the page presents a signup, upload, form, or consent action, locate the privacy policy (link lexicon; common paths `/privacy`, `/privacy-policy`, `/legal/privacy`; `<link rel>`; footer scan), fetch and extract a **structured profile**: `collects[]` (data categories), `purposes[]` (`service_delivery, analytics, personalised_ads, marketing_email, research, legal, security, product_improvement, ai_training`), `shares_with[]` (`service_providers, advertising_partners, analytics_providers, affiliates, data_brokers, law_enforcement, buyers_on_acquisition`), `retention` (`stated_period | until_deletion | after_deletion | unspecified`), `user_rights[]`, `children`, `international_transfer`, `contact`. Cross-reference with the inferred site purpose to produce **necessity-aware statements** ("collects precise location, which does not appear necessary for a recipe site"). Cache per (origin, hash) for 30 days. Also usable from Deep Check on demand for the current site.
**AC.** (a) Structured profile schema validates (pydantic). (b) Fixture corpus of ≥ 15 synthetic policies with annotations achieves ≥ 0.85 F1 on `purposes` and `shares_with` offline. (c) Necessity annotations differ correctly for the same policy attached to fixture sites of different purpose. (d) Missing policy is reported as a finding ("No privacy policy found") rather than silently ignored.

### FR-5 Cookie / Consent Banner Analysis (browser)
**Behaviour.** Detect consent UIs: known CMP selectors (OneTrust, Cookiebot, Quantcast, TrustArc, Didomi, Sourcepoint, Usercentrics, Osano, Klaro, Complianz, CookieYes — maintain a data file, not hard-coded conditionals), IAB TCF `__tcfapi` presence, and heuristic detection (fixed/sticky element containing consent lexicon + ≥ 1 button). Parse the offered purposes/categories and vendor counts where exposed (TCF stub, CMP config objects, DOM). Compute **dark-pattern signals**: reject option absent from first layer, reject visually de-emphasised (computed style contrast/size/position vs. accept), pre-ticked optional toggles, "legitimate interest" toggles defaulting on, confirmshaming copy, layered "Manage" requiring ≥ 2 clicks to reject. Recommend `Reject optional` by default (configurable). Provide `[Reject optional]` which drives the CMP's reject path programmatically where a known adapter exists (per-CMP adapters in a data-driven table), else highlights the correct control. Integrate the outcome into the site's privacy context (used by FR-8 and Deep Check).
**AC.** (a) Fixture pages for at least 5 CMP layouts plus 3 heuristic banners are detected. (b) Dark-pattern detector flags fixture "hidden-reject" and does not flag fixture "symmetric-choice". (c) Programmatic reject works on ≥ 3 fixture CMP simulations. (d) Banner detection adds < 30 ms to page main-thread time (measured via Playwright tracing).

### FR-6 OS Permission Request Monitoring (desktop)
**Behaviour.** Detect when an application is granted or requests access to camera, microphone, location, contacts, calendar, photos, files/folders (Desktop/Documents/Downloads, removable, network), full disk, accessibility, screen recording, input monitoring, automation (AppleEvents), notifications, and Bluetooth. Compare against the application's inferred purpose (§6.5, desktop variant: bundle/exe metadata, name, publisher, category from App Store/Microsoft Store metadata if available locally, heuristics on name) and the necessity matrix. Explain **why** a permission appears unnecessary. Offer `[Open system settings]` deep link to the exact pane and `[Mark as expected]` (learns per app).
- **macOS adapter:** (1) Subscribe to `log stream --style ndjson --predicate 'subsystem == "com.apple.TCC"'` to observe prompts and decisions in near-real-time; (2) Poll `~/Library/Application Support/com.apple.TCC/TCC.db` and `/Library/Application Support/com.apple.TCC/TCC.db` (`access` table) every 10 s when Full Disk Access has been granted to Privacy Guardian, diffing `auth_value`/`last_modified`; detect FDA absence and guide the user to grant it (surfaced in onboarding and in the tray menu with a status indicator); (3) Screen capture detection cross-process is not possible via `CGPreflightScreenCaptureAccess`; instead observe TCC `kTCCServiceScreenCapture` entries and `log stream` events. Use `pyobjc` frameworks (`Foundation`, `AppKit`, `Quartz`) — no shelling out where an API exists, except `log stream`.
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
- Windows: `AddClipboardFormatListener` for writes; for reads use `GetClipboardSequenceNumber` polling combined with `GetClipboardOwner`; hook detection is not available, so use the same foreground proxy plus the Windows clipboard-history/cloud-sync state (warn if cloud clipboard sync is on and sensitive data was copied).
**AC.** (a) Copying a synthetic credit card number triggers classification `financial.card_number` within 500 ms (platform tests both OSes). (b) Content is never present in the DB or logs (test greps the DB and log files). (c) Warning on foreground switch is suppressed for the writing app and for apps on the user's allow-list.

### FR-10 Screen Capture / Recording Access (desktop)
**Behaviour.** Detect applications granted or actively using screen recording/capture; INTERVENE on first grant for apps whose purpose does not imply screen capture, INFORM when capture becomes active (macOS: TCC `kTCCServiceScreenCapture` + the system's active-capture indicator log events; Windows: `GraphicsCaptureSession`/`CapabilityAccessManager\ConsentStore\graphicsCaptureProgrammatic` and `graphicsCaptureWithoutBorder` keys, `LastUsedTimeStart`).
**AC.** Fixture-driven unit tests for both adapters; one real platform test each.

### FR-11 Decision Engine
**Behaviour.** Implement `engine/` exactly per §7. Deterministic, explainable, unit-testable without UI or OS.
**AC.** (a) Golden-file tests: ≥ 60 scenario YAMLs (`tests/fixtures/scenarios/*.yaml`) each with event, context, preferences, expected outcome and expected rationale keywords (Sol generates these from a template script; do not hand-write 60 files). (b) Property test: raising a category's preference to `always_warn` never lowers the outcome severity. (c) Every INTERVENE carries ≥ 1 actionable option beyond "continue".

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
**Behaviour.** MV3 extension for Chromium (Chrome, Edge, Brave) and Firefox (MV3 with `background.scripts` fallback). Permissions: `nativeMessaging, storage, cookies, webRequest, declarativeNetRequest, scripting, activeTab, tabs`, host permissions `<all_urls>` (Tera writes the store-listing justification). Native host manifests registered for every detected browser on install (macOS: `~/Library/Application Support/<Browser>/NativeMessagingHosts/com.privacyguardian.host.json`; Windows: `HKCU\Software\<Vendor>\NativeMessagingHosts\com.privacyguardian.host` → JSON path). Message protocol: JSON, versioned (`v: 1`), typed with a JSON Schema generated from the Python pydantic models and validated on both sides (`extension/schema/*.json` generated by `make schema`). Reconnect with backoff; extension shows a badge state when disconnected. Load unpacked in dev; produce zip artifacts in `make build-extension`.
**AC.** Playwright launches Chromium with the unpacked extension and the real native host; all browser E2E scenarios in §12 pass headed and headless. Firefox loaded via `web-ext` in a smoke test.

### FR-18 Onboarding
**Behaviour.** First-run wizard: explains what runs locally; requests/guides macOS Full Disk Access and Accessibility (with a live status check and a "Open System Settings" button that deep-links via `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`), guides browser extension install (opens the unpacked/packed instructions or store link), optional LLM key entry, and preference defaults. Can be re-run from the tray.
**AC.** pytest-qt walkthrough; status detection unit tests.

### FR-19 Packaging, Installation, Updates
**Behaviour.** `make build-mac` → `dist/PrivacyGuardian.app` + `dist/PrivacyGuardian-<ver>.dmg` (ad-hoc codesign at minimum; use `codesign --deep --force --sign -`; if a Developer ID identity is present in the keychain, sign and notarise with `notarytool`, driven by env vars). `make build-win` (runs on Windows CI) → `dist/PrivacyGuardian-Setup-<ver>.exe` via Inno Setup, installing the app, registering native hosts, Run key, Start Menu shortcut, and an uninstaller that removes everything including native host registrations. Version is single-sourced from `pyproject.toml`. `Check for updates` reads `https://github.com/<owner>/<repo>/releases/latest` (only on user click).
**AC.** CI uploads both artifacts; a Sol worker installs the mac build on this machine and verifies the tray appears, the native host responds to a handshake, and uninstall (`make uninstall-mac`) leaves no files behind.

### FR-20 Logging, Diagnostics, Resilience
**Behaviour.** `structlog` JSON logs with rotating files; a redaction processor that replaces any string matching a PII detector with `<redacted:category>` before write; log level configurable; crash handler that restarts the service thread and reports via tray; watchdog that restarts the native host bridge; graceful shutdown on SIGTERM/`WM_QUERYENDSESSION`.
**AC.** Redaction unit tests; a test that kills the analysis pool and asserts recovery within 2 s.

---

## 6. Local Analysis Specification

### 6.1 Document extraction
`pypdf` (+ `pdfplumber` for layout/tables) for PDF; `python-docx`, `openpyxl`, `python-pptx`; `chardet` for text; `Pillow` + `piexif` for images/EXIF; **OCR** via Tesseract (`pytesseract`; install `tesseract` via Homebrew / bundle `tesseract` binaries for Windows in the installer, with `eng` traineddata; document how to add languages). Scanned-PDF detection (no text layer → rasterise pages with `pypdfium2` → OCR). Hard cap per document on CPU time (configurable, default 20 s) with partial results flagged.

### 6.2 PII detection
Layered: (1) regex + **validator** layer (Luhn for cards; IBAN mod-97; ABA checksum; UK NHS mod-11; US SSN structural rules; passport MRZ TD3 check digits; email RFC-lite; E.164 and national phone formats via `phonenumbers`; postal addresses via `usaddress`/`pyap` plus heuristics — `libpostal` is **not** required; dates of birth by context words); (2) named-entity layer with **spaCy** `en_core_web_sm` (bundle the model; lazy-load it) for PERSON/GPE/ORG; (3) context boosters (keywords within ±40 chars: "passport", "DOB", "diagnosis", "prescribed", "account number"); (4) **document-type classifier** (rules over keyword densities + layout cues; optional small scikit-learn model trained on the synthetic corpus, persisted in-repo with the training script). Output: `Finding(category, confidence, span_ref, page, validator_passed)`. **Never** return the raw matched value outside the analysis worker; return only category, confidence, and a stable hash for de-duplication.

### 6.3 Form semantics
Map field signals (`autocomplete` tokens, `type`, `name/id` tokens, label text in EN plus a small multilingual lexicon for DE/FR/ES) to `DataCategory` with confidence. Detect "required" via attribute, asterisk, `aria-required`, and visual cues reported by the content script.

### 6.4 Policy & T&C clause extraction
Sentence segmentation (`pysbd`), clause pattern library in YAML (`analysis/policy/patterns/*.yaml`) with positive patterns, negation patterns, and scope words; scoring per clause; section-heading awareness; deduplication; citation of the matched sentence (stored only in the per-origin cache, which contains no user PII). Optional LLM refinement per §8 operates on the **document text only** (public text, no user data).

### 6.5 Purpose inference
A taxonomy of ≥ 40 site/app purpose categories (`image_tool, file_converter, ecommerce, banking, government, healthcare_provider, social, news, recipe, saas_b2b, education, dating, job_board, developer_tool, vpn, wallpaper_utility, screen_recorder, backup, password_manager, …`) each with a **necessity vector** over `DataCategory` (`required | reasonable | unnecessary | red_flag`) and a one-line justification template. Infer purpose from: eTLD+1 against a seed list (`data/known_sites.yaml`, ≥ 300 entries — generate from a curated category list with a script, not by hand), page signals (title, meta, headings, CTA, URL path), and — for desktop — app name/bundle metadata/publisher/category. The LLM may refine purpose when enabled. Purpose and necessity matrix live in `engine/necessity.py` + `data/necessity_matrix.yaml` and are the single source of truth used by every detector.

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

Tera documents the whole thing with worked examples in `docs/DECISION_ENGINE.md`.

---

## 8. LLM Layer (optional, off by default)

- Provider: the **OpenAI Python SDK** (`openai`, latest major). Before writing any SDK code, the Astra sub-agent must read the current SDK documentation for the Responses API and structured outputs; training priors on the API surface are stale.
- Model: configurable; default to the strongest generally available reasoning model at build time. Use **structured outputs** (JSON schema derived from pydantic models) for every call so results are typed. Stream for long policy/T&C documents. Handle the SDK's typed exception chain (rate-limit, status, connection); check for refusals/incomplete outputs before reading content. Enable prompt caching on the stable system prompt + pattern-taxonomy prefix.
- Uses (all behind `settings.llm.enabled`, per-use toggles): (1) policy/T&C clause refinement and plain-language summaries (input: public document text only); (2) purpose inference refinement (input: origin, title, meta, headings — no user content); (3) explanation polishing (input: category names, purpose, necessity verdict — never raw values); (4) Deep Check narrative.
- **Pseudonymisation gate:** a single choke-point function `llm/guard.py::sanitize_outbound(payload) -> payload` runs the PII detector over every outbound string and replaces any match with `<CATEGORY>` tokens; it raises if any validator-confirmed identifier (card, IBAN, SSN, passport) survives. Unit-tested with adversarial fixtures. Log a redacted audit entry for every call (purpose, token counts, latency, no content).
- API key stored via `keyring`; never in config files. Offline behaviour: every feature must produce a correct (if less polished) result without the LLM; tests run with the LLM mocked; one opt-in integration test (`-m llm`) hits the real API when the provider key env var is present.
- Tera documents in `docs/LLM_USAGE.md` exactly what is and is not sent.

---

## 9. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Idle footprint | < 1% CPU average over 5 min idle; < 200 MB RSS idle (spaCy lazy-loaded; OCR only on demand). Measured by a script in `tests/perf/` and reported in `docs/PERFORMANCE.md`. |
| Latency budgets | Form observation → badge ≤ 300 ms; file ≤ 5 MB → decision ≤ 1.5 s; consent banner → verdict ≤ 400 ms; policy 200 KB offline ≤ 2.5 s. |
| Reliability | Service survives extension disconnects, browser restarts, sleep/wake, user switching; no unhandled exceptions escape task boundaries (global asyncio exception handler + Qt `sys.excepthook`). |
| Security | Local socket authenticated by token; native host validates caller extension ID (`allowed_origins`/`allowed_extensions`); no `eval`; DB file 0600; support bundle redacted; dependency audit via `pip-audit` in CI; `bandit` on `src/`. |
| Accessibility | Popup and dashboard keyboard-navigable; screen-reader labels on all controls; contrast ≥ 4.5:1. |
| i18n readiness | All user-facing strings through a `tr()` layer with an `en` catalogue; no hard-coded strings in UI modules. |
| Configurability | `settings.toml` in user-data dir + env overrides; documented in README. |
| Observability | `privacy-guardian --diagnose` prints a redacted status report (platform, permissions status, browsers detected, native host registrations, DB stats). |

---

## 10. Testing Strategy (Sol owns; Astra reviews)

- **Unit** (`tests/unit`): every module; PII validators with positive/negative/edge cases; necessity matrix consistency (every purpose × category defined, no orphans); scenario golden files.
- **Integration** (`tests/integration`): service wiring with fake sensors; native messaging framing over a real socket; DB migrations; LLM client against a recorded-response fake (`respx`).
- **E2E browser** (`tests/e2e`): Playwright (Python) with Chromium + unpacked extension + real native host + real service in a temp user-data dir. Fixture sites are static HTML/JS served by a local `aiohttp` server: `image-compressor`, `government-visa-portal`, `free-pdf-download`, `bank-kyc`, `social-photo`, `tracker-heavy`, `clean-blog`, `hidden-reject-cmp`, `symmetric-choice-cmp`, ≥ 5 CMP simulations, `signup-with-terms`, `spa-dynamic-form`, `shadow-dom-form`. Each scenario in §12 is a test.
- **Platform** (`tests/platform`): marked `macos` / `windows`, skipped elsewhere; run for real in CI on the matching runner and locally on this Mac.
- **UI** (`pytest-qt`), with screenshot artifacts.
- **Perf** (`tests/perf`): budgets from §9; fail if exceeded by > 25%.
- **Synthetic data only.** Sol generates all fixture documents (PDF/DOCX/images with rendered text and EXIF) via scripts in `tests/fixtures/generate/`; identifiers must pass validators but be clearly synthetic (test card numbers from card-network test ranges, fictitious names). Never use real personal data.
- **Windows execution.** Primary path: GitHub Actions `windows-latest` (an Astra sub-agent sets up the remote with `gh` if none exists, pushes `develop`, and wires CI; you verify status via `gh run list`). Secondary path: if a local Windows VM (Parallels/UTM/VMware) is discovered on this machine, use it for interactive Windows verification and have Tera document how. Windows-specific adapters must additionally be unit-tested on macOS through the injected registry/clipboard/task-scheduler abstractions so they are never untested locally.

---

## 11. Schedule (Astra plans; every checkpoint ends with green tests, a review, and a `docs/PLAN.md` update)

This is the default 3-hour plan. Adjust the boundaries in `docs/PLAN.md` at T+0:10 if the machine inspection changes anything, then hold yourself to it.

| Window | Phase | Astra coders (parallel) | Sol workers (parallel) | Tera |
|---|---|---|---|---|
| T+0:00–0:10 | **P0 Plan** | — (inspect machine; write `PLAN.md`, `ARCHITECTURE.md` with all interfaces/contracts) | — | — |
| T+0:10–0:30 | **P1 Skeleton + contracts** | A1: tooling, `uv` project, Makefile, CI, `--diagnose`, tray shows. A2: `core/events.py`, `bus.py`, `config/`, `storage/` schema + migrations, IPC socket + native host framing, `make schema`. | S1: test scaffolding, conftest, fixture generators (synthetic PDF/DOCX/JPEG+EXIF), scenario-YAML generator. S2: E2E harness (aiohttp fixture server, Playwright launcher with extension). | T1: `DEV_SETUP.md`, README skeleton, `ARCHITECTURE.md` prose from your contracts. |
| T+0:30–1:15 | **P2 Engine + analysis + extension** | A3: `engine/*` + `data/necessity_matrix.yaml`, `sensitivity.yaml`, purpose taxonomy + `known_sites.yaml` generator. A4: `analysis/pii`, `documents`, redaction. A5: `analysis/policy`, `consent.py`, `tracking.py`, `forms.py`, `purpose.py`. A6: `extension/*` (all content scripts, background, manifests) + `sensors/browser_bridge.py` + submission holding + redacted-copy flow. | S3: engine golden scenarios + property tests. S4: PII/document tests + T&C/policy corpora (≥15 each, annotated) + F1 tests. S5: consent/tracking/forms fixture pages (all CMP sims) + unit tests. S6: extension/native-host integration tests. | T2: `DECISION_ENGINE.md`, `DETECTORS.md`, `LLM_USAGE.md`, extension README + store text. |
| T+1:15–2:00 | **P3 Desktop + UI + LLM** | A7: macOS adapters (TCC, launch agents, login items, pasteboard, screen). A8: Windows adapters behind injected abstractions (ConsentStore, Run keys, Task Scheduler, clipboard, extensions) + breadth scoring. A9: `ui/*` (popup, tray, Deep Check, dashboard, notifications, hotkey, theme, i18n `tr()`), onboarding, `deepcheck/`. A10: `llm/*` with guard + offline parity. | S7: adapter fixture tests (both OSes, run on mac), platform-marked real tests. S8: pytest-qt suite + screenshots. S9: LLM guard adversarial tests + mocked client tests + preferences/learning tests. | T3: `PLATFORM_LIMITATIONS.md`, `THREAT_MODEL.md`, README feature matrix/install/config sections. |
| T+2:00–2:35 | **P4 Integration + packaging** | A11: wire everything through `service.py`; run full §12 E2E; fix what Sol reports. A12: PyInstaller specs, dmg, Inno Setup, native host (un)registration, auto-start, `make uninstall-mac`, CI artifacts. | S10: §12 scenarios as tests; perf scripts; resilience tests; security scan (`bandit`, `pip-audit`). S11: mac install smoke test. | T4: `PERFORMANCE.md`, `CHANGELOG.md`, README troubleshooting/uninstall. |
| T+2:35–3:00 | **P5 Hardening + acceptance** | Fix-only. Coverage/F1 gaps, i18n pass, redaction audit. | S12: fresh-clone README verification. Full `make check`. | T5: final doc pass; README verification record. |
| T+3:00 | **Checkpoint: initial build complete.** Write the acceptance report. If anything is still red, keep going (rule 3 of the time budget) and report the overrun. | | | |

Within each phase, dispatch all Astra tasks and all Sol tasks **at the same time** against the interfaces in `docs/ARCHITECTURE.md`, so tests exist alongside the code. Tera starts each phase's docs the moment the contracts are fixed. Do not serialise a phase on any single agent.

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

## 13. README.md Requirements (Tera writes; a fresh Sol worker verifies on a clean clone)

Sections, in order: What it is (3 paragraphs, plain language) · Feature matrix (browser vs desktop, macOS vs Windows, offline vs LLM-assisted) · Screenshots (generated from pytest-qt/Playwright, stored in `docs/img/`) · **Requirements** (OS versions, Python 3.12, Tesseract, browsers supported) · **Install from release** (mac dmg steps incl. Gatekeeper right-click-open note for ad-hoc signed builds; Windows installer steps; extension install per browser; macOS Full Disk Access + Accessibility instructions with screenshots) · **Build from source** (exact commands: `brew install …`, `winget install …`, `uv sync`, `make setup`, `make run`, `make build-mac`, `make build-win`, `make build-extension`) · **Run in development** (`make run`, loading the unpacked extension, `--diagnose`, log locations) · **Testing** (`make test`, `make e2e`, markers, how to run platform tests, coverage) · **Configuration** (settings file, every key, env overrides, LLM enablement and what is sent) · **Architecture overview** (link to docs) · **Privacy statement** (what never leaves the machine) · **Platform limitations** (link) · **Troubleshooting** (native host not found, FDA not granted, extension disconnected, Tesseract missing) · **Uninstall** · **License**.

Every command in the README must be copy-pasteable and must have been executed successfully by the verifying Sol worker; record that verification (date, commit SHA) at the bottom of `docs/PLAN.md`.

---

## 14. Delegation Brief Template (use for every sub-agent spawn)

```
TASK <id>: <one-line objective>
MODEL: astra | sol | tera
TIME BOX: <minutes>; report back at the deadline even if incomplete, with what is done and what is not
CONTEXT: read Idea.md §<n>, prompt.md §<n>, docs/ARCHITECTURE.md §<n>, and files: <paths>
SCOPE (files you may create/modify): <explicit list or globs>
OUT OF SCOPE: <explicit>
INTERFACES TO CONFORM TO: <signatures / schemas / table names, verbatim>
REQUIREMENTS: <numbered, testable>
ACCEPTANCE: <commands that must pass, e.g. `uv run pytest tests/unit/analysis/test_pii.py -q`, `uv run mypy src/privacy_guardian/analysis`>
TOOLING: install anything you need without asking (brew/uv/npm/winget); list installs in your report
CONSTRAINTS: no raw PII outside the analysis worker; no network except as specified; Conventional Commit on develop (or your worktree branch) with Co-Authored-By trailer; do not modify files outside SCOPE; do not ask questions this brief answers — make the call and note it
REPORT BACK: summary of changes, commands run with results (verbatim tail), decisions you made, open questions, known gaps
```

For Sol tasks add: `TEST PLAN: one test per AC; fixtures are synthetic; mark platform tests; do not modify src/ — if the code is wrong, write the failing test and report it.`
For Tera tasks add: `SOURCES: derive facts only from docs/ARCHITECTURE.md, the code in SCOPE-adjacent paths, and the sub-agent reports quoted in this brief; mark anything unverified as TODO rather than guessing.`

---

## 15. Review Checklist (Astra applies to every returned task before acceptance — fast, but not skipped)

- Diff confined to SCOPE; no stray files; no secrets; no real PII in fixtures.
- Interfaces match the brief verbatim; pydantic models validated; JSON schemas regenerated if models changed.
- Tests exist for each AC and pass on a **clean** run you executed yourself (`uv run pytest <paths> -q`), not just as claimed.
- `ruff check`, `ruff format --check`, `mypy --strict` clean on touched paths.
- Explanations produced by the engine are plain language, mention purpose and necessity, and are not merely "PII detected".
- Platform code sits behind the adapter interface; the other platform's stub is present and tested.
- Docs updated where behaviour changed (route to Tera); `docs/PLAN.md` status updated at the checkpoint.
- Reject and re-dispatch to the same sub-agent with specific findings when any item fails. Never "fix it up" yourself. Batch small findings into one round-trip rather than several.

---

## 16. Start Sequence

1. Note the start time. Read `Idea.md` and this file completely. Inspect the machine in one pass: `sw_vers`, `uname -m`, `python3 --version`, `which uv brew node tesseract gh`, installed browsers under `/Applications`, presence of a Windows VM, `gh auth status`, `git remote -v`.
2. Produce `docs/PLAN.md` (the §11 schedule with task IDs `P2-A4` style, owner model, dependencies, file scopes, time boxes, and a clock-time checkpoint table) and `docs/ARCHITECTURE.md` (module boundaries, the event model, the message protocol, the adapter interfaces, DB schema) — these are the contracts every Astra coder builds against, every Sol worker tests against, and Tera documents. Spend no more than 10 minutes here; contracts can be amended at a checkpoint.
3. Dispatch P1 immediately: Astra A1 + A2, Sol S1 + S2, Tera T1, all at once. From then on, at every sub-agent return: review, accept or bounce, dispatch the next unblocked task. Never let the pool drain.
4. Do not pause to ask the user anything this document or `Idea.md` answers. Do not ask for permission to install tools, create the GitHub remote, or run installers. If something is truly blocked (e.g. no GitHub auth at all), finish everything that is not blocked, then state precisely what is blocked and why.
5. At T+3:00 (or at completion, whichever is later), write the acceptance report in `docs/PLAN.md` and give the user a concise summary: what was built, elapsed time vs. the 3-hour budget and where time went, evidence (CI run URLs, test counts, coverage, artifact paths), platform limitations, any FR whose numeric target is not yet met and by how much, and anything left blocked.
