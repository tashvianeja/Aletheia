# Acceptance map

`tests/ACCEPTANCE.json` is the machine-readable source of the acceptance map. It covers all 20 functional requirements and all 18 end-to-end scenarios; this page makes its current status readable without changing the test contract.

## Functional requirements

| Requirement | Current mapped evidence | Status |
|---|---|---|
| FR-1 Document uploads | `unit/analysis/test_documents.py`; image-compressor fixture | Unit evidence present; browser E2E pending |
| FR-2 Forms | `unit/analysis/test_forms.py`; free-PDF/bank fixtures | Unit evidence present; browser E2E pending |
| FR-3 Terms | `unit/analysis/test_policy_corpus.py`; terms corpus | Corpus evidence present |
| FR-4 Policies | `unit/analysis/test_policy_corpus.py`; policy corpus | Corpus evidence present |
| FR-5 Consent | E2E fixture plus pending consent unit test | Pending verification |
| FR-6 Permissions | Pending platform adapter test | Pending |
| FR-7 Broad system access | Pending platform adapter test | Pending |
| FR-8 Tracking | Tracker fixture plus pending tracking unit test | Pending verification |
| FR-9 Clipboard | Pending clipboard adapter test; store test | Partial |
| FR-10 Screen access | Pending platform adapter test | Pending |
| FR-11 Decisions | `unit/engine/test_decision.py`; scenarios | Unit evidence present |
| FR-12 Popup | Pending UI popup test | Pending |
| FR-13 Tray | Pending UI tray test | Pending |
| FR-14 Deep Check | Pending integration test | Pending |
| FR-15 Preferences | preferences and store tests | Unit evidence present |
| FR-16 Event history | store test | Unit evidence present |
| FR-17 Native messaging | IPC transport/protocol tests; real extension pending | Partial |
| FR-18 Onboarding | Pending UI onboarding test | Pending |
| FR-19 Packaging | Pending package smoke tests | Pending |
| FR-20 Logging/resilience | logging test; resilience pending | Partial |

## End-to-end scenarios

| Scenario | Current status from `tests/ACCEPTANCE.json` |
|---:|---|
| 1–3 | Fixtures/document or redaction coverage present; real extension/service flow pending. |
| 4–5 | Form semantics and fixtures present; browser path pending. |
| 6–9 | Terms/policy/CMP/tracker fixtures exist; browser interception/action pending. |
| 10 | Real macOS adapter test pending. |
| 11 | Injected Windows adapter and Windows CI pending. |
| 12 | Platform adapter aggregation pending. |
| 13 | Persistence redaction covered; clipboard adapter pending. |
| 14 | Fixture context present; Deep Check integration pending. |
| 15 | Preference learning and export/import round trip covered. |
| 16 | Browser/service resilience integration pending. |
| 17 | Built installer artifacts pending. |
| 18 | Cold-start and idle measurements pending. |

The source JSON gives the precise test/fixture names and should be updated with test evidence as implementation lands. The reported verification baseline is recorded in `docs/PLAN.md`; a full acceptance pass is not complete.
