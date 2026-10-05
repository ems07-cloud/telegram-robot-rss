import asyncio

import httpx
import pytest

from robotrss.feeds import FeedError, fetch, normalize_url, parse
from tests.helpers import FIX, FakeSite, rss


def test_real_rss_from_habr():
    title, entries = parse((FIX / "habr_python.xml").read_bytes())
    assert "Хабр" in title
    assert len(entries) >= 10
    e = entries[0]
    assert e.title and e.link.startswith("https://habr.com/")
    assert e.published is not None
    assert "<" not in e.summary and len(e.summary) <= 300       # HTML вырезан, текст обрезан


def test_real_atom_from_github():
    title, entries = parse((FIX / "aiogram_releases.atom").read_bytes())
    assert "aiogram" in title.lower()
    assert entries[0].link.startswith("https://github.com/aiogram/aiogram/releases/")


def test_feed_without_dates_is_accepted():
    """Оригинальный бот отвергал такие ленты целиком — теперь даты не обязательны."""
    _, entries = parse(rss([("a", "Первая"), ("b", "Вторая")]))
    assert [e.id for e in entries] == ["a", "b"]
    assert entries[0].published is None


def test_not_a_feed():
    with pytest.raises(FeedError):
        parse("<html><body>обычная страница</body></html>")


@pytest.mark.parametrize("raw, url", [
    ("habr.com/ru/rss/articles/", "https://habr.com/ru/rss/articles/"),
    ("https://Example.com/Feed.XML", "https://Example.com/Feed.XML"),   # регистр пути сохраняется
    ("  http://site.ru/rss ", "http://site.ru/rss"),
], ids=["adds-scheme", "keeps-case", "strips"])
def test_normalize_url(raw, url):
    assert normalize_url(raw) == url


def test_normalize_rejects_garbage():
    with pytest.raises(FeedError):
        normalize_url("привет")


def test_conditional_request_and_errors():
    site = FakeSite()
    site.pages["https://s.ru/rss"] = rss([("a", "A")])

    async def scenario():
        async with site.client() as c:
            first = await fetch(c, "https://s.ru/rss")
            again = await fetch(c, "https://s.ru/rss", etag=first.etag)
            with pytest.raises(FeedError, match="404"):
                await fetch(c, "https://s.ru/nope")
        return first, again

    first, again = asyncio.run(scenario())
    assert first.etag and len(first.entries) == 1
    assert again.not_modified and again.entries == []


def test_network_error_becomes_feed_error():
    def boom(request):
        raise httpx.ConnectError("нет сети", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
            await fetch(c, "https://s.ru/rss")

    with pytest.raises(FeedError, match="ConnectError"):
        asyncio.run(scenario())
