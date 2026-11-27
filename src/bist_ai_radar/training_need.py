"""Decide whether a new training run is *needed*. It never starts one.

The check only reads matured outcomes and the ledger. Thresholds come from a
policy file the administrator writes after looking at real results; without
that file the check reports the evidence and makes no decision. Calendar age
alone is never a reason, and a single bad window can never trigger a need:
degradation must persist over at least two consecutive windows, measured
relative to BIST so a falling market is not mistaken for model decay.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from math import log
from pathlib import Path
from statistics import mean

from .public_research import METHOD_VERSION
from .recommendation_outcomes import Outcome

POLICY_FILE = "training_policy.json"
REQUIRED_KEYS = {"horizon", "evaluated_method_version"}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Reason:
    code: str
    text: str


@dataclass(frozen=True)
class Assessment:
    status: str  # "esik_tanimsiz" | "gerekli" | "gerekli_degil"
    reasons: tuple[Reason, ...] = ()
    evidence: dict = field(default_factory=dict)

    @property
    def needed(self) -> bool:
        return self.status == "gerekli"

    def fingerprint(self) -> str:
        """Stable id of *why* training is needed; same reasons → same id."""
        key = json.dumps({
            "reasons": sorted(reason.code for reason in self.reasons),
            "method_version": METHOD_VERSION,
            "horizon": self.evidence.get("horizon"),
        }, sort_keys=True)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def load_policy(directory: Path) -> dict | None:
    path = Path(directory) / POLICY_FILE
    if not path.exists():
        return None
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise PolicyError("training_policy.json is not valid JSON.") from error
    validate_policy(policy)
    return policy


def validate_policy(policy: dict) -> None:
    missing = REQUIRED_KEYS - set(policy)
    if missing:
        raise PolicyError(f"Policy is missing: {', '.join(sorted(missing))}.")
    degradation = policy.get("degradation")
    if degradation is not None:
        if int(degradation.get("consecutive_windows", 0)) < 2:
            raise PolicyError("Degradation needs at least 2 consecutive windows; one bad window is not enough.")
        if int(degradation.get("window_size", 0)) < 1:
            raise PolicyError("Degradation window_size must be positive.")
    for key in ("calendar_days", "max_age_days", "schedule"):
        if key in policy:
            raise PolicyError("Calendar-based training rules are not allowed.")


def _distribution(entries: list[dict]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["main_sector"] or "?"] = counts.get(entry["main_sector"] or "?", 0) + 1
    total = sum(counts.values())
    return {key: value / total for key, value in counts.items()} if total else {}


def population_stability(baseline: list[dict], recent: list[dict]) -> float | None:
    """PSI of the main-sector mix between two groups of recommendations."""
    if not baseline or not recent:
        return None
    first, second = _distribution(baseline), _distribution(recent)
    floor = 1e-4
    return sum(
        (second.get(key, floor) - first.get(key, floor))
        * log(max(second.get(key, floor), floor) / max(first.get(key, floor), floor))
        for key in set(first) | set(second)
    )


def evidence_summary(entries: list[dict], outcomes: list[Outcome], horizon: int) -> dict:
    rows = sorted(
        (item for item in outcomes if item.horizon == horizon and item.excess_vs_benchmark is not None),
        key=lambda item: (item.published_at, item.entry_id),
    )
    return {
        "horizon": horizon,
        "ledger_entries": len(entries),
        "matured_compared": len(rows),
        "beat_benchmark": (sum(item.excess_vs_benchmark > 0 for item in rows) / len(rows)) if rows else None,
        "mean_excess_vs_benchmark": mean(item.excess_vs_benchmark for item in rows) if rows else None,
        "regimes": sorted({item.regime for item in rows}),
        "method_version": METHOD_VERSION,
    }


def assess(entries: list[dict], outcomes: list[Outcome], policy: dict | None) -> Assessment:
    horizon = int(policy["horizon"]) if policy else 21
    evidence = evidence_summary(entries, outcomes, horizon)
    if policy is None:
        return Assessment("esik_tanimsiz", (), evidence)
    validate_policy(policy)
    rows = sorted(
        (
            item for item in outcomes
            if item.horizon == horizon and item.excess_vs_benchmark is not None
        ),
        key=lambda item: (item.published_at, item.entry_id),
    )
    reasons: list[Reason] = []

    trained_through = str(policy.get("trained_through", ""))
    new_labels = [item for item in rows if item.published_at[:10] > trained_through]
    evidence["new_matured_since_training"] = len(new_labels)
    minimum = policy.get("min_new_matured")
    if minimum is not None and len(new_labels) >= int(minimum):
        reasons.append(Reason(
            "yeni_etiketli_veri",
            f"Son eğitimden sonra {len(new_labels)} yeni olgun sonuç birikti (eşik {int(minimum)}).",
        ))

    degradation = policy.get("degradation")
    if degradation:
        size = int(degradation["window_size"])
        count = int(degradation["consecutive_windows"])
        limit = float(degradation["max_mean_excess"])
        windows = [rows[index:index + size] for index in range(0, len(rows) - len(rows) % size, size)]
        recent = windows[-count:] if len(windows) >= count else []
        means = [mean(item.excess_vs_benchmark for item in window) for window in recent]
        regimes = {item.regime for window in recent for item in window}
        evidence["recent_window_excess"] = means
        min_regimes = int(degradation.get("min_regimes", 1))
        if recent and all(value <= limit for value in means) and len(regimes) >= min_regimes:
            reasons.append(Reason(
                "kalici_goreli_bozulma",
                f"Son {count} ardışık pencerede BIST'e göre ortalama getiri eşiğin altında kaldı.",
            ))

    drift = policy.get("drift")
    if drift:
        size = int(drift["sample_size"])
        current = [entry for entry in entries if entry["method_version"] == METHOD_VERSION]
        if len(current) >= 2 * size:
            psi = population_stability(current[:size], current[-size:])
            evidence["sector_mix_psi"] = psi
            if psi is not None and psi >= float(drift["max_psi"]):
                reasons.append(Reason(
                    "veri_dagilimi_degisti",
                    "Önerilen şirketlerin sektör dağılımı başlangıca göre belirgin biçimde değişti.",
                ))

    evaluated = str(policy["evaluated_method_version"])
    if evaluated != METHOD_VERSION:
        reasons.append(Reason(
            "yontem_uyumsuzlugu",
            f"Canlı yöntem {METHOD_VERSION}, son değerlendirilen yöntem {evaluated}.",
        ))
    return Assessment("gerekli" if reasons else "gerekli_degil", tuple(reasons), evidence)
