"""Initialize the database and load seed health records.

Three modes:

    python -m app.load_data           # default: SAFE — ensures schema,
                                        seeds only if profiles table is
                                        empty. User-entered data preserved.
    python -m app.load_data --reset   # destructive — drops every table
                                        and reseeds from scratch. Use only
                                        for local development.
    python -m app.load_data --keep    # legacy alias for safe mode (schema
                                        only, no seeding even when empty).

Production (Render) and any environment with ``TURSO_DATABASE_URL`` set
should always run the default mode so user edits survive deploys.
"""
from __future__ import annotations

import re
import sys
from typing import Optional, Tuple

from app.database import connect, init_schema
from app.nutrition_data import (
    LOGS as NUTRITION_LOGS,
    NUTRIENTS,
    RDA_BY_SEX,
    estimate_kcal_tdee,
)
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


def load(reset: bool = False, schema_only: bool = False) -> None:
    """Apply schema migrations + optionally seed data.

    Arguments:
        reset:        Wipe every app table before applying schema. DESTRUCTIVE.
                      Default False — preserves user-entered data across deploys.
        schema_only:  Apply schema, then return without checking whether to seed.
                      Useful when you want to migrate columns and nothing else.

    Without flags (the deploy/safe default): runs schema migration, then
    seeds only if the ``profiles`` table is empty.
    """
    conn = connect()
    try:
        if reset:
            conn.executescript(
                "DROP VIEW  IF EXISTS v_daily_nutrition;"
                "DROP TABLE IF EXISTS profile_nutrient_rda;"
                "DROP TABLE IF EXISTS nutrition_values;"
                "DROP TABLE IF EXISTS nutrition_logs;"
                "DROP TABLE IF EXISTS nutrients;"
                "DROP VIEW  IF EXISTS v_measurements;"
                "DROP TABLE IF EXISTS measurements;"
                "DROP TABLE IF EXISTS test_items;"
                "DROP TABLE IF EXISTS profiles;"
            )
        init_schema(conn)

        if schema_only:
            print("Schema ensured (schema-only mode); data left untouched.")
            return

        # Detect whether we should seed. Seed iff profiles table is empty.
        existing_profiles = conn.execute(
            "SELECT COUNT(*) AS n FROM profiles"
        ).fetchone()["n"]
        if existing_profiles > 0 and not reset:
            print(
                f"Schema ensured. {existing_profiles} profiles already present — "
                "skipping seed (use --reset to force reseed)."
            )
            return

        profile_count = 0
        item_count = 0
        measure_count = 0

        for profile in PROFILES:
            cur = conn.execute(
                """
                INSERT INTO profiles
                  (slug, display_name, note, sort_order, sex, birth_year, height_cm)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile["slug"],
                    profile["display_name"],
                    profile.get("note"),
                    profile.get("sort_order", 0),
                    profile.get("sex"),
                    profile.get("birth_year"),
                    profile.get("height_cm"),
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

        nutrient_count, log_count, value_count = _seed_nutrition(conn)

        conn.commit()
        path = conn.execute("PRAGMA database_list").fetchone()["file"]
        print(
            f"Loaded {profile_count} profiles / {item_count} items / "
            f"{measure_count} measurements / "
            f"{nutrient_count} nutrients / {log_count} food logs / "
            f"{value_count} nutrient values -> {path}"
        )
    finally:
        conn.close()


def _seed_nutrition(conn) -> tuple[int, int, int]:
    """Insert nutrient master list + daily food logs from nutrition_data.py."""
    nutrient_id_by_code: dict[str, int] = {}
    for row in NUTRIENTS:
        # The NUTRIENTS tuple grew over time; older rows may still be 9-wide.
        if len(row) == 9:
            code, name_ko, name_en, unit, category, rda, ul, sort_order, note = row
            excess_warning = None
        else:
            (code, name_ko, name_en, unit, category, rda, ul, sort_order,
             note, excess_warning) = row
        cur = conn.execute(
            """
            INSERT INTO nutrients
              (code, name_ko, name_en, unit, category, rda, ul,
               sort_order, note, excess_warning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code, name_ko, name_en, unit, category, rda, ul,
             sort_order, note, excess_warning),
        )
        nutrient_id_by_code[code] = cur.lastrowid

    profile_rows = conn.execute(
        "SELECT id, slug, sex, birth_year, height_cm FROM profiles"
    ).fetchall()
    profile_id_by_slug = {row["slug"]: row["id"] for row in profile_rows}

    _seed_profile_rda(conn, profile_rows, nutrient_id_by_code)

    log_count = 0
    value_count = 0
    for sort_idx, entry in enumerate(NUTRITION_LOGS):
        slug = entry["profile_slug"]
        if slug not in profile_id_by_slug:
            raise ValueError(f"unknown profile slug in nutrition log: {slug}")
        cur = conn.execute(
            """
            INSERT INTO nutrition_logs
              (profile_id, log_date, meal_type, food_name, serving, sort_order, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id_by_slug[slug],
                entry["date"],
                entry["meal"],
                entry["food"],
                entry.get("serving"),
                sort_idx,
                entry.get("note"),
            ),
        )
        log_id = cur.lastrowid
        log_count += 1
        for code, amount in entry.get("values", {}).items():
            if code not in nutrient_id_by_code:
                raise ValueError(f"unknown nutrient code: {code}")
            conn.execute(
                """
                INSERT INTO nutrition_values (log_id, nutrient_id, amount)
                VALUES (?, ?, ?)
                """,
                (log_id, nutrient_id_by_code[code], float(amount)),
            )
            value_count += 1

    return len(NUTRIENTS), log_count, value_count


def _seed_profile_rda(conn, profile_rows, nutrient_id_by_code: dict[str, int]) -> None:
    """Write per-profile RDA overrides derived from sex + Mifflin-St Jeor.

    Skips profiles with no `sex` set so the catalog defaults stand in.
    """
    for row in profile_rows:
        sex = row["sex"]
        if sex not in RDA_BY_SEX:
            continue
        base = dict(RDA_BY_SEX[sex])
        if row["birth_year"] and row["height_cm"]:
            base["kcal"] = estimate_kcal_tdee(
                sex=sex,
                birth_year=row["birth_year"],
                height_cm=row["height_cm"],
            )
        for code, value in base.items():
            nutrient_id = nutrient_id_by_code.get(code)
            if nutrient_id is None:
                continue
            conn.execute(
                """
                INSERT INTO profile_nutrient_rda (profile_id, nutrient_id, rda)
                VALUES (?, ?, ?)
                """,
                (row["id"], nutrient_id, float(value)),
            )


if __name__ == "__main__":
    load(
        reset="--reset" in sys.argv,
        schema_only="--keep" in sys.argv,
    )
