"""
compare_spec_vs_trend.py

Goal4: 기존 Spec-Out 방식과 Trend Analysis 방식을 레코드 단위로 비교할 수 있는
테이블을 만든다.

- 기존 Spec-Out 방식: C유형(위험 Threshold가 정의된) 컬럼의 "순간값"이 그 시점에
  위험영역을 넘었는지만 본다. 추세나 지속성은 고려하지 않는다(원래 방식 그대로 재현).
- Trend Analysis 방식: ../trend_analysis.py가 이미 계산해 둔 early_warning=True를 그대로 쓴다.

기존 프로젝트 파일을 최대한 재사용한다:
- 원본 데이터 / NG_Code: ../HealthIndex_Dataset.csv, ../DP_HealthIndex_Dataset_r1.csv
- Trend Analysis 결과: ../analysis_outputs/trend_analysis_results.csv
- Baseline(위험선) 정보: ../26.07.29 Baseline 관련 작업/26.07.29_1625_Baseline_C_위험선_ProductRecipe_v2.csv
- 경로 상수(GROUP_KEYS, WINDOW, RAW_INPUT_FILES, BASELINE_C_CSV)는
  ../trend_analysis.py 모듈을 그대로 import해서 재사용한다(읽기 전용, 수정 없음).

이 파일은 기존 코드/CSV를 전혀 수정하지 않는다.
"""

import os
import sys

import numpy as np
import pandas as pd

GOAL4_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(GOAL4_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import trend_analysis as ta  # noqa: E402  (경로 상수 재사용 목적. import만 하며 실행하지 않음)

RESULTS_CSV = os.path.join(PROJECT_ROOT, "analysis_outputs", "trend_analysis_results.csv")

# Baseline_C 파일의 matched_defect 문자열이 원본 단계에서부터 인코딩이 깨져 있어
# (예: "Particle(파티클)") 문자열로 정확히 매칭하기 어렵다. 대신 원인이 되는
# 컬럼명(ASCII, 안전)을 실제 NG_Code 값에 직접 매핑해서 사용한다.
COLUMN_TO_NG_CODE = {
    "CLN_Pressure": "REM_COAT",
    "Surface_Roughness": "PARTICLE",
}


def load_baseline_c_map():
    """column x group_key(Product|Recipe) -> {threshold, risky_direction} 조회 테이블."""
    c = pd.read_csv(ta.BASELINE_C_CSV)
    return c[["column", "group_key", "threshold", "risky_direction"]]


def compute_spec_predictions(raw, c_map):
    """레코드별 Spec-Out 방식 예측(spec_flag)과 연속 심각도 점수(spec_score)를 계산한다.
    spec_score는 ROC/PR 곡선을 그리기 위한 참고용 연속 점수이며(위험선을 얼마나
    벗어났는지), Spec 방식 자체의 판정 기준(spec_flag)은 이분법(넘었다/안 넘었다) 그대로다.
    """
    n = len(raw)
    group_key = (raw["Product_ID"] + "|" + raw["Recipe_ID"]).to_numpy()

    spec_flag = np.zeros(n, dtype=bool)
    spec_score = np.full(n, -np.inf)

    for column in COLUMN_TO_NG_CODE:
        sub = c_map[c_map["column"] == column].set_index("group_key")
        threshold = pd.Series(group_key).map(sub["threshold"]).to_numpy(dtype=float)
        direction = pd.Series(group_key).map(sub["risky_direction"]).to_numpy(dtype=object)
        values = raw[column].to_numpy(dtype=float)

        has_th = ~np.isnan(threshold)
        low_risky = has_th & (direction == "low_is_risky")
        high_risky = has_th & (direction == "high_is_risky")

        violated = np.zeros(n, dtype=bool)
        margin = np.full(n, -np.inf)
        violated[low_risky] = values[low_risky] <= threshold[low_risky]
        violated[high_risky] = values[high_risky] >= threshold[high_risky]
        margin[low_risky] = threshold[low_risky] - values[low_risky]
        margin[high_risky] = values[high_risky] - threshold[high_risky]

        spec_flag |= violated
        spec_score = np.maximum(spec_score, margin)

    spec_score[np.isinf(spec_score)] = np.nan
    return spec_flag, spec_score


def mark_eligible(raw):
    """Trend Analysis는 그룹 내 처음 (WINDOW-1)개 관측치는 판정하지 못한다(Rolling Window 특성).
    Spec 방식은 원래 매 시점 판정 가능하지만, 공정 비교를 위해 두 방식 모두 판정
    가능한 구간(eligible)만 성능지표 계산 대상으로 삼는다.
    """
    raw = raw.sort_values(ta.GROUP_KEYS + ["DateTime"]).reset_index(drop=True)
    order = raw.groupby(ta.GROUP_KEYS).cumcount()
    eligible = (order >= ta.WINDOW - 1).to_numpy()
    return raw, eligible


def compute_trend_predictions(raw, source_name, trend_results):
    """레코드(Machine x Product x Recipe x DateTime) 단위로, 그 시점에 조금이라도
    early_warning=True인 컬럼이 있었는지(trend_flag)와 몇 개 컬럼이 동시에
    경고했는지(trend_score, 연속 점수 대용)를 계산한다.
    """
    sub = trend_results[trend_results["source_file"] == source_name]
    agg = (
        sub.groupby(ta.GROUP_KEYS + ["DateTime"])
        .size()
        .rename("trend_score")
        .reset_index()
    )
    merged = raw.merge(agg, on=ta.GROUP_KEYS + ["DateTime"], how="left")
    trend_score = merged["trend_score"].fillna(0).to_numpy(dtype=float)
    trend_flag = trend_score > 0
    return trend_flag, trend_score


def build_comparison_table(source_name, path, trend_results, c_map):
    raw = pd.read_csv(path)
    raw["DateTime"] = pd.to_datetime(raw["DateTime"])
    raw, eligible = mark_eligible(raw)

    spec_flag, spec_score = compute_spec_predictions(raw, c_map)
    trend_flag, trend_score = compute_trend_predictions(raw, source_name, trend_results)

    table = raw[ta.GROUP_KEYS + ["DateTime", "NG_Code"]].copy()
    table["source_file"] = source_name
    table["y_true"] = (raw["NG_Code"] != "OK").to_numpy()
    table["eligible"] = eligible
    table["spec_flag"] = spec_flag
    table["spec_score"] = spec_score
    table["trend_flag"] = trend_flag
    table["trend_score"] = trend_score
    return table


def build_full_comparison(trend_results):
    """두 원본 파일 전체에 대한 레코드 단위 비교 테이블을 만들어 하나로 합친다."""
    c_map = load_baseline_c_map()
    tables = [
        build_comparison_table(source_name, path, trend_results, c_map)
        for source_name, path in ta.RAW_INPUT_FILES
    ]
    return pd.concat(tables, ignore_index=True)


def compute_lead_times(table):
    """실제 NG 발생 시점 기준으로, 각 방식이 그 직전(또는 동시)에 몇 분 먼저
    탐지했는지 계산한다. eligible한 구간만 대상으로 한다(공정 비교).

    그룹(Machine x Product x Recipe) 내에서 시간순으로 훑으며, 각 방식이 마지막으로
    경보를 울린 시각을 계속 갱신하다가 실제 NG가 발생한 시점에 그 마지막 경보
    시각과의 시간차(lead time)를 기록한다. 그 시점까지 한 번도 경보가 없었다면
    해당 방식은 이 NG를 "탐지하지 못한 것"으로 처리한다(lead time = NaN).
    """
    rows = []
    elig = table[table["eligible"]].sort_values(ta.GROUP_KEYS + ["DateTime"])

    for group_vals, g in elig.groupby(ta.GROUP_KEYS, sort=False):
        g = g.reset_index(drop=True)
        dt = g["DateTime"].to_numpy()
        ng = g["y_true"].to_numpy()
        spec = g["spec_flag"].to_numpy()
        trend = g["trend_flag"].to_numpy()
        source_file = g["source_file"].to_numpy()
        ng_code = g["NG_Code"].to_numpy()

        last_spec_time = None
        last_trend_time = None
        for i in range(len(g)):
            if spec[i]:
                last_spec_time = dt[i]
            if trend[i]:
                last_trend_time = dt[i]
            if ng[i]:
                lead_spec = (
                    (dt[i] - last_spec_time) / np.timedelta64(1, "m")
                    if last_spec_time is not None else np.nan
                )
                lead_trend = (
                    (dt[i] - last_trend_time) / np.timedelta64(1, "m")
                    if last_trend_time is not None else np.nan
                )
                rows.append({
                    "source_file": source_file[i],
                    "Machine_ID": group_vals[0],
                    "Product_ID": group_vals[1],
                    "Recipe_ID": group_vals[2],
                    "DateTime": dt[i],
                    "NG_Code": ng_code[i],
                    "detected_by_spec": last_spec_time is not None,
                    "lead_minutes_spec": lead_spec,
                    "detected_by_trend": last_trend_time is not None,
                    "lead_minutes_trend": lead_trend,
                })

    return pd.DataFrame(rows)
