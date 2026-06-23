from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import (
    CURRENCIES,
    CURRENCY_FLAGS,
    CURRENCY_LABELS,
    SCRAPE_API_KEY,
    SCRAPE_HOUR_LIST,
    SCRAPE_MINUTE_LIST,
    STATIC_DIR,
    TEMPLATES_DIR,
    TZ,
)
from .database import (
    get_all_changes,
    get_history,
    get_latest,
    get_previous,
    get_sparkline,
    init_db,
    is_healthy,
    last_scraped_at,
    now_iso,
)
from .models import (
    ConversionRequest,
    ConversionResult,
    HealthResponse,
    HistoryResponse,
    LatestResponse,
    RateLatest,
    ScrapeSummary,
    SchedulerStatus,
)
from .scheduler import state as sched_state
from .scheduler import start as start_scheduler
from .scheduler import stop as stop_scheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger("bcv")


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_api_key(key: Optional[str]) -> None:
    if not SCRAPE_API_KEY:
        raise HTTPException(status_code=404, detail="scrape endpoint disabled")
    if not key or not hmac.compare_digest(key, SCRAPE_API_KEY):
        raise HTTPException(status_code=403, detail="invalid api key")


async def require_api_key(key: Optional[str] = Security(api_key_header)) -> None:
    _check_api_key(key)


def _format_value(v: float) -> str:
    """Venezuelan convention: comma as decimal sep, dot as thousands sep."""
    s = f"{v:,.8f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _build_rate_latest(currency: str) -> Optional[RateLatest]:
    try:
        latest = get_latest(currency)
    except Exception:  # noqa: BLE001
        return None
    if not latest:
        return None
    try:
        previous = get_previous(currency)
        history = get_sparkline(currency, limit=30)
    except Exception:  # noqa: BLE001
        previous, history = None, []
    prev_value = previous["value"] if previous else None
    delta = (latest["value"] - prev_value) if prev_value is not None else None
    delta_pct = ((delta / prev_value) * 100.0) if (delta is not None and prev_value) else None
    return RateLatest(
        currency=currency,
        label=CURRENCY_LABELS.get(currency, currency),
        flag=CURRENCY_FLAGS.get(currency, ""),
        value=latest["value"],
        source_date=latest["source_date"],
        scraped_at=latest["scraped_at"],
        previous_value=prev_value,
        delta=delta,
        delta_pct=delta_pct,
        history=history,
    )


def _safe_rates() -> list[RateLatest]:
    out: list[RateLatest] = []
    for c in CURRENCIES:
        r = _build_rate_latest(c)
        if r is not None:
            out.append(r)
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("db ready")
    try:
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to start scheduler: %s", exc)
    yield
    stop_scheduler()


app = FastAPI(
    title="BCV Scraper",
    description="Tracks the official BCV reference exchange rates 6 times a day.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


templates.env.filters["bcv_value"] = _format_value


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, **_dashboard_context()},
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, currency: str = Query("USD")):
    cur = currency.upper()
    if cur not in CURRENCIES:
        cur = "USD"
    records = get_history(cur, limit=500)
    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "currency": cur,
            "currencies": CURRENCIES,
            "records": records,
        },
    )


@app.get("/api/rates/latest", response_model=LatestResponse)
async def api_latest():
    rates = _safe_rates()
    scraped = rates[0].scraped_at if rates else now_iso()
    source_date = rates[0].source_date if rates else None
    return LatestResponse(rates=rates, scraped_at=scraped, source_date=source_date)


@app.get("/api/rates/latest/{currency}", response_model=RateLatest)
async def api_latest_one(currency: str):
    cur = currency.upper()
    if cur not in CURRENCIES:
        raise HTTPException(status_code=400, detail=f"unsupported currency: {currency}")
    rate = _build_rate_latest(cur)
    if not rate:
        raise HTTPException(status_code=404, detail="no data yet")
    return rate


@app.get("/api/rates/history", response_model=HistoryResponse)
async def api_history(
    currency: str = Query(...),
    limit: int = Query(200, ge=1, le=2000),
):
    cur = currency.upper()
    if cur not in CURRENCIES:
        raise HTTPException(status_code=400, detail=f"unsupported currency: {currency}")
    records = get_history(cur, limit=limit)
    return HistoryResponse(currency=cur, records=records)


@app.get("/api/rates/changes")
async def api_changes(limit: int = Query(500, ge=1, le=2000)):
    return {"records": get_all_changes(limit=limit)}


@app.post("/api/scrape", response_model=ScrapeSummary, dependencies=[Depends(require_api_key)])
async def api_scrape():
    from .scraper import scrape_once
    summary = await scrape_once()
    sched_state.last_summary = summary.model_dump()
    sched_state.last_run = summary.scraped_at
    return summary


@app.get("/api/scheduler/status", response_model=SchedulerStatus)
async def api_scheduler_status():
    from .scheduler import refresh_next
    refresh_next()
    errs: list[str] = []
    ins = skp = 0
    if sched_state.last_summary:
        errs = list(sched_state.last_summary.get("errors") or [])
        ins = int(sched_state.last_summary.get("inserted") or 0)
        skp = int(sched_state.last_summary.get("skipped") or 0)
    return SchedulerStatus(
        running=sched_state.running,
        last_run=sched_state.last_run,
        next_run=sched_state.next_run,
        hours=SCRAPE_HOUR_LIST,
        minutes=SCRAPE_MINUTE_LIST,
        timezone=TZ,
        last_errors=errs,
        last_inserted=ins,
        last_skipped=skp,
    )


CALC_CURRENCIES = [
    {"code": "VES", "label": "Bolívar venezolano", "flag": "Bs"},
    {"code": "USD", "label": CURRENCY_LABELS.get("USD", "Dólar"), "flag": CURRENCY_FLAGS.get("USD", "$")},
    {"code": "EUR", "label": CURRENCY_LABELS.get("EUR", "Euro"), "flag": CURRENCY_FLAGS.get("EUR", "€")},
    {"code": "CNY", "label": CURRENCY_LABELS.get("CNY", "Yuan"), "flag": CURRENCY_FLAGS.get("CNY", "¥")},
    {"code": "TRY", "label": CURRENCY_LABELS.get("TRY", "Lira"), "flag": CURRENCY_FLAGS.get("TRY", "₺")},
    {"code": "RUB", "label": CURRENCY_LABELS.get("RUB", "Rublo"), "flag": CURRENCY_FLAGS.get("RUB", "₽")},
]


def _get_rates_map() -> dict[str, float]:
    rates: dict[str, float] = {}
    for c in CURRENCIES:
        try:
            latest = get_latest(c)
            if latest:
                rates[c] = latest["value"]
        except Exception:
            pass
    return rates


@app.post("/api/calculate", response_model=ConversionResult)
async def api_calculate(body: ConversionRequest):
    fro = body.from_currency.upper()
    to = body.to_currency.upper()
    valid = {c["code"] for c in CALC_CURRENCIES}
    if fro not in valid:
        raise HTTPException(status_code=400, detail=f"unsupported currency: {body.from_currency}")
    if to not in valid:
        raise HTTPException(status_code=400, detail=f"unsupported currency: {body.to_currency}")
    rates = _get_rates_map()
    if not rates:
        raise HTTPException(status_code=503, detail="no exchange rate data available yet")
    source_date = "—"
    for c in CURRENCIES:
        try:
            latest = get_latest(c)
            if latest:
                source_date = latest.get("source_date", "—")
                break
        except Exception:
            pass
    if fro == to:
        return ConversionResult(
            amount=body.amount,
            from_currency=fro,
            to_currency=to,
            result=body.amount,
            rate=1.0,
            source_date=source_date,
        )
    # convert to VES first, then to target
    if fro == "VES":
        ves_amount = body.amount
        rate = 1.0 / rates[to] if to != "VES" else 1.0
    else:
        if fro not in rates:
            raise HTTPException(status_code=503, detail=f"no rate for {fro}")
        ves_amount = body.amount * rates[fro]
        if to == "VES":
            rate = rates[fro]
        else:
            if to not in rates:
                raise HTTPException(status_code=503, detail=f"no rate for {to}")
            rate = rates[fro] / rates[to]
    if to == "VES":
        result = ves_amount
    else:
        if to not in rates:
            raise HTTPException(status_code=503, detail=f"no rate for {to}")
        result = ves_amount / rates[to]
    return ConversionResult(
        amount=body.amount,
        from_currency=fro,
        to_currency=to,
        result=round(result, 8),
        rate=round(rate, 8),
        source_date=source_date,
    )


@app.get("/api/health", response_model=HealthResponse)
async def api_health():
    return HealthResponse(
        ok=True,
        db=is_healthy(),
        scraper=bool(sched_state.last_summary) or is_healthy(),
        now=datetime.now().astimezone(),
    )


def _dashboard_context() -> dict:
    last_errors: list[str] = []
    if sched_state.last_summary and sched_state.last_summary.get("errors"):
        last_errors = list(sched_state.last_summary["errors"])
    schedule_times = sorted(
        f"{h:02d}:{m:02d}"
        for h in SCRAPE_HOUR_LIST
        for m in SCRAPE_MINUTE_LIST
    )
    return {
        "rates": _safe_rates(),
        "last_scraped_at": last_scraped_at(),
        "last_errors": last_errors,
        "now": now_iso(),
        "next_run": sched_state.next_run,
        "hours": SCRAPE_HOUR_LIST,
        "minutes": SCRAPE_MINUTE_LIST,
        "schedule_times": schedule_times,
        "tz": TZ,
        "calc_currencies": CALC_CURRENCIES,
    }


@app.exception_handler(404)
async def _not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": exc.detail or "not found"})
    if exc.detail and exc.detail != "Not Found":
        return JSONResponse(status_code=404, content={"detail": exc.detail})
    return templates.TemplateResponse(
        "index.html",
        {"request": request, **_dashboard_context()},
        status_code=404,
    )
