"""The words Aletheia uses for data categories and site purposes.

Both the necessity engine and the explanation layer name the same things, so the
table lives here rather than in either of them.
"""

from __future__ import annotations

LABELS = {
    "government_id": "Government ID",
    "government_id.passport": "Passport number",
    "government_id.national_id": "National ID number",
    "government_id.ssn": "Social security number",
    "government_id.drivers_license": "Driving licence number",
    "government_id.tax_id": "Tax identification number",
    "full_name": "Full name",
    "dob": "Date of birth",
    "age": "Age",
    "gender": "Gender",
    "email": "Email",
    "phone": "Phone number",
    "postal_address": "Home address",
    "biometric_photo": "Biometric photo",
    "financial": "Financial details",
    "financial.card_number": "Card number",
    "financial.iban": "Bank account (IBAN)",
    "financial.account_number": "Bank account number",
    "financial.routing": "Bank routing number",
    "medical": "Medical information",
    "medical.diagnosis": "Medical diagnosis",
    "medical.medication": "Medication",
    "medical.insurance_id": "Health insurance ID",
    "credentials": "Credentials",
    "credentials.password": "Password",
    "credentials.api_key": "API key",
    "credentials.private_key": "Private key",
    "location_precise": "Precise location",
    "location_coarse": "Approximate location",
    "device_identifiers": "Persistent device identifiers",
    "browsing_activity": "Browsing activity",
    "browser_history": "Browser history",
    "contacts": "Contacts",
    "calendar": "Calendar",
    "files_broad": "Full file access",
    "camera": "Camera",
    "microphone": "Microphone",
    "screen": "Screen recording",
    "clipboard": "Clipboard",
    "accessibility": "Accessibility control",
    "automation": "System automation",
    "background_execution": "Background execution",
    "startup": "Startup access",
    "employment": "Employment history",
    "education": "Education history",
    "ethnicity_religion_orientation": "Ethnicity, religion or orientation",
    "minors_data": "Information about a child",
    "free_text_pii": "Personal details in free text",
}

# Labels that are grammatically plural, so a sentence about one of them still reads:
# "Persistent device identifiers do not appear necessary", never "does". Matched
# exactly, because "Financial details" is plural where "Card number" is not.
PLURAL_LABELS = frozenset(
    {"device_identifiers", "contacts", "credentials", "financial", "free_text_pii"}
)


def plural_label(category: str) -> bool:
    return category in PLURAL_LABELS


# Every purpose in the necessity matrix needs a name that reads in a sentence:
# these appear as "does not appear necessary for a <name>", where the bare matrix
# key gave "a banking" and "a ecommerce".
PURPOSE_NAMES = {
    "airline": "airline",
    "antivirus": "antivirus app",
    "backup": "backup tool",
    "banking": "bank",
    "calendar": "calendar app",
    "charity": "charity",
    "dating": "dating service",
    "ecommerce": "online shop",
    "education": "education service",
    "email": "email service",
    "fitness": "fitness app",
    "insurance": "insurer",
    "messaging": "messaging app",
    "photo_editor": "photo editor",
    "productivity": "productivity tool",
    "recruitment": "recruiter",
    "vpn": "VPN service",
    "government": "government service",
    "news": "news site",
    "search": "search engine",
    "social": "social network",
    "recipe": "recipe site",
    "gaming": "game",
    "weather": "weather service",
    "image_tool": "image tool",
    "file_converter": "file converter",
    "free_download": "free download",
    "wallpaper_utility": "wallpaper app",
    "saas_b2b": "business tool",
    "maps_navigation": "maps app",
    "video_conference": "video call service",
    "healthcare_provider": "healthcare provider",
    "finance_investing": "investment service",
    "shopping_comparison": "price comparison site",
    "screen_recorder": "screen recorder",
    "password_manager": "password manager",
    "developer_tool": "developer tool",
    "accessibility_tool": "accessibility tool",
    "job_board": "job board",
    "ride_hailing": "ride-hailing service",
    "food_delivery": "food delivery service",
    "travel_booking": "travel booking site",
    "music_streaming": "music service",
    "video_streaming": "video service",
    "cloud_storage": "file sharing service",
    "legal_services": "legal service",
}


def category_label(value: str) -> str:
    return LABELS.get(value, value.replace(".", " ").replace("_", " ").capitalize())


def purpose_label(purpose: str) -> str:
    return PURPOSE_NAMES.get(purpose, purpose.replace("_", " "))


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def lowered(label: str) -> str:
    """Drop a label's leading capital mid-sentence, but leave "IBAN" and "API key" alone."""
    return label[:1].lower() + label[1:] if label[1:] == label[1:].lower() else label
