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

P0: contracts complete and baseline accepted. All functional requirements and numeric targets unverified until independently tested. No omitted feature is accepted. Record commands, counts, coverage, artifacts, commit IDs, platform gaps and elapsed time below at each checkpoint.

## Task register

|Task|Owner|Scope|Dependencies|Status/evidence|
|---|---|---|---|---|
|P0-A1|Astra core|PLAN/ARCHITECTURE/contracts|none|Published 11:53 UTC; review accepted baseline|
|P1-A1|Astra core|pyproject/uv/Makefile/CI|P0|Python3.12.13 +153 packages installed 11:56 UTC|
|P1-A2|Astra core|core/config/storage/IPC|P0|Accepted foundational tests; IPC 3 passed; ongoing integration hardening|
|P1-S1/S2|Sol|tests/fixtures/scaffolding/browser harness|P0|In progress|
|P2-A3/A4/A5/A10|Astra analysis|analysis/engine/data/llm|P0|In progress|
|P2-A6|Astra analysis|extension/browser bridge|P1-A2|Implemented 98f952c; browser E2E pending|
|P3-A7/A8/A9|Astra core|platform/UI/deepcheck|P1|Implemented 775abab; independent tests in progress|
|P4-A11/A12|Astra core|service integration/packaging|P2/P3|First Mac app+DMG verified; final rebuild/Windows installer pending|
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

Compatibility audit found Homebrew OCR bottle requires macOS27. Replaced packaging path with a source-built static Tesseract5.5.3 + Leptonica1.87.0 + libpng1.6.58 targeting macOS13. `vtool` verifies minos13.0; `otool` only system libSystem/libz/libc++ dependencies. Qt6.11.2 binary inspected for arm64+x86_64: minos13.0. First DMG remains superseded until rebuilt with static OCR.

Remaining acceptance: full browser E2E (including native host and actions), actual platform/native lifecycle tests, full-app five-minute idle measurement, final coverage gates and both installer smoke tests. Windows CI has not passed beyond lint yet; no Windows native verification is claimed.
