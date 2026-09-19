# Privacy Guardian browser extension

This is the browser sensor/actuator for Privacy Guardian. It observes page context for file uploads, forms, consent, documents, and tracking; sends schema-validated requests to the local native host `com.privacyguardian.host`; and applies user-approved browser actions such as tracking-rule updates.

The extension does not run the decision engine. The Python service performs local analysis and returns category-level decisions. The background worker derives the requester origin from the browser sender, restricts form metadata to an allowlist, keeps URL/tracker context transiently, and displays a warning badge when the local service disconnects.

## Browser identities

| Browser family | Manifest | ID |
|---|---|---|
| Chromium / Chrome / Edge / Brave | `manifest.json` | `bfdjphkbgihhbonhnmjbbfhckdddonob` |
| Firefox | `manifest.firefox.json` | `privacy-guardian@privacyguardian.local` |

## Development status

Run `make build-extension` from the repository root to generate the declared build output. Loading an unpacked extension, native-host manifest registration, service startup, upload handoff, and browser E2E tests are all pending verification. Do not publish this source directory to a browser store or rely on it for protection until those checks and review are complete.

## Permissions

The manifests request native messaging, storage, cookies, web requests, declarative net request, scripting, active tab, tabs, and `<all_urls>` host access. These are broad permissions because the extension needs to observe relevant page events and perform an explicit local action. See [`../docs/PLATFORM_LIMITATIONS.md`](../docs/PLATFORM_LIMITATIONS.md) and [`../docs/THREAT_MODEL.md`](../docs/THREAT_MODEL.md) for constraints and remaining risks.
