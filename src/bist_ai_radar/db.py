from __future__ import annotations

import sqlite3
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import database_backend, load_settings, sqlite_path
from .database_backend import PostgresConnection

_POSTGRES_INIT_LOCK_ID = 7_223_202_607
_POSTGRES_INIT_LOCK = threading.Lock()
_INITIALIZED_POSTGRES_URLS: set[str] = set()
_RISK_OBSERVATION_MIGRATION = "20260723_candidate_risk_observations_backfill"
_OUTCOME_ATTRIBUTION_MIGRATION = "20260802_outcome_attribution"

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_bars (
    symbol TEXT NOT NULL,
    day TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    raw_open REAL,
    raw_high REAL,
    raw_low REAL,
    raw_close REAL,
    source TEXT NOT NULL DEFAULT '',
    fetched_at TEXT,
    PRIMARY KEY (symbol, day)
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    published_at TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    disclosure_index INTEGER,
    source_url TEXT NOT NULL DEFAULT '',
    sentiment_score REAL,
    importance_score REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_items_unique
ON news_items (symbol, published_at, source, title);

CREATE TABLE IF NOT EXISTS company_research_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    published_at TEXT NOT NULL,
    disclosure_index INTEGER,
    value_text TEXT NOT NULL,
    numeric_value REAL,
    unit TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    UNIQUE(symbol, fact_type, published_at, value_text)
);

CREATE INDEX IF NOT EXISTS idx_company_research_facts_symbol
ON company_research_facts (symbol, published_at);

CREATE TABLE IF NOT EXISTS research_fact_processing (
    news_item_id INTEGER PRIMARY KEY,
    processed_at TEXT NOT NULL,
    extracted_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(news_item_id) REFERENCES news_items(id)
);

CREATE TABLE IF NOT EXISTS event_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    sector TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_score REAL NOT NULL,
    forward_return_5d REAL NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    score REAL NOT NULL,
    probability REAL NOT NULL,
    expected_return_pct REAL NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    horizon_days INTEGER NOT NULL,
    capital_at_risk_pct REAL NOT NULL DEFAULT 1.0,
    position_size_pct REAL NOT NULL DEFAULT 10.0,
    risk_reward REAL NOT NULL DEFAULT 1.0,
    action TEXT NOT NULL DEFAULT 'IZLE',
    execution_cost_pct REAL NOT NULL DEFAULT 0.60
);

CREATE INDEX IF NOT EXISTS idx_generated_signals_symbol_time
ON generated_signals (symbol, generated_at);

CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    signal_at TEXT NOT NULL,
    planned_entry REAL NOT NULL,
    entry_price REAL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    horizon_sessions INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    return_rate REAL,
    cost_rate REAL NOT NULL DEFAULT 0.006,
    max_drawdown_rate REAL NOT NULL DEFAULT 0,
    max_gain_rate REAL NOT NULL DEFAULT 0,
    close_reason TEXT NOT NULL DEFAULT '',
    counterfactual_return_rate REAL,
    benchmark_return REAL,
    sector_return REAL,
    excess_benchmark_return REAL,
    excess_sector_return REAL,
    market_regime TEXT NOT NULL DEFAULT '',
    outcome_attribution TEXT NOT NULL DEFAULT '',
    evaluated_at TEXT,
    FOREIGN KEY(signal_id) REFERENCES generated_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_positions_status
ON paper_positions (status, symbol);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_positions_open_symbol
ON paper_positions (symbol)
WHERE status IN ('PENDING', 'OPEN');

CREATE TABLE IF NOT EXISTS model_feedback (
    paper_position_id INTEGER PRIMARY KEY,
    signal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    signal_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    return_rate REAL,
    predicted_probability REAL NOT NULL,
    signal_score REAL NOT NULL,
    error_type TEXT NOT NULL,
    benchmark_return REAL,
    sector_return REAL,
    excess_benchmark_return REAL,
    excess_sector_return REAL,
    market_regime TEXT NOT NULL DEFAULT '',
    outcome_attribution TEXT NOT NULL DEFAULT '',
    eligible_for_learning INTEGER NOT NULL,
    synced_at TEXT NOT NULL,
    FOREIGN KEY(paper_position_id) REFERENCES paper_positions(id),
    FOREIGN KEY(signal_id) REFERENCES generated_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_model_feedback_learning
ON model_feedback (eligible_for_learning, signal_at);

CREATE TABLE IF NOT EXISTS candidate_observations (
    symbol TEXT NOT NULL,
    observed_day TEXT NOT NULL,
    numeric_score REAL NOT NULL,
    numeric_reason TEXT NOT NULL,
    ml_probability REAL,
    turnover REAL NOT NULL,
    selected INTEGER NOT NULL,
    recommended INTEGER NOT NULL DEFAULT 0,
    signal_score REAL,
    rejection_reason TEXT NOT NULL,
    return_5d REAL,
    excess_5d REAL,
    missed_5d INTEGER,
    return_21d REAL,
    excess_21d REAL,
    missed_21d INTEGER,
    return_252d REAL,
    excess_252d REAL,
    missed_252d INTEGER,
    risk_flag INTEGER NOT NULL DEFAULT 0,
    risk_horizon TEXT,
    risk_notes TEXT NOT NULL DEFAULT '',
    risk_score REAL,
    risk_success_5d INTEGER,
    risk_success_21d INTEGER,
    risk_success_252d INTEGER,
    risk_limit_rejected INTEGER NOT NULL DEFAULT 0,
    risk_limit_reason TEXT NOT NULL DEFAULT '',
    evaluated_at TEXT,
    PRIMARY KEY(symbol, observed_day)
);

CREATE INDEX IF NOT EXISTS idx_candidate_observations_missed
ON candidate_observations (missed_5d, missed_21d, observed_day);

CREATE TABLE IF NOT EXISTS candidate_risk_observations (
    symbol TEXT NOT NULL,
    observed_day TEXT NOT NULL,
    horizon TEXT NOT NULL,
    risk_notes TEXT NOT NULL,
    risk_score REAL NOT NULL,
    ranking_excess REAL,
    return_rate REAL,
    excess_return REAL,
    success INTEGER,
    evaluated_at TEXT,
    PRIMARY KEY (symbol, observed_day, horizon)
);

CREATE INDEX IF NOT EXISTS idx_candidate_risk_observations_pending
ON candidate_risk_observations (horizon, evaluated_at, observed_day);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage_snapshots (
    snapshot_day TEXT PRIMARY KEY,
    active_companies INTEGER NOT NULL,
    price_symbols INTEGER NOT NULL,
    news_symbols INTEGER NOT NULL,
    current_financial_symbols INTEGER NOT NULL,
    annual_history_symbols INTEGER NOT NULL,
    quarterly_history_symbols INTEGER NOT NULL,
    research_fact_symbols INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shadow_evaluation_runs (
    run_day TEXT PRIMARY KEY,
    observation_count INTEGER NOT NULL,
    matured_5d INTEGER NOT NULL,
    win_rate_5d REAL,
    average_excess_5d REAL,
    matured_21d INTEGER NOT NULL,
    win_rate_21d REAL,
    average_excess_21d REAL,
    matured_252d INTEGER NOT NULL,
    win_rate_252d REAL,
    average_excess_252d REAL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
    alert_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_watch_subscriptions (
    chat_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_symbol_watch_subscriptions_symbol
ON symbol_watch_subscriptions (symbol);

CREATE TABLE IF NOT EXISTS personal_portfolio_positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    average_cost REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_signal_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(chat_id, symbol, verdict, created_at)
);

CREATE TABLE IF NOT EXISTS momentum_paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    started_month TEXT NOT NULL,
    signal_at TEXT NOT NULL,
    momentum_score REAL NOT NULL,
    average_turnover_tl REAL NOT NULL,
    planned_entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    horizon_sessions INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    opened_at TEXT,
    entry_price REAL,
    closed_at TEXT,
    exit_price REAL,
    return_rate REAL,
    max_drawdown_rate REAL,
    max_gain_rate REAL,
    close_reason TEXT,
    evaluated_at TEXT,
    UNIQUE(symbol, started_month)
);

CREATE INDEX IF NOT EXISTS idx_momentum_paper_positions_status
ON momentum_paper_positions (status, signal_at);

CREATE TABLE IF NOT EXISTS periodic_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    horizon TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    confidence REAL NOT NULL,
    expected_high_return_pct REAL NOT NULL,
    UNIQUE(batch_id, horizon, symbol)
);

CREATE INDEX IF NOT EXISTS idx_periodic_recommendations_horizon_batch
ON periodic_recommendations (horizon, batch_id);

CREATE TABLE IF NOT EXISTS periodic_signal_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    horizon TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    setup_type TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    planned_entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    horizon_sessions INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    entry_price REAL,
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    return_rate REAL,
    close_reason TEXT NOT NULL DEFAULT '',
    evaluated_at TEXT,
    notified_at TEXT,
    UNIQUE(batch_id, horizon, symbol)
);

CREATE INDEX IF NOT EXISTS idx_periodic_signal_positions_status
ON periodic_signal_positions (status, horizon, created_at);

CREATE TABLE IF NOT EXISTS baby_company_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    discovery_score REAL NOT NULL,
    growth_rate REAL NOT NULL,
    approximate_market_cap_tl REAL NOT NULL,
    reason TEXT NOT NULL,
    catalyst TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    last_seen_at TEXT,
    last_price REAL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_baby_company_positions_status
ON baby_company_positions (status, opened_at);

CREATE TABLE IF NOT EXISTS baby_company_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    alert_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    notified_at TEXT,
    UNIQUE(position_id, alert_kind),
    FOREIGN KEY(position_id) REFERENCES baby_company_positions(id)
);

CREATE INDEX IF NOT EXISTS idx_baby_company_alerts_pending
ON baby_company_alerts (notified_at, created_at);

CREATE TABLE IF NOT EXISTS weekly_technical_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    priority_rank INTEGER NOT NULL,
    technical_score REAL NOT NULL,
    validation_win_rate REAL NOT NULL,
    validation_trades INTEGER NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    horizon_sessions INTEGER NOT NULL DEFAULT 5,
    status TEXT NOT NULL DEFAULT 'PENDING',
    entry_price REAL,
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    return_rate REAL,
    close_reason TEXT NOT NULL DEFAULT '',
    evaluated_at TEXT,
    notified_at TEXT,
    UNIQUE(week_key, symbol)
);

CREATE INDEX IF NOT EXISTS idx_weekly_technical_positions_status
ON weekly_technical_positions (status, week_key);

CREATE TABLE IF NOT EXISTS telegram_delivery_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    message_preview TEXT NOT NULL,
    error TEXT NOT NULL,
    attempts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_delivery_failures_occurred
ON telegram_delivery_failures (occurred_at);

CREATE TABLE IF NOT EXISTS telegram_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_telegram_outbox_due
ON telegram_outbox (status, next_attempt_at);

CREATE TABLE IF NOT EXISTS external_source_health (
    source TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_source_health (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    blocked_until TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, symbol)
);

CREATE INDEX IF NOT EXISTS idx_symbol_source_health_blocked
ON symbol_source_health (source, blocked_until);

CREATE TABLE IF NOT EXISTS sync_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    currency_scale REAL NOT NULL,
    current_assets REAL,
    total_assets REAL,
    current_liabilities REAL,
    total_liabilities REAL,
    equity REAL,
    paid_capital REAL,
    revenue REAL,
    gross_profit REAL,
    operating_profit REAL,
    net_income REAL,
    operating_cash_flow REAL,
    capital_expenditures REAL,
    cash_and_equivalents REAL,
    dividends_paid REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, period)
);

CREATE TABLE IF NOT EXISTS financial_snapshot_versions (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    disclosure_index INTEGER NOT NULL,
    published_at TEXT NOT NULL,
    currency_scale REAL NOT NULL,
    current_assets REAL,
    total_assets REAL,
    current_liabilities REAL,
    total_liabilities REAL,
    equity REAL,
    paid_capital REAL,
    revenue REAL,
    gross_profit REAL,
    operating_profit REAL,
    net_income REAL,
    operating_cash_flow REAL,
    capital_expenditures REAL,
    cash_and_equivalents REAL,
    dividends_paid REAL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, period, disclosure_index)
);

CREATE INDEX IF NOT EXISTS idx_financial_versions_asof
ON financial_snapshot_versions (symbol, published_at, period);

CREATE TABLE IF NOT EXISTS company_universe (
    symbol TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    city TEXT NOT NULL,
    permalink TEXT NOT NULL,
    sector TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    first_trade_day TEXT,
    last_trade_day TEXT,
    source TEXT NOT NULL DEFAULT 'KAP',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS macro_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT NOT NULL,
    UNIQUE(source, published_at, title)
);

CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator_key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[object]:
    settings = load_settings()
    backend = database_backend(settings.database_url)
    if backend == "postgresql":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "PostgreSQL icin psycopg eksik. pip install -e '.[postgres]' calistir."
            ) from error
        raw_connection = psycopg.connect(settings.database_url, row_factory=dict_row)
        connection = PostgresConnection(raw_connection)
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()
        return
    path = Path(sqlite_path(settings.database_url))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def _run_data_migrations(connection: object) -> None:
    risk_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        (_RISK_OBSERVATION_MIGRATION,),
    ).fetchone()
    if risk_applied is None:
        connection.execute(
            """
            INSERT INTO candidate_risk_observations (
                symbol, observed_day, horizon, risk_notes, risk_score, ranking_excess
            )
            SELECT symbol, observed_day, risk_horizon, risk_notes,
                   COALESCE(risk_score, numeric_score), ml_probability
            FROM candidate_observations
            WHERE risk_flag = 1 AND risk_horizon IN ('AYLIK', 'YILLIK')
            ON CONFLICT(symbol, observed_day, horizon) DO NOTHING
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
            (_RISK_OBSERVATION_MIGRATION,),
        )
    attribution_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        (_OUTCOME_ATTRIBUTION_MIGRATION,),
    ).fetchone()
    if attribution_applied is not None:
        return
    migrations = {
        "paper_positions": {
            "counterfactual_return_rate": "REAL",
            "benchmark_return": "REAL",
            "sector_return": "REAL",
            "excess_benchmark_return": "REAL",
            "excess_sector_return": "REAL",
            "market_regime": "TEXT NOT NULL DEFAULT ''",
            "outcome_attribution": "TEXT NOT NULL DEFAULT ''",
        },
        "model_feedback": {
            "benchmark_return": "REAL",
            "sector_return": "REAL",
            "excess_benchmark_return": "REAL",
            "excess_sector_return": "REAL",
            "market_regime": "TEXT NOT NULL DEFAULT ''",
            "outcome_attribution": "TEXT NOT NULL DEFAULT ''",
        },
    }
    for table, columns in migrations.items():
        existing = _table_columns(connection, table)
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
    connection.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
        (_OUTCOME_ATTRIBUTION_MIGRATION,),
    )


def _table_columns(connection: object, table: str) -> set[str]:
    if getattr(connection, "backend", "sqlite") == "postgresql":
        return {
            str(row["name"])
            for row in connection.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = ?
                """,
                (table,),
            ).fetchall()
        }
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _init_postgres(database_url: str) -> None:
    if database_url in _INITIALIZED_POSTGRES_URLS:
        return
    with _POSTGRES_INIT_LOCK:
        if database_url in _INITIALIZED_POSTGRES_URLS:
            return
        with connect() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(?)",
                (_POSTGRES_INIT_LOCK_ID,),
            )
            connection.executescript(SCHEMA)
            _run_data_migrations(connection)
        _INITIALIZED_POSTGRES_URLS.add(database_url)


def init_db() -> None:
    settings = load_settings()
    if database_backend(settings.database_url) == "postgresql":
        _init_postgres(settings.database_url)
        return
    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.executescript(SCHEMA)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(company_universe)").fetchall()
        }
        if "sector" not in columns:
            connection.execute(
                "ALTER TABLE company_universe ADD COLUMN sector TEXT NOT NULL DEFAULT ''"
            )
        if "is_active" not in columns:
            connection.execute(
                "ALTER TABLE company_universe ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
        if "first_trade_day" not in columns:
            connection.execute(
                "ALTER TABLE company_universe ADD COLUMN first_trade_day TEXT"
            )
        if "last_trade_day" not in columns:
            connection.execute(
                "ALTER TABLE company_universe ADD COLUMN last_trade_day TEXT"
            )
        if "source" not in columns:
            connection.execute(
                "ALTER TABLE company_universe ADD COLUMN source TEXT NOT NULL DEFAULT 'KAP'"
            )
        price_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(price_bars)").fetchall()
        }
        for column in ("raw_open", "raw_high", "raw_low", "raw_close"):
            if column not in price_columns:
                connection.execute(f"ALTER TABLE price_bars ADD COLUMN {column} REAL")
        if "source" not in price_columns:
            connection.execute(
                "ALTER TABLE price_bars ADD COLUMN source TEXT NOT NULL DEFAULT ''"
            )
        if "fetched_at" not in price_columns:
            connection.execute("ALTER TABLE price_bars ADD COLUMN fetched_at TEXT")
        news_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(news_items)").fetchall()
        }
        if "disclosure_index" not in news_columns:
            connection.execute("ALTER TABLE news_items ADD COLUMN disclosure_index INTEGER")
        if "source_url" not in news_columns:
            connection.execute(
                "ALTER TABLE news_items ADD COLUMN source_url TEXT NOT NULL DEFAULT ''"
            )
        signal_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(generated_signals)").fetchall()
        }
        signal_migrations = {
            "capital_at_risk_pct": (
                "ALTER TABLE generated_signals "
                "ADD COLUMN capital_at_risk_pct REAL NOT NULL DEFAULT 1.0"
            ),
            "position_size_pct": (
                "ALTER TABLE generated_signals "
                "ADD COLUMN position_size_pct REAL NOT NULL DEFAULT 10.0"
            ),
            "risk_reward": (
                "ALTER TABLE generated_signals "
                "ADD COLUMN risk_reward REAL NOT NULL DEFAULT 1.0"
            ),
            "action": (
                "ALTER TABLE generated_signals "
                "ADD COLUMN action TEXT NOT NULL DEFAULT 'IZLE'"
            ),
            "execution_cost_pct": (
                "ALTER TABLE generated_signals "
                "ADD COLUMN execution_cost_pct REAL NOT NULL DEFAULT 0.60"
            ),
        }
        for column, statement in signal_migrations.items():
            if column not in signal_columns:
                connection.execute(statement)
        paper_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(paper_positions)").fetchall()
        }
        if "cost_rate" not in paper_columns:
            connection.execute(
                """
                ALTER TABLE paper_positions
                ADD COLUMN cost_rate REAL NOT NULL DEFAULT 0.006
                """
            )
            connection.execute(
                """
                UPDATE paper_positions
                SET return_rate = return_rate - 0.006
                WHERE return_rate IS NOT NULL
                  AND status IN ('TARGET', 'STOP', 'EXPIRED')
                """
            )
        candidate_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(candidate_observations)"
            ).fetchall()
        }
        candidate_migrations = {
            "return_252d": "ALTER TABLE candidate_observations ADD COLUMN return_252d REAL",
            "excess_252d": "ALTER TABLE candidate_observations ADD COLUMN excess_252d REAL",
            "missed_252d": "ALTER TABLE candidate_observations ADD COLUMN missed_252d INTEGER",
            "risk_flag": (
                "ALTER TABLE candidate_observations "
                "ADD COLUMN risk_flag INTEGER NOT NULL DEFAULT 0"
            ),
            "risk_horizon": "ALTER TABLE candidate_observations ADD COLUMN risk_horizon TEXT",
            "risk_notes": (
                "ALTER TABLE candidate_observations "
                "ADD COLUMN risk_notes TEXT NOT NULL DEFAULT ''"
            ),
            "risk_score": "ALTER TABLE candidate_observations ADD COLUMN risk_score REAL",
            "risk_success_5d": (
                "ALTER TABLE candidate_observations ADD COLUMN risk_success_5d INTEGER"
            ),
            "risk_success_21d": (
                "ALTER TABLE candidate_observations ADD COLUMN risk_success_21d INTEGER"
            ),
            "risk_success_252d": (
                "ALTER TABLE candidate_observations ADD COLUMN risk_success_252d INTEGER"
            ),
            "risk_limit_rejected": (
                "ALTER TABLE candidate_observations "
                "ADD COLUMN risk_limit_rejected INTEGER NOT NULL DEFAULT 0"
            ),
            "risk_limit_reason": (
                "ALTER TABLE candidate_observations "
                "ADD COLUMN risk_limit_reason TEXT NOT NULL DEFAULT ''"
            ),
        }
        for column, statement in candidate_migrations.items():
            if column not in candidate_columns:
                connection.execute(statement)
        for table in ("financial_snapshots", "financial_snapshot_versions"):
            financial_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column in (
                "operating_cash_flow",
                "capital_expenditures",
                "cash_and_equivalents",
                "dividends_paid",
            ):
                if column not in financial_columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} REAL")
        _run_data_migrations(connection)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "init"
    if command != "init":
        raise SystemExit("Usage: python -m bist_ai_radar.db init")
    init_db()
    print("Database initialized.")


if __name__ == "__main__":
    main()
