from pathlib import Path

import httpx

FIX = Path(__file__).parent / "fixtures"


def rss(items: list[tuple[str, str]], title: str = "Тестовая лента") -> str:
    """RSS 2.0 из пар (guid, заголовок); первая — самая новая, как в настоящих лентах."""
    body = "".join(f"<item><guid>{g}</guid><title>{t}</title><link>https://example.ru/{g}</link>"
                   f"<description>Текст {t}</description></item>" for g, t in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{body}</channel></rss>'


class FakeSite:
    """Подменённый интернет: адрес → содержимое; считает запросы, умеет ETag и сбои."""

    def __init__(self):
        self.pages: dict[str, str] = {}
        self.broken: set[str] = set()
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.broken:
            return httpx.Response(503)
        if url not in self.pages:
            return httpx.Response(404)
        body = self.pages[url]
        etag = f'"{hash(body) & 0xffff}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, text=body, headers={"ETag": etag})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))
