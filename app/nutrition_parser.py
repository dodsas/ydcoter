"""Free-text food log -> structured nutrition entries via Claude.

The user describes a day's meals in natural language. We ask Claude to
return strict JSON whose shape mirrors :mod:`app.nutrition_data.LOGS`,
so the rest of the pipeline (insertion, totals view) doesn't change.

Claude only sees the nutrient codes we already track — anything else is
discarded. Estimates are intentionally approximate; the prompt asks for
"reasonable" values rather than precise lab numbers.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from app.yclaude_client import YClaudeError, client as yclaude


# Meal aliases we accept in Claude's response. Lower-case ASCII canonical
# forms are stored in the DB; anything outside this set is silently
# coerced to 'snack' so we never reject a whole day on a typo.
_MEAL_ALIASES = {
    "breakfast": "breakfast", "아침":   "breakfast", "morning":   "breakfast",
    "lunch":     "lunch",     "점심":   "lunch",
    "dinner":    "dinner",    "저녁":   "dinner",
    "snack":     "snack",     "간식":   "snack",
    "supplement":"supplement","영양제": "supplement","supplements":"supplement",
}


@dataclass(frozen=True)
class ParsedEntry:
    meal: str
    food: str
    serving: str | None
    note: str | None
    values: dict[str, float]   # nutrient_code -> amount in that nutrient's unit


def parse_food_text(
    text: str,
    *,
    nutrient_catalog: Iterable[dict],
    date_iso: str,
    existing_entries: list[dict] | None = None,
) -> list[ParsedEntry]:
    """Send ``text`` to Claude and return validated entries.

    ``nutrient_catalog`` is the live nutrient table fetched from SQLite —
    we hand the full code list to Claude so its output uses only codes
    we recognise. Unknown codes in the response are dropped.

    ``existing_entries`` is the list of food rows already stored for this
    date — passed to Claude as context so it knows not to re-emit them.
    Each item should be a dict with at least ``meal_type``, ``food_name``,
    and optional ``serving``.
    """
    catalog = list(nutrient_catalog)
    if not catalog:
        raise ValueError("nutrient_catalog is empty — load_data must run first")

    prompt = _build_prompt(
        text,
        catalog=catalog,
        date_iso=date_iso,
        existing_entries=existing_entries or [],
    )
    raw = yclaude.chat(prompt)
    payload = _extract_json(raw)

    entries_in = payload.get("entries", [])
    if not isinstance(entries_in, list):
        raise YClaudeError(
            "Claude returned 'entries' as a non-list — try rephrasing the log",
            status_code=502,
        )

    known_codes = {row["code"] for row in catalog}
    out: list[ParsedEntry] = []
    for raw_entry in entries_in:
        if not isinstance(raw_entry, dict):
            continue
        food = (raw_entry.get("food") or "").strip()
        if not food:
            continue
        meal_raw = (raw_entry.get("meal") or "").strip().lower()
        meal = _MEAL_ALIASES.get(meal_raw, "snack")
        serving = _clean_str(raw_entry.get("serving"))
        note = _clean_str(raw_entry.get("note"))

        values_in = raw_entry.get("values") or {}
        if not isinstance(values_in, dict):
            values_in = {}
        values: dict[str, float] = {}
        for code, amount in values_in.items():
            if code not in known_codes:
                continue
            try:
                num = float(amount)
            except (TypeError, ValueError):
                continue
            if num < 0:
                continue
            values[code] = num

        out.append(ParsedEntry(
            meal=meal, food=food, serving=serving, note=note, values=values,
        ))

    if not out:
        raise YClaudeError(
            "Claude returned no usable entries — try rephrasing or adding amounts",
            status_code=422,
        )

    return out


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


_PROMPT_HEADER = """\
당신은 한국 식단의 영양 분석가입니다. 사용자가 하루 동안 먹은 음식을 자연어로 \
설명하면, 아래 영양소 코드 목록을 사용해 음식별 영양소 추정치를 JSON으로 반환합니다.

규칙:
1. 응답은 **오직 JSON 객체** 하나입니다. 설명, 마크다운, 코드펜스 금지.
2. 최상위 형태:
   {"entries": [ { "meal": ..., "food": ..., "serving": ..., "note": ..., "values": { code: amount } } ]}
3. meal 은 다음 중 하나: "breakfast", "lunch", "dinner", "snack", "supplement".
   사용자가 한국어("아침"/"점심"/"저녁"/"간식"/"영양제")로 적어도 위 영문 코드로 변환.
4. food 는 한국어 식품명 (간결하게). serving 은 사용자가 명시한 분량 그대로 (예: "1개", "반컵 (125ml)").
   분량 정보가 없으면 serving 은 null.
5. values 의 키는 아래 코드 목록에서만 선택. 단위는 코드 옆 표기와 일치해야 함 (kcal·g·mg·µg).
6. 사용자가 일부만 먹었다고 하면 (예: "국물 1/3 마심") 비례 축소해서 반영하고, note 에 한 줄로 메모.
7. 추정값은 합리적인 한국 식품 영양 데이터(식약처 식품영양정보 수준)에 기반.
   확신이 없는 영양소는 생략 — 0 을 넣지 말 것.
8. 응답에 적힌 단위는 무시되고 amount 만 저장되므로, **반드시 코드 옆 단위로 환산**해서 숫자만 넣을 것.
9. **추가 입력 모드**: "이미 저장된 항목" 섹션이 비어있지 않으면 그 항목들은 절대 다시 출력하지 마세요. \
오직 "신규 식단 설명" 텍스트에 새로 적힌 음식만 entries 에 포함합니다. \
같은 끼니(meal)라도 음식이 다르면 별도 entry 로 추가하세요.

영양소 코드 목록:
"""

_PROMPT_FOOTER_TEMPLATE = """

대상 날짜: {date}

이미 저장된 항목 ({existing_count}개):
{existing_block}

신규 식단 설명 (이 텍스트의 음식만 entries 로 변환):
\"\"\"
{text}
\"\"\"

이제 JSON 만 출력하세요. entries 에는 위 신규 텍스트에 새로 등장한 음식만 넣습니다.
"""


def _build_prompt(
    text: str,
    *,
    catalog: list[dict],
    date_iso: str,
    existing_entries: list[dict],
) -> str:
    rows = []
    for row in catalog:
        bits = [f"- {row['code']} ({row['unit']}) — {row['name_ko']}"]
        if row.get("rda"):
            bits.append(f"RDA {row['rda']}")
        if row.get("ul"):
            bits.append(f"UL {row['ul']}")
        rows.append(" · ".join(bits))
    catalog_block = "\n".join(rows)

    existing_block = _format_existing(existing_entries)

    return (
        _PROMPT_HEADER
        + catalog_block
        + _PROMPT_FOOTER_TEMPLATE.format(
            date=date_iso,
            existing_count=len(existing_entries),
            existing_block=existing_block,
            text=text.strip(),
        )
    )


def _format_existing(entries: list[dict]) -> str:
    if not entries:
        return "(없음)"
    lines = []
    for e in entries:
        meal = e.get("meal_type") or "?"
        food = e.get("food_name") or "?"
        serving = e.get("serving")
        lines.append(f"  - [{meal}] {food}" + (f" — {serving}" if serving else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json(raw: str) -> dict:
    """Claude usually returns clean JSON; sometimes it wraps with text or
    fences. Strip those, then parse. Raises YClaudeError on hard failure.
    """
    if not raw or not raw.strip():
        raise YClaudeError("Claude returned empty response", status_code=502)

    candidates = []
    m = _FENCE_RE.search(raw)
    if m:
        candidates.append(m.group(1))
    candidates.append(raw)

    # Fall-through: grab the first {...} block of the longest candidate.
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
        start = cand.find("{")
        end = cand.rfind("}")
        if start != -1 and end > start:
            chunk = cand[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue

    raise YClaudeError(
        f"Could not parse JSON from Claude response: {raw[:300]}",
        status_code=502,
    )


def _clean_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
