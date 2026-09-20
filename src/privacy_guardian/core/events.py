from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DataCategory(StrEnum):
    FULL_NAME = "full_name"
    EMAIL = "email"
    PHONE = "phone"
    POSTAL_ADDRESS = "postal_address"
    DOB = "dob"
    AGE = "age"
    GENDER = "gender"
    GOVERNMENT_ID = "government_id"
    GOVERNMENT_ID_PASSPORT = "government_id.passport"
    GOVERNMENT_ID_NATIONAL_ID = "government_id.national_id"
    GOVERNMENT_ID_SSN = "government_id.ssn"
    GOVERNMENT_ID_DRIVERS_LICENSE = "government_id.drivers_license"
    GOVERNMENT_ID_TAX_ID = "government_id.tax_id"
    FINANCIAL = "financial"
    FINANCIAL_CARD_NUMBER = "financial.card_number"
    FINANCIAL_IBAN = "financial.iban"
    FINANCIAL_ACCOUNT_NUMBER = "financial.account_number"
    FINANCIAL_ROUTING = "financial.routing"
    MEDICAL = "medical"
    MEDICAL_DIAGNOSIS = "medical.diagnosis"
    MEDICAL_MEDICATION = "medical.medication"
    MEDICAL_INSURANCE_ID = "medical.insurance_id"
    CREDENTIALS = "credentials"
    CREDENTIALS_PASSWORD = "credentials.password"
    CREDENTIALS_API_KEY = "credentials.api_key"
    CREDENTIALS_PRIVATE_KEY = "credentials.private_key"
    BIOMETRIC_PHOTO = "biometric_photo"
    LOCATION_PRECISE = "location_precise"
    LOCATION_COARSE = "location_coarse"
    DEVICE_IDENTIFIERS = "device_identifiers"
    BROWSING_ACTIVITY = "browsing_activity"
    CONTACTS = "contacts"
    CALENDAR = "calendar"
    FILES_BROAD = "files_broad"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    SCREEN = "screen"
    CLIPBOARD = "clipboard"
    ACCESSIBILITY = "accessibility"
    AUTOMATION = "automation"
    BACKGROUND_EXECUTION = "background_execution"
    STARTUP = "startup"
    BROWSER_HISTORY = "browser_history"
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    ETHNICITY_RELIGION_ORIENTATION = "ethnicity_religion_orientation"
    MINORS_DATA = "minors_data"
    FREE_TEXT_PII = "free_text_pii"


class Requester(Model):
    kind: Literal["website", "application", "extension"] = "website"
    origin: str = ""
    etld_plus_one: str = ""
    bundle_id: str = ""
    exe_path: str = ""
    signer: str = ""
    display_name: str = "Unknown requester"
    purpose: str = "unknown"
    purpose_confidence: float = Field(default=0.0, ge=0, le=1)
    trust_tier: Literal["known_trusted", "known_risky", "unknown"] = "unknown"

    @property
    def key(self) -> str:
        return self.origin or self.bundle_id or self.exe_path or self.display_name


class Finding(Model):
    category: DataCategory
    confidence: float = Field(default=1.0, ge=0, le=1)
    span_ref: str = ""
    page: int | None = None
    validator_passed: bool = False
    stable_hash: str = ""


class PrivacyEvent(Model):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = "privacy"
    source: Literal["browser", "os", "clipboard", "manual"] = "browser"
    requester: Requester = Field(default_factory=Requester)
    data_categories: list[DataCategory] = Field(default_factory=list)
    payload_ref: str | None = None
    platform: str = "unknown"
    correlation_id: str | None = None


class FileUploadEvent(PrivacyEvent):
    event_type: Literal["file_upload"] = "file_upload"
    document_type: str = "generic"
    filename: str = ""
    file_count: int = Field(default=1, ge=1)
    size_bytes: int = Field(default=0, ge=0)
    partial: bool = False


class FormField(Model):
    field_id: str
    category: DataCategory | None = None
    label: str = ""
    name: str = ""
    input_type: str = "text"
    autocomplete: str = ""
    required: bool = False
    asserted_required: bool = False
    filled: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    # A short numeric box labelled "code" is a one-time passcode, not a phone number.
    max_length: int = Field(default=0, ge=0)


class FormContext(Model):
    """The prose around a form, which is what separates a signup from a mailing list.

    Field shape alone cannot tell "Email" on a newsletter box from "Email" as the
    identifier on a registration form, and necessity differs completely between them.
    """

    submit_text: str = Field(default="", max_length=200)
    heading: str = Field(default="", max_length=300)
    legend: str = Field(default="", max_length=300)
    action_path: str = Field(default="", max_length=300)
    nearby_text: str = Field(default="", max_length=600)
    page_title: str = Field(default="", max_length=300)


class FormObservedEvent(PrivacyEvent):
    event_type: Literal["form_observed"] = "form_observed"
    fields: list[FormField] = Field(default_factory=list)
    context: FormContext = Field(default_factory=FormContext)


class FormSubmitEvent(FormObservedEvent):
    event_type: Literal["form_submit"] = "form_submit"  # type: ignore[assignment]


class ConsentBannerEvent(PrivacyEvent):
    event_type: Literal["consent_banner"] = "consent_banner"
    purposes: list[str] = Field(default_factory=list)
    dark_patterns: list[str] = Field(default_factory=list)
    vendor_count: int = 0
    cmp: str = "unknown"


class PolicyDocumentEvent(PrivacyEvent):
    partial: bool = False
    event_type: Literal["policy_document"] = "policy_document"
    kind: Literal["privacy_policy", "terms"] = "privacy_policy"
    document_hash: str = ""
    missing: bool = False


class TrackingEvent(PrivacyEvent):
    event_type: Literal["tracking"] = "tracking"
    tracker_domains: list[str] = Field(default_factory=list)
    fingerprinting: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    signals: list[str] = Field(default_factory=list)


class PermissionRequestEvent(PrivacyEvent):
    event_type: Literal["permission_request"] = "permission_request"
    permission: str = ""
    state: Literal["requested", "granted", "denied", "active", "stopped"] = "requested"
    # True when the grant was already in place, rather than something that just changed.
    # A standing grant is the state of the machine, not news, and is worded that way.
    existing: bool = False


class SystemAccessEvent(PrivacyEvent):
    event_type: Literal["system_access"] = "system_access"
    accesses: list[str] = Field(default_factory=list)
    breadth: float = Field(default=0, ge=0, le=1)
    existing: bool = False


class ClipboardReadEvent(PrivacyEvent):
    event_type: Literal["clipboard_read"] = "clipboard_read"
    source: Literal["browser", "os", "clipboard", "manual"] = "clipboard"
    writer_key: str = ""
    proxy: bool = True
    cloud_sync: bool = False


class ScreenCaptureEvent(PrivacyEvent):
    event_type: Literal["screen_capture"] = "screen_capture"
    active: bool = False
    first_grant: bool = False


class StartupRegistrationEvent(PrivacyEvent):
    event_type: Literal["startup_registration"] = "startup_registration"
    mechanism: str = ""
    modified: bool = False


class DeepCheckRequestEvent(PrivacyEvent):
    event_type: Literal["deep_check"] = "deep_check"
    source: Literal["browser", "os", "clipboard", "manual"] = "manual"


Event = Annotated[
    FileUploadEvent
    | FormObservedEvent
    | FormSubmitEvent
    | ConsentBannerEvent
    | PolicyDocumentEvent
    | TrackingEvent
    | PermissionRequestEvent
    | SystemAccessEvent
    | ClipboardReadEvent
    | ScreenCaptureEvent
    | StartupRegistrationEvent
    | DeepCheckRequestEvent,
    Field(discriminator="event_type"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class Outcome(StrEnum):
    IGNORE = "IGNORE"
    INFORM = "INFORM"
    INTERVENE = "INTERVENE"


class DecisionFinding(Model):
    """One row in the widget: a warning triangle, a green tick or a neutral note."""

    label: str
    severity: Literal["warn", "ok", "info"] = "warn"
    detail: str = ""


class Decision(Model):
    event_id: str
    outcome: Outcome
    risk: float = Field(ge=0, le=1)
    explanation: str
    headline: str = ""
    body: str = ""
    findings: list[DecisionFinding] = Field(default_factory=list)
    subject: str = ""
    destination: str = ""
    rationale: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    action_labels: dict[str, str] = Field(default_factory=dict)
    primary_action: str = ""
    tertiary_action: str = ""
    # Set only when the user has authorised this action to run without being asked.
    auto_action: str = ""
    layout: Literal["body_first", "findings_first"] = "body_first"
    default_action: str = "cancel"
    # How loudly the widget should say this, from the verdict and the risk. The two
    # red tiers are the ones that hold something up; the rest only report.
    urgency: Literal["", "act_now", "attention", "heads_up", "all_clear", "note"] = ""

    @property
    def title(self) -> str:
        return self.headline or self.explanation

    @property
    def detail(self) -> str:
        return self.body if self.headline else ""


class UserResponse(Model):
    event_id: str
    action: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    remember: bool = False
