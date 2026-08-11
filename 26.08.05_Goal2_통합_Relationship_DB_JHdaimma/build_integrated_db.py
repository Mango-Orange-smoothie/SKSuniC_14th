"""Relationship DB 통합 — 새 티어표 기준 재구성

실행 순서 (저장소 루트에서)
  1. build_tier_table.py             티어표 생성 (RF 학습, 3분)
  2. check_injected_scenarios.py     검정 가능성
  3. compare_spec_vs_data_threshold.py  규격 간극
  4. build_integrated_db.py          ← 이 스크립트 (위 산출물을 통합)

이 스크립트가 하는 일
  ① 티어표 보강      rel_20에 검정가능성·규격간극·데이터셋별 내역을 붙인다
  ② Vibration 영역   rel_28 — 티어표 밖 별도 알람 트랙 (추세팀이 채울 자리 포함)
  ③ NG_Code 요약     rel_29 — 20만행 기준 건수·비율
  ④ 추세 인터페이스   rel_30 — 김시우님이 추세 결과를 붙일 자리
  ⑤ Agent 계약       agent_cause_factors.json v2.0 (경로·키 고정)

경로 고정 주의
  main의 agent.py가 이 파일을 읽는다. 파일명과 "cause_factors" 키를 바꾸면 즉시 깨진다.
      REL_DB / "agent_cause_factors.json"  ->  json["cause_factors"]
  하위 키 defects / owner / direction / mechanism 도 유지한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]

DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
# 멘토 공식 스펙 (origin/김시우 pipeline/spec.py, 26.08.05 수령) — Vibration은 없음
SPEC = {
    "Laser_Power": (17.8, 18.5, 19.2), "Power_Efficiency": (92, 95, 98),
    "Laser_Centering_Position": (-3, 0, 3), "Frequency": (98, 100, 102),
    "Feed_Speed": (248, 250, 252), "Head_Temp": (38, 42, 47), "Focus": (-4, 0, 4),
    "Kerf_Width_Profile": (49.2, 50, 50.8), "Coating_Thickness": (9.5, 10, 10.5),
    "Coating_Uniformity": (97, 99, 100),
}

print("[1/6] 데이터 로드")
o = pd.read_csv(PROJ / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(PROJ / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
print(f"    원본 {len(o):,} + r1 {len(r):,} = {len(df):,}행")


# ==================================================================== ① 티어표 보강
ENRICHED_COLS = [
    "testability", "pct_z_gt3", "spec_LSL", "spec_USL", "spec_gap",
    "has_official_spec", "threshold_source_dataset",
    "n_risky_original", "n_risky_r1",
    "defect_rate_risky_original_pct", "defect_rate_risky_r1_pct",
]


def enrich_tier_table() -> pd.DataFrame:
    t = pd.read_csv(OUT / "rel_20_tier_table.csv", encoding="utf-8-sig")
    # 이 스크립트를 다시 돌려도 안전하도록, 이전에 붙인 열은 떼고 시작한다.
    t = t.drop(columns=[c for c in ENRICHED_COLS if c in t.columns])
    inj = pd.read_csv(OUT / "rel_26_scenario_injection_check.csv",
                      encoding="utf-8-sig").set_index("factor")
    gap = pd.read_csv(OUT / "rel_27_spec_vs_data_threshold.csv", encoding="utf-8-sig")
    gap_key = {(x.defect, x.factor): x for _, x in gap.iterrows()}

    rows = []
    for _, x in t.iterrows():
        c, d_ = x.factor, x.defect
        i = inj.loc[c] if c in inj.index else None
        g = gap_key.get((d_, c))

        # 경계값을 넘은 행이 원본/r1 각각 몇 건이고 그 구간 불량률이 얼마인가.
        # Head_Temp처럼 경계 자체가 r1에서만 나온 경우를 드러내기 위함이다.
        thr, down = x.alert_threshold_raw, ("감소" in x.domain_direction)
        others = [z for z in DEFECTS if z != d_]
        pure = (df[d_] == 1) & (df[others].sum(axis=1) == 0)
        stat = {}
        for name, mask in [("original", df.source_dataset == "original"),
                           ("r1", df.source_dataset == "r1")]:
            risky = ((df[c] <= thr) if down else (df[c] > thr)) & mask
            stat[f"n_risky_{name}"] = int(risky.sum())
            stat[f"defect_rate_risky_{name}_pct"] = (
                round(pure[risky].mean() * 100, 3) if risky.sum() else None)

        # 어느 데이터셋이 이 경계값을 사실상 결정했는가
        no, n1 = stat["n_risky_original"], stat["n_risky_r1"]
        tot = no + n1
        if tot == 0:
            src = "판정불가"
        elif n1 / tot > 0.8:
            src = "r1 주도(원본 기여 미미)"
        elif no / tot > 0.8:
            src = "원본 주도"
        else:
            src = "양쪽 기여"

        rows.append(dict(
            **x.to_dict(),
            testability=(i.testability if i is not None else "미확인"),
            pct_z_gt3=(i.pct_z_gt3 if i is not None else None),
            spec_LSL=(g.spec_LSL if g is not None else None),
            spec_USL=(g.spec_USL if g is not None else None),
            spec_gap=(g.gap_from_spec if g is not None else None),
            has_official_spec=c in SPEC,
            threshold_source_dataset=src, **stat,
        ))
    return pd.DataFrame(rows)


# ==================================================================== ② Vibration 별도 영역
def build_vibration_area() -> pd.DataFrame:
    """티어표에 넣지 않는다. 추세 + 상하한 급이탈 알람 전용 트랙.

    멘토 공식 스펙에 Vibration이 없으므로 상하한을 데이터에서 제시한다.
    추세 기준은 추세분석 담당이 채운다 — 여기서는 빈칸으로 자리만 만든다.
    """
    rows = []
    for d_ in ["Chipping", "Micro_Crack"]:      # 확정 도메인: Vibration 증가 -> 증가
        others = [z for z in DEFECTS if z != d_]
        pure = (df[d_] == 1) & (df[others].sum(axis=1) == 0)
        v = df.Vibration
        rows.append(dict(
            factor="Vibration", defect=d_,
            role="원인(정비대상)", area="alarm_only_not_tier",
            domain_direction="Vibration 증가 → " + d_ + " 증가",
            domain_evidence="멘토 확정",
            alarm_type="추세 상승 + 상하한 급이탈",
            why_not_in_tier="값을 조정하는 인자가 아니라 설비 정비 대상이라 "
                            "원인 티어표에 두면 실행 불가능한 조치를 제안하게 됨",
            has_official_spec=False,
            spec_note="멘토 공식 스펙(spec.py 10개 변수)에 Vibration 없음 — 상하한을 데이터에서 제시",
            # --- 데이터 기반 상하한 후보 (통합 20만행)
            p01=round(v.quantile(.01), 4), p50=round(v.quantile(.50), 4),
            p99=round(v.quantile(.99), 4), p999=round(v.quantile(.999), 4),
            vmin=round(v.min(), 4), vmax=round(v.max(), 4),
            upper_candidate_p99=round(v.quantile(.99), 4),
            upper_candidate_p999=round(v.quantile(.999), 4),
            # 원본 기준(정상 운전)에서의 상한 — r1은 열화 주입이라 별도로 제시
            upper_original_p99=round(o.Vibration.quantile(.99), 4),
            upper_r1_p99=round(r.Vibration.quantile(.99), 4),
            defect_rate_above_p99_pct=round(pure[v > v.quantile(.99)].mean() * 100, 3),
            defect_rate_overall_pct=round(pure.mean() * 100, 3),
            # 상한 초과가 실제로 그 defect를 예측하는지 자체 점검.
            # 1보다 작으면 상한 알람을 그 defect에 연결하면 안 된다.
            lift_above_p99=round(pure[v > v.quantile(.99)].mean() / pure.mean(), 3)
            if pure.mean() > 0 else None,
            # --- 추세 담당이 채울 자리
            trend_window_days="", trend_slope_threshold="",
            spec_breach_rule="", alarm_owner="추세분석 담당",
            status="스키마만 정의 — 기준값은 추세분석 담당이 채움",
        ))
    return pd.DataFrame(rows)


# ==================================================================== ③ NG_Code 요약
def build_ng_summary() -> pd.DataFrame:
    """20만행 기준 NG_Code별 건수·비율. 요청 행 순서를 지킨다."""
    n = len(df)
    order = [("OK", "OK"), ("PARTICLE", "Particle"), ("CRACK", "Micro_Crack"),
             ("REM_COAT", "Remain_Coat"), ("CHIP", "Chipping")]
    vc = df.NG_Code.value_counts()
    rows = []
    for code, label in order:
        cnt = int(vc.get(code, 0))
        rows.append(dict(구분=label, NG_Code=code, 건수=cnt,
                         비율_pct=round(cnt / n * 100, 3)))
    # 요청 목록 밖 코드도 누락 없이 싣는다
    for code, cnt in vc.items():
        if code not in [c for c, _ in order]:
            rows.append(dict(구분=f"(기타) {code}", NG_Code=code, 건수=int(cnt),
                             비율_pct=round(cnt / n * 100, 3)))
    rows.append(dict(구분="합계", NG_Code="-", 건수=n, 비율_pct=100.0))
    return pd.DataFrame(rows)


# ==================================================================== ④ 추세 인터페이스
def build_trend_interface(tier: pd.DataFrame) -> pd.DataFrame:
    """김시우님이 추세분석 결과를 붙일 자리.

    내가 채우는 것 : 어느 인자를 어느 defect에 대해 어느 선까지 감시할지
    추세팀이 채울 것: 현재 기울기, 도달 예상일, 추세 상태
    """
    rows = []
    for _, x in tier[tier.tier.isin(["T1", "T2", "M1"])].iterrows():
        rows.append(dict(
            factor=x.factor, defect=x.defect, tier=x.tier, role=x.role,
            action_type=x.action_type,
            # --- 내가 제공 (목표선)
            target_threshold_raw=x.alert_threshold_raw,
            threshold_direction=("아래로 내려가면 위험" if "감소" in x.domain_direction
                                 else "위로 올라가면 위험"),
            normal_range_raw=x.normal_range_raw,
            risky_range_raw=x.risky_range_raw,
            risk_ratio=x.risk_ratio,
            alert_usable=x.alert_usable,
            threshold_source_dataset=x.threshold_source_dataset,
            spec_LSL=x.spec_LSL, spec_USL=x.spec_USL,
            # --- 추세팀이 채울 자리
            current_slope_per_day="", days_to_threshold="", trend_status="",
            trend_window_days="", trend_owner="김시우(추세분석)",
            note="target_threshold_raw 가 추세의 목표선이다. "
                 "threshold_source_dataset 이 'r1 주도'면 정상 운전에서는 도달하지 않을 수 있다.",
        ))
    return pd.DataFrame(rows)


# ==================================================================== ⑤ Agent 계약
def build_agent_payload(tier: pd.DataFrame, vib: pd.DataFrame,
                        ng: pd.DataFrame) -> dict:
    def entry(x):
        return {
            # --- 기존 키 (main agent.py가 쓰는 것 — 절대 변경 금지)
            "defects": [x.defect], "owner": "JHdaimma",
            "direction": "down" if "감소" in x.domain_direction else "up",
            "mechanism": x.domain_direction,
            # --- 추가 필드
            "tier": x.tier, "role": x.role, "action_type": x.action_type,
            "actionable": x.tier in ("T1", "T2"),
            "cliffs_delta": x.cliffs_delta, "rf_rank": x.rf_rank,
            "threshold_raw": x.alert_threshold_raw,
            "normal_range": x.normal_range_raw, "risky_range": x.risky_range_raw,
            "risk_ratio": x.risk_ratio, "alert_usable": bool(x.alert_usable),
            "testability": x.testability,
            "threshold_source_dataset": x.threshold_source_dataset,
            "tier_reason": x.tier_reason,
        }

    # 같은 인자가 여러 defect에 걸리면 티어·경계값이 defect마다 다르다.
    # (예: CLN_Flow — Remain_Coat는 T1, Particle은 T2)
    # main agent.py가 쓰는 최상위 키 구조는 유지하되, defect별 상세를 per_defect에 담고
    # 최상위 tier는 가장 보수적인(낮은) 등급으로 둔다. 과대 주장 방지.
    RANK = {"T1": 1, "T2": 2, "M1": 1, "M2": 2, "M3": 3}

    def detail(x):
        return {"tier": x.tier, "action_type": x.action_type,
                "threshold_raw": x.alert_threshold_raw,
                "normal_range": x.normal_range_raw, "risky_range": x.risky_range_raw,
                "risk_ratio": x.risk_ratio, "alert_usable": bool(x.alert_usable),
                "cliffs_delta": x.cliffs_delta,
                "threshold_source_dataset": x.threshold_source_dataset,
                "tier_reason": x.tier_reason}

    causes, monitors = {}, {}
    for _, x in tier.iterrows():
        if x.tier in ("T1", "T2") and x.role.startswith("원인"):
            b = causes
        elif x.tier.startswith("M"):
            b = monitors
        else:
            continue
        if x.factor in b:
            e = b[x.factor]
            e["defects"].append(x.defect)
            e["per_defect"][x.defect] = detail(x)
            if RANK.get(x.tier, 9) > RANK.get(e["tier"], 9):
                e["tier"] = x.tier          # 더 낮은 등급으로 내림
                e["action_type"] = x.action_type
                e["actionable"] = x.tier in ("T1", "T2")
            e["note_multi_defect"] = ("defect마다 티어·경계값이 다르다. "
                                      "per_defect를 반드시 확인할 것.")
        else:
            e = entry(x)
            e["per_defect"] = {x.defect: detail(x)}
            b[x.factor] = e

    no_cause = {}
    for d_ in DEFECTS:
        if not any(d_ in e["defects"] for e in causes.values()):
            sub = tier[tier.defect == d_]
            no_cause[d_] = {
                "confirmed_cause_count": 0,
                "answer": f"{d_}의 조치 가능한 확정 원인은 현재 0건입니다.",
                "candidates_below_bar": [
                    {"factor": y.factor, "tier": y.tier, "reason": y.tier_reason}
                    for _, y in sub.iterrows() if y.tier in ("T3", "T4")],
            }

    return {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basis": "확정 도메인 11건 × (통계검정 Mann-Whitney U + Cliff's delta + BH-FDR, "
                 "RandomForest 순열중요도). 원본 10만 + r1 10만 = 20만행.",
        "cause_factors": causes,          # ← main agent.py가 읽는 키
        "monitor_factors": monitors,
        "defects_without_confirmed_cause": no_cause,
        "tier_legend": {
            "T1": "원인 · 즉시조치 — 통계·RF 모두 통과",
            "T2": "원인 · 조건부조치 — 2개 중 1개 통과 또는 재현 실패",
            "T3": "원인 후보 · 감시만 — 통계·RF 모두 미달. 원인이라고 답하지 말 것",
            "T4": "판단보류 — 도메인과 데이터 방향이 반대. 양쪽 병기할 것",
            "M1": "감시지표 · 경보 전용 — 조치 지시 금지",
        },
        "external_owned": {
            "Vibration": {
                "defects": ["Chipping", "Micro_Crack"],
                "reason": "값 조정이 아닌 설비 정비 대상 — 추세·상하한 급이탈 알람 전용",
                "owner": "추세분석 담당",
                "file": "rel_28_vibration_alarm.csv",
                "note": "티어표에 없음. Vibration 알람이 오면 위 2개 defect와 연결할 것.",
            }
        },
        "ng_code_summary": ng.to_dict("records"),
        "agent_rules": [
            "tier가 T3·T4인 인자를 '원인'이라고 답하지 말 것.",
            "alert_usable=false 인 인자로 경보를 만들지 말 것 "
            "(위험구간 불량률이 정상구간보다 낮음).",
            "testability가 '검정불가'면 '무관하다'가 아니라 "
            "'이 데이터로는 확인할 수 없다'고 답할 것.",
            "threshold_source_dataset이 'r1 주도'면 "
            "'열화가 진행된 상황 기준'이라는 단서를 붙일 것.",
            "Vibration은 이 표에 없다. 추세분석 담당 산출물을 참조할 것.",
            "role이 감시지표인 인자에 조치를 지시하지 말 것. 경보만.",
            "SOP는 아직 수령하지 않았다. 조치 문구를 지어내지 말 것.",
        ],
        "known_limitations": [
            "이 데이터셋은 멘토가 고장 시나리오를 주입해 만든 것이다. 주입되지 않은 "
            "시나리오는 검정 자체가 불가능하므로, 신호가 없다고 무관한 것이 아니다.",
            "Chipping은 원본에 pure 표본이 3건뿐이라 사실상 r1 단독 판정이다.",
            "Head_Temp 경계값 42.646은 원본에서는 2,099행만 넘고 그 구간 Chipping이 "
            "0건이다. r1(열화 주입)에서만 72% 발생한다.",
            "SOP 미수령 — sop 칸은 비어 있다.",
            "CLN_Pressure 급락(spike) 판단 기준이 아직 없다.",
        ],
        "sop": {"status": "SOP 미수령 — 멘토 제공 대기", "entries": []},
    }


# ==================================================================== 실행
if __name__ == "__main__":
    print("[2/6] 티어표 보강")
    tier = enrich_tier_table()
    tier.to_csv(OUT / "rel_20_tier_table.csv", index=False, encoding="utf-8-sig")
    print(f"    rel_20_tier_table.csv  {len(tier)}행 × {len(tier.columns)}열")

    print("[3/6] Vibration 별도 영역")
    vib = build_vibration_area()
    vib.to_csv(OUT / "rel_28_vibration_alarm.csv", index=False, encoding="utf-8-sig")
    print(f"    rel_28_vibration_alarm.csv  {len(vib)}행")

    print("[4/6] NG_Code 요약")
    ng = build_ng_summary()
    ng.to_csv(OUT / "rel_29_ng_code_summary.csv", index=False, encoding="utf-8-sig")
    print(f"    rel_29_ng_code_summary.csv  {len(ng)}행")

    print("[5/6] 추세 인터페이스")
    tr = build_trend_interface(tier)
    tr.to_csv(OUT / "rel_30_trend_interface.csv", index=False, encoding="utf-8-sig")
    print(f"    rel_30_trend_interface.csv  {len(tr)}행")

    print("[6/6] Agent 계약 (경로·키 고정)")
    payload = build_agent_payload(tier, vib, ng)
    (OUT / "agent_cause_factors.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    agent_cause_factors.json  v{payload['schema_version']}  "
          f"원인 {len(payload['cause_factors'])} / 감시 {len(payload['monitor_factors'])}")

    # ------------------------------------------------------------------ 출력
    W = 100
    print("\n" + "=" * W)
    print("NG_Code 요약 (원본 10만 + r1 10만 = 20만행)")
    print("=" * W)
    print(f"{'구분':14s} {'NG_Code':12s} {'건수':>10s} {'비율':>9s}")
    print("-" * W)
    for _, x in ng.iterrows():
        print(f"{x['구분']:14s} {x.NG_Code:12s} {x['건수']:>10,} {x['비율_pct']:>8.3f}%")

    print("\n" + "=" * W)
    print("Vibration — 티어표 밖 별도 알람 영역 (rel_28)")
    print("=" * W)
    v = vib.iloc[0]
    print(f"  공식 스펙        : 없음 (멘토 spec.py 10개 변수에 미포함)")
    print(f"  데이터 상한 후보 : p99 {v.upper_candidate_p99}  /  p99.9 {v.upper_candidate_p999}")
    print(f"  원본 p99 {v.upper_original_p99}   r1 p99 {v.upper_r1_p99}")
    for _, x in vib.iterrows():
        warn = "" if x.lift_above_p99 > 1 else "   ⚠ 상한 초과가 이 defect를 예측 못 함"
        print(f"  {x.defect:12s} p99 초과 구간 불량률 {x.defect_rate_above_p99_pct:>6.2f}%"
              f"  (전체 {x.defect_rate_overall_pct:.2f}%, {x.lift_above_p99}배){warn}")
    print(f"  추세 기준        : 빈칸 — 추세분석 담당이 채움")

    print("\n" + "=" * W)
    print("경계값을 어느 데이터셋이 정했나 (r1 주도면 정상 운전에서 도달 안 할 수 있음)")
    print("=" * W)
    for _, x in tier.iterrows():
        ro = x.defect_rate_risky_original_pct
        r1_ = x.defect_rate_risky_r1_pct
        print(f"  {x.tier:3s} {x.defect:12s} {x.factor:22s} {x.threshold_source_dataset:22s}"
              f" 원본 {x.n_risky_original:>7,}행({ro if ro is not None else 0:>6.2f}%)"
              f" r1 {x.n_risky_r1:>7,}행({r1_ if r1_ is not None else 0:>6.2f}%)")

    print("\n" + "=" * W)
    print("Agent 계약 — main agent.py가 읽는 cause_factors")
    print("=" * W)
    for k, v_ in payload["cause_factors"].items():
        print(f"  {k:24s} {'/'.join(v_['defects']):22s} {v_['tier']}  {v_['action_type']}")
    print(f"\n  감시지표: {', '.join(payload['monitor_factors'])}")
    print(f"  확정원인 0건 defect: {', '.join(payload['defects_without_confirmed_cause'])}")
    print("=" * W)
