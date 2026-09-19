from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from privacy_guardian.analysis.worker import analyze_payload
from privacy_guardian.core.ipc.transport import send_request
from tests.e2e.conftest import RealBrowser

pytestmark = pytest.mark.e2e


async def native_ping(browser: RealBrowser) -> dict[str, object]:
    return await browser.worker.evaluate(
        """() => new Promise(resolve => {
          const port = chrome.runtime.connectNative('com.privacyguardian.host');
          const timer = setTimeout(() => resolve({error: 'native response timeout'}), 5000);
          port.onMessage.addListener(message => { clearTimeout(timer); port.disconnect(); resolve(message); });
          port.onDisconnect.addListener(() => { clearTimeout(timer); resolve({error: chrome.runtime.lastError?.message || 'native host disconnected'}); });
          port.postMessage({v:1,id:'direct-native-ping',type:'ping',payload:{browser:'chromium-e2e'}});
        })"""
    )


async def latest_decision(browser: RealBrowser, event_type: str) -> tuple[str, str] | None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sqlite3.connect(browser.data_dir / "guardian.sqlite3") as connection:
            row = connection.execute(
                "SELECT e.id,d.outcome FROM events e JOIN decisions d ON d.event_id=e.id "
                "WHERE e.event_type=? ORDER BY d.id DESC LIMIT 1",
                (event_type,),
            ).fetchone()
        if row:
            return str(row[0]), str(row[1])
        await asyncio.sleep(0.05)
    return None


async def desktop_action(browser: RealBrowser, event_id: str, action: str) -> dict[str, object]:
    return await send_request(
        browser.data_dir,
        {
            "v": 1,
            "id": "desktop-action",
            "type": "action",
            "payload": {"event_id": event_id, "action": action},
        },
    )


async def fill_free_download(page: object) -> None:
    values = {
        "name": "Morgan Synthetic",
        "email": "morgan@example.test",
        "phone": "+1 202 555 0142",
        "date_of_birth": "2000-01-01",
        "home_address": "100 Test Avenue",
    }
    for name, value in values.items():
        await page.locator(f'[name="{name}"]').fill(value)


@pytest.mark.asyncio
async def test_real_extension_native_service_labels_unnecessary_fields(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    errors: list[str] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    ping = await native_ping(real_browser)
    assert ping.get("ok") is True, ping
    await page.goto(f"{base_url}/fixtures/free-pdf-download")

    await page.locator(".pg-badge").first.wait_for(timeout=10_000)

    badges = await page.locator(".pg-badge").all_text_contents()
    assert badges == ["May be unnecessary"] * 3
    assert not errors


@pytest.mark.asyncio
async def test_dynamic_shadow_form_is_inventoried_within_half_a_second(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    # Separate one-time native-host startup from the dynamic-node observation budget.
    await page.goto(f"{base_url}/fixtures/free-pdf-download")
    await page.locator(".pg-badge").first.wait_for(timeout=10_000)
    await page.goto(f"{base_url}/fixtures/shadow-dom-form")
    await page.wait_for_function("document.querySelector('#shadow-host')?.shadowRoot")
    latency_ms = await page.locator("#shadow-host").evaluate(
        "host => new Promise((resolve,reject) => { const limit=setTimeout(()=>reject(new Error('badge timeout')),5000); const poll=()=>{if(host.shadowRoot.querySelector('.pg-badge')){clearTimeout(limit);resolve(performance.now()-window.shadowAttachedAt)}else requestAnimationFrame(poll)};poll(); })"
    )

    assert latency_ms <= 500


@pytest.mark.asyncio
async def test_symmetric_consent_fixture_is_not_flagged_as_dark_pattern(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/symmetric-choice-cmp")

    assert await page.locator(".cmp").count() == 1
    if await page.locator(".pg-panel").count():
        assert "harder" not in (await page.locator(".pg-panel").inner_text()).lower()
    decision = await latest_decision(real_browser, "consent_banner")
    assert decision is not None and decision[1] == "INFORM"


@pytest.mark.asyncio
async def test_free_download_review_highlights_only_three_unnecessary_fields(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/free-pdf-download")
    await fill_free_download(page)
    await page.locator(".pg-badge").first.wait_for(timeout=5_000)
    assert await page.locator(".pg-badge").count() == 3

    await page.locator("#lead-form button[type=submit]").click()
    review = page.locator('.pg-panel [data-pg-action="review_fields"]')
    await review.wait_for(timeout=5_000)
    decision = await latest_decision(real_browser, "form_submit")
    assert decision is not None and decision[1] == "INTERVENE"
    await review.click()

    await page.locator(".pg-review").first.wait_for(timeout=2_000)
    assert await page.locator(".pg-review").count() == 3
    assert state.submissions == []


@pytest.mark.asyncio
async def test_free_download_continue_submits_without_persisting_values(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/free-pdf-download")
    await fill_free_download(page)
    await page.locator(".pg-badge").first.wait_for(timeout=5_000)
    await page.locator("#lead-form button[type=submit]").click()
    continuation = page.locator('.pg-panel [data-pg-action="continue"]')
    await continuation.wait_for(timeout=5_000)
    await continuation.click()

    for _attempt in range(100):
        if state.submissions:
            break
        await asyncio.sleep(0.05)
    assert state.submissions == [
        {
            "name": "present",
            "email": "present",
            "phone": "present",
            "date_of_birth": "present",
            "home_address": "present",
        }
    ]
    with sqlite3.connect(real_browser.data_dir / "guardian.sqlite3") as connection:
        dump = "\n".join(connection.iterdump())
    assert "Morgan Synthetic" not in dump
    assert "morgan@example.test" not in dump
    assert "+1 202 555 0142" not in dump


@pytest.mark.asyncio
async def test_bank_kyc_has_no_badges_or_intervention_and_submits(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/bank-kyc")
    await page.locator('[name="date_of_birth"]').fill("2000-01-01")
    await page.locator('[name="home_address"]').fill("100 Test Avenue")
    await page.wait_for_timeout(500)
    assert await page.locator(".pg-badge").count() == 0
    await page.locator("#kyc button[type=submit]").click()
    for _attempt in range(100):
        if state.submissions:
            break
        await asyncio.sleep(0.05)
    assert state.submissions
    decision = await latest_decision(real_browser, "form_submit")
    assert decision is not None and decision[1] != "INTERVENE"


@pytest.mark.asyncio
async def test_hidden_reject_desktop_action_rejects_only_optional_cookies(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/hidden-reject-cmp")
    await page.locator(".pg-panel").wait_for(timeout=5_000)
    decision = await latest_decision(real_browser, "consent_banner")
    assert decision is not None and decision[1] == "INTERVENE"
    panel_text = (await page.locator(".pg-panel").inner_text()).lower()
    assert "harder" in panel_text

    response = await desktop_action(real_browser, decision[0], "reject_optional")
    assert response["ok"] is True
    await page.locator(".cmp").wait_for(state="detached", timeout=5_000)

    assert await page.evaluate("window.consentResult") == "rejected"
    cookies = {cookie["name"] for cookie in await real_browser.context.cookies()}
    assert cookies == {"necessary"}


@pytest.mark.asyncio
async def test_passport_redacted_copy_replaces_input_and_rescans_clean(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/image-compressor")
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    started = time.perf_counter()
    await page.locator("#file").set_input_files(passport)
    redact = page.locator('.pg-panel [data-pg-action="redact"]')
    await redact.wait_for(timeout=10_000)
    intervention_seconds = time.perf_counter() - started
    decision = await latest_decision(real_browser, "file_upload")
    assert decision is not None and decision[1] == "INTERVENE"
    await redact.click()
    await page.wait_for_function(
        "document.querySelector('#file').files[0]?.name !== 'passport_synthetic.pdf'"
    )
    content = await page.locator("#file").evaluate(
        "async input => Array.from(new Uint8Array(await input.files[0].arrayBuffer()))"
    )
    rescanned = analyze_payload(
        {"kind": "document", "filename": "redacted.pdf", "data": bytes(content)}
    )
    assert rescanned.findings == []
    assert intervention_seconds <= 1.5


@pytest.mark.asyncio
async def test_passport_cancel_keeps_form_from_reaching_server(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/image-compressor")
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    await page.locator("#file").set_input_files(passport)
    cancel = page.locator('.pg-panel [data-pg-action="cancel"]')
    await cancel.wait_for(timeout=10_000)
    await cancel.click()
    await page.locator("#submit").click()
    await page.wait_for_timeout(500)
    assert state.submissions == []


@pytest.mark.asyncio
async def test_government_passport_is_not_intervened_and_upload_proceeds(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/government-visa-portal")
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    await page.locator("#file").set_input_files(passport)
    decision = await latest_decision(real_browser, "file_upload")
    assert decision is not None and decision[1] in {"IGNORE", "INFORM"}
    await page.locator("#submit").click()
    for _attempt in range(100):
        if state.uploads:
            break
        await asyncio.sleep(0.05)
    assert state.uploads and state.uploads[0][0] == "passport_synthetic.pdf"


@pytest.mark.asyncio
async def test_social_photo_strip_metadata_upload_has_no_gps(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/social-photo")
    photo = Path(__file__).resolve().parents[1] / "fixtures/social_photo_gps_synthetic.jpg"
    await page.locator("#file").set_input_files(photo)
    strip = page.locator('.pg-panel [data-pg-action="strip_metadata"]')
    await strip.wait_for(timeout=10_000)
    decision = await latest_decision(real_browser, "file_upload")
    assert decision is not None and decision[1] == "INFORM"
    await strip.click()
    await page.wait_for_function(
        "document.querySelector('#file').files[0]?.name !== 'social_photo_gps_synthetic.jpg'"
    )
    await page.locator("#submit").click()
    for _attempt in range(100):
        if state.uploads:
            break
        await asyncio.sleep(0.05)
    assert state.uploads
    uploaded = analyze_payload(
        {"kind": "document", "filename": state.uploads[0][0], "data": state.uploads[0][2]}
    )
    assert all(finding.category.value != "location_precise" for finding in uploaded.findings)


@pytest.mark.asyncio
async def test_terms_interception_shows_three_risks_and_preserves_checkbox_state(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/signup-with-terms")
    await page.locator("#agree").click()
    panel = page.locator(".pg-panel")
    await panel.wait_for(timeout=5_000)
    text = (await panel.inner_text()).lower()
    assert "arbitration" in text
    assert "training" in text
    assert "retention" in text or "deletion" in text
    assert "payment" in text
    assert "account" in text
    assert "basic" in text
    assert text.count("✓") >= 3
    await panel.locator('[data-pg-action="continue"]').click()
    await panel.wait_for(state="detached", timeout=3_000)
    assert await page.locator("#agree").is_checked()


@pytest.mark.asyncio
async def test_tracker_block_adds_dnr_rules_and_preserves_unrelated_storage(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/tracker-heavy")
    await page.evaluate("localStorage.setItem('shopping_cart','synthetic-cart-item')")
    await page.evaluate(
        """() => new Promise((resolve,reject) => {
          const request=indexedDB.open('unrelated-shopping',1);
          request.onupgradeneeded=()=>request.result.createObjectStore('cart');
          request.onerror=()=>reject(request.error);
          request.onsuccess=()=>{const tx=request.result.transaction('cart','readwrite');tx.objectStore('cart').put('synthetic-item','current');tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)};
        })"""
    )
    await real_browser.context.add_cookies(
        [
            {"name": "synthetic_uid", "value": "one", "domain": host, "path": "/"}
            for host in ("tracker-one.test", "ads-two.test", "metrics-three.test")
        ]
    )
    block = page.locator('.pg-panel [data-pg-action="block"]')
    await block.wait_for(timeout=5_000)
    decision = await latest_decision(real_browser, "tracking")
    assert decision is not None and decision[1] == "INFORM"
    await block.click()
    await block.wait_for(state="detached", timeout=5_000)

    expected_filters = {
        "||tracker-one.test^",
        "||ads-two.test^",
        "||metrics-three.test^",
    }
    filters: set[str | None] = set()
    for _attempt in range(100):
        rules = await real_browser.worker.evaluate("chrome.declarativeNetRequest.getDynamicRules()")
        filters = {rule["condition"].get("urlFilter") for rule in rules}
        if expected_filters <= filters:
            break
        await asyncio.sleep(0.05)
    assert expected_filters <= filters
    assert await page.evaluate("localStorage.getItem('shopping_cart')") == "synthetic-cart-item"
    indexed_value = await page.evaluate(
        """() => new Promise((resolve,reject) => {const request=indexedDB.open('unrelated-shopping');request.onerror=()=>reject(request.error);request.onsuccess=()=>{const tx=request.result.transaction('cart');const get=tx.objectStore('cart').get('current');get.onsuccess=()=>resolve(get.result);get.onerror=()=>reject(get.error)}})"""
    )
    assert indexed_value == "synthetic-item"
    for host in ("tracker-one.test", "ads-two.test", "metrics-three.test"):
        assert await real_browser.context.cookies(f"https://{host}/") == []
    await page.reload()
    persisted_rules = await real_browser.worker.evaluate(
        "chrome.declarativeNetRequest.getDynamicRules()"
    )
    assert expected_filters <= {rule["condition"].get("urlFilter") for rule in persisted_rules}


@pytest.mark.asyncio
async def test_recipe_deep_check_reports_unnecessary_precise_location(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/recipe-location-policy")
    await native_ping(real_browser)
    result = await send_request(
        real_browser.data_dir,
        {
            "v": 1,
            "id": "recipe-deep-check",
            "type": "deep_check",
            "payload": {"origin": base_url},
        },
        timeout=10,
    )
    assert result["ok"] is True
    summaries = " ".join(str(item["summary"]) for item in result["result"]["findings"]).lower()
    assert "precise location" in summaries
    assert "not appear necessary" in summaries or "unnecessary" in summaries
