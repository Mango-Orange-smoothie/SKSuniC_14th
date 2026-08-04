"""Health Index 재설계 v2 — "오늘 뭐부터 봐야 하는가"를 위한 우선순위 신호 계산.

배경: 이전 버전(v1)은 불량페널티+안정성페널티+추세페널티를 가중치(3/8/5)로 더해
하나의 점수로 뭉갰다. 근거 없는 가중치 문제도 있었지만, 더 근본적으로는 목적과
안 맞았다 — 이 프로젝트는 "과거를 요약한 리포트"가 아니라 "엔지니어에게 뭘 보라고
알려주는 AI Agent"가 목표다. 하나의 점수로 뭉개면 에이전트가 "왜 급한지" 설명을
못 한다.

v2 구조 — 엔지니어가 "오늘 뭐부터 볼지" 정할 수 있는 숫자(0~100, 100이 건강)를 만들되,
임의 가중치 없이 만든다.

**Health Index가 답하는 질문은 "다른 장비/변수 대비 몇 등인가"가 아니라 "스펙 아웃(임시
USL/LSL) 되기 전에 미리 알 수 있는가"다.** (처음에 정규분포/순위 기반 백분위로 만들었다가,
그건 "통계적으로 얼마나 특이한가"를 재는 거라 목적과 안 맞아서 폐기하고 이 방식으로
다시 짰다.)

  1. **레벨 = 스펙 경계까지 남은 여유를 다 쓴 정도(margin_used_pct, 0~100+)**
       스펙 경계 z(boundary_z) = baseline(median)에서 임시 USL/LSL(정상군 p0.5~p99.5,
         00_stratum_baseline_stats_by_opcond.csv)까지의 거리를, robust z-scale로 잰 것.
         OPCOND 층별로 계산한 뒤 컬럼당 중앙값을 대표값으로 씀.
       margin_used_pct = (지금 레벨 z ÷ boundary_z) × 100
         0% = baseline 그대로, 100% = 스펙 경계 도달, 100% 넘으면 이미 스펙아웃.
       변수별 Health Index = 100 − clip(margin_used_pct, 0, 100)
  2. **추세 = 점수에 안 섞고, "예상 며칠 뒤 스펙아웃"으로 따로 보여준다.**
       margin_used_pct의 최근 14일 기울기(%/일)를 구해서, 나빠지는 방향이면
       (100 − 지금 margin_used_pct) ÷ 기울기 = 예상 며칠 뒤 스펙아웃.
       레벨(z)과 추세(z/일)는 단위가 달라 그냥 더하면 한쪽이 묻히는 문제가 있었어서,
       "점수 하나로 억지로 합치기"를 그만두고 서로 다른 질문에 각자 답하게 했다 —
       레벨은 "지금 얼마나 급한가", 추세는 "언제쯤 더 급해지는가".
  3. defect별 Health Index = 그 defect 원인변수들 중 최솟값(제일 나쁜 게 전체를 끌어내림)
     장비별 Health Index   = 그 장비 defect들 중 최솟값
  4. 확정 원인이 아닌 나머지 변수도 같은 레벨/추세 계산을 적용한다(안전망) — 단 defect
     연결/SOP는 안 붙이고 "미확인 이상"으로만 표시한다. Step0가 이미 전체 연속형
     변수에 대해 baseline/일별 시계열을 계산해둬서 추가 비용이 거의 없다.
  5. 실제 불량 발생 여부(최근 7일 defect rate)는 레벨/추세와 별개 필드로 분리한다
     — "이미 터진 것"과 "터지기 전 조짐"은 다른 층위의 정보라서 섞으면 안 된다.

알려진 한계: boundary_z는 컬럼당 대표값 하나(OPCOND 층별 중앙값)라서, 장비/레시피마다
실제 스펙 여유가 다를 수 있는 걸 다 못 담는다. margin_used_pct도 "일별 평균 z"를
"개별 샷 기준 p0.5~p99.5"랑 비교하는 거라, 하루 평균은 개별 샷보다 덜 극단적으로 나와서
실제보다 여유가 있어 보일 수 있다 — 다음 라운드에서 보완할 것.

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
from scipy import stats as scipy_stats

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config
from pipeline.spec import SPEC
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

# 미확인 이상(안전망) 판정 임계값 — 스펙 경계까지 남은 여유를 이 % 이상 썼으면 표시.
# 확정 원인이 아니라서 보수적으로(절반 이상 썼을 때만) 잡는다. 최적화된 값은 아니다.
ANOMALY_MARGIN_THRESHOLD_PCT = 50.0
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


def compute_spec_values(opcond_baseline: pd.DataFrame) -> dict[str, dict]:
    """컬럼별 baseline(median)과 임시 USL/LSL(p0.5~p99.5)을 원래 단위 그대로 대표값 하나로 정리.

    boundary_z(z-scale)와 별개로, 실제 값(원래 단위)을 그대로 보여주기 위한 것 —
    "29.3% 사용" 같은 추상적 숫자 대신 "현재 293.08 / 하한 297.01"처럼 실제 값으로
    보여주는 게 더 직관적이라는 피드백 반영.
    """
    spec: dict[str, dict] = {}
    for col, g in opcond_baseline.groupby("column"):
        spec[col] = {
            "baseline_median": float(g["median"].median()),
            "lsl": float(g["p0_5"].median()),
            "usl": float(g["p99_5"].median()),
        }
    return spec


def compute_boundary_z(opcond_baseline: pd.DataFrame) -> dict[str, float]:
    """컬럼별 "baseline에서 임시 스펙 경계(p0.5~p99.5)까지 몇 z 떨어져 있는지"를 구한다.

    OPCOND 층마다 살짝 다를 수 있어서, 층별로 계산한 뒤 중앙값을 컬럼의 대표값으로 쓴다.
    direction에 따라 어느 쪽 경계를 볼지 결정 — either는 둘 중 가까운 쪽(더 보수적인 쪽)을 쓴다.
    """
    boundary_z: dict[str, float] = {}
    for col, g in opcond_baseline.groupby("column"):
        direction = direction_of(col)
        scale = g["robust_z_scale"].where(g["robust_z_scale"].abs() > 1e-9)
        up_z = (g["p99_5"] - g["median"]) / scale
        down_z = (g["median"] - g["p0_5"]) / scale
        if direction == "up":
            candidate = up_z
        elif direction == "down":
            candidate = down_z
        else:
            candidate = pd.concat([up_z, down_z], axis=1).min(axis=1)
        candidate = candidate[candidate > 0].dropna()
        if len(candidate):
            boundary_z[col] = float(candidate.median())
    return boundary_z


def _real_spec_margin_pct(raw_values: pd.Series, direction: str, lsl: float, target: float, usl: float) -> pd.Series:
    """멘토 실측 스펙(pipeline/spec.py) 기준 margin_used_pct. 0=TARGET, 100=USL/LSL 도달.

    OPCOND 층별 정규화를 안 거치고 raw 값을 그대로 스펙과 비교한다 — 멘토가 준 스펙은
    Product/Recipe에 상관없는 절대 물리적 기준이라, 상대적 z-score가 아니라 실측값
    자체를 써야 맞다.
    """
    above = raw_values >= target
    margin = pd.Series(np.nan, index=raw_values.index, dtype=float)
    if usl > target:
        margin[above] = (raw_values[above] - target) / (usl - target) * 100
    if target > lsl:
        margin[~above] = (target - raw_values[~above]) / (target - lsl) * 100
    if direction == "up":
        margin[~above] = 0.0  # 위로만 위험한 변수는 target 아래로 벗어나도 여유 소진 아님
    elif direction == "down":
        margin[above] = 0.0
    return margin


def compute_level_and_trend(
    daily_series: pd.DataFrame, boundary_z: dict[str, float], spec_values: dict[str, dict],
) -> pd.DataFrame:
    """장비×컬럼별로 "스펙 경계까지 남은 여유"(레벨)와 "그 여유가 줄어드는 속도"(추세)를 계산한다.

    두 가지 기준 소스를 컬럼별로 섞어 쓴다:
      - SPEC(pipeline/spec.py)에 있는 10개 컬럼: 멘토가 준 진짜 LSL/TARGET/USL을 raw 값과
        직접 비교(spec_source="mentor_spec") — 신뢰도 높음.
      - 나머지 컬럼: daily_mean_z(OPCOND baseline 대비 일별 정규화 잔차)와 boundary_z(정상군
        p0.5~p99.5 기반 임시 경계)로 계산(spec_source="provisional_percentile") — 진짜
        스펙이 아니라 정상군 분포로 대체한 임시값이니 참고용으로만 쓸 것.
    실제 원래 단위 값(current_value/lsl/usl)도 같이 붙여서 "29.3% 사용"이 아니라 실제
    수치로 보여줄 수 있게 한다.
    """
    rows = []
    for (machine, col), g in daily_series.groupby(["Machine_ID", "column"]):
        g = g.sort_values("date")
        direction = direction_of(col)
        real_spec = SPEC.get(col)

        if real_spec is not None:
            spec_source = "mentor_spec"
            lsl_disp, usl_disp, baseline_disp = real_spec["LSL"], real_spec["USL"], real_spec["TARGET"]
            margin_pct = _real_spec_margin_pct(g["daily_mean"], direction, lsl_disp, baseline_disp, usl_disp)
            margin_pct.index = g.index
        else:
            b_z = boundary_z.get(col)
            spec = spec_values.get(col)
            if not b_z or not spec:
                continue
            spec_source = "provisional_percentile"
            lsl_disp, usl_disp, baseline_disp = spec["lsl"], spec["usl"], spec["baseline_median"]
            z = g["daily_mean_z"]
            if direction == "down":
                z = -z
            elif direction == "either":
                z = z.abs()
            # direction == "up"은 그대로
            margin_pct = (z / b_z) * 100  # 0=baseline, 100=스펙 경계, 100 넘으면 스펙아웃

        valid = margin_pct.dropna()
        if valid.empty:
            continue
        current_margin_pct = float(valid.iloc[-1])
        latest_idx = valid.index[-1]
        latest_date = g.loc[latest_idx, "date"]
        current_value = float(g.loc[latest_idx, "daily_mean"])
        health_index_var = 100 - min(max(current_margin_pct, 0.0), 100.0)
        spec_out = current_margin_pct >= 100

        recent = valid.iloc[-RECENT_WINDOW_DAYS:]
        margin_slope, est_days = None, None
        if len(recent) >= 3 and recent.nunique() > 1:
            x = np.arange(len(recent))
            lr = scipy_stats.linregress(x, recent.values)
            margin_slope = float(lr.slope)  # %/일 (양수=여유가 줄어드는 중)
            if not spec_out and margin_slope > 1e-9:
                remaining = 100 - current_margin_pct
                projected = remaining / margin_slope
                est_days = round(projected, 1) if projected <= 365 else None  # 1년 넘게 남으면 "임박 아님" 취급
            # 이미 스펙아웃이면 "며칠 뒤"는 의미 없으므로 est_days는 None으로 둔다 (spec_status로 대체)

        rows.append({
            "Machine_ID": machine,
            "column": col,
            "direction": direction,
            "latest_date": str(latest_date.date()),
            "current_value": round(current_value, 4),
            "baseline_median": round(baseline_disp, 4),
            "lsl": round(lsl_disp, 4),
            "usl": round(usl_disp, 4),
            "spec_source": spec_source,
            "spec_status": "SPEC_OUT" if spec_out else "OK",
            "margin_used_pct": round(current_margin_pct, 1),
            "health_index": round(health_index_var, 1),
            "margin_trend_pct_per_day": round(margin_slope, 3) if margin_slope is not None else None,
            "estimated_days_to_spec_out": est_days,
            "is_cause_factor": col in CAUSE_COLS,
        })
    return pd.DataFrame(rows)


TOP_N = 3  # 순위 표시 개수 — "제일 나쁜 것 하나"만 보여주지 말고 상위 N개를 보여달라는 피드백 반영


def aggregate_health_index(level_trend: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """변수별 Health Index를 defect별 -> 장비별로 집계한다 (둘 다 '최솟값' 규칙).

    평균이 아니라 최솟값을 쓰는 이유: 여러 원인변수 중 하나라도 심각하게 나쁘면
    그 defect 전체가 위험해야 한다 — "약한 고리가 전체를 결정한다"는 원칙이라
    가중치처럼 임의로 정할 여지가 없다. 대표값(최솟값)과 별개로, 상위 TOP_N개
    순위(worst_factors/worst_defects)도 같이 담아서 "제일 나쁜 것 하나"만 보여주지
    않고 여러 개를 순서대로 볼 수 있게 한다.
    """
    cause_rows = level_trend[level_trend["is_cause_factor"]]

    defect_rows = []
    for (machine, defect), _ in [
        ((m, d), None) for m in cause_rows["Machine_ID"].unique() for d in DEFECT_RATE_COLS
    ]:
        factor_names = [f for f, meta in CAUSE_FACTORS.items() if defect in meta["defects"]]
        sub = cause_rows[(cause_rows["Machine_ID"] == machine) & (cause_rows["column"].isin(factor_names))]
        if sub.empty:
            continue
        ranked = sub.sort_values("health_index").head(TOP_N)
        worst = ranked.iloc[0]
        defect_rows.append({
            "Machine_ID": machine,
            "defect": defect,
            "health_index": worst["health_index"],
            "worst_factor": worst["column"],
            "worst_factors": [
                {"factor": r["column"], "health_index": r["health_index"], "spec_status": r["spec_status"]}
                for _, r in ranked.iterrows()
            ],
        })
    defect_index = pd.DataFrame(defect_rows)

    machine_rows = []
    for machine, g in defect_index.groupby("Machine_ID"):
        ranked = g.sort_values("health_index").head(TOP_N)
        worst = ranked.iloc[0]
        machine_rows.append({
            "Machine_ID": machine,
            "health_index": worst["health_index"],
            "worst_defect": worst["defect"],
            "worst_defects": [
                {"defect": r["defect"], "health_index": r["health_index"], "worst_factor": r["worst_factor"]}
                for _, r in ranked.iterrows()
            ],
        })
    machine_index = pd.DataFrame(machine_rows)

    return defect_index, machine_index


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


def _none_if_nan(value):
    """DataFrame에 섞여 들어간 None이 NaN으로 바뀌는 걸 JSON 출력 직전에 되돌린다."""
    return None if pd.isna(value) else value


def build_machine_snapshot(
    level_trend: pd.DataFrame, occurrence: pd.DataFrame,
    defect_index: pd.DataFrame, machine_index: pd.DataFrame,
) -> dict:
    """장비별로 Health Index(장비/defect/변수 3단계) + 실제발생 여부 + 미확인 이상을 묶는다."""
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
                    "current_value": row["current_value"],
                    "baseline_median": row["baseline_median"],
                    "lsl": row["lsl"],
                    "usl": row["usl"],
                    "spec_source": row["spec_source"],
                    "spec_status": row["spec_status"],
                    "health_index": row["health_index"],
                    "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                    "estimated_days_to_spec_out": _none_if_nan(row["estimated_days_to_spec_out"]),
                    "direction": meta["direction"],
                    "mechanism": meta["mechanism"],
                    "source": meta["owner"],
                }
            occ = occurrence[(occurrence["Machine_ID"] == machine) & (occurrence["defect"] == defect)]
            d_idx = defect_index[(defect_index["Machine_ID"] == machine) & (defect_index["defect"] == defect)]
            defect_signals[defect] = {
                "health_index": float(d_idx["health_index"].iloc[0]) if len(d_idx) else None,
                "worst_factors": d_idx["worst_factors"].iloc[0] if len(d_idx) else [],
                "actual_occurred_recent_7d": bool(occ["actual_occurred_recent_7d"].iloc[0]) if len(occ) else False,
                "occurred_days_recent_7d": int(occ["occurred_days_recent_7d"].iloc[0]) if len(occ) else 0,
                "causes": causes,
            }

        # 미확인 이상(안전망): 확정 원인 아닌 변수 중 스펙 여유를 많이 쓴 것만
        anomalies = []
        flagged = other_rows[other_rows["margin_used_pct"] >= ANOMALY_MARGIN_THRESHOLD_PCT]
        for _, row in flagged.sort_values("margin_used_pct", ascending=False).iterrows():
            anomalies.append({
                "column": row["column"],
                "current_value": row["current_value"],
                "baseline_median": row["baseline_median"],
                "lsl": row["lsl"],
                "usl": row["usl"],
                "spec_source": row["spec_source"],
                "spec_status": row["spec_status"],
                "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                "estimated_days_to_spec_out": _none_if_nan(row["estimated_days_to_spec_out"]),
                "note": "확정 원인 아님 — 어느 defect와 연결되는지 검증 안 됨, 모니터링 참고용",
            })

        m_idx = machine_index[machine_index["Machine_ID"] == machine]
        machines[machine] = {
            "health_index": float(m_idx["health_index"].iloc[0]) if len(m_idx) else None,
            "worst_defects": m_idx["worst_defects"].iloc[0] if len(m_idx) else [],
            "latest_date": g["latest_date"].max(),
            "defect_signals": defect_signals,
            "unconfirmed_anomalies": anomalies,
        }
    return machines


def main() -> None:
    opcond_baseline, daily_series_raw = load_step0_outputs()

    boundary_z = compute_boundary_z(opcond_baseline)
    spec_values = compute_spec_values(opcond_baseline)

    level_trend = compute_level_and_trend(daily_series_raw, boundary_z, spec_values)
    level_trend.to_csv(OUT_DIR / "01_level_trend_by_machine_column.csv", index=False, encoding="utf-8-sig")

    defect_index, machine_index = aggregate_health_index(level_trend)
    defect_index.to_csv(OUT_DIR / "02_health_index_by_defect.csv", index=False, encoding="utf-8-sig")
    machine_index.to_csv(OUT_DIR / "03_health_index_by_machine.csv", index=False, encoding="utf-8-sig")

    occurrence = load_defect_occurrence()
    occurrence.to_csv(OUT_DIR / "04_defect_occurrence_recent7d.csv", index=False, encoding="utf-8-sig")

    machines = build_machine_snapshot(level_trend, occurrence, defect_index, machine_index)

    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "recent_window_days": RECENT_WINDOW_DAYS,
        "anomaly_margin_threshold_pct": ANOMALY_MARGIN_THRESHOLD_PCT,
        "cause_factors": CAUSE_FACTORS,
        "machines": machines,
    }
    with open(OUT_DIR / "health_index_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: {len(machines)}개 장비 스냅샷 생성")
    ranked = sorted(machines.items(), key=lambda kv: (kv[1]["health_index"] is None, kv[1]["health_index"]))
    for machine, snap in ranked:
        n_anomalies = len(snap["unconfirmed_anomalies"])
        top3 = ", ".join(f"{d['defect']}({d['health_index']})" for d in snap["worst_defects"])
        print(f"  {machine}: Health Index {snap['health_index']} (순위: {top3}), 미확인 이상 {n_anomalies}건")


if __name__ == "__main__":
    main()
