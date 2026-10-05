"""Загрузка и разбор лент. RSS 2.0, Atom и RSS без дат — всё через feedparser."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import struct_time
from urllib.parse import urlsplit

import feedparser
import httpx


class FeedError(Exception):
    pass


@dataclass
class Entry:
    id: str
    title: str
    link: str
    published: datetime | None
    summary: str


@dataclass
class FetchResult:
    not_modified: bool = False
    title: str = ""
    entries: list[Entry] = field(default_factory=list)
    etag: str | None = None
    modified: str | None = None


def normalize_url(raw: str) -> str:
    """Добавляет схему, если её нет. Регистр не трогаем: путь бывает чувствителен к нему."""
    url = raw.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    if not parts.netloc or "." not in parts.netloc:
        raise FeedError("Это не похоже на адрес ленты")
    return url


def _plain(text: str, limit: int = 300) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _date(value: struct_time | None) -> datetime | None:
    return datetime(*value[:6], tzinfo=timezone.utc) if value else None


def parse(content: bytes | str) -> tuple[str, list[Entry]]:
    feed = feedparser.parse(content)
    if not feed.entries and (feed.bozo or not feed.version):    # version пуст у обычной HTML-страницы
        raise FeedError("По адресу нет RSS или Atom")
    entries = []
    for e in feed.entries:
        link = e.get("link", "")
        title = " ".join((e.get("title") or link or "Без заголовка").split())
        # id из ленты, иначе ссылка, иначе хеш заголовка — даты для этого не нужны
        ident = e.get("id") or link or hashlib.sha1(title.encode()).hexdigest()
        entries.append(Entry(id=ident, title=title, link=link,
                             published=_date(e.get("published_parsed") or e.get("updated_parsed")),
                             summary=_plain(e.get("summary", ""))))
    return " ".join(feed.feed.get("title", "").split()), entries


async def fetch(client: httpx.AsyncClient, url: str, etag: str | None = None,
                modified: str | None = None) -> FetchResult:
    """Условный запрос: если лента не менялась, сервер отвечает 304 и мы ничего не качаем."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    try:
        resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise FeedError(f"Не удалось загрузить: {exc.__class__.__name__}") from exc
    if resp.status_code == 304:
        return FetchResult(not_modified=True, etag=etag, modified=modified)
    if resp.status_code >= 400:
        raise FeedError(f"Сайт ответил {resp.status_code}")
    title, entries = parse(resp.content)
    return FetchResult(title=title, entries=entries, etag=resp.headers.get("etag"),
                       modified=resp.headers.get("last-modified"))
