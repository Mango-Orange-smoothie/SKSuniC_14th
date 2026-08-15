"""관계DB를 읽는 쪽의 규칙 — CLAUDE.md 규칙 1·2, 그리고 "한 인자에 defect가 둘".

여기 있는 것 대부분은 **DB 값을 베끼지 않는다.** 예를 들어 "CLN_Flow의 tier는 T1"이라고
적으면 DB가 바뀌는 순간 테스트가 거짓말이 된다(규칙 1 위반). 대신 *관계*를 검사한다 —
"T1 짝이 T2 짝보다 먼저 골라진다", "per_defect가 인자 레벨을 이긴다" 같은 것.

예외는 도메인 방향 하나다. "세정 유량은 낮을수록 위험"은 멘토 확정 사실이라 데이터가
아니라 물리가 정한다(규칙 6). 이게 뒤집히면 DB 쪽을 의심해야 하므로 값으로 못 박는다.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# _usable_defects — per_defect.alert_usable이 인자 레벨을 이긴다
# ---------------------------------------------------------------------------

def test_per_defect가_False면_그_짝만_빠진다(bhi):
    meta = {
        "defects": ["Remain_Coat", "Particle"],
        "alert_usable": True,
        "per_defect": {"Particle": {"alert_usable": False}},
    }
    assert bhi._usable_defects(meta) == ["Remain_Coat"]


def test_per_defect가_없으면_인자_레벨을_따른다(bhi):
    meta = {"defects": ["Remain_Coat"], "alert_usable": False, "per_defect": {}}
    assert bhi._usable_defects(meta) == []


def test_per_defect_True는_인자_레벨_False를_이긴다(bhi):
    meta = {
        "defects": ["Particle"],
        "alert_usable": False,
        "per_defect": {"Particle": {"alert_usable": True}},
    }
    assert bhi._usable_defects(meta) == ["Particle"]


def test_alert_usable이_아예_없으면_사용_가능으로_본다(bhi):
    assert bhi._usable_defects({"defects": ["Particle"]}) == ["Particle"]


# ---------------------------------------------------------------------------
# _scored_defects — 장비 대표 점수는 경보용의 부분집합
# ---------------------------------------------------------------------------

def test_방향이_반박된_짝은_대표_점수에서_빠진다(bhi, monkeypatch):
    meta = {"defects": ["Remain_Coat", "Micro_Crack"], "alert_usable": True, "per_defect": {}}
    monkeypatch.setattr(bhi, "VERIFIED_PAIRS", {("X", "Remain_Coat")})
    assert bhi._usable_defects(meta) == ["Remain_Coat", "Micro_Crack"]  # 경보는 둘 다 나간다
    assert bhi._scored_defects(meta, "X") == ["Remain_Coat"]  # 점수는 하나만


def test_tier표를_못_읽으면_전부_채택으로_폴백(bhi, monkeypatch):
    """조용히 빠지는 것보다 예전 동작이 낫다 — _load_verified_pairs의 None 계약."""
    meta = {"defects": ["Remain_Coat", "Micro_Crack"], "alert_usable": True, "per_defect": {}}
    monkeypatch.setattr(bhi, "VERIFIED_PAIRS", None)
    assert bhi._scored_defects(meta, "X") == ["Remain_Coat", "Micro_Crack"]


def test_대표_점수는_언제나_경보용의_부분집합(bhi):
    """실제 DB 전체를 훑어서 이 포함관계가 깨진 인자가 없는지 본다."""
    for factor, meta in bhi.HEALTH_FACTORS.items():
        scored = set(bhi._scored_defects(meta, factor))
        assert scored <= set(bhi._usable_defects(meta)), factor


# ---------------------------------------------------------------------------
# _pair_tier_rank — 컬럼당 하나를 골라야 할 때 "파일 행 순서"가 아니라 tier로 고른다
# ---------------------------------------------------------------------------

def test_급한_tier가_낮은_숫자(bhi):
    ranks = [bhi._TIER_RANK[t] for t in ("T1", "T2", "T3", "T4", "M1")]
    assert ranks == sorted(ranks)


def test_모르는_짝은_맨_뒤(bhi):
    unknown = bhi._pair_tier_rank("NoSuchFactor", "NoSuchDefect")
    assert unknown > max(bhi._TIER_RANK.values())


def _multi_defect_factors(bhi):
    return [(f, ds) for f, meta in bhi.HEALTH_FACTORS.items()
            if len(ds := bhi._usable_defects(meta)) > 1]


def test_다중_defect_인자가_실제로_있다(bhi):
    """이게 0이면 아래 테스트들이 조용히 아무것도 검사하지 않게 된다."""
    assert _multi_defect_factors(bhi)


def test_행_순서를_거꾸로_넣어도_급한_짝이_먼저(bhi):
    """화면 대표값을 고르는 자리(load_defect_threshold_map)가 쓰는 정렬 그대로 재현한다.

    동점(같은 tier)은 갈리지 않는 게 정상이다 — 실제로 Cooling_Flow의 Chipping/Micro_Crack이
    둘 다 같은 tier다. 검사할 것은 "더 급한 짝이 덜 급한 짝에 밀리지 않는가" 하나다.
    """
    for factor, defects in _multi_defect_factors(bhi):
        best = min(bhi._pair_tier_rank(factor, d) for d in defects)
        for order in (defects, list(reversed(defects))):
            picked = sorted(order, key=lambda d: bhi._pair_tier_rank(factor, d))[0]
            assert bhi._pair_tier_rank(factor, picked) == best, f"{factor}: {order} -> {picked}"


def test_T1_짝은_T2_짝에_안_밀린다(bhi):
    """CLAUDE.md가 든 실제 사례 — CLN_Flow의 Remain_Coat(T1)가 Particle(T2)에 밀렸었다."""
    graded = [(f, ds) for f, ds in _multi_defect_factors(bhi)
              if len({bhi._pair_tier_rank(f, d) for d in ds}) > 1]
    assert graded, "tier가 갈리는 다중 defect 인자가 없어 이 규칙을 검증할 대상이 없다"
    for factor, defects in graded:
        ranked = sorted(defects, key=lambda d: bhi._pair_tier_rank(factor, d))
        assert bhi._pair_tier_rank(factor, ranked[0]) < bhi._pair_tier_rank(factor, ranked[-1])


# ---------------------------------------------------------------------------
# direction_of
# ---------------------------------------------------------------------------

def test_관계DB에_없는_컬럼은_either(bhi):
    """방향을 모르면 양방향 이상으로 보수적으로 취급한다."""
    assert bhi.direction_of("NoSuchColumn") == "either"


def test_세정_유량은_낮을수록_위험(bhi):
    """멘토 확정 시나리오(Cleaning Failure -> CLN_Flow 감소). 물리가 정하는 방향이다."""
    assert bhi.direction_of("CLN_Flow") == "down"


def test_모든_인자의_방향이_셋_중_하나(bhi):
    for factor in bhi.HEALTH_FACTORS:
        assert bhi.direction_of(factor) in ("up", "down", "either"), factor
