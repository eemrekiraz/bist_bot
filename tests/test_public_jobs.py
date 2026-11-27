from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bist_ai_radar import public_jobs
from bist_ai_radar.db import connect, init_db
from bist_ai_radar.models import CompanyProfile
from bist_ai_radar.repositories import MarketRepository


class PublicJobsTests(unittest.TestCase):
    def test_public_runner_does_not_import_training_or_private_bot(self) -> None:
        for module in ("bist_ai_radar.scheduler", "bist_ai_radar.ml", "bist_ai_radar.bot"):
            self.assertNotIn(module, sys.modules)

    def test_empty_universe_does_not_fetch_financials(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{Path(directory) / 'test.sqlite3'}"}), patch(
            "bist_ai_radar.public_jobs.KapFinancialFeed"
        ) as feed:
            result = public_jobs.financial_universe_scan(batch_size=1)
            self.assertEqual(result.requested, 0)
            feed.assert_not_called()

    def test_empty_financial_result_records_status(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{Path(directory) / 'test.sqlite3'}"}), patch(
            "bist_ai_radar.public_jobs.KapFinancialFeed"
        ) as feed, patch("bist_ai_radar.public_jobs.time.sleep"):
            init_db()
            with connect() as connection:
                MarketRepository(connection).upsert_companies([CompanyProfile("TEST", "Example", "", "", "BILISIM")])
            feed.return_value.read_snapshots.return_value = []
            result = public_jobs.financial_universe_scan(batch_size=1, time_budget_seconds=10)
            self.assertEqual(result.empty, 1)
            with connect() as connection:
                row = connection.execute("SELECT state_value FROM sync_state WHERE state_key = ?", ("financial_universe_status:TEST",)).fetchone()
                self.assertEqual(row["state_value"], "EMPTY")

    def test_unknown_command_does_not_start_a_job(self) -> None:
        with patch.object(sys, "argv", ["public_jobs", "train-model"]):
            with self.assertRaisesRegex(SystemExit, "Use public-cloud-refresh"):
                public_jobs.main()

    def test_benchmark_is_stored_under_its_own_symbol(self) -> None:
        from datetime import date
        from unittest.mock import MagicMock
        from bist_ai_radar.models import PriceBar
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{Path(directory) / 'test.sqlite3'}"}):
            init_db()
            feed = MagicMock()
            feed.read_price_bars.return_value = [
                PriceBar("XU100.IS", date(2026, 11, 26), 1, 1, 1, 1, 0),
                PriceBar("XU100.IS", date(2026, 11, 28), 1, 1, 1, 1, 0),
            ]
            self.assertTrue(public_jobs.refresh_benchmark(feed, date(2026, 11, 27)))
            feed.read_price_bars.assert_called_once_with("XU100.IS", days=400)
            with connect() as connection:
                rows = connection.execute("SELECT symbol, day FROM price_bars").fetchall()
            self.assertEqual([(row["symbol"], row["day"]) for row in rows], [("XU100", "2026-11-26")])
            feed.read_price_bars.side_effect = RuntimeError("offline")
            self.assertFalse(public_jobs.refresh_benchmark(feed, date(2026, 11, 27)))

