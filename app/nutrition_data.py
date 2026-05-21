"""Nutrition reference + daily-log seed data.

Two tables:

- NUTRIENTS: master list with RDA (recommended daily allowance) and UL
  (tolerable upper intake limit) for adult Korean males.
- LOGS: per-day food entries with per-nutrient amounts.

Sources for RDA/UL: 한국인 영양소 섭취기준 2020 (KDRI) — adult male 19~49y.
Values are conservative estimates; tune via the seed file as needed.

Schema of one log entry:
    {
      "profile_slug": "tteoni",
      "date":         "YYYY-MM-DD",
      "meal":         "lunch" | "dinner" | "snack" | "supplement" | ...,
      "food":         "displayed food name",
      "serving":      "free-text serving description",
      "note":         optional,
      "values":       { nutrient_code: amount, ... }
    }

All nutrient amounts use the unit declared in NUTRIENTS (so kcal, g, mg, µg).
"""

# ---------------------------------------------------------------------------
# Per-sex RDA values (KDRI 2020, adult 19–49 years).
# Used by app.load_data to populate the per-profile override table.
# The default values on the NUTRIENTS rows are the male figures, kept so
# any profile without explicit sex still gets a sensible target.
# ---------------------------------------------------------------------------
RDA_BY_SEX = {
    "male": {
        # kcal is computed per-profile via estimate_kcal_tdee — value here
        # is a fallback only.
        "kcal": 2500,
        "protein": 65, "carb": 325, "fat": 60, "fiber": 25, "sodium": 2000,
        "ca": 800, "fe": 10, "mg": 370, "zn": 10, "k": 3500, "se": 60, "iodine": 150,
        "vit_a": 800, "vit_c": 100, "vit_d": 10, "vit_e": 12, "vit_k": 75,
        "b1": 1.2, "b2": 1.5, "b3": 16, "b6": 1.5, "folate": 400, "b12": 2.4, "biotin": 30,
    },
    "female": {
        "kcal": 1900,
        "protein": 55, "carb": 305, "fat": 45, "fiber": 20, "sodium": 2000,
        "ca": 700, "fe": 14, "mg": 280, "zn": 8, "k": 3500, "se": 60, "iodine": 150,
        "vit_a": 650, "vit_c": 100, "vit_d": 10, "vit_e": 12, "vit_k": 65,
        "b1": 1.1, "b2": 1.2, "b3": 14, "b6": 1.4, "folate": 400, "b12": 2.4, "biotin": 30,
    },
}


def estimate_kcal_tdee(
    *,
    sex: str,
    birth_year: int,
    height_cm: float,
    reference_year: int | None = None,
    pal: float = 1.5,
) -> int:
    """Estimate daily energy need via Mifflin–St Jeor.

    Weight is approximated from ideal BMI 22 since we don't store it.
    Activity level (PAL) defaults to 1.5 = "light" (desk work + commute).
    Result is rounded to the nearest 50 kcal to avoid false precision.
    """
    from datetime import date

    year = reference_year or date.today().year
    age = max(year - birth_year, 18)
    weight = 22.0 * (height_cm / 100) ** 2
    bmr = 10 * weight + 6.25 * height_cm - 5 * age
    bmr += 5 if sex == "male" else -161
    tdee = bmr * pal
    return int(round(tdee / 50) * 50)


# (code, name_ko, name_en, unit, category, rda, ul, sort, note)
NUTRIENTS = [
    # ---- macros / energy ----
    ("kcal",     "에너지",       "Energy",         "kcal", "macro",  2500, None,  10, "성인 남성 권장 섭취량"),
    ("protein",  "단백질",       "Protein",        "g",    "macro",    65, None,  11, None),
    ("carb",     "탄수화물",     "Carbohydrate",   "g",    "macro",   325, None,  12, None),
    ("fat",      "지방",         "Fat",            "g",    "macro",    60, None,  13, None),
    ("fiber",    "식이섬유",     "Dietary fiber",  "g",    "macro",    25, None,  14, None),
    ("sodium",   "나트륨",       "Sodium",         "mg",   "macro",  2000, None,  15, "WHO 권고 상한"),

    # ---- minerals ----
    ("ca",       "칼슘",         "Calcium",        "mg",   "mineral", 800, 2500,  20, None),
    ("fe",       "철분",         "Iron",           "mg",   "mineral",  10,   45,  21, None),
    ("mg",       "마그네슘",     "Magnesium",      "mg",   "mineral", 370,  350,  22, "UL은 보충제 형태 기준"),
    ("zn",       "아연",         "Zinc",           "mg",   "mineral",  10,   35,  23, None),
    ("k",        "칼륨",         "Potassium",      "mg",   "mineral",3500, None,  24, None),
    ("se",       "셀레늄",       "Selenium",       "µg",   "mineral",  60,  400,  25, None),
    ("iodine",   "요오드",       "Iodine",         "µg",   "mineral", 150, 2400,  26, None),

    # ---- vitamins ----
    ("vit_a",    "비타민 A",     "Vitamin A",      "µg",   "vitamin", 800, 3000,  30, "RAE"),
    ("vit_c",    "비타민 C",     "Vitamin C",      "mg",   "vitamin", 100, 2000,  31, None),
    ("vit_d",    "비타민 D",     "Vitamin D",      "µg",   "vitamin",  10,  100,  32, None),
    ("vit_e",    "비타민 E",     "Vitamin E",      "mg",   "vitamin",  12,  540,  33, "α-토코페롤"),
    ("vit_k",    "비타민 K",     "Vitamin K",      "µg",   "vitamin",  75, None,  34, None),
    ("b1",       "비타민 B1",    "Thiamin",        "mg",   "vitamin", 1.2, None,  35, None),
    ("b2",       "비타민 B2",    "Riboflavin",     "mg",   "vitamin", 1.5, None,  36, None),
    ("b3",       "나이아신",     "Niacin",         "mg",   "vitamin",  16,   35,  37, "UL은 보충제 형태 기준"),
    ("b6",       "비타민 B6",    "Pyridoxine",     "mg",   "vitamin", 1.5,  100,  38, None),
    ("folate",   "엽산",         "Folate",         "µg",   "vitamin", 400, 1000,  39, None),
    ("b12",      "비타민 B12",   "Cobalamin",      "µg",   "vitamin", 2.4, None,  40, None),
    ("biotin",   "비오틴",       "Biotin",         "µg",   "vitamin",  30, None,  41, None),
]


# Each entry is a dict; values map nutrient code -> amount (in that nutrient's unit).
LOGS = [
    # =====================================================================
    # 2026-05-20  떠니
    # =====================================================================

    # ---------- 점심 ----------
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "lunch",
        "food": "KFC 징거버거",
        "serving": "1개",
        "values": {
            "kcal": 535, "carb": 49, "protein": 25, "fat": 27, "fiber": 3, "sodium": 1010,
            "ca": 80, "fe": 3.0, "mg": 30, "zn": 1.8, "k": 370,
            "vit_a": 50, "vit_c": 2, "vit_d": 0.1, "b12": 0.5, "folate": 80, "b3": 6,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "lunch",
        "food": "KFC 너겟",
        "serving": "5조각",
        "values": {
            "kcal": 235, "carb": 12, "protein": 13, "fat": 14, "fiber": 1, "sodium": 480,
            "ca": 15, "fe": 0.8, "mg": 14, "zn": 0.6, "k": 200,
            "vit_a": 10, "vit_d": 0.1, "b12": 0.3, "folate": 20, "b3": 3,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "lunch",
        "food": "제로콜라",
        "serving": "반컵 (125ml)",
        "values": {
            "kcal": 0, "sodium": 5,
        },
    },

    # ---------- 저녁 ----------
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "신라면",
        "serving": "면 1개 + 국물 1/3",
        "note": "국물은 1/3만 음용",
        "values": {
            "kcal": 435, "carb": 68, "protein": 9, "fat": 14, "fiber": 3, "sodium": 900,
            "ca": 50, "fe": 1.5, "mg": 20, "zn": 0.6, "k": 200,
            "vit_a": 30, "vit_c": 1, "folate": 60, "b3": 3,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "슬라이스 치즈",
        "serving": "1장 (18g)",
        "values": {
            "kcal": 60, "carb": 1, "protein": 3.5, "fat": 4.5, "sodium": 230,
            "ca": 120, "fe": 0.1, "mg": 5, "zn": 0.5, "k": 17,
            "vit_a": 60, "vit_d": 0.1, "b12": 0.2, "folate": 5,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "계란",
        "serving": "2개",
        "values": {
            "kcal": 150, "carb": 1, "protein": 12, "fat": 10, "sodium": 140,
            "ca": 56, "fe": 1.8, "mg": 14, "zn": 1.3, "se": 30, "k": 138, "iodine": 50,
            "vit_a": 160, "vit_d": 2.0, "vit_e": 1, "b2": 0.5, "b12": 1.1, "folate": 90,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "블루베리",
        "serving": "20알 (~30g)",
        "values": {
            "kcal": 17, "carb": 4, "fiber": 0.7, "k": 23,
            "vit_c": 3, "vit_k": 5, "fe": 0.1,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "그릭요거트",
        "serving": "2스푼 (~30g)",
        "values": {
            "kcal": 30, "carb": 1.5, "protein": 3, "fat": 1.5, "sodium": 10,
            "ca": 35, "zn": 0.2, "k": 40, "b12": 0.2, "b2": 0.1,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "땅콩",
        "serving": "10알 (~10g)",
        "values": {
            "kcal": 57, "carb": 1.6, "protein": 2.6, "fat": 5, "fiber": 0.8,
            "ca": 9, "fe": 0.5, "mg": 17, "zn": 0.3, "k": 70,
            "vit_e": 0.8, "b3": 1.2, "folate": 25,
        },
    },

    # ---------- 간식 ----------
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "snack",
        "food": "쌀로별",
        "serving": "1봉 (71g)",
        "values": {
            "kcal": 350, "carb": 50, "protein": 4, "fat": 14, "fiber": 0.5, "sodium": 280,
            "ca": 10, "fe": 0.5, "mg": 8, "zn": 0.4, "k": 80, "folate": 10,
        },
    },

    # ---------- 영양제 ----------
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "supplement",
        "food": "Nature's Way Alive! 남성용 울트라 종합비타민",
        "serving": "1정",
        "note": "철분은 무첨가 (남성용 처방)",
        "values": {
            "vit_a": 1050, "vit_c": 250, "vit_d": 50, "vit_e": 67, "vit_k": 80,
            "b1": 50, "b2": 50, "b3": 50, "b6": 60, "b12": 200,
            "folate": 400, "biotin": 1000,
            "ca": 100, "mg": 50, "zn": 15, "se": 200, "iodine": 150,
        },
    },
]
