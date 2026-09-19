from __future__ import annotations

import time

import pytest

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
    started = time.perf_counter()
    await page.goto(f"{base_url}/fixtures/shadow-dom-form")

    await page.locator("#shadow-host").evaluate(
        "host => { const input=host.shadowRoot.querySelector('input'); input.value='2000-01-01'; input.dispatchEvent(new Event('input',{bubbles:true})); }"
    )
    await page.locator("#shadow-host").evaluate(
        "host => new Promise((resolve,reject) => { const limit=setTimeout(()=>reject(new Error('badge timeout')),500); const poll=()=>{if(host.shadowRoot.querySelector('.pg-badge')){clearTimeout(limit);resolve(true)}else requestAnimationFrame(poll)};poll(); })"
    )

    assert time.perf_counter() - started < 2.0


@pytest.mark.asyncio
async def test_symmetric_consent_fixture_is_not_flagged_as_dark_pattern(
    real_browser: RealBrowser, fixture_site: tuple[str, object]
) -> None:
    base_url, _ = fixture_site
    page = await real_browser.context.new_page()
    await page.goto(f"{base_url}/fixtures/symmetric-choice-cmp")
    await page.wait_for_timeout(1_000)

    assert await page.locator(".cmp").count() == 1
    assert await page.locator('.pg-panel [data-pg-action="reject_optional"]').count() == 0
    if await page.locator(".pg-panel").count():
        assert "harder" not in (await page.locator(".pg-panel").inner_text()).lower()
