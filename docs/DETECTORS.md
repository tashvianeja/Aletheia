# Detector scope

## Local analysis boundary

`analysis.worker.analyze_payload()` owns raw payload analysis. Its result exposes category findings, confidence, validator status, stable hashes, document type, partial/warning state, structured profiles, and opaque handles. Findings deliberately exclude matched values.

Raw bytes may move through the native transport during an active file upload. They are discarded after use and are not intended to enter the engine, persistent store, or logs. Handle lifetime is bounded in worker memory; the redaction path consumes the handle.

## PII and document detection

The detector combines regular expressions, validators, contextual patterns, and optional lazy spaCy named-entity recognition. Implemented validators include Luhn cards, IBAN mod-97, ABA routing numbers, NHS mod-11, US SSN structure, and passport MRZ checks. Regex/context detection covers names, email, phones, addresses, dates of birth, government IDs, financial identifiers, medical phrases, private keys, and API keys.

Document extraction supports PDF, DOCX, XLSX, PPTX, text-like files, and images. It looks for image metadata and can invoke Tesseract OCR, including for scanned PDF pages. Extraction has a configurable deadline; partial results/warnings must be surfaced instead of being represented as complete. The current default is 20 seconds, configurable as `analysis_timeout_seconds`.

## Forms, consent, policies, and tracking

Form semantics use field ID/name, labels, input type, autocomplete, required markers, maximum length, and confidence, together with a `FormContext` describing the surrounding prose: submit label, nearest heading, fieldset legend, action path, nearby text, and page title. A field's label is resolved from `<label>`, `aria-labelledby`, `aria-label`, the heading of the block it sits in, the caption immediately above it, its placeholder and its title, in that order, so forms built out of divs — survey builders and single-page apps — are read as the questions they ask rather than as anonymous boxes. Where several categories match a label, the longest match wins, and per-category exclusions keep an email address from being read as a postal one. Field metadata sent through the browser bridge is allowlisted; raw field values are forbidden, and the context carries page copy only.

Whether a field is necessary is decided from the form's inferred intent rather than the site's industry, using an on-device sentence encoder plus structural evidence. See *Judging a form* in `DECISION_ENGINE.md`.

Consent analysis receives structured button/toggle/snapshot data and identifies optional purposes and dark-pattern indications. Policy and terms analysis segments text and applies YAML clause patterns. Each clause declares `positive`, `negative` and `requires` rules: `requires` names the clause's own subject matter, so a sentence has to be about the thing the clause is named after before it may be claimed by it — a cancellation notice period is not an age requirement. Where several sentences match one clause, the one under the matching section heading is kept. Collection categories are read only from genuine collection statements, and from the enumerated span where the sentence has one, so prose that merely mentions a category does not become a claim that it is collected. Citations are sanitized before caching and travel as evidence beside a claim already stated in plain English (`engine/clauses.py`), never as the claim itself. It recognizes public policy text only; a missing or partial policy remains a warning, not a clean result.

Tracking analysis uses observed request hosts, cookies, URL-derived signals held transiently by the extension, known tracker data, fingerprinting signals, and persistent identifiers. Firefox CNAME/DNS observations are cached best effort. A tracking finding is evidence of observable signals, not proof of every form of cross-site tracking.

Browser MAIN-world wrappers watch for a file the person chose to share: a `File` from a picker,
drop or paste, or a slice or re-read of one, followed through `Blob.slice`, `FormData.append`,
`FileReader` and `Request` bodies. A `Blob` the page built itself is a request body, not an upload,
and is not reported.

For known upload paths, initial analysis may wait up to four seconds before failing open; after an
`INTERVENE`, the service keeps a safe 60-second decision timeout. Synchronous file XHR may be
aborted, while ordinary XHR and beacons pass through. These limits prevent a delayed local helper
from becoming a broad browsing outage.

## Measured corpus evidence

The synthetic corpus contains 15 terms and 15 policy documents. Reported benchmark quality is terms F1 1.000 (TP 35, FP 0, FN 0), policy purposes F1 0.9048 (TP 19, FP 4, FN 0), and policy sharing F1 0.9444 (TP 17, FP 0, FN 2). This is fixture-corpus evidence only; it does not establish real-world recall or a general accuracy guarantee.
