"""Goal5 — 러프 Health Index + 경보 + SOP 제안 (월요일 대시보드용, 1차 버전).

목적: 월요일 멘토 미팅 전 "대충이라도" 보여줄 결과물. 정교한 최종 버전이 아니라
지금까지 팀이 확정한 유효인자(daeho=Particle, 전성재=Remain_Coat,
JHdaimma=Chipping/Micro_Crack)를 모아서 실제 숫자로 된 Health Index/경보/SOP를 만든다.

가중치는 전부 잠정치이며 문서에 그렇게 명시한다 (pipeline/README.md의 Goal5 설계와 동일한
원칙 — 자동학습 가중치는 이번 범위 밖).

실행 (저장소 루트에서):
  python "26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py"

산출물 (이 폴더 안):
  01_health_index_by_machine_date.csv   Machine x Date 단위 Health Index
  02_active_alerts.csv                  현재(최근 7일) 경보 목록
  03_sop_suggestions.csv                경보별 SOP 제안 매핑
  dashboard_data.json                   대시보드 HTML이 바로 읽는 통합 데이터
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config
from pipeline.common import load_dataset, compute_stratum_baseline_stats, zscore_transform

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 팀이 각 defect별로 확정한 "원인(cause)" FDC 변수. 출처:
#   Particle:    daeho  26.07.31_2058_Goal2_PARTICLE_후속검증 (선행신호 검증까지 완료)
#   Remain_Coat: 전성재 26.07.31_Goal2_REM_COAT_유효인자_분석_전성재 (Machine 통제 다변량, v2)
#   Chipping:    JHdaimma 26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma (SHAP 모델A)
#   Micro_Crack: JHdaimma 동일 (Vibration/Cooling_Flow = Chipping과 공유 원인)
# direction: "up"=높을수록 위험, "down"=낮을수록 위험
# ---------------------------------------------------------------------------
CAUSE_FACTORS = {
    "Vibration": {
        "direction": "up",
        "defects": ["Particle", "Micro_Crack"],
        "owner": "daeho / JHdaimma",
        "mechanism": "기계적 진동 -> 디브리 비산/재부착(Particle), 응력 축적(Micro_Crack)",
    },
    "CLN_Pressure": {
        "direction": "down",
        "defects": ["Remain_Coat"],
        "owner": "전성재",
        "mechanism": "세정 압력 부족 -> 코팅 미제거",
    },
    "Laser_Power": {
        "direction": "down",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "출력 부족 -> low-k 불완전 승화 -> 블레이드가 잔류물 타격",
    },
    "Power_Efficiency": {
        "direction": "either",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "효율 이상(과다/과소 모두) -> 승화 불완전 (멘토: U자형 비선형 주의)",
    },
    "Head_Temp": {
        "direction": "up",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "헤드온도 상승 -> 굴절률 변화 -> 센터링 변화 -> Chipping",
    },
    "Laser_Centering_Position": {
        "direction": "either",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "빔 중심 이탈 -> 비대칭 절단",
    },
    "Cooling_Flow": {
        "direction": "down",
        "defects": ["Micro_Crack"],
        "owner": "JHdaimma",
        "mechanism": "냉각 유량 부족(Chipping과 공유 원인으로 확인)",
    },
    "Kerf_Width_Profile": {
        "direction": "either",
        "defects": ["Chipping"],
        "owner": "Jun / JHdaimma",
        "mechanism": "가공폭 과다/과소 모두 위험 -> 패키지 크기 불균형 또는 가공영역 이탈 "
                     "(JHdaimma: 통계검정/permutation/SHAP 3방법 합의, Jun: confirmed)",
    },
    "Top_Kerf": {
        "direction": "either",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "Kerf_Width_Profile과 동일 메커니즘 상속 (3방법 합의로 확정)",
    },
    "Bottom_Kerf": {
        "direction": "either",
        "defects": ["Chipping"],
        "owner": "JHdaimma",
        "mechanism": "Kerf_Width_Profile과 동일 메커니즘 상속 (3방법 합의로 확정, "
                     "값 중복 여부는 팀 자체 검증 완료 — 중복 아님)",
    },
    "Groove_Depth": {
        "direction": "down",
        "defects": ["Chipping"],
        "owner": "Jun",
        "mechanism": "가공 깊이 부족(deep이 아니라 shallow가 위험) -> Low-k가 완전히 승화되지 "
                     "못해 Blade 진입 시 Chipping 발생. Jun 통계검정 confirmed. "
                     "(정정 26.08.02: JHdaimma 모델에서 Laser_Power의 결과값(R²=0.606)으로도 "
                     "나오지만, 이건 JHdaimma가 Chipping 예측 후보에서 애초에 제외하고 다른 "
                     "회귀로만 다룬 것뿐 — Jun이 별도로 직접 검정해서 confirmed 받은 결과를 "
                     "무효화하는 근거가 아님. JHdaimma도 감시지표로 -0.750(얕을수록 위험과 "
                     "일치하는 강한 음의 방향)을 별도 확인함.)",
    },
}
CAUSE_COLS = list(CAUSE_FACTORS.keys())

# 원인(CAUSE_FACTORS)으로 확정하기엔 근거 부족하지만 참고용으로 같이 보는 감시지표.
# 주의: 이 딕셔너리는 아직 build_alerts/build_sop_suggestions 등 어디서도 안 쓰임(죽은 코드) —
# 실제로 대시보드/경보에 반영하려면 별도 배선이 필요하다.
MONITOR_FACTORS = {
    "Surface_Roughness": ["Particle", "Chipping", "Micro_Crack"],
}

DEFECT_RATE_COLS = ["Particle_rate", "Remain_Coat_rate", "Micro_Crack_rate", "Chipping_rate"]

# 러프 가중치 (잠정 — 멘토/팀 논의로 조정 예정)
W_DEFECT = 3.0     # (100 - Yield_7d_ma) 에 곱하는 배율
W_STABILITY = 8.0  # 원인변수 평균 |z| 에 곱하는 배율
W_TREND = 5.0      # 나쁜 방향 추세 변수 1개당 감점
CAP_DEFECT = 45
CAP_STABILITY = 30
CAP_TREND = 20
# 실제 분포(최초 실행 결과 min=75.5, DP02/DP03가 지속적으로 75~78 구간)를 보고 잡은 값.
# 정교한 기준이 아니라 "지금 뚜렷하게 낮은 장비 2대를 놓치지 않는" 러프 임계값.
ALERT_HI_THRESHOLD = 80
ALERT_Z_THRESHOLD = 2.0


def load_step0_outputs():
    baseline_opcond = pd.read_csv(config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv")
    machine_trend = pd.read_csv(config.PREPROCESSING_DIR / "00_machine_column_trend.csv")
    return baseline_opcond, machine_trend


def compute_daily_stability(df: pd.DataFrame, baseline_opcond: pd.DataFrame) -> pd.DataFrame:
    """cause 변수 7개의 OPCOND 층화 z-score를 계산해 Machine x Date 평균 |z|로 집계."""
    z_df = zscore_transform(df, baseline_opcond, config.OPCOND, CAUSE_COLS)
    z_df["date"] = z_df["DateTime"].dt.date

    # direction 반영: "down"이 위험이면 z를 뒤집어서 "z가 클수록 위험"으로 통일.
    for col, meta in CAUSE_FACTORS.items():
        zcol = f"{col}_z"
        if meta["direction"] == "down":
            z_df[zcol] = -z_df[zcol]
        elif meta["direction"] == "either":
            z_df[zcol] = z_df[zcol].abs()

    z_cols = [f"{c}_z" for c in CAUSE_COLS]
    daily = z_df.groupby(["Machine_ID", "date"])[z_cols].mean().reset_index()
    daily["mean_abs_risk_z"] = daily[z_cols].mean(axis=1)
    return daily, z_df


def compute_machine_bad_trend_detail(machine_trend: pd.DataFrame) -> pd.DataFrame:
    """cause 변수별로 '나쁜 방향' 추세면 표시. direction=either는 상승/하강 둘 다 나쁨으로 취급.

    개수(bad_trend_count)뿐 아니라 어떤 변수가 걸렸는지(factor 목록)도 함께 반환 —
    경보 메시지에서 "왜 이 장비 점수가 낮은지"를 설명하는 데 필요하다.
    """
    rows = []
    for _, row in machine_trend.iterrows():
        col = row["column"]
        if col not in CAUSE_FACTORS:
            continue
        direction = CAUSE_FACTORS[col]["direction"]
        trend_class = row["trend_class"]
        bad = False
        if direction == "up" and trend_class == "candidate_upward_drift":
            bad = True
        elif direction == "down" and trend_class == "candidate_downward_drift":
            bad = True
        elif direction == "either" and trend_class in ("candidate_upward_drift", "candidate_downward_drift"):
            bad = True
        rows.append({"Machine_ID": row["Machine_ID"], "column": col, "bad_trend": bad})
    bad_df = pd.DataFrame(rows)
    count = bad_df.groupby("Machine_ID")["bad_trend"].sum().rename("bad_trend_count")
    factors = (
        bad_df[bad_df["bad_trend"]]
        .groupby("Machine_ID")["column"]
        .apply(lambda s: list(s))
        .rename("bad_trend_factors")
    )
    return pd.concat([count, factors], axis=1).reset_index()


def build_health_index(df: pd.DataFrame, baseline_opcond, machine_trend) -> pd.DataFrame:
    daily_stability, z_df = compute_daily_stability(df, baseline_opcond)

    # 05_machine_daily_trend.csv: analysis_step_by_step.py 산출물 (Yield_7d_ma, defect rate 포함)
    trend_table = pd.read_csv(REPO_ROOT / "analysis_outputs" / "05_machine_daily_trend.csv")
    trend_table["date"] = pd.to_datetime(trend_table["date"]).dt.date

    merged = daily_stability.merge(
        trend_table[["Machine_ID", "date", "Yield_7d_ma"] + DEFECT_RATE_COLS],
        on=["Machine_ID", "date"], how="left",
    )

    bad_trend_detail = compute_machine_bad_trend_detail(machine_trend)
    merged = merged.merge(bad_trend_detail, on="Machine_ID", how="left")
    merged["bad_trend_count"] = merged["bad_trend_count"].fillna(0)
    merged["bad_trend_factors"] = merged["bad_trend_factors"].apply(lambda v: v if isinstance(v, list) else [])

    merged["defect_penalty"] = ((100 - merged["Yield_7d_ma"].fillna(100)) * W_DEFECT).clip(0, CAP_DEFECT)
    merged["stability_penalty"] = (merged["mean_abs_risk_z"].clip(lower=0) * W_STABILITY).clip(0, CAP_STABILITY)
    merged["trend_penalty"] = (merged["bad_trend_count"] * W_TREND).clip(0, CAP_TREND)

    merged["health_index"] = (
        100 - merged["defect_penalty"] - merged["stability_penalty"] - merged["trend_penalty"]
    ).clip(0, 100).round(1)

    return merged.sort_values(["Machine_ID", "date"]), z_df


def build_alerts(hi_table: pd.DataFrame, z_df: pd.DataFrame) -> pd.DataFrame:
    """최근 7일 기준 경보: Health Index 낮음 OR 특정 원인변수가 위험 임계값을 넘음."""
    recent_cutoff = hi_table["date"].max() - pd.Timedelta(days=7)
    recent = hi_table[pd.to_datetime(hi_table["date"]) > pd.Timestamp(recent_cutoff)]

    alerts = []
    for _, row in recent.iterrows():
        if row["health_index"] < ALERT_HI_THRESHOLD:
            # 우선순위: ① 당일 z-score가 임계값을 넘는 급성 신호, ② 없으면 그 장비가
            # 지속적으로 나쁜 방향 추세를 보이는 원인변수(trend_penalty의 실제 근거).
            spike = [c for c in CAUSE_COLS if row.get(f"{c}_z", 0) is not None and row[f"{c}_z"] >= ALERT_Z_THRESHOLD]
            trending = row.get("bad_trend_factors", [])
            if spike:
                triggered = spike
                trigger_type = "당일 급성 이상"
            elif trending:
                triggered = trending
                trigger_type = "지속적 추세 이상 (spec 이내지만 서서히 악화)"
            else:
                triggered = []
                trigger_type = "복합 원인 (단일 변수로 설명 안 됨)"
            alerts.append({
                "Machine_ID": row["Machine_ID"],
                "date": str(row["date"]),
                "health_index": row["health_index"],
                "defect_penalty": row["defect_penalty"],
                "stability_penalty": row["stability_penalty"],
                "trend_penalty": row["trend_penalty"],
                "trigger_type": trigger_type,
                "triggered_factors": ",".join(triggered) if triggered else "-",
            })
    columns = [
        "Machine_ID", "date", "health_index", "defect_penalty",
        "stability_penalty", "trend_penalty", "trigger_type", "triggered_factors",
    ]
    if not alerts:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(alerts)[columns].sort_values("health_index")


def build_sop_suggestions(alerts: pd.DataFrame) -> pd.DataFrame:
    """경보에 등장한 원인변수마다 점검/조치 룰 기반 SOP 초안 — 전부 DRAFT_UNVERIFIED."""
    triggered_all = set()
    for factors in alerts["triggered_factors"]:
        for f in factors.split(","):
            if f in CAUSE_FACTORS:
                triggered_all.add(f)

    rows = []
    for factor in sorted(triggered_all):
        meta = CAUSE_FACTORS[factor]
        rows.append({
            "factor": factor,
            "defects": ", ".join(meta["defects"]),
            "mechanism": meta["mechanism"],
            "check": f"{factor} 실측값을 baseline(00_stratum_baseline_stats_by_opcond.csv) 대비 확인",
            "action": f"{factor} 이상 원인(설비 점검/재보정) 조치 후 {', '.join(meta['defects'])} 불량률 72시간 재확인",
            "source": meta["owner"],
            "status": "DRAFT_UNVERIFIED — 멘토/현장 SOP 확인 전까지 참고용",
        })
    return pd.DataFrame(rows)


def main() -> None:
    df = load_dataset()
    baseline_opcond, machine_trend = load_step0_outputs()

    hi_table, z_df = build_health_index(df, baseline_opcond, machine_trend)
    z_cols = [f"{c}_z" for c in CAUSE_COLS]
    daily_z_lookup = z_df.groupby(["Machine_ID", "date"])[z_cols].mean().reset_index()
    hi_full = hi_table.merge(daily_z_lookup, on=["Machine_ID", "date"], suffixes=("", "_dup"))

    hi_full.to_csv(OUT_DIR / "01_health_index_by_machine_date.csv", index=False, encoding="utf-8-sig")

    alerts = build_alerts(hi_full, z_df)
    alerts.to_csv(OUT_DIR / "02_active_alerts.csv", index=False, encoding="utf-8-sig")

    sop = build_sop_suggestions(alerts)
    sop.to_csv(OUT_DIR / "03_sop_suggestions.csv", index=False, encoding="utf-8-sig")

    # 대시보드용 통합 JSON
    hi_full["date"] = hi_full["date"].astype(str)
    dashboard = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "health_index_series": hi_full[["Machine_ID", "date", "health_index", "defect_penalty",
                                          "stability_penalty", "trend_penalty"]].to_dict(orient="records"),
        "alerts": alerts.to_dict(orient="records"),
        "sop_suggestions": sop.to_dict(orient="records"),
        "cause_factors": CAUSE_FACTORS,
    }
    with open(OUT_DIR / "dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: Health Index {len(hi_full)}행, 경보 {len(alerts)}건, SOP 제안 {len(sop)}건")
    print(f"장비별 최신 Health Index:")
    latest = hi_full.sort_values("date").groupby("Machine_ID").tail(1)
    print(latest[["Machine_ID", "date", "health_index"]].to_string(index=False))


if __name__ == "__main__":
    main()
