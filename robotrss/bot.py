"""Команды бота (aiogram 3). Те же, что в оригинальном RobotRSS, плюс фильтр по словам."""
from __future__ import annotations

import html
import re

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import core
from .db import DB
from .feeds import FeedError, fetch, normalize_url

HELP = (
    "<b>RobotRSS</b> присылает новые записи из RSS и Atom лент.\n\n"
    "/add &lt;адрес&gt; &lt;название&gt; — подписаться\n"
    "/filter &lt;название&gt; &lt;слова через пробел&gt; — присылать только с этими словами "
    "(<code>/filter название -</code> — снять фильтр)\n"
    "/get &lt;название&gt; [1–10] — последние записи прямо сейчас\n"
    "/list — мои подписки\n"
    "/remove &lt;название&gt; — отписаться\n"
    "/stop и /start — выключить и включить рассылку"
)
ALIAS = re.compile(r"^[\w\-]{1,32}$")


class Remove(CallbackData, prefix="rm"):
    alias: str


def build_router(db: DB, client: httpx.AsyncClient) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        db.set_active(message.from_user.id, True)
        await message.answer("Рассылка включена ✅\n\n" + HELP)

    @router.message(Command("stop"))
    async def stop(message: Message) -> None:
        db.set_active(message.from_user.id, False)
        await message.answer("Рассылка на паузе. Подписки сохранены — /start, чтобы продолжить.")

    @router.message(Command("help", "about"))
    async def help_(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("add"))
    async def add(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) != 2:
            await message.answer("Так: <code>/add https://habr.com/ru/rss/articles/ habr</code>")
            return
        raw, alias = parts
        uid = message.from_user.id
        if not ALIAS.match(alias):
            await message.answer("Название — одно слово до 32 символов: буквы, цифры, «-» и «_».")
            return
        if db.alias_taken(uid, alias):
            await message.answer(f"Подписка «{html.escape(alias)}» уже есть.")
            return
        try:
            url = normalize_url(raw)
            result = await fetch(client, url)
        except FeedError as exc:
            await message.answer(f"Не получилось: {html.escape(str(exc))}.")
            return
        if not result.entries:
            await message.answer("Лента пустая — проверьте адрес.")
            return
        db.subscribe(uid, url, alias, result.title)
        db.mark_seen(url, [e.id for e in result.entries])      # архив не шлём, только новое
        db.set_active(uid, True)
        await message.answer(f"Подписка «{html.escape(alias)}» добавлена ✅\n"
                             f"{html.escape(result.title or url)} — записей в ленте: {len(result.entries)}.\n"
                             f"Новые пришлю, как появятся. Последние сейчас: /get {html.escape(alias)} 3")

    @router.message(Command("filter"))
    async def filter_(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if len(parts) < 2:
            await message.answer("Так: <code>/filter habr python aiogram</code> или <code>/filter habr -</code>")
            return
        alias, words = parts[0], ([] if parts[1:] == ["-"] else parts[1:])
        if not db.set_keywords(message.from_user.id, alias, words):
            await message.answer(f"Подписки «{html.escape(alias)}» нет — см. /list")
            return
        await message.answer(f"Фильтр для «{html.escape(alias)}»: " +
                             (", ".join(html.escape(w) for w in words) if words else "снят, приходит всё"))

    @router.message(Command("get"))
    async def get(message: Message, command: CommandObject) -> None:
        parts = (command.args or "").split()
        if not parts:
            await message.answer("Так: <code>/get habr 3</code>")
            return
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
        sub = next((s for s in db.subscriptions(user_id=message.from_user.id) if s.alias == parts[0]), None)
        if sub is None:
            await message.answer(f"Подписки «{html.escape(parts[0])}» нет — см. /list")
            return
        try:
            posts = await core.latest(client, sub, max(1, min(count, 10)))
        except FeedError as exc:
            await message.answer(f"Лента не отвечает: {html.escape(str(exc))}")
            return
        for text in posts or ["Подходящих записей нет."]:
            await message.answer(text, disable_web_page_preview=True)

    @router.message(Command("list"))
    async def list_(message: Message) -> None:
        subs = db.subscriptions(user_id=message.from_user.id)
        if not subs:
            await message.answer("Подписок пока нет. Добавьте: <code>/add &lt;адрес&gt; &lt;название&gt;</code>")
            return
        kb = InlineKeyboardBuilder()
        lines = ["<b>Мои подписки</b>", ""]
        for s in subs:
            flt = f"\n   фильтр: {', '.join(html.escape(k) for k in s.keywords)}" if s.keywords else ""
            lines.append(f"• <b>{html.escape(s.alias)}</b> — {html.escape(s.url)}{flt}")
            kb.button(text=f"✖️ {s.alias}", callback_data=Remove(alias=s.alias))
        kb.adjust(2)
        state = "" if db.is_active(message.from_user.id) else "\n\n⏸ Рассылка на паузе — /start"
        await message.answer("\n".join(lines) + state, reply_markup=kb.as_markup(), disable_web_page_preview=True)

    async def do_remove(user_id: int, alias: str) -> str:
        if db.unsubscribe(user_id, alias):
            return f"Подписка «{html.escape(alias)}» удалена."
        return f"Подписки «{html.escape(alias)}» нет — см. /list"

    @router.message(Command("remove"))
    async def remove(message: Message, command: CommandObject) -> None:
        alias = (command.args or "").strip()
        await message.answer(await do_remove(message.from_user.id, alias) if alias else "Так: <code>/remove habr</code>")

    @router.callback_query(Remove.filter())
    async def remove_button(cb: CallbackQuery, callback_data: Remove) -> None:
        await cb.message.answer(await do_remove(cb.from_user.id, callback_data.alias))
        await cb.answer()

    return router
