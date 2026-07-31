"""Goal2 REM_COAT — 4차 검증: 전체 후보 변수 선행신호 전수조사 (전성재).

9번 검증(verify_v3)에서 CLN_Pressure가 "동시점엔 강하지만 선행신호는 없는" 유형임을
발견했다. 이런 유형(=원인이라면 순간적/즉시성 현상, 원인이 아니라면 결과 공변)이
CLN_Pressure 외에 또 있는지, 후보 39개(FDC+response+도메인피처) 전체로 확대해서
daeho 방법론(동일 규약: lag window 5/20/50, retention floor 0.15)을 적용한다.

verify_v3와 통계 코드는 동일, 대상 컬럼만 3개 -> 39개로 확대.
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

EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = config.TREND_ALPHA
LAG_WINDOW = 50  # verify_v3에서 CLN_Pressure가 가장 안정적으로 낮게 나온 창
SIGNAL_RETENTION_FLOOR = 0.15

ALL_CANDIDATES = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]


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


def scan(df_z: pd.DataFrame) -> pd.DataFrame:
    ordered = df_z.sort_values(["Machine_ID", "DateTime"]).copy()
    is_defect = ordered[DEFECT_COL] == 1
    rows = []

    for col in ALL_CANDIDATES:
        z_col = f"{col}_z"
        delta_now, p_now, n_g, n_r = cliffs_delta(
            ordered.loc[is_defect, z_col], ordered.loc[~is_defect, z_col]
        )
        lag_col = ordered.groupby("Machine_ID")[z_col].transform(
            lambda s: s.shift(1).rolling(LAG_WINDOW, min_periods=LAG_WINDOW // 2).mean()
        )
        delta_lag, p_lag, n_g_lag, n_r_lag = cliffs_delta(lag_col[is_defect], lag_col[~is_defect])
        retention = abs(delta_lag) / abs(delta_now) if pd.notna(delta_now) and abs(delta_now) > 1e-9 else np.nan
        rows.append({
            "column": col,
            "cliffs_delta_concurrent": delta_now,
            "p_concurrent": p_now,
            "cliffs_delta_lagged_50strip": delta_lag,
            "p_lagged": p_lag,
            "signal_retention_ratio": retention,
        })

    result = pd.DataFrame(rows)
    pvals = result["p_concurrent"].fillna(1.0)
    rejected, p_adj, _, _ = multipletests(pvals, alpha=FDR_ALPHA, method="fdr_bh")
    result["p_concurrent_fdr"] = p_adj
    result["concurrent_meaningful"] = rejected & (result["cliffs_delta_concurrent"].abs() >= EFFECT_SIZE_MIN)

    def classify(row):
        if not row["concurrent_meaningful"]:
            return "동시점부터 무신호 (후보 아님)"
        if pd.isna(row["signal_retention_ratio"]):
            return "판정불가"
        if row["signal_retention_ratio"] >= SIGNAL_RETENTION_FLOOR:
            return "추세형 — 선행신호 있음 (점진적 원인 후보)"
        return "즉시형 — 선행신호 없음 (순간적 원인 또는 결과공변, 개별 검토 필요)"

    result["pattern_type"] = result.apply(classify, axis=1)
    return result.sort_values("cliffs_delta_concurrent", key=lambda s: s.abs(), ascending=False)


def main() -> None:
    df = load_dataset()
    df_z = stratified_z(df, ALL_CANDIDATES)
    result = scan(df_z)
    result.to_csv(OUT_DIR / "verify_v4_01_full_temporal_scan.csv", index=False, encoding="utf-8-sig")

    meaningful = result.loc[result["concurrent_meaningful"]]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lag_window_strips": LAG_WINDOW,
        "signal_retention_floor": SIGNAL_RETENTION_FLOOR,
        "n_candidates_scanned": len(result),
        "n_concurrent_meaningful": len(meaningful),
        "trend_type_columns": meaningful.loc[
            meaningful["signal_retention_ratio"] >= SIGNAL_RETENTION_FLOOR, "column"
        ].tolist(),
        "instant_type_columns": meaningful.loc[
            meaningful["signal_retention_ratio"] < SIGNAL_RETENTION_FLOOR, "column"
        ].tolist(),
    }
    with open(OUT_DIR / "verify_v4_00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"동시점에서 의미있는 신호가 있는 컬럼: {len(meaningful)}개")
    print(f"  추세형(선행신호 있음): {summary['trend_type_columns']}")
    print(f"  즉시형(선행신호 없음): {summary['instant_type_columns']}")


if __name__ == "__main__":
    main()
