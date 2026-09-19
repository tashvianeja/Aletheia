# Acceptance map

`tests/ACCEPTANCE.json` is the machine-readable source of the acceptance map. It covers all 20 functional requirements and all 18 end-to-end scenarios; this page makes its current status readable without changing the test contract. The verified coverage checkpoint is 85.09% scoped and 74.52% overall. One run reported 260 passed, 4 skipped, and one transient permission-status timeout that passed in an isolated 0.51-second retry; final counts remain pending.

## Functional requirements

| Requirement | Current mapped evidence | Status |
|---|---|---|
| FR-1 Document uploads | Document unit coverage; upload E2E and package OCR coverage | Implemented; raw-passport timing target pending |
| FR-2 Forms | Form unit coverage; headed browser fixture cases | Implemented; final browser count pending |
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
| FR-17 Native messaging | IPC transport/protocol tests; Chromium native-host handshake verified | Partial |
| FR-18 Onboarding | UI coverage and packaged onboarding smoke | Implemented and exercised |
| FR-19 Packaging | Clean-clone app/DMG/install/OCR/uninstall audit | macOS exercised; Windows installer pending |
| FR-20 Logging/resilience | SIGKILL-mid-analysis abort/service-alive/reconnect coverage | Implemented and exercised |

## End-to-end scenarios

| Scenario | Current status from `tests/ACCEPTANCE.json` |
|---:|---|
| 1–3 | Upload, redaction, and image paths are implemented; raw passport remains above its 1.5-second timing target. |
| 4–5 | Headed form/browser cases exercised; final case totals pending. |
| 6–9 | Terms/Deep Check, CMP, and DNR/cookie-block paths exercised. |
| 10 | Real macOS adapter test pending. |
| 11 | Injected Windows adapter and Windows CI pending. |
| 12 | Platform adapter aggregation pending. |
| 13 | Real clipboard/spawn-worker path exercised; content remains absent from storage/logs by contract. |
| 14 | Exact three-finding Deep Check coverage exercised. |
| 15 | Preference learning and export/import round trip covered. |
| 16 | SIGKILL mid-analysis abort plus service-alive/reconnect exercised. |
| 17 | Fresh-clone macOS DMG install/onboarding/handshake/OCR/uninstall exercised; Windows pending. |
| 18 | Corrected five-minute Cocoa baseline meets targets; final light-worker re-measurement pending. |

The source JSON gives the precise test/fixture names and should be updated with test evidence as implementation lands. The reported verification baseline is recorded in `docs/PLAN.md`; a full acceptance pass is not complete.
