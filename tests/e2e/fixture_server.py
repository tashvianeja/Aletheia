from __future__ import annotations

from dataclasses import dataclass, field

from aiohttp import web

from tests.e2e.site_content import PAGES, PRIVACY_POLICY, TERMS_DOCUMENT


@dataclass
class FixtureState:
    submissions: list[dict[str, str]] = field(default_factory=list)
    uploads: list[tuple[str, str, bytes]] = field(default_factory=list)


def create_fixture_app(state: FixtureState | None = None) -> web.Application:
    fixture_state = state or FixtureState()
    app = web.Application(client_max_size=64 * 1024**2)
    app[web.AppKey("fixture_state", FixtureState)] = fixture_state

    async def fixture(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name not in PAGES:
            raise web.HTTPNotFound(text=f"unknown fixture {name}")
        return web.Response(text=PAGES[name], content_type="text/html")

    async def received(request: web.Request) -> web.Response:
        data = await request.post()
        safe_record: dict[str, str] = {}
        for key, value in data.items():
            if hasattr(value, "filename"):
                safe_record[key] = str(value.filename)
                content = value.file.read(16 * 1024**2)
                fixture_state.uploads.append(
                    (str(value.filename), str(value.content_type), content)
                )
            else:
                safe_record[key] = "present"
        fixture_state.submissions.append(safe_record)
        return web.Response(text="received")

    async def state_response(_: web.Request) -> web.Response:
        return web.json_response({"submissions": fixture_state.submissions})

    async def privacy(_: web.Request) -> web.Response:
        return web.Response(text=PRIVACY_POLICY, content_type="text/html")

    async def terms(_: web.Request) -> web.Response:
        return web.Response(text=TERMS_DOCUMENT, content_type="text/html")

    async def favicon(_: web.Request) -> web.Response:
        return web.Response(status=204)

    app.router.add_get("/fixtures/{name}", fixture)
    app.router.add_get("/privacy", privacy)
    app.router.add_get("/terms", terms)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_post("/received", received)
    app.router.add_get("/_state", state_response)
    return app
