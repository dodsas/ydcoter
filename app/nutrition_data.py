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
        # 'ceiling' targets — bar fills toward these but >100% is bad:
        "sat_fat": 22, "trans_fat": 2.0, "chol": 300, "sugar": 62,
        "ca": 800, "p": 700, "fe": 10, "mg": 370, "zn": 10, "cu": 850, "mn": 4,
        "k": 3500, "se": 60, "iodine": 150,
        "vit_a": 800, "vit_c": 100, "vit_d": 10, "vit_e": 12, "vit_k": 75,
        "b1": 1.2, "b2": 1.5, "b3": 16, "b5": 5, "b6": 1.5, "folate": 400, "b12": 2.4, "biotin": 30,
        "choline": 550,
        "omega3": 1.6, "omega6": 13,
    },
    "female": {
        "kcal": 1900,
        "protein": 55, "carb": 305, "fat": 45, "fiber": 20, "sodium": 2000,
        "sat_fat": 17, "trans_fat": 2.0, "chol": 300, "sugar": 48,
        "ca": 700, "p": 700, "fe": 14, "mg": 280, "zn": 8, "cu": 650, "mn": 3.5,
        "k": 3500, "se": 60, "iodine": 150,
        "vit_a": 650, "vit_c": 100, "vit_d": 10, "vit_e": 12, "vit_k": 65,
        "b1": 1.1, "b2": 1.2, "b3": 14, "b5": 5, "b6": 1.4, "folate": 400, "b12": 2.4, "biotin": 30,
        "choline": 425,
        "omega3": 1.1, "omega6": 10,
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


# (code, name_ko, name_en, unit, category, rda, ul, sort, note, excess_warning)
#
# `excess_warning` is shown by the UI only when the row classifies as "bad"
# (over target for limit-type nutrients, or over UL for good-type).
# Leave None for nutrients where overconsumption is benign (water-soluble
# vitamins without UL, fiber, potassium, omega-3, etc.).
NUTRIENTS = [
    # ---- macros / energy ----
    ("kcal",     "에너지",       "Energy",         "kcal", "macro",  2500, None,  10, "성인 남성 권장 섭취량", None),
    ("protein",  "단백질",       "Protein",        "g",    "macro",    65, None,  11, None, None),
    ("carb",     "탄수화물",     "Carbohydrate",   "g",    "macro",   325, None,  12, None, None),
    ("fat",      "지방",         "Fat",            "g",    "macro",    60, None,  13, None, None),
    ("sat_fat",  "포화지방",     "Saturated fat",  "g",    "macro",    22, None,  14, "<8% 에너지 (KDRI 2020)",
        "LDL 콜레스테롤 상승·심혈관 질환 위험 증가"),
    ("trans_fat","트랜스지방",   "Trans fat",      "g",    "macro",     2, None,  15, "<1% 에너지 (KDRI 2020)",
        "HDL 감소·LDL 증가·관상동맥 질환 위험"),
    ("chol",     "콜레스테롤",   "Cholesterol",    "mg",   "macro",   300, None,  16, "<300 mg/일 (KDRI 2020)",
        "동맥경화·심혈관 질환 위험 (개인차 큼)"),
    ("sugar",    "당류",         "Sugars",         "g",    "macro",    62, None,  17, "<10% 에너지 (KDRI 2020)",
        "비만·인슐린 저항성·지방간·치아 우식"),
    ("fiber",    "식이섬유",     "Dietary fiber",  "g",    "macro",    25, None,  18, None, None),
    ("sodium",   "나트륨",       "Sodium",         "mg",   "macro",  2000, None,  19, "WHO 권고 상한",
        "고혈압·심혈관 부담·신장 부담·뇌졸중 위험"),

    # ---- minerals ----
    ("ca",       "칼슘",         "Calcium",        "mg",   "mineral", 800, 2500,  20, None,
        "신장결석·고칼슘혈증·다른 미네랄(철·아연) 흡수 방해"),
    ("p",        "인",           "Phosphorus",     "mg",   "mineral", 700, 3500,  21, None,
        "칼슘 흡수 방해·골밀도 감소·신장 부담"),
    ("fe",       "철분",         "Iron",           "mg",   "mineral",  10,   45,  22, None,
        "위장 자극·간 손상·산화 스트레스 증가"),
    ("mg",       "마그네슘",     "Magnesium",      "mg",   "mineral", 370,  350,  23, "UL은 보충제 형태 기준",
        "(보충제 과량) 설사·구역질·저혈압·전해질 불균형"),
    ("zn",       "아연",         "Zinc",           "mg",   "mineral",  10,   35,  24, None,
        "구리 흡수 방해·HDL 감소·면역 저하 (장기 과량)"),
    ("cu",       "구리",         "Copper",         "µg",   "mineral", 850,10000,  25, None,
        "간 손상·구토·신경계 증상 (만성 축적)"),
    ("mn",       "망간",         "Manganese",      "mg",   "mineral",   4,   11,  26, None,
        "신경계 영향 (장기 과다 시 파킨슨 유사 증상)"),
    ("k",        "칼륨",         "Potassium",      "mg",   "mineral",3500, None,  27, None, None),
    ("se",       "셀레늄",       "Selenium",       "µg",   "mineral",  60,  400,  28, None,
        "셀레노시스(탈모·손톱 변형·신경 손상·구취)"),
    ("iodine",   "요오드",       "Iodine",         "µg",   "mineral", 150, 2400,  29, None,
        "갑상선 기능 이상 (항진/저하 양방향)"),

    # ---- vitamins ----
    ("vit_a",    "비타민 A",     "Vitamin A",      "µg",   "vitamin", 800, 3000,  30, "RAE",
        "간 독성·두통·시야 흐림·기형 유발 (임산부 주의)"),
    ("vit_c",    "비타민 C",     "Vitamin C",      "mg",   "vitamin", 100, 2000,  31, None,
        "위장 장애(설사)·신장결석 위험 (장기 고용량)"),
    ("vit_d",    "비타민 D",     "Vitamin D",      "µg",   "vitamin",  10,  100,  32, None,
        "고칼슘혈증·신장 손상·연부조직 석회화"),
    ("vit_e",    "비타민 E",     "Vitamin E",      "mg",   "vitamin",  12,  540,  33, "α-토코페롤",
        "출혈 경향 증가·항응고제와 상호작용"),
    ("vit_k",    "비타민 K",     "Vitamin K",      "µg",   "vitamin",  75, None,  34, None, None),
    ("b1",       "비타민 B1",    "Thiamin",        "mg",   "vitamin", 1.2, None,  35, None, None),
    ("b2",       "비타민 B2",    "Riboflavin",     "mg",   "vitamin", 1.5, None,  36, None, None),
    ("b3",       "나이아신",     "Niacin",         "mg",   "vitamin",  16,   35,  37, "UL은 보충제 형태 기준",
        "안면홍조·간 독성·혈당 변동 (보충제 고용량 시)"),
    ("b5",       "판토텐산",     "Pantothenic acid","mg",  "vitamin",   5, None,  38, "B5", None),
    ("b6",       "비타민 B6",    "Pyridoxine",     "mg",   "vitamin", 1.5,  100,  39, None,
        "말초신경병증·감각 이상 (장기 고용량)"),
    ("folate",   "엽산",         "Folate",         "µg",   "vitamin", 400, 1000,  40, None,
        "B12 결핍 가림·신경 손상 지연 (특히 노년)"),
    ("b12",      "비타민 B12",   "Cobalamin",      "µg",   "vitamin", 2.4, None,  41, None, None),
    ("biotin",   "비오틴",       "Biotin",         "µg",   "vitamin",  30, None,  42, None, None),
    ("choline",  "콜린",         "Choline",        "mg",   "vitamin", 550, 3500,  43, "비타민양 영양소 (KDRI AI)",
        "어시(생선 비린내)·저혈압·발한·간 독성 (고용량)"),

    # ---- fatty acids ----
    ("omega3",   "오메가-3",     "Omega-3 (n-3)",  "g",    "other",   1.6, None,  50, "ALA + EPA + DHA 합산. KDRI AI", None),
    ("omega6",   "오메가-6",     "Omega-6 (n-6)",  "g",    "other",    13, None,  51, "Linoleic acid 위주. KDRI AI", None),
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
            "kcal": 535, "carb": 49, "protein": 25, "fat": 27,
            "sat_fat": 6, "trans_fat": 0.2, "chol": 50, "sugar": 7, "fiber": 3, "sodium": 1010,
            "ca": 80, "p": 240, "fe": 3.0, "mg": 30, "zn": 1.8, "mn": 0.3, "k": 370,
            "vit_a": 50, "vit_c": 2, "vit_d": 0.1, "b12": 0.5, "folate": 80, "b3": 6, "b5": 1.0,
            "choline": 50,
            "omega3": 0.3, "omega6": 4.5,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "lunch",
        "food": "KFC 너겟",
        "serving": "5조각",
        "values": {
            "kcal": 235, "carb": 12, "protein": 13, "fat": 14,
            "sat_fat": 3, "trans_fat": 0.1, "chol": 35, "fiber": 1, "sodium": 480,
            "ca": 15, "p": 120, "fe": 0.8, "mg": 14, "zn": 0.6, "k": 200,
            "vit_a": 10, "vit_d": 0.1, "b12": 0.3, "folate": 20, "b3": 3, "b5": 0.4,
            "choline": 35,
            "omega3": 0.15, "omega6": 2.5,
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
            "kcal": 435, "carb": 68, "protein": 9, "fat": 14,
            "sat_fat": 7, "trans_fat": 0.05, "sugar": 3, "fiber": 3, "sodium": 900,
            "ca": 50, "p": 80, "fe": 1.5, "mg": 20, "zn": 0.6, "mn": 0.5, "k": 200,
            "vit_a": 30, "vit_c": 1, "folate": 60, "b3": 3,
            "omega3": 0.05, "omega6": 2.0,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "슬라이스 치즈",
        "serving": "1장 (18g)",
        "values": {
            "kcal": 60, "carb": 1, "protein": 3.5, "fat": 4.5,
            "sat_fat": 3, "chol": 15, "sugar": 0.5, "sodium": 230,
            "ca": 120, "p": 80, "fe": 0.1, "mg": 5, "zn": 0.5, "k": 17,
            "vit_a": 60, "vit_d": 0.1, "b12": 0.2, "folate": 5, "b5": 0.1,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "계란",
        "serving": "2개",
        "values": {
            "kcal": 150, "carb": 1, "protein": 12, "fat": 10,
            "sat_fat": 3.3, "chol": 370, "sodium": 140,
            "ca": 56, "p": 190, "fe": 1.8, "mg": 14, "zn": 1.3, "se": 30, "k": 138, "iodine": 50,
            "vit_a": 160, "vit_d": 2.0, "vit_e": 1, "b2": 0.5, "b5": 1.5, "b12": 1.1, "folate": 90,
            "choline": 250,
            "omega3": 0.07, "omega6": 1.3,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "블루베리",
        "serving": "20알 (~30g)",
        "values": {
            "kcal": 17, "carb": 4, "sugar": 3, "fiber": 0.7, "k": 23, "mn": 0.1,
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
            "kcal": 30, "carb": 1.5, "protein": 3, "fat": 1.5,
            "sat_fat": 0.9, "chol": 3, "sugar": 1, "sodium": 10,
            "ca": 35, "p": 30, "zn": 0.2, "k": 40, "b2": 0.1, "b5": 0.1, "b12": 0.2,
            "choline": 5,
        },
    },
    {
        "profile_slug": "tteoni",
        "date": "2026-05-20",
        "meal": "dinner",
        "food": "땅콩",
        "serving": "10알 (~10g)",
        "values": {
            "kcal": 57, "carb": 1.6, "protein": 2.6, "fat": 5,
            "sat_fat": 0.7, "sugar": 0.4, "fiber": 0.8,
            "ca": 9, "p": 38, "fe": 0.5, "mg": 17, "zn": 0.3, "cu": 50, "mn": 0.2, "k": 70,
            "vit_e": 0.8, "b3": 1.2, "b5": 0.18, "folate": 25,
            "omega3": 0.001, "omega6": 1.6,
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
            "kcal": 350, "carb": 50, "protein": 4, "fat": 14,
            "sat_fat": 5, "sugar": 7, "fiber": 0.5, "sodium": 280,
            "ca": 10, "p": 60, "fe": 0.5, "mg": 8, "zn": 0.4, "k": 80, "folate": 10,
            "omega3": 0.05, "omega6": 6.0,
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
            "b1": 50, "b2": 50, "b3": 50, "b5": 50, "b6": 60, "b12": 200,
            "folate": 400, "biotin": 1000,
            "ca": 100, "mg": 50, "zn": 15, "cu": 2000, "mn": 2, "se": 200, "iodine": 150,
        },
    },
]
