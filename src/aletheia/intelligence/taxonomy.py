from __future__ import annotations

from enum import StrEnum


class FormIntent(StrEnum):
    """What the person is trying to do, which is what necessity has to be judged against.

    The previous model asked "what kind of site is this" and answered necessity from a
    site-category table. That cannot distinguish an Instagram signup, where a phone
    number is the account identifier, from a recipe blog's mailing-list box, where the
    same field is pure over-collection.
    """

    ACCOUNT_SIGNUP = "account_signup"
    ACCOUNT_LOGIN = "account_login"
    PASSWORD_RESET = "password_reset"
    TWO_FACTOR = "two_factor"
    CHECKOUT_PAYMENT = "checkout_payment"
    SHIPPING_ADDRESS = "shipping_address"
    NEWSLETTER = "newsletter"
    LEAD_CAPTURE = "lead_capture"
    CONTACT_SUPPORT = "contact_support"
    PROFILE_EDIT = "profile_edit"
    IDENTITY_VERIFICATION = "identity_verification"
    JOB_APPLICATION = "job_application"
    BOOKING = "booking"
    SURVEY_FEEDBACK = "survey_feedback"
    SEARCH_FILTER = "search_filter"
    UNKNOWN = "unknown"


class FieldRole(StrEnum):
    """Why this particular field is on this particular form."""

    PRIMARY_IDENTIFIER = "primary_identifier"
    ALTERNATE_IDENTIFIER = "alternate_identifier"
    CREDENTIAL = "credential"
    PAYMENT_INSTRUMENT = "payment_instrument"
    DELIVERY_TARGET = "delivery_target"
    CONTACT_CHANNEL = "contact_channel"
    VERIFICATION_EVIDENCE = "verification_evidence"
    PROFILE_DETAIL = "profile_detail"
    MARKETING_OPTIONAL = "marketing_optional"
    UNRELATED_COLLECTION = "unrelated_collection"


# Phrases a real form uses for each intent. These are embedded once at build time into
# centroids; matching is nearest-centroid in sentence space, so wording the site author
# actually chose ("Join free today", "Únete ahora") does not have to appear here.
EXEMPLARS: dict[FormIntent, tuple[str, ...]] = {
    FormIntent.ACCOUNT_SIGNUP: (
        "Create your account",
        "Sign up for a free account",
        "Join now and get started",
        "Register a new account",
        "Create a username and password",
        "Get started - it only takes a minute",
        "Crear cuenta nueva",
        "Konto erstellen",
    ),
    FormIntent.ACCOUNT_LOGIN: (
        "Log in to your account",
        "Sign in with your email and password",
        "Welcome back, please sign in",
        "Enter your credentials to continue",
        "Member login",
        "Iniciar sesión",
        "Anmelden",
    ),
    FormIntent.PASSWORD_RESET: (
        "Reset your password",
        "Forgot your password",
        "Choose a new password",
        "Send me a recovery link",
        "Account recovery",
    ),
    FormIntent.TWO_FACTOR: (
        "Enter the verification code we sent you",
        "Two-factor authentication code",
        "Enter the 6 digit code",
        "Confirm it is you with a one time passcode",
    ),
    FormIntent.CHECKOUT_PAYMENT: (
        "Payment details",
        "Enter your card number to pay",
        "Complete your purchase",
        "Place your order",
        "Billing information",
        "Pay now securely",
        "Finalizar compra",
    ),
    FormIntent.SHIPPING_ADDRESS: (
        "Shipping address",
        "Where should we deliver your order",
        "Delivery details",
        "Enter your postal address for delivery",
        "Dirección de envío",
    ),
    FormIntent.NEWSLETTER: (
        "Subscribe to our newsletter",
        "Get weekly updates in your inbox",
        "Join our mailing list",
        "Sign up for email updates",
        "Stay in the loop",
    ),
    FormIntent.LEAD_CAPTURE: (
        "Download the free ebook",
        "Get your free guide instantly",
        "Request a demo and our sales team will call you",
        "Unlock the free report",
        "Enter your details to claim your free trial",
        "Get a free quote from our advisors",
    ),
    FormIntent.CONTACT_SUPPORT: (
        "Contact us",
        "Send us a message",
        "How can we help you today",
        "Get in touch with support",
        "Leave your question and we will reply",
    ),
    FormIntent.PROFILE_EDIT: (
        "Edit your profile",
        "Update your account settings",
        "Change your personal information",
        "Manage your details",
    ),
    FormIntent.IDENTITY_VERIFICATION: (
        "Verify your identity",
        "Upload a photo of your passport or ID",
        "Know your customer verification",
        "Confirm your date of birth to continue",
        "Identity and address verification",
    ),
    FormIntent.JOB_APPLICATION: (
        "Apply for this job",
        "Upload your resume or CV",
        "Tell us about your work experience",
        "Job application form",
    ),
    FormIntent.BOOKING: (
        "Book your appointment",
        "Reserve a table",
        "Complete your reservation",
        "Choose your travel dates",
        "Passenger details",
    ),
    FormIntent.SURVEY_FEEDBACK: (
        "Take our survey",
        "Tell us what you think",
        "Rate your experience",
        "Customer feedback form",
    ),
    FormIntent.SEARCH_FILTER: (
        "Search",
        "Filter results",
        "Find what you are looking for",
        "Sort and refine",
    ),
}
