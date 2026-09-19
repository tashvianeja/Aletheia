# Privacy Guardian browser extension

This is the browser sensor/actuator for Privacy Guardian. It observes page context for file uploads, forms, consent, documents, and tracking; sends schema-validated requests to the local native host `com.privacyguardian.host`; and applies user-approved browser actions such as tracking-rule updates.

The extension does not run the decision engine. The Python service performs local analysis and returns category-level decisions. The background worker derives the requester origin from the browser sender, restricts form metadata to an allowlist, keeps URL/tracker context transiently, and displays a warning badge when the local service disconnects.

## Browser identities

| Browser family | Manifest | ID |
|---|---|---|
| Chromium / Chrome / Edge / Brave | `manifest.json` | `bfdjphkbgihhbonhnmjbbfhckdddonob` |
| Firefox | `manifest.firefox.json` | `privacy-guardian@privacyguardian.local` |

## Development and verification status

Run `make build-extension` from the repository root to generate `dist/privacy-guardian-chromium.zip` and `dist/privacy-guardian-firefox.zip`. For development, start the service and run `uv run privacy-guardian --install-native-host`, then load the unpacked extension source in the matching browser. Headed Chromium exercised 17 cases (15 passed; two timing fixes are in progress), including CMP variants, DNR/cookie blocking that preserves cart and IndexedDB state, exact-three-finding Deep Check, and SIGKILL-mid-analysis recovery. A connected form case took 238.983 ms; a connected passport DOM-change-to-visible warning took 1.095 s (host-side 1.327781 s). Firefox’s fixed-ID native-host handshake took 3.02 seconds. Historical cold first action before bridge readiness was 2.386 s. Final browser totals remain pending.

The extension uses MAIN-world wrappers as a best-effort observation layer. Known uploads fail open after a four-second initial-analysis wait; an actual intervention waits for the service’s safe 60-second decision timeout. This is intentionally narrow: synchronous file XHR can be aborted, while ordinary XHR and beacons are allowed to proceed. Firefox CNAME/DNS tracking signals are cached best effort.

## Permissions

The manifests request native messaging, storage, cookies, web requests, declarative net request, scripting, active tab, tabs, and `<all_urls>` host access. These are broad permissions because the extension needs to observe relevant page events and perform an explicit local action. Tracker refresh/network activity occurs only in response to relevant page context and an explicit user block action; update checking belongs to the desktop app and is user-clicked. See [`../docs/PLATFORM_LIMITATIONS.md`](../docs/PLATFORM_LIMITATIONS.md) and [`../docs/THREAT_MODEL.md`](../docs/THREAT_MODEL.md) for constraints and remaining risks.
