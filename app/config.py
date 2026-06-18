from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

load_dotenv(BASE_DIR / ".env")

BCV_URL = os.environ.get("BCV_URL", "https://www.bcv.org.ve/")
SCRAPE_API_KEY = os.environ.get("SCRAPE_API_KEY", "").strip()

_SCRAPE_ON_STARTUP_RAW = os.environ.get("BCV_SCRAPE_ON_STARTUP", "true").strip().lower()
SCRAPE_ON_STARTUP = _SCRAPE_ON_STARTUP_RAW not in ("0", "false", "no", "off")

TZ = os.environ.get("TZ", "America/Caracas")
SCRAPE_HOURS = os.environ.get("SCRAPE_HOURS", "0,4,8,12,16,20")
SCRAPE_HOUR_LIST = [int(h) for h in SCRAPE_HOURS.split(",") if h.strip().isdigit()]

HTTP_TIMEOUT = float(os.environ.get("BCV_HTTP_TIMEOUT", "15"))
HTTP_USER_AGENT = os.environ.get(
    "BCV_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

_VERIFY_RAW = os.environ.get("BCV_VERIFY_SSL", "true").strip().lower()
HTTP_VERIFY_SSL = _VERIFY_RAW not in ("0", "false", "no", "off")
HTTP_SSL_BUNDLE = os.environ.get("BCV_SSL_BUNDLE", "").strip() or None

HOST = os.environ.get("BCV_HOST", "127.0.0.1")
PORT = int(os.environ.get("BCV_PORT", "8000"))

CURRENCIES = ["USD", "EUR", "CNY", "TRY", "RUB"]
CURRENCY_LABELS = {
    "USD": "Dólar estadounidense",
    "EUR": "Euro",
    "CNY": "Yuan chino",
    "TRY": "Lira turca",
    "RUB": "Rublo ruso",
}
CURRENCY_FLAGS = {
    "USD": "$",
    "EUR": "€",
    "CNY": "¥",
    "TRY": "₺",
    "RUB": "₽",
}

# PostgreSQL connection
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "bcv_scraper")
DB_USER = os.environ.get("DB_USER", "admin_root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
