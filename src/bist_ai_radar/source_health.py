from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import connect, init_db
from .symbol_source_health import symbol_source_quarantine_count

SOURCES = (
    ("YAHOO", "Yahoo fiyat"),
    ("KAP_NEWS", "KAP bildirim"),
    ("KAP_FINANCIAL", "KAP finansal"),
    ("MACRO_NEWS", "Resmi makro haber"),
)
CRITICAL_FAILURE_COUNT = 3


@dataclass(frozen=True)
class SourceStatus:
    source: str
    label: str
    status: str
    consecutive_failures: int
    last_error: str
    last_success_at: str = ""
    last_failure_at: str = ""


def build_source_health_report() -> str:
    init_db()
    with connect() as connection:
        report = format_source_health(source_statuses(connection))
        quarantined = symbol_source_quarantine_count(connection, "YAHOO")
    return report + f"\nYahoo gecici geri cekilen kod: {quarantined}"


def record_source_attempt(source: str, error: Exception | None = None) -> None:
    init_db()
    with connect() as connection:
        if error is None:
            record_source_success(connection, source)
        else:
            record_source_failure(connection, source, error)


def record_source_success(connection: sqlite3.Connection, source: str) -> None:
    connection.execute(
        """
        INSERT INTO external_source_health (
            source, last_success_at, last_error, consecutive_failures, updated_at
        )
        VALUES (?, datetime('now'), '', 0, datetime('now'))
        ON CONFLICT(source) DO UPDATE SET
            last_success_at = excluded.last_success_at,
            last_error = '',
            consecutive_failures = 0,
            updated_at = excluded.updated_at
        """,
        (source,),
    )


def record_source_failure(
    connection: sqlite3.Connection,
    source: str,
    error: Exception | str,
) -> None:
    connection.execute(
        """
        INSERT INTO external_source_health (
            source, last_failure_at, last_error, consecutive_failures, updated_at
        )
        VALUES (?, datetime('now'), ?, 1, datetime('now'))
        ON CONFLICT(source) DO UPDATE SET
            last_failure_at = excluded.last_failure_at,
            last_error = excluded.last_error,
            consecutive_failures = external_source_health.consecutive_failures + 1,
            updated_at = excluded.updated_at
        """,
        (source, str(error).replace("\n", " ")[:240]),
    )


def source_statuses(connection: sqlite3.Connection) -> tuple[SourceStatus, ...]:
    rows = {
        str(row["source"]): row
        for row in connection.execute(
            """
            SELECT source, consecutive_failures, last_error, last_success_at, last_failure_at
            FROM external_source_health
            """
        ).fetchall()
    }
    statuses: list[SourceStatus] = []
    for source, label in SOURCES:
        row = rows.get(source)
        failures = int(row["consecutive_failures"]) if row else 0
        status = _status_for_failures(failures, row is not None)
        statuses.append(
            SourceStatus(
                source,
                label,
                status,
                failures,
                str(row["last_error"]) if row else "",
                str(row["last_success_at"] or "") if row else "",
                str(row["last_failure_at"] or "") if row else "",
            )
        )
    return tuple(statuses)


def format_source_health(statuses: tuple[SourceStatus, ...]) -> str:
    lines = ["VERI KAYNAK DURUMU"]
    for item in statuses:
        line = (
            f"{item.label}: {item.status} | "
            f"Ardisik hata: {item.consecutive_failures} | "
            f"Son basari: {item.last_success_at or 'Yok'}"
        )
        lines.append(line)
        if item.last_error:
            lines.append(f"- Son hata: {item.last_error}")
    return "\n".join(lines)


def _status_for_failures(failures: int, has_record: bool) -> str:
    if not has_record:
        return "BILINMIYOR"
    if failures >= CRITICAL_FAILURE_COUNT:
        return "KRITIK"
    if failures:
        return "UYARI"
    return "HAZIR"
