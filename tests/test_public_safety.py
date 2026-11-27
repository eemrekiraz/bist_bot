from __future__ import annotations

import importlib.util
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing, redirect_stdout
from io import StringIO


def load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicSafetyTests(unittest.TestCase):
    def test_private_files_are_rejected_and_examples_allowed(self) -> None:
        safety = load_script("check_public_safety")
        for path in (".env", ".env.production", "data/cache.sqlite3", "logs/result.log", "private.pem", ".ssh/id_ed25519"):
            self.assertTrue(safety.forbidden_path(path))
        for path in (".env.example", "src/app.py", "tests/test_public_safety.py", "README.md"):
            self.assertFalse(safety.forbidden_path(path))

    def test_cache_with_private_identity_cannot_be_shared(self) -> None:
        cache = load_script("check_public_cache")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE subscribers (chat_id TEXT)")
                connection.execute("INSERT INTO subscribers VALUES ('test-user')")
                connection.commit()
            with self.assertRaisesRegex(ValueError, "user or credential"):
                cache.check_cache(path)

    def test_market_only_cache_passes(self) -> None:
        cache = load_script("check_public_cache")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE prices (symbol TEXT, close REAL)")
                connection.execute("INSERT INTO prices VALUES ('TEST', 100)")
                connection.commit()
            with redirect_stdout(StringIO()):
                cache.check_cache(path)
