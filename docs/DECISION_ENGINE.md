# Decision engine

## Inputs and outcomes

`engine.decision.decide()` is the pure entry point. It receives a typed event, optional category-only findings, a site/app profile, user preferences, and learned rules, and returns a `Decision` with `IGNORE`, `INFORM`, or `INTERVENE`, a 0–1 risk, plain-language explanation, rationale, actions, and a timeout-safe default action.

Events describe the requester, purpose confidence, categories, and event class. Profiles may add policy evidence such as advertiser/data-broker sharing, retention after deletion, AI training on user content, international transfers, data sale, dark patterns, and tracking confidence. The engine does not receive raw PII values.

## How a decision is made

1. Each category gets a sensitivity prior from `data/sensitivity.yaml`.
2. The necessity matrix classifies each category for the requester’s purpose as `required`, `reasonable`, `unnecessary`, or `red_flag`. An unknown/low-confidence purpose returns a low-confidence `reasonable` assessment instead of assuming harm.
3. Policy consequences multiply risk: advertising/data-broker sharing ×1.25, retention after deletion ×1.2, AI training ×1.15, international transfer ×1.1, and data sale ×1.3 when present.
4. Risk is the maximum category score based on sensitivity, necessity weight (`0.2`, `0.5`, `1.0`, `1.3` respectively), consequences, tracking, and unexpectedness. Baseline thresholds are `<0.25` Ignore, `0.25–<0.55` Inform, and `≥0.55` Intervene.
5. Preferences can raise a minimum outcome. `usually_allow` raises thresholds, but protected categories cannot silently be downgraded to Ignore. Protected roots are government ID, medical, financial, credentials, biometric photo, and minors’ data.
6. The same requester/category set is rate-limited for 24 hours unless new red flags or high-impact data exist. Three consecutive Continues may downgrade an intervention to Inform for a non-protected category and purpose pair.

Event-specific rules cover consent dark patterns, tracking signals, broad system access, screen capture, denied permissions, form observation, clipboard allowlists, expected permissions, and requester allow overrides. Actions are selected by event type: for example, file uploads offer `cancel`, `continue`, and `redact`; consent offers `reject_optional`; tracking offers `block`.

## One warning per thing to say

`decide()` is pure and does not know what has already been shown. The service does, and it folds a repeat of a warning already on record onto that warning rather than raising a second one, because every surface keys the card it is showing by event id.

`engine.notice.notice_signature()` names what makes one warning different from another: for tracking, the set of mechanisms and whether the device is fingerprinted, not the tracker count or confidence, both of which climb as a page finishes loading; for consent, the CMP, dark patterns and purposes, not the vendor count or button geometry, which move with every re-render. A repeat may sharpen an outstanding warning but never lowers its outcome, and one the person has already answered becomes `IGNORE`.

Two classes are always raised afresh, listed in `notice.ALWAYS_ASK`: warnings that hold up something the person is doing now — uploads, form submissions, terms acceptance — because reusing one would apply an earlier answer to a new action; and warnings that report a moment rather than a standing state, which today means clipboard reads.

## Examples

| Situation | Evidence used | Expected engine behavior |
|---|---|---|
| Passport to an image tool | Government-ID finding; `image_tool` purpose; unnecessary/red-flag matrix result | High risk and **Intervene** with cancel/redact actions. |
| Filled bank KYC form | Financial/identity category; banking purpose | Required/reasonable context can reduce the outcome; it is not automatically treated as suspicious. |
| Hidden reject button in a consent banner | Optional purposes plus dark-pattern signal | At least **Intervene**, with `reject_optional` as default action. |
| Persistent tracker signals | Tracker domains, fingerprinting, or tracking signals | **Inform** when signals exist, with a `block` recommendation. |
| Wallpaper app with startup and broad access | Access breadth ≥0.6 and unnecessary/red-flag assessments | Raises risk to at least 0.65 and **Intervene**. |

These are contract-level examples. The browser/desktop end-to-end scenarios that exercise them are mapped in `tests/ACCEPTANCE.json`; the final local headed browser run passed all 23 real Chromium cases plus Firefox. CI and final platform acceptance remain pending.
