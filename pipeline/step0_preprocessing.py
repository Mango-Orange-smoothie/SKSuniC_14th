"""Step 0: 데이터 전처리 & 피처 기반.

Goal 1~6(장비/제품 비교, 유효인자 발굴, 상호작용, 이상탐지, Health Index, SOP 초안)
모듈이 공통으로 참조할 컬럼 분류·변동성/추세 분류·baseline·정규화 기반을 만든다.
원본 CSV는 절대 수정하지 않는다. 실행: `python -m pipeline.step0_preprocessing`

산출물 (analysis_outputs/preprocessing/):
  00_column_classification.csv        컬럼별 분류/변동성/추세 요약 (68개 원본 컬럼 전체)
  00_machine_column_trend.csv         (Machine, 연속형 컬럼)별 추세검정 상세
  00_missing_sensor_fault_flags.csv   결측/불가능한 0값/flatline(고착) 플래그
  00_stratum_baseline_stats_by_opcond.csv        Product×Recipe grain OK-baseline
  00_stratum_baseline_stats_by_machine_opcond.csv Machine×Product×Recipe grain OK-baseline
  00_preprocessing_summary.json       요약 통계 + assert 결과 + 다운스트림 기본 컬럼 목록
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import statsmodels.api as sm

from pipeline import config
from pipeline.common import (
    compute_stratum_baseline_stats,
    mann_kendall,
    save_table,
    zscore_transform,
)

CONTINUOUS_TREND_COLS = config.FDC_COLS + config.RESPONSES + ["Yield"]
CONTINUOUS_BASELINE_COLS = CONTINUOUS_TREND_COLS + config.DOMAIN_FEATURES
# flatline(고착) 탐지는 센서성 연속값에만 의미가 있다. Yield는 정상 공정에서
# 정의상 100이 매우 자주 반복되므로(공정이 잘 돌아간다는 뜻) 여기서 제외한다.
SENSOR_FLATLINE_CHECK_COLS = config.FDC_COLS + config.RESPONSES


# ---------------------------------------------------------------------------
# 1단계: 로드 & 키/정상군 검증
# ---------------------------------------------------------------------------

def load_and_validate() -> pd.DataFrame:
    df = pd.read_csv(config.INPUT_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["is_normal"] = config.NORMAL(df)

    n_rows = len(df)
    n_unique_keys = df[config.KEY].drop_duplicates().shape[0]
    n_dup_keys = int(df.duplicated(config.KEY).sum())
    n_normal = int(df["is_normal"].sum())

    assert n_rows == config.EXPECTED_ROW_COUNT, (
        f"행 수가 예상과 다릅니다: {n_rows} != {config.EXPECTED_ROW_COUNT} "
        "(원본 데이터셋이 바뀌었을 수 있음 — 계속 진행 전 확인 필요)"
    )
    assert n_dup_keys == 0, f"Lot_ID+Strip_ID 키 중복 {n_dup_keys}건 발견 — 분석키 규약 위반"
    assert n_normal == config.EXPECTED_NORMAL_COUNT, (
        f"정상군 수가 예상과 다릅니다: {n_normal} != {config.EXPECTED_NORMAL_COUNT}"
    )

    df = config.add_domain_features(df)
    return df


# ---------------------------------------------------------------------------
# 2단계: 변동성 지표 (스케일 불변, 타입별로 다르게)
# ---------------------------------------------------------------------------

def _dispersion_ratio(values: pd.Series) -> float:
    """스케일-불변 변동성 비율.

    평균이 0에서 충분히 떨어져 있으면 CV(std/mean)를, Cutting_Offset처럼
    부호 있는/0 중심 컬럼은 CV가 발산하므로 관측 range 대비 std로 대체한다.
    """
    if len(values) < 5:
        return np.nan
    mean = values.mean()
    std = values.std()
    if std == 0:
        return 0.0
    if abs(mean) > 0.1 * std:
        return abs(std / mean)
    rng = values.max() - values.min()
    return std / rng if rng > 1e-9 else 0.0


def _classify_ratio(ratio: float) -> str:
    if pd.isna(ratio):
        return "unknown"
    if ratio < config.CV_STABLE_THRESHOLD:
        return "stable"
    if ratio < config.CV_VARIABLE_THRESHOLD:
        return "moderate"
    return "variable"


def variability_continuous(df_normal: pd.DataFrame, col: str) -> tuple[float, str, str]:
    ratios = []
    for _, g in df_normal.groupby(config.OPCOND):
        r = _dispersion_ratio(g[col].dropna())
        if pd.notna(r):
            ratios.append(r)
    if not ratios:
        return np.nan, "unknown", "cv_or_range_normalized"
    return float(np.median(ratios)), _classify_ratio(float(np.median(ratios))), "cv_or_range_normalized"


def variability_binary(df_all: pd.DataFrame, col: str) -> tuple[float, str, str]:
    """이진 defect: variance=p(1-p)는 무의미하므로 층별 발생률의 CV를 사용.

    NORMAL(OK) 정의상 defect 컬럼은 정상군에서 항상 0이므로 반드시 전체 데이터(df_all)로
    계산해야 한다 — 정상군(df_normal)으로 계산하면 발생률이 모든 층에서 0이 되어 무의미해진다.
    주의: 희귀 이벤트는 층별 표본이 작을수록 발생률 CV가 표본 노이즈만으로도
    커지는 경향이 있다 — 'variable' 판정을 과도하게 신뢰하지 말 것 (dispersion_method 참고).
    """
    rates = df_all.groupby(config.OPCOND)[col].mean().dropna()
    if len(rates) < 2 or rates.mean() == 0:
        return np.nan, "unknown", "rate_cv"
    cv = rates.std() / rates.mean()
    return float(cv), _classify_ratio(float(cv)), "rate_cv"


def variability_count(df_all: pd.DataFrame, col: str) -> tuple[float, str, str]:
    """count(die 단위) 컬럼: index of dispersion(var/mean, Poisson 과산포 진단).

    defect count 컬럼은 정상군에서 항상 0이므로 전체 데이터(df_all)로 계산한다 (위와 동일 이유).
    """
    ratios = []
    for _, g in df_all.groupby(config.OPCOND):
        s = g[col].dropna()
        if len(s) < 5 or s.mean() == 0:
            continue
        ratios.append(s.var() / s.mean())
    ratios = [r for r in ratios if pd.notna(r)]
    if not ratios:
        return np.nan, "unknown", "index_of_dispersion"
    median_ratio = float(np.median(ratios))
    cls = "stable" if median_ratio < 0.5 else ("moderate" if median_ratio < 2.0 else "variable")
    return median_ratio, cls, "index_of_dispersion"


# ---------------------------------------------------------------------------
# 3단계: 노이즈 vs 실제 열화추세 (장비별, OPCOND 잔차 기반)
# ---------------------------------------------------------------------------

def compute_machine_column_trend(df: pd.DataFrame, opcond_baseline: pd.DataFrame) -> pd.DataFrame:
    """OPCOND 층 median을 뺀 z-잔차의 장비별 일간 평균에 Mann-Kendall(=kendalltau)+OLS 기울기.

    Product/Recipe 조합이 날마다 달라도, 먼저 조건별로 정규화했기 때문에
    "그 장비가 자기 기대 baseline 대비 드리프트하는지"를 올바르게 반영한다.
    """
    z_df = zscore_transform(df, opcond_baseline, config.OPCOND, CONTINUOUS_TREND_COLS)
    z_df["date"] = z_df["DateTime"].dt.date

    rows = []
    for machine, g in z_df.groupby("Machine_ID"):
        daily = g.groupby("date")
        for col in CONTINUOUS_TREND_COLS:
            zcol = f"{col}_z"
            series = daily[zcol].mean().sort_index()
            day_index = np.arange(len(series))
            tau, p_value = mann_kendall(pd.Series(day_index), series)

            ols_slope, ols_pvalue = np.nan, np.nan
            valid = series.dropna()
            if len(valid) >= 3:
                x = sm.add_constant(np.arange(len(valid)))
                model = sm.OLS(valid.values, x).fit()
                ols_slope = float(model.params[1])
                ols_pvalue = float(model.pvalues[1])

            if pd.notna(p_value) and p_value < config.TREND_ALPHA:
                trend_class = "candidate_upward_drift" if tau > 0 else "candidate_downward_drift"
            else:
                trend_class = "no_trend"

            rows.append(
                {
                    "Machine_ID": machine,
                    "column": col,
                    "n_days": len(valid),
                    "kendall_tau": tau,
                    "kendall_p_value": p_value,
                    "ols_slope_per_day": ols_slope,
                    "ols_p_value": ols_pvalue,
                    "trend_class": trend_class,
                }
            )
    return pd.DataFrame(rows)


def summarize_column_trend(machine_trend: pd.DataFrame) -> dict[str, str]:
    """장비별 추세를 컬럼 단위로 요약: 하나라도 유의한 상승/하강이 있으면 candidate_*."""
    summary = {}
    for col, g in machine_trend.groupby("column"):
        classes = set(g["trend_class"])
        has_up = "candidate_upward_drift" in classes
        has_down = "candidate_downward_drift" in classes
        if has_up and has_down:
            summary[col] = "mixed"
        elif has_up:
            summary[col] = "candidate_upward_drift"
        elif has_down:
            summary[col] = "candidate_downward_drift"
        else:
            summary[col] = "no_trend"
    return summary


# ---------------------------------------------------------------------------
# 4단계: 결측 / 물리적으로 불가능한 0값 / flatline(고착) 탐지
# ---------------------------------------------------------------------------

def detect_missing_sensor_faults(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    df_sorted = df.sort_values(["Machine_ID", "DateTime"])

    flatline_counts: dict[str, int] = {}
    for col in SENSOR_FLATLINE_CHECK_COLS:
        flagged = 0
        for _, g in df_sorted.groupby("Machine_ID"):
            s = g[col]
            same_as_prev = s.eq(s.shift())
            run_id = (~same_as_prev).cumsum()
            run_len = s.groupby(run_id).transform("size")
            flagged += int((run_len >= config.FLATLINE_RUN_LENGTH).sum())
        flatline_counts[col] = flagged

    rows = []
    for col in df.columns:
        if col in ("DateTime", "is_normal"):
            continue
        missing = int(df[col].isna().sum())
        zero_count = int((df[col] == 0).sum()) if col in config.ZERO_IMPLAUSIBLE_COLS else 0
        flat = flatline_counts.get(col, 0)
        rows.append(
            {
                "column": col,
                "missing_count": missing,
                "missing_rate": missing / total,
                "zero_implausible_count": zero_count,
                "zero_implausible_rate": zero_count / total,
                "flatline_flagged_count": flat,
                "flatline_flagged_rate": flat / total,
                "suggested_handling": "flag_only",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5단계: 컬럼 분류 taxonomy
# ---------------------------------------------------------------------------

def _subsystem_of(col: str) -> str:
    for name, cols in config.SUBSYSTEMS.items():
        if col in cols:
            return name
    return "id_production"


def _data_type_of(col: str) -> str:
    if col == "DateTime":
        return "datetime"
    if col in ("Lot_ID", "Strip_ID"):
        return "id"
    if col in ("Machine_ID", "Product_ID", "Recipe_ID", "Shift", "Operator_ID", "NG_Code"):
        return "categorical"
    if col in config.DEFECTS_BINARY:
        return "binary"
    if col in config.DEFECTS_COUNT or col in ("Door_Open_Count", "Fan_RPM", "Maintenance_Count"):
        return "count"
    return "continuous"


def _analysis_role_of(col: str) -> str:
    if col == "DateTime":
        return "datetime"
    if col in config.EXCLUDED_IDENTIFIERS:
        return "identifier_excluded"
    if col in config.MENTOR_EXCLUDED_VARS:
        return "mentor_excluded"
    if col in ("Machine_ID", "Product_ID", "Recipe_ID"):
        return "context_stratum"
    if col in ("Yield", "NG_Code"):
        return "target_outcome"
    if col in config.DEFECTS_BINARY or col in config.DEFECTS_COUNT:
        return "target_defect"
    if col in config.UNDOCUMENTED_EXCLUDED:
        return "undocumented_excluded"
    if col == "Maintenance_Count":
        return "undocumented_retained"
    return "predictor"  # FDC_* / response


def build_column_classification(
    df: pd.DataFrame,
    df_normal: pd.DataFrame,
    trend_summary: dict[str, str],
    fault_flags: pd.DataFrame,
) -> pd.DataFrame:
    fault_lookup = fault_flags.set_index("column")
    rows = []
    for col in df.columns:
        if col in ("is_normal",) or col in config.DOMAIN_FEATURES:
            continue  # 원본 68개 컬럼만; 파생 도메인 피처는 별도 문서화
        data_type = _data_type_of(col)
        role = _analysis_role_of(col)
        subsystem = _subsystem_of(col)

        ratio, var_class, disp_method = np.nan, "not_applicable", "not_applicable"
        if data_type == "continuous" and col in CONTINUOUS_TREND_COLS:
            # 연속형 FDC/response: '정상 공정의 안정성'을 보는 것이 목적이므로 OK행 기준(df_normal).
            ratio, var_class, disp_method = variability_continuous(df_normal, col)
        elif data_type == "binary":
            # defect 발생률은 OK행에서 항상 0이므로 전체 데이터(df) 기준으로 계산.
            ratio, var_class, disp_method = variability_binary(df, col)
        elif data_type == "count":
            ratio, var_class, disp_method = variability_count(df, col)

        trend_class = trend_summary.get(col, "not_applicable")

        decision_note = config.UNDOCUMENTED_COL_NOTES.get(col, "")
        if not decision_note:
            if role == "identifier_excluded":
                decision_note = "멘토 피드백: 로트 추적/작업자 식별용, 분석 피처로 부적합 — 원본엔 보존, 피처셋에서 제외."
            elif role == "mentor_excluded":
                decision_note = config.MENTOR_EXCLUDED_VARS_NOTE
            elif role == "context_stratum":
                decision_note = "장비/제품/레시피 층 정의 및 범주형 통제변수로 사용."
            elif role == "target_outcome":
                decision_note = "공정 결과 라벨 — 피처가 아니라 타깃/검증값(Goal2 타깃, Goal5 검증)."
            elif role == "target_defect":
                decision_note = "defect 타깃 — Goal2/4의 예측 대상."

        mentor_note = config.MENTOR_DOMAIN_NOTES.get(col)
        if mentor_note:
            decision_note = f"{decision_note} {mentor_note}".strip() if decision_note else mentor_note

        include_default = role in (
            "predictor", "context_stratum", "target_defect", "target_outcome", "undocumented_retained",
        )

        f = fault_lookup.loc[col] if col in fault_lookup.index else None
        rows.append(
            {
                "column": col,
                "subsystem": subsystem,
                "data_type": data_type,
                "analysis_role": role,
                "variability_class": var_class,
                "variability_ratio": ratio,
                "dispersion_method": disp_method,
                "degradation_trend_class": trend_class,
                "missing_rate": float(f["missing_rate"]) if f is not None else np.nan,
                "zero_fault_rate": float(f["zero_implausible_rate"]) if f is not None else np.nan,
                "flatline_fault_rate": float(f["flatline_flagged_rate"]) if f is not None else np.nan,
                "is_operation_condition_key": col in config.OPCOND,
                "is_excluded_identifier": col in config.EXCLUDED_IDENTIFIERS,
                "is_mentor_excluded": col in config.MENTOR_EXCLUDED_VARS,
                "include_in_downstream_default": include_default,
                "decision_note": decision_note,
            }
        )
    result = pd.DataFrame(rows)
    assert len(result) == 68, f"컬럼 분류표가 68개 원본 컬럼을 모두 포함해야 함 (실제 {len(result)}개)"
    return result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_and_validate()
    df_normal = df.loc[df["is_normal"]]

    opcond_baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, CONTINUOUS_BASELINE_COLS)
    machine_opcond_baseline = compute_stratum_baseline_stats(df_normal, config.GROUP, CONTINUOUS_BASELINE_COLS)
    save_table(opcond_baseline, "00_stratum_baseline_stats_by_opcond.csv", subdir="preprocessing")
    save_table(machine_opcond_baseline, "00_stratum_baseline_stats_by_machine_opcond.csv", subdir="preprocessing")

    machine_trend = compute_machine_column_trend(df, opcond_baseline)
    save_table(machine_trend, "00_machine_column_trend.csv", subdir="preprocessing")
    trend_summary = summarize_column_trend(machine_trend)

    fault_flags = detect_missing_sensor_faults(df)
    save_table(fault_flags, "00_missing_sensor_fault_flags.csv", subdir="preprocessing")

    classification = build_column_classification(df, df_normal, trend_summary, fault_flags)
    save_table(classification, "00_column_classification.csv", subdir="preprocessing")

    # 정합성 체크: Fail_Die와 (100-Yield)는 정의상 강하게 연관되어야 함 — 안 그러면 파이프라인 버그.
    consistency_check = df["Fail_Die"].corr(100 - df["Yield"], method="spearman")
    assert consistency_check > 0.5, (
        f"Fail_Die와 (100-Yield)의 Spearman 상관이 비정상적으로 낮음 ({consistency_check:.3f}) — "
        "데이터 로드/조인 버그 의심"
    )

    include_cols = classification.loc[classification["include_in_downstream_default"], "column"].tolist()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(df),
        "unique_key_count": int(df[config.KEY].drop_duplicates().shape[0]),
        "normal_count": int(df["is_normal"].sum()),
        "fail_die_vs_yield_spearman": float(consistency_check),
        "include_in_downstream_default_columns": include_cols,
        "subsystem_column_counts": {
            name: len(cols) for name, cols in config.SUBSYSTEMS.items()
        },
        "notes": [
            "die 단위 x,y 좌표 없음 — 공간(DBSCAN) 클러스터링은 이번 범위 제외.",
            "결측/불가능0/flatline은 flag_only 정책 — 자동 보간 없음.",
            "OPCOND=[Product_ID,Recipe_ID], GROUP=[Machine_ID,Product_ID,Recipe_ID] — 용도 다름, README 참고.",
        ],
    }
    with open(config.PREPROCESSING_DIR / "00_preprocessing_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: Step0 산출물은 {config.PREPROCESSING_DIR}에 저장되었습니다.")
    print(f"  - 컬럼 분류: {len(classification)}개 컬럼")
    print(f"  - 다운스트림 기본 포함 컬럼: {len(include_cols)}개")
    print(f"  - Fail_Die vs (100-Yield) Spearman: {consistency_check:.3f}")


if __name__ == "__main__":
    main()
