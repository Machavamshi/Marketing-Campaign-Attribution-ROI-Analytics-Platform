import csv
import json
import sqlite3
from pathlib import Path

from flask import current_app, g

from generate import TABLE_COLUMNS


IMPORT_ORDER = [
    "channels", "audiences", "creatives", "campaigns", "campaign_events", "contacts", "contact_audiences",
    "touchpoints", "web_sessions", "leads", "lead_events", "opportunities",
    "opportunity_events", "orders", "cost_records", "attribution_results", "campaign_metrics",
]


def connect_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_database(current_app.config["DATABASE"])
    return g.db


def close_db(error: Exception | None) -> None:
    if error is not None:
        current_app.logger.warning("Closing database connection after request error: %s", type(error).__name__)
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)


def initialize_database() -> None:
    database = Path(current_app.config["DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)
    dataset_dir = Path(current_app.config["DATASET_DIR"])
    seed_file = dataset_dir / "channels.csv"
    if not seed_file.is_file():
        raise FileNotFoundError(
            f"Dataset is missing: {seed_file}. Generate it with "
            "'python -m data_generator.generate_all --scale starter'."
        )

    connection = connect_database(database)
    try:
        has_schema = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaigns'"
        ).fetchone()
        if has_schema:
            metric_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(campaign_metrics)")
            }
            if "spend_usd" in metric_columns and "spend_base_currency" not in metric_columns:
                raise RuntimeError(
                    "This database uses the legacy USD metric schema. It was preserved without conversion. "
                    "Set DATABASE_PATH to a new SQLite file to initialize the current INR dataset."
                )
            has_campaign_events = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_events'"
            ).fetchone()
            if not has_campaign_events:
                connection.execute(
                    """CREATE TABLE campaign_events (
                        campaign_event_id TEXT NOT NULL PRIMARY KEY,
                        campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                        event_type TEXT NOT NULL CHECK (event_type IN ('campaign_created','campaign_revised')),
                        occurred_at TEXT NOT NULL,
                        details_json TEXT NOT NULL
                    )"""
                )
                with connection:
                    campaigns = connection.execute("SELECT * FROM campaigns").fetchall()
                    for index, row in enumerate(campaigns, 1):
                        snapshot = dict(row)
                        connection.execute(
                            "INSERT INTO campaign_events VALUES (?,?,?,?,?)",
                            (
                                f"CME-MIGRATION-{index:09d}",
                                row["campaign_id"],
                                "campaign_created",
                                f"{row['start_date']}T00:00:00Z",
                                json.dumps({"after": snapshot}, sort_keys=True),
                            ),
                        )
            return
        connection.executescript((Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8"))
        with connection:
            for table in IMPORT_ORDER:
                csv_path = dataset_dir / f"{table}.csv"
                if not csv_path.is_file():
                    raise FileNotFoundError(f"Dataset table is missing: {csv_path}")
                with csv_path.open("r", newline="", encoding="utf-8") as source:
                    reader = csv.DictReader(source)
                    if reader.fieldnames != TABLE_COLUMNS[table]:
                        raise ValueError(f"Unexpected columns in {csv_path.name}")
                    columns = TABLE_COLUMNS[table]
                    sql = (
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})"
                    )
                    connection.executemany(
                        sql,
                        ([row[column] or None for column in columns] for row in reader),
                    )
    except Exception:
        connection.close()
        if database.exists():
            database.unlink()
        raise
    finally:
        if connection:
            connection.close()


def dataframe(sql: str, parameters: tuple = ()):
    import pandas as pd

    return pd.read_sql_query(sql, get_db(), params=parameters)
