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

P0: in progress. All functional requirements and numeric targets unverified until independently tested. No omitted feature is accepted. Record commands, counts, coverage, artifacts, commit IDs, platform gaps and elapsed time below at each checkpoint.

## Task register

|Task|Owner|Scope|Dependencies|Status/evidence|
|---|---|---|---|---|
|P0-A1|Astra core|PLAN/ARCHITECTURE/contracts|none|Published 11:53 UTC; review accepted baseline|
|P1-A1|Astra core|pyproject/uv/Makefile/CI|P0|Python3.12.13 +153 packages installed 11:56 UTC|
|P1-A2|Astra core|core/config/storage/IPC|P0|Implemented; independent tests pending|
|P1-S1/S2|Sol|tests/fixtures/scaffolding/browser harness|P0|In progress|
|P2-A3/A4/A5/A10|Astra analysis|analysis/engine/data/llm|P0|In progress|
|P2-A6|Astra worker TBD|extension/browser bridge|P1-A2|Pending dispatch|
|P3-A7/A8/A9|Astra core|platform/UI/deepcheck|P1|Pending dispatch|
|P4-A11/A12|Astra core|service integration/packaging|P2/P3|Pending|
|P1–P5-T1|Tera|documentation|contracts + available slot|Pending|

### P1 interim evidence (12:00 UTC)

Root independently ran `.venv/bin/python -m pytest tests/unit -q`: 58 passed in 0.54s. Core/config/storage/util strict mypy: 16 files clean; ruff clean. Nested environment setting regression fixed after Sol failure. IPC review hardening applied: reject NaN/Infinity, contain bad-auth Windows clients, validate exact caller origin, contain callback exceptions, avoid frozen-host recursion. Tesseract/create-dmg install in progress.
