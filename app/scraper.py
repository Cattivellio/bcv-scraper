from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .config import (
    BCV_URL,
    CURRENCIES,
    HTTP_SSL_BUNDLE,
    HTTP_TIMEOUT,
    HTTP_USER_AGENT,
    HTTP_VERIFY_SSL,
)
from .database import insert_if_changed, now_iso
from .models import ScrapeSummary


logger = logging.getLogger(__name__)


_BCV_DIV_ID_TO_CURRENCY = {
    "dolar": "USD",
    "euro": "EUR",
    "yuan": "CNY",
    "lira": "TRY",
    "rublo": "RUB",
}

_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class ParsedRate:
    currency: str
    value: float
    source_date: str  # YYYY-MM-DD


class ScraperError(Exception):
    pass


def _parse_value(raw: str) -> float:
    if not raw:
        raise ScraperError("empty value")
    cleaned = raw.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    return float(cleaned)


def _parse_source_date(soup: BeautifulSoup) -> Optional[str]:
    el = soup.find("span", class_="date-display-single")
    if el and el.get("content"):
        m = _ISO_DATE_RE.search(el["content"])
        if m:
            return m.group(1)
    txt = soup.get_text(" ", strip=True)
    m = _ISO_DATE_RE.search(txt)
    return m.group(1) if m else None


def parse_rates(html: str) -> tuple[list[ParsedRate], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    source_date = _parse_source_date(soup)
    parsed: list[ParsedRate] = []
    seen: set[str] = set()
    for div_id, currency in _BCV_DIV_ID_TO_CURRENCY.items():
        if currency in seen:
            continue
        container = soup.find("div", id=div_id)
        if not container:
            logger.warning("BCV: container #%s not found", div_id)
            continue
        strong = container.find("strong", class_="strong-tb")
        if not strong:
            logger.warning("BCV: <strong.strong-tb> not found in #%s", div_id)
            continue
        try:
            value = _parse_value(strong.get_text())
        except (ValueError, ScraperError) as exc:
            logger.warning("BCV: cannot parse value in #%s: %s", div_id, exc)
            continue
        parsed.append(ParsedRate(currency=currency, value=value, source_date=source_date or ""))
        seen.add(currency)
    return parsed, source_date


async def fetch_html(client: httpx.AsyncClient) -> str:
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    resp = await client.get(BCV_URL, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _ssl_verify() -> bool | str:
    if not HTTP_VERIFY_SSL:
        return False
    if HTTP_SSL_BUNDLE:
        return HTTP_SSL_BUNDLE
    try:
        import certifi
        return certifi.where()
    except Exception:  # noqa: BLE001
        return True


async def scrape_once() -> ScrapeSummary:
    """Fetch BCV once, parse, and persist only the rows that actually changed."""
    from .database import (
        get_latest,
        get_previous,
        get_sparkline,
    )
    from .config import CURRENCY_FLAGS, CURRENCY_LABELS

    scraped_at = now_iso()
    errors: list[str] = []

    verify = _ssl_verify()
    async with httpx.AsyncClient(http2=False, verify=verify) as client:
        try:
            html = await fetch_html(client)
        except Exception as exc:  # noqa: BLE001
            logger.exception("BCV fetch failed")
            return ScrapeSummary(
                scraped_at=scraped_at,
                source_date=None,
                source_url=BCV_URL,
                inserted=0,
                skipped=0,
                errors=[f"fetch failed: {exc}"],
                rates=[],
            )

    parsed, source_date = parse_rates(html)
    if not parsed:
        errors.append("no rates parsed from page")
        return ScrapeSummary(
            scraped_at=scraped_at,
            source_date=source_date,
            source_url=BCV_URL,
            inserted=0,
            skipped=0,
            errors=errors,
            rates=[],
        )

    inserted = 0
    skipped = 0
    rates_out = []
    for r in parsed:
        if not r.source_date:
            errors.append(f"missing source_date for {r.currency}")
            continue
        try:
            changed = insert_if_changed(
                currency=r.currency,
                value=r.value,
                source_date=r.source_date,
                scraped_at=scraped_at,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"db insert failed for {r.currency}: {exc}")
            continue
        if changed:
            inserted += 1
        else:
            skipped += 1

        latest = get_latest(r.currency) or {}
        previous = get_previous(r.currency)
        history = get_sparkline(r.currency, limit=30)

        from .models import RateLatest
        prev_value = previous["value"] if previous else None
        delta = (r.value - prev_value) if prev_value is not None else None
        delta_pct = ((delta / prev_value) * 100.0) if (delta is not None and prev_value) else None

        rates_out.append(
            RateLatest(
                currency=r.currency,
                label=CURRENCY_LABELS.get(r.currency, r.currency),
                flag=CURRENCY_FLAGS.get(r.currency, ""),
                value=r.value,
                source_date=r.source_date,
                scraped_at=latest.get("scraped_at", scraped_at),
                previous_value=prev_value,
                delta=delta,
                delta_pct=delta_pct,
                history=history,
            )
        )

    return ScrapeSummary(
        scraped_at=scraped_at,
        source_date=source_date,
        source_url=BCV_URL,
        inserted=inserted,
        skipped=skipped,
        errors=errors,
        rates=rates_out,
    )


def run_scrape_sync() -> ScrapeSummary:
    return asyncio.run(scrape_once())


__all__ = [
    "ParsedRate",
    "ScraperError",
    "parse_rates",
    "scrape_once",
    "run_scrape_sync",
    "CURRENCIES",
]
