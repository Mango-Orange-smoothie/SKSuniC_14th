"""팀 통합 Relationship DB — 4개 defect (Chipping / Micro_Crack / Particle / Remain_Coat)

목적
  각 담당자가 따로 낸 유효인자 판정을 하나의 스키마로 합쳐, AI Agent가
  "원인(조치 가능) / 감시지표(관찰만) / 불량결과"를 구분해 답할 수 있게 한다.

출처 (2026-08-05 기준 각 브랜치 최신)
  Chipping    JHdaimma  26.08.01_.../agent_db/db_01_factors.csv
  Micro_Crack JHdaimma  위와 동일
  Particle    daeho     origin/daeho 26.08.05_.../out/04_particle_influence_factors_final.csv
  Remain_Coat 전성재     origin/전성재 26.07.31_.../REM_COAT_유효인자_정리.md (16절 역할분류)
  4종 교차대조          origin/Jun  26.08.01_2229_.../07_*_unified_verdict.csv

설계 원칙
  1. 담당자 판정을 덮어쓰지 않는다. 담당자 판정과 Jun 대조본을 나란히 싣고,
     어긋나면 final_status = disputed 로 두고 rel_03에 사유를 남긴다.
  2. 역할(원인/감시지표)은 통계가 아니라 컬럼 계층(FDC/Response)이 정한다.
     단 '결과 공변'이 검증된 인자는 감시지표 중에서도 사후지표로 따로 표시한다.
  3. 도메인 지지는 '확정' 근거일 때만 부여한다. 작성자 추론은 지지가 아니다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_unified_relationship_db.py"
"""
from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
REPO = OUT.parent
MY_DB = REPO / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"
JUN_DIR = "26.08.01_2229_Goal2_통합_전체방법론_4개defect"
DAEHO_DIR = "26.08.05_Goal2_PARTICLE_유효인자_분석_JHdaimma방법론_daeho"

DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
OWNER = {"Chipping": "JHdaimma", "Micro_Crack": "JHdaimma",
         "Particle": "daeho", "Remain_Coat": "전성재"}


def git_csv(ref: str, path: str) -> pd.DataFrame:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git show 실패: {ref}:{path}\n{r.stderr[:300]}")
    return pd.read_csv(io.StringIO(r.stdout))


# ==================================================================== 판정 어휘 통일
# 각 담당자가 쓰는 등급 이름이 달라서, 공통 어휘로 옮긴 뒤 비교한다.
NORM = {
    # JHdaimma
    "confirmed": "confirmed",
    "candidate_weak_signal": "candidate",
    "insufficient_evidence": "insufficient",
    "contaminated_by_Chipping": "rejected_contaminated",
    "contaminated_by_Micro_Crack": "rejected_contaminated",
    "shared_cause_with_Chipping": "candidate",       # 아래 DEMOTE에서 재검토
    "shared_cause_with_Micro_Crack": "candidate",
    # Jun 통합본
    "Tier1_실행준비완료": "confirmed",
    "Tier2c_방향일치_크기데이터셋의존": "candidate",
    "Tier2d_데이터셋특정적_재현안됨": "candidate",
    "Tier3_약한신호": "candidate",
    "monitor_only": "monitor_confirmed",
    "rejected": "rejected",
    "candidate_needs_domain_review": "needs_domain_review",
}


def norm(v) -> str:
    if not isinstance(v, str) or not v:
        return "insufficient"
    return NORM.get(v.strip(), v.strip())


# ==================================================================== 작성자 판정 정정
# 앞선 검토에서 근거 없음이 확인돼 스스로 강등하는 항목. 사유를 반드시 남긴다.
DEMOTE = {
    ("Micro_Crack", "Vibration"): (
        "insufficient",
        "도메인 지지 철회 — 멘토 '진동은 설비 열화의 대표 신호'를 작성자가 "
        "'진동 -> 미세균열' 근거로 확대 해석한 것. 단변량 통과도 broad 라벨에만 의존"
        "(broad +0.565 -> pure +0.124). Jun 통합본도 not_reproduced.",
    ),
    ("Micro_Crack", "Cooling_Flow"): (
        "insufficient",
        "pure 라벨에서 |delta| 0.018로 붕괴. 멘토 미확정 컬럼이며 도메인 근거 없음.",
    ),
}

# 결과 공변(원인 아님)이 데이터로 검증된 인자 — 감시지표 중에서도 사후지표
POST_HOC_MONITOR = {
    "Surface_Roughness": "daeho 검증1: 선행신호 잔존율 7.5% — 불량 발생 후 거칠기가 "
                         "올라가는 결과 공변. 원인 아님, 탐지지표로만 사용.",
}

# 전성재님이 16절에서 직접 지정한 역할 (Jun 통합본 판정과 별개로 담당자 판정이 우선)
SEONGJAE_ROLE = {
    "CLN_Pressure": ("원인(조치가능)", "confirmed",
                     "확정 유효인자(4·5·6·10·12번). 추세감시가 아니라 스트립별 실시간 급락 알람 대상"),
    "CLN_Flow": ("원인(조치가능·DP04 한정)", "candidate",
                 "DP04에서만 원인(Goal1 매개분석). 전체 장비 공통 원인 아님"),
    "Coating_Thickness": ("분류보류", "insufficient",
                          "측정 시점(가공 전/후) 미확인 — 현업 확인 전까지 어느 분류에도 넣지 말 것"),
    "CLN_Time": ("제외", "rejected", "9번에서 원인 후보 완전 제외"),
}

ROLE_BY_LAYER = {"FDC": "원인(조치가능)", "Response": "감시지표(관찰만)", "Other": "미분류"}

# 멘토가 제외를 지시한 컬럼 (김시우 전처리 d39bbff 반영)
MENTOR_EXCLUDED = ["Focus", "Cutting_Offset"]

# 팀 공통 효과크기 하한 (Cliff's delta)
EFFECT_SIZE_MIN = 0.2


# ==================================================================== 1) 담당자 판정 수집
def load_owner_verdicts() -> pd.DataFrame:
    rows = []

    # --- Chipping / Micro_Crack : 내 db_01
    mine = pd.read_csv(MY_DB / "db_01_factors.csv", encoding="utf-8-sig")
    for _, r in mine.iterrows():
        v, note = norm(r.verdict), ""
        key = (r.target, r.factor)
        if key in DEMOTE:
            v, note = DEMOTE[key]
        rows.append(dict(
            defect=r.target, factor=r.factor, layer=r.layer, subsystem=r.subsystem,
            owner="JHdaimma", owner_verdict_raw=r.verdict, owner_verdict=v,
            delta_pure=r.delta_pure, delta_broad=r.delta_broad, p_fdr_pure=r.p_fdr_pure,
            n_methods=r.n_methods_agree,
            delta_original=r.delta_original_dataset, delta_r1=r.delta_r1_dataset,
            domain_status=r.domain_status, domain_mechanism=r.domain_mechanism,
            owner_note=note or (r.caution if isinstance(r.caution, str) else ""),
        ))

    # --- Particle : daeho 26.08.05 (JHdaimma 방법론 이식본)
    d = git_csv("origin/daeho", f"{DAEHO_DIR}/out/04_particle_influence_factors_final.csv")
    rep = git_csv("origin/daeho", f"{DAEHO_DIR}/out/08_reproducibility_particle.csv")
    rep = rep.set_index("column")
    for _, r in d.iterrows():
        rows.append(dict(
            defect="Particle", factor=r.column, layer=_layer_of(r.subsystem, r.column),
            subsystem=r.subsystem, owner="daeho",
            owner_verdict_raw=r.verdict, owner_verdict=norm(r.verdict),
            delta_pure=r["cliffs_delta_is_particle_primary"],
            delta_broad=r["cliffs_delta_is_particle_broad"],
            p_fdr_pure=r["p_fdr_is_particle_primary"],
            n_methods=r.n_methods_agree,
            delta_original=rep.delta_original.get(r.column),
            delta_r1=rep.delta_r1.get(r.column),
            domain_status=r.domain_status, domain_mechanism=r.domain_mechanism,
            owner_note=r.daeho_followup_status if isinstance(r.daeho_followup_status, str) else "",
        ))

    # --- Remain_Coat : Jun 통합본 수치 + 전성재 16절 역할판정
    j = git_csv("origin/Jun", f"{JUN_DIR}/07_remain_coat_unified_verdict.csv")
    for _, r in j.iterrows():
        role, v, note = SEONGJAE_ROLE.get(r.column, (None, None, ""))
        rows.append(dict(
            defect="Remain_Coat", factor=r.column, layer=r.layer, subsystem=r.subsystem,
            owner="전성재",
            owner_verdict_raw=(f"전성재 16절: {role}" if role else "(16절 미지정)"),
            owner_verdict=(v if v else norm(r.tier)),
            delta_pure=r.delta_pure, p_fdr_pure=r.p_fdr_pure,
            n_methods=r.n_methods_agree,
            delta_original=r.delta_original, delta_r1=r.delta_r1,
            domain_status=r.domain_status, domain_mechanism=r.domain_mechanism,
            owner_note=note,
            _seongjae_role=role,
        ))
    return pd.DataFrame(rows)


def _layer_of(subsystem: str, col: str) -> str:
    """daeho 출력에는 layer 컬럼이 없어 subsystem으로 되돌린다."""
    if subsystem == "response":
        return "Response"
    if subsystem == "engineered":
        # 팀 공용 파생 피처 — 원재료가 Response를 포함하면 Response
        return "Response" if col in {"Laser_Cleaning_Demand", "Cleaning_Load_Ratio",
                                     "Package_Size_Asymmetry"} else "FDC"
    if subsystem.startswith("fdc_"):
        return "FDC"
    return "Other"


# ==================================================================== 2) Jun 대조본
def load_jun() -> pd.DataFrame:
    out = []
    for f, d in [("chipping", "Chipping"), ("micro_crack", "Micro_Crack"),
                 ("particle", "Particle"), ("remain_coat", "Remain_Coat")]:
        v = git_csv("origin/Jun", f"{JUN_DIR}/07_{f}_unified_verdict.csv")
        v = v.rename(columns={"column": "factor"})
        v["defect"] = d
        v["jun_verdict"] = v.tier.map(norm)
        out.append(v[["defect", "factor", "tier", "jun_verdict", "layer", "subsystem",
                      "reproducibility", "temporal_status", "flag_shap"]])
    return (pd.concat(out, ignore_index=True)
            .rename(columns={"tier": "jun_verdict_raw",
                             "layer": "jun_layer", "subsystem": "jun_subsystem"}))


# ==================================================================== 3) 합치기 + 역할 부여
CONFIRMED_LIKE = {"confirmed", "monitor_confirmed"}


def build_factors() -> pd.DataFrame:
    o = load_owner_verdicts()
    j = load_jun()
    m = o.merge(j, on=["defect", "factor"], how="outer")
    m["owner"] = m.owner.fillna(m.defect.map(OWNER))
    m["owner_verdict"] = m.owner_verdict.fillna("insufficient")
    m["jun_verdict"] = m.jun_verdict.fillna("(대조본 없음)")
    # Jun 쪽에만 있는 인자는 계층 정보가 비어 있다 — Jun 대조본 값으로 메운다.
    m["layer"] = m.layer.fillna(m.jun_layer).fillna("Other")
    m["subsystem"] = m.subsystem.fillna(m.jun_subsystem).fillna("unknown")
    m = m.drop(columns=["jun_layer", "jun_subsystem"])

    # --- 역할
    def role_of(r):
        sj = r.get("_seongjae_role")
        if isinstance(sj, str) and sj:      # NaN은 truthy라 문자열인지 먼저 본다
            return sj
        if r.factor in POST_HOC_MONITOR:
            return "감시지표(결과공변·사후)"
        return ROLE_BY_LAYER.get(r.layer, "미분류")

    m["role"] = m.apply(role_of, axis=1)
    m["role_note"] = m.factor.map(POST_HOC_MONITOR).fillna("")

    # --- 담당자 vs Jun 교차대조
    # 담당자 판정을 덮어쓰지 않는다. 각 defect의 담당자가 그 defect의 권위이고,
    # Jun 통합본은 같은 데이터를 다른 방법으로 본 대조군이다. 어긋나면 신뢰도를
    # 낮추고 rel_03에 사유를 남길 뿐, 담당자 결론 자체는 유지한다.
    def cross(r):
        if r.jun_verdict == "(대조본 없음)":
            return "담당자_단독"
        a, b = r.owner_verdict, r.jun_verdict
        if a == b:
            return "일치"
        if (a in CONFIRMED_LIKE) != (b in CONFIRMED_LIKE):
            return "불일치"          # 확정 여부가 갈림 — 가장 중요한 어긋남
        return "등급차"              # 둘 다 미확정인데 세부 등급만 다름

    m["cross_check"] = m.apply(cross, axis=1)

    # --- 최종 상태 = 담당자 판정
    def final(r):
        a = r.owner_verdict
        if a == "monitor_confirmed":
            return "confirmed_monitor"
        if a == "confirmed":
            return "confirmed_cause"
        if a in {"rejected", "rejected_contaminated"}:
            return "rejected"
        if a == "candidate":
            return "candidate"
        if a == "needs_domain_review" or r.jun_verdict == "needs_domain_review":
            return "needs_domain_review"
        return "insufficient"

    m["final_status"] = m.apply(final, axis=1)

    # --- 신뢰도 : 두 방법이 같은 결론이면 높음, 담당자만이면 중간
    def conf(r):
        if r.final_status not in {"confirmed_cause", "confirmed_monitor"}:
            return "-"
        if r.cross_check == "일치":
            return "높음(2개 방법론 일치)"
        if r.cross_check == "담당자_단독":
            return "중간(대조본 없음)"
        return "중간(Jun 대조본과 불일치 — rel_03 참조)"

    m["confidence"] = m.apply(conf, axis=1)

    # 감시지표는 원인 확정이 될 수 없다 — 계층과 상태를 강제로 정합화
    swap = (m.final_status == "confirmed_cause") & (m.role.str.startswith("감시지표"))
    m.loc[swap, "final_status"] = "confirmed_monitor"

    # --- 조치 가능 여부 (Agent가 SOP를 낼 수 있는가)
    m["actionable"] = (m.final_status == "confirmed_cause") & (m.role.str.startswith("원인"))

    # --- 자동 점검 : 확정인데 엄격 라벨에서 효과크기가 팀 기준(0.2)에 못 미치는 경우
    # Micro_Crack/Vibration이 정확히 이 형태로 잘못 확정됐었다(broad +0.565 -> pure +0.124).
    # 같은 실수를 다른 defect에서 반복하지 않으려고 기계적으로 잡는다.
    m["caution"] = ""
    weak = (m.final_status.isin(["confirmed_cause", "confirmed_monitor"])
            & m.delta_pure.abs().lt(EFFECT_SIZE_MIN))
    m.loc[weak, "caution"] = (
        f"확정이지만 엄격(pure/primary) 라벨 효과크기 |delta|<{EFFECT_SIZE_MIN} — "
        "다른 defect가 섞인 넓은 라벨에 의존한 결론일 수 있음. 재확인 필요")

    # 멘토가 제외 지시한 컬럼이 담당자 분석에 남아 있으면 표시한다.
    m.loc[m.factor.isin(MENTOR_EXCLUDED), "caution"] = (
        m.loc[m.factor.isin(MENTOR_EXCLUDED), "caution"].str.rstrip() + " / "
        + "멘토 제외 지시 컬럼 — 이 인자가 포함된 분석은 해당 컬럼을 빼고 재실행 필요").str.strip(" /")

    m["source_file"] = m.defect.map({
        "Chipping": "JHdaimma db_01_factors.csv",
        "Micro_Crack": "JHdaimma db_01_factors.csv",
        "Particle": f"daeho {DAEHO_DIR}/out/04_particle_influence_factors_final.csv",
        "Remain_Coat": f"Jun {JUN_DIR}/07_remain_coat + 전성재 REM_COAT_유효인자_정리.md 16절",
    })

    cols = ["defect", "factor", "layer", "role", "role_note", "subsystem", "owner",
            "final_status", "actionable", "confidence", "cross_check",
            "owner_verdict", "owner_verdict_raw", "jun_verdict", "jun_verdict_raw",
            "delta_pure", "delta_broad", "p_fdr_pure", "n_methods",
            "delta_original", "delta_r1",
            "reproducibility", "temporal_status",
            "domain_status", "domain_mechanism", "owner_note", "caution", "source_file"]
    m = m[[c for c in cols if c in m.columns]]
    order = {"confirmed_cause": 0, "confirmed_monitor": 1,
             "candidate": 3, "needs_domain_review": 4, "rejected": 5, "insufficient": 6}
    m["_o"] = m.final_status.map(order).fillna(9)
    m = m.sort_values(["defect", "_o", "delta_pure"],
                      key=lambda s: s.abs() if s.name == "delta_pure" else s,
                      ascending=[True, True, False]).drop(columns="_o")
    return m.reset_index(drop=True)


# ==================================================================== 4) 관계 그래프
def build_relationships(f: pd.DataFrame) -> pd.DataFrame:
    rel = []
    keep = f[f.final_status.isin(["confirmed_cause", "confirmed_monitor", "candidate"])]
    for _, r in keep.iterrows():
        if r.role.startswith("원인"):
            relation = "causes"
        elif r.role.startswith("감시지표(결과공변"):
            relation = "co_varies_with"     # 원인 아님. 사후 탐지용
        elif r.role.startswith("감시지표"):
            relation = "monitors"
        else:
            relation = "associated_with"
        d = r.delta_pure
        rel.append(dict(
            source=r.factor, source_role=r.role, source_layer=r.layer,
            target=r.defect, target_role="불량결과",
            relation=relation,
            strength=None if pd.isna(d) else round(abs(d), 4),
            direction=("unknown" if pd.isna(d) else ("up" if d > 0 else "down")),
            status=r.final_status,
            confidence=r.confidence,
            actionable=bool(r.actionable),
            owner=r.owner,
            evidence=f"담당자={r.owner_verdict} / Jun대조={r.jun_verdict}",
        ))
    return pd.DataFrame(rel).sort_values(
        ["target", "relation", "strength"], ascending=[True, True, False]).reset_index(drop=True)


# ==================================================================== 5) 불일치 대장
DISPUTE_REASON = {
    ("Particle", "Vibration"):
        "비교군 정의 차이. daeho는 진혁 ~label 방식(r1 비교군의 38.1%가 불량)으로 "
        "delta +0.317 -> confirmed. Jun은 다른 비교군에서 not_reproduced -> Tier2d(관찰만). "
        "daeho 10_comparison_group_contrast_particle.csv에서 r1 Vibration이 "
        "-0.024 ~ +0.289로 갈림. 원본 데이터에서는 4종 비교군이 소수점 셋째 자리까지 동일.",
    ("Chipping", "Groove_Depth"):
        "JHdaimma는 도메인 확정(설계서 C유형 명시) + 단변량 통과로 confirmed. "
        "Jun은 n_methods=1(RF·SHAP 탈락)이라 Tier3_약한신호. 다변량에서 "
        "Laser_Power와 정보가 겹치는지 확인 필요.",
    ("Chipping", "Laser_Centering_Position"):
        "JHdaimma confirmed vs Jun Tier2d(not_reproduced). 원본 데이터의 Chipping이 "
        "4건뿐이라 원본측 delta 추정 자체가 불안정 — 재현성 판정의 신뢰구간 확인 필요.",
    ("Remain_Coat", "CLN_Flow"):
        "전성재는 'DP04 한정 원인'(Goal1 매개분석, 초과위험 103% 설명). "
        "Jun은 전체 장비 기준이라 rejected. 장비축을 넣느냐 마느냐의 차이이며 "
        "둘 다 맞다 — DB에는 '장비 한정 원인'으로 싣는다.",
    ("Remain_Coat", "Cleaning_Capacity"):
        "Jun rejected. 전성재 16절 미지정. CLN_Flow x CLN_Pressure x CLN_Time 파생이라 "
        "CLN_Flow의 DP04 한정 결론과 함께 재검토 필요.",
    ("Remain_Coat", "CLN_Pressure"):
        "전성재는 담당자로서 확정 원인(검증 4·5·6·10·12번). Jun은 Tier2c — 방향은 "
        "일치하나 효과 크기가 데이터셋에 따라 갈림(원본 -0.529 vs r1 -0.136). "
        "전성재 결론을 유지하되 '크기는 데이터셋 의존' 단서를 함께 표시.",
}

# Jun 통합본이 '도메인 미분류(candidate_needs_domain_review)'로 둔 인자를 담당자가
# 확정한 경우 — 통계 결과가 다른 게 아니라, 팀 원안 문서에 그 컬럼 설명이 없어서
# Jun 쪽이 판단을 보류한 것이다. 사유가 같으므로 한 문장으로 처리한다.
UNCLASSIFIED_NOTE = (
    "통계 결과는 양쪽이 같다. Jun 통합본은 이 컬럼이 팀 HealthIndex 원안 문서에 "
    "설명이 없어 도메인 판단을 보류(candidate_needs_domain_review)한 것이고, "
    "담당자는 데이터 근거로 확정했다. → 멘토에게 '이 컬럼이 무엇을 재는 값인지' "
    "확인받으면 즉시 해소되는 종류의 불일치."
)


def build_disputes(f: pd.DataFrame) -> pd.DataFrame:
    d = f[f.cross_check == "불일치"].copy()

    def reason(r):
        if (r.defect, r.factor) in DISPUTE_REASON:
            return DISPUTE_REASON[(r.defect, r.factor)]
        if r.jun_verdict == "needs_domain_review":
            return UNCLASSIFIED_NOTE
        return "사유 미기재 — 확인 필요"

    d["dispute_reason"] = [reason(r) for _, r in d.iterrows()]
    d["dispute_type"] = ["도메인_미확인" if r.jun_verdict == "needs_domain_review"
                         else "판정_충돌" for _, r in d.iterrows()]
    d["resolution_needed"] = ["멘토에게 컬럼 정의 확인" if r.jun_verdict == "needs_domain_review"
                              else "팀 회의에서 방법론 정합 후 재판정" for _, r in d.iterrows()]
    return d[["defect", "factor", "role", "owner", "dispute_type",
              "owner_verdict", "jun_verdict", "final_status",
              "delta_pure", "delta_original", "delta_r1",
              "dispute_reason", "resolution_needed"]].sort_values(
        ["dispute_type", "defect", "factor"]).reset_index(drop=True)


# ==================================================================== 6) 도메인 지식
def build_domain() -> pd.DataFrame:
    dk = pd.read_csv(MY_DB / "db_04_domain_knowledge.csv", encoding="utf-8-sig")
    add = pd.DataFrame([
        dict(kind="defect_mechanism", item="Particle", process_stage="unassigned",
             description="디브리(가공 부산물) 잔류/재부착. 진동 -> 디브리 비산·재부착이 "
                         "유일하게 살아남은 원인 후보(daeho 검증1·5)",
             evidence_type="데이터_실증", reliability="추정",
             note="Jun 통합본은 같은 인자를 관찰만(Tier2d)으로 봄 — disputed",
             source="daeho 26.08.05"),
        dict(kind="defect_mechanism", item="Remain_Coat", process_stage="세정",
             description="세정 압력 급락 시 보호코팅이 덜 제거돼 잔류. "
                         "추세형이 아니라 그 스트립 세정 순간의 즉시성 현상",
             evidence_type="데이터_실증", reliability="확정",
             note="전성재 검증9 — 선행신호 잔존율 4.1%. SOP는 추세감시가 아니라 "
                  "스트립별 실시간 급락 알람으로 설계할 것",
             source="전성재 26.07.31"),
        dict(kind="monitoring_limit", item="Remain_Coat", process_stage="세정",
             description="Remain_Coat에는 감시지표 유형 자체가 없다. 후보 39개 전수조사에서 "
                         "'서서히 나빠지다 미리 잡히는' 인자가 하나도 없었음",
             evidence_type="데이터_실증", reliability="확정",
             note="즉시성 현상이라 사전 감시가 원리적으로 어려움 — Agent는 이 defect에 "
                  "대해 '며칠 뒤 발생' 예측을 하면 안 됨",
             source="전성재 REM_COAT 16절"),
        dict(kind="monitoring_limit", item="Surface_Roughness", process_stage="unassigned",
             description="Chipping·Micro_Crack·Particle 3개에서 상위권이지만 결과 공변. "
                         "선행신호 잔존율 7.5%",
             evidence_type="데이터_실증", reliability="확정",
             note="원인으로 쓰면 안 됨. 사후 탐지지표로만. 멘토 drop 여부는 여전히 미확정",
             source="daeho 검증1 + JHdaimma db_00"),
    ])
    return pd.concat([dk, add], ignore_index=True)


# ==================================================================== 실행
if __name__ == "__main__":
    factors = build_factors()
    rels = build_relationships(factors)
    disputes = build_disputes(factors)
    domain = build_domain()

    factors.to_csv(OUT / "rel_01_factors.csv", index=False, encoding="utf-8-sig")
    rels.to_csv(OUT / "rel_02_relationships.csv", index=False, encoding="utf-8-sig")
    disputes.to_csv(OUT / "rel_03_disputes.csv", index=False, encoding="utf-8-sig")
    domain.to_csv(OUT / "rel_04_domain_knowledge.csv", index=False, encoding="utf-8-sig")

    th = pd.read_csv(MY_DB / "db_03_thresholds.csv", encoding="utf-8-sig")
    th.to_csv(OUT / "rel_05_thresholds.csv", index=False, encoding="utf-8-sig")

    meta = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        purpose="AI Agent용 팀 통합 관계 DB — 4개 defect의 원인/감시지표/불량결과",
        owners=OWNER,
        sources={
            "Chipping/Micro_Crack": "JHdaimma 26.08.01_.../agent_db/db_01_factors.csv",
            "Particle": f"origin/daeho {DAEHO_DIR}/out/04_particle_influence_factors_final.csv (26.08.05)",
            "Remain_Coat": f"origin/Jun {JUN_DIR}/07_remain_coat_unified_verdict.csv "
                           "+ origin/전성재 REM_COAT_유효인자_정리.md 16절",
            "교차대조": f"origin/Jun {JUN_DIR}/07_*_unified_verdict.csv",
        },
        counts={
            "총 인자행": int(len(factors)),
            "확정_원인": int((factors.final_status == "confirmed_cause").sum()),
            "확정_감시지표": int((factors.final_status == "confirmed_monitor").sum()),
            "교차대조_불일치": int((factors.cross_check == "불일치").sum()),
            "후보": int((factors.final_status == "candidate").sum()),
            "도메인확인필요": int((factors.final_status == "needs_domain_review").sum()),
            "기각": int((factors.final_status == "rejected").sum()),
        },
        rules_for_agent=[
            "actionable=False 인 인자에 대해서는 조치를 지시하지 말 것. 감시지표는 경보만.",
            "final_status=disputed 는 양쪽 주장을 모두 제시하고 판단을 유보할 것.",
            "Remain_Coat에 대해 '며칠 뒤 발생' 형태의 사전 예측을 하지 말 것 "
            "(감시지표 부재 — 즉시성 현상).",
            "Surface_Roughness를 원인으로 제시하지 말 것 (결과 공변).",
            "Micro_Crack의 확정 원인은 현재 0건이다. 없다고 답하고, 다이싱 단계 컬럼 "
            "부재를 이유로 밝힐 것. 억지로 후보를 제시하지 말 것.",
        ],
        known_limitations=[
            "Micro_Crack 확정 원인 0건 — 표본 문제가 아니라 다이싱 단계를 나타내는 컬럼이 "
            "데이터에 없는 변수 누락 문제(r1 단독 모델 AUC 0.578).",
            "SHAP은 판정에서 제외했다 — 4개 defect에서 과통과 24건 / 누락 1건 "
            "(db_10_shap_false_positives.csv).",
            "daeho Particle 분석은 Focus·Cutting_Offset을 포함해 돌렸다. 멘토가 제외 지시한 "
            "컬럼이므로 Particle 결과 재확인 시 이 두 컬럼을 빼고 재실행 필요.",
            "pure 라벨 정의가 담당자마다 다르다(JHdaimma는 상대 defect만 제외, "
            "Jun/daeho는 전체 defect 제외). 통일 전까지 delta_pure 직접 비교는 주의.",
            "조치 난이도표(어느 인자를 실제로 얼마나 빨리 바꿀 수 있는가)가 없다 — 멘토 확인 필요.",
        ],
        open_questions_for_mentor=[
            "Particle의 Vibration은 원인인가 관찰 대상인가? (daeho confirmed vs Jun Tier2d)",
            "Surface_Roughness는 실제 측정값인가, 형식상 컬럼인가?",
            "Vibration을 축별/시점별로 세분화한 데이터가 있는가? (레이저/다이싱 단계 분리 목적)",
            "Coating_Thickness는 가공 전 측정인가 후 측정인가?",
            "각 원인 인자의 조치 난이도·소요시간은?",
        ],
    )
    (OUT / "rel_00_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ 콘솔 요약
    print("=" * 100)
    print("팀 통합 Relationship DB — 4개 defect")
    print("=" * 100)
    for d in DEFECTS:
        s = factors[factors.defect == d]
        print(f"\n[{d}]  담당 {OWNER[d]}  ·  인자 {len(s)}개")
        for st, label in [("confirmed_cause", "확정 원인(조치가능)"),
                          ("confirmed_monitor", "확정 감시지표(관찰만)"),
                          ("candidate", "후보")]:
            sub = s[s.final_status == st]
            if len(sub):
                items = ", ".join(
                    f"{r.factor}({r.delta_pure:+.3f})" + ("*" if r.cross_check == "불일치" else "")
                    if pd.notna(r.delta_pure) else r.factor for _, r in sub.iterrows())
                print(f"   {label:22s} {len(sub):2d}개  {items}")
        if not len(s[s.final_status == "confirmed_cause"]):
            print(f"   {'확정 원인(조치가능)':22s}  0개  <- Agent는 '원인 없음'으로 답해야 함")
    print("\n   * = Jun 대조본과 불일치 (rel_03_disputes.csv)")

    w = factors[factors.caution.str.contains("엄격", na=False)]
    if len(w):
        print("\n" + "!" * 100)
        print(f"자동 점검 경고 — 확정인데 엄격 라벨 효과크기가 팀 기준 {EFFECT_SIZE_MIN} 미만: {len(w)}건")
        for _, r in w.iterrows():
            b = f"{r.delta_broad:+.3f}" if pd.notna(r.delta_broad) else "n/a"
            print(f"   · {r.defect}/{r.factor}  pure={r.delta_pure:+.3f}  broad={b}"
                  f"  ({r.owner} 판정)")
        print("!" * 100)

    print("\n" + "=" * 100)
    print(f"교차대조 불일치 {len(disputes)}건 — rel_03_disputes.csv")
    for t in ["판정_충돌", "도메인_미확인"]:
        sub = disputes[disputes.dispute_type == t]
        print(f"\n  [{t}] {len(sub)}건")
        for _, r in sub.iterrows():
            print(f"    · {r.defect}/{r.factor}: {r.owner}={r.owner_verdict} vs Jun={r.jun_verdict}"
                  f"  -> DB 수록={r.final_status}")
    print("=" * 100)
    for f_, n in [("rel_01_factors.csv", len(factors)), ("rel_02_relationships.csv", len(rels)),
                  ("rel_03_disputes.csv", len(disputes)), ("rel_04_domain_knowledge.csv", len(domain)),
                  ("rel_05_thresholds.csv", len(th)), ("rel_00_metadata.json", "-")]:
        print(f"  -> {f_:34s} {n}행")
