"""관계 DB -> AI Agent 입력 변환

김시우님 프로토타입(26.08.01_Goal_AI_Agent_Prototype_김시우/agent.py)은
health_index_data.json의 cause_factors를 읽는다. 그 스키마를 그대로 유지하면서
rel_01_factors.csv에서 생성해, agent.py의 로드 한 줄만 바꾸면 붙도록 만든다.

  기존:  CAUSE_FACTORS = DATA["cause_factors"]
  변경:  CAUSE_FACTORS = json.load(open(REL_DB / "agent_cause_factors.json"))["cause_factors"]

기존 키(defects/owner/direction/mechanism)는 그대로 두고 필드만 추가하므로
agent.py의 get_defect_causes / get_sop_for_factor는 수정 없이 동작한다.

핵심 차이 — 현재 프로토타입의 cause_factors 11개에는 다음 문제가 있다.
  1. Micro_Crack의 Vibration/Cooling_Flow가 원인으로 들어 있다 (26.08.05 강등됨)
  2. Kerf_Width_Profile / Top_Kerf / Bottom_Kerf / Groove_Depth는 Response 계열
     감시지표인데 cause_factors에 있어, get_sop_for_factor가 "조치하라"는 SOP를
     만들어낸다. 감시지표는 조치 대상이 아니다.
이 스크립트는 원인과 감시지표를 분리해서 내보낸다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_agent_payload.py"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent


def entry(r) -> dict:
    d = r.delta_pure
    return {
        "defects": [r.defect],
        "owner": r.owner,
        "direction": "unknown" if pd.isna(d) else ("up" if d > 0 else "down"),
        "mechanism": r.domain_mechanism if isinstance(r.domain_mechanism, str) else "",
        # --- 아래는 추가 필드 (기존 agent.py는 무시해도 동작)
        "role": r.role,
        "actionable": bool(r.actionable),
        "confidence": r.confidence,
        "effect_size_pure": None if pd.isna(d) else round(float(d), 4),
        "cross_check": r.cross_check,
        "caution": r.caution if isinstance(r.caution, str) and r.caution else None,
    }


def merge(bucket: dict, factor: str, e: dict) -> None:
    """같은 인자가 여러 defect에 걸리면 defects 목록만 합친다."""
    if factor in bucket:
        bucket[factor]["defects"] += e["defects"]
        if e["caution"] and not bucket[factor]["caution"]:
            bucket[factor]["caution"] = e["caution"]
    else:
        bucket[factor] = e


def main() -> None:
    f = pd.read_csv(OUT / "rel_01_factors.csv", encoding="utf-8-sig")
    meta = json.loads((OUT / "rel_00_metadata.json").read_text(encoding="utf-8"))

    causes: dict[str, dict] = {}
    monitors: dict[str, dict] = {}
    for _, r in f.iterrows():
        if r.final_status == "confirmed_cause":
            merge(causes, r.factor, entry(r))
        elif r.final_status == "confirmed_monitor":
            merge(monitors, r.factor, entry(r))

    # defect별 확정 원인이 0건이면 Agent가 "없다"고 답해야 한다. 빈 목록을 명시적으로 넣어
    # get_defect_causes가 "조회 가능한 defect 목록"만 뱉고 끝나지 않게 한다.
    defects = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
    no_cause = {
        d: {
            "confirmed_cause_count": 0,
            "answer": f"{d}의 확정 원인은 현재 0건입니다.",
            "reason": next((l for l in meta["known_limitations"] if l.startswith(d)),
                           "담당자 분석에서 확정 원인이 나오지 않았습니다."),
        }
        for d in defects
        if not any(d in e["defects"] for e in causes.values())
    }

    # 티어를 인자 항목에 직접 얹는다 — Agent가 답변 어조를 티어로 고를 수 있게.
    tiers = pd.read_csv(OUT / "rel_12_tiers.csv", encoding="utf-8-sig")
    for _, r in tiers.iterrows():
        bucket = causes if r.track.startswith("원인") else monitors
        if r.factor in bucket:
            bucket[r.factor]["tier"] = r.tier
            bucket[r.factor]["tier_meaning"] = r.tier_meaning

    # 경보에 쓸 수 있는 경계값만 (기각된 인자의 경계값은 제외)
    th = pd.read_csv(OUT / "rel_05_thresholds.csv", encoding="utf-8-sig")
    th = th[th.usable_for_alert].drop_duplicates(["defect", "factor"], keep="first")

    sop = pd.read_csv(OUT / "rel_06_sop_draft.csv", encoding="utf-8-sig")
    hil = pd.read_csv(OUT / "rel_07_health_index_link.csv", encoding="utf-8-sig")

    payload = {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/rel_01_factors.csv",
        "cause_factors": causes,
        "monitor_factors": monitors,
        "defects_without_confirmed_cause": no_cause,
        "agent_rules": meta["rules_for_agent"],
        "tier_legend": {
            "C1": "원인 · 실행 준비 완료 — 조치 지시 가능",
            "C2": "원인 · 조건부 — 단서를 붙여 제시",
            "C3": "원인 · 관찰 — 확정 표현 금지, 확인 요청으로",
            "M1": "감시지표 · 경보 가능",
            "M2": "감시지표 · 경보 가능하나 단서 필요",
            "M3": "감시지표 · 결과 공변 — 사후 탐지만. 예측·조치 불가",
            "P1/P2": "후보 — 원인이라고 답하면 안 됨",
        },
        # 위험 경계값: "z가 이 값을 넘으면 불량률 X%" — Agent 경보 문구의 근거
        "thresholds": th[["defect", "factor", "threshold_z", "risky_direction",
                          "defect_rate_safe_pct", "defect_rate_risky_pct",
                          "risk_ratio", "current_status"]].to_dict("records"),
        # SOP 재료. 전부 DRAFT_UNVERIFIED이고, staleness_warning이 있으면 그대로 쓰면 안 됨
        "sop_draft": sop[["defect", "factor", "tier", "action_type", "inspection_target",
                          "normal_range", "warning_signal", "recommended_action",
                          "status", "current_status", "actionable_now",
                          "staleness_warning"]].to_dict("records"),
        # 김시우님 Goal5 cause_factors를 어떻게 고쳐야 하는지
        "health_index_actions": hil[["factor", "defect", "current_status",
                                     "current_role", "required_action"]].to_dict("records"),
        "disputes": pd.read_csv(OUT / "rel_03_disputes.csv", encoding="utf-8-sig")[
            ["defect", "factor", "owner", "owner_verdict", "jun_verdict", "dispute_reason"]
        ].to_dict("records"),
    }
    (OUT / "agent_cause_factors.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 88)
    print("AI Agent 입력 생성 — agent_cause_factors.json")
    print("=" * 88)
    print(f"\n원인(조치가능) {len(causes)}개 — get_sop_for_factor가 SOP를 만들어도 되는 인자")
    for k, v in causes.items():
        print(f"   {k:26s} {'/'.join(v['defects']):22s} {v['confidence']}")
    print(f"\n감시지표(관찰만) {len(monitors)}개 — 경보만. 조치 지시 금지")
    for k, v in monitors.items():
        print(f"   {k:26s} {'/'.join(v['defects']):22s} {v['role']}")
    print(f"\n확정 원인 0건인 defect {len(no_cause)}개 — Agent는 '없다'고 답해야 함")
    for k in no_cause:
        print(f"   {k}")

    # ---------------------------------------------------- 현재 main 프로토타입과의 차이
    current = {
        "Vibration": ["Particle", "Micro_Crack"], "CLN_Pressure": ["Remain_Coat"],
        "Laser_Power": ["Chipping"], "Power_Efficiency": ["Chipping"],
        "Head_Temp": ["Chipping"], "Laser_Centering_Position": ["Chipping"],
        "Cooling_Flow": ["Micro_Crack"], "Kerf_Width_Profile": ["Chipping"],
        "Top_Kerf": ["Chipping"], "Bottom_Kerf": ["Chipping"], "Groove_Depth": ["Chipping"],
    }
    print("\n" + "=" * 88)
    print("현재 main 프로토타입(health_index_data.json cause_factors 11개)과의 차이")
    print("=" * 88)
    for k, ds in current.items():
        for d in ds:
            if k in causes and d in causes[k]["defects"]:
                continue
            if k in monitors and d in monitors[k]["defects"]:
                print(f"  [역할 변경] {d}/{k}: 원인 -> {monitors[k]['role']}  "
                      f"(SOP 대상에서 제외해야 함)")
            else:
                print(f"  [삭제 필요] {d}/{k}: 확정 원인 아님 — 현재 Agent는 이걸 원인이라고 답한다")
    for k, v in causes.items():
        for d in v["defects"]:
            if k not in current or d not in current[k]:
                print(f"  [추가] {d}/{k}")
    print("=" * 88)


if __name__ == "__main__":
    main()
