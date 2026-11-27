from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    yahoo_chart_base_url: str
    kap_feed_url: str
    financial_batch_size: int


def load_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/public-cloud.sqlite3"),
        yahoo_chart_base_url=os.getenv("YAHOO_CHART_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart"),
        kap_feed_url=os.getenv("KAP_FEED_URL", "https://www.kap.org.tr/tr/api/disclosure/list/light"),
        financial_batch_size=max(1, int(os.getenv("FINANCIAL_BATCH_SIZE", "24"))),
    )


def sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Use a sqlite:/// DATABASE_URL.")
    return database_url.removeprefix("sqlite:///")


def database_backend(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return "sqlite"
    if database_url.startswith(("postgresql://", "postgres://")):
        return "postgresql"
    raise ValueError("DATABASE_URL must start with sqlite:/// or postgresql://.")
