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
    "legpress": {"name": "레그프레스", "cat": "lower", "note1": "허리 등받이 밀착, 가동범위 3/4", "pf": "seated-leg-press"},
    "backext": {"name": "백 익스텐션", "cat": "lower", "note2": "통증 없는 가동범위, 맨몸부터", "pf": "back-extension"},
    "rdl": {"name": "덤벨 RDL", "cat": "lower", "note2": "허리 중립 유지 — 햄스트링이 당기는 느낌이 정답", "pf": "dumbbell-romanian-deadlift"},
    "chestpress": {"name": "체스트프레스", "cat": "upper", "pf": "chest-press-machine"},
    "shoulderpress": {"name": "숄더프레스", "cat": "upper", "note2": "등받이에 등 붙이고", "pf": "shoulder-press-machine"},
    "latpulldown": {"name": "랫풀다운", "cat": "upper", "pf": "lat-pulldown"},
    "seatedrow": {"name": "시티드 로우", "cat": "upper", "pf": "seated-cable-row"},
    "legcurl": {"name": "레그컬", "cat": "lower", "pf": "seated-leg-curl"},
}
PHASE1 = ["legpress", "chestpress", "latpulldown", "seatedrow", "legcurl"]
HINGES = ("backext", "rdl")
PHASE1_TARGET = 6  # 1단계 졸업 세션 수
RDL_FROM_WEEK = 7  # 힙 힌지: 4~6주차 백 익스텐션 → 7주차~ 덤벨 RDL


def _phase2(hinge: str) -> List[str]:
    return ["legpress", hinge, "chestpress", "shoulderpress", "latpulldown", "seatedrow", "legcurl"]


# 머신 최소 단위 5kg → 증량 폭 전 종목 +5kg. 덤벨 RDL만 +2.5kg 가능.
def _inc(ex: str) -> float:
    return 2.5 if ex == "rdl" else 5.0


# 상체는 +5kg 점프(~17%)가 커서 반복 상한 15회로 완충.
def _rep_max(ex: str) -> int:
    return 15 if EXERCISES[ex]["cat"] == "upper" else 12


def _guide_url(ex: str) -> str:
    return f"https://planfit.ai/ko/exercise/{EXERCISES[ex]['pf']}"


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _ex_sets(session: WorkoutSession, ex: str) -> List[WorkoutSet]:
    return sorted((t for t in session.sets if t.exercise == ex), key=lambda t: t.set_no)


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
    return top.weight_kg, top.weight_kg + _inc(ex)


def _program_week(sessions: List[WorkoutSession], as_of: date) -> Optional[int]:
    """첫 세션이 속한 주(월요일 시작)가 1주차."""
    if not sessions:
        return None
    start = _monday_of(date.fromisoformat(sessions[0].session_date))
    week = (_monday_of(as_of) - start).days // 7 + 1
    return week if week >= 1 else None


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


def build_plan(slug: str, sessions: List[WorkoutSession], as_of: date) -> WorkoutPlan:
    """세션 이력(날짜 오름차순)으로 현재 상태·다음 세션 처방·로드맵을 만든다."""
    p1_done = sum(1 for s in sessions if s.phase == 1)
    phase = 2 if p1_done >= PHASE1_TARGET else 1
    week = _program_week(sessions, as_of)
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
            detail="하체 3×8~12 · 상체 3×8~15, 힙 힌지 추가",
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
            detail="가벼운 덤벨부터, 허리 중립 (+2.5kg 단위 증량 가능)",
            status="current" if hinge == "rdl" else _milestone_status(week, RDL_FROM_WEEK, None),
        ),
    ]

    rules = [
        "주 3회, 세션당 전 종목 3세트.",
        "2단계 증량 트리거: 3세트 모두 반복 상한(하체 12회 · 상체 15회) 성공 → +5kg(머신 한 칸) 올리고 8회부터 재시작.",
        "덤벨 RDL만 +2.5kg 단위 증량 가능 (머신 제약 무관).",
        "허리 불편감 3/10 이상이 다음날에도 지속되면 마지막 올린 중량 롤백. 다리 저림·방사통·힘 빠짐 신규 발생 시 진료 대상.",
    ]

    last = sessions[-1] if sessions else None
    caution = None
    if last and last.discomfort is not None and last.discomfort >= 3:
        caution = (
            f"{last.session_date} 세션 불편감 {last.discomfort}/10 — 다음날에도 지속되면 "
            "마지막 올린 중량을 롤백하세요. 다리 저림·방사통·힘 빠짐이 새로 생겼다면 진료 대상."
        )

    week_start = _monday_of(as_of).isoformat()
    return WorkoutPlan(
        profile=slug,
        as_of=as_of.isoformat(),
        started=sessions[0].session_date if sessions else None,
        sessions_total=len(sessions),
        sessions_this_week=sum(1 for s in sessions if s.session_date >= week_start),
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
