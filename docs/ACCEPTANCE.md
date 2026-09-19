# Acceptance map

`tests/ACCEPTANCE.json` is the machine-readable source of the acceptance map. It covers all 20 functional requirements and all 18 end-to-end scenarios; this page makes its current status readable without changing the test contract. Final local headed `make check` evidence at `2af6d4a` is 311 passed and 5 skipped: 277 instrumented passes with four skips and two deselections, plus 34 runtime passes and one skip. Exact line coverage is 85.55% scoped (`1,687/1,972`) and 75.43% overall (`4,136/5,483`).

## Functional requirements

| Requirement | Current mapped evidence | Status |
|---|---|---|
| FR-1 Document uploads | Document unit coverage; upload E2E and package OCR coverage | Implemented; bounded full-text scan passes current gate |
| FR-2 Forms | Form unit coverage; headed browser fixture cases | Implemented and exercised |
| FR-3 Terms | `unit/analysis/test_policy_corpus.py`; terms corpus | Corpus evidence present |
| FR-4 Policies | `unit/analysis/test_policy_corpus.py`; policy corpus | Corpus evidence present |
| FR-5 Consent | Five known CMPs, three heuristic, and three reject cases | Implemented and exercised |
| FR-6 Permissions | Adapter/UI coverage; read-only macOS status check | Implemented; physical grant/revocation pending |
| FR-7 Broad system access | Adapter/platform coverage | Implemented; Windows physical verification pending |
| FR-8 Tracking | DNR/cookie block test preserves cart and IndexedDB | Implemented and exercised |
| FR-9 Clipboard | Real clipboard/spawn-worker timing path | Implemented and exercised |
| FR-10 Screen access | Adapter/platform coverage | Implemented; protected live grant pending |
| FR-11 Decisions | `unit/engine/test_decision.py`; scenarios | Unit evidence present |
| FR-12 Popup | UI coverage and Cocoa screenshots | Implemented and exercised |
| FR-13 Tray | UI coverage and packaged visible-tray smoke | Implemented and exercised |
| FR-14 Deep Check | Exact three-finding integration coverage | Implemented and exercised |
| FR-15 Preferences | preferences and store tests | Unit evidence present |
| FR-16 Event history | store test | Unit evidence present |
| FR-17 Native messaging | IPC transport/protocol tests; Chromium/Firefox handshakes and recovery exercised | Implemented and exercised |
| FR-18 Onboarding | UI coverage and packaged onboarding smoke | Implemented and exercised |
| FR-19 Packaging | Refreshed app/DMG lifecycle: onboarding/tray, protocol-v1 readiness, OCR, uninstall/restoration, codesign, 339 Mach-O slices at macOS 13 | macOS exercised; Windows installer run pending |
| FR-20 Logging/resilience | SIGKILL-mid-analysis abort/service-alive/reconnect coverage; native-host death/result-race regression passed in 14.78 seconds | Implemented and exercised |

## End-to-end scenarios

| Scenario | Current status from `tests/ACCEPTANCE.json` |
|---:|---|
| 1–3 | Upload, redaction, image, and bounded full-text paths are implemented and exercised. |
| 4–5 | Connected form DOM badge measured 137.8 ms; the separate host-side comparison was 252.649 ms. |
| 6–9 | Terms/Deep Check, CMP, and DNR/cookie-block paths exercised. |
| 10 | Real macOS adapter test pending. |
| 11 | Isolated Windows registry adapter coverage exists; final Windows installer/runtime acceptance is pending. |
| 12 | Platform adapter aggregation coverage exercised. |
| 13 | Real clipboard/spawn-worker path exercised; content remains absent from storage/logs by contract. |
| 14 | Exact three-finding Deep Check coverage exercised. |
| 15 | Preference learning and export/import round trip covered. |
| 16 | SIGKILL mid-analysis abort plus service-alive/reconnect exercised. |
| 17 | Current macOS DMG lifecycle exercised; Windows pending. |
| 18 | Final 300-second Cocoa run: 0.823200875 s tray-ready and 0.0442277493% CPU; raw RSS misses 200 MB by 7.33952 MB at median and 10.5344 MB at peak, while the 25% tolerance gate passes. |

The source JSON gives the precise test/fixture names and should be updated with test evidence as implementation lands. The reported verification baseline is recorded in `docs/PLAN.md`; a full acceptance pass is not complete.
