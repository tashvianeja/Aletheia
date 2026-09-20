# Detector scope

## Local analysis boundary

`analysis.worker.analyze_payload()` owns raw payload analysis. Its result exposes category findings, confidence, validator status, stable hashes, document type, partial/warning state, structured profiles, and opaque handles. Findings deliberately exclude matched values.

Raw bytes may move through the native transport during an active file upload. They are discarded after use and are not intended to enter the engine, persistent store, or logs. Handle lifetime is bounded in worker memory; the redaction path consumes the handle.

## PII and document detection

The detector combines regular expressions, validators, contextual patterns, and optional lazy spaCy named-entity recognition. Implemented validators include Luhn cards, IBAN mod-97, ABA routing numbers, NHS mod-11, US SSN structure, passport MRZ checks, and the Verhoeff checksum an Aadhaar number and a Virtual ID carry. Regex/context detection covers names, email, phones, addresses, dates of birth, government IDs, financial identifiers, medical phrases, private keys, and API keys.

An Aadhaar number is printed on the card with nothing to label it, so a bare twelve-digit group is only read as one where the surrounding text names the scheme and the Verhoeff digit and the 2-9 opening digit both check out. Without that gate a checksum alone would call roughly one twelve-digit group in ten somebody's national ID. The scheme is not always named: a card issued in Kannada, Tamil or Bengali names itself in that language, and the banner reading "Aadhaar" and "Unique Identification Authority of India" in English is a picture on the page rather than text on it, so the extracted text carries the word nowhere at all. What it does carry, in English, whatever language the card was issued in, is UIDAI's own address column: `VTC` is UIDAI's name for the village, town or city line and belongs to nothing else, and it always sits with an enrolment number, a PIN code or a sub-district. Either the name or that signature identifies the card, in `documents.extract` and again at the bare-number gate in `pii.detector`.

Indian mobile numbers and addresses have their own contextual patterns, because `phonenumbers` cannot place a bare Indian mobile and the street-suffix address patterns are written for US and UK addresses. An Indian address is not written under the word "address" either: UIDAI prints a column of labelled fields, one to a line, above which the house and street lines carry no label at all and are found from the care-of line above them. The labels ordinary prose also uses — `State:`, `District:`, `PIN:` — count only where the line below carries another of the column's labels, so a run of them reads as an address and one on its own does not.

## What a redacted copy covers

`analysis.documents.masking` decides what a redacted copy covers and what it leaves readable, per document. The rule is a property of the kind of document, not of the fact that it is one: covering an identity document entirely removes the details the person is sharing it to prove, and a copy nobody can accept is one that gets replaced by the original.

For an Aadhaar card the number is masked the way UIDAI's own Masked Aadhaar masks it — the first eight digits go, the last four stay — and the name, the gender and the year of birth stay with it, because those are what an identity check reads. Everything else on the card is covered: the number in full, the Virtual ID, the QR code, the photograph, the address, the phone number, the email address and the exact date of birth. The photograph goes because a face is matched against a face and nothing asking for an Aadhaar is checking one. For an identity document whose scheme is not recognised, everything found on it is covered. For anything else, the detected findings are covered and nothing else is.

An Aadhaar prints its address twice, once in English and once in the language it was issued in, and the second copy is routinely beyond reading: the fonts an e-Aadhaar embeds hand back nothing usable for most Indic scripts, though every line of it is legible to whoever opens the file. That copy is covered by the shape of its block instead — a run of lines ending on the six-digit PIN, back as far as the last line carrying something the card keeps readable — and only where no label has already covered that PIN, so a block found by its labels keeps them readable.

What counts as a photograph is decided in `documents.redact`: a page's pictures are mostly its logos, its banners, the rules between its sections and, on an e-Aadhaar, a block of standing advice shipped as an image, and painting those out defaces the copy while withholding nothing. A picture is covered when no single colour covers as much as three tenths of it — flat artwork is built from areas of one colour and a photograph is not — or when it is a small upright rectangle, which catches a face shot against a plain backdrop. A picture that will not decode is covered rather than trusted.

QR codes are located by their finder patterns (`analysis.documents.qr`) rather than decoded, because an Aadhaar's QR holds everything the printed side says and masking the digits beside it would achieve nothing. Three finder centres of a matching module size fix the symbol's square, and they have to sit as three finders do — two of them the same distance from the third and at a right angle to it — rather than merely near one another. A sheet carrying two codes, as an e-Aadhaar does, otherwise came back as one enormous symbol spanning both, and the bar that followed covered everything printed between them. Two centres do not size a symbol at all, and one that cannot be sized is reported as absent rather than covered with a guess.

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
