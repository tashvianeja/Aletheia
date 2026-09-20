# Aletheia

## 1. Problem

Users constantly make privacy decisions without knowing:

* **What information is being collected**
* **Why it is being collected**
* **Whether it is actually necessary**
* **Where it will be used**
* **Whether it will be stored or shared**
* **Whether they are agreeing to tracking or profiling**

This happens when uploading files, filling forms, accepting cookies, installing applications, granting permissions, reading privacy policies, or accepting terms and conditions.

The problem is not that users have no privacy controls. The problem is that **the information required to make an informed decision is often hidden, technical, or presented at the wrong time**.

Aletheia runs quietly in the background and intervenes only when it detects a potentially important privacy decision.

---

# 2. Product Behaviour

Aletheia is a **desktop background application**, similar in behaviour to Grammarly.

It:

* runs continuously in the background
* occupies almost no screen space
* monitors relevant privacy events
* does not constantly interrupt the user
* displays a small notification/widget only when something requires attention
* allows the user to expand the notification for an explanation or action

For example:

```text
                    User uses computer normally
                              │
                              ↓
                    Aletheia
                     running silently
                              │
             ┌────────────────┼────────────────┐
             ↓                ↓                ↓
        File upload       Permission       Form input
             │                │                │
             └────────────────┼────────────────┘
                              ↓
                     Is this important?
                              │
                     ┌────────┴────────┐
                    NO                YES
                     │                 │
                  Ignore          Small popup
                                       │
                              Explain / Recommend
```

The goal is **zero privacy effort for normal interactions**.

---

# 3. What It Detects

## 3.1 File Uploads

When a user uploads a file, Aletheia locally examines the file before submission.

It identifies:

* personal information
* contact information
* addresses
* government IDs
* financial information
* medical information
* metadata
* other potentially sensitive information

It then considers the destination and purpose.

Example:

```text
Uploading:
passport.pdf

To:
online image compressor

Detected:
Government ID
Full name
Date of birth
Passport number
Photo

Aletheia:
"This file contains highly sensitive identity information.
An image compressor does not appear to require most of this information."

[Cancel] [Upload anyway] [Create redacted copy]
```

The important part is that it doesn't simply say **“this contains PII.”**

It asks:

> **“Does this website actually need this information?”**

---

# 3.2 Unnecessary Text Being Entered

The same principle applies when the user manually enters information.

For example, a website for downloading a free PDF asks:

```text
Name
Email
Phone number
Date of birth
Home address
```

Aletheia analyses the form and the purpose of the website.

It could display:

```text
This form is asking for information that may not be
necessary for its stated purpose.

Likely unnecessary:
• Phone number
• Date of birth
• Home address

[Continue] [Review fields]
```

This is particularly useful because users often don't realise that a field is unnecessary until they have already submitted it.

---

# 3.3 Terms & Conditions

When the user is about to accept a long Terms & Conditions document, Aletheia can analyse it and surface clauses that materially affect the user's privacy.

Instead of summarising the entire document, it extracts things such as:

```text
Before you accept:

⚠ Data may be shared with third parties
⚠ Company may use submitted content to improve its services
⚠ Account data may be retained after account deletion
⚠ Arbitration clause detected

Nothing unusual detected regarding:
✓ Payment
✓ Account creation
✓ Basic service usage
```

The important engineering decision is **event-triggered analysis**.

The system does not analyse every document on the internet. It activates when the user reaches an agreement/consent action.

---

# 3.4 Privacy Policies

Privacy policies are particularly difficult for normal users because the relevant information is buried inside long legal documents.

Aletheia extracts structured information:

```text
                 WEBSITE PRIVACY

Collects:
✓ Name
✓ Email
✓ Location
✓ Browsing activity
✓ Device information

Uses data for:
✓ Providing the service
✓ Analytics
⚠ Personalised advertising

Shares data with:
⚠ Advertising partners
⚠ Analytics providers

Retention:
⚠ Data may be retained after account deletion
```

It should also distinguish between:

**“The website collects your location”**

and

**“The website collects your location even though location does not appear necessary for the service you're using.”**

The second is much more useful.

---

# 3.5 Cookies and Tracking

When a cookie/consent banner appears, Aletheia identifies what the choices actually mean.

For example:

```text
This website wants to:

✓ Store necessary cookies
⚠ Track your activity for analytics
⚠ Share identifiers with advertising partners
⚠ Build an advertising profile

Recommended:
Reject optional cookies

[Reject optional] [Accept] [View details]
```

It can also detect potentially manipulative consent designs, such as a prominent “Accept All” button while the privacy-preserving option is hidden behind additional screens.

This is an existing area of privacy tooling, so the differentiator is not merely detecting cookie banners; it is integrating cookie decisions into the user's **overall privacy context**.

---

# 3.6 Unnecessary Permissions

Aletheia monitors permission requests such as:

* Camera
* Microphone
* Location
* Contacts
* Notifications
* Clipboard
* Files
* Screen recording

It compares the requested permission with the application's apparent purpose.

Example:

```text
Application:
PDF Converter

Requested:
✓ Files — required
⚠ Camera — appears unnecessary
⚠ Microphone — appears unnecessary
```

The user can then choose whether to grant access.

The system should explain **why the permission is suspicious**, rather than simply labelling it dangerous.

---

# 3.7 Unnecessary System Access

Some applications request broader access than a single permission.

Examples include:

* Full file-system access
* Accessibility access
* Screen recording
* Background execution
* Contacts
* Clipboard monitoring
* Startup access
* Browser history
* System-level automation

Aletheia identifies when an application is asking for **broad system access relative to what it appears to do**.

For example:

```text
Application:
Simple Wallpaper App

Requesting:
• Full file access
• Startup access
• Background execution

These permissions appear broader than necessary
for changing your wallpaper.
```

This extends the system beyond browser privacy into **desktop privacy**.

---

# 3.8 Advertising Profiles and Persistent Identifiers

Aletheia also detects when a website or application is attempting to create a persistent profile of the user.

This could include:

* Advertising IDs
* Cross-site tracking identifiers
* Behavioural profiles
* Interest categories
* Device fingerprinting
* Persistent cookies
* Linking activity across services

Instead of showing a technical explanation:

> `Third-party tracking cookie detected`

it could say:

```text
⚠ Advertising profile detected

This website appears to be using identifiers
to associate your activity with a profile for
personalised advertising.

[Learn more] [Block if possible]
```

This is important because users may understand **“building a profile about you”** much more easily than individual tracking mechanisms.

Web tracking can involve cookies, URL identifiers, browser/device characteristics, and other signals, so this component should not depend on cookies alone.

---

# 4. One Common Decision Engine

Although there are many types of events, they should all feed into the same underlying engine.

```text
                Privacy Event
                     │
                     ↓
             What is being taken?
                     │
                     ↓
              Who is taking it?
                     │
                     ↓
             Why do they need it?
                     │
                     ↓
          Is it necessary for this task?
                     │
                     ↓
          What happens to the data?
                     │
                     ↓
          What does the user normally allow?
                     │
                     ↓
                Risk / Concern
                     │
          ┌──────────┼──────────┐
          ↓          ↓          ↓
        Ignore      Inform     Intervene
```

This allows completely different events to be handled using the same underlying concept:

> **Data requested + requester + purpose + necessity + consequence + user preference**

---

# 5. Engineering Architecture

```text
┌──────────────────────────────────────────┐
│              USER'S COMPUTER             │
│                                          │
│  Browser Extension                       │
│  ├── Forms                               │
│  ├── File Uploads                        │
│  ├── Cookies                             │
│  ├── Privacy Policies                    │
│  └── T&C                                 │
│                                          │
│  Desktop Monitor                         │
│  ├── Permissions                         │
│  ├── System Access                       │
│  └── Application Requests                │
│                 │                        │
│                 ↓                        │
│       ┌─────────────────────┐            │
│       │ Aletheia    │            │
│       │ Background Service  │            │
│       └──────────┬──────────┘            │
│                  ↓                       │
│       ┌─────────────────────┐            │
│       │ Event Classifier    │            │
│       └──────────┬──────────┘            │
│                  ↓                       │
│       ┌─────────────────────┐            │
│       │ Context Analyzer    │            │
│       └──────────┬──────────┘            │
│                  ↓                       │
│       ┌─────────────────────┐            │
│       │ Privacy Policy      │            │
│       │ / Risk Engine       │            │
│       └──────────┬──────────┘            │
│                  ↓                       │
│       ┌─────────────────────┐            │
│       │ Decision Engine     │            │
│       └───────┬─────┬───────┘            │
│               │     │                    │
│            Ignore  Notify/Block          │
│                     │                    │
│                     ↓                    │
│             Minimal UI Popup             │
└──────────────────────────────────────────┘
```

---

# 6. Local Processing

Privacy is the primary constraint of the system itself.

The system should process as much information as possible locally.

For example:

```text
User uploads document
        ↓
Local PII detector
        ↓
"Passport number detected"
        ↓
Context engine receives:
    document_type = identity_document
    destination = image_compressor
    sensitive_fields = passport_number
        ↓
Decision
```

The actual passport number does not need to be sent to an external AI model.

The same principle applies to typed information and browsing activity.

---

# 7. Background UI

The UI should deliberately be small.

When nothing important happens:

```text
                 [Aletheia ●]
```

Nothing else appears.

When intervention is required:

```text
┌──────────────────────────────────────┐
│ 🔒 Aletheia                  │
│                                      │
│ This website is asking for your      │
│ phone number.                        │
│                                      │
│ It does not appear necessary for     │
│ the service you're using.             │
│                                      │
│ [Continue]       [Don't share]       │
└──────────────────────────────────────┘
```

The popup should disappear after the decision.

A larger dashboard can exist for users who want it, but **the core product should not require opening a dashboard**.

### Manual Deep Check

The user can also **open Aletheia at any time and request a thorough privacy check**, even if the system has not detected anything unusual.

This is useful when the user feels that something may be wrong but the automatic system has not flagged it.

For example, the user could click the Aletheia icon and select:

```text
[Run thorough check]
```

The system then performs a deeper analysis of the current context, such as:

* What information the current website/application can access
* What permissions have been granted
* What information is currently being collected
* Whether cookies or tracking mechanisms are active
* Whether an advertising profile is being created
* What data the privacy policy says is collected and shared
* Whether the current form is requesting unnecessary information
* Whether the application has broader system access than necessary
* Any other privacy-relevant behaviour detected

It then produces a consolidated result:

```text
┌──────────────────────────────────────┐
│ Privacy Check                        │
│                                      │
│ Overall: 2 things to review          │
│                                      │
│ ⚠ Advertising profile               │
│   Your activity may be used for      │
│   personalised advertising.          │
│                                      │
│ ⚠ Data retention                     │
│   Uploaded data may be retained      │
│   after account deletion.             │
│                                      │
│ ✓ No unnecessary permissions found   │
│ ✓ No sensitive file currently shared │
│                                      │
│ [View full analysis]                 │
└──────────────────────────────────────┘
```

This creates two modes:

**Automatic mode:**
Runs silently and interrupts the user only when something requires attention.

**Deep-check mode:**
User-initiated and more comprehensive, allowing the user to investigate whenever something feels suspicious.

The deep check should be able to analyse the **current application/website and its available context**, rather than requiring the user to manually collect information for the system.

---

# 8. Personalisation

The system can learn simple user preferences over time.

For example:

```text
Information       Default behaviour

Medical data      Always warn
Government IDs    Always warn
Location          Ask
Phone number      Ask
Email             Usually allow
Analytics         Reject
Advertising       Reject
```

The user can override any decision.

The system should not silently make high-impact decisions based solely on learned behaviour.

---

# 9. Additional Privacy Events Worth Supporting

Beyond the features you listed, I would add a few closely related ones:

### Clipboard access

Detect when an application reads the clipboard, especially if it contains potentially sensitive information.

Example:

> “This application is accessing your clipboard. Your clipboard currently contains information that may be sensitive.”

### Screen access

Warn when an application requests continuous screen capture or screen-reading access.

### Browser history access

Flag applications/extensions requesting access to browsing history.

### Data retention

When a service explicitly states that information is retained for a long period, surface it during signup/upload.

### Third-party sharing

Detect statements such as:

> “We may share information with service providers, partners, or advertisers.”

and explain **who the categories of recipients are and why it matters**.

### Account deletion

During signup, flag when the service's privacy policy says deleting an account does not necessarily immediately delete all associated data.

### Tracking across websites

Detect mechanisms indicating that activity can be linked across multiple websites or services.

These are all variations of the same question:

> **“What are you giving this service access to, and what happens after you give it?”**

---

# 10. MVP

For a hackathon, I would **not attempt to support the entire operating system immediately**.

Build a working prototype around:

### Browser

1. File upload analysis
2. Form-field analysis
3. Privacy-policy analysis
4. T&C analysis
5. Cookie/consent analysis
6. Tracking/profile detection

### Desktop

7. Permission/access anomaly detection
8. Clipboard/screen/file-access warnings

### Core system

9. Background service
10. Context-based decision engine
11. Small notification UI
12. Local privacy preferences
13. Local event history

This gives you one coherent product rather than eight disconnected features.

The central engineering idea remains:

> **Aletheia observes privacy-relevant events, understands what is being requested and why, determines whether it is necessary, and only interrupts the user when there is something worth knowing or acting on.**