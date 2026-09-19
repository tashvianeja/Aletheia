from __future__ import annotations

import aiohttp
import pytest

from tests.e2e.site_content import PAGES


@pytest.mark.asyncio
async def test_all_required_fixture_sites_are_served(fixture_site: tuple[str, object]) -> None:
    base_url, _ = fixture_site
    required = {
        "image-compressor",
        "government-visa-portal",
        "free-pdf-download",
        "bank-kyc",
        "social-photo",
        "tracker-heavy",
        "clean-blog",
        "hidden-reject-cmp",
        "symmetric-choice-cmp",
        "signup-with-terms",
        "spa-dynamic-form",
        "shadow-dom-form",
    }
    assert required <= PAGES.keys()
    async with aiohttp.ClientSession() as session:
        for name in sorted(required):
            async with session.get(f"{base_url}/fixtures/{name}") as response:
                assert response.status == 200
                assert "text/html" in response.headers["Content-Type"]
                assert "<title>" in await response.text()


@pytest.mark.asyncio
async def test_submission_endpoint_records_only_presence_and_filename(
    fixture_site: tuple[str, object],
) -> None:
    base_url, state = fixture_site
    form = aiohttp.FormData()
    form.add_field("email", "testperson@example.test")
    form.add_field("document", b"synthetic", filename="synthetic.txt", content_type="text/plain")
    async with (
        aiohttp.ClientSession() as session,
        session.post(f"{base_url}/received", data=form) as response,
    ):
        assert response.status == 200
    assert state.submissions == [{"email": "present", "document": "synthetic.txt"}]


def test_cmp_matrix_includes_five_known_and_three_heuristic_layouts() -> None:
    known = {name for name in PAGES if name.startswith("cmp-")}
    heuristic = {name for name in PAGES if name.startswith("heuristic-banner-")}
    assert len(known) >= 5
    assert len(heuristic) >= 3


def test_clean_blog_has_no_tracking_primitives() -> None:
    html = PAGES["clean-blog"]
    forbidden = ("document.cookie", "localStorage", "toDataURL", "tracker-one", "pixel.gif")
    assert all(marker not in html for marker in forbidden)
