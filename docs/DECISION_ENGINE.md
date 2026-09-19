# Decision engine

## Inputs and outcomes

`engine.decision.decide()` is the pure entry point. It receives a typed event, optional category-only findings, a site/app profile, user preferences, and learned rules, and returns a `Decision` with `IGNORE`, `INFORM`, or `INTERVENE`, a 0–1 risk, plain-language explanation, rationale, actions, and a timeout-safe default action.

Events describe the requester, purpose confidence, categories, and event class. Profiles may add policy evidence such as advertiser/data-broker sharing, retention after deletion, AI training on user content, international transfers, data sale, dark patterns, and tracking confidence. The engine does not receive raw PII values.

## How a decision is made

1. Each category gets a sensitivity prior from `data/sensitivity.yaml`.
2. Necessity classifies each category as `required`, `reasonable`, `unnecessary`, or `red_flag`. For **forms**, the classification is keyed on the form's inferred intent (see *Judging a form* below), not on the site's industry. For every other event class the site/app purpose matrix in `data/necessity_matrix.yaml` still applies. An unknown or low-confidence purpose returns a low-confidence `reasonable` assessment instead of assuming harm.
3. Policy consequences multiply risk: advertising/data-broker sharing ×1.25, retention after deletion ×1.2, AI training ×1.15, international transfer ×1.1, and data sale ×1.3 when present.
4. Risk is the maximum category score based on sensitivity, necessity weight (`0.2`, `0.5`, `1.0`, `1.3` respectively), consequences, tracking, and unexpectedness. Baseline thresholds are `<0.25` Ignore, `0.25–<0.55` Inform, and `≥0.55` Intervene.
5. Preferences can raise a minimum outcome. `usually_allow` raises thresholds, but protected categories cannot silently be downgraded to Ignore. Protected roots are government ID, medical, financial, credentials, biometric photo, and minors’ data.
6. The same requester/category set is rate-limited for 24 hours unless new red flags or high-impact data exist. Three consecutive Continues may downgrade an intervention to Inform for a non-protected category and purpose pair.

Event-specific rules cover consent dark patterns, tracking signals, broad system access, screen capture, denied permissions, form observation, clipboard allowlists, expected permissions, and requester allow overrides. Actions are selected by event type: for example, file uploads offer `cancel`, `continue`, and `redact`; consent offers `reject_optional`; tracking offers `block`.

## Judging a form

Necessity only means anything relative to what the person is trying to do. Keying it on
the site's industry cannot distinguish a registration form, where a phone number is the
account identifier, from a mailing-list box, where the same field is pure over-collection
— and it reported Instagram's signup identifier and password as unnecessary for exactly
that reason.

`intelligence.necessity.assess_form()` therefore runs three steps:

1. **Intent.** `intelligence.intent.classify_form()` infers what the form is for from two
   independent kinds of evidence, accumulated as log-odds and normalised together:
   *structure* (a `cc-number` field means payment; `current-password` without
   `new-password` means login; a `one-time-code` box means two-factor) and *sentence
   similarity* between the form's own prose — heading, legend, submit label, nearby text,
   page title — and per-intent exemplars, computed by an on-device sentence encoder. The
   site's purpose contributes a weak prior that breaks ties but is outweighed by real
   structural evidence, so a bank's newsletter box is still a newsletter box.
2. **Role.** Each field is assigned the reason it is on this form: primary or alternate
   identifier, credential, payment instrument, delivery target, contact channel,
   verification evidence, profile detail, optional extra, or unrelated collection. Roles
   are themselves intent-conditional: a bank account number is a payment instrument on a
   checkout and an unexplained demand on a job application.
3. **Verdict.** Categories are judged against what the intent genuinely needs, with the
   site's purpose re-entering as a modifier — sensitive collection is ordinary for a bank
   or a government portal, and implausible for an image compressor.

Two safeguards keep the model honest. An intent that exists only because of the field it
would excuse is discarded: a page claiming to "verify your identity" has not become a
bank by saying so, so `identity_verification` is only credible from a site whose business
plausibly involves it. And a credential is never reported as unnecessary, because telling
someone their password is not needed to log in discredits everything else the product says.

## Deciding whether to say anything

Detecting over-collection is not the same as being worth an interruption. A field is
raised only when the form's intent is known with at least 0.45 confidence, the field is
compulsory or the person has actually filled it in, and the category clears a sensitivity
floor of 0.45 — which admits phone numbers, birthdays, addresses and everything above
them, and excludes an email address or a full name on a form somebody chose to fill in.
A `red_flag` bypasses the floor. Below the confidence threshold the engine says nothing:
a guess about what a form is for is not grounds for telling someone their data is
unnecessary.

The same gate is why a missing sentence encoder costs recall but not precision. Without
it, structural evidence alone still identifies the common transactions and the judgement
falls silent on the ambiguous remainder rather than guessing at it.

## One warning per thing to say

`decide()` is pure and does not know what has already been shown. The service does, and it folds a repeat of a warning already on record onto that warning rather than raising a second one, because every surface keys the card it is showing by event id.

`engine.notice.notice_signature()` names what makes one warning different from another: for tracking, the set of mechanisms and whether the device is fingerprinted, not the tracker count or confidence, both of which climb as a page finishes loading; for consent, the CMP, dark patterns and purposes, not the vendor count or button geometry, which move with every re-render. A repeat may sharpen an outstanding warning but never lowers its outcome, and one the person has already answered becomes `IGNORE`.

Two classes are always raised afresh, listed in `notice.ALWAYS_ASK`: warnings that hold up something the person is doing now — uploads, form submissions, terms acceptance — because reusing one would apply an earlier answer to a new action; and warnings that report a moment rather than a standing state, which today means clipboard reads.

## Examples

| Situation | Evidence used | Expected engine behavior |
|---|---|---|
| Passport to an image tool | Government-ID finding; `image_tool` purpose; an identity-verification claim the site's business does not support | High risk and **Intervene** with cancel/redact actions. |
| Instagram signup asking for phone-or-email | `account_signup` intent; the field is the account's alternate identifier | Silent. The identifier and the password are what the transaction needs. |
| Mailing-list box asking for a birthday | `newsletter` intent; `dob` outside what the intent needs and above the sensitivity floor | **Inform**, naming the date of birth. |
| Filled bank KYC form | Financial/identity category; banking purpose | Required/reasonable context can reduce the outcome; it is not automatically treated as suspicious. |
| Hidden reject button in a consent banner | Optional purposes plus dark-pattern signal | At least **Intervene**, with `reject_optional` as default action. |
| Persistent tracker signals | Tracker domains, fingerprinting, or tracking signals | **Inform** when signals exist, with a `block` recommendation. |
| Wallpaper app with startup and broad access | Access breadth ≥0.6 and unnecessary/red-flag assessments | Raises risk to at least 0.65 and **Intervene**. |

These are contract-level examples. The browser/desktop end-to-end scenarios that exercise them are mapped in `tests/ACCEPTANCE.json`; the final local headed browser run passed all 23 real Chromium cases plus Firefox. CI and final platform acceptance remain pending.
