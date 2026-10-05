"""Запуск: BOT_TOKEN=... python -m robotrss"""
import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

from . import config
from .bot import build_router
from .core import check_once
from .db import DB

log = logging.getLogger("robotrss")


async def poller(db: DB, client: httpx.AsyncClient, bot: Bot) -> None:
    async def send(user_id: int, text: str) -> bool:
        try:
            await bot.send_message(user_id, text, disable_web_page_preview=True)
            return True
        except TelegramForbiddenError:       # заблокировал бота — перестаём слать
            return False

    while True:
        try:
            st = await check_once(db, client, send)
            log.info("обход: лент %s, без изменений %s, сбоев %s, отправлено %s",
                     st.feeds, st.not_modified, st.failed, st.sent)
        except Exception:                     # один неудачный обход не должен остановить бота
            log.exception("обход упал")
        await asyncio.sleep(config.CHECK_INTERVAL)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")
    db = DB(config.DB_PATH)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "RobotRSS/2.0 (+https://github.com/ems07-cloud/telegram-robot-rss)"}) as client:
        bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        dp.include_router(build_router(db, client))
        task = asyncio.create_task(poller(db, client, bot))
        try:
            await dp.start_polling(bot)
        finally:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
