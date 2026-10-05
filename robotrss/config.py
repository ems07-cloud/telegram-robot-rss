import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "robotrss.sqlite")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))      # секунд между обходами лент
MAX_PER_CHECK = int(os.getenv("MAX_PER_CHECK", "5"))           # не больше N новых записей на ленту за обход
FAILS_BEFORE_NOTICE = int(os.getenv("FAILS_BEFORE_NOTICE", "5"))  # после скольких сбоев подряд предупредить
