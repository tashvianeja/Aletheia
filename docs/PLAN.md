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

Root's final independent headed `make check` passes with source `1539390` and tests `aefa972`: 312 tests, with 85.55% scoped and 75.46% overall line coverage. Clean-clone verification before the final liveness/UI fixes passes 307 tests. The native five-minute performance tolerance gate passes, but raw RSS exceeds the 200MB target: median 207.33952MB and peak 210.5344MB. The final dashboard/liveness-enabled macOS artifact passes installed lifecycle, signature and complete macOS13 binary audit. Earlier arm64/Intel CI artifacts also pass installed lifecycles. Windows built its installer but failed test/verification infrastructure checks; corrections are committed, while final-source hosted verification is blocked by GitHub account billing. Timestamped evidence below supersedes earlier checkpoints.

## Task register

|Task|Owner|Scope|Dependencies|Status/evidence|
|---|---|---|---|---|
|P0-A1|Astra core|PLAN/ARCHITECTURE/contracts|none|Published 11:53 UTC; review accepted baseline|
|P1-A1|Astra core|pyproject/uv/Makefile/CI|P0|Python3.12.13 +153 packages installed 11:56 UTC|
|P1-A2|Astra core|core/config/storage/IPC|P0|Final local gate passes, including native host liveness and actual browser SIGKILL recovery|
|P1-S1/S2|Sol|tests/fixtures/scaffolding/browser harness|P0|Implemented; independent suites expand during acceptance|
|P2-A3/A4/A5/A10|Astra analysis|analysis/engine/data/llm|P0|Implemented; corpus, worker, guard and engine tests pass|
|P2-A6|Astra analysis|extension/browser bridge|P1-A2|Implemented; Chromium and Firefox native paths independently exercised|
|P3-A7/A8/A9|Astra core|platform/UI/deepcheck|P1|Implemented; independent UI/native tests pass locally, Windows final CI pending|
|P4-A11/A12|Astra core|service integration/packaging|P2/P3|Final source2af6d4a Mac artifact/lifecycle verified; repaired Windows installer pending|
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

### Final macOS artifact checkpoint (13:36 UTC, T+1:47)

Main source frozen at `edeb15d`; later `b28416d` changes only the acceptance evidence. `.venv/bin/python scripts/build.py mac` completed successfully, replacing the superseded main app and DMG. The complete Mach-O audit checks 339 slices/files and reports highest minimum macOS 13.0. `tests/packaging/verify_packaged_installation.py --platform macos --artifact dist/PrivacyGuardian-0.1.0.dmg --maximum-macos 13.0` passed installed onboarding/tray readiness, genuine framed native-host handshake (version 0.1.0/protocol 1), bundled PNG/native JPEG OCR, uninstall and registration restoration. Fresh clone independently built from source and passed the same lifecycle at `3bec889` before the final clipboard race fix.

Whole-tree Ruff lint/format: 172 files pass. Native and Windows strict mypy: 73 modules pass; Bandit medium/high gate clean. Sol authoritative pre-final line coverage: 85.09% scoped, 74.52% overall; final root `make check` rerun pending. Connected headed browser evidence: native bridge ready 1.354564s (<5), passport DOM change-to-visible 1.095s (<1.5), host-side comparison 1.327781s, field badge 238.983ms (<300), consent mutation 213.5ms (<400). Cold first-action measurements included bridge startup and ranged 2.386–2.834s; these remain separately recorded rather than hidden. Real native clipboard plus spawned worker 185.746ms (<500); clear/write race has a dedicated passing regression.

Lightweight worker retention changed since the earlier accepted idle measurement, so root is reserving a fresh five-minute native Cocoa process-tree run now. No heavy local work during that window. Windows/Intel CI installer acceptance remains pending; latest source includes bounded AF_PIPE envelope authentication, bounded test teardown, split instrumented coverage/uninstrumented latency gates, and corrected artifact audit parsing.

### Final idle and text coverage checkpoint (13:45 UTC, T+1:56)

Root completed the uncontended native Cocoa 300-second measurement with 60 samples: tray readiness 0.823200875s, initial RSS 200.5MiB (210.239488MB), warm median 197.734375MiB (207.33952MB), peak 200.78125MiB (210.5344MB), final 192.78125MiB (202.145792MB), whole-process-tree CPU 0.0442277493%. The specified 25% tolerance gate passed; the raw median and peak exceed the prompt's decimal 200MB target and are explicitly retained here.

Review found ordinary text still used the expanded-document 2M-character cap. Plain-text extraction now scans the complete bounded input through 50MiB; worker text uses the same UTF-8 byte threshold and explicitly marked first/last 5MiB sampling above it. PDF/Office expansion, archive, image, page and time guards remain bounded. Sol tail-only PII regressions and final root `make check` are pending. This extraction-only change requires a refreshed package but does not alter the measured idle lifecycle.

Full-content profiling measured 869ms extraction/classification and 1441ms PII. Replacing literal regular-expression searches with substring checks and normalizing case once reduced extraction to 303ms while preserving all content and NER. Cold full 5MiB diagnostic total is 1.762s: above the raw 1.5s target by 17.5%, inside its 1.875s tolerance gate. Sol's independent retest is required before acceptance.

Sol independent retest at `1725a02`: five full-text correctness tests pass, including an email only at the end of a 5MiB file and worker text beyond 2M characters, with `partial=False`. Exclusive cold full-text timing is 1.822472s, inside 1.875s and above the raw 1.5s target. Native clipboard timing is now excluded from coverage and explicitly included in the uninstrumented runtime suite.

CI `35446163637` macOS arm64 built and passed the installed package lifecycle. Its final enforcement failed because continued test steps contain timing failures (coverage-instrumented clipboard 0.537275s, bridge readiness 5.146072s, passport 1.5148s); step conclusions alone must not be treated as test acceptance. Scoped line coverage is 85.66% (1666/1945). Native timing is moving to the uninstrumented phase and the prompt's allowed 25% performance gate tolerance will be applied consistently while retaining raw target measurements. Windows runtime and Intel package completion remain under review.

### Independent full check and cross-platform corrections (13:56 UTC, T+2:07)

Root's exact `PRIVACY_GUARDIAN_E2E_HEADED=1 QT_QPA_PLATFORM=offscreen make check` passed at `7fb6b07`: Ruff 173 files, strict mypy 73 modules, instrumented 270 passed / 4 skipped / 2 timing tests deselected, uninstrumented headed browsers/performance/native clipboard 34 passed / 1 platform skip. Line gates: scoped 1667/1945 = 85.71%; overall 4107/5448 = 75.39%.

Intel CI uncovered an additional incompatible binary: cryptography 50.0.1 has no Intel wheel, so its source build linked Homebrew OpenSSL and bundled a legacy provider requiring macOS15. The Intel package lifecycle stopped at the binary audit and did not pass. Build now compiles checksum-pinned OpenSSL3.5.8 LTS statically for macOS13 and rebuilds current cryptography, preserving legacy PDF ciphers; actual Intel CI audit remains required. Downgrading to the last universal wheel was rejected because that release has a known certificate-verification vulnerability.

Intel timing also exposed repeated policy paragraph segmentation. Exact per-call paragraph caching preserves every occurrence and heading without retaining raw content globally. Root corpus/performance checks pass (205KB 0.306559s), and Sol's duplicate-heading/cache-bound/isolation tests pass. Latest source/tests/docs `d3390ba` are pushed; clean-clone check is running. Superseded CI runs are cancelled to prioritize the final run, while the older Windows job is preserved for its runtime-timeout diagnostics and installer evidence.

Clean-clone `make check` at `d3390ba` subsequently passed 273 instrumented plus 34 runtime tests (307 total, 5 platform skips), scoped 85.71% and overall 75.42%. Main final app/DMG and both extension archives rebuilt successfully at 14:00 UTC; installed lifecycles are serialized after the clone build. Tera's pending final documentation pass must replace obsolete cold-start/benchmark disclaimers with the measured evidence, preserve decimal-MB target misses, report the passing 205KB policy timing, and document Rust/Cargo plus static OpenSSL build requirements on Intel macOS.

### Native termination and hosted-runner checkpoint (14:19 UTC, T+2:30)

The final main and clone macOS lifecycles both passed with whole-artifact audits of 339 Mach-O slices, maximum minimum OS13.0. Intel CI then passed the corrected static-crypto build and installed lifecycle; its remaining runtime miss was passport decision 2125.7ms against the 1875ms tolerance gate. Windows verification identified missing dynamically imported ACL modules in frozen executables and unbounded Firefox-test process cleanup. Both were repaired and pushed in `4d20bde`; that hosted run remains active.

A stronger real mixed-PDF SIGKILL regression exposed completion before the five-second orphan lease. Source `2af6d4a` binds native sessions to host PID plus creation time, checks exact process liveness before publishing, and disconnects before draining EOF work. Sol's actual browser-tree kill regression passed in14.73s, and root independently passed it in14.78s. Focused live/dead/reused-PID and cleanup tests pass. Root's final headed full check is running; a refreshed macOS artifact remains required for this source change.

Final hosted run [35448338656](https://github.com/tashvianeja/Privacy-Guardian/actions/runs/35448338656) could not start any job. GitHub's annotation states that recent account payments failed or the spending limit must be increased in Billing & plans. This is an external account blocker, not a test result; no final cross-platform green CI claim is made. Existing running jobs are preserved for their remaining Windows/Intel evidence.

### Final independent local gate (14:22 UTC, T+2:33)

Root's exact headed full check at source `2af6d4a` passes: Ruff 176 files, strict mypy 73 modules; 277 instrumented tests pass with 4 platform skips and 2 timing tests deselected (42.54s); 34 real browser/performance/native clipboard tests pass with 1 platform skip (104.11s). Total 311 passed / 5 skipped. Required scoped line coverage is 1687/1972 = 85.55%; overall 4136/5483 = 75.43%. No application tests were authored by Astra. Final main macOS rebuild, signature/audit/lifecycle/checksum are in progress; extension archives have been refreshed.

### Final local artifact (14:27 UTC, T+2:38)

The final source `2af6d4a` main macOS build completed successfully. Root independently verified deep strict code signing and all 339 Mach-O slices/files, with highest minimum macOS13.0. The installed DMG lifecycle completed with exit0, including visible onboarding/tray, native version0.1.0/protocol1 ready response, bundled PNG and native JPEG OCR, uninstall and registration restoration. Durable output is `/private/tmp/pg-main-liveness-lifecycle.log`; build output is `/private/tmp/pg-main-liveness-build.log`.

Final SHA256 digests:

|Artifact|SHA256|
|---|---|
|`dist/PrivacyGuardian-0.1.0.dmg`|`31dc9c46582b48b2c7448eb6fe268eeef85ec1c27026c3d04f0502fbcfffeb08`|
|`dist/privacy-guardian-chromium.zip`|`414f6cedb7221ed3594730c1d0e1f8abf6035d6895d26a9f4a5f30cb0c7ee42f`|
|`dist/privacy-guardian-firefox.zip`|`bbadfc4e4fcf6348f2465ec2155a2aeafae16de84bfb42632cd1e69d04e875d2`|

The repaired Windows checkpoint `4d20bde` completed its installer build. Its arm64 job completed 276 instrumented tests and passed the packaged lifecycle, but final enforcement failed because cold native-bridge setup took6.552899s against the6.25s tolerance gate. This historical hosted result is distinct from the green current-source local suite. Intel's earlier corrected static-crypto artifact passed its full installed lifecycle, while its passport runtime measurement2125.7ms exceeded1875ms. Final-source hosted jobs remain blocked before execution by account billing; cross-platform acceptance is not declared complete.

### Windows failure triage (14:30 UTC, T+2:41)

[Run35448070182, Windows job105910359890](https://github.com/tashvianeja/Privacy-Guardian/actions/runs/35448070182/job/105910359890) built the installer and printed successful packaged diagnostic JSON, including available OCR and registry monitoring. The workflow then treated an unreliable windowed-executable `$LASTEXITCODE` as failure before entering installed lifecycle. Source1539390 uses `Start-Process -Wait -PassThru` and its explicit exit code. The artifact exists, but Windows installed lifecycle remains unverified.

Instrumented Windows tests:273 passed,2 failed,5 skipped,2 timing deselected. Failures were a test calling nonexistent `win32security.EqualSid` and a dashboard timer reading a fixture's closed database. Production dashboard refresh now runs only while shown and stops before service shutdown; Sol owns its regression. Runtime29 passed,1 failed,1 skipped,27 errors: repeated fixture teardown retained SQLite connections and service processes, with later browser setup and policy timing affected by accumulated contention. Sol is correcting resource ownership rather than suppressing cleanup failures. Historical line coverage was83.34% scoped (1621/1945) and75.37% overall (4112/5456), before the latest native-host/PID tests. No Windows latency or full-suite acceptance is inferred from this run. The final hosted rerun remains blocked by account billing.

### Final source verification (14:35 UTC, T+2:46)

Sol's resource-ownership corrections and dashboard visibility regression are committed in `aefa972`; implementation `1539390` stops refresh when hidden and closes the dashboard before service shutdown. Root independently reran the exact headed full gate: Ruff176 files, strict mypy73 modules;278 instrumented tests pass /4 platform skips /2 timing deselections in42.31s;34 uninstrumented runtime tests pass /1 platform skip in101.30s. Total312 passed /5 skipped. Scoped line coverage1687/1972=85.55%; overall4144/5492=75.46%.

[Final checkpoint run35449032544](https://github.com/tashvianeja/Privacy-Guardian/actions/runs/35449032544), head `aefa972`, again started no jobs because GitHub reports failed account payments or a spending-limit issue. This is the latest blocked verification URL; no manual rerun or billing change was attempted. The main macOS artifact is rebuilding from the accepted final source, with log `/private/tmp/pg-main-dashboard-build.log`.

### Final artifact refresh (14:37:13 UTC, T+2:48:13)

Final implementation `1539390` plus independent tests `aefa972` is frozen. The refreshed main macOS build and installed lifecycle both exit0. Root independently verifies deep strict signature and339 Mach-O slices/files with maximum minimum macOS13.0. `/private/tmp/pg-main-dashboard-lifecycle.log` records visible onboarding/tray, native version0.1.0/protocol1 ready handshake, bundled PNG/native JPEG OCR, uninstall and restored registrations. Final DMG SHA256 is `85b4ac8513e34bfeb9df37129abd19f4706176073ea6166c7a1122df801b66ad`, superseding the14:27 artifact. Both extension hashes above remain unchanged.

Elapsed local implementation/verification time at this checkpoint is2h48m13s. Local acceptance and macOS packaging are complete; all-platform acceptance remains incomplete because corrected Windows verification cannot execute under the hosted account billing block. The older4d20bde Intel job is still building and cannot establish final-source acceptance even if it later passes.

### Final-source clean-clone verification (14:41 UTC, T+2:52)

Sol fast-forwarded the independent clean clone to `aefa972` and ran literal headless `make check` against the final implementation. It passed312 tests /5 platform skips:278 instrumented tests in42.74s (2 timing tests deselected only in that phase), plus34 uninstrumented runtime tests in94.05s. Ruff176 files and strict mypy73 modules pass. Scoped line coverage remains1687/1972=85.55%; overall4143/5492=75.44%, one executed line below root's75.46% measurement. Thus final-source fresh-clone verification supersedes the earlier307-test baseline. No additional application change or rebuild is required.

### Completed historical Intel job (14:43 UTC, T+2:54)

[Run35448070182, Intel job105910359735](https://github.com/tashvianeja/Privacy-Guardian/actions/runs/35448070182/job/105910359735), source `4d20bde`, completed its static-crypto build and installed lifecycle successfully at14:40:13. Coverage passed:1666/1945=85.66% scoped and4116/5456=75.44% overall. The job nevertheless failed final enforcement:275 instrumented tests passed with one10-second read-only permission-query subprocess timeout,4 skips and2 timing deselections;33 runtime tests passed with one passport DOM latency failure3115.4ms against1875ms tolerance and1 skip. This older Intel artifact is verified for installation/macOS13 compatibility, not accepted for all runtime targets. The final source retains green local and fresh-clone gates; hosted verification remains blocked before execution at run35449032544.
