# Changelog

All notable changes will be documented here. This project has not produced a verified release artifact.

## [Unreleased]

### Changed

- The thorough check shows a progress bar while it runs, not a checklist. The card used to
  list the four sections it was going to check and tick them off; for the few seconds a run
  lasts that is a list to read, mostly of things that have not happened yet. It is now one
  line naming what is being checked at that moment — getting ready, trackers, policies and
  forms, application permissions, writing the summary — a count of how many of the four have
  answered, and a bar that fills as they do, going busy for the summary because there is no
  way to know how long the model will take. The mark beside the line turns for as long as the
  run is going, including the two waits the bar cannot count.
- Preferences is now Settings, and About is gone. The dashboard has four sections: Overview,
  Events, Settings, Sites & apps. The Gemini model is a closed list of the current Flash models
  (`gemini-flash-latest`, 3.8 / 3.7 / 3.6 / 3.5 Flash, 3.5 / 3.1 Flash-Lite, 2.5 Flash / Flash-Lite)
  instead of an editable box; a successful **Test** replaces it with the text-answering Flash
  models the key can call, and a configured model that is not among them stays selectable.
  The tracker-list attribution line has moved off the page into the README. The About pane's
  version, diagnostics JSON, redacted log view and support-bundle export are no longer in the
  window; `privacy-guardian --diagnose` still prints the same diagnostics.
- The Overview is now a tally of what has passed through the app, in the manner of a browser's
  "trackers blocked" panel: sites & apps checked, trackers spotted, files checked before upload,
  policies & terms summarised (with an estimated reading time once word counts exist), cookie
  banners and desktop permissions, followed by a list of the decisions the person actually made,
  with those taken automatically on their behalf marked as such. Every figure comes from stored
  records via `Store.tally()`, and each thing is counted once — a tracker on a site however many
  page loads reported it, a permission grant however often it was polled, a document however
  many times it was re-read — so the page can never claim more than the history shows. The
  service now records how many words of each policy or terms document it analysed. The dashboard
  opens on the Overview; Intervened / Informed / Ignored stay on Events, where the table they
  describe is.
- Sites & apps is a report again, not a console. The pane ended in a "Site and app memory"
  section — a lookup field, a raw profile dump and an editable JSON copy of every stored
  preference — which is machinery for whoever built the thing, not for someone asking what a
  website does with their data. It is gone from the page; the memory behind it is untouched and
  still read, written, exported and imported as before.
- Every card now wears its urgency. `Decision` carries an `urgency` tier, set by the engine from
  the verdict and the risk — `act_now` (INTERVENE at risk ≥ 0.75), `attention` (other
  interventions), `heads_up` (a warning that asks nothing), `all_clear` (fine, or handled for the
  person) and `note` — and both the desktop widget and the in-page panel render it the same way:
  a coloured band across the top that names the tier in words ("Act now", "Needs your attention",
  "Heads up", "All clear"), a stop sign / triangle / circle / tick to match, the card outline in
  the tier's colour, and the findings grouped in a box washed in the same hue with their icons
  coloured to match. The two reds are told apart on purpose: "Act now" is the only solid band, and
  it pulses three times as the card lands, then rests. Informational cards list what was found
  and where, not only the headline. The thorough-check card takes the tier of its worst finding,
  and each of its rows keeps its own. The confirmation strip leads with a green tick.
- Rebuilt both intervention surfaces — the desktop widget and the in-page extension panel — on one
  card design: a headline, a short body, severity-marked finding rows, a subject/destination
  context line, and actions ranked so the protective option is the filled primary button. Both
  render the same structured `Decision`, so the two surfaces can no longer drift apart.
- `Decision` now carries `headline`, `body`, `findings`, `subject`, `destination`, `action_labels`,
  `primary_action`, `tertiary_action`, `layout` and `auto_action` instead of one run-on
  `explanation` string. `explanation` remains as the single-line form used in history and logs.
- Replaced the dashboard's tab strip with sidebar navigation: Overview, Events, Preferences,
  Sites & apps, About. Events gained Intervened/Informed/Ignored tiles and time / what happened /
  site or app / decision columns. Preferences now lists the seven kinds of information a person
  recognises instead of every detector category, plus a Learning card.
- The thorough check reports four grouped sections with per-finding detail lines, shows a live
  checklist while it runs, and hands off to the full report in the dashboard.
- The menu bar icon is a monochrome padlock template with a status dot, and its menu leads with a
  status line and the thorough check.
- Warnings say more with fewer words. Finding rows carry where a thing was found — the page in a
  document, or the file's own metadata — and tracking rows name the trackers and say what each
  mechanism does instead of printing the detector's name for it ("Reuses one stored identifier
  across separate websites", not "Cross origin storage identifier"). The "Why am I seeing this?"
  reasoning is grouped by verdict, so four fields no longer produce four near-identical sentences.
  Warnings raised from page context name the site: they all used to open with the word "Website".
  Every purpose in the necessity matrix now has a name that reads in a sentence, in place of "a
  banking" and "a ecommerce", and a consent toggle labelled "Targeted advertising" is folded into
  the advertising purpose rather than listed as a fifth one.

### Added

- Learned defaults: after the same reversible protective choice on five distinct sites, Privacy
  Guardian offers once to make it automatic, with "Keep asking me" as a real option. Government ID,
  medical, financial and credential data are excluded from automation by construction.
- A compact confirmation bar reporting what an action did, in the page and on the desktop.
- "Show me where" now locates and highlights the flagged clauses on the page.
- `install.sh`: one command to build and install on macOS, with `--skip-ocr`, `--no-autostart` and
  `--uninstall`.
- `learning_enabled` setting and `Store.outcome_counts()`.

### Fixed

- The thorough-check card answered for whichever page you left it on. A check reads one page at
  one moment, but the card stayed in the corner through the next tab and the one after, keeping
  the same headline, the same findings and the same ticked-off sections — so a clean result from
  the page you had just left read as a verdict on the page you were now looking at, and a warning
  from that page read as one about this one. The browser now reports which page is in front with
  every heartbeat, and the card leaves the moment that stops being the page it checked. A browser
  showing no page at all, or one sitting behind a check of a desktop application, is not a page
  change and takes nothing away from someone part-way through reading it.
- The same warning appeared twice. A page reports its context repeatedly — on load, when the
  consent banner animates in, each time another advertising script runs — and every report minted
  a fresh event, so the same "building an advertising profile" card was raised again a moment
  later. Repeats of a warning already on record now share its identity: the card on screen is
  updated in place, one the person has already answered is not raised again, and a later look can
  sharpen a warning but never withdraws a question still being asked. Warnings that hold something
  up (uploads, form submissions, terms) and ones that report a moment rather than a standing state
  (clipboard reads) are still always asked afresh. Two narrower causes are fixed with it: the
  polished wording from an optional cloud call was pushed at the desktop for browser events the
  page was already showing, and page-level analysis ran once per frame, so a page with three
  iframes reported itself four times.
- Nothing was ever announced again. A warning was raised once and then quieted on every later
  look as "the same request was already shown within the last day" — whether or not the person had
  seen it, let alone dealt with it. Reloading a page or opening the next one produced silence, and
  the only way to find out what a site was doing was to run the thorough check by hand. Being
  shown is no longer taken for being answered: a warning is raised again until the person picks an
  action or closes the card, and closing it is now reported, which is also what makes "Don't ask
  again for this site" on an informational card do anything. That tick had no effect at all, and a
  stylesheet rule was showing it on every card whether or not it had been opened.
- The "May be unnecessary" marker never appeared beside an optional field. It is meant to appear
  once the person puts something in a box nobody made them fill in, but the page's inventory
  deliberately ignored whether a box was filled, and typing changes no attribute for the observer
  to notice, so the moment it waited for never arrived. Whether a box has something in it now
  counts as a change, half a second after the typing stops. The boolean is compared; the value is
  not, and still never leaves the page.
- Cards said the same thing three times over and named mechanisms instead of consequences. An
  advertising card carried a headline, a paragraph repeating the headline, a row repeating the
  paragraph, and then a row for each mechanism — invisible images, tagged links, a stored
  identifier — which are all ways of doing the one thing the row above them already said. It now
  says what the page does to the person: who it hands the visit to, that it can recognise the
  device after cookies are cleared, and whether it can attach an email address to both. The
  mechanisms, the reasoning and the full clause list moved under "Why am I seeing this?", which
  informational cards have now too. A cookie banner's purposes are one row rather than four, a
  form lists the fields worth looking at rather than every field it has, and a policy card names
  four clauses with the rest one click away.
- Eleven advertising "websites" were four companies. Tracker hostnames are counted and blocked by
  the company behind them, so `cm.g.doubleclick.net`, `ad.doubleclick.net` and a hashed
  `safeframe.googlesyndication.com` subdomain no longer read as three separate sites following
  you.
- A site could still stack up two or three "building an advertising profile" cards, one a moment
  after the other, each listing a little more than the last. The mechanisms behind that one
  statement arrive in waves — the tracker requests as the page loads, the fingerprint when that
  script gets its turn, the pixels later still — and a wave that brought a new mechanism was taken
  for a different warning, so it was raised as its own card. A page's tracking is now one notice
  for as long as the person is on it, and the in-page panel, like the desktop widget before it,
  takes a sharpened decision into the card already on screen rather than leaving the first wording
  up: what the reader has opened or ticked stays as they left it.
- Privacy Guardian announced a file share on sites where nothing had been shared. Any `Blob` or
  `ArrayBuffer` request body counted as an upload, which covers analytics beacons, JSON payloads
  and media chunks on a large share of the web; the "file" was then named `upload.bin` and flagged
  as only partially checked because the bytes could not be parsed. Only something the person chose
  now counts — a `File` from a picker, drop or paste, or a slice or re-read of one, tracked through
  `Blob.slice`, `FormData.append` and `Request` bodies so chunked and resumable uploads are still
  reviewed.
- A new tracking mechanism on an already-reported page was suppressed as "the same request shown
  within the last day". Fingerprinting appearing on a page previously flagged only for tracker
  requests is now raised.

- Setup did not set anything up. Every page of the walkthrough could be clicked straight
  through in four clicks with nothing configured, and the native messaging bridge was only
  registered at Finish, *after* the page that asks you to load the extension, so the
  extension could never connect while setup was open. The bridge is now registered on
  entering that page, the page shows the extension's path with copy and reveal buttons and
  per-browser instructions, and Next stays disabled until a browser has genuinely
  connected. Continuing without the extension is possible but takes a confirmation, and it
  leaves setup marked incomplete so it prompts again rather than claiming to be ready.
  The final page summarises what is and is not working instead of asserting success.
- Floating widgets were placed partly off the bottom of the screen and behind the Dock.
  Three causes, all now fixed: the window was measured before its word-wrapped labels had
  been laid out, so its height was underestimated; it was anchored to the primary screen
  rather than the one in use; and Qt's always-on-top maps to a window level below the
  Dock, which draws over anything pinned to the bottom edge. A card taller than the
  screen now scrolls instead of overflowing.
- Browser events raised both an in-page widget and a desktop popup. The page now owns events it can
  render; the desktop owns the rest, and picks up browser events only when no extension is live.
- Pausing did not hold for privacy-policy events: a partial document could still raise the outcome
  from Ignore to Inform after the pause check had run.
- A scanned PDF failed the whole document analysis when OCR was unavailable, so the upload
  proceeded unchecked. Scanned pages are now reported as unchecked and the upload is flagged
  partial.
- The macOS bundle failed `codesign --verify --strict` because PySide6 framework directories carry
  `com.apple.FinderInfo`. The build now signs a clean staged copy and verifies it before building
  the DMG.
- "Show me where" on a terms dialog silently swallowed the user's click and did nothing.
- Restarting the service after a worker thread died left the old clipboard monitor running and
  started a second one against a stale backend.
- Each thorough check created a new window instead of reusing one.
- Resolving a decision reset the menu bar icon to idle even while other decisions were pending or
  monitoring was paused.
- Informational in-page toasts kept polling the native host every 300 ms for a full minute after
  they had been dismissed.
- `wallpaper_utility` treated startup and background execution as reasonable, contradicting the
  product's own worked example.
- macOS 13 and later moved the System Settings privacy anchors; the app used the pre-Ventura URL.

### Added

- Typed privacy events, category-only findings, decision engine, local SQLite storage contract, and authenticated IPC contracts.
- Local PII/document, form, consent, policy/terms, purpose, and tracking analysis modules.
- Optional, disabled-by-default LLM client with a sanitization gate and OS-keychain credentials.
- macOS and Windows adapter implementations plus Qt UI components, with injected/UI coverage and limited real macOS checks.
- WebExtension source for Chromium-family browsers and Firefox, including CMP, Deep Check, tracker DNR/cookie, browser-recovery, and Firefox fixed-ID handshake coverage.
- macOS packaging scripts and a compatible static Tesseract 5.5.3 / Leptonica 1.87 / libpng 1.6.58 build path targeting macOS 13.
- Developer, security, platform, detector, LLM, performance, and product documentation grounded in current code/evidence.

### Verification pending

- Real TCC/Full Disk Access/Accessibility/screen checks, a Windows installed-lifecycle rerun after the fixed PowerShell exit-code gate, green CI (the latest-source run is billing-blocked), and release artifacts.
