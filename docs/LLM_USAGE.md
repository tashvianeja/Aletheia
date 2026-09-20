# Model usage

## On-device models (always local, always on)

Two models run on this machine and never contact a network. Neither is affected by the
cloud settings below.

| Model | Where | What it does |
|---|---|---|
| spaCy `en_core_web_sm` | analysis worker | Named-entity recognition inside the PII detector |
| MiniLM-L6 sentence encoder, int8 ONNX (~23 MB on disk, ~95 MB resident) | service process, lazy | Infers what a form is for, so necessity is judged against the transaction rather than the site's industry |

The encoder is loaded on the first form judged and released after 90 idle seconds. Its
input is page copy — heading, submit label, legend, nearby text, title — never field
values. It ships as a build input fetched and checksummed by `scripts/fetch_model.py`;
when it is missing, form judgement falls back to structural inference and reports less
rather than reporting wrongly. `docs/DECISION_ENGINE.md` describes how its output is used.

## Optional cloud assistance

## Default and opt-in

The optional provider is Google's Gemini API, through the `google-genai` SDK.

Cloud assistance is disabled by default (`llm.enabled = false`). The code default model is `gemini-flash-latest`. Settings offers a closed list of the current Gemini Flash models (checked against the published model list on 2026-09-20); the Flash tier is the one whose cost and latency suit a few short structured requests per page. **Test** in Settings sends one minimal structured request with the key and model currently on screen; on success it replaces the list with the text-answering Flash models that key can actually call (`models.list()`, filtered to those supporting `generateContent`, then to Flash variants that are not image, audio, live or TTS models). No model identifier in this repository has been confirmed against a live account: the Test button exists so that you confirm it against yours.

When explicitly enabled, four independently configurable uses exist: policy refinement, purpose refinement, explanation polishing, and Deep Check narrative. Every local feature retains an offline fallback. A disabled toggle or unavailable credential/API returns the fallback with a reason instead of failing the local assessment. No live API key or live provider request was used for this build’s verification; `tests/integration/test_llm_live.py` performs one when `PRIVACY_GUARDIAN_RUN_LLM_TEST=1` and `GEMINI_API_KEY` are both set.

## What may be sent

| Use | Allowed input | Explicitly excluded |
|---|---|---|
| Policy refinement | Public policy or terms document text | User-provided content and raw PII |
| Purpose refinement | Origin, page title, metadata, headings, CTA, and path signals | Form values, uploads, URL query strings |
| Explanation polish | Category names, purpose, necessity, outcome context | Raw values and action-changing instructions |
| Deep Check narrative | Sanitized category-level findings and clean checks | Raw document/form/clipboard contents |

Before any request, `sanitize_outbound()` normalizes text, decodes URL encoding, repeatedly redacts detected values, and rejects a payload when a validator-confirmed card, IBAN, SSN, passport, or comparable identifier survives. Numeric identifiers are replaced. The same sanitization is applied to typed response content before it is used. This is defense in depth, not a promise that an external model sees no non-sensitive public text.

## Credential, request, and logging behavior

The key is read from the OS keychain service `PrivacyGuardian`, account `gemini_api_key`. The SDK would otherwise take its credential from `GEMINI_API_KEY` or `GOOGLE_API_KEY` and its endpoint from `GOOGLE_GEMINI_BASE_URL`; the client passes `api_key`, `vertexai=False` and `base_url` explicitly so none of those environment variables can redirect a request. Calls run in a lazy, separate one-worker process against `generateContent` with a Pydantic `response_schema` and `response_mime_type: application/json`, a pinned base URL, a 20-second timeout, and the SDK's five automatic retries reduced to a single attempt — an assessment that has already fallen back locally must not keep trying in the background. Automatic function calling is disabled. The implementation records only purpose, token count, latency, and fallback reason in its audit log, not request content.

Unlike the previous provider there is no per-request "do not store" flag to set; what Google retains is governed by the terms of the account whose key you supply, and the free tier and paid tier differ. Review those terms before enabling this.

The single outbound guard runs inside that optional process. It treats supplied documents as untrusted data, requires a schema-only response, preserves uncertainty/negation, and cannot lower deterministic risk or replace the recommended action. It handles refusal, incomplete results, timeout, connection, status, rate-limit, keychain, and validation failures by falling back locally. A `SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT` or `SPII` finish reason is treated as a refusal, and `MAX_TOKENS` as an incomplete answer, so a truncated object is never mistaken for a complete one. Structured output follows [Gemini's structured-output guide](https://ai.google.dev/gemini-api/docs/structured-output).

## Operational limitations

LLM paths have mocked/unit coverage, and `tests/integration/test_llm_live.py` holds two opt-in tests that make a real Gemini request; neither has been run against a live key in this repository, so no model identifier here is confirmed to exist on any particular account. Settings → **Test** is the supported way to confirm a key and model before relying on them. Enabling a cloud feature changes the data boundary described above; use it only after reviewing the specific payload and provider terms for your deployment.
