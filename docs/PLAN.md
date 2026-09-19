# Build plan and acceptance record

Start: 2026-09-19 11:49 UTC. Initial deadline: 14:49 UTC. Prompt and Idea remain unchanged.

| Window (UTC) | Phase | Owners / scope | Checkpoint |
|---|---|---|---|
|11:49–11:59 (T+0:00–0:10)|P0 contracts|Astra core: contracts/tooling; Astra analysis: engine design; Sol: test plan|Contracts published|
|11:59–12:19 (T+0:10–0:30)|P1 skeleton|Astra core: config/storage/IPC; Astra analysis: analysis/engine; Sol: fixtures/scaffolding|Typed models and first tests|
|12:19–13:04 (T+0:30–1:15)|P2 analysis + browser|Astra analysis: analyzers/engine/LLM; Astra core: service/platform/UI; Sol: independent suites|Analyzer/engine tests green|
|13:04–13:49 (T+1:15–2:00)|P3 desktop/UI/browser|Astra workers: extension/platform/UI; Sol: integration/platform tests; Tera after slot available: docs|Feature wiring checked|
|13:49–14:24 (T+2:00–2:35)|P4 integration/package|Astra: packaging/CI/integration; Sol: E2E/perf/coverage; Tera: docs|Installers and E2E|
|14:24–14:49 (T+2:35–3:00)|P5 acceptance|Astra fixes; Sol gates/fresh-clone; Tera final docs|Evidence recorded|

## Capacity and constraints

Three worker slots: two Astra implementation workers and one Sol verification worker. Rotate the first completed implementation slot to Tera documentation. No application tests written by Astra. macOS 27 arm64 local environment; Windows real runs pending CI. GitHub authentication verified outside sandbox: Koala-123 has repo scope. Initial sandbox auth failure was misleading. Python 3.12.13 and 153 uv dependencies installed.

## Acceptance status

Contracts and implementation are complete enough for independent acceptance. Current local unit/integration/platform tests and native five-minute idle targets pass. Browser and installer verification continue; scoped coverage remains below85% at the last measurement. No omitted feature is accepted. Timestamped evidence below supersedes earlier checkpoints.

## Task register

|Task|Owner|Scope|Dependencies|Status/evidence|
|---|---|---|---|---|
|P0-A1|Astra core|PLAN/ARCHITECTURE/contracts|none|Published 11:53 UTC; review accepted baseline|
|P1-A1|Astra core|pyproject/uv/Makefile/CI|P0|Python3.12.13 +153 packages installed 11:56 UTC|
|P1-A2|Astra core|core/config/storage/IPC|P0|Accepted foundational tests; IPC 3 passed; ongoing integration hardening|
|P1-S1/S2|Sol|tests/fixtures/scaffolding/browser harness|P0|Implemented; independent suites expand during acceptance|
|P2-A3/A4/A5/A10|Astra analysis|analysis/engine/data/llm|P0|Implemented; corpus, worker, guard and engine tests pass|
|P2-A6|Astra analysis|extension/browser bridge|P1-A2|Implemented; Chromium and Firefox native paths independently exercised|
|P3-A7/A8/A9|Astra core|platform/UI/deepcheck|P1|Implemented 775abab; independent tests in progress|
|P4-A11/A12|Astra core|service integration/packaging|P2/P3|First Mac artifact superseded by compatibility fixes; fresh rebuild/Windows installer pending|
|P1–P5-T1|Tera|documentation|contracts + available slot|Initial docs committed; follow-up verification updates pending|

### P1 interim evidence (12:00 UTC)

Root independently ran `.venv/bin/python -m pytest tests/unit -q`: 58 passed in 0.54s. Core/config/storage/util strict mypy: 16 files clean; ruff clean. Nested environment setting regression fixed after Sol failure. IPC review hardening applied: reject NaN/Infinity, contain bad-auth Windows clients, validate exact caller origin, contain callback exceptions, avoid frozen-host recursion. Tesseract/create-dmg install in progress.

### P1/P2 implementation checkpoint (12:17 UTC, T+0:28)

Foundations commit `b21b4ce` pushed; initial CI run `35441787422` reached both platforms but stopped at Ruff formatting in two files. Formatting corrected; no Windows runtime verification claimed. Root independent tests: 107 passed at Sol checkpoint `662b508`; contextual logging regression fixed and re-run (3 tests passed). Root IPC integration: 3 passed. Source strict mypy currently 70 modules clean.

Installed: uv-managed CPython3.12.13; 154 project/dev packages including spaCy model3.8.0 via locked wheel URL; Tesseract5.5.3 with English/OSD traineddata and create-dmg1.3.0 via Homebrew. OpenAI SDK3.16.2 official API verified by analysis worker; configured default model gpt-6-astra.

First macOS package built at `dist/PrivacyGuardian.app` and `dist/PrivacyGuardian-0.1.0.dmg` (145,079,029 compressed bytes; app268MiB). Root verified deep strict codesign, UDZO imageinfo, isolated offscreen packaged smoke exit0. Bundled OCR runs successfully, non-system libraries rewritten to loader-relative paths. This artifact predates subsequent source changes and must be rebuilt at final acceptance.

Service/UI/platform implementations now present; independent Sol tests being added. Mandatory local analysis remains separate from bounded background cloud I/O, so cloud latency cannot delay native upload/form decisions. Raw worker payloads release on continue/cancel/redaction and expire through idle pool recycle. Remaining review work: full platform native monitoring/revocation, supervisor lifecycle, complete dashboard/settings, CI gates, browser E2E, live platform checks, perf and installer smoke. No feature is accepted merely for existing.

### Review checkpoint (12:25 UTC, T+0:36)

Root independent unit/integration evidence: 157 passed, one logging token-format regression identified; redaction marker corrected to `<redacted:category>` for retest. Source strict mypy70 modules clean. Bandit `-r src -ll -q` clean after replacing whitelist SQL interpolation with fixed statement maps. Coverage from partial suites: 48.04% overall line, 70.91% scoped line; not final and below target, independent UI/platform/E2E/coverage tests are being expanded. Analysis corpus evidence accepted earlier: termsF1=1.0, policy purposesF1=.9048, sharingF1=.9444.

Compatibility audit found Homebrew OCR bottle requires macOS27. Replaced packaging path with a source-built static Tesseract5.5.3 + Leptonica1.87.0 + libpng1.6.58 targeting macOS13. `vtool` verifies minos13.0; `otool` only system libSystem/libz/libc++ dependencies. Initial Qt framework inspection showed minos13.0, but the later complete wrapper audit below found higher requirements and replaced this dependency. First DMG remains superseded until rebuilt.

Remaining acceptance: full browser E2E (including native host and actions), actual platform/native lifecycle tests, full-app five-minute idle measurement, final coverage gates and both installer smoke tests. Windows CI has not passed beyond lint yet; no Windows native verification is claimed.

### Integration checkpoint (12:43 UTC, T+0:54)

Latest coherent source `959e1b2` and independent Sol tests `45e1857` pushed for cross-platform CI. CI surfaced Windows-only typing errors and a Meta shortcut alias regression; both corrected and local strict mypy now passes all70 modules on native and `--platform win32`. Root independently verified38 UI/platform tests (2 platform skips); onboarding availability wording correction pending retest. Static source Ruff and Bandit medium/high gate pass.

Native transport now supports bounded concurrent requests on both platforms, with contained maintenance/listener recovery. Metadata-only forms/consent/tracking use a bounded two-thread executor so file extraction cannot block badges. Raw file/clipboard contents remain solely in the analysis process beyond transport. Document cache retains separate typed policy/terms profiles under origin+text hash, recomputes purpose-dependent necessity, and merges concurrent profile updates after analysis.

Real Chromium+native host handshake and three free-download field badges pass. Dynamic shadow-root inventory currently867.8ms versus required500ms despite discovery fixes; investigating transport startup versus DOM scheduling with Sol. Direct service form analysis45ms cold/under5ms warm. Coverage gate now explicitly measures70% overall line and85% scoped line; packaging smoke continues if only coverage fails, but workflow still fails the final gate. No acceptance threshold has been lowered.

### Native idle and compatibility checkpoint (13:02 UTC, T+1:13)

Root independent actual Cocoa five-minute process-tree measurement passed raw targets: tray ready2.510139708s (<3s),60 samples, initial/peak151.828125MiB (<200), warm median131.65625MiB, final134.109375MiB, cumulative process-tree CPU0.1012557973% (<1%). Exit0. Source at12:57:18 includes Qt6.8.3, compatible NumPy and unchanged-clipboard foreground-query optimization; subsequent native manifest watcher changes require normal regression verification.

A full artifact audit found Qt6.11.2 Python wrappers actually required macOS15 despite Qt framework13, and NumPy selected an optimized macOS14 wheel. Corrected dependency resolution to PySide6==6.8.3 and explicit NumPy2.5.3 cp312 mac11arm64 / mac10_13x64 wheel sources. Direct `vtool` audit of QtCore/Gui/Widgets wrappers, libpyside and shiboken reports min12 on both slices; all selected NumPy native files report min11. Final rebuilt whole-artifact Mach-O audit remains required. `pip-audit --skip-editable`: no known vulnerabilities; spaCy model wheel lacks PyPI audit record and editable application is skipped.

Firefox156 and web-ext installed for Sol-owned real native-host smoke. Qt pytest abort in sandbox (`requires neon`) independently reproduced as sandbox CPU-probe restriction; exact regular test command passes unsandboxed (4 tests). Windows user-only ACLs now supplement POSIX modes for application data/token/database/settings, and isolated-profile uninstall preserves global keychain credentials.

Sol coverage checkpoint207passed3skipped: overall70.37%line passed, scoped75.24%line remains below85%; additional branch/lifecycle tests are in progress. Dynamic Shadow DOM500ms browser assertion now passes, as do terms3warnings/3normal-use checks and recipe policy wording. Large-document timing optimization and full installer lifecycle/Windows CI remain open.

### Runtime and lifecycle checkpoint (13:17 UTC, T+1:28)

Root independently verified236 unit/integration/platform/Mach-O tests passed,3 platform skips. Real Firefox native-host smoke passed in3.02s. Uninstrumented38.2MB representative PDF: cold1.486588s, warm0.163277s, both below3s. Headed Chromium targeted tests: dynamic shadow badge31.9ms (<500), consent instrumentation0.050ms across3 events, actual browser-process SIGKILL persists aborted upload and leaves service responsive. Passport selection-to-intervention remains1.8625s against1.5s and is not accepted; lightweight browser-session worker preparation and generation-aware upload-model preparation are being retested.

Coverage instrumentation materially inflated spawned-worker timings (fresh-clone15.49s versus uninstrumented1.49s). Makefile and CI now run instrumented unit/integration/platform/packaging suites, then the complete uninstrumented E2E/performance suites; both are hard gates, and numeric thresholds remain unchanged. CI test steps have15-minute bounds and60-second Python stack diagnostics. Latest independent coverage expansion is committed by Sol; final aggregate70%/85% line gates pending.

Source checkpoints697337e and Sol f162819 pushed/ready for coherent CI. macOS CI successfully built compatible application and passed packaged diagnose/smoke; installer helper direct-script import defect was found and corrected by Sol. Fresh clone setup/lint/typecheck/diagnose/smoke passed. Main workspace dist still requires final rebuild; no superseded artifact is accepted.
