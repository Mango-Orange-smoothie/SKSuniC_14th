"""Health Index 재설계 v2 — "오늘 뭐부터 봐야 하는가"를 위한 우선순위 신호 계산.

배경: 이전 버전(v1)은 불량페널티+안정성페널티+추세페널티를 가중치(3/8/5)로 더해
하나의 점수로 뭉갰다. 근거 없는 가중치 문제도 있었지만, 더 근본적으로는 목적과
안 맞았다 — 이 프로젝트는 "과거를 요약한 리포트"가 아니라 "엔지니어에게 뭘 보라고
알려주는 AI Agent"가 목표다. 하나의 점수로 뭉개면 에이전트가 "왜 급한지" 설명을
못 한다.

v2 구조:
  1. defect별로 확정 원인변수(CAUSE_FACTORS)의 "레벨"(지금 얼마나 벗어났나)과
     "추세"(최근 며칠간 얼마나 빠르게 나빠지는가)를 따로따로 보고한다 — 하나의
     점수로 합치지 않는다. 합치는 가중치 자체가 또 다른 임의값이 되기 때문에,
     그 판단(레벨이 심각한지 추세가 나쁜지 종합적으로 얼마나 급한지)은 AI Agent가
     자연어로 설명하게 맡긴다.
  2. 확정 원인이 아닌 나머지 변수도 같은 레벨/추세 계산을 적용한다(안전망) —
     단 defect 연결/SOP는 안 붙이고 "미확인 이상"으로만 표시한다. Step0가 이미
     전체 연속형 변수에 대해 baseline/일별 시계열을 계산해둬서 추가 비용이 거의 없다.
  3. 실제 불량 발생 여부(최근 7일 defect rate)는 레벨/추세와 별개 필드로 분리한다
     — "이미 터진 것"과 "터지기 전 조짐"은 다른 층위의 정보라서 섞으면 안 된다.

이 스크립트는 정적 HTML 대시보드를 만들지 않는다(v1의 build_dashboard_html.py는
삭제됨) — 산출물은 AI Agent(agent.py)가 직접 읽는 health_index_data.json 하나뿐이다.

실행 (저장소 루트에서):
  python "26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py"

산출물 (이 폴더 안):
  health_index_data.json   AI Agent가 읽는 데이터 (레벨/추세/실제발생/미확인이상)
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
from pipeline.common import load_dataset, zscore_transform
from pipeline.step0_preprocessing import CONTINUOUS_TREND_COLS

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 팀이 각 defect별로 확정한 "원인(cause)" FDC/response 변수. 출처:
#   Particle:    daeho  26.07.31_2058_Goal2_PARTICLE_후속검증 (선행신호 검증까지 완료)
#   Remain_Coat: 전성재 26.07.31_Goal2_REM_COAT_유효인자_분석_전성재 (Machine 통제 다변량, v2)
#   Chipping:    JHdaimma 26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma (3방법 합의:
#                통계검정+permutation importance+SHAP), Jun의 CHIP 분석(confirmed) 교차확인
#   Micro_Crack: JHdaimma 동일 (Vibration/Cooling_Flow = Chipping과 공유 원인)
# direction: "up"=높을수록 위험, "down"=낮을수록 위험, "either"=양방향 다 위험(U자형 등)
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
        "mechanism": "가공 깊이 부족(shallow가 위험, deep은 문제 아님) -> Low-k가 완전히 "
                     "승화되지 못해 Blade 진입 시 Chipping 발생. 통계검정 confirmed.",
    },
}
CAUSE_COLS = set(CAUSE_FACTORS.keys())

DEFECT_RATE_COLS = {
    "Particle": "Particle_rate",
    "Remain_Coat": "Remain_Coat_rate",
    "Micro_Crack": "Micro_Crack_rate",
    "Chipping": "Chipping_rate",
}

# 미확인 이상(안전망) 판정 임계값 — 확정 원인이 아니라서 보수적으로 잡음. 근거 있는
# 최적화 값이 아니라 관례적 컷오프(대략 상위/하위 2.3%)다. 필요시 조정할 것.
ANOMALY_Z_THRESHOLD = 2.0
# 레벨/추세 계산에 쓰는 최근 구간 길이(일). 통계적 유의성을 새로 검정하는 게 아니라
# "최근 방향/속도"를 서술하는 용도라서 짧아도 된다 — 다만 지난 검증(DP02 Laser_Power
# 사례)에서 확인했듯 이 값 자체로 "유의미한 추세 확정"을 주장하지는 않는다.
RECENT_WINDOW_DAYS = 14
RECENT_DEFECT_WINDOW_DAYS = 7


def load_step0_outputs():
    opcond_baseline = pd.read_csv(config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv")
    daily_series = pd.read_csv(config.PREPROCESSING_DIR / "00_machine_daily_series.csv")
    daily_series["date"] = pd.to_datetime(daily_series["date"])
    return opcond_baseline, daily_series


def direction_of(column: str) -> str:
    """CAUSE_FACTORS에 있으면 확정된 방향, 없으면 방향 모르니 either(양방향 이상 취급)."""
    meta = CAUSE_FACTORS.get(column)
    return meta["direction"] if meta else "either"


def compute_level_and_trend(daily_series: pd.DataFrame) -> pd.DataFrame:
    """장비×컬럼별로 (a) 최근 시점 레벨, (b) 최근 N일 추세 기울기를 계산한다.

    레벨/추세 둘 다 daily_mean_z(00_machine_daily_series.csv, OPCOND baseline 대비
    일별 정규화 잔차)를 그대로 쓴다 — 새 통계 계산이 아니라 기존 산출물 재사용.
    방향(up/down/either)에 따라 부호를 통일해서 "값이 클수록 위험"으로 맞춘다.
    """
    rows = []
    for (machine, col), g in daily_series.groupby(["Machine_ID", "column"]):
        g = g.sort_values("date")
        direction = direction_of(col)
        z = g["daily_mean_z"]
        if direction == "down":
            z = -z
        elif direction == "either":
            z = z.abs()
        # direction == "up"은 그대로

        valid = z.dropna()
        if valid.empty:
            continue
        level_z = float(valid.iloc[-1])
        latest_date = g.loc[valid.index[-1], "date"]

        recent = valid.iloc[-RECENT_WINDOW_DAYS:]
        if len(recent) >= 3 and recent.nunique() > 1:
            x = np.arange(len(recent))
            slope = float(np.polyfit(x, recent.values, 1)[0])
        else:
            slope = None

        rows.append({
            "Machine_ID": machine,
            "column": col,
            "direction": direction,
            "latest_date": str(latest_date.date()),
            "level_z": round(level_z, 3),
            "recent_trend_slope_z_per_day": round(slope, 4) if slope is not None else None,
            "is_cause_factor": col in CAUSE_COLS,
        })
    return pd.DataFrame(rows)


def load_defect_occurrence() -> pd.DataFrame:
    """05_machine_daily_trend.csv(analysis_step_by_step.py 산출물)로 최근 실제 발생 여부 판정."""
    trend = pd.read_csv(REPO_ROOT / "analysis_outputs" / "05_machine_daily_trend.csv")
    trend["date"] = pd.to_datetime(trend["date"])
    cutoff = trend["date"].max() - pd.Timedelta(days=RECENT_DEFECT_WINDOW_DAYS)
    recent = trend[trend["date"] > cutoff]

    rows = []
    for machine, g in recent.groupby("Machine_ID"):
        for defect, rate_col in DEFECT_RATE_COLS.items():
            occurred = bool((g[rate_col] > 0).any())
            count_days = int((g[rate_col] > 0).sum())
            rows.append({
                "Machine_ID": machine,
                "defect": defect,
                "actual_occurred_recent_7d": occurred,
                "occurred_days_recent_7d": count_days,
            })
    return pd.DataFrame(rows)


def build_machine_snapshot(level_trend: pd.DataFrame, occurrence: pd.DataFrame) -> dict:
    """장비별로 defect별 원인 신호(확정) + 미확인 이상(안전망) + 실제발생 여부를 묶는다."""
    machines: dict[str, dict] = {}

    for machine, g in level_trend.groupby("Machine_ID"):
        cause_rows = g[g["is_cause_factor"]]
        other_rows = g[~g["is_cause_factor"]]

        # defect별로 원인변수 묶기
        defect_signals: dict[str, dict] = {}
        for defect in DEFECT_RATE_COLS:
            factor_names = [f for f, meta in CAUSE_FACTORS.items() if defect in meta["defects"]]
            factor_rows = cause_rows[cause_rows["column"].isin(factor_names)]
            if factor_rows.empty:
                continue
            causes = {}
            for _, row in factor_rows.iterrows():
                meta = CAUSE_FACTORS[row["column"]]
                causes[row["column"]] = {
                    "level_z": row["level_z"],
                    "recent_trend_slope_z_per_day": row["recent_trend_slope_z_per_day"],
                    "direction": meta["direction"],
                    "mechanism": meta["mechanism"],
                    "source": meta["owner"],
                }
            occ = occurrence[(occurrence["Machine_ID"] == machine) & (occurrence["defect"] == defect)]
            defect_signals[defect] = {
                "actual_occurred_recent_7d": bool(occ["actual_occurred_recent_7d"].iloc[0]) if len(occ) else False,
                "occurred_days_recent_7d": int(occ["occurred_days_recent_7d"].iloc[0]) if len(occ) else 0,
                "causes": causes,
            }

        # 미확인 이상(안전망): 확정 원인 아닌 변수 중 레벨이 임계값 넘는 것만
        anomalies = []
        flagged = other_rows[other_rows["level_z"].abs() >= ANOMALY_Z_THRESHOLD]
        for _, row in flagged.sort_values("level_z", ascending=False).iterrows():
            anomalies.append({
                "column": row["column"],
                "level_z": row["level_z"],
                "recent_trend_slope_z_per_day": row["recent_trend_slope_z_per_day"],
                "note": "확정 원인 아님 — 어느 defect와 연결되는지 검증 안 됨, 모니터링 참고용",
            })

        machines[machine] = {
            "latest_date": g["latest_date"].max(),
            "defect_signals": defect_signals,
            "unconfirmed_anomalies": anomalies,
        }
    return machines


def main() -> None:
    df = load_dataset()
    opcond_baseline, daily_series_raw = load_step0_outputs()

    # daily_series는 이미 OPCOND 정규화된 z-잔차를 담고 있음(Step0 산출물) — 여기서
    # zscore_transform을 다시 돌리지 않는다. df는 이 파일에서 더 안 씀(재현성 확인용으로만 로드).
    del df

    level_trend = compute_level_and_trend(daily_series_raw)
    level_trend.to_csv(OUT_DIR / "01_level_trend_by_machine_column.csv", index=False, encoding="utf-8-sig")

    occurrence = load_defect_occurrence()
    occurrence.to_csv(OUT_DIR / "02_defect_occurrence_recent7d.csv", index=False, encoding="utf-8-sig")

    machines = build_machine_snapshot(level_trend, occurrence)

    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "recent_window_days": RECENT_WINDOW_DAYS,
        "anomaly_z_threshold": ANOMALY_Z_THRESHOLD,
        "cause_factors": CAUSE_FACTORS,
        "machines": machines,
    }
    with open(OUT_DIR / "health_index_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: {len(machines)}개 장비 스냅샷 생성")
    for machine, snap in machines.items():
        n_defects = len(snap["defect_signals"])
        n_anomalies = len(snap["unconfirmed_anomalies"])
        print(f"  {machine}: defect 신호 {n_defects}개, 미확인 이상 {n_anomalies}건")


if __name__ == "__main__":
    main()
