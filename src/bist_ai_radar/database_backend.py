from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any


class CompatRow(dict[str, Any]):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self.cursor.rowcount or 0)

    def __iter__(self) -> Iterator[CompatRow]:
        for row in self.cursor:
            yield CompatRow(row)

    def fetchone(self) -> CompatRow | None:
        row = self.cursor.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self) -> list[CompatRow]:
        return [CompatRow(row) for row in self.cursor.fetchall()]

    def fetchmany(self, size: int = 1000) -> list[CompatRow]:
        return [CompatRow(row) for row in self.cursor.fetchmany(size)]


class PostgresConnection:
    backend = "postgresql"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def execute(self, query: str, params: Iterable[Any] | None = None) -> PostgresCursor:
        cursor = self.connection.execute(_translate_postgres_query(query), params or ())
        return PostgresCursor(cursor)

    def executemany(
        self,
        query: str,
        params: Iterable[Iterable[Any]],
    ) -> PostgresCursor:
        cursor = self.connection.cursor()
        cursor.executemany(_translate_postgres_query(query), params)
        return PostgresCursor(cursor)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.connection.execute(_translate_postgres_schema(statement))

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


def _translate_postgres_query(query: str) -> str:
    translated = query.replace("%", "%%")
    translated = translated.replace("datetime('now')", "CURRENT_TIMESTAMP::text")
    translated = translated.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    translated = translated.replace("?", "%s")
    if "INSERT OR IGNORE INTO" in query.upper() and "ON CONFLICT" not in query.upper():
        translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return translated


def _translate_postgres_schema(statement: str) -> str:
    translated = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        statement,
        flags=re.IGNORECASE,
    )
    translated = re.sub(r"\bINTEGER\b", "BIGINT", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bREAL\b", "DOUBLE PRECISION", translated, flags=re.IGNORECASE)
    return translated.strip()
