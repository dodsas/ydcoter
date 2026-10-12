"""운동 프로그램 정의와 계획 계산 (GET /workout/plan).

web/workout.html 의 JS(EXERCISES/PHASE1/PHASE2/증량 규칙)와 같은 규칙을
공유한다 — 프로그램 규칙을 바꾸면 양쪽을 함께 수정할 것.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from app.models import (
    WorkoutPlan,
    WorkoutPlanExercise,
    WorkoutPlanMilestone,
    WorkoutSession,
    WorkoutSet,
)

EXERCISES = {
    "legpress": {"name": "레그프레스", "cat": "lower", "note1": "허리 등받이 밀착, 가동범위 3/4", "note2": "11자 정렬 · 깊이 컷 · 휴식 2~3분 또는 심박 110~115 복귀", "pf": "seated-leg-press"},
    "backext": {"name": "백 익스텐션", "cat": "lower", "note2": "통증 없는 가동범위, 맨몸부터 — 코어 신선한 초반 고정", "pf": "back-extension"},
    "rdl": {"name": "덤벨 RDL", "cat": "lower", "note2": "허리 중립 유지 — 햄스트링이 당기는 느낌이 정답", "pf": "dumbbell-romanian-deadlift"},
    "chestpress": {"name": "체스트프레스", "cat": "upper", "note2": "프레스 1번 — 어깨가 가장 신선할 때 큰 것부터", "pf": "chest-press-machine"},
    "shoulderpress": {"name": "숄더프레스", "cat": "upper", "note2": "예열(외회전+스캡 1분) 후 진입 · 등받이 밀착 · 세트 간 2분 · 판정은 왼쪽 기준", "pf": "shoulder-press-machine"},
    "latpulldown": {"name": "랫풀다운", "cat": "upper", "note2": "완충 1 — 당기기로 전면삼각근은 대기 전력만", "pf": "lat-pulldown"},
    "seatedrow": {"name": "시티드 로우", "cat": "upper", "note2": "마지막 — 어깨 안정화 부하뿐이라 피로 상태에서도 안전", "pf": "seated-cable-row"},
    "legcurl": {"name": "레그컬", "cat": "lower", "note2": "프리텐션 · 발끝 세우기 — 숄더 직전 고정 칸(어깨 개입 0)", "pf": "seated-leg-curl"},
}
PHASE1 = ["legpress", "chestpress", "latpulldown", "seatedrow", "legcurl"]
HINGES = ("backext", "rdl")
PHASE1_TARGET = 6  # 1단계 졸업 세션 수
RDL_FROM_WEEK = 7  # 힙 힌지: 4~6주차 백 익스텐션 → 7주차~ 덤벨 RDL
# 허리 리스크 종목(힙 힌지)은 반복 상한을 채워도 같은 중량을 최소 2주 유지
# 후 증량 — 백 익스텐션 10→15→20kg 연속 +5kg가 L5 에피소드로 이어진 이력.
HINGE_HOLD_DAYS = 14


# 기본 배열(7종): 하체·허리 리스크 종목은 신선할 때 앞으로, 프레스 사이에
# 완충 2칸(랫풀·레그컬), 가장 잘 크는 로우는 후순위 손해가 제일 작아 마지막.
def _phase2(hinge: str) -> List[str]:
    return ["legpress", hinge, "chestpress", "latpulldown", "legcurl", "shoulderpress", "seatedrow"]


# 머신 최소 단위 5kg → 증량 폭 전 종목 +5kg.
# 덤벨 RDL만 예외: 아령 하나당 2kg 단위 조절 → 기록(한 쪽 무게) 기준 +2kg.
def _inc(ex: str) -> float:
    return 2.0 if ex == "rdl" else 5.0


# 반복 상한 = 조절 단위 기준: 머신(+5kg 한 칸, 점프 9~14%)은 15회까지 볼륨으로
# 완충 — 특히 레그프레스는 허리 부담상 중량보다 볼륨 우선. 덤벨 RDL만
# +2kg 미세 조절이 가능해 완충 불필요 → 12회.
def _rep_max(ex: str) -> int:
    return 12 if ex == "rdl" else 15


def _guide_url(ex: str) -> str:
    return f"https://planfit.ai/ko/exercise/{EXERCISES[ex]['pf']}"


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _ex_sets(session: WorkoutSession, ex: str) -> List[WorkoutSet]:
    """수행한 세트만 — skipped 또는 0회(시도만 하고 못 든 기록)는 제외."""
    return sorted(
        (t for t in session.sets if t.exercise == ex and not t.skipped and t.reps != 0),
        key=lambda t: t.set_no,
    )


def _last_session_with(sessions: List[WorkoutSession], ex: str) -> Optional[WorkoutSession]:
    for s in reversed(sessions):
        if _ex_sets(s, ex):
            return s
    return None


def _best_set(sets: List[WorkoutSet]) -> Optional[WorkoutSet]:
    """최고 세트 — 중량 우선, 같은 중량이면 횟수."""
    done = [t for t in sets if t.weight_kg is not None or t.reps is not None]
    if not done:
        return None
    return max(done, key=lambda t: (t.weight_kg or 0, t.reps or 0))


def _hit_rep_top(sets: List[WorkoutSet], ex: str) -> bool:
    """3세트 모두 반복 상한 성공 — 2단계 증량 트리거."""
    done = [t for t in sets if t.reps is not None]
    return len(done) >= 3 and all(t.reps >= _rep_max(ex) for t in done)


def _weight_history(sessions: List[WorkoutSession], ex: str) -> List[tuple[str, float, float]]:
    """세션별 (날짜, 최고 중량, 볼륨=Σ중량×반복) — 수행 세트 기준, 오래된 순."""
    out = []
    for s in sessions:
        sets = _ex_sets(s, ex)
        top = _best_set(sets)
        if top is None or top.weight_kg is None:
            continue
        vol = sum((t.weight_kg or 0) * (t.reps or 0) for t in sets)
        out.append((s.session_date, top.weight_kg, vol))
    return out


def _hinge_hold_active(sessions: List[WorkoutSession], ex: str, weight: float) -> bool:
    """힙 힌지 2주 유지 규칙 — 현재 중량을 처음 든 날로부터 14일 미만이면 증량 보류."""
    if ex not in HINGES:
        return False
    hist = _weight_history(sessions, ex)
    first = next((d for d, w, _ in hist if w >= weight), None)
    if first is None:
        return False
    last = hist[-1][0]
    return (date.fromisoformat(last) - date.fromisoformat(first)).days < HINGE_HOLD_DAYS


def _progression(sessions: List[WorkoutSession], ex: str) -> Optional[tuple[float, float]]:
    last = _last_session_with(sessions, ex)
    if not last or last.phase != 2:
        return None
    sets = _ex_sets(last, ex)
    if not _hit_rep_top(sets, ex):
        return None
    top = _best_set(sets)
    if top is None or top.weight_kg is None:
        return None
    if _hinge_hold_active(sessions, ex, top.weight_kg):
        return None
    return top.weight_kg, top.weight_kg + _inc(ex)


def _stall_stats(sessions: List[WorkoutSession], ex: str) -> tuple[Optional[int], Optional[str]]:
    """정체 카운터: (마지막 증량 후 수행 세션 수, 최근 3세션 볼륨 추세 up|flat|down)."""
    hist = _weight_history(sessions, ex)
    if not hist:
        return None, None
    since = 0
    for i in range(len(hist) - 1, 0, -1):
        if hist[i][1] > hist[i - 1][1]:
            break
        since += 1
    trend = None
    if len(hist) >= 2:
        vols = [v for _, _, v in hist[-3:]]
        base = vols[0] or 1
        change = (vols[-1] - vols[0]) / base
        trend = "up" if change > 0.05 else "down" if change < -0.05 else "flat"
    return since, trend


def _program_week(sessions: List[WorkoutSession]) -> Optional[int]:
    """마지막 세션이 속한 주차 — 첫 세션 주(월요일 시작)가 1주차.
    오늘 날짜에 의존하지 않고 기록된 이력만으로 계산한다."""
    if not sessions:
        return None
    start = _monday_of(date.fromisoformat(sessions[0].session_date))
    last = _monday_of(date.fromisoformat(sessions[-1].session_date))
    return (last - start).days // 7 + 1


def _pick_hinge(sessions: List[WorkoutSession], week: Optional[int]) -> str:
    """마지막으로 쓴 힌지 종목 우선 — 단 RDL로 넘어간 뒤엔 되돌리지 않고,
    가이드 주차(7주차~)가 되면 백 익스텐션이어도 RDL을 제안."""
    last_used = next(
        (t.exercise for s in reversed(sessions) for t in s.sets if t.exercise in HINGES),
        None,
    )
    if last_used == "rdl" or (week is not None and week >= RDL_FROM_WEEK):
        return "rdl"
    return last_used or "backext"


def _milestone_status(week: Optional[int], start_w: int, end_w: Optional[int]) -> str:
    if week is None or week < start_w:
        return "upcoming"
    if end_w is not None and week > end_w:
        return "done"
    return "current"


def build_plan(slug: str, sessions: List[WorkoutSession]) -> WorkoutPlan:
    """세션 이력(날짜 오름차순)만으로 전체 플랜을 만든다 — 기준일 없음."""
    p1_done = sum(1 for s in sessions if s.phase == 1)
    phase = 2 if p1_done >= PHASE1_TARGET else 1
    week = _program_week(sessions)
    hinge = _pick_hinge(sessions, week) if phase == 2 else None
    plan = PHASE1 if phase == 1 else _phase2(hinge)

    exercises: List[WorkoutPlanExercise] = []
    for order, ex in enumerate(plan, start=1):
        meta = EXERCISES[ex]
        last = _last_session_with(sessions, ex)
        last_sets = _ex_sets(last, ex) if last else []
        prog = _progression(sessions, ex) if phase == 2 else None
        suggested = (
            prog[1]
            if prog
            else next((t.weight_kg for t in last_sets if t.weight_kg is not None), None)
        )
        note = (meta.get("note1") if phase == 1 else meta.get("note2")) or meta.get("note1")
        since, trend = _stall_stats(sessions, ex) if phase == 2 else (None, None)
        exercises.append(
            WorkoutPlanExercise(
                exercise=ex,
                name=meta["name"],
                category=meta["cat"],
                order=order,
                target_reps_min=10 if phase == 1 else 8,
                target_reps_max=10 if phase == 1 else _rep_max(ex),
                suggested_weight_kg=suggested,
                progression_due=prog is not None,
                progression_from_kg=prog[0] if prog else None,
                progression_to_kg=prog[1] if prog else None,
                sessions_since_increase=since,
                volume_trend=trend,
                last_date=last.session_date if last else None,
                last_sets=last_sets,
                note=note,
                guide_url=_guide_url(ex),
            )
        )

    milestones = [
        WorkoutPlanMilestone(
            key="phase1",
            title="1단계 — 머신 5종 적응기",
            period="1~2주차",
            detail=f"5종 3×10 · 총 {PHASE1_TARGET}세션 ({p1_done}/{PHASE1_TARGET} 완료)",
            status="done" if p1_done >= PHASE1_TARGET else "current",
        ),
        WorkoutPlanMilestone(
            key="phase2",
            title="2단계 — 7종 전신",
            period="3주차~약 3개월",
            detail="머신 3×8~15 · 덤벨 RDL 3×8~12, 힙 힌지 추가",
            status="current" if phase == 2 else "upcoming",
        ),
        WorkoutPlanMilestone(
            key="hinge_backext",
            title="힙 힌지: 백 익스텐션",
            period="4~6주차",
            detail="통증 없는 가동범위, 맨몸부터",
            status="done" if hinge == "rdl" else _milestone_status(week, 4, RDL_FROM_WEEK - 1),
        ),
        WorkoutPlanMilestone(
            key="hinge_rdl",
            title="힙 힌지: 덤벨 RDL",
            period=f"{RDL_FROM_WEEK}주차~",
            detail="가벼운 덤벨부터, 허리 중립 (아령 하나당 2kg 단위 — 한 쪽 기준 +2kg 증량)",
            status="current" if hinge == "rdl" else _milestone_status(week, RDL_FROM_WEEK, None),
        ),
    ]

    rules = [
        "주 3회, 세션당 전 종목 3세트.",
        "2단계 증량 트리거: 3세트 모두 반복 상한(머신 15회 · 덤벨 RDL 12회) 성공 → 한 칸 올리고 8회부터 재시작.",
        "머신은 15회까지 볼륨으로 완충 후 +5kg — 특히 레그프레스는 허리 부담상 중량보다 반복수 우선.",
        "덤벨 RDL만 +2kg 단위 증량 (아령 하나당 2kg 조절 — 기록·증량 모두 한 쪽 무게 기준).",
        "힙 힌지(백 익스텐션·덤벨 RDL)는 상한을 채워도 같은 중량 2주 유지 후 증량 — 연속 +5kg가 허리 에피소드로 이어진 이력.",
        "레그프레스와 힙 힌지를 같은 세션에서 동시에 증량하지 않기 — 허리 부하 종목은 한 번에 하나만.",
        "허리 불편감 3/10 이상이 다음날에도 지속되면 마지막 올린 중량 롤백. 다리 저림·방사통·힘 빠짐 신규 발생 시 진료 대상.",
    ]

    last = sessions[-1] if sessions else None
    caution = None
    if last and last.discomfort is not None and last.discomfort >= 3:
        caution = (
            f"{last.session_date} 세션 불편감 {last.discomfort}/10 — 다음날에도 지속되면 "
            "마지막 올린 중량을 롤백하세요. 다리 저림·방사통·힘 빠짐이 새로 생겼다면 진료 대상."
        )

    return WorkoutPlan(
        profile=slug,
        started=sessions[0].session_date if sessions else None,
        sessions_total=len(sessions),
        program_week=week,
        phase=phase,
        phase1_done=p1_done,
        phase1_target=PHASE1_TARGET,
        hinge=hinge,
        caution=caution,
        next_session=exercises,
        milestones=milestones,
        rules=rules,
    )
