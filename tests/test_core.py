import asyncio

import pytest

from robotrss import config
from robotrss.core import check_once, format_entry, matches
from robotrss.db import DB
from robotrss.feeds import Entry
from tests.helpers import FakeSite, rss

URL = "https://news.ru/rss"


@pytest.fixture
def world():
    db, site = DB(), FakeSite()
    site.pages[URL] = rss([("1", "Python 3.14 вышел"), ("0", "Старая новость")])
    db.subscribe(10, URL, "news")
    db.subscribe(20, URL, "py")
    db.set_active(10, True)
    db.set_active(20, True)
    db.set_keywords(20, "py", ["python"])
    return db, site


def run(db, site, blocked=()):
    sent = []

    async def send(uid, text):
        if uid in blocked:
            return False
        sent.append((uid, text))
        return True

    async def go():
        async with site.client() as c:
            return await check_once(db, c, send)

    return asyncio.run(go()), sent


def test_first_check_sends_no_archive_then_only_new(world):
    db, site = world
    _, sent = run(db, site)
    assert sent == []                                       # при подписке архив не шлём
    site.pages[URL] = rss([("3", "Вышел aiogram 3.20"), ("2", "Python в Excel"), ("1", "Python 3.14 вышел")])
    stats, sent = run(db, site)
    assert stats.sent == 3
    assert [(u, t.split("\n")[1]) for u, t in sent] == [
        (10, '<a href="https://example.ru/2">Python в Excel</a>'),
        (10, '<a href="https://example.ru/3">Вышел aiogram 3.20</a>'),
        (20, '<a href="https://example.ru/2">Python в Excel</a>'),   # у второго фильтр «python»
    ]


def test_feed_downloaded_once_for_all_subscribers(world):
    db, site = world
    run(db, site)
    assert site.requests.count(URL) == 1


def test_unchanged_feed_uses_304(world):
    db, site = world
    run(db, site)
    stats, sent = run(db, site)
    assert stats.not_modified == 1 and sent == []


def test_cap_per_check(world, monkeypatch):
    db, site = world
    run(db, site)
    monkeypatch.setattr(config, "MAX_PER_CHECK", 2)
    site.pages[URL] = rss([(str(i), f"Новость {i}") for i in range(10, 2, -1)])
    _, sent = run(db, site)
    assert [t.split("\n")[1] for u, t in sent if u == 10] == [
        '<a href="https://example.ru/9">Новость 9</a>', '<a href="https://example.ru/10">Новость 10</a>']


def test_broken_feed_warns_once(world):
    db, site = world
    run(db, site)
    site.broken.add(URL)
    notices = []
    for _ in range(config.FAILS_BEFORE_NOTICE + 3):
        _, sent = run(db, site)
        notices += sent
    assert len(notices) == 2                                 # по одному на подписчика, а не каждый обход
    assert "не отвечает уже 5 раз подряд" in notices[0][1]


def test_blocked_user_is_deactivated(world):
    db, site = world
    run(db, site)
    site.pages[URL] = rss([("2", "Python новость"), ("1", "Python 3.14 вышел")])
    run(db, site, blocked={10})
    assert not db.is_active(10) and db.is_active(20)


def test_title_is_escaped():
    text = format_entry("news", Entry("1", "x < y & <b>тег</b>", "https://e.ru/?a=1&b=2", None, ""))
    assert "x &lt; y &amp; &lt;b&gt;тег&lt;/b&gt;" in text
    assert 'href="https://e.ru/?a=1&amp;b=2"' in text


def test_keyword_filter_is_case_insensitive():
    e = Entry("1", "Вышел PYTHON 3.14", "", None, "")
    assert matches(e, ["python"]) and matches(e, []) and not matches(e, ["golang"])


@pytest.mark.parametrize("title, hit", [
    ("Пишем Telegram-бота на aiogram", True),
    ("Сколько стоит разработка ботов", True),
    ("Как работает шифровальная машина", False),     # «бот» внутри «работает» — не считается
    ("Годы работы с оптимизацией", False),
], ids=["bota", "botov", "rabotaet", "raboty"])
def test_keyword_matches_from_word_start(title, hit):
    assert matches(Entry("1", title, "", None, ""), ["бот"]) is hit
