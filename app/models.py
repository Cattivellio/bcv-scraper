from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


CurrencyCode = Literal["USD", "EUR", "CNY", "TRY", "RUB"]


class RateRecord(BaseModel):
    id: int
    currency: CurrencyCode
    value: float
    source_date: str = Field(..., description="Fecha Valor (YYYY-MM-DD) reported by BCV")
    scraped_at: str = Field(..., description="ISO timestamp of the scrap that produced this row")


class RateLatest(BaseModel):
    currency: CurrencyCode
    label: str
    flag: str
    value: float
    source_date: str
    scraped_at: str
    previous_value: Optional[float] = None
    delta: Optional[float] = None
    delta_pct: Optional[float] = None
    history: list[float] = Field(default_factory=list, description="Last N values, oldest first")


class LatestResponse(BaseModel):
    rates: list[RateLatest]
    scraped_at: str
    source_date: Optional[str] = None


class HistoryResponse(BaseModel):
    currency: CurrencyCode
    records: list[RateRecord]


class ScrapeSummary(BaseModel):
    scraped_at: str
    source_date: Optional[str] = None
    source_url: str
    inserted: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    rates: list[RateLatest]


class SchedulerStatus(BaseModel):
    running: bool
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    hours: list[int]
    minutes: list[int]
    timezone: str
    last_errors: list[str] = Field(default_factory=list)
    last_inserted: int = 0
    last_skipped: int = 0


class ConversionRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to convert")
    from_currency: str = Field(..., description="Source currency code")
    to_currency: str = Field(..., description="Target currency code")


class ConversionResult(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    result: float
    rate: float = Field(..., description="Effective exchange rate used")
    source_date: str


class HealthResponse(BaseModel):
    ok: bool
    db: bool
    scraper: bool
    now: datetime
