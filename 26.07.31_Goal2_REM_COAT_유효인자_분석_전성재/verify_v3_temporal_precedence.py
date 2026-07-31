"""Goal2 REM_COAT — 3차 검증: 선행신호(시간 선행성) 검사 (전성재).

daeho 브랜치의 `26.07.31_2058_Goal2_PARTICLE_후속검증/particle_followup_validation.py`
검증1(temporal_precedence)과 정확히 동일한 통계 규약(Mann-Whitney U 기반 Cliff's delta,
lag window 5/20/50 strips, signal_retention_floor=0.15, BH-FDR)을 그대로 적용한다 —
팀 전체가 숫자를 직접 비교할 수 있게 하기 위함. 구현은 새로 작성했지만 방법론은 재사용.

논리: 어떤 인자가 REM_COAT의 원인이라면, 그 인자가 나빠진 상태가 불량 발생보다 시간적으로
앞서야 한다(같은 장비의 직전 스트립들에서 이미 이상 신호가 있어야 함). 반대로 불량의
'결과'(동반증상)라면 같은 스트립에서 동시에 측정될 때만 신호가 보이고 직전 스트립에는
신호가 없어야 한다.

대상 컬럼:
  - CLN_Pressure: 지금까지 3가지 방법(Jun/방법A/방법B)에서 확정된 핵심 유효인자.
    선행신호까지 있으면 "원인"이라는 주장이 훨씬 강해진다.
  - CLN_Time: 방법B(Machine 통제)에서 방향이 도메인 가설과 반대로 나와 다중공선성에
    의한 부호 역전으로 의심됨 — 선행신호가 없다면 인과가 아니라는 방증이 됨.
  - Coating_Thickness: 측정 시점(가공 전/후) 불확실로 후보 제외됨 — 선행신호 여부가
    "다른 스트립들과 무관하게 그 스트립에서만 동시 측정된 값인지"를 보는 데 참고가 됨
    (단, 같은 스트립 내 측정 시점 문제 자체를 직접 증명하진 않음, 별개 확인 필요).

주의(daeho 원문 그대로): 이것은 인과 증명이 아니라 '결과 공변 가설을 반증할 수 있는가'
하는 검사다. 두 인자가 공통 원인을 공유해 함께 서서히 움직인다면 선행 신호도 함께
나타날 수 있다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.stats.multitest import multipletests

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
DEFECT_COL = "Remain_Coat"

# daeho와 동일한 규약 — 바꾸면 팀 내 숫자 비교가 불가능해진다.
EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = config.TREND_ALPHA
LAG_WINDOWS = [5, 20, 50]
SIGNAL_RETENTION_FLOOR = 0.15

TEMPORAL_TARGETS = ["CLN_Pressure", "CLN_Time", "Coating_Thickness"]


def cliffs_delta(group_vals: pd.Series, rest_vals: pd.Series) -> tuple[float, float, int, int]:
    g = pd.Series(group_vals).dropna()
    r = pd.Series(rest_vals).dropna()
    if len(g) < 3 or len(r) < 3:
        return np.nan, np.nan, len(g), len(r)
    u_stat, p_value = scipy_stats.mannwhitneyu(g, r, alternative="two-sided")
    delta = (2 * u_stat) / (len(g) * len(r)) - 1
    return float(delta), float(p_value), len(g), len(r)


def stratified_z(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    baseline = compute_stratum_baseline_stats(df.loc[df["is_normal"]], config.OPCOND, columns)
    return zscore_transform(df, baseline, config.OPCOND, columns)


def temporal_precedence(df_z: pd.DataFrame) -> pd.DataFrame:
    ordered = df_z.sort_values(["Machine_ID", "DateTime"]).copy()
    is_defect = ordered[DEFECT_COL] == 1
    rows = []

    for col in TEMPORAL_TARGETS:
        z_col = f"{col}_z"
        delta_now, p_now, n_g, n_r = cliffs_delta(
            ordered.loc[is_defect, z_col], ordered.loc[~is_defect, z_col]
        )
        for window in LAG_WINDOWS:
            lag_col = ordered.groupby("Machine_ID")[z_col].transform(
                lambda s, w=window: s.shift(1).rolling(w, min_periods=max(3, w // 2)).mean()
            )
            delta_lag, p_lag, n_g_lag, n_r_lag = cliffs_delta(
                lag_col[is_defect], lag_col[~is_defect]
            )
            retention = (
                abs(delta_lag) / abs(delta_now) if pd.notna(delta_now) and abs(delta_now) > 1e-9 else np.nan
            )
            rows.append({
                "column": col,
                "lag_window_strips": window,
                "n_defect": n_g,
                "n_normal": n_r,
                "cliffs_delta_concurrent": delta_now,
                "p_concurrent": p_now,
                "cliffs_delta_lagged": delta_lag,
                "p_lagged": p_lag,
                "n_defect_lagged": n_g_lag,
                "signal_retention_ratio": retention,
            })

    result = pd.DataFrame(rows)
    pvals = result["p_lagged"].fillna(1.0)
    rejected, p_adj, _, _ = multipletests(pvals, alpha=FDR_ALPHA, method="fdr_bh")
    result["p_lagged_fdr"] = p_adj
    result["lagged_significant"] = rejected & (result["cliffs_delta_lagged"].abs() >= EFFECT_SIZE_MIN)

    def interpret(row):
        if pd.isna(row["cliffs_delta_lagged"]):
            return "판정불가"
        if row["lagged_significant"]:
            return "선행신호 유지 — 상류 원인 가능성 잔존"
        if pd.notna(row["signal_retention_ratio"]) and row["signal_retention_ratio"] < SIGNAL_RETENTION_FLOOR:
            return "선행신호 소멸 — 결과 공변(동반증상) 해석 지지"
        return "선행신호 약함 — 판단 보류"

    result["interpretation"] = result.apply(interpret, axis=1)
    return result


def main() -> None:
    df = load_dataset()
    df_z = stratified_z(df, TEMPORAL_TARGETS)

    result = temporal_precedence(df_z)
    result.to_csv(OUT_DIR / "verify_v3_01_temporal_precedence.csv", index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "daeho 브랜치 particle_followup_validation.py 검증1과 동일 규약 (lag window 5/20/50, retention floor 0.15)",
        "targets": TEMPORAL_TARGETS,
        "by_column_50strip_window": {
            col: result.loc[
                (result["column"] == col) & (result["lag_window_strips"] == 50), "interpretation"
            ].iloc[0]
            for col in TEMPORAL_TARGETS
        },
    }
    with open(OUT_DIR / "verify_v3_00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(result.to_string(index=False))
    print("\n50-strip 창 기준 최종 해석:")
    for col, interp in summary["by_column_50strip_window"].items():
        print(f"  {col}: {interp}")


if __name__ == "__main__":
    main()
