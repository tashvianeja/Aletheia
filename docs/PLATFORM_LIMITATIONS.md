# Platform limitations

## Verification status

The implementation includes macOS and Windows adapter code behind a common `PlatformAdapter` interface. Current evidence is injected/unit coverage and source review; a real macOS desktop run, a real Windows runner run, CI completion, browser/service end-to-end execution, and installer smoke tests are TODO. This document is intentionally conservative until those checks finish.

## macOS

The macOS adapter reads observable TCC changes, watches launch/startup locations, observes relevant system logs when available, checks Accessibility status, monitors clipboard state, and can open selected System Settings privacy panes. TCC databases and system logs are protected by macOS and may require Full Disk Access; Accessibility controls separate portions of observation. Sandboxing, System Integrity Protection, user permissions, OS version differences, app signing, and process visibility can prevent or delay events.

The adapter can create/remove a user LaunchAgent for autostart. That behavior, app notarization, Gatekeeper experience, and an installed `.app` have not been smoke-tested. “Full Disk Access granted” only indicates that this app may read certain protected locations; it does not prove full OS-wide monitoring.

## Windows

The Windows adapter has injected abstractions for capability/registry observations, clipboard, scheduled tasks, startup locations, browser extensions, and broad-access scoring. It is designed for Windows 10 21H2+ and Windows 11 x64, but no physical Windows host, VM, or successful `windows-latest` CI result has verified it yet.

Registry access can be restricted by policy or permissions. Some applications obtain access through mechanisms that are not represented in the observed registry/task sources. Inno Setup installation, native-host registration, autostart, uninstall cleanup, and named-pipe behavior remain TODO on Windows.

## Browsers

Chrome/Chromium, Edge, Brave, and Firefox are targets. The extension requests `nativeMessaging`, storage, cookies, web request, declarative net request, scripting, active-tab, tabs, and all-URL host access because it must observe relevant page context and perform requested local actions. It validates page messages and passes metadata through an allowlist, but any capability depends on browser version, enterprise policy, private/incognito mode, content security policy, frame isolation, and extension installation state.

The source assigns Chromium ID `bfdjphkbgihhbonhnmjbbfhckdddonob` and Firefox ID `privacy-guardian@privacyguardian.local`. Native-host manifests/registration and actual browser handshakes are pending verification. Dynamic blocking is best-effort and browser-scoped; it does not constitute a network firewall.

## Product boundaries

Privacy Guardian observes accessible signals and makes local recommendations. It cannot see every application action, encrypted service-side processing, invisible permission grant, browser operation, or network request. It is not an antivirus, DLP system, legal determination, or guarantee that data has been blocked, deleted, or not retained by a remote service.
