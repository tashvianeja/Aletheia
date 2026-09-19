from __future__ import annotations

from collections.abc import Mapping


def page(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title></head>
<body><h1>{title}</h1>{body}<script>{script}</script></body></html>"""


UPLOAD_FORM = """
<form id="upload" action="/received" method="post" enctype="multipart/form-data">
  <label for="file">Choose document</label><input id="file" name="document" type="file" multiple>
  <button id="submit" type="submit">Upload</button>
</form>
"""

FREE_PDF_FORM = """
<p>Download a free PDF guide.</p>
<form id="lead-form" action="/received" method="post">
 <label>Name <input name="name" autocomplete="name" required></label>
 <label>Email <input name="email" type="email" autocomplete="email" required></label>
 <label>Phone <input name="phone" autocomplete="tel"></label>
 <label>Date of birth <input name="date_of_birth" autocomplete="bday"></label>
 <label>Home address <input name="home_address" autocomplete="street-address"></label>
 <button type="submit">Get the guide</button>
</form>
"""

BANK_KYC_FORM = """
<p>Verify your identity before opening a regulated bank account.</p>
<form id="kyc" action="/received" method="post">
 <label>Date of birth <input name="date_of_birth" autocomplete="bday" required></label>
 <label>Home address <input name="home_address" autocomplete="street-address" required></label>
 <button type="submit">Verify identity</button>
</form>
"""


def cmp_body(name: str, hidden_reject: bool = False, symmetric: bool = False) -> str:
    reject_style = (
        "display:none"
        if hidden_reject
        else ("font:inherit;padding:12px" if symmetric else "font-size:12px")
    )
    accept_style = (
        "font:inherit;padding:12px"
        if symmetric
        else "font-size:20px;background:#084;color:white;padding:16px"
    )
    return f"""
<div id="cmp" class="cmp {name}" role="dialog" aria-label="Cookie consent" style="position:fixed;bottom:0;background:white;color:black">
 <p>We use necessary, analytics, and advertising cookies.</p>
 <label><input id="analytics" type="checkbox" checked> Analytics</label>
 <label><input id="advertising" type="checkbox" checked> Advertising</label>
 <button id="reject" style="{reject_style}">Reject optional</button>
 <button id="accept" style="{accept_style}">Accept all</button>
</div>
"""


CMP_SCRIPT = """
document.querySelector('#accept')?.addEventListener('click', () => {
 document.cookie='analytics=yes; SameSite=Lax'; document.cookie='advertising=yes; SameSite=Lax';
 document.querySelector('#cmp').remove(); window.consentResult='accepted';
});
document.querySelector('#reject')?.addEventListener('click', () => {
 document.cookie='necessary=yes; SameSite=Lax';
 document.querySelector('#cmp').remove(); window.consentResult='rejected';
});
"""


TERMS = """
<section id="terms-text">
 <h2>Synthetic Terms</h2>
 <p>Disputes must be resolved through binding arbitration.</p>
 <p>Submitted content may be used to train our machine learning models.</p>
 <p>Backups may retain account data after account deletion.</p>
</section>
<label><input id="agree" type="checkbox"> I agree to the <a href="/terms">Terms and Conditions</a></label>
"""

TRACKER_SCRIPT = """
for (const host of ['tracker-one.test','ads-two.test','metrics-three.test']) {
 const img=document.createElement('img'); img.width=1; img.height=1; img.src='https://'+host+'/pixel.gif?uid=synthetic-id'; document.body.append(img);
}
localStorage.setItem('cross_site_id','00000000-0000-4000-8000-000000000001');
const canvas=document.createElement('canvas'); canvas.getContext('2d').fillText('synthetic',2,2); canvas.toDataURL();
navigator.hardwareConcurrency; navigator.deviceMemory; navigator.plugins.length;
document.cookie='tracker_fixture=synthetic-id; Max-Age=31536000; SameSite=Lax';
"""

SPA_SCRIPT = """
setTimeout(() => {
 const form=document.createElement('form'); form.id='dynamic-form';
 form.innerHTML='<label>Phone <input name="phone" autocomplete="tel"></label><button>Continue</button>';
 document.body.append(form);
}, 100);
"""

SHADOW_SCRIPT = """
const host=document.querySelector('#shadow-host'); const root=host.attachShadow({mode:'open'});
root.innerHTML='<form id="shadow-form"><label>Date of birth <input name="dob" autocomplete="bday"></label></form>';
"""


PAGES: Mapping[str, str] = {
    "image-compressor": page(
        "Online Image Compressor", "<p>Compress images without an account.</p>" + UPLOAD_FORM
    ),
    "government-visa-portal": page(
        "Government Visa Portal", "<p>Upload a passport to apply for a visa.</p>" + UPLOAD_FORM
    ),
    "social-photo": page(
        "Social Photo Sharing", "<p>Share a photo with friends.</p>" + UPLOAD_FORM
    ),
    "free-pdf-download": page("Free PDF Download", FREE_PDF_FORM),
    "bank-kyc": page("Community Bank Identity Verification", BANK_KYC_FORM),
    "signup-with-terms": page("Synthetic Cloud Signup", TERMS),
    "tracker-heavy": page("Tracker Heavy News", cmp_body("onetrust"), TRACKER_SCRIPT + CMP_SCRIPT),
    "clean-blog": page(
        "Clean Gardening Blog", "<article><p>How to grow synthetic tomatoes.</p></article>"
    ),
    "hidden-reject-cmp": page(
        "Hidden Reject Shop", cmp_body("cookiebot", hidden_reject=True), CMP_SCRIPT
    ),
    "symmetric-choice-cmp": page(
        "Symmetric Choice Shop", cmp_body("trustarc", symmetric=True), CMP_SCRIPT
    ),
    "cmp-onetrust": page("OneTrust Fixture", cmp_body("onetrust"), CMP_SCRIPT),
    "cmp-cookiebot": page("Cookiebot Fixture", cmp_body("cookiebot"), CMP_SCRIPT),
    "cmp-quantcast": page("Quantcast Fixture", cmp_body("qc-cmp2-container"), CMP_SCRIPT),
    "cmp-trustarc": page("TrustArc Fixture", cmp_body("truste_box_overlay"), CMP_SCRIPT),
    "cmp-didomi": page("Didomi Fixture", cmp_body("didomi-popup-container"), CMP_SCRIPT),
    "heuristic-banner-one": page("Consent Notice", cmp_body("custom-consent"), CMP_SCRIPT),
    "heuristic-banner-two": page(
        "Privacy Choices", cmp_body("privacy-dialog", symmetric=True), CMP_SCRIPT
    ),
    "heuristic-banner-three": page("Cookies Settings", cmp_body("cookies-panel"), CMP_SCRIPT),
    "spa-dynamic-form": page("Single Page Signup", "<div id='app'></div>", SPA_SCRIPT),
    "shadow-dom-form": page("Shadow DOM Signup", "<div id='shadow-host'></div>", SHADOW_SCRIPT),
    "recipe-location-policy": page(
        "Weeknight Recipes",
        "<p>Quick dinner recipes.</p><a rel='privacy-policy' href='/privacy'>Privacy policy</a>",
    ),
}


PRIVACY_POLICY = page(
    "Synthetic Privacy Policy",
    "<p>We collect precise location for personalised advertising and share it with advertising partners. "
    "Account records may remain in backups after deletion.</p>",
)

TERMS_DOCUMENT = page("Synthetic Terms and Conditions", TERMS)
