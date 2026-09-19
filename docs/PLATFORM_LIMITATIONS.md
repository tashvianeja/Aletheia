# Platform limitations

## Verification status

The implementation includes macOS and Windows adapter code behind a common `PlatformAdapter` interface. Injection/unit coverage is present, plus one real FSEvents check, a read-only actual-macOS permissions check, and a current packaged install/onboarding/native-host/OCR/uninstall exercise. Real TCC/Full Disk Access/Accessibility/screen-capture grants, final Windows installer/runtime acceptance, refreshed artifacts after the native-host race fix, and final CI remain TODO.

## macOS

The macOS adapter reads observable TCC changes, watches launch/startup locations, observes relevant system logs when available, checks Accessibility status, monitors clipboard state, and can open selected System Settings privacy panes. Availability of TCC and several system signals depends on Full Disk Access and Accessibility; the app exposes separate controls for those permissions. Sandboxing, System Integrity Protection, user permissions, OS version differences, app signing, and process visibility can prevent or delay events.

The adapter can create/remove a user LaunchAgent for autostart. Prior main and fresh-clone app/DMG lifecycles passed visible onboarding/tray, native protocol-v1 readiness, bundled OCR, uninstall, and registration restoration; all 339 Mach-O slices audited at a maximum minimum version of macOS 13. The refreshed main app passes codesign and the 339-slice/macOS-13 audit, while its lifecycle run is in progress. Corrected Intel static-cryptography/OpenSSL packaging and installed-package smoke/audit passed at 14:14 UTC; the earlier CI job still failed its old test outcomes, so it is not a green CI result. Notarization, Gatekeeper behavior, and protected permission grants remain pending. “Full Disk Access granted” only indicates that this app may read certain protected locations; it does not prove full OS-wide monitoring.

## Windows

The Windows adapter has injected abstractions for capability/registry observations, clipboard, scheduled tasks, startup locations, browser extensions, and broad-access scoring. It is designed for Windows 10 21H2+ and Windows 11 x64. Windows CI has exercised 267 tests, but no physical Windows UI session or successful final installer/runtime acceptance has verified the product. An old installer host failed on `ModuleNotFoundError: win32security`; `58739d7` bundles the frozen dependency and the repaired run is building its installer. A separate latest-source CI run has no jobs because of an account billing limit. It is not release evidence.

Registry access can be restricted by policy or permissions. Some applications obtain access through mechanisms that are not represented in the observed registry/task sources. Inno Setup installation, native-host registration, autostart, uninstall cleanup, and physical named-pipe behavior remain TODO on Windows. Windows uses bounded `recv_bytes` JSON with a mandatory constant-time envelope-token comparison; it does not use Pickle or a blocking standard-library authentication challenge.

## Browsers

Chrome/Chromium, Edge, Brave, and Firefox are targets. The extension requests `nativeMessaging`, storage, cookies, web request, declarative net request, scripting, active-tab, tabs, and all-URL host access because it must observe relevant page context and perform requested local actions. It validates page messages and passes metadata through an allowlist, but any capability depends on browser version, enterprise policy, private/incognito mode, content security policy, frame isolation, and extension installation state.

The source assigns Chromium ID `bfdjphkbgihhbonhnmjbbfhckdddonob` and Firefox ID `privacy-guardian@privacyguardian.local`. The final local headed run passed all 23 real Chromium cases plus Firefox, and exercises consent, tracker blocking, Deep Check, native messaging, and recovery. Firefox’s fixed-ID native-host handshake took 3.02 seconds. This local evidence does not make CI green. Dynamic blocking is best-effort and browser-scoped; it does not constitute a network firewall.

## Clipboard and redaction semantics

Clipboard monitoring is a foreground-change proxy: it classifies newly observed clipboard content and warns when the foreground requester changes. It does **not** detect every clipboard read by every process. It retains categories, not the clipboard text, after classification. The real clipboard/spawn-worker path measured 185.7 ms.

Document redaction rebuilds text PDFs and removes images where applicable, so the result can change layout or formatting. Metadata stripping removes metadata; for a PNG, pixels remain visibly the same. Users should inspect an output before submitting it.

## Product boundaries

Privacy Guardian observes accessible signals and makes local recommendations. It cannot see every application action, encrypted service-side processing, invisible permission grant, browser operation, or network request. It is not an antivirus, DLP system, legal determination, or guarantee that data has been blocked, deleted, or not retained by a remote service.
