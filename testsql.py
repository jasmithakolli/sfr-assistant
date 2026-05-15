# =====================================================
# SFR ASSISTANT — SQLite Query Engine
# =====================================================

import os
import re
import pandas as pd
import plotly.express as px  # type: ignore

from rapidfuzz import process, fuzz

try:
    from sqlalchemy import create_engine, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    import sqlite3

# =====================================================
# DATABASE CONFIG
# =====================================================

DB_PATH    = os.getenv("SFR_DB_PATH", "sfr.db")

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
        return create_engine(f"sqlite:///{DB_PATH}", pool_pre_ping=True)
    return None


engine = get_engine()

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

    if "how many" in q:
        return "count_query"

    if any(word in q for word in ["show", "list", "what failed"]):
        return "detail_lookup"

    if any(word in q for word in ["trend", "monthly", "over time", "by month"]):
        return "timeseries_metric"

    if any(word in q for word in ["heatmap", "breakdown", "cross-tab"]):
        if any(word in q for word in ["duration", "delay", "average"]):
            return "heatmap_metric"
        return "heatmap_count"

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
    {where}
    LIMIT  100;
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

    if "station vs gear" in q or "gear vs station" in q:
        dim1 = COL_STATION
        dim2 = COL_GEAR

    elif "station vs cause" in q or "cause vs station" in q:
        dim1 = COL_STATION
        dim2 = COL_CAUSE

    elif "gear vs cause" in q or "cause vs gear" in q:
        dim1 = COL_GEAR
        dim2 = COL_CAUSE

    elif "station vs month" in q or "month vs station" in q:
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

    if SQLALCHEMY_AVAILABLE:
        with engine.connect() as conn:
            result  = conn.execute(text(sql))
            columns = list(result.keys())
            rows    = result.fetchall()
    else:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows    = cur.fetchall()
        conn.close()

    return {"columns": columns, "rows": rows}

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
        show_mins = is_duration_col(value_col)

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

    for i, row in enumerate(rows[:10], start=1):
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

    # ── HEATMAP ──────────────────────────────────────────
    if len(columns) == 3:
        top_dim1 = (
            df.groupby(columns[0])[columns[2]]
            .sum().nlargest(10).index
        )
        top_dim2 = (
            df.groupby(columns[1])[columns[2]]
            .sum().nlargest(8).index
        )

        filtered = df[
            df[columns[0]].isin(top_dim1) &
            df[columns[1]].isin(top_dim2)
        ]

        pivot = filtered.pivot_table(
    index=columns[0],
    columns=columns[1],
    values=columns[2],
    aggfunc="sum",
    fill_value=0
)
        pivot = pivot.astype(float)
        fig = px.imshow(pivot, text_auto=True, aspect="auto", title="Heatmap")
        fig.update_layout(template="plotly_dark", height=700, width=1000)
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
        print("\n" + "=" * 60)

        question = fix_typos(question)
        print(f"QUESTION: {question}")

        sql     = generate_sql(question)
        results = execute_sql(sql)
        answer  = format_answer(results, question)
        graph   = generate_graph(results, question)

        return {"answer": answer, "graph": graph}

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