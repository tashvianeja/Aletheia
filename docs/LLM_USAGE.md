# Optional LLM usage

## Default and opt-in

Cloud assistance is disabled by default (`llm.enabled = false`). The current code default model is `gpt-6-astra`. The model identifier was checked against the [OpenAI models documentation](https://developers.openai.com/api/docs/models/gpt-6-astra); no live API request was made as part of this build.

When explicitly enabled, four independently configurable uses exist: policy refinement, purpose refinement, explanation polishing, and Deep Check narrative. Every local feature retains an offline fallback. A disabled toggle or unavailable credential/API returns the fallback with a reason instead of failing the local assessment. No live API key or live provider request was used for this build’s verification.

## What may be sent

| Use | Allowed input | Explicitly excluded |
|---|---|---|
| Policy refinement | Public policy or terms document text | User-provided content and raw PII |
| Purpose refinement | Origin, page title, metadata, headings, CTA, and path signals | Form values, uploads, URL query strings |
| Explanation polish | Category names, purpose, necessity, outcome context | Raw values and action-changing instructions |
| Deep Check narrative | Sanitized category-level findings and clean checks | Raw document/form/clipboard contents |

Before any request, `sanitize_outbound()` normalizes text, decodes URL encoding, repeatedly redacts detected values, and rejects a payload when a validator-confirmed card, IBAN, SSN, passport, or comparable identifier survives. Numeric identifiers are replaced. The same sanitization is applied to typed response content before it is used. This is defense in depth, not a promise that an external model sees no non-sensitive public text.

## Credential, request, and logging behavior

The key is read from the OS keychain service `PrivacyGuardian`, account `openai_api_key`; environment API keys and configurable base URLs are intentionally not read by this client. Requests run in a lazy, separate one-worker process and use the OpenAI Responses API with typed structured output, `store: false`, a fixed OpenAI API base URL, a 20-second timeout, zero SDK retries, and a stable prompt-cache key. The implementation records only purpose, token count, latency, and fallback reason in its audit log, not request content.

The single outbound guard runs inside that optional process. It treats supplied documents as untrusted data, requires a schema-only response, preserves uncertainty/negation, and cannot lower deterministic risk or replace the recommended action. It handles refusal, incomplete results, timeout, connection, status, rate-limit, keychain, and validation failures by falling back locally. The use of structured output follows [OpenAI’s structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Operational limitations

LLM paths have mocked/unit coverage in the build work, but a real provider call and opt-in integration test are pending. Enabling a cloud feature changes the data boundary described above; use it only after reviewing the specific payload and provider terms for your deployment.
