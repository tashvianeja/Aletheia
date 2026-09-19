# Threat model

## Assets

The primary assets are raw uploaded documents, form values, clipboard content, page/context signals, local event history, preference data, the local IPC token, optional API-key credentials, and redacted diagnostic logs. The design goal is to limit sensitive content to the analysis worker and retain category-level records only.

## Trust boundaries

| Boundary | Data crossing | Intended control |
|---|---|---|
| Browser page → extension | Field metadata, page context, and user action | Content scripts constrain sender/page context; background validates event schema; form values never leave the page. |
| Extension → native host | Framed JSON native messages | Extension-native messaging plus caller-origin allowlist. |
| Native host → service | Local authenticated request | Per-install token; 0600 Unix socket inside a 0700 data directory, or bounded Windows AF_PIPE JSON with constant-time envelope-token comparison. |
| Service → analysis worker | Active raw bytes/text | Opaque worker handles; bounded worker memory and expiry. |
| Service → SQLite/logs | Sanitized event/decision/profile data | Stored projection excludes raw values, payload references, field labels/names, file names, URL query strings, and raw extracted text; logging redacts PII. |
| Optional LLM boundary | Sanitized public/category-level content | Explicit opt-in, keychain key, single outbound guard in a separate lazy process, validated-identifier rejection, typed output, offline fallback. |

## Threats and mitigations

| Threat | Mitigation in the implementation | Remaining limitation |
|---|---|---|
| A random local process sends service commands | Token-authenticated local transport, framed size limit, caller validation; no Pickle or blocking stdlib auth challenge on AF_PIPE | Local malware running as the user may still access user-space resources; endpoint security is outside this app. |
| A hostile webpage forges a browser event | Extension derives requester identity from browser sender and validates schemas | Compromised browser/extension environment is out of scope. |
| Sensitive values leak into history or logs | Category-only findings, sanitization, redacting log processor, storage projection | Bugs in third-party libraries or future code can violate this; audit and tests remain necessary. |
| Sensitive content is sent to the LLM | Disabled-by-default feature, one sanitizer choke point, keychain-only key, fallback | Sanitization cannot make a cloud provider a zero-risk boundary; public policy text is still sent when opted in. |
| Oversized/malicious documents consume resources | Size/handle limits, archive checks, analysis deadline, partial results | OCR/extractors can still be resource intensive; benchmark and adversarial testing are incomplete. |
| An extension blocks too much or too little | Bounded dynamic rules, explicit user-facing action, category context, four-second fail-open initial analysis | Browser APIs cannot cover all traffic; headed Chromium action coverage is partial and final totals remain pending. |
| Preference learning silences important decisions | Protected categories cannot auto-downgrade to Ignore; learned rules only downgrade to Inform | Category/purpose inference can be wrong. |

## Non-goals

The current build does not claim resistance to a compromised OS, browser, privileged administrator, malicious accessibility service, or remote service that has already received data. It also does not guarantee legal accuracy of policy interpretation. Users should retain control over submissions and permission grants.

## Verification gaps

IPC tests have reported real Unix-socket coverage; Chromium browser actions and Firefox’s fixed-ID native-host handshake are also exercised. `pip-audit` was clean except for the local project and direct spaCy wheel, which are not PyPI packages and were skipped; Bandit medium-and-above was clean. Real TCC/screen checks, Windows execution, final artifact signing/rebuild, final browser counts, and green CI remain pending. These are material defense-in-depth checks and must be completed before a release claim.
