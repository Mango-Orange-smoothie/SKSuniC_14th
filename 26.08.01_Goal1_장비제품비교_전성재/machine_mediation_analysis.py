"""Goal 1 — DP04/CLN_Flow 발견 심화검증 (전성재).

machine_comparison.py에서 "DP04만 CLN_Flow가 만성적으로 낮고, CLN_Pressure는 장비 간
차이가 없다"를 발견했다. 이게 우연한 상관이 아니라 실제로 DP04의 초과 Remain_Coat
발생률을 설명하는지 3단계로 검증한다.

  단계1  DP04 vs 개별 장비 3대 각각의 CLN_Flow 차이 (전체검정 하나로는 "DP04만" 특정 못함)
  단계2  매개효과: Machine 더미만으로 Remain_Coat를 설명하는 모델과, 거기에 CLN_Flow를
         추가한 모델을 비교. DP04 계수(다른 장비 대비 초과 위험)가 CLN_Flow를 넣었을 때
         얼마나 줄어드는지 본다 — 많이 줄어들수록 "CLN_Flow가 DP04 초과위험을 설명한다"는
         근거가 강해진다 (고전적 매개분석 논리).
  단계3  r1(불량률 높인 새 데이터)에서도 같은 패턴이 재현되는지.

pipeline/config.py, pipeline/common.py만 재사용.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.linear_model import LogisticRegression
from statsmodels.stats.multitest import multipletests

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
DEFECT_COL = "Remain_Coat"
MEDIATOR_COLS = ["CLN_Flow", "CLN_Pressure"]


def rank_biserial(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    a, b = a.dropna(), b.dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(2 * u / (len(a) * len(b)) - 1), float(p)


def step1_pairwise_dp04(z_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dp04 = z_df.loc[z_df["Machine_ID"] == "DP04", "CLN_Flow_z"]
    for machine in ["DP01", "DP02", "DP03"]:
        other = z_df.loc[z_df["Machine_ID"] == machine, "CLN_Flow_z"]
        delta, p = rank_biserial(dp04, other)
        rows.append({"comparison": f"DP04 vs {machine}", "cliffs_delta": delta, "p_value": p})
    result = pd.DataFrame(rows)
    _, p_adj, _, _ = multipletests(result["p_value"], method="fdr_bh")
    result["p_fdr"] = p_adj
    result["significant"] = (result["p_fdr"] < 0.05) & (result["cliffs_delta"].abs() >= 0.2)
    return result


def step2_mediation(z_df: pd.DataFrame) -> dict:
    machine_dummies = pd.get_dummies(z_df["Machine_ID"], prefix="Machine", drop_first=True)  # DP01 기준
    y = z_df[DEFECT_COL].astype(int)

    # 모델1: Machine만
    X1 = machine_dummies
    m1 = LogisticRegression(max_iter=2000).fit(X1, y)
    dp04_coef_alone = float(m1.coef_[0][list(X1.columns).index("Machine_DP04")])

    # 모델2: Machine + CLN_Flow + CLN_Pressure
    X2 = pd.concat([machine_dummies, z_df[["CLN_Flow_z", "CLN_Pressure_z"]]], axis=1)
    m2 = LogisticRegression(max_iter=2000).fit(X2, y)
    dp04_coef_adjusted = float(m2.coef_[0][list(X2.columns).index("Machine_DP04")])
    cln_flow_coef = float(m2.coef_[0][list(X2.columns).index("CLN_Flow_z")])
    cln_pressure_coef = float(m2.coef_[0][list(X2.columns).index("CLN_Pressure_z")])

    reduction_pct = (
        (1 - dp04_coef_adjusted / dp04_coef_alone) * 100 if dp04_coef_alone != 0 else np.nan
    )
    return {
        "dp04_log_odds_alone": dp04_coef_alone,
        "dp04_odds_ratio_alone": float(np.exp(dp04_coef_alone)),
        "dp04_log_odds_after_cln_flow_adjust": dp04_coef_adjusted,
        "dp04_odds_ratio_after_adjust": float(np.exp(dp04_coef_adjusted)),
        "dp04_excess_risk_reduction_pct": reduction_pct,
        "cln_flow_coef_in_adjusted_model": cln_flow_coef,
        "cln_pressure_coef_in_adjusted_model": cln_pressure_coef,
        "interpretation": (
            "DP04의 초과위험(log-odds)이 CLN_Flow를 모델에 추가했을 때 "
            f"{reduction_pct:.1f}% 줄었다 — 이 비율이 클수록 'CLN_Flow가 DP04 초과위험을 "
            "설명한다'는 근거가 강함 (100%면 완전 설명, 0%면 전혀 무관)."
        ),
    }


def step3_r1_replication() -> dict | None:
    r1_path = Path(config.ROOT) / "data" / "raw" / "DP_HealthIndex_Dataset_r1.csv"
    if not r1_path.exists():
        return None
    orig_input = config.INPUT_CSV
    config.INPUT_CSV = r1_path
    try:
        df_r1 = load_dataset()
    finally:
        config.INPUT_CSV = orig_input

    z_r1, _ = build_z(df_r1)
    rate_by_machine = df_r1.groupby("Machine_ID")[DEFECT_COL].mean()
    clnflow_median_by_machine = z_r1.groupby("Machine_ID")["CLN_Flow_z"].median()
    clnpressure_median_by_machine = z_r1.groupby("Machine_ID")["CLN_Pressure_z"].median()

    return {
        "remain_coat_rate_by_machine": rate_by_machine.to_dict(),
        "cln_flow_median_z_by_machine": clnflow_median_by_machine.to_dict(),
        "cln_pressure_median_z_by_machine": clnpressure_median_by_machine.to_dict(),
        "dp04_still_highest_remain_coat": bool(rate_by_machine.idxmax() == "DP04"),
        "dp04_still_lowest_cln_flow": bool(clnflow_median_by_machine.idxmin() == "DP04"),
    }


def build_z(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, MEDIATOR_COLS)
    z_df = zscore_transform(df, baseline, config.OPCOND, MEDIATOR_COLS)
    z_cols = [f"{c}_z" for c in MEDIATOR_COLS]
    z_df[z_cols] = z_df[z_cols].fillna(0.0)
    return z_df, z_cols


def main() -> None:
    df = load_dataset()
    z_df, _ = build_z(df)

    step1 = step1_pairwise_dp04(z_df)
    step1.to_csv(OUT_DIR / "04_step1_dp04_pairwise_cln_flow.csv", index=False, encoding="utf-8-sig")

    step2 = step2_mediation(z_df)
    with open(OUT_DIR / "05_step2_mediation_result.json", "w", encoding="utf-8") as f:
        json.dump(step2, f, ensure_ascii=False, indent=2)

    step3 = step3_r1_replication()
    if step3 is not None:
        with open(OUT_DIR / "06_step3_r1_replication.json", "w", encoding="utf-8") as f:
            json.dump(step3, f, ensure_ascii=False, indent=2, default=str)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "step1_dp04_pairwise": step1.to_dict("records"),
        "step2_mediation": step2,
        "step3_r1_replication": step3,
    }
    with open(OUT_DIR / "00b_deep_verification_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("=== 단계1: DP04 vs 개별 장비 CLN_Flow 차이 ===")
    print(step1.to_string(index=False))
    print("\n=== 단계2: 매개효과 ===")
    print(step2["interpretation"])
    print(f"  DP04 오즈비(보정 전): {step2['dp04_odds_ratio_alone']:.3f}")
    print(f"  DP04 오즈비(CLN_Flow 보정 후): {step2['dp04_odds_ratio_after_adjust']:.3f}")
    if step3:
        print("\n=== 단계3: r1 재현 ===")
        print(f"  DP04가 r1에서도 Remain_Coat 1위: {step3['dp04_still_highest_remain_coat']}")
        print(f"  DP04가 r1에서도 CLN_Flow 최저: {step3['dp04_still_lowest_cln_flow']}")


if __name__ == "__main__":
    main()
