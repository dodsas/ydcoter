"""Initialize the SQLite database and load seed health records.

Usage:
    python -m app.load_data        # idempotent: drops and reloads seed data
"""
from __future__ import annotations

import re
import sys
from typing import Optional, Tuple

from app.database import connect, init_schema
from app.seed_data import RECORDS

_RANGE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*[~\-]\s*\d+(?:\.\d+)?\s*$")
_NUM_RE = re.compile(r"[+-]?\d+\.\d+|[+-]?\d+")


def parse_value(raw: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """Return (numeric, text) for a raw cell value.

    - Pure number: numeric set, text mirrors the original.
    - Mixed (e.g. '음성:0.19'): extracts the first number; text keeps the raw.
    - Range (e.g. '0~3'): numeric is None, text holds the range.
    - Empty/None: returns (None, None).
    """
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, None

    if _RANGE_RE.match(s):
        return None, s

    normalized = s.replace(",", ".") if re.fullmatch(r"\d+,\d+", s) else s
    try:
        return float(normalized), s
    except ValueError:
        pass

    m = _NUM_RE.search(normalized)
    if m:
        try:
            return float(m.group()), s
        except ValueError:
            pass
    return None, s


def load(reset: bool = True) -> None:
    conn = connect()
    try:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS measurements;"
                "DROP TABLE IF EXISTS test_items;"
                "DROP VIEW  IF EXISTS v_measurements;"
            )
        init_schema(conn)

        item_count = 0
        measure_count = 0

        for (major, minor, code, name, values,
             ref_min, ref_max, ref_indicator, related, memo) in RECORDS:
            cur = conn.execute(
                """
                INSERT INTO test_items
                  (major_category, minor_category, code, name,
                   ref_min, ref_max, ref_indicator, related_diseases, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (major, minor, code, name, ref_min, ref_max,
                 ref_indicator, related, memo),
            )
            item_id = cur.lastrowid
            item_count += 1

            for year, raw in values.items():
                num, text = parse_value(raw)
                if num is None and text is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO measurements (item_id, year, value_numeric, value_text)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_id, year, num, text),
                )
                measure_count += 1

        conn.commit()
        print(f"Loaded {item_count} items / {measure_count} measurements -> "
              f"{conn.execute('PRAGMA database_list').fetchone()['file']}")
    finally:
        conn.close()


if __name__ == "__main__":
    load(reset="--keep" not in sys.argv)
