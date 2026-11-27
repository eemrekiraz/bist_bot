from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from ..models import MacroNewsItem
from ..news_validation import source_policy, source_quality_weight


@dataclass(frozen=True)
class MacroNewsImpact:
    score: float
    importance: float
    category: str
    reason: str


class MacroNewsEngine:
    rules = (
        (
            "parasal_sikilasma",
            -0.80,
            ("faiz art", "rate hike", "rate increase", "tightening", "restrictive"),
        ),
        (
            "parasal_gevseme",
            0.70,
            ("faiz indir", "rate cut", "easing", "liquidity support"),
        ),
        (
            "enflasyon_baskisi",
            -0.55,
            (
                "enflasyon",
                "inflation",
                "price pressure",
                "fiyat bask",
                "producer price",
            ),
        ),
        (
            "jeopolitik_risk",
            -0.75,
            ("war", "savas", "sanction", "yaptirim", "conflict", "gerilim"),
        ),
        (
            "enerji_soku",
            -0.50,
            ("oil price", "petrol", "natural gas", "dogal gaz", "energy shock"),
        ),
        (
            "enerji_arzi",
            0.40,
            ("oil production", "supply increase", "uretim art", "stok art", "inventory build"),
        ),
        (
            "buyume",
            0.45,
            (
                "economic growth",
                "buyume",
                "industrial production",
                "istihdam",
                "gross domestic product",
                "gdp increase",
            ),
        ),
        (
            "daralma",
            -0.55,
            ("recession", "daralma", "contraction", "unemployment rises", "gdp decline"),
        ),
        (
            "likidite",
            0.35,
            ("likidite", "liquidity", "credit support", "kredi destegi"),
        ),
        (
            "mali_destek",
            0.40,
            ("fiscal support", "stimulus", "tesvik", "investment program", "kamu yatirim"),
        ),
        (
            "ticaret_kisitlamasi",
            -0.45,
            ("tariff", "trade restriction", "ihracat yasagi", "ithalat vergisi", "embargo"),
        ),
    )

    def classify(self, item: MacroNewsItem, sector: str = "") -> MacroNewsImpact:
        text = self._normalize(f"{item.title} {item.body}")
        category = "genel"
        score = 0.0
        matches = 0
        for rule_category, rule_score, terms in self.rules:
            hits = sum(term in text for term in terms)
            if hits and abs(rule_score) >= abs(score):
                category = rule_category
                score = rule_score
            matches += hits
        score += self._sector_adjustment(category, sector)
        score = max(-1.0, min(1.0, score))
        policy = source_policy(item.source)
        importance = min(
            1.0,
            0.35
            + matches * 0.12
            + policy.trust * 0.22
            + (0.10 if policy.topic in {"monetary", "growth", "energy"} else 0.0),
        )
        return MacroNewsImpact(
            score=score,
            importance=importance,
            category=category,
            reason=f"{item.source}: {category}",
        )

    def aggregate(
        self,
        items: list[MacroNewsItem],
        sector: str = "",
        max_age_days: int = 30,
    ) -> MacroNewsImpact | None:
        now = datetime.now()
        weighted_score = 0.0
        total_weight = 0.0
        strongest: MacroNewsImpact | None = None
        for item in items:
            age_days = max(0.0, (now - item.published_at).total_seconds() / 86400)
            if age_days > max_age_days:
                continue
            impact = self.classify(item, sector)
            recency = math.exp(-age_days / 10)
            quality = source_quality_weight(item, items)
            weight = impact.importance * recency * quality
            weighted_score += impact.score * weight
            total_weight += weight
            if strongest is None or impact.importance * abs(impact.score) > (
                strongest.importance * abs(strongest.score)
            ):
                strongest = impact
        if not strongest or total_weight == 0:
            return None
        return MacroNewsImpact(
            score=max(-1.0, min(1.0, weighted_score / total_weight)),
            importance=strongest.importance,
            category=strongest.category,
            reason=strongest.reason,
        )

    def _sector_adjustment(self, category: str, sector: str) -> float:
        normalized_sector = self._normalize(sector)
        if category == "jeopolitik_risk":
            if self._contains(normalized_sector, "savunma"):
                return 0.45
            if self._contains(normalized_sector, "turizm", "havayolu", "ulastirma"):
                return -0.25
        if category in {"enerji_soku", "enerji_arzi"}:
            direction = -1.0 if category == "enerji_arzi" else 1.0
            if self._contains(normalized_sector, "petrol", "enerji", "madencilik"):
                return 0.30 * direction
            if self._contains(normalized_sector, "havayolu", "ulastirma", "kimya", "cam"):
                return -0.25 * direction
        if category in {"buyume", "daralma"}:
            direction = 1.0 if category == "buyume" else -1.0
            if self._contains(
                normalized_sector,
                "ana metal",
                "otomotiv",
                "sanayi",
                "cimento",
                "lojistik",
            ):
                return 0.22 * direction
            if self._contains(normalized_sector, "gida", "saglik", "telekom"):
                return -0.05 * direction
        if category in {"parasal_sikilasma", "parasal_gevseme"}:
            direction = -1.0 if category == "parasal_sikilasma" else 1.0
            if self._contains(normalized_sector, "gayrimenkul", "insaat", "faktoring"):
                return 0.22 * direction
            if self._contains(normalized_sector, "banka", "sigorta"):
                return -0.08 * direction
        if category == "ticaret_kisitlamasi" and self._contains(
            normalized_sector,
            "ihrac",
            "otomotiv",
            "tekstil",
            "demir",
            "celik",
        ):
            return -0.20
        if category == "mali_destek" and self._contains(
            normalized_sector,
            "insaat",
            "savunma",
            "altyapi",
            "teknoloji",
        ):
            return 0.18
        return 0.0

    def _contains(self, value: str, *keywords: str) -> bool:
        return any(keyword in value for keyword in keywords)

    def _normalize(self, value: str) -> str:
        translated = value.casefold().translate(
            str.maketrans(
                {"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"}
            )
        )
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", translated)
            if not unicodedata.combining(character)
        )
