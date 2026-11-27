from __future__ import annotations

from dataclasses import dataclass

from .adapters import GdeltNewsFeed, OfficialRssFeed
from .adapters.http import HttpClient
from .db import connect, init_db
from .engines import MacroNewsEngine
from .models import MacroNewsItem
from .news_validation import critical_news_is_confirmed, validate_macro_news_items
from .repositories import MarketRepository
from .source_health import record_source_failure, record_source_success

OFFICIAL_MACRO_FEEDS = (
    (
        "TCMB",
        "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB%2BTR/"
        "Bottom%2BMenu/Diger/RSS/Basin%2BDuyurulari",
    ),
    (
        "TCMB_PPK",
        "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB%2BTR/"
        "Bottom%2BMenu/Diger/RSS/PPK%2BKararlari",
    ),
    ("FED", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html"),
    ("BOE", "https://www.bankofengland.co.uk/rss/news"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
    ("EIA", "https://www.eia.gov/rss/todayinenergy.xml"),
)


@dataclass(frozen=True)
class MacroNewsRefresh:
    fetched: int
    stored: int
    critical_messages: tuple[str, ...]
    accepted: int = 0
    rejected: int = 0


def refresh_macro_news(
    limit_per_source: int = 8, *, client: HttpClient | None = None,
) -> MacroNewsRefresh:
    init_db()
    feed = OfficialRssFeed(client=client)
    fetched_items: list[MacroNewsItem] = []
    official_successes = 0
    source_errors: list[str] = []
    for source, url in OFFICIAL_MACRO_FEEDS:
        try:
            fetched_items.extend(feed.read(source, url, limit=limit_per_source))
            official_successes += 1
        except Exception as error:
            print(f"Macro feed failed for {source}: {error}")
            source_errors.append(f"{source}: {error}")
    try:
        fetched_items.extend(GdeltNewsFeed(client=client).read())
    except Exception as error:
        print(f"Global GDELT feed failed: {error}")
        source_errors.append(f"GDELT: {error}")

    validation = validate_macro_news_items(fetched_items)
    accepted_items = list(validation.accepted)

    critical_messages: list[str] = []
    with connect() as connection:
        repository = MarketRepository(connection)
        unseen = [
            item for item in accepted_items if not repository.macro_news_exists(item)
        ]
        stored = repository.insert_macro_news(accepted_items)
        impacts = [
            (item, MacroNewsEngine().classify(item))
            for item in unseen
        ]
        for item, impact in impacts:
            if not critical_news_is_confirmed(item, accepted_items):
                continue
            if abs(impact.score) * impact.importance >= 0.50:
                direction = "POZITIF" if impact.score > 0 else "RISK"
                critical_messages.append(
                    f"MAKRO {direction}: {item.source}\n"
                    f"{item.title}\n"
                    f"Etki: {impact.score:+.2f} | {impact.category}"
                )
        if official_successes >= max(3, len(OFFICIAL_MACRO_FEEDS) // 2):
            record_source_success(connection, "MACRO_NEWS")
        else:
            record_source_failure(
                connection,
                "MACRO_NEWS",
                "; ".join(source_errors) or "Resmi makro akis kapsami yetersiz",
            )
        connection.commit()
    rejected = (
        validation.rejected_stale
        + validation.rejected_future
        + validation.rejected_invalid
        + validation.rejected_duplicate
    )
    return MacroNewsRefresh(
        fetched=len(fetched_items),
        stored=stored,
        critical_messages=tuple(critical_messages),
        accepted=len(accepted_items),
        rejected=rejected,
    )
