# Value Normalization Rules

Health-checkup spreadsheets mix Korean and English notations, sometimes
within the same row. The loader collapses these variants into a single
canonical form before they reach the database so downstream code (table
cells, sparklines, search, exports) only ever sees one shape.

## Canonical shapes

| Concept           | Canonical form          | Variants that map to it                    |
|-------------------|-------------------------|--------------------------------------------|
| Negative          | `Negative`              | `음성`                                      |
| Positive          | `Positive`              | `양성`                                      |
| Weak positive     | `Weak Positive`         | `약양성`                                    |
| Trace             | `Trace`                 | (already canonical)                        |
| Negative + titer  | `Negative (0.19)`       | `음성:0.19`, `Negative 0.16`, `음성: 0.19`  |
| Non-reactive + titer | `Non-Reactive (0.11)` | `Non-Reactive: 0.11`, `Non-Reactive 0.11`  |
| Integer range     | `0-3`                   | `0~3`, `0 ~ 3`, `0 - 3`                    |

### Exceptions (intentionally not normalized)

| Token   | Why kept as-is                                                 |
|---------|----------------------------------------------------------------|
| `정상`  | Korean clinical term for hearing-test results (청력 좌/우). It is not a synonym of the `NORMAL` *status flag* (which lives on `v_measurements.status`). |

## Where the rules live

- **`app/load_data.py` → `normalize_value_text()`** — single source of
  truth. Runs on every measurement during seed loading.
- **`app/seed_data.py`** — source strings already follow the canonical
  shape, so a human reading the seed file sees the same values that
  end up in the DB.

The normalizer is **idempotent**: running it on an already-canonical
string returns the string unchanged. That means any future ingestion
path (manual edits, future POST endpoint, CSV import) can call the same
function without risking double-conversion.

## Adding a new rule

1. Decide the canonical form. Prefer English unless the term is a
   domain-specific Korean clinical word (cf. `정상`).
2. Add the mapping in `_KO_TO_EN` (for simple token substitution) or
   extend the regex in `normalize_value_text()` (for shape transforms
   like compound titers).
3. Update the table above.
4. Re-run `python -m app.load_data` to apply.

## Order matters

`약양성` contains the substring `양성`. The substitution table must
process the longer string first, otherwise `약양성` would partially
match `양성` and become `약Positive`.

## Status flags (`HIGH` / `LOW` / `NORMAL`)

Status is **not** stored in `measurements`. It is computed on read by
the `v_measurements` view from `value_numeric` against the row's
`ref_min` / `ref_max`. Editing a reference range via
`PATCH /items/{id}/reference` immediately re-classifies every
measurement — no normalization or re-seed needed.

## Audit query

Quick check that the DB only contains canonical text:

```sql
SELECT DISTINCT value_text, COUNT(*) AS n
FROM   measurements
WHERE  value_text IS NOT NULL
  AND  value_numeric IS NULL
GROUP  BY value_text
ORDER  BY n DESC;
```

Expected non-numeric values (as of the last seed):
`Negative`, `정상`, `0-3`, `Weak Positive`, `Trace`, `Positive`.

Compound forms (numeric + label):
`Negative (X.XX)`, `Non-Reactive (X.XX)`.
