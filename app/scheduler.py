from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .config import SCRAPE_HOUR_LIST, SCRAPE_ON_STARTUP, TZ
from .scraper import scrape_once


logger = logging.getLogger(__name__)


class SchedulerState:
    running: bool = False
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    last_summary: Optional[dict] = None
    instance: Optional[AsyncIOScheduler] = None


state = SchedulerState()


async def _job() -> None:
    from .database import now_iso

    state.last_run = now_iso()
    try:
        summary = await scrape_once()
        state.last_summary = summary.model_dump()
        if summary.errors:
            logger.warning(
                "scraper job finished with %d error(s): %s",
                len(summary.errors), summary.errors,
            )
        logger.info(
            "scraper job done: source_date=%s inserted=%d skipped=%d errors=%d",
            summary.source_date, summary.inserted, summary.skipped, len(summary.errors),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("scraper job crashed: %s", exc)


def start() -> AsyncIOScheduler:
    if state.instance is not None:
        return state.instance

    hours_csv = ",".join(str(h) for h in SCRAPE_HOUR_LIST) or "0,4,8,12,16,20"
    sched = AsyncIOScheduler(timezone=TZ)

    sched.add_job(
        _job,
        CronTrigger(hour=hours_csv, minute=0, timezone=TZ),
        id="bcv-scrape-cron",
        name=f"BCV scrape at hours {hours_csv}",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    if SCRAPE_ON_STARTUP:
        sched.add_job(
            _job,
            DateTrigger(run_date=datetime.now(tz=timezone.utc), timezone=TZ),
            id="bcv-scrape-startup",
            name="BCV scrape on startup",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=None,
        )
        logger.info("startup scrape scheduled to run immediately")

    sched.start()
    state.instance = sched
    state.running = True
    state.next_run = _format_next(sched)
    logger.info("scheduler started (hours=%s tz=%s)", hours_csv, TZ)
    return sched


def stop() -> None:
    if state.instance is not None:
        try:
            state.instance.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        state.instance = None
        state.running = False
        state.next_run = None


def refresh_next() -> None:
    if state.instance is not None:
        state.next_run = _format_next(state.instance)


def _format_next(sched: AsyncIOScheduler) -> Optional[str]:
    """Return the earliest of (next cron run, next startup run)."""
    candidates = []
    for jid in ("bcv-scrape-cron", "bcv-scrape-startup"):
        job = sched.get_job(jid)
        if job and job.next_run_time:
            candidates.append(job.next_run_time)
    if not candidates:
        return None
    return min(candidates).astimezone().isoformat(timespec="seconds")


