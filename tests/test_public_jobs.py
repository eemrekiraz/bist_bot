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
