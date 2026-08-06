"""통합 DB 확장 — AI Agent 처음부터 끝까지(SOP·HealthIndex 출력)에 필요한 나머지 테이블

build_unified_relationship_db.py가 만든 rel_01~05는 '판정'까지다.
김시우님이 Agent를 끝까지(엔지니어 화면 출력) 만들려면 아래가 더 필요하다.

  rel_05  위험 경계값     4개 defect 전부로 확장 (기존엔 Chipping/Micro_Crack만)
  rel_06  SOP 초안        Jun Goal6 + 현재 판정 대조 (낡은 SOP를 표시)
  rel_07  HealthIndex 연결 김시우 Goal5 cause_factors 11개 -> 현재 판정 반영표
  rel_08  구간별 불량률    "이 값이면 불량률 몇 %"
  rel_09  SHAP 전역       인자별 평균 기여도
  rel_10  SHAP 개별       "이 LOT은 왜 위험한가" — 설명 전용
  rel_11  3방법 대조      통계/RF/SHAP 순위 나란히
  rel_12  티어표          원인 트랙 / 감시지표 트랙 분리
  rel_13  Vibration 얽힘  daeho Goal3 — Vibration이 쟁점이라 근거를 같이 싣는다

방침: 걸러내지 않는다. 확신이 낮은 것도 status/confidence를 달아서 전부 싣는다.
Agent가 무엇을 말하지 말아야 하는지는 필드로 판단하게 한다.

실행 (저장소 루트에서, build_unified_relationship_db.py 다음에):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_full_db_extension.py"
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
REPO = OUT.parent
MY_DB = REPO / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"
JUN_DIR = "26.08.01_2229_Goal2_통합_전체방법론_4개defect"
SOP_DIR = "26.08.02_1952_Goal6_유효인자통합_SOP초안"
GOAL5_DIR = "26.08.01_Goal5_HealthIndex_Dashboard_김시우"


def git_text(ref: str, path: str) -> str:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git show 실패: {ref}:{path}\n{r.stderr[:300]}")
    return r.stdout


def git_csv(ref: str, path: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(git_text(ref, path)))


factors = pd.read_csv(OUT / "rel_01_factors.csv", encoding="utf-8-sig")
STATUS = {(r.defect, r.factor): r for _, r in factors.iterrows()}


# ============================================================ rel_05 위험 경계값 (4개 defect)
def thresholds() -> pd.DataFrame:
    rows = []
    mine = pd.read_csv(MY_DB / "db_03_thresholds.csv", encoding="utf-8-sig")
    for _, r in mine.iterrows():
        rows.append(dict(defect=r.target, factor=r.variable, threshold_z=r.threshold_z,
                         threshold_raw_approx=r.threshold_raw_approx,
                         risky_direction=r.risky_direction,
                         defect_rate_safe_pct=r.defect_rate_below,
                         defect_rate_risky_pct=r.defect_rate_above,
                         risk_ratio=r.risk_ratio, n_safe=r.n_below, n_risky=r.n_above,
                         source="JHdaimma db_03", note=r.note))
    for f, d in [("chipping", "Chipping"), ("micro_crack", "Micro_Crack"),
                 ("particle", "Particle"), ("remain_coat", "Remain_Coat")]:
        t = git_csv("origin/Jun", f"{JUN_DIR}/05_{f}_thresholds.csv")
        for _, r in t.iterrows():
            rows.append(dict(defect=d, factor=r.column, threshold_z=r.threshold_z,
                             threshold_raw_approx=None, risky_direction=r.risky_direction,
                             defect_rate_safe_pct=r.defect_rate_below_pct,
                             defect_rate_risky_pct=r.defect_rate_above_pct,
                             risk_ratio=r.risk_ratio, n_safe=r.n_below, n_risky=r.n_above,
                             source="Jun 통합본 05", note="DecisionTree stump(depth=1) 경계값"))
    t = pd.DataFrame(rows)
    # 현재 판정을 붙여, 기각된 인자의 경계값을 Agent가 경보에 쓰지 않도록 한다.
    t["current_status"] = [STATUS[(r.defect, r.factor)].final_status
                           if (r.defect, r.factor) in STATUS else "(판정없음)"
                           for _, r in t.iterrows()]
    t["usable_for_alert"] = t.current_status.isin(
        ["confirmed_cause", "confirmed_monitor", "candidate"])
    return t.sort_values(["defect", "usable_for_alert", "risk_ratio"],
                         ascending=[True, False, False]).reset_index(drop=True)


# ============================================================ rel_06 SOP 초안
def sop() -> pd.DataFrame:
    s = git_csv("origin/Jun", f"{SOP_DIR}/02_SOP_초안.csv")
    cur, act, stale = [], [], []
    for _, r in s.iterrows():
        k = (r.defect, r.factor)
        st = STATUS[k].final_status if k in STATUS else "(판정없음)"
        cur.append(st)
        act.append(bool(STATUS[k].actionable) if k in STATUS else False)
        # SOP는 08-02 기준이다. 그 뒤 판정이 바뀐 항목을 표시한다.
        if st == "confirmed_cause":
            stale.append("")
        elif st == "confirmed_monitor":
            stale.append("역할 변경: 감시지표 — 조치 SOP가 아니라 경보 문구로 바꿔야 함")
        elif st in {"insufficient", "rejected"}:
            stale.append("판정 강등됨 — 이 SOP는 현재 근거가 없다. 사용 중지 권고")
        else:
            stale.append(f"현재 판정={st} — 재검토 필요")
    s["current_status"] = cur
    s["actionable_now"] = act
    s["staleness_warning"] = stale
    s["source"] = f"Jun {SOP_DIR}/02_SOP_초안.csv (2026-08-02)"
    return s


# ============================================================ rel_07 HealthIndex 연결
def health_index_link() -> pd.DataFrame:
    hd = json.loads(git_text("origin/김시우", f"{GOAL5_DIR}/health_index_data.json"))
    rows = []
    for factor, meta in hd["cause_factors"].items():
        for d in meta["defects"]:
            k = (d, factor)
            r = STATUS.get(k)
            st = r.final_status if r is not None else "(판정없음)"
            if st == "confirmed_cause":
                action = "유지 — 원인. SOP 생성 가능"
            elif st == "confirmed_monitor":
                action = "역할 변경 — 감시지표. cause_factors에서 빼고 경보 전용으로"
            else:
                action = "삭제 — 현재 확정 원인 아님. Agent가 원인이라고 답하면 안 됨"
            rows.append(dict(
                factor=factor, defect=d,
                goal5_owner=meta.get("owner"), goal5_direction=meta.get("direction"),
                goal5_mechanism=meta.get("mechanism"),
                current_status=st,
                current_role=(r.role if r is not None else "(판정없음)"),
                actionable_now=bool(r.actionable) if r is not None else False,
                required_action=action,
                source="김시우 Goal5 health_index_data.json vs rel_01"))
    # Goal5에 없는데 새로 확정된 것
    for _, r in factors[factors.final_status.isin(
            ["confirmed_cause", "confirmed_monitor"])].iterrows():
        if r.factor in hd["cause_factors"] and r.defect in hd["cause_factors"][r.factor]["defects"]:
            continue
        rows.append(dict(factor=r.factor, defect=r.defect, goal5_owner=None,
                         goal5_direction=None, goal5_mechanism=None,
                         current_status=r.final_status, current_role=r.role,
                         actionable_now=bool(r.actionable),
                         required_action="추가 — Goal5에 없음",
                         source="rel_01에만 있음"))
    return pd.DataFrame(rows).sort_values(["required_action", "defect", "factor"]).reset_index(drop=True)


# ============================================================ rel_12 티어표
def tiers() -> pd.DataFrame:
    """원인 트랙과 감시지표 트랙을 절대 한 줄로 세우지 않는다.

    섞으면 Groove_Depth(측정값)가 상위 티어에 올라가고 Agent가 '조치하라'고 말하게 된다.
    """
    rows = []
    for _, r in factors.iterrows():
        if r.final_status == "confirmed_cause":
            track = "원인(조치가능)"
            if r.cross_check == "일치" and r.reproducibility == "reproduced":
                tier, meaning = "C1", "실행 준비 완료 — 2개 방법론 일치 + 두 데이터셋 재현"
            elif r.cross_check == "일치" or r.reproducibility == "reproduced":
                tier, meaning = "C2", "조건부 — 대조 또는 재현 중 하나가 미충족"
            else:
                tier, meaning = "C3", "관찰 — 대조 불일치 + 재현 안 됨"
        elif r.final_status == "confirmed_monitor":
            track = "감시지표(경보전용)"
            if r.role.startswith("감시지표(결과공변"):
                tier, meaning = "M3", "결과 공변 — 사후 탐지만. 예측·조치 불가"
            elif r.cross_check == "일치":
                tier, meaning = "M1", "경보 사용 가능 — 2개 방법론 일치"
            else:
                tier, meaning = "M2", "경보 사용 가능하나 대조 불일치 — 문구에 단서 필요"
        elif r.final_status == "candidate":
            track, tier, meaning = "후보", "P1", "한쪽 방법만 통과 — 확정 아님"
        elif r.final_status == "needs_domain_review":
            track, tier, meaning = "후보", "P2", "통계는 통과, 도메인 근거 미확인 — 멘토 확인 대기"
        else:
            continue
        rows.append(dict(defect=r.defect, factor=r.factor, track=track, tier=tier,
                         tier_meaning=meaning, role=r.role,
                         actionable=bool(r.actionable), owner=r.owner,
                         delta_pure=r.delta_pure, cross_check=r.cross_check,
                         reproducibility=r.reproducibility, caution=r.caution))
    t = pd.DataFrame(rows)
    order = {"C1": 0, "C2": 1, "C3": 2, "M1": 3, "M2": 4, "M3": 5, "P1": 6, "P2": 7}
    return t.assign(_o=t.tier.map(order)).sort_values(
        ["_o", "defect"]).drop(columns="_o").reset_index(drop=True)


# ============================================================ 실행
if __name__ == "__main__":
    made = []

    t = thresholds();            t.to_csv(OUT / "rel_05_thresholds.csv", index=False, encoding="utf-8-sig")
    made.append(("rel_05_thresholds.csv", len(t), "위험 경계값 — 4개 defect 전부"))

    s = sop();                   s.to_csv(OUT / "rel_06_sop_draft.csv", index=False, encoding="utf-8-sig")
    made.append(("rel_06_sop_draft.csv", len(s), "SOP 초안 + 낡음 경고"))

    h = health_index_link();     h.to_csv(OUT / "rel_07_health_index_link.csv", index=False, encoding="utf-8-sig")
    made.append(("rel_07_health_index_link.csv", len(h), "Goal5 연결 + 필요 조치"))

    for src, dst, desc in [
        ("db_05_binning.csv", "rel_08_binning.csv", "구간별 불량률"),
        ("db_06_shap_global.csv", "rel_09_shap_global.csv", "SHAP 전역 — 설명 전용"),
        ("db_07_shap_local.csv", "rel_10_shap_local.csv", "SHAP 개별 건 — 설명 전용"),
        ("db_08_method_agreement.csv", "rel_11_method_agreement.csv", "3방법 순위 대조"),
    ]:
        d = pd.read_csv(MY_DB / src, encoding="utf-8-sig")
        d.to_csv(OUT / dst, index=False, encoding="utf-8-sig")
        made.append((dst, len(d), desc))

    ti = tiers();                ti.to_csv(OUT / "rel_12_tiers.csv", index=False, encoding="utf-8-sig")
    made.append(("rel_12_tiers.csv", len(ti), "티어표 — 원인/감시 트랙 분리"))

    v = git_csv("origin/daeho", "26.08.02_2250_Goal3_Vibration_얽힘구조/05_effect_interaction.csv")
    v.to_csv(OUT / "rel_13_vibration_entanglement.csv", index=False, encoding="utf-8-sig")
    made.append(("rel_13_vibration_entanglement.csv", len(v), "daeho Goal3 — Vibration 얽힘"))

    print("=" * 96)
    print("통합 DB 확장 — Agent 처음부터 끝까지에 필요한 테이블")
    print("=" * 96)
    for f, n, d in made:
        print(f"  -> {f:36s} {n:5d}행   {d}")

    print("\n" + "=" * 96)
    print("티어표")
    print("=" * 96)
    for tr in ["원인(조치가능)", "감시지표(경보전용)", "후보"]:
        sub = ti[ti.track == tr]
        print(f"\n[{tr}] {len(sub)}건")
        for tier in sub.tier.unique():
            ss = sub[sub.tier == tier]
            print(f"  {tier} ({ss.tier_meaning.iloc[0]})")
            for _, r in ss.iterrows():
                print(f"      {r.defect:12s} {r.factor}")

    print("\n" + "=" * 96)
    print("김시우님 Goal5 반영 필요 항목 (rel_07)")
    print("=" * 96)
    for a in h.required_action.unique():
        sub = h[h.required_action == a]
        print(f"\n  [{a}] {len(sub)}건")
        for _, r in sub.iterrows():
            print(f"      {r.defect:12s} {r.factor}")

    print("\n" + "=" * 96)
    print("낡은 SOP (rel_06)")
    print("=" * 96)
    for _, r in s[s.staleness_warning != ""].iterrows():
        print(f"  · {r.defect:12s} {r.factor:24s} {r.staleness_warning}")
