from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import MacroNewsItem


@dataclass(frozen=True)
class MacroSourcePolicy:
    trust: float
    region: str
    topic: str
    official: bool = True


@dataclass(frozen=True)
class MacroNewsValidation:
    accepted: tuple[MacroNewsItem, ...]
    rejected_stale: int
    rejected_future: int
    rejected_invalid: int
    rejected_duplicate: int


SOURCE_POLICIES = {
    "TCMB": MacroSourcePolicy(1.00, "TR", "monetary"),
    "TCMB_PPK": MacroSourcePolicy(1.00, "TR", "monetary"),
    "FED": MacroSourcePolicy(0.98, "US", "monetary"),
    "ECB": MacroSourcePolicy(0.96, "EU", "monetary"),
    "BOE": MacroSourcePolicy(0.94, "UK", "monetary"),
    "BEA": MacroSourcePolicy(0.94, "US", "growth"),
    "EIA": MacroSourcePolicy(0.94, "GLOBAL", "energy"),
}
GDELT_POLICY = MacroSourcePolicy(0.58, "GLOBAL", "general", official=False)
MAX_NEWS_AGE_DAYS = 21
MAX_FUTURE_HOURS = 6

_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "bu",
    "da",
    "de",
    "for",
    "from",
    "ile",
    "in",
    "icin",
    "of",
    "on",
    "the",
    "to",
    "ve",
}


def source_policy(source: str) -> MacroSourcePolicy:
    if source.startswith("GDELT:"):
        return GDELT_POLICY
    return SOURCE_POLICIES.get(
        source,
        MacroSourcePolicy(0.65, "UNKNOWN", "general", official=False),
    )


def validate_macro_news_items(
    items: list[MacroNewsItem],
    now: datetime | None = None,
) -> MacroNewsValidation:
    reference = _naive_utc(now or datetime.now(timezone.utc))
    accepted: list[MacroNewsItem] = []
    stale = future = invalid = duplicate = 0
    for item in sorted(items, key=lambda value: value.published_at, reverse=True):
        published = _naive_utc(item.published_at)
        age_hours = (reference - published).total_seconds() / 3600
        if not item.title.strip() or not item.link.strip():
            invalid += 1
            continue
        if age_hours < -MAX_FUTURE_HOURS:
            future += 1
            continue
        if age_hours > MAX_NEWS_AGE_DAYS * 24:
            stale += 1
            continue
        if any(_same_source_duplicate(item, existing) for existing in accepted):
            duplicate += 1
            continue
        accepted.append(item)
    return MacroNewsValidation(tuple(accepted), stale, future, invalid, duplicate)


def source_quality_weight(
    item: MacroNewsItem,
    universe: list[MacroNewsItem] | tuple[MacroNewsItem, ...] = (),
) -> float:
    policy = source_policy(item.source)
    if policy.official:
        return policy.trust
    corroboration = corroborating_source_count(item, universe)
    if corroboration >= 3:
        return policy.trust
    if corroboration >= 2:
        return policy.trust * 0.85
    return policy.trust * 0.45


def critical_news_is_confirmed(
    item: MacroNewsItem,
    universe: list[MacroNewsItem] | tuple[MacroNewsItem, ...],
) -> bool:
    policy = source_policy(item.source)
    return policy.official and policy.trust >= 0.90 or corroborating_source_count(
        item,
        universe,
    ) >= 2


def corroborating_source_count(
    item: MacroNewsItem,
    universe: list[MacroNewsItem] | tuple[MacroNewsItem, ...],
) -> int:
    sources = {_source_identity(item.source)}
    item_tokens = _event_tokens(item)
    if len(item_tokens) < 3:
        return len(sources)
    for candidate in universe:
        if candidate is item or _source_identity(candidate.source) in sources:
            continue
        if abs((candidate.published_at - item.published_at).total_seconds()) > 72 * 3600:
            continue
        candidate_tokens = _event_tokens(candidate)
        if _jaccard(item_tokens, candidate_tokens) >= 0.36:
            sources.add(_source_identity(candidate.source))
    return len(sources)


def _same_source_duplicate(left: MacroNewsItem, right: MacroNewsItem) -> bool:
    if _source_identity(left.source) != _source_identity(right.source):
        return False
    if left.link and right.link and left.link.rstrip("/") == right.link.rstrip("/"):
        return True
    if abs((left.published_at - right.published_at).total_seconds()) > 72 * 3600:
        return False
    left_tokens = _event_tokens(left)
    right_tokens = _event_tokens(right)
    return min(len(left_tokens), len(right_tokens)) >= 3 and _jaccard(
        left_tokens,
        right_tokens,
    ) >= 0.86


def _event_tokens(item: MacroNewsItem) -> set[str]:
    normalized = _normalize(item.title)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 2 and token not in _STOPWORDS
    }


def _source_identity(source: str) -> str:
    return source.removeprefix("GDELT:").casefold()


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _normalize(value: str) -> str:
    translated = value.casefold().translate(
        str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
    )
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", translated)
        if not unicodedata.combining(character)
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
