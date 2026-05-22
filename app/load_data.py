"""Initialize the database and load seed health records.

Modes:

    python -m app.load_data                  # default: SAFE — ensures
                                               schema, seeds only if
                                               profiles table is empty.
    python -m app.load_data --reset          # destructive — drops every
                                               table and reseeds. Local
                                               only.
    python -m app.load_data --keep           # legacy alias for safe mode.
    python -m app.load_data --turso-cleanup  # one-shot: drop legacy
                                               health tables/views from
                                               Turso after the split.

Production (Render) and any environment with ``TURSO_DATABASE_URL`` set
should always run the default mode so user edits survive deploys.
"""
from __future__ import annotations

import re
import sys
from typing import Optional, Tuple

from app.database import (
    ROOT,
    _connect_local,
    _split_sql,
    connect,
    init_health_schema,
    init_nutrition_schema,
    using_turso,
)
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
    # Split-DB seeding: health records (profiles/test_items/measurements)
    # always go to the local SQLite file; nutrition tables go to Turso when
    # configured, else share the local conn (dev fallback).
    health_conn = _connect_local()
    nutri_conn  = connect() if using_turso() else health_conn
    same_db     = nutri_conn is health_conn

    try:
        if reset:
            # Health side
            for stmt in (
                "DROP VIEW  IF EXISTS v_measurements",
                "DROP TABLE IF EXISTS measurements",
                "DROP TABLE IF EXISTS test_items",
            ):
                health_conn.execute(stmt)
            # Nutrition side (separate DB unless dev-fallback)
            for stmt in (
                "DROP VIEW  IF EXISTS v_daily_nutrition",
                "DROP TABLE IF EXISTS profile_nutrient_rda",
                "DROP TABLE IF EXISTS nutrition_values",
                "DROP TABLE IF EXISTS nutrition_logs",
                "DROP TABLE IF EXISTS nutrients",
            ):
                nutri_conn.execute(stmt)
            # Profiles is shared as an FK target — drop on both.
            health_conn.execute("DROP TABLE IF EXISTS profiles")
            if not same_db:
                nutri_conn.execute("DROP TABLE IF EXISTS profiles")

        init_health_schema(health_conn)
        init_nutrition_schema(nutri_conn)

        if schema_only:
            print("Schema ensured (schema-only mode); data left untouched.")
            return

        existing_profiles = health_conn.execute(
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
            cur = health_conn.execute(
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

            # Mirror the row onto the nutrition DB with an explicit id so
            # FK references from nutrition_logs / profile_nutrient_rda
            # resolve to the same row.
            if not same_db:
                nutri_conn.execute(
                    """
                    INSERT INTO profiles
                      (id, slug, display_name, note, sort_order, sex, birth_year, height_cm)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        profile["slug"],
                        profile["display_name"],
                        profile.get("note"),
                        profile.get("sort_order", 0),
                        profile.get("sex"),
                        profile.get("birth_year"),
                        profile.get("height_cm"),
                    ),
                )

            for (major, minor, code, name, values,
                 ref_min, ref_max, ref_indicator, related, memo) in RECORDS:
                cur = health_conn.execute(
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
                    health_conn.execute(
                        """
                        INSERT INTO measurements (item_id, year, value_numeric, value_text)
                        VALUES (?, ?, ?, ?)
                        """,
                        (item_id, year, num, text),
                    )
                    measure_count += 1

        nutrient_count, log_count, value_count = _seed_nutrition(
            health_conn, nutri_conn
        )

        health_conn.commit()
        if not same_db:
            nutri_conn.commit()
        print(
            f"Loaded {profile_count} profiles / {item_count} items / "
            f"{measure_count} measurements / "
            f"{nutrient_count} nutrients / {log_count} food logs / "
            f"{value_count} nutrient values"
        )
    finally:
        health_conn.close()
        if not same_db:
            nutri_conn.close()


def _seed_nutrition(health_conn, nutri_conn) -> tuple[int, int, int]:
    """Seed nutrients + daily food logs.

    Reads profile id/slug/sex/etc. from ``health_conn`` (authoritative);
    writes nutrient + log rows to ``nutri_conn`` (Turso in prod, same
    handle as health_conn in dev-fallback)."""
    nutrient_id_by_code: dict[str, int] = {}
    for row in NUTRIENTS:
        # The NUTRIENTS tuple grew over time; older rows may still be 9-wide.
        if len(row) == 9:
            code, name_ko, name_en, unit, category, rda, ul, sort_order, note = row
            excess_warning = None
        else:
            (code, name_ko, name_en, unit, category, rda, ul, sort_order,
             note, excess_warning) = row
        cur = nutri_conn.execute(
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

    profile_rows = health_conn.execute(
        "SELECT id, slug, sex, birth_year, height_cm FROM profiles"
    ).fetchall()
    profile_id_by_slug = {row["slug"]: row["id"] for row in profile_rows}

    _seed_profile_rda(nutri_conn, profile_rows, nutrient_id_by_code)

    log_count = 0
    value_count = 0
    for sort_idx, entry in enumerate(NUTRITION_LOGS):
        slug = entry["profile_slug"]
        if slug not in profile_id_by_slug:
            raise ValueError(f"unknown profile slug in nutrition log: {slug}")
        cur = nutri_conn.execute(
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
            nutri_conn.execute(
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


def turso_cleanup() -> None:
    """Apply sql/turso-cleanup.sql against Turso only.

    Drops legacy health tables/views (test_items, measurements,
    v_measurements, v_daily_nutrition) that are no longer queried after
    the split. Refuses to run without ``TURSO_DATABASE_URL`` so it can't
    accidentally drop the local seed data.
    """
    if not using_turso():
        print(
            "ERROR: --turso-cleanup requires TURSO_DATABASE_URL.",
            file=sys.stderr,
        )
        sys.exit(2)

    path = ROOT / "sql" / "turso-cleanup.sql"
    statements = _split_sql(path.read_text(encoding="utf-8"))

    conn = connect()
    try:
        for stmt in statements:
            print(f"  > {stmt};")
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    print(f"Turso cleanup applied ({len(statements)} statements).")


if __name__ == "__main__":
    if "--turso-cleanup" in sys.argv:
        turso_cleanup()
    else:
        load(
            reset="--reset" in sys.argv,
            schema_only="--keep" in sys.argv,
        )
