# =====================================================
# SFR ASSISTANT — SQLite Query Engine
# =====================================================

import os
import re
import sqlite3
import pandas as pd
import plotly.express as px  # type: ignore
from ollama import chat

from rapidfuzz import process, fuzz

try:
    from sqlalchemy import create_engine, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


def llm_generate_sql(question, columns):
    prompt = f"""
You are a SQLite SQL generator.

Database Table:
sfr_report

Available Columns:
{columns}

Rules:
1. Use ONLY table name sfr_report.
2. Use ONLY the columns listed above.
3. Return ONLY valid SQLite SQL (a SELECT statement).
4. Do not explain.
5. Do not use markdown.
6. Do not invent tables.

Question:
{question}
"""

    response = chat(
        model="llama3",
        messages=[{"role": "user", "content": prompt}],
        timeout=60
    )

    raw = response.get("message", {}).get("content", "") if isinstance(response, dict) else str(response)

    print("\nPROMPT:")
    print(prompt)
    print("\nRAW FROM MODEL:\n", raw)

    # Helpers
    def _strip_markdown(text: str) -> str:
        # remove fenced code blocks and surrounding backticks
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = text.replace('`', '')
        return text.strip()

    def _extract_first_select(text: str) -> str:
        # try to find the first SELECT ... ; block
        m = re.search(r"(SELECT[\s\S]+?;)", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # fallback: find first SELECT to end
        m2 = re.search(r"(SELECT[\s\S]+)", text, flags=re.IGNORECASE)
        return m2.group(1).strip() if m2 else ""

    def _is_safe_sql(sql_text: str) -> bool:
        s = sql_text.lower()
        # must be a SELECT and reference the expected table
        if not s.startswith("select"):
            print("LLM SQL rejected: not a SELECT")
            return False
        if TABLE_NAME.lower() not in s:
            print(f"LLM SQL rejected: does not reference table {TABLE_NAME}")
            return False
        # forbid DDL/DML and sqlite master access
        forbidden = ["drop", "delete", "update", "insert", "attach", "alter", "create", "replace", "pragma", "sqlite_master", "--", "/*", "*/"]
        for token in forbidden:
            if token in s:
                print(f"LLM SQL rejected: contains forbidden token '{token}'")
                return False
        # basic sanity: no unusual identifiers like 'station_code' (common bad LLM hallucination)
        if re.search(r"\b[a-z_]+code\b", s):
            print("LLM SQL rejected: contains '*_code' identifier")
            return False
        return True

    cleaned = _strip_markdown(raw)
    sql_candidate = _extract_first_select(cleaned)

    if not sql_candidate:
        print("LLM produced no SQL. Falling back to internal generator.")
        return None

    # Ensure it ends with semicolon for neatness
    if not sql_candidate.strip().endswith(";"):
        sql_candidate = sql_candidate.strip() + ";"

    if not _is_safe_sql(sql_candidate):
        print("LLM SQL failed safety checks — falling back to internal generator.")
        return None

    print("SQL FROM MODEL (accepted):\n", sql_candidate)
    return sql_candidate

# =====================================================
# DATABASE CONFIG
# =====================================================

DB_PATH    = os.getenv(
    "SFR_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfr.db"),
)

# Normalize DB path: trim quotes, expand env vars/user, absolute path,
# and create the parent directory if missing.
DB_PATH = DB_PATH.strip().strip('"').strip("'")
DB_PATH = os.path.expanduser(os.path.expandvars(DB_PATH))
DB_PATH = os.path.abspath(DB_PATH)
parent_dir = os.path.dirname(DB_PATH)
if parent_dir and not os.path.exists(parent_dir):
    try:
        os.makedirs(parent_dir, exist_ok=True)
    except OSError:
        pass

# =====================================================
# TABLE & COLUMN NAMES  (SQLite — no backtick quoting issues)
# Use double-quotes for column names with spaces
# =====================================================

TABLE_NAME     = "sfr_report"

# Raw column names (as in CSV/DB)
COL_SL              = "SL"
COL_SFR_NO          = "SFRNo"
COL_REPORTED        = "Reported"
COL_CHARGEABLE      = '"Chargeable / Non Chargeable"'
COL_STATION         = '"Station"'
COL_GEAR            = '"Gear at Fault"'
COL_SUB_GEAR        = '"Sub Gear at Fault"'
COL_BRIEF_DESC      = '"Brief Description"'
COL_CAUSE           = '"Cause of Failure"'
COL_SUB_CAUSE       = '"Sub Cause of Failure"'
COL_TRAIN           = '"Train Detained"'
COL_TIME_OCC        = '"Time of Occ urrence"'      # note the space in original
COL_TIME_INFORMED   = '"Time Signal Main In formed"'  # note the space in original
COL_TIME_REACHED    = '"Time Signal Main Reached"'
COL_TIME_RECTIFIED  = '"Time Rectified"'
COL_DURATION        = '"Dur ation"'                # note the space in original

# =====================================================
# KNOWN STATIONS
# =====================================================

KNOWN_STATIONS = [
    "YGL", "KOLR", "MMZ", "TDU", "JOA",
    "BPA", "GT",   "VKB", "JMKT", "PGDP",
    "BN",  "CT",   "KDM", "GNN",  "BGSF",
    "ASAF","SNF",  "DKJ", "PBP"
]

# =====================================================
# MONTH MAP
# =====================================================

MONTH_MAP = {
    "january"  : "01",
    "february" : "02",
    "march"    : "03",
    "april"    : "04",
    "may"      : "05",
    "june"     : "06",
    "july"     : "07",
    "august"   : "08",
    "september": "09",
    "october"  : "10",
    "november" : "11",
    "december" : "12"
}

# =====================================================
# DURATION COLUMN IDENTIFIERS (used in format_answer)
# =====================================================

DURATION_COL_NAMES = {
    "dur ation",
    "duration",
    "avg duration",
    "total duration",
    "avg_duration",
    "total_duration"
}

# =====================================================
# DB CONNECTION
# =====================================================

def get_engine():
    if SQLALCHEMY_AVAILABLE:
        db_url = f"sqlite:///{DB_PATH.replace('\\', '/')}"
        return create_engine(db_url, pool_pre_ping=True)
    return None


def get_default_engine():
    return get_engine()


engine = get_default_engine()


def ensure_database() -> None:
    """Load CSV into SQLite when DB is missing or empty."""
    print(f"Using DB_PATH={DB_PATH}")
    print(f"DB exists: {os.path.exists(DB_PATH)}")

    if not os.path.exists(DB_PATH):
        from bootstrap_db import bootstrap
        bootstrap(DB_PATH)
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        def _has_expected_schema(connection) -> bool:
            expected = {
                "SL",
                "SFRNo",
                "Reported",
                "Chargeable / Non Chargeable",
                "Station",
                "Gear at Fault",
                "Sub Gear at Fault",
                "Brief Description",
                "Cause of Failure",
                "Sub Cause of Failure",
                "Train Detained",
                "Time of Occ urrence",
                "Time Signal Main In formed",
                "Time Signal Main Reached",
                "Time Rectified",
                "Dur ation",
            }
            cols = [row[1] for row in connection.execute("PRAGMA table_info(sfr_report)").fetchall()]
            return expected.issubset(set(cols))

        def _is_header_like(connection) -> bool:
            try:
                cols = [row[1] for row in connection.execute("PRAGMA table_info(sfr_report)").fetchall()]
                row = connection.execute("SELECT * FROM sfr_report LIMIT 1").fetchone()
                if not row:
                    return False
                return all(str(value).strip() == str(col).strip() for value, col in zip(row, cols))
            except Exception:
                return False

        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sfr_report'"
        ).fetchone()[0]
        if n:
            count = conn.execute("SELECT COUNT(*) FROM sfr_report").fetchone()[0]
            schema_ok = _has_expected_schema(conn)
            header_bad = _is_header_like(conn)
            conn.close()
            if count > 0 and schema_ok and not header_bad:
                return
            print("Invalid or corrupted DB detected.")
            conn.close()
            try:
                os.remove(DB_PATH)
                print(f"Removed corrupted DB file: {DB_PATH}")
            except Exception as e:
                print(f"Unable to remove corrupted DB file: {e}")
            from bootstrap_db import bootstrap
            bootstrap(DB_PATH)
            return
        conn.close()
    except sqlite3.OperationalError as e:
        raise sqlite3.OperationalError(
            f"Unable to open SQLite DB at {DB_PATH}: {e}"
        )
    except Exception:
        pass
    from bootstrap_db import bootstrap
    bootstrap(DB_PATH)

# =====================================================
# HELPERS
# =====================================================

def is_duration_col(col_name: str) -> bool:
    return col_name.strip().lower() in DURATION_COL_NAMES


def fmt_val(value, col_name: str) -> str:
    if value is None:
        return "N/A"
    try:
        num = round(float(value), 1)
        return f"{num} mins" if is_duration_col(col_name) else str(num)
    except (ValueError, TypeError):
        return str(value)

# =====================================================
# TYPO FIX
# =====================================================

def fix_typos(question: str) -> str:
    words = question.split()
    fixed = []
    for word in words:
        match = process.extractOne(
            word.upper(),
            KNOWN_STATIONS,
            scorer=fuzz.ratio
        )
        if match and match[1] >= 85:
            fixed.append(match[0])
        else:
            fixed.append(word)
    return " ".join(fixed)

# =====================================================
# DETECT MONTH
# =====================================================

def detect_month(question: str):
    q = question.lower()
    for month, num in MONTH_MAP.items():
        if month in q:
            return num
    return None

# =====================================================
# QUERY CLASSIFIER
# =====================================================

def classify_query(question: str) -> str:
    q = question.lower()

    detained_count_request = (
        "detain" in q
        and any(word in q for word in ["how many", "total", "number", "count"])
    )

    if "how many" in q or detained_count_request:
        return "count_query"

    if any(word in q for word in ["show", "list", "what failed"]):
        return "detail_lookup"

    # Detect 2D breakdowns involving month and another dimension
    month_cross = "month" in q and any(dim in q for dim in ["station", "gear", "cause"])
    heatmap_request = any(word in q for word in ["heatmap", "breakdown", "cross-tab", "cross tab", "crosstab"]) or month_cross

    if heatmap_request:
        if any(word in q for word in ["duration", "delay", "average", "avg", "mean"]):
            return "heatmap_metric"
        return "heatmap_count"

    if any(word in q for word in ["trend", "monthly", "over time", "by month"]):
        return "timeseries_metric"

    if "vs" in q:
        if any(word in q for word in ["duration", "delay", "average"]):
            return "heatmap_metric"
        return "heatmap_count"

    has_metric   = any(word in q for word in ["duration", "delay"])
    has_agg      = any(word in q for word in ["total", "sum", "average", "avg", "mean", "overall", "entire"])
    has_grouping = any(word in q for word in [
        "station", "gear", "cause", "month", "by", "per", "each",
        "top", "highest", "lowest", "most", "least", "longest", "worst"
    ])

    if has_metric and has_agg and not has_grouping:
        return "single_metric"

    if any(word in q for word in ["top", "highest", "lowest", "most", "least", "longest", "worst"]):
        return "ranking_by_metric"

    if has_metric and has_agg and has_grouping:
        return "ranking_by_metric"

    return "detail_lookup"

# =====================================================
# METRIC DETECTION
# =====================================================

def detect_metric(question: str) -> str:
    q = question.lower()
    if "detain" in q:
        return "COUNT(*)"
    if any(word in q for word in ["duration", "delay", "rectification"]):
        return COL_DURATION
    return "COUNT(*)"

# =====================================================
# SQLITE MONTH FILTER
# SQLite uses strftime instead of MySQL's MONTH(STR_TO_DATE(...))
# Date format assumed: 'DD-MM-YYYY HH:MM' based on original code
# =====================================================

def month_filter(month: str) -> str:
    # SQLite strftime needs ISO date format; we parse via substr/replace
    # Stored format: 'DD-MM-YYYY HH:MM'
    # Extract month: chars 4-5 (0-indexed: substr(col, 4, 2))
    return f"substr({COL_TIME_OCC}, 4, 2) = '{month.zfill(2)}'"

# =====================================================
# SQLITE MONTH EXPRESSION (for GROUP BY / SELECT)
# Returns 'YYYY-MM' string for grouping
# =====================================================

def month_expr() -> str:
    # From 'DD-MM-YYYY HH:MM' → 'YYYY-MM'
    # substr(col, 7, 4) = YYYY, substr(col, 4, 2) = MM
    return f"(substr({COL_TIME_OCC}, 7, 4) || '-' || substr({COL_TIME_OCC}, 4, 2))"

# =====================================================
# COUNT QUERY SQL
# =====================================================

def count_query_sql(question: str) -> str:
    q = question.lower()

    if "detain" in q:
        filters = [
            f"{COL_TRAIN} IS NOT NULL",
            f"TRIM(CAST({COL_TRAIN} AS TEXT)) NOT IN ('', 'nan', 'none', 'no', 'No', 'NO')",
        ]

        for station in KNOWN_STATIONS:
            if station.lower() in q:
                filters.append(f"{COL_STATION} LIKE '%{station}%'")

        month = detect_month(question)
        if month:
            filters.append(month_filter(month))

        where = "WHERE " + " AND ".join(filters)
        return f"SELECT COUNT(*) AS total FROM {TABLE_NAME} {where};"

    if "chargeable" in q and "non-chargeable" in q:
        return f"""
        SELECT {COL_CHARGEABLE} AS category,
               COUNT(*) AS total
        FROM   {TABLE_NAME}
        WHERE  {COL_CHARGEABLE} IN ('Yes', 'No')
        GROUP  BY category;
        """

    if "non-chargeable" in q or "non chargeable" in q:
        filters = [f"{COL_CHARGEABLE} = 'No'"]
        month = detect_month(question)
        if month:
            filters.append(month_filter(month))
        where = "WHERE " + " AND ".join(filters)
        return f"SELECT COUNT(*) AS total FROM {TABLE_NAME} {where};"

    if "chargeable" in q:
        filters = [f"{COL_CHARGEABLE} = 'Yes'"]
        month = detect_month(question)
        if month:
            filters.append(month_filter(month))
        where = "WHERE " + " AND ".join(filters)
        return f"SELECT COUNT(*) AS total FROM {TABLE_NAME} {where};"

    filters = []

    if "signal" in q:
        filters.append(f"{COL_GEAR} LIKE '%SIGNAL%'")
    if "track circuit" in q:
        filters.append(f"{COL_GEAR} LIKE '%TRACK%'")

    for station in KNOWN_STATIONS:
        if station.lower() in q:
            filters.append(f"{COL_STATION} LIKE '%{station}%'")

    month = detect_month(question)
    if month:
        filters.append(month_filter(month))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    return f"""
    SELECT COUNT(*) AS total
    FROM   {TABLE_NAME}
    {where};
    """

# =====================================================
# DETAIL LOOKUP SQL
# =====================================================

def detail_lookup_sql(question: str) -> str:
    q = question.lower()
    filters = []

    for station in KNOWN_STATIONS:
        if station.lower() in q:
            filters.append(f"{COL_STATION} LIKE '%{station}%'")

    month = detect_month(question)
    if month:
        filters.append(month_filter(month))

    if "signal" in q:
        filters.append(f"{COL_GEAR} LIKE '%SIGNAL%'")
    if "track circuit" in q:
        filters.append(f"{COL_GEAR} LIKE '%TRACK%'")
    if "cable" in q:
        filters.append(f"{COL_CAUSE} LIKE '%cable%'")

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    return f"""
    SELECT {COL_STATION},
           {COL_GEAR},
           {COL_SUB_GEAR},
           {COL_CAUSE},
           {COL_TRAIN},
           {COL_DURATION},
           {COL_TIME_OCC}
    FROM   {TABLE_NAME}
    {where};
    """

# =====================================================
# DETECT TOP-N LIMIT
# =====================================================

def detect_limit(question: str) -> int:
    match = re.search(r'\btop\s+(\d+)\b', question.lower())
    if match:
        return int(match.group(1))
    return 10

# =====================================================
# RANKING SQL
# =====================================================

def ranking_sql(question: str) -> str:
    q      = question.lower()
    metric = detect_metric(question)
    limit  = detect_limit(question)

    if "month" in q:
        dim = month_expr()
    elif "gear" in q:
        dim = COL_GEAR
    elif "cause" in q:
        dim = COL_CAUSE
    else:
        dim = COL_STATION

    agg = "AVG" if ("average" in q or "avg" in q) else "SUM"

    if metric == "COUNT(*)":
        return f"""
        SELECT {dim}     AS category,
               COUNT(*)  AS total
        FROM   {TABLE_NAME}
        GROUP  BY category
        ORDER  BY total DESC
        LIMIT  {limit};
        """

    return f"""
    SELECT {dim}            AS category,
           {agg}({metric})  AS total
    FROM   {TABLE_NAME}
    GROUP  BY category
    ORDER  BY total DESC
    LIMIT  {limit};
    """

# =====================================================
# TIMESERIES SQL  (SQLite-compatible date grouping)
# =====================================================

def timeseries_sql(question: str) -> str:
    metric = detect_metric(question)
    date_expr = month_expr()

    if metric == "COUNT(*)":
        return f"""
        SELECT {date_expr} AS month,
               COUNT(*)    AS total
        FROM   {TABLE_NAME}
        GROUP  BY month
        ORDER  BY month;
        """

    return f"""
    SELECT {date_expr}   AS month,
           AVG({metric}) AS avg_duration
    FROM   {TABLE_NAME}
    GROUP  BY month
    ORDER  BY month;
    """

# =====================================================
# HEATMAP SQL
# =====================================================

def heatmap_sql(question: str, metric_mode: bool = False) -> str:
    q = question.lower()
    if (
        "station vs gear" in q
        or "gear vs station" in q
        or "station by gear" in q
        or "gear breakdown" in q
    ):
        dim1 = COL_STATION
        dim2 = COL_GEAR

    elif "station vs cause" in q or "cause vs station" in q:
        dim1 = COL_STATION
        dim2 = COL_CAUSE

    elif "gear vs cause" in q or "cause vs gear" in q:
        dim1 = COL_GEAR
        dim2 = COL_CAUSE

    elif any(kw in q for kw in [
        "station vs month", "month vs station",
        "station by month", "month by station",
        "station and month", "month and station"
    ]):
        dim1 = COL_STATION
        dim2 = month_expr()

    elif any(kw in q for kw in [
        "gear vs month", "month vs gear",
        "gear by month", "month by gear",
        "gear and month", "month and gear"
    ]):
        dim1 = COL_GEAR
        dim2 = month_expr()

    elif any(kw in q for kw in [
        "cause vs month", "month vs cause",
        "cause by month", "month by cause",
        "cause and month", "month and cause"
    ]):
        dim1 = COL_CAUSE
        dim2 = month_expr()

    elif "month" in q and "cause" in q:
        dim1 = COL_CAUSE
        dim2 = month_expr()

    elif "month" in q and "gear" in q:
        dim1 = COL_GEAR
        dim2 = month_expr()

    elif "month" in q and "station" in q:
        dim1 = COL_STATION
        dim2 = month_expr()

    else:
        dim1 = COL_STATION
        dim2 = COL_CAUSE

    if metric_mode:
        raw = detect_metric(question)
        if raw == "COUNT(*)":
            metric_sql = "COUNT(*)"
        elif "average" in q or "avg" in q:
            metric_sql = f"AVG({raw})"
        else:
            metric_sql = f"SUM({raw})"
    else:
        metric_sql = "COUNT(*)"

    return f"""
    SELECT {dim1}       AS dim1,
           {dim2}       AS dim2,
           {metric_sql} AS total
    FROM   {TABLE_NAME}
    GROUP  BY dim1, dim2;
    """

# =====================================================
# SINGLE METRIC SQL
# =====================================================

def single_metric_sql(question: str) -> str:
    q = question.lower()

    if "average" in q or "avg" in q or "mean" in q:
        agg   = "AVG"
        label = "avg_duration"
    else:
        agg   = "SUM"
        label = "total_duration"

    filters = []

    for station in KNOWN_STATIONS:
        if station.lower() in q:
            filters.append(f"{COL_STATION} LIKE '%{station}%'")

    month = detect_month(question)
    if month:
        filters.append(month_filter(month))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    return f"""
    SELECT {agg}({COL_DURATION}) AS {label}
    FROM   {TABLE_NAME}
    {where};
    """

# =====================================================
# SQL GENERATOR
# =====================================================

def generate_sql(question: str) -> str:
    intent = classify_query(question)
    print(f"INTENT: {intent}")

    dispatch = {
        "count_query"      : count_query_sql,
        "detail_lookup"    : detail_lookup_sql,
        "ranking_by_metric": ranking_sql,
        "timeseries_metric": timeseries_sql,
        "heatmap_count"    : heatmap_sql,
        "single_metric"    : single_metric_sql,
    }

    if intent == "heatmap_metric":
        return heatmap_sql(question, metric_mode=True)

    return dispatch.get(intent, detail_lookup_sql)(question)

# =====================================================
# EXECUTE SQL
# =====================================================

def execute_sql(sql: str) -> dict:
    print("\nFINAL SQL:")
    print(sql)
    print(f"Executing against DB_PATH={DB_PATH}")

    columns = []
    rows = []

    def _sqlite_fetch():
        if not os.path.exists(DB_PATH):
            raise sqlite3.OperationalError(f"Database file does not exist: {DB_PATH}")

        with sqlite3.connect(DB_PATH) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if TABLE_NAME not in tables:
            print(f"Table '{TABLE_NAME}' missing in {DB_PATH}. Rebuilding database.")
            ensure_database()

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

        return cols, rows

    if SQLALCHEMY_AVAILABLE:
        try:
            with engine.connect() as conn:
                result  = conn.execute(text(sql))
                columns = list(result.keys())
                rows    = result.fetchall()
        except Exception as ex:
            print(f"SQLAlchemy execution failed: {ex}. Falling back to sqlite3.")

    if not columns and not rows:
        try:
            columns, rows = _sqlite_fetch()
        except Exception as ex:
            print(f"sqlite3 fallback failed on DB_PATH={DB_PATH}: {ex}")
            raise

    # Filter out header-like rows where each value equals its column name
    # Build a set of known header names (stripped of surrounding quotes)
    known_headers = set()
    for val in [
        COL_SL, COL_SFR_NO, COL_REPORTED, COL_CHARGEABLE, COL_STATION,
        COL_GEAR, COL_SUB_GEAR, COL_BRIEF_DESC, COL_CAUSE, COL_SUB_CAUSE,
        COL_TRAIN, COL_TIME_OCC, COL_TIME_INFORMED, COL_TIME_REACHED,
        COL_TIME_RECTIFIED, COL_DURATION
    ]:
        s = str(val).strip()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        known_headers.add(s.strip().lower())

    def _is_header_row(row, cols):
        try:
            # count how many cells look like header labels
            cnt = 0
            for v in row:
                vs = str(v).strip().lower()
                if vs in known_headers:
                    cnt += 1
            # if at least half of the cells match known header labels, treat as header
            return cnt >= max(1, int(len(row) / 2))
        except Exception:
            return False

    filtered_rows = [r for r in rows if not _is_header_row(r, columns)]

    return {"columns": columns, "rows": filtered_rows}

# =====================================================
# FORMAT ANSWER
# =====================================================

def format_answer(results: dict, question: str = "") -> str:
    rows    = results["rows"]
    columns = results["columns"]

    if not rows:
        return "No matching data found."

    q = question.lower()

    # ── SINGLE VALUE ─────────────────────────────────────
    if len(rows) == 1 and len(columns) == 1:
        col = columns[0]
        raw = rows[0][0]

        if raw is None:
            return "No data available."

        value = fmt_val(raw, col)

        if "avg" in col.lower():
            label = "Average Duration"
        elif "total" in col.lower() and is_duration_col(col):
            label = "Total Duration"
        elif is_duration_col(col):
            label = "Duration"
        elif col.lower() == "total":
            num = int(float(raw))
            if "detain" in q:
                return f"Total trains detained: {num}"
            if "non-chargeable" in q or "non chargeable" in q:
                return f"Total non-chargeable failures: {num}"
            if "chargeable" in q:
                return f"Total chargeable failures: {num}"
            return f"Total: {num}"
        else:
            label = col.replace("_", " ").title()

        return f"{label}: {value}"

        # ── TWO COLUMNS ───────────────────────────────────────
    if len(columns) == 2:

        value_col = columns[1]
        duration_requested = any(
            word in q
            for word in ["duration", "delay", "rectification", "repair time"]
        )
        show_mins = is_duration_col(value_col) or duration_requested

        def nice_label(raw_label) -> str:

            s = str(raw_label).strip()

            if s.lower() == "yes":
                return "Chargeable"

            if s.lower() == "no":
                return "Non-Chargeable"

            return s

        def fmt_row_val(val) -> str:

            if val is None:
                return "N/A"

            try:

                v = round(float(val), 1)

                if show_mins:
                    return f"{v} mins"

                if "failure" in q:
                    return f"{int(v)} failures"

                return str(int(v)) if v == int(v) else str(v)

            except (ValueError, TypeError):

                return str(val)

        lines = []

        for i, row in enumerate(rows, start=1):

            label = nice_label(row[0])

            val_str = fmt_row_val(row[1])

            lines.append(f"{i}. {label} — {val_str}")

        return "\n".join(lines)
    # ── HEATMAP (3 columns) ───────────────────────────────
    if len(columns) == 3:
        return "Heatmap generated successfully."

    # ── DETAIL RECORDS (7 columns) ────────────────────────
    output = []

    for i, row in enumerate(rows, start=1):
        station  = str(row[0]) if row[0] else "N/A"
        gear     = str(row[1]) if row[1] else "N/A"
        sub_gear = str(row[2]) if row[2] else "N/A"
        cause    = str(row[3]) if row[3] else "N/A"
        detained = str(row[4]) if row[4] else "N/A"
        duration = fmt_val(row[5], "dur ation")
        time_val = str(row[6]) if row[6] else "N/A"

        block = (
            f"Failure {i}\n"
            f"  Station        : {station}\n"
            f"  Gear           : {gear}\n"
            f"  Sub Gear       : {sub_gear}\n"
            f"  Cause          : {cause}\n"
            f"  Train Detained : {detained}\n"
            f"  Duration       : {duration}\n"
            f"  Time           : {time_val}"
        )
        output.append(block)

    return "\n\n".join(output)

# =====================================================
# GRAPH GENERATOR
# =====================================================

def generate_graph(results: dict, question: str):
    rows    = results["rows"]
    columns = results["columns"]

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=columns)
    q  = question.lower()

    if len(columns) > 3:
        return None
    if "station" in q and "gear" in q:
        fig = px.bar(
            df,
            x="dim1",
            y="total",
            color="dim2",
            barmode="stack",
            title="Station by Gear Breakdown"
        )

        fig.update_layout(
            template="plotly_dark",
            height=700
        )

        return fig
    # ── HEATMAP ──────────────────────────────────────────
    if len(columns) == 3:
        pivot = df.pivot_table(
            index=columns[0],
            columns=columns[1],
            values=columns[2],
            aggfunc="sum",
            fill_value=0
        )

        pivot = pivot.astype(float)

        fig = px.imshow(
            pivot,
            text_auto=True,
            aspect="auto",
            title="Heatmap"
        )

        fig.update_layout(
            template="plotly_dark",
            autosize=True,
            height=max(700, len(pivot.index) * 45),
            margin=dict(
                l=150,
                r=50,
                t=80,
                b=150
            ),
            xaxis=dict(
                tickangle=-45,
                side="top",
                automargin=True
            ),
            yaxis=dict(
                automargin=True
            )
        )

        return fig

    # ── 2-COLUMN CHARTS ───────────────────────────────────
    if len(columns) != 2:
        return None

    x_col = columns[0]
    y_col = columns[1]

    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")
    df = df.dropna(subset=[y_col])

    if df.empty:
        return None

    x_lower = x_col.lower()
    if any(kw in x_lower for kw in ["date", "month", "year", "time", "week", "day"]):
        try:
            df[x_col] = pd.to_datetime(df[x_col])
        except Exception:
            pass
        df = df.sort_values(x_col)
    else:
        df = df.sort_values(y_col, ascending=False)

    y_label = y_col.replace("_", " ").title()
    if is_duration_col(y_col):
        y_label += " (mins)"

    if "chargeable" in q:
        fig = px.pie(df, names=x_col, values=y_col, title="Chargeable Distribution")

    elif any(word in q for word in [
        "trend", "monthly", "over time", "by month",
        "weekly", "daily", "yearly", "per month",
        "per week", "per day", "history", "time series"
    ]) or any(kw in x_lower for kw in ["date", "month", "year", "time", "week", "day"]):
        fig = px.line(
            df,
            x=x_col,
            y=y_col,
            markers=True,
            title=f"{y_label} Over Time",
            labels={y_col: y_label}
        )
        fig.update_traces(line=dict(width=2), marker=dict(size=7))

    else:
        fig = px.bar(
            df.head(15),
            x=x_col,
            y=y_col,
            text=y_col,
            title=f"{y_label} by {x_col.replace('_', ' ').title()}",
            labels={y_col: y_label}
        )
        fig.update_traces(textposition="outside")

    fig.update_layout(
        template="plotly_dark",
        height=600,
        width=1000,
        font=dict(size=14),
        title_font=dict(size=20),
        margin=dict(l=40, r=40, t=60, b=80),
        xaxis=dict(tickangle=-45)
    )

    return fig

# =====================================================
# MAIN ASK FUNCTION
# =====================================================

def ask(question: str) -> dict:
    try:
        ensure_database()
        print("\n" + "=" * 60)

        question = fix_typos(question)
        print(f"QUESTION: {question}")

        # For graph stability and reliable demo, use internal SQL generator.
        # The LLM-generated SQL may have arbitrary column names that break chart logic.
        USE_LLM = False  # Set to False to preserve graph/chart functionality

        if USE_LLM:
            print("Using LLM SQL generator.")
            conn = sqlite3.connect(DB_PATH)

            cols = pd.read_sql(
                "PRAGMA table_info(sfr_report)",
                conn
            )

            columns = cols["name"].tolist()

            conn.close()

            sql = llm_generate_sql(
                question,
                columns
            )

            if not sql:
                print("LLM did not return a safe SQL statement — using internal generator.")
                sql = generate_sql(question)

        else:
            print("Using internal SQL generator.")
            sql = generate_sql(question)

        results = execute_sql(sql)
        answer  = format_answer(results, question)
        graph   = generate_graph(results, question)

        return {
            "answer": answer,
            "graph": graph,
            "columns": results.get("columns"),
            "rows": results.get("rows"),
        }

    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "answer": f"Database query failed: {str(e)}",
            "graph" : None
        }

# =====================================================
# TERMINAL TEST LOOP
# =====================================================

if __name__ == "__main__":

    print("=" * 60)
    print("  SFR ASSISTANT  (SQLite)")
    print("  DB:", DB_PATH)
    print("  Type 'exit' to quit")
    print("=" * 60)

    while True:

        q = input("\nAsk: ").strip()

        if not q:
            continue

        if q.lower() == "exit":
            break

        result = ask(q)

        print("\nANSWER:\n")
        print(result["answer"])

        if result["graph"]:
            result["graph"].show()
