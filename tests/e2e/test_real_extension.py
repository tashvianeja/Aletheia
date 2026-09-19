from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import time
from pathlib import Path

import psutil
import pytest
from playwright.async_api import async_playwright

from privacy_guardian.analysis.worker import analyze_payload
from privacy_guardian.core.ipc.transport import send_request
from tests.e2e.conftest import PERFORMANCE_TOLERANCE, RealBrowser

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


def decision_count(browser: RealBrowser, event_type: str) -> int:
    with sqlite3.connect(browser.data_dir / "guardian.sqlite3") as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type=?", (event_type,)
            ).fetchone()[0]
        )


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
    await page.add_init_script(
        """(() => {
          window.__pgSensitiveInputVisibleAt = null;
          window.__pgAllBadgesVisibleAt = null;
          const observe = () => {
            const sensitive = document.querySelector(
              'input[name="phone"],input[name="date_of_birth"],input[name="home_address"]'
            );
            if (
              sensitive && sensitive.getClientRects().length &&
              window.__pgSensitiveInputVisibleAt === null
            ) window.__pgSensitiveInputVisibleAt = performance.now();
            const badges = [...document.querySelectorAll('.pg-badge')];
            if (
              badges.length === 3 && badges.every(badge => badge.getClientRects().length) &&
              window.__pgAllBadgesVisibleAt === null
            ) window.__pgAllBadgesVisibleAt = performance.now();
          };
          new MutationObserver(observe).observe(document, {
            subtree: true, childList: true, attributes: true
          });
          document.addEventListener('DOMContentLoaded', observe, {once: true});
        })();"""
    )
    ping = await native_ping(real_browser)
    assert ping.get("ok") is True, ping
    started = time.perf_counter()
    await page.goto(f"{base_url}/fixtures/free-pdf-download")

    await page.locator(".pg-badge").first.wait_for(timeout=10_000)
    await page.wait_for_function(
        "Number.isFinite(window.__pgSensitiveInputVisibleAt) && "
        "Number.isFinite(window.__pgAllBadgesVisibleAt)",
        timeout=10_000,
    )
    navigation_latency_ms = (time.perf_counter() - started) * 1000
    timing = await page.evaluate(
        "({input:window.__pgSensitiveInputVisibleAt,badges:window.__pgAllBadgesVisibleAt})"
    )
    assert timing["input"] is not None and timing["badges"] is not None, timing
    observation_latency_ms = float(timing["badges"]) - float(timing["input"])
    assert observation_latency_ms > 0, timing
    print(f"initial navigation-to-form-badge latency: {navigation_latency_ms:.3f}ms")
    print(f"form-observation-to-visible-badges latency: {observation_latency_ms:.3f}ms")

    badges = await page.locator(".pg-badge").all_text_contents()
    assert badges == ["May be unnecessary"] * 3
    assert observation_latency_ms <= 300 * PERFORMANCE_TOLERANCE, observation_latency_ms
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

    print(f"warm dynamic shadow badge latency: {latency_ms:.3f}ms")
    assert latency_ms <= 500 * PERFORMANCE_TOLERANCE


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
async def test_consent_mutation_main_thread_detection_stays_under_30ms(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    clean_base = base_url.replace("127.0.0.1", "localhost")
    await page.goto(f"{clean_base}/fixtures/clean-blog")
    await native_ping(real_browser)
    cdp = await real_browser.context.new_cdp_session(page)
    trace_events: list[dict[str, object]] = []
    trace_complete = asyncio.Event()
    cdp.on("Tracing.dataCollected", lambda event: trace_events.extend(event["value"]))
    cdp.on("Tracing.tracingComplete", lambda _event: trace_complete.set())
    await cdp.send(
        "Tracing.start",
        {
            "categories": "devtools.timeline,v8.execute",
            "options": "record-as-much-as-possible",
        },
    )
    await page.evaluate(
        """() => {
          const banner=document.createElement('div');
          banner.id='onetrust-banner-sdk';banner.className='cmp';banner.role='dialog';
          banner.innerHTML='<p>We use necessary and analytics cookies.</p><button id="onetrust-reject-all-handler">Reject all</button><button>Accept all</button>';
          document.body.append(banner);
        }"""
    )
    await page.locator(".pg-panel").wait_for(timeout=5_000)
    await cdp.send("Tracing.end")
    await asyncio.wait_for(trace_complete.wait(), 5)
    consent_events = [
        event
        for event in trace_events
        if "/content/consent.js" in str(event.get("args", {})) and event.get("dur")
    ]
    main_thread_ms = sum(float(event["dur"]) for event in consent_events) / 1000
    print(
        f"consent content-script main-thread time: {main_thread_ms:.3f}ms "
        f"across {len(consent_events)} trace events"
    )
    assert consent_events, "CDP trace contained no consent.js execution"
    assert main_thread_ms < 30 * PERFORMANCE_TOLERANCE, main_thread_ms


@pytest.mark.asyncio
async def test_consent_mutation_reaches_verdict_within_400ms(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/clean-blog")
    await native_ping(real_browser)
    await page.evaluate(
        """() => {
          window.pgConsentInsertedAt=performance.now();
          const banner=document.createElement('div');
          banner.id='onetrust-banner-sdk';banner.className='cmp';banner.role='dialog';
          banner.innerHTML='<p>We use necessary and analytics cookies.</p><label><input checked type="checkbox">Analytics</label><button id="onetrust-reject-all-handler">Reject all</button><button>Accept all</button>';
          document.body.append(banner);
        }"""
    )
    await page.locator(".pg-panel").wait_for(timeout=5_000)
    elapsed_ms = await page.evaluate("performance.now()-window.pgConsentInsertedAt")
    print(f"consent mutation-to-verdict latency: {elapsed_ms:.3f}ms")
    assert elapsed_ms <= 400 * PERFORMANCE_TOLERANCE, elapsed_ms


@pytest.mark.asyncio
async def test_five_known_cmps_and_three_heuristic_banners_are_detected(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    fixtures = (
        "cmp-onetrust",
        "cmp-cookiebot",
        "cmp-quantcast",
        "cmp-trustarc",
        "cmp-didomi",
        "heuristic-banner-one",
        "heuristic-banner-two",
        "heuristic-banner-three",
    )
    for fixture in fixtures:
        before = decision_count(real_browser, "consent_banner")
        await page.goto(f"{base_url}/fixtures/{fixture}")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if decision_count(real_browser, "consent_banner") > before:
                break
            await asyncio.sleep(0.05)
        assert decision_count(real_browser, "consent_banner") > before, fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["cmp-onetrust", "cmp-cookiebot", "cmp-trustarc"])
async def test_known_cmp_reject_optional_action_actuates_fixture(
    real_browser: RealBrowser, fixture_site: tuple[str, object], fixture: str
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/{fixture}")
    reject = page.locator('.pg-panel [data-pg-action="reject_optional"]')
    await reject.wait_for(timeout=5_000)
    await reject.click()
    await page.locator(".cmp").wait_for(state="detached", timeout=3_000)
    assert await page.evaluate("window.consentResult") == "rejected"
    assert {cookie["name"] for cookie in await real_browser.context.cookies()} == {"necessary"}


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
    await page.evaluate(
        """() => {
          window.__pgSelectionStarted = null;
          window.__pgPanelVisible = null;
          document.querySelector('#file').addEventListener('change', () => {
            window.__pgSelectionStarted = performance.now();
          }, {once:true});
          new MutationObserver(() => {
            const action=document.querySelector('.pg-panel [data-pg-action="redact"]');
            if (action && action.getClientRects().length && window.__pgPanelVisible === null) {
              window.__pgPanelVisible=performance.now();
            }
          }).observe(document.documentElement,{subtree:true,childList:true,attributes:true});
        }"""
    )
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    started = time.perf_counter()
    await page.locator("#file").set_input_files(passport)
    redact = page.locator('.pg-panel [data-pg-action="redact"]')
    await redact.wait_for(timeout=10_000)
    intervention_seconds = time.perf_counter() - started
    dom_intervention_ms = await page.evaluate("window.__pgPanelVisible-window.__pgSelectionStarted")
    print(f"passport change-event-to-visible-DOM latency: {dom_intervention_ms:.3f}ms")
    print(f"passport selection-to-intervention latency: {intervention_seconds:.6f}s")
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
    assert dom_intervention_ms <= 1_500 * PERFORMANCE_TOLERANCE, dom_intervention_ms


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
    base_url, state = fixture_site
    page = await real_browser.context.new_page()
    blocked_failures: list[str] = []
    page.on(
        "requestfailed",
        lambda request: (
            blocked_failures.append(request.failure or "")
            if any(
                host in request.url
                for host in ("tracker-one.test", "ads-two.test", "metrics-three.test")
            )
            else None
        ),
    )
    fixture_port = base_url.rsplit(":", 1)[1]
    for host in ("tracker-one.test", "ads-two.test", "metrics-three.test"):
        await page.goto(f"http://{host}:{fixture_port}/tracker-pixel")
    state.tracker_hits.clear()
    await page.goto(f"{base_url}/fixtures/tracker-heavy")
    for _attempt in range(100):
        if set(state.tracker_hits) == {"tracker-one.test", "ads-two.test", "metrics-three.test"}:
            break
        await asyncio.sleep(0.05)
    assert set(state.tracker_hits) == {"tracker-one.test", "ads-two.test", "metrics-three.test"}
    await page.evaluate("localStorage.setItem('shopping_cart','synthetic-cart-item')")
    await page.evaluate(
        """() => new Promise((resolve,reject) => {
          const request=indexedDB.open('unrelated-shopping',1);
          request.onupgradeneeded=()=>request.result.createObjectStore('cart');
          request.onerror=()=>reject(request.error);
          request.onsuccess=()=>{const tx=request.result.transaction('cart','readwrite');tx.objectStore('cart').put('synthetic-item','current');tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)};
        })"""
    )
    for host in ("tracker-one.test", "ads-two.test", "metrics-three.test"):
        cookies = await real_browser.context.cookies(f"http://{host}/")
        assert any(cookie["name"] == "synthetic_uid" for cookie in cookies)
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
        assert await real_browser.context.cookies(f"http://{host}/") == []
    state.tracker_hits.clear()
    blocked_failures.clear()
    await page.reload()
    await page.wait_for_timeout(500)
    assert state.tracker_hits == []
    assert len(blocked_failures) >= 3
    assert all("BLOCKED_BY_CLIENT" in failure for failure in blocked_failures)
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


@pytest.mark.asyncio
async def test_deep_check_composite_has_exact_three_findings_and_clean_blog_is_all_clean(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/tracker-hidden-retention")
    assert await latest_decision(real_browser, "consent_banner") is not None
    assert await latest_decision(real_browser, "tracking") is not None
    result = await send_request(
        real_browser.data_dir,
        {
            "v": 1,
            "id": "composite-deep-check",
            "type": "deep_check",
            "payload": {"origin": base_url},
        },
        timeout=12,
    )
    findings: list[dict[str, object]] = result["result"]["findings"]
    kinds = [str(finding["kind"]) for finding in findings]
    assert kinds.count("tracking") == 1
    assert kinds.count("consent") == 1
    assert kinds.count("policy") == 1, result
    assert len(findings) == 3
    assert any(item["clean"] for item in result["result"]["checked"])  # type: ignore[index,union-attr]

    clean_base = base_url.replace("127.0.0.1", "localhost")
    await page.goto(f"{clean_base}/fixtures/clean-blog")
    clean = await send_request(
        real_browser.data_dir,
        {
            "v": 1,
            "id": "clean-deep-check",
            "type": "deep_check",
            "payload": {"origin": clean_base},
        },
        timeout=12,
    )
    assert clean["result"]["findings"] == []
    assert clean["result"]["checked"]
    assert all(item["clean"] for item in clean["result"]["checked"])


@pytest.mark.asyncio
async def test_browser_disconnect_aborts_pending_upload_and_reconnects_within_five_seconds(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/image-compressor")
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    await page.locator("#file").set_input_files(passport)
    await page.locator('.pg-panel [data-pg-action="redact"]').wait_for(timeout=10_000)
    decision = await latest_decision(real_browser, "file_upload")
    assert decision is not None and decision[1] == "INTERVENE"

    await real_browser.context.close()
    deadline = time.monotonic() + 5
    status: str | None = None
    while time.monotonic() < deadline:
        with sqlite3.connect(real_browser.data_dir / "guardian.sqlite3") as connection:
            row = connection.execute(
                "SELECT status FROM events WHERE id=?", (decision[0],)
            ).fetchone()
        status = str(row[0]) if row else None
        if status == "aborted":
            break
        await asyncio.sleep(0.05)
    assert status == "aborted"
    service_ping = await send_request(
        real_browser.data_dir,
        {"v": 1, "id": "post-browser-kill", "type": "ping", "payload": {}},
    )
    assert service_ping["ok"] is True

    restarted_playwright = await async_playwright().start()
    extension = Path(__file__).resolve().parents[2] / "extension"
    environment = os.environ.copy()
    environment["PRIVACY_GUARDIAN_DATA_DIR"] = str(real_browser.data_dir)
    reconnect_started = time.perf_counter()
    restarted = await restarted_playwright.chromium.launch_persistent_context(
        str(real_browser.profile_dir),
        channel="chromium",
        headless=True,
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
            "--host-resolver-rules=MAP tracker-one.test 127.0.0.1,MAP ads-two.test 127.0.0.1,MAP metrics-three.test 127.0.0.1",
        ],
        env=environment,
    )
    try:
        worker = (
            restarted.service_workers[0]
            if restarted.service_workers
            else await restarted.wait_for_event("serviceworker", timeout=5_000)
        )
        restarted_browser = RealBrowser(
            context=restarted,
            data_dir=real_browser.data_dir,
            extension_id=worker.url.split("/")[2],
            worker=worker,
            profile_dir=real_browser.profile_dir,
            service_pid=real_browser.service_pid,
            bridge_ready_seconds=0,
        )
        ping = await native_ping(restarted_browser)
        reconnect_seconds = time.perf_counter() - reconnect_started
        assert ping.get("ok") is True, ping
        assert reconnect_seconds <= 5 * PERFORMANCE_TOLERANCE, reconnect_seconds
    finally:
        await restarted.close()
        await restarted_playwright.stop()


@pytest.mark.asyncio
async def test_abrupt_browser_kill_during_worker_analysis_persists_aborted_event(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/image-compressor")
    warm = await send_request(
        real_browser.data_dir,
        {
            "v": 1,
            "id": "warm-worker-before-kill",
            "type": "context",
            "payload": {
                "origin": base_url,
                "policy": {"text": "Synthetic service policy."},
            },
        },
    )
    assert warm["ok"] is True
    service_process = psutil.Process(real_browser.service_pid)
    baseline_cpu: dict[int, float] = {}
    for child in service_process.children(recursive=True):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            command = " ".join(child.cmdline())
            if "spawn_main" in command:
                cpu = child.cpu_times()
                baseline_cpu[child.pid] = cpu.user + cpu.system
    assert baseline_cpu
    instrumented = await real_browser.worker.evaluate(
        """() => {
          if (globalThis.__pgFinishInstrumented) return true;
          const originalNative=native;
          globalThis.__pgFinishInstrumented=true;
          globalThis.__pgFinishStarted=false;
          globalThis.__pgFinishSettled=false;
          native=async function(type,payload,timeout){
            if(type==='file_finish'){globalThis.__pgFinishStarted=true;globalThis.__pgFinishSettled=false;}
            try{return await originalNative(type,payload,timeout);}
            finally{if(type==='file_finish')globalThis.__pgFinishSettled=true;}
          };
          return true;
        }"""
    )
    assert instrumented is True
    passport = Path(__file__).resolve().parents[1] / "fixtures/passport_synthetic.pdf"
    await page.locator("#file").set_input_files(passport)

    analysis_observed = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        finish_state = await real_browser.worker.evaluate(
            "({started:globalThis.__pgFinishStarted,settled:globalThis.__pgFinishSettled})"
        )
        for child in service_process.children(recursive=True):
            with child.oneshot():
                cpu = child.cpu_times().user + child.cpu_times().system
                command = " ".join(child.cmdline())
            if (
                "spawn_main" in command
                and cpu - baseline_cpu.get(child.pid, cpu) >= 0.1
                and finish_state == {"started": True, "settled": False}
            ):
                analysis_observed = True
                break
        if analysis_observed:
            break
        await asyncio.sleep(0.01)
    assert analysis_observed, "analysis worker did not become active"

    browser_roots: list[psutil.Process] = []
    for process in psutil.Process().children(recursive=True):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            command = " ".join(process.cmdline())
            if f"--user-data-dir={real_browser.profile_dir}" in command:
                browser_roots.append(process)
    assert browser_roots, "could not identify isolated Chromium process"
    browser_root = min(browser_roots, key=lambda process: len(process.parents()))
    members = browser_root.children(recursive=True)
    for process in reversed([*members, browser_root]):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.kill()
    psutil.wait_procs([*members, browser_root], timeout=3)

    aborted: dict[str, str] | None = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sqlite3.connect(real_browser.data_dir / "guardian.sqlite3") as connection:
            row = connection.execute(
                "SELECT id,status FROM events WHERE event_type='file_upload' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        if row and str(row[1]) == "aborted":
            aborted = {"id": str(row[0]), "status": str(row[1])}
            break
        await asyncio.sleep(0.05)
    assert aborted is not None
    ping = await send_request(
        real_browser.data_dir,
        {"v": 1, "id": "service-survived-abrupt-kill", "type": "ping", "payload": {}},
    )
    assert ping["ok"] is True
