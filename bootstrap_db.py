"""Create sfr.db from CSV if missing (run once)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "sfr.db"
CSV_CANDIDATES = [
    HERE / "sfr_report.csv",
    HERE.parent / "proj" / "sfr_report.csv",
]


def bootstrap(db_path: str | None = None) -> str:
    """Create sfr.db from CSV; optionally specify a custom db_path."""
    if db_path is None:
        db_path = DB_PATH
    else:
        db_path = Path(db_path)

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            n = conn.execute("SELECT COUNT(*) FROM sfr_report").fetchone()[0]
            if n > 0:
                return str(db_path)
        finally:
            conn.close()

    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if not csv_path:
        raise FileNotFoundError(
            "No sfr.db and no sfr_report.csv found. Copy sfr_report.csv into the chat folder."
        )

    df = pd.read_csv(csv_path)
    conn = sqlite3.connect(str(db_path))
    df.to_sql("sfr_report", conn, if_exists="replace", index=False)
    conn.close()
    return str(db_path)


if __name__ == "__main__":
    path = bootstrap()
    print(f"Database ready: {path}")
