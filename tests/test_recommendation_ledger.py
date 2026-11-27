from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from bist_ai_radar.models import PriceBar
from bist_ai_radar.public_research import ISTANBUL, METHOD_VERSION
from bist_ai_radar.recommendation_jobs import notify_if_needed, render_notice, send_admin_message
from bist_ai_radar.recommendation_ledger import (
    LEDGER_FILE, LedgerError, build_entries, read_ledger, record_snapshot,
)
from bist_ai_radar.recommendation_outcomes import (
    BENCHMARK_SYMBOL, attribute, classify_regime, evaluate_entry, evaluate_ledger, summarize,
)
from bist_ai_radar.training_need import PolicyError, assess, validate_policy

PUBLISHED = datetime(2026, 11, 27, 19, 45, tzinfo=ISTANBUL)


def company(symbol: str, sector: str, score: float) -> dict:
    return {
        "symbol": symbol, "title": f"{symbol} A.Ş.", "sector": sector, "day": "2026-11-27",
        "close": 10.0, "period": "2026/09", "eligible": True, "news": [],
        "scores": {"dengeli": score, "kalite": score, "buyume": score},
        "reasons": ["Örnek gerekçe"], "risk": "Örnek risk",
    }


def snapshot() -> dict:
    return {
        "updated": PUBLISHED.isoformat(timespec="minutes"),
        "companies": [
            company("AAAA", "BANKALAR", 0.9), company("BBBB", "SIGORTA SIRKETLERI", 0.8),
            company("CCCC", "BILISIM", 0.7), company("DDDD", "BANKALAR", 0.6),
        ],
        "macro": [],
    }


def series(symbol: str, closes: list[float], start: date = date(2026, 11, 27)) -> list[PriceBar]:
    return [
        PriceBar(symbol, start + timedelta(days=index), value, value, value, value, 1000, raw_close=value)
        for index, value in enumerate(closes)
    ]


def entry(**overrides: object) -> dict:
    base = {
        "entry_id": "2026-11-27:dengeli:AAAA", "symbol": "AAAA", "profile": "dengeli",
        "method_version": METHOD_VERSION, "published_at": "2026-11-27T19:45+03:00",
        "main_sector": "finans", "close_day": "2026-11-27", "sector_peers": ["AAAA", "P1", "P2", "P3"],
    }
    return {**base, **overrides}


class LedgerTests(unittest.TestCase):
    def test_entries_match_published_portfolio_with_required_fields(self) -> None:
        entries = build_entries(snapshot(), profiles=("dengeli",))
        self.assertEqual([item["symbol"] for item in entries], ["AAAA", "CCCC"])
        first = entries[0]
        for key in ("published_at", "data_cutoff", "main_sector", "original_sector", "close_day",
                    "close_price", "reasons", "method", "method_version", "sector_peers"):
            self.assertIn(key, first)
        self.assertEqual(first["main_sector"], "finans")
        self.assertEqual(first["original_sector"], "BANKALAR")
        self.assertEqual(first["sector_peers"], ["AAAA", "BBBB", "DDDD"])

    def test_record_is_append_only_and_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            now = PUBLISHED + timedelta(minutes=3)
            first = record_snapshot(Path(directory), snapshot(), now=now)
            second = record_snapshot(Path(directory), snapshot(), now=now + timedelta(minutes=1))
            self.assertGreater(first.added, 0)
            self.assertEqual(second.added, 0)
            self.assertEqual(second.skipped_existing, first.added)
            entries = read_ledger(Path(directory))
            self.assertEqual(len(entries), first.added)
            self.assertTrue(all(item["recorded_at"].startswith("2026-11-27T16:48") for item in entries))

    def test_old_snapshot_is_never_backfilled(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(LedgerError):
                record_snapshot(Path(directory), snapshot(), now=PUBLISHED + timedelta(days=2))
            self.assertFalse((Path(directory) / LEDGER_FILE).exists())

    def test_edit_or_deletion_is_detected(self) -> None:
        with TemporaryDirectory() as directory:
            record_snapshot(Path(directory), snapshot(), now=PUBLISHED + timedelta(minutes=1))
            path = Path(directory) / LEDGER_FILE
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text(lines[0].replace('"close_price":10.0', '"close_price":9.0') + "\n"
                            + "\n".join(lines[1:]) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                read_ledger(Path(directory))
            path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                read_ledger(Path(directory))


class OutcomeTests(unittest.TestCase):
    def test_horizon_is_not_labelled_before_it_matures(self) -> None:
        bars = {"AAAA": series("AAAA", [10 + index * 0.01 for index in range(30)]),
                BENCHMARK_SYMBOL: series(BENCHMARK_SYMBOL, [100] * 30)}
        horizons = {item.horizon for item in evaluate_entry(entry(), bars)}
        self.assertEqual(horizons, {5, 21})

    def test_loss_in_falling_market_is_not_a_selection_error(self) -> None:
        bars = {
            "AAAA": series("AAAA", [10, 9.9, 9.8, 9.7, 9.6, 9.5]),
            BENCHMARK_SYMBOL: series(BENCHMARK_SYMBOL, [100, 97, 94, 91, 88, 85]),
            "P1": series("P1", [10, 9, 9, 9, 9, 8]),
            "P2": series("P2", [10, 9, 9, 9, 9, 8]),
            "P3": series("P3", [10, 9, 9, 9, 9, 8]),
        }
        outcome = evaluate_entry(entry(), bars, horizons=(5,))[0]
        self.assertLess(outcome.net_return, 0)
        self.assertGreater(outcome.excess_vs_benchmark, 0)
        self.assertEqual(outcome.attribution, "piyasa_kaynakli_zarar")
        self.assertEqual(outcome.regime, "kriz")
        self.assertEqual(outcome.sector_peers_used, 4)
        self.assertIsNotNone(outcome.excess_vs_sector)

    def test_cost_and_missing_benchmark_are_explicit(self) -> None:
        bars = {"AAAA": series("AAAA", [10, 10, 10, 10, 10, 11])}
        outcome = evaluate_entry(entry(), bars, horizons=(5,), round_trip_cost=0.01)[0]
        self.assertAlmostEqual(outcome.net_return, 0.09)
        self.assertIsNone(outcome.benchmark_return)
        self.assertEqual(outcome.attribution, "karsilastirma_eksik")
        self.assertIsNone(outcome.sector_return)

    def test_attribution_and_regime_labels(self) -> None:
        self.assertEqual(attribute(0.05, 0.02), "basarili")
        self.assertEqual(attribute(0.05, -0.02), "endeksin_gerisinde_kar")
        self.assertEqual(attribute(-0.05, -0.02), "secim_hatasi")
        rising = series(BENCHMARK_SYMBOL, [100, 101, 102, 103, 104, 105])
        self.assertEqual(classify_regime(rising, "2026-11-27", "2026-12-02"), "boga")

    def test_summary_splits_regime_and_attribution(self) -> None:
        bars = {"AAAA": series("AAAA", [10, 10, 10, 10, 10, 11]),
                BENCHMARK_SYMBOL: series(BENCHMARK_SYMBOL, [100, 101, 102, 103, 104, 105])}
        summary = summarize(evaluate_ledger([entry()], bars, horizons=(5,)), pending=2)
        week = summary["horizons"]["5"]
        self.assertEqual(week["count"], 1)
        self.assertEqual(week["attribution"], {"basarili": 1})
        self.assertIn("boga", week["by_regime"])
        self.assertEqual(summary["pending_entries"], 2)
        self.assertIn("stop", summary["execution"])


class TrainingNeedTests(unittest.TestCase):
    def outcomes(self, excess: list[float]) -> list:
        result = []
        for index, value in enumerate(excess):
            day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            bars = {"AAAA": series("AAAA", [10, 10, 10, 10, 10, 10 * (1 + value)], date.fromisoformat(day)),
                    BENCHMARK_SYMBOL: series(BENCHMARK_SYMBOL, [100] * 6, date.fromisoformat(day))}
            item = entry(entry_id=f"{day}:dengeli:AAAA", published_at=f"{day}T19:45+03:00", close_day=day)
            result.extend(evaluate_entry(item, bars, horizons=(5,), round_trip_cost=0.0))
        return result

    def test_no_policy_means_no_decision(self) -> None:
        assessment = assess([], self.outcomes([-0.1] * 10), None)
        self.assertEqual(assessment.status, "esik_tanimsiz")
        self.assertFalse(assessment.needed)

    def test_single_bad_window_and_calendar_rules_are_rejected(self) -> None:
        base = {"horizon": 5, "evaluated_method_version": METHOD_VERSION}
        with self.assertRaises(PolicyError):
            validate_policy({**base, "degradation": {"window_size": 5, "consecutive_windows": 1, "max_mean_excess": -0.01}})
        with self.assertRaises(PolicyError):
            validate_policy({**base, "calendar_days": 30})

    def test_persistent_relative_degradation_triggers_need(self) -> None:
        policy = {"horizon": 5, "evaluated_method_version": METHOD_VERSION,
                  "degradation": {"window_size": 3, "consecutive_windows": 2, "max_mean_excess": -0.02}}
        healthy = assess([], self.outcomes([0.01] * 3 + [-0.05] * 3), policy)
        self.assertEqual(healthy.status, "gerekli_degil")
        degraded = assess([], self.outcomes([0.01] * 3 + [-0.05] * 6), policy)
        self.assertTrue(degraded.needed)
        self.assertEqual([reason.code for reason in degraded.reasons], ["kalici_goreli_bozulma"])

    def test_method_change_is_a_reason(self) -> None:
        assessment = assess([], [], {"horizon": 5, "evaluated_method_version": "eski"})
        self.assertEqual([reason.code for reason in assessment.reasons], ["yontem_uyumsuzlugu"])


class NoticeTests(unittest.TestCase):
    def test_notice_goes_once_per_reason_and_never_starts_training(self) -> None:
        assessment = assess([], [], {"horizon": 5, "evaluated_method_version": "eski"})
        sent: list[str] = []
        with TemporaryDirectory() as directory:
            self.assertEqual(notify_if_needed(Path(directory), assessment, send=False, sender=sent.append), "would_notify")
            self.assertEqual(sent, [])
            self.assertEqual(notify_if_needed(Path(directory), assessment, send=True, sender=sent.append), "notified")
            self.assertEqual(notify_if_needed(Path(directory), assessment, send=True, sender=sent.append), "already_notified")
            self.assertEqual(len(sent), 1)
            self.assertIn("Eğitim başlatılmadı", sent[0])
            stored = (Path(directory) / "training_notices.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("chat", stored)
        self.assertIn("Gerekçe:", render_notice(assessment))

    def test_delivery_error_does_not_leak_token(self) -> None:
        class FailingClient:
            def post_json(self, url: str, body: dict) -> dict:
                raise RuntimeError(f"HTTP 401 while fetching {url}")

        from unittest.mock import patch
        placeholder = "example-placeholder-value"
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": placeholder, "TELEGRAM_CHAT_ID": "1"}):
            with self.assertRaises(RuntimeError) as raised:
                send_admin_message("deneme", client=FailingClient())
        self.assertNotIn(placeholder, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
