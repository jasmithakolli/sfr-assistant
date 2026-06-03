"""SFR Analytics — uses the same engine as SFR ASSISTANT (chat/testsql.py)."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
ACTIVE_DATASET = "No dataset uploaded"

ROOT = Path(__file__).resolve().parent

from testsql import ask as engine_ask, DB_PATH, classify_query  # noqa: E402
from bootstrap_db import bootstrap  # noqa: E402

app = Flask(__name__, static_folder="static")

QUICK_QUERIES = [
    "show all the ygl failure",
    "Monthly trend of trains detained",
    "Station vs gear type total delay",
    "How many chargeable vs non-chargeable failures",
    "Show me all track circuit failures",
    "Top 10 stations by total delay",
]


def _plotly_from_engine(graph) -> dict | None:
    if graph is None:
        return None
    return json.loads(graph.to_json())


def _table_from_results(results: dict, title: str = "Query Results") -> dict | None:
    columns = results.get("columns") or []
    rows = results.get("rows") or []
    if not columns or not rows:
        return None

    return {
        "title": title,
        "columns": [str(c) for c in columns],
        "rows": [dict(zip([str(c) for c in columns], row)) for row in rows],
        "total": len(rows),
        "showing": len(rows),
    }


def _failure_cards_from_results(results: dict) -> list[dict]:
    columns = [str(c).lower() for c in (results.get("columns") or [])]
    rows = results.get("rows") or []
    if not columns or not rows or len(columns) < 7:
        return []

    cards = []
    for idx, row in enumerate(rows, start=1):
        row_data = dict(zip(columns, row))
        cards.append({
            "index": idx,
            "station": row_data.get("station", "") or row_data.get("station name", ""),
            "gear": row_data.get("gear at fault", "") or row_data.get("gear", ""),
            "sub_gear": row_data.get("sub gear at fault", "") or row_data.get("sub gear", ""),
            "cause": row_data.get("cause of failure", "") or row_data.get("cause", ""),
            "train_detained": row_data.get("train detained", "") or row_data.get("train", ""),
            "duration": row_data.get("dur ation", "") or row_data.get("duration", ""),
            "time": row_data.get("time of occ urrence", "") or row_data.get("time", ""),
            "chargeable": row_data.get("chargeable", "") or row_data.get("chargeable failure", ""),
        })
    return cards


@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/api/kpis")
def kpis():
    bootstrap()
    # Compute KPIs from the SQLite DB for accuracy
    import sqlite3
    import pandas as pd
    from testsql import DB_PATH

    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("SELECT * FROM sfr_report", conn)
        conn.close()
    except Exception:
        df = pd.DataFrame()

    # helpers to find columns by partial match
    def find_col(df, keyword):
        for c in df.columns:
            if keyword.lower() in str(c).lower():
                return c
        return None

    total_failures = int(len(df)) if not df.empty else 0

    dur_col = find_col(df, 'dur')
    try:
        avg_repair_time = round(float(df[dur_col].dropna().astype(float).mean()), 1) if dur_col and not df.empty else None
    except Exception:
        avg_repair_time = None

    station_col = find_col(df, 'station')
    worst_station = None
    try:
        if station_col and dur_col and not df.empty:
            grp = df.groupby(station_col)[dur_col].apply(lambda s: pd.to_numeric(s, errors='coerce').sum()).sort_values(ascending=False)
            worst_station = str(grp.index[0]) if not grp.empty else None
    except Exception:
        worst_station = None

    time_col = find_col(df, 'time')
    peak_month = None
    try:
        if time_col and not df.empty:
            s = df[time_col].astype(str).fillna('')
            # expected format 'DD-MM-YYYY ...'
            months = s.str.slice(6,10) + '-' + s.str.slice(3,5)
            peak = months.value_counts().idxmax() if not months.empty else None
            peak_month = peak
    except Exception:
        peak_month = None

    charge_col = find_col(df, 'charge')
    chargeable_count = None
    non_chargeable_count = None
    try:
        if charge_col and not df.empty:
            vals = df[charge_col].astype(str).str.lower()
            chargeable_count = int((vals == 'yes').sum())
            non_chargeable_count = int((vals == 'no').sum())
    except Exception:
        chargeable_count = None
        non_chargeable_count = None

    train_col = find_col(df, 'train')
    trains_detained_total = 0
    try:
        if train_col and not df.empty:
            vals = df[train_col].astype(str).str.strip().str.lower()
            # count truthy entries that are not 'no' or empty
            trains_detained_total = int(((~vals.isin(['', 'nan', 'none', 'no'])) & vals.notna()).sum())
    except Exception:
        trains_detained_total = 0

    gear_col = find_col(df, 'gear')
    top_gear = None
    try:
        if gear_col and not df.empty:
            top_gear = str(df[gear_col].astype(str).value_counts().idxmax())
    except Exception:
        top_gear = None

    r = engine_ask("how many failures")

    return jsonify({
        "total_failures": total_failures,
        "avg_repair_time": avg_repair_time,
        "worst_station": worst_station or "—",
        "peak_month": peak_month or "—",
        "chargeable_count": chargeable_count or 0,
        "non_chargeable_count": non_chargeable_count or 0,
        "trains_detained_total": trains_detained_total,
        "top_gear": top_gear or "—",
        "dataset": "sfr_report",
        "engine_note": r.get("answer", "")[:80],
    })


@app.get("/api/datasets")
def datasets():
    return jsonify({"active": "sfr_report.csv", "datasets": [{"id": "default", "name": "sfr_report"}]})


@app.post("/api/datasets/select")
def select_dataset():
    return jsonify({"ok": True, "active": "sfr_report"})


@app.post("/api/upload")
def upload():
    # Uploads have been disabled — file ingestion removed per admin request
    return jsonify({"error": "Uploads are disabled in this deployment"}), 404

@app.get("/api/current-dataset")
def current_dataset():
    return jsonify({
        "name": ACTIVE_DATASET
    })

@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    bootstrap()

    # Always delegate to the engine; context-based smart actions removed
    result = engine_ask(message)
    answer = result.get("answer", "")
    chart = _plotly_from_engine(result.get("graph"))
    
    
    # Return EITHER failure_cards OR table, not both (avoid duplicate answers)
    failure_cards = _failure_cards_from_results(result)
    table = None if failure_cards else _table_from_results(result)
    lines = [ln.strip() for ln in answer.split("\n") if ln.strip() and "—" in ln]

    # No suggestions — clean simple results only
    suggestions = []
    return jsonify({
        "title": message[:80],
        "message": answer.split("\n")[0][:200] if answer else "Done",
        "insight": {
            "key_insight": answer,
            "trend": "",
            "recommendation": "",
            "chart_summary": "Chart shown on the right." if chart else "",
            "table": None,
        },
        "chart": chart,
        "table": table,
        "failure_cards": failure_cards,
        "summary_lines": lines,
        "suggestions": suggestions,
        "meta": {
            "query_type": "engine",
            "matched": len(result.get("rows", [])),
            "engine": "chat/testsql.py",
        },
    })


@app.get("/api/export/excel")
def export_excel():
    import io
    import sqlite3
    import pandas as pd
    bootstrap()
    from testsql import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM sfr_report", conn)
    conn.close()
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="sfr_export.xlsx")


@app.get("/api/quick-queries")
def quick_queries():
    return jsonify({"queries": QUICK_QUERIES})


if __name__ == "__main__":
    bootstrap()
    print("\n  SFR Analytics — same engine as SFR ASSISTANT")
    print("  Open: http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000, use_reloader=False)
