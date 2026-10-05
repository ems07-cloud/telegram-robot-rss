"""Команды бота через настоящие обработчики; Telegram и интернет подменены."""
import asyncio
from types import SimpleNamespace

from aiogram.filters import CommandObject

from robotrss.bot import Remove, build_router
from robotrss.db import DB
from tests.helpers import FakeSite, rss

URL = "https://news.ru/rss"


class Chat:
    def __init__(self, uid=10):
        self.uid, self.out = uid, []

    def msg(self):
        chat = self

        class M:
            from_user = SimpleNamespace(id=chat.uid)

            async def answer(self, text, reply_markup=None, **kw):
                chat.out.append((text, reply_markup))
        return M()


def handlers(db, site):
    router = build_router(db, site.client())
    return {h.callback.__name__: h.callback for h in router.message.handlers + router.callback_query.handlers}


def cmd(args):
    return CommandObject(prefix="/", command="x", args=args)


def setup():
    db, site, chat = DB(), FakeSite(), Chat()
    site.pages[URL] = rss([("2", "Вторая про python"), ("1", "Первая")], title="Новости")
    return db, site, chat, handlers(db, site)


def test_add_get_filter_list_remove():
    db, site, chat, h = setup()
    run = asyncio.run
    run(h["add"](chat.msg(), cmd(f"{URL} news")))
    assert "Подписка «news» добавлена" in chat.out[-1][0] and "записей в ленте: 2" in chat.out[-1][0]
    assert db.unseen(URL, ["1", "2"]) == set()               # архив помечен как прочитанный

    run(h["get"](chat.msg(), cmd("news 5")))
    assert [t.split("\n")[1] for t, _ in chat.out[-2:]] == [
        '<a href="https://example.ru/1">Первая</a>', '<a href="https://example.ru/2">Вторая про python</a>']

    run(h["filter_"](chat.msg(), cmd("news python")))
    run(h["get"](chat.msg(), cmd("news")))
    assert "Вторая про python" in chat.out[-1][0]

    run(h["list_"](chat.msg()))
    text, markup = chat.out[-1]
    assert "news" in text and "фильтр: python" in text
    assert markup.inline_keyboard[0][0].callback_data == Remove(alias="news").pack()

    run(h["remove"](chat.msg(), cmd("news")))
    assert chat.out[-1][0] == "Подписка «news» удалена."
    assert db.subscriptions(user_id=10) == [] and db.feeds() == []


def test_add_validation():
    db, site, chat, h = setup()
    run = asyncio.run
    run(h["add"](chat.msg(), cmd(URL)))
    assert chat.out[-1][0].startswith("Так:")
    run(h["add"](chat.msg(), cmd(f"{URL} плохое!имя")))
    assert "одно слово" in chat.out[-1][0]
    run(h["add"](chat.msg(), cmd("https://news.ru/nope news")))
    assert "Сайт ответил 404" in chat.out[-1][0]
    run(h["add"](chat.msg(), cmd(f"{URL} news")))
    run(h["add"](chat.msg(), cmd(f"{URL} news")))
    assert "уже есть" in chat.out[-1][0]


def test_stop_and_start():
    db, site, chat, h = setup()
    asyncio.run(h["stop"](chat.msg()))
    assert not db.is_active(10)
    asyncio.run(h["start"](chat.msg()))
    assert db.is_active(10)
