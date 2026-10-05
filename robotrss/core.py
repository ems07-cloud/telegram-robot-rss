"""Обход лент: каждую скачиваем один раз на всех подписчиков и шлём только новое."""
from __future__ import annotations

import html
import re
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from . import config
from .db import DB, Subscription
from .feeds import Entry, FeedError, fetch

log = logging.getLogger(__name__)
Send = Callable[[int, str], Awaitable[bool]]   # отправить текст; False — пользователь заблокировал бота


def matches(entry: Entry, keywords: list[str]) -> bool:
    """Пустой фильтр — всё подходит; иначе хотя бы одно слово должно встретиться в заголовке
    или описании. Ищем с начала слова: «бот» найдёт «бота» и «ботов», но не «работает»."""
    if not keywords:
        return True
    text = f"{entry.title} {entry.summary}".casefold()
    return any(re.search(r"(?<!\w)" + re.escape(k.casefold()), text) for k in keywords)


def format_entry(alias: str, entry: Entry) -> str:
    title = html.escape(entry.title)
    head = f'<a href="{html.escape(entry.link, quote=True)}">{title}</a>' if entry.link else f"<b>{title}</b>"
    lines = [f"📰 <b>{html.escape(alias)}</b>", head]
    if entry.summary:
        lines += ["", html.escape(entry.summary)]
    if entry.published:
        lines += ["", f"<i>{entry.published:%d.%m.%Y %H:%M} UTC</i>"]
    return "\n".join(lines)


@dataclass
class CheckStats:
    feeds: int = 0
    not_modified: int = 0
    failed: int = 0
    sent: int = 0


async def check_once(db: DB, client: httpx.AsyncClient, send: Send) -> CheckStats:
    stats = CheckStats()
    for url, etag, modified, _ in db.feeds():
        stats.feeds += 1
        subs = [s for s in db.subscriptions(url=url) if db.is_active(s.user_id)]
        try:
            result = await fetch(client, url, etag, modified)
        except FeedError as exc:
            stats.failed += 1
            fails = db.feed_failed(url)
            log.warning("%s: %s (сбоев подряд: %s)", url, exc, fails)
            if fails == config.FAILS_BEFORE_NOTICE:      # предупреждаем один раз, а не каждый обход
                for s in subs:
                    await send(s.user_id, f"⚠️ Лента «{html.escape(s.alias)}» не отвечает уже "
                                          f"{fails} раз подряд: {html.escape(str(exc))}.\n"
                                          f"Если она переехала — /remove {html.escape(s.alias)}")
            continue
        if result.not_modified:
            stats.not_modified += 1
            db.feed_ok(url, result.etag, result.modified)
            continue

        fresh_ids = db.unseen(url, [e.id for e in result.entries])
        first_time = not db.has_seen_any(url)
        new = [e for e in result.entries if e.id in fresh_ids]
        db.mark_seen(url, [e.id for e in result.entries])
        db.feed_ok(url, result.etag, result.modified, result.title)
        if first_time:
            continue               # при добавлении ленты не засыпаем человека её архивом

        new = list(reversed(new))[-config.MAX_PER_CHECK:]    # по порядку, старые раньше
        for s in subs:
            for entry in (e for e in new if matches(e, s.keywords)):
                if await send(s.user_id, format_entry(s.alias, entry)):
                    stats.sent += 1
                else:
                    db.set_active(s.user_id, False)
                    break
    return stats


async def latest(client: httpx.AsyncClient, sub: Subscription, count: int) -> list[str]:
    """Последние записи ленты по запросу пользователя (/get), с учётом его фильтра."""
    result = await fetch(client, sub.url)
    picked = [e for e in result.entries if matches(e, sub.keywords)][:count]
    return [format_entry(sub.alias, e) for e in reversed(picked)]
