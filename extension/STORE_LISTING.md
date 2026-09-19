# Draft store listing — not for submission

## Privacy Guardian — local privacy checks

Privacy Guardian helps you understand privacy-relevant requests while you browse. It can identify supported form, upload, consent, policy, and tracking signals, then asks the local Privacy Guardian desktop service for a category-level recommendation.

The extension is designed to keep analysis local. Optional cloud assistance belongs to the desktop app, is off by default, and has a separate privacy policy in the product documentation. The extension does not send telemetry.

### Why these permissions

- **All websites and active tabs:** observe supported privacy events where they happen.
- **Native messaging:** ask the local Privacy Guardian service to analyze an event and return a decision.
- **Cookies and web requests:** detect observed tracking signals and remove/block them only after a user action. Firefox CNAME/DNS information is best effort.
- **Declarative Net Request:** add bounded browser blocking rules after the user selects “Block if possible.”
- **Storage:** keep extension-local transient settings/state needed by the extension.

### Data handling

The extension derives the site identity from browser APIs and sends constrained event metadata to the local service. Upload bytes are passed only to the active local analysis session and discarded afterward; the service stores category-level results rather than raw values. The extension/service bridge and privacy claims require final browser end-to-end verification before this text may be submitted to a store.

### Support status

This listing is a draft. Store packaging, review materials, screenshots, compatibility validation, and published support contacts are TODO.
