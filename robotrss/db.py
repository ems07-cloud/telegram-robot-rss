"""Хранилище на SQLite: пользователи, ленты, подписки и уже отправленные записи."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS feeds (
    url TEXT PRIMARY KEY, title TEXT DEFAULT '', etag TEXT, modified TEXT, fails INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL, url TEXT NOT NULL, alias TEXT NOT NULL, keywords TEXT DEFAULT '',
    PRIMARY KEY (user_id, alias));
CREATE TABLE IF NOT EXISTS seen (url TEXT NOT NULL, entry_id TEXT NOT NULL, PRIMARY KEY (url, entry_id));
"""


@dataclass
class Subscription:
    user_id: int
    url: str
    alias: str
    keywords: list[str]


class DB:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    # пользователи
    def set_active(self, user_id: int, active: bool) -> None:
        self.conn.execute("INSERT INTO users (id, active) VALUES (?, ?) "
                          "ON CONFLICT(id) DO UPDATE SET active = excluded.active", (user_id, int(active)))
        self.conn.commit()

    def is_active(self, user_id: int) -> bool:
        row = self.conn.execute("SELECT active FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row[0])

    # подписки
    def subscribe(self, user_id: int, url: str, alias: str, title: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO feeds (url, title) VALUES (?, ?)", (url, title))
        self.conn.execute("INSERT INTO subscriptions (user_id, url, alias) VALUES (?, ?, ?)", (user_id, url, alias))
        self.conn.commit()

    def alias_taken(self, user_id: int, alias: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM subscriptions WHERE user_id = ? AND alias = ?",
                                      (user_id, alias)).fetchone())

    def unsubscribe(self, user_id: int, alias: str) -> bool:
        cur = self.conn.execute("DELETE FROM subscriptions WHERE user_id = ? AND alias = ?", (user_id, alias))
        # лента без подписчиков больше не нужна
        self.conn.execute("DELETE FROM feeds WHERE url NOT IN (SELECT url FROM subscriptions)")
        self.conn.execute("DELETE FROM seen WHERE url NOT IN (SELECT url FROM feeds)")
        self.conn.commit()
        return cur.rowcount > 0

    def set_keywords(self, user_id: int, alias: str, keywords: list[str]) -> bool:
        cur = self.conn.execute("UPDATE subscriptions SET keywords = ? WHERE user_id = ? AND alias = ?",
                                ("\n".join(keywords), user_id, alias))
        self.conn.commit()
        return cur.rowcount > 0

    def subscriptions(self, user_id: int | None = None, url: str | None = None) -> list[Subscription]:
        q, args = "SELECT user_id, url, alias, keywords FROM subscriptions WHERE 1=1", []
        if user_id is not None:
            q, args = q + " AND user_id = ?", args + [user_id]
        if url is not None:
            q, args = q + " AND url = ?", args + [url]
        return [Subscription(u, link, a, [k for k in kw.split("\n") if k])
                for u, link, a, kw in self.conn.execute(q + " ORDER BY alias", args)]

    # ленты
    def feeds(self) -> list[tuple[str, str | None, str | None, int]]:
        return self.conn.execute("SELECT url, etag, modified, fails FROM feeds").fetchall()

    def feed_ok(self, url: str, etag: str | None, modified: str | None, title: str | None = None) -> None:
        self.conn.execute("UPDATE feeds SET etag = ?, modified = ?, fails = 0, title = COALESCE(?, title) "
                          "WHERE url = ?", (etag, modified, title, url))
        self.conn.commit()

    def feed_failed(self, url: str) -> int:
        self.conn.execute("UPDATE feeds SET fails = fails + 1 WHERE url = ?", (url,))
        self.conn.commit()
        return self.conn.execute("SELECT fails FROM feeds WHERE url = ?", (url,)).fetchone()[0]

    # уже отправленное
    def unseen(self, url: str, ids: list[str]) -> set[str]:
        seen = {r[0] for r in self.conn.execute("SELECT entry_id FROM seen WHERE url = ?", (url,))}
        return {i for i in ids if i not in seen}

    def mark_seen(self, url: str, ids: list[str]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO seen (url, entry_id) VALUES (?, ?)", [(url, i) for i in ids])
        self.conn.commit()

    def has_seen_any(self, url: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM seen WHERE url = ? LIMIT 1", (url,)).fetchone())
