# Detector scope

## Local analysis boundary

`analysis.worker.analyze_payload()` owns raw payload analysis. Its result exposes category findings, confidence, validator status, stable hashes, document type, partial/warning state, structured profiles, and opaque handles. Findings deliberately exclude matched values.

Raw bytes may move through the native transport during an active file upload. They are discarded after use and are not intended to enter the engine, persistent store, or logs. Handle lifetime is bounded in worker memory; the redaction path consumes the handle.

## PII and document detection

The detector combines regular expressions, validators, contextual patterns, and optional lazy spaCy named-entity recognition. Implemented validators include Luhn cards, IBAN mod-97, ABA routing numbers, NHS mod-11, US SSN structure, and passport MRZ checks. Regex/context detection covers names, email, phones, addresses, dates of birth, government IDs, financial identifiers, medical phrases, private keys, and API keys.

Document extraction supports PDF, DOCX, XLSX, PPTX, text-like files, and images. It looks for image metadata and can invoke Tesseract OCR, including for scanned PDF pages. Extraction has a configurable deadline; partial results/warnings must be surfaced instead of being represented as complete. The current default is 20 seconds, configurable as `analysis_timeout_seconds`.

## Forms, consent, policies, and tracking

Form semantics use field ID/name, labels, input type, autocomplete, required markers, and confidence. Field metadata sent through the browser bridge is allowlisted; raw field values are forbidden.

Consent analysis receives structured button/toggle/snapshot data and identifies optional purposes and dark-pattern indications. Policy and terms analysis segments text, applies YAML clause patterns with positive/negative scope rules, sanitizes citations before caching, and extracts clauses, collection categories, purposes, sharing, retention, rights, and policy warnings. It recognizes public policy text only; a missing or partial policy remains a warning, not a clean result.

Tracking analysis uses observed request hosts, cookies, URL-derived signals held transiently by the extension, known tracker data, fingerprinting signals, and persistent identifiers. Firefox CNAME/DNS observations are cached best effort. A tracking finding is evidence of observable signals, not proof of every form of cross-site tracking.

Browser MAIN-world wrappers are also best effort. For known upload paths, initial analysis may wait up to four seconds before failing open; after an `INTERVENE`, the service keeps a safe 60-second decision timeout. Synchronous file XHR may be aborted, while ordinary XHR and beacons pass through. These limits prevent a delayed local helper from becoming a broad browsing outage.

## Measured corpus evidence

The synthetic corpus contains 15 terms and 15 policy documents. Reported benchmark quality is terms F1 1.000 (TP 35, FP 0, FN 0), policy purposes F1 0.9048 (TP 19, FP 4, FN 0), and policy sharing F1 0.9444 (TP 17, FP 0, FN 2). This is fixture-corpus evidence only; it does not establish real-world recall or a general accuracy guarantee.
