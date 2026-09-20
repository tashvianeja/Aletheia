from __future__ import annotations

import json
from pathlib import Path

from aletheia.core.events import DataCategory

ROOT = Path(__file__).resolve().parents[1] / "src/aletheia/data"
# Curated public service domains grouped by their primary user-facing purpose.
SITES = {
    "image_tool": "tinypng.com tinyjpg.com squoosh.app compressor.io imagecompressor.com iloveimg.com remove.bg picresize.com kraken.io jpeg.io",
    "file_converter": "cloudconvert.com convertio.co zamzar.com online-convert.com freeconvert.com smallpdf.com ilovepdf.com pdf2go.com pdfcandy.com sodapdf.com",
    "ecommerce": "amazon.com ebay.com walmart.com target.com etsy.com aliexpress.com bestbuy.com costco.com ikea.com wayfair.com myntra.com flipkart.com",
    "banking": "chase.com bankofamerica.com wellsfargo.com citi.com hsbc.com barclays.co.uk natwest.com lloydsbank.com capitalone.com usbank.com hdfcbank.com icicibank.com",
    "government": "usa.gov gov.uk canada.ca australia.gov.au india.gov.in irs.gov ssa.gov travel.state.gov uscis.gov service-public.fr bund.de gov.sg",
    "healthcare_provider": "mayoclinic.org clevelandclinic.org nhs.uk kp.org hopkinsmedicine.org massgeneral.org mountsinai.org pennmedicine.org stanfordhealthcare.org uclahealth.org",
    "social": "facebook.com instagram.com reddit.com x.com mastodon.social tumblr.com pinterest.com threads.net snapchat.com tiktok.com",
    "news": "bbc.com reuters.com apnews.com theguardian.com nytimes.com washingtonpost.com npr.org aljazeera.com dw.com france24.com",
    "recipe": "allrecipes.com foodnetwork.com bbcgoodfood.com seriouseats.com simplyrecipes.com epicurious.com bonappetit.com food.com tasteofhome.com budgetbytes.com",
    "saas_b2b": "salesforce.com hubspot.com monday.com asana.com airtable.com notion.so atlassian.com zendesk.com freshworks.com clickup.com",
    "education": "coursera.org edx.org khanacademy.org udemy.com udacity.com duolingo.com futurelearn.com brilliant.org skillshare.com codecademy.com",
    "dating": "tinder.com bumble.com hinge.co match.com okcupid.com eharmony.com plentyoffish.com grindr.com happn.com coffeemeetsbagel.com",
    "job_board": "indeed.com glassdoor.com monster.com ziprecruiter.com dice.com naukri.com foundit.in reed.co.uk totaljobs.com seek.com.au",
    "developer_tool": "github.com gitlab.com bitbucket.org stackoverflow.com npmjs.com pypi.org crates.io docker.com vercel.com netlify.com",
    "vpn": "mullvad.net protonvpn.com nordvpn.com expressvpn.com surfshark.com ivpn.net windscribe.com tunnelbear.com privateinternetaccess.com hide.me",
    "wallpaper_utility": "wallhaven.cc unsplash.com pexels.com wallpaperengine.io wallpaperscraft.com interfaceLIFT.com desktopnexus.com hdqwalls.com",
    "screen_recorder": "obsproject.com loom.com screen.studio screencastify.com bandicam.com screencast-o-matic.com getsharex.com screenpal.com",
    "backup": "backblaze.com carbonite.com idrive.com acronis.com crashplan.com duplicati.com arqbackup.com restic.net borgbackup.org kopia.io",
    "password_manager": "1password.com bitwarden.com dashlane.com keepersecurity.com keepass.info keepassxc.org nordpass.com roboform.com enpass.io lastpass.com",
    "email": "gmail.com outlook.com proton.me fastmail.com mail.com tutanota.com tuta.com hey.com zoho.com gmx.com",
    "messaging": "signal.org telegram.org whatsapp.com discord.com slack.com element.io wire.com threema.ch viber.com messenger.com",
    "video_conference": "zoom.us meet.google.com webex.com whereby.com jitsi.org bigbluebutton.org ringcentral.com goto.com",
    "maps_navigation": "maps.google.com openstreetmap.org mapquest.com waze.com here.com tomtom.com bing.com/maps komoot.com alltrails.com",
    "travel_booking": "booking.com expedia.com kayak.com skyscanner.com airbnb.com hotels.com tripadvisor.com agoda.com trivago.com travelocity.com",
    "airline": "delta.com united.com aa.com southwest.com britishairways.com lufthansa.com emirates.com qatarairways.com singaporeair.com airindia.com",
    "food_delivery": "doordash.com ubereats.com grubhub.com deliveroo.co.uk justeat.co.uk swiggy.com zomato.com foodpanda.com takeaway.com seamless.com",
    "ride_hailing": "uber.com lyft.com bolt.eu grab.com gojek.com olacabs.com careem.com indrive.com",
    "finance_investing": "fidelity.com vanguard.com schwab.com robinhood.com etrade.com interactivebrokers.com zerodha.com groww.in trading212.com degiro.com",
    "insurance": "geico.com progressive.com statefarm.com allstate.com libertyMutual.com aviva.co.uk axa.com allianz.com lemonade.com usaa.com",
    "fitness": "strava.com garmin.com fitbit.com myfitnesspal.com runkeeper.com trainingpeaks.com peloton.com freeletics.com nike.com",
    "music_streaming": "spotify.com music.apple.com deezer.com tidal.com pandora.com soundcloud.com bandcamp.com qobuz.com",
    "video_streaming": "netflix.com hulu.com disneyplus.com primevideo.com max.com peacocktv.com crunchyroll.com tubitv.com vimeo.com youtube.com",
    "gaming": "steampowered.com gog.com epicgames.com itch.io ea.com ubisoft.com battle.net roblox.com minecraft.net playstation.com",
    "cloud_storage": "dropbox.com box.com drive.google.com onedrive.live.com mega.io pcloud.com sync.com tresorit.com icedrive.net internxt.com",
    "photo_editor": "canva.com pixlr.com photopea.com fotor.com befunky.com picmonkey.com lunapic.com polarr.com",
    "recruitment": "greenhouse.io lever.co workday.com workable.com smartrecruiters.com ashbyhq.com bamboohr.com personio.com",
    "legal_services": "legalzoom.com rocketlawyer.com avvo.com nolo.com findlaw.com lawdepot.com justia.com",
    "charity": "redcross.org unicef.org doctorswithoutborders.org oxfam.org charitywater.org givewell.org kiva.org",
    "shopping_comparison": "camelcamelcamel.com pricespy.co.uk idealo.de pricerunner.com shopping.google.com kelkoo.com",
    "search": "google.com duckduckgo.com bing.com brave.com ecosia.org startpage.com qwant.com mojeek.com",
    "weather": "weather.com accuweather.com weather.gov wunderground.com metoffice.gov.uk windy.com yr.no",
    "free_download": "gutenberg.org archive.org standardebooks.org openlibrary.org manybooks.net free-ebooks.net",
    "calendar": "calendly.com cal.com doodle.com teamup.com timeanddate.com",
    "productivity": "todoist.com ticktick.com evernote.com trello.com workflowy.com obsidian.md",
    "antivirus": "malwarebytes.com bitdefender.com eset.com avast.com avg.com kaspersky.com sophos.com",
    "accessibility_tool": "nvaccess.org freedomscientific.com zoomtext.com",
}
# Required and reasonable data are scoped to the purpose, never to a domain's prestige.
OVERRIDES = {
    "image_tool": {"reasonable": "files_broad biometric_photo"},
    "file_converter": {"reasonable": "files_broad"},
    "ecommerce": {
        "required": "full_name postal_address",
        "reasonable": "email phone financial.card_number age",
    },
    "banking": {
        "required": "full_name dob postal_address government_id government_id.passport government_id.national_id government_id.ssn government_id.tax_id financial financial.account_number",
        "reasonable": "email phone financial.card_number financial.iban financial.routing employment biometric_photo",
    },
    "government": {
        "required": "full_name dob government_id government_id.passport government_id.national_id government_id.ssn government_id.drivers_license government_id.tax_id biometric_photo",
        "reasonable": "postal_address email phone age gender employment education financial",
    },
    "healthcare_provider": {
        "required": "full_name dob medical medical.diagnosis medical.medication medical.insurance_id",
        "reasonable": "email phone postal_address government_id gender age biometric_photo",
    },
    "social": {
        "reasonable": "full_name email age biometric_photo contacts camera microphone location_coarse"
    },
    "news": {"reasonable": "email age"},
    "recipe": {"reasonable": "email"},
    "saas_b2b": {"reasonable": "full_name email employment credentials.password"},
    "education": {"reasonable": "full_name email age education minors_data"},
    "dating": {
        "required": "age",
        "reasonable": "full_name email gender biometric_photo location_coarse ethnicity_religion_orientation",
    },
    "job_board": {"reasonable": "full_name email phone employment education postal_address"},
    "developer_tool": {"reasonable": "full_name email files_broad credentials.api_key"},
    "vpn": {"required": "background_execution", "reasonable": "startup automation email"},
    "wallpaper_utility": {"reasonable": "background_execution startup"},
    "screen_recorder": {
        "required": "screen",
        "reasonable": "microphone camera files_broad accessibility",
    },
    "backup": {
        "required": "files_broad background_execution startup",
        "reasonable": "automation email",
    },
    "password_manager": {
        "required": "credentials credentials.password credentials.api_key credentials.private_key",
        "reasonable": "clipboard accessibility background_execution startup",
    },
    "email": {
        "required": "email",
        "reasonable": "full_name contacts calendar files_broad credentials.password",
    },
    "messaging": {"reasonable": "full_name phone email contacts microphone camera biometric_photo"},
    "video_conference": {
        "required": "microphone camera",
        "reasonable": "screen full_name email calendar",
    },
    "maps_navigation": {
        "required": "location_precise",
        "reasonable": "location_coarse postal_address background_execution",
    },
    "travel_booking": {
        "required": "full_name",
        "reasonable": "email phone dob postal_address government_id.passport financial.card_number",
    },
    "airline": {
        "required": "full_name dob government_id.passport",
        "reasonable": "email phone gender financial.card_number",
    },
    "food_delivery": {
        "required": "postal_address",
        "reasonable": "full_name phone email location_precise financial.card_number",
    },
    "ride_hailing": {
        "required": "location_precise",
        "reasonable": "full_name phone financial.card_number",
    },
    "finance_investing": {
        "required": "full_name dob government_id government_id.tax_id financial financial.account_number",
        "reasonable": "email phone postal_address employment",
    },
    "insurance": {
        "required": "full_name dob postal_address",
        "reasonable": "email phone medical medical.diagnosis employment financial",
    },
    "fitness": {
        "reasonable": "full_name email age gender medical location_precise biometric_photo"
    },
    "music_streaming": {"reasonable": "email age"},
    "video_streaming": {"reasonable": "email age financial.card_number"},
    "gaming": {"reasonable": "email age microphone camera credentials.password"},
    "cloud_storage": {
        "required": "files_broad",
        "reasonable": "email background_execution startup",
    },
    "photo_editor": {"reasonable": "biometric_photo camera files_broad"},
    "recruitment": {
        "required": "full_name employment education",
        "reasonable": "email phone postal_address",
    },
    "legal_services": {
        "reasonable": "full_name email phone postal_address government_id financial"
    },
    "charity": {"reasonable": "full_name email postal_address financial.card_number"},
    "shopping_comparison": {"reasonable": "email location_coarse"},
    "search": {"reasonable": "location_coarse"},
    "weather": {"reasonable": "location_coarse location_precise"},
    "free_download": {"reasonable": "full_name email"},
    "calendar": {"required": "calendar", "reasonable": "full_name email contacts"},
    "productivity": {"reasonable": "full_name email files_broad calendar"},
    "antivirus": {
        "required": "files_broad background_execution startup",
        "reasonable": "automation accessibility browser_history",
    },
    "accessibility_tool": {
        "required": "accessibility screen",
        "reasonable": "automation microphone clipboard background_execution startup",
    },
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    sites = {
        domain.lower().split("/")[0]: {
            "purpose": purpose,
            "confidence": 0.95,
            "trust_tier": "unknown",
        }
        for purpose, domains in SITES.items()
        for domain in domains.split()
    }
    matrix = {}
    sensitive = {
        "government_id",
        "financial",
        "medical",
        "credentials",
        "ethnicity_religion_orientation",
        "minors_data",
    }
    for purpose in SITES:
        vector = {
            category.value: "red_flag"
            if category.value.split(".")[0] in sensitive
            else "unnecessary"
            for category in DataCategory
        }
        for verdict, categories in OVERRIDES[purpose].items():
            for category in categories.split():
                vector[category] = verdict
        matrix[purpose] = {
            "justification": f"A {purpose.replace('_', ' ')} needs information related to its stated task.",
            "categories": vector,
        }
    sensitivity = {category.value: 0.55 for category in DataCategory}
    for category in DataCategory:
        root = category.value.split(".")[0]
        sensitivity[category.value] = {
            "government_id": 0.95,
            "medical": 0.9,
            "financial": 0.9,
            "credentials": 1.0,
        }.get(root, sensitivity[category.value])
    sensitivity.update(
        full_name=0.3,
        email=0.3,
        phone=0.5,
        postal_address=0.6,
        dob=0.6,
        age=0.3,
        gender=0.35,
        biometric_photo=0.9,
        location_precise=0.5,
        location_coarse=0.3,
        device_identifiers=0.4,
        browsing_activity=0.45,
        files_broad=0.9,
        camera=0.8,
        microphone=0.85,
        screen=0.9,
        accessibility=0.95,
        automation=0.85,
        background_execution=0.45,
        startup=0.45,
        browser_history=0.8,
        ethnicity_religion_orientation=0.9,
        minors_data=0.95,
    )
    for name, data in [
        ("known_sites", sites),
        ("necessity_matrix", matrix),
        ("sensitivity", sensitivity),
    ]:
        (ROOT / f"{name}.yaml").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"{len(sites)} curated domains; {len(matrix)} purposes; {len(DataCategory)} categories")


if __name__ == "__main__":
    main()
