from __future__ import annotations

import unittest

from bist_ai_radar.config import database_backend
from bist_ai_radar.database_backend import (
    PostgresCursor,
    _translate_postgres_query,
    _translate_postgres_schema,
)


class FakeCursor:
    rowcount = 2

    def __init__(self) -> None:
        self.rows = iter(({"symbol": "THYAO", "close": 300.0},))

    def __iter__(self):
        return self.rows


class DatabaseBackendTests(unittest.TestCase):
    def test_detects_supported_database_urls(self) -> None:
        self.assertEqual(database_backend("sqlite:///data/radar.sqlite3"), "sqlite")
        self.assertEqual(database_backend("postgresql://user:pass@db/radar"), "postgresql")
        self.assertEqual(database_backend("postgres://user:pass@db/radar"), "postgresql")

    def test_rejects_unknown_database_url(self) -> None:
        with self.assertRaises(ValueError):
            database_backend("mysql://localhost/radar")

    def test_postgres_cursor_supports_name_and_index_access(self) -> None:
        row = next(iter(PostgresCursor(FakeCursor())))

        self.assertEqual(row["symbol"], "THYAO")
        self.assertEqual(row[1], 300.0)

    def test_translates_sqlite_schema_types(self) -> None:
        translated = _translate_postgres_schema(
            "CREATE TABLE sample (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "count INTEGER, ratio REAL)"
        )

        self.assertIn("id BIGSERIAL PRIMARY KEY", translated)
        self.assertIn("count BIGINT", translated)
        self.assertIn("ratio DOUBLE PRECISION", translated)

    def test_escapes_literal_percent_for_psycopg_queries(self) -> None:
        translated = _translate_postgres_query(
            "SELECT * FROM financials WHERE period LIKE '%/12' AND symbol = ?"
        )

        self.assertEqual(
            translated,
            "SELECT * FROM financials WHERE period LIKE '%%/12' AND symbol = %s",
        )


if __name__ == "__main__":
    unittest.main()
