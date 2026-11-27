from __future__ import annotations

from datetime import datetime, timedelta


def symbol_source_attempt_allowed(
    connection: object,
    source: str,
    symbol: str,
    now: datetime | None = None,
) -> bool:
    row = connection.execute(
        """
        SELECT blocked_until FROM symbol_source_health
        WHERE source = ? AND symbol = ?
        """,
        (source.upper(), symbol.upper()),
    ).fetchone()
    if not row or not row["blocked_until"]:
        return True
    return datetime.fromisoformat(str(row["blocked_until"])) <= (now or datetime.now())


def record_symbol_source_success(
    connection: object,
    source: str,
    symbol: str,
    now: datetime | None = None,
) -> None:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO symbol_source_health (
            source, symbol, last_success_at, last_error, consecutive_failures,
            blocked_until, updated_at
        )
        VALUES (?, ?, ?, '', 0, NULL, ?)
        ON CONFLICT(source, symbol) DO UPDATE SET
            last_success_at = excluded.last_success_at,
            last_error = '',
            consecutive_failures = 0,
            blocked_until = NULL,
            updated_at = excluded.updated_at
        """,
        (source.upper(), symbol.upper(), timestamp, timestamp),
    )


def record_symbol_source_failure(
    connection: object,
    source: str,
    symbol: str,
    error: Exception | str,
    now: datetime | None = None,
) -> datetime:
    current_time = now or datetime.now()
    row = connection.execute(
        """
        SELECT consecutive_failures FROM symbol_source_health
        WHERE source = ? AND symbol = ?
        """,
        (source.upper(), symbol.upper()),
    ).fetchone()
    failures = int(row["consecutive_failures"] or 0) + 1 if row else 1
    message = str(error).replace("\n", " ")[:240]
    if is_permanent_symbol_error(error):
        delay = timedelta(days=7)
    else:
        delay = timedelta(hours=min(24, 2 ** min(failures, 4)))
    blocked_until = current_time + delay
    timestamp = current_time.isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO symbol_source_health (
            source, symbol, last_failure_at, last_error, consecutive_failures,
            blocked_until, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol) DO UPDATE SET
            last_failure_at = excluded.last_failure_at,
            last_error = excluded.last_error,
            consecutive_failures = excluded.consecutive_failures,
            blocked_until = excluded.blocked_until,
            updated_at = excluded.updated_at
        """,
        (
            source.upper(),
            symbol.upper(),
            timestamp,
            message,
            failures,
            blocked_until.isoformat(timespec="seconds"),
            timestamp,
        ),
    )
    return blocked_until


def symbol_source_quarantine_count(
    connection: object,
    source: str,
    now: datetime | None = None,
) -> int:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    row = connection.execute(
        """
        SELECT COUNT(*) AS count FROM symbol_source_health
        WHERE source = ? AND blocked_until > ?
        """,
        (source.upper(), timestamp),
    ).fetchone()
    return int(row["count"] or 0)


def is_permanent_symbol_error(error: Exception | str) -> bool:
    message = str(error).upper()
    return "HTTP 404" in message or "NO YAHOO FINANCE DATA" in message
