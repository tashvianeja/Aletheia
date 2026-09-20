# Platform limitations

## Verification status

The implementation includes macOS and Windows adapter code behind a common `PlatformAdapter` interface. Injection/unit coverage is present, plus one real FSEvents check, a read-only actual-macOS permissions check, and a current packaged install/onboarding/native-host/OCR/uninstall exercise. Real TCC/Full Disk Access/Accessibility/screen-capture grants, final Windows installer/runtime acceptance, and final CI remain TODO.

## macOS

The macOS adapter reads observable TCC changes, watches launch/startup locations, observes relevant system logs when available, checks Accessibility status, monitors clipboard state, and can open selected System Settings privacy panes. Availability of TCC and several system signals depends on Full Disk Access and Accessibility; the app exposes separate controls for those permissions. Sandboxing, System Integrity Protection, user permissions, OS version differences, app signing, and process visibility can prevent or delay events.

The adapter can create/remove a user LaunchAgent for autostart. The refreshed main app/DMG lifecycle passed visible onboarding/tray, native protocol-v1 readiness, bundled OCR, uninstall, and registration restoration; codesign and the 339-slice/macOS-13 audit also passed. Corrected Intel static-cryptography/OpenSSL packaging and installed-package smoke/audit passed at 14:14 UTC; the earlier CI job still failed its old test outcomes, so it is not a green CI result. Intel source packaging rebuilds cryptography with checksum-pinned static OpenSSL 3.5.8 and needs Rust/Cargo. Notarization, Gatekeeper behavior, and protected permission grants remain pending. “Full Disk Access granted” only indicates that this app may read certain protected locations; it does not prove full OS-wide monitoring.

## Windows

The Windows adapter has injected abstractions for capability/registry observations, clipboard, scheduled tasks, startup locations, browser extensions, and broad-access scoring. It is designed for Windows 10 21H2+ and Windows 11 x64. Windows CI has exercised 267 tests, but no physical Windows UI session or successful final installer/runtime acceptance has verified the product. Run `35448070182` built the installer and its packaged `diagnose` emitted valid JSON with OCR and registry checks true. Its old PowerShell windowed-executable `$LASTEXITCODE` gate failed before installed-lifecycle testing; `1539390` uses `Start-Process -Wait -PassThru` and reads `ExitCode`, but the rerun is unverified because the [latest-source CI run](https://github.com/tashvianeja/Privacy-Guardian/actions/runs/35449032544) has no jobs due to an account billing limit. It is not release evidence.

Registry access can be restricted by policy or permissions. Some applications obtain access through mechanisms that are not represented in the observed registry/task sources. Inno Setup installation, native-host registration, autostart, uninstall cleanup, and physical named-pipe behavior remain TODO on Windows. Windows uses bounded `recv_bytes` JSON with a mandatory constant-time envelope-token comparison; it does not use Pickle or a blocking standard-library authentication challenge.

## Browsers

Chrome/Chromium, Edge, Brave, and Firefox are targets. The extension requests `nativeMessaging`, storage, cookies, web request, declarative net request, scripting, active-tab, tabs, and all-URL host access because it must observe relevant page context and perform requested local actions. It validates page messages and passes metadata through an allowlist, but any capability depends on browser version, enterprise policy, private/incognito mode, content security policy, frame isolation, and extension installation state.

The source assigns Chromium ID `bfdjphkbgihhbonhnmjbbfhckdddonob` and Firefox ID `aletheia@aletheia.local`. The final local headed run passed all 23 real Chromium cases plus Firefox, and exercises consent, tracker blocking, Deep Check, native messaging, and recovery. Firefox’s fixed-ID native-host handshake took 3.02 seconds. This local evidence does not make CI green. Dynamic blocking is best-effort and browser-scoped; it does not constitute a network firewall.

## Clipboard and redaction semantics

Clipboard monitoring is a foreground-change proxy: it classifies newly observed clipboard content and warns when the foreground requester changes. It does **not** detect every clipboard read by every process. It retains categories, not the clipboard text, after classification. The real clipboard/spawn-worker path measured 185.7 ms.

Document redaction paints black boxes into the page's own content, leaving layout, fonts and images as they were; what a box covers stays in the file, which is what lets the original be restored from the copy. A redacted copy is therefore not a safe way to publish a document to an adversary who will open it in a tool — it is a way to hand somebody a file they will look at.

What gets a box is set per document kind (see *What a redacted copy covers* in `DETECTORS.md`), so an identity document keeps whatever its scheme says an identity check needs. Placement depends on locating the detail on the page: a flagged detail with no word or OCR token under it refuses the copy rather than leaving it showing, but OCR that never read a detail cannot flag it in the first place. A scanned identity document gives no way to tell a photograph from the rest of the picture, so the portrait on one is left visible and the copy says so. QR-code detection needs at least three readable finder patterns and roughly two pixels per module, and is applied to the first 20 pages. Metadata stripping removes metadata; for a PNG, pixels remain visibly the same. Users should inspect an output before submitting it.

## Product boundaries

Aletheia observes accessible signals and makes local recommendations. It cannot see every application action, encrypted service-side processing, invisible permission grant, browser operation, or network request. It is not an antivirus, DLP system, legal determination, or guarantee that data has been blocked, deleted, or not retained by a remote service.
