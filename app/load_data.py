"""Initialize the SQLite database and load seed health records.

Usage:
    python -m app.load_data        # idempotent: drops and reloads seed data
    python -m app.load_data --keep # only ensures schema; leaves data alone
"""
from __future__ import annotations

import re
import sys
from typing import Optional, Tuple

from app.database import connect, init_schema
from app.seed_data import PROFILES, RECORDS

_RANGE_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*[~\-]\s*\d+(?:\.\d+)?\s*$")
_NUM_RE = re.compile(r"[+-]?\d+\.\d+|[+-]?\d+")


_COMPOUND_RE = re.compile(
    r"\s*([A-Za-z][A-Za-z\- ]*?)\s*[: ]\s*([+-]?\d+(?:\.\d+)?)\s*"
)
_KO_TO_EN = (
    # `약양성` must come first because it contains the substring `양성`.
    ("약양성", "Weak Positive"),
    ("양성",   "Positive"),
    ("음성",   "Negative"),
    # `정상` (hearing test) is preserved as a Korean clinical term.
)


def normalize_value_text(text: Optional[str]) -> Optional[str]:
    """Canonicalize qualitative cell text so 음성/Negative variants align.

    - Korean negatives/positives become English.
    - Compound forms like '음성:0.19', 'Negative 0.16', 'Non-Reactive: 0.11'
      collapse to a single shape: 'Label (value)'.
    - Range '0~3' is rewritten with an ASCII hyphen '0-3'.
    - 정상 is left untouched (specific to the hearing test).

    Idempotent: running it twice yields the same string.
    """
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None

    for ko, en in _KO_TO_EN:
        s = s.replace(ko, en)

    s = re.sub(r"(\d+)\s*~\s*(\d+)", r"\1-\2", s)

    # Skip if the value already uses the canonical 'Label (value)' shape.
    if "(" not in s:
        m = _COMPOUND_RE.fullmatch(s)
        if m:
            s = f"{m.group(1).strip()} ({m.group(2)})"

    return s


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
                "DROP VIEW  IF EXISTS v_measurements;"
                "DROP TABLE IF EXISTS measurements;"
                "DROP TABLE IF EXISTS test_items;"
                "DROP TABLE IF EXISTS profiles;"
            )
        init_schema(conn)

        if not reset:
            print(f"Schema ensured -> {conn.execute('PRAGMA database_list').fetchone()['file']}")
            return

        profile_count = 0
        item_count = 0
        measure_count = 0

        for profile in PROFILES:
            cur = conn.execute(
                """
                INSERT INTO profiles (slug, display_name, note, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (
                    profile["slug"],
                    profile["display_name"],
                    profile.get("note"),
                    profile.get("sort_order", 0),
                ),
            )
            profile_id = cur.lastrowid
            profile_count += 1

            for (major, minor, code, name, values,
                 ref_min, ref_max, ref_indicator, related, memo) in RECORDS:
                cur = conn.execute(
                    """
                    INSERT INTO test_items
                      (profile_id, major_category, minor_category, code, name,
                       ref_min, ref_max, ref_indicator, related_diseases, memo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (profile_id, major, minor, code, name, ref_min, ref_max,
                     ref_indicator, related, memo),
                )
                item_id = cur.lastrowid
                item_count += 1

                if not profile.get("has_data"):
                    continue

                for year, raw in values.items():
                    num, text = parse_value(raw)
                    text = normalize_value_text(text)
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
        path = conn.execute("PRAGMA database_list").fetchone()["file"]
        print(
            f"Loaded {profile_count} profiles / {item_count} items / "
            f"{measure_count} measurements -> {path}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    load(reset="--keep" not in sys.argv)
