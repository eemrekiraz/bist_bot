from __future__ import annotations

import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def check_cache(path: Path) -> None:
    sensitive = {"chat_id", "user_id", "telegram_chat_id", "token", "password", "secret"}
    token = re.compile(r"\b\d{6,16}:[A-Za-z0-9_-]{30,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            names = {row[1].lower() for row in columns}
            if sensitive & names and connection.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone():
                raise ValueError("Cache contains populated user or credential columns; refusing to share it.")
            for row in connection.execute(f"SELECT * FROM {quoted}"):
                if any(isinstance(value, str) and token.search(value) for value in row):
                    raise ValueError("Cache contains a possible credential; refusing to share it.")
    print("Public market cache checked; no populated user identity columns or token patterns found.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check_public_cache.py PATH_TO_PUBLIC_CACHE")
    check_cache(Path(sys.argv[1]))
