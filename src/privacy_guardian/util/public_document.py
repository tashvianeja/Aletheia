from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


class _PublicText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


async def fetch_public_document(url: str, origin: str, user_agent: str) -> dict[str, object]:
    def validated(candidate: str) -> bool:
        parsed, source = urlsplit(candidate), urlsplit(origin)
        return (
            parsed.scheme in {"https", "http"}
            and not parsed.username
            and not parsed.password
            and (parsed.scheme, parsed.hostname, parsed.port)
            == (source.scheme, source.hostname, source.port)
        )

    if not validated(url) or len(url) > 4096 or any(char in user_agent for char in "\r\n"):
        raise ValueError("Public document URL is outside the current origin")
    async with httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as client:
        for _ in range(3):
            async with client.stream(
                "GET",
                url,
                headers={"User-Agent": user_agent[:400], "Accept": "text/html,text/plain"},
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    if not validated(url):
                        raise ValueError("Cross-origin document redirect")
                    continue
                response.raise_for_status()
                data = bytearray()
                partial = False
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        partial = True
                        del data[2 * 1024 * 1024 :]
                        break
                text = bytes(data).decode(response.encoding or "utf-8", errors="replace")
                if "html" in response.headers.get("content-type", ""):
                    parser = _PublicText()
                    parser.feed(text)
                    text = "\n".join(parser.parts)
                bounded = text
                while len(json.dumps({"text": bounded}, ensure_ascii=False).encode()) > 600 * 1024:
                    bounded = bounded[: int(len(bounded) * 0.8)]
                return {"text": bounded, "partial": partial or len(bounded) < len(text)}
    raise ValueError("Too many document redirects")
