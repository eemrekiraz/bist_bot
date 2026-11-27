from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bist_ai_radar.db import connect, init_db


class DatabaseConnectionTests(unittest.TestCase):
    def test_commits_and_closes_connection_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "radar.sqlite3"
            settings = SimpleNamespace(database_url=f"sqlite:///{database_path.as_posix()}")
            with patch("bist_ai_radar.db.load_settings", return_value=settings):
                with connect() as connection:
                    connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
                    connection.execute("INSERT INTO records (value) VALUES ('saved')")

                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

            restored = sqlite3.connect(database_path)
            try:
                row = restored.execute("SELECT value FROM records").fetchone()
            finally:
                restored.close()
            self.assertEqual(row[0], "saved")

    def test_rolls_back_and_closes_connection_after_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "radar.sqlite3"
            settings = SimpleNamespace(database_url=f"sqlite:///{database_path.as_posix()}")
            with patch("bist_ai_radar.db.load_settings", return_value=settings):
                with connect() as setup:
                    setup.execute("CREATE TABLE records (value TEXT NOT NULL)")
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    with connect() as connection:
                        connection.execute("INSERT INTO records (value) VALUES ('discarded')")
                        raise RuntimeError("stop")

                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

            restored = sqlite3.connect(database_path)
            try:
                rows = restored.execute("SELECT value FROM records").fetchall()
            finally:
                restored.close()
            self.assertEqual(rows, [])

    def test_candidate_risk_backfill_runs_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "radar.sqlite3"
            settings = SimpleNamespace(database_url=f"sqlite:///{database_path.as_posix()}")
            with patch("bist_ai_radar.db.load_settings", return_value=settings):
                init_db()
                with connect() as connection:
                    connection.execute(
                        "DELETE FROM schema_migrations WHERE name = ?",
                        ("20260723_candidate_risk_observations_backfill",),
                    )
                    connection.execute(
                        """
                        INSERT INTO candidate_observations (
                            symbol, observed_day, numeric_score, numeric_reason,
                            turnover, selected, recommended, rejection_reason,
                            risk_flag, risk_horizon, risk_notes, risk_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "THYAO",
                            "2026-07-22",
                            71.0,
                            "test",
                            0.0,
                            0,
                            0,
                            "RISK_FILTER",
                            1,
                            "AYLIK",
                            "risk",
                            71.0,
                        ),
                    )

                init_db()
                init_db()
                with connect() as connection:
                    risk_count = connection.execute(
                        "SELECT COUNT(*) AS count FROM candidate_risk_observations"
                    ).fetchone()["count"]
                    migration_count = connection.execute(
                        "SELECT COUNT(*) AS count FROM schema_migrations WHERE name = ?",
                        ("20260723_candidate_risk_observations_backfill",),
                    ).fetchone()["count"]

            self.assertEqual(risk_count, 1)
            self.assertEqual(migration_count, 1)


if __name__ == "__main__":
    unittest.main()
