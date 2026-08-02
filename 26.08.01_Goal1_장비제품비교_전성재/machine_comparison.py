"""Goal 1 — 장비(Machine_ID) 간 비교 (전성재).

Goal2 REM_COAT 분석(`26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/`)에서 "DP04만
Remain_Coat 발생률이 다른 3대보다 1.6~1.8배 높다"를 발견했다. 이걸 REM_COAT 하나가
아니라 ① defect 6종 전체, ② 공정 변수(FDC/response) 전체로 확장해서, DP04가 REM_COAT만
유독 심한 건지 아니면 전반적으로 다른 장비인지 확인한다.

pipeline/README.md의 Goal1 방법론을 그대로 따른다: OPCOND(Product×Recipe)를 고정한
채(=OPCOND 층별 강건 z-score로 정규화) Machine_ID 그룹을 비모수 검정으로 비교한다.
OPCOND를 고정해야 "제품이 달라서 나는 차이"와 "장비가 달라서 나는 차이"가 안 섞인다.

산출물:
  01_defect_rate_by_machine.csv       defect 6종 x 장비 4대 발생률 + 카이제곱 검정
  02_continuous_kruskal_by_machine.csv  FDC/response 39개 x 장비 Kruskal-Wallis
  03_top_variable_machine_medians.csv   유의한 변수들의 장비별 median z (누가 튀는지)
  00_summary.json
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
FDR_ALPHA = config.TREND_ALPHA
CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]
DEFECTS = config.DEFECTS_BINARY  # Chipping, Remain_Coat, Particle, Micro_Crack, Laser_Paim, Edge_Burn


def defect_rate_by_machine(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for defect in DEFECTS:
        table = pd.crosstab(df["Machine_ID"], df[defect])
        chi2, p, _, _ = scipy_stats.chi2_contingency(table)
        rates = df.groupby("Machine_ID")[defect].mean()
        overall_rate = df[defect].mean()
        for machine, rate in rates.items():
            rows.append({
                "defect": defect,
                "Machine_ID": machine,
                "rate": rate,
                "overall_rate": overall_rate,
                "rate_ratio_vs_overall": rate / overall_rate if overall_rate > 0 else np.nan,
                "chi2_p_across_machines": p,
            })
    result = pd.DataFrame(rows)
    per_defect = result.drop_duplicates("defect")
    _, p_adj, _, _ = multipletests(per_defect["chi2_p_across_machines"], alpha=FDR_ALPHA, method="fdr_bh")
    defect_to_p = dict(zip(per_defect["defect"], p_adj))
    result["chi2_p_fdr"] = result["defect"].map(defect_to_p)
    result["significant_fdr"] = result["chi2_p_fdr"] < FDR_ALPHA
    return result.sort_values(["chi2_p_fdr", "defect", "Machine_ID"])


def continuous_kruskal_by_machine(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, CANDIDATE_COLS)
    z_df = zscore_transform(df, baseline, config.OPCOND, CANDIDATE_COLS)

    rows = []
    median_rows = []
    for col in CANDIDATE_COLS:
        z_col = f"{col}_z"
        groups = [g[z_col].dropna().values for _, g in z_df.groupby("Machine_ID")]
        if any(len(g) < 5 for g in groups):
            continue
        h_stat, p_value = scipy_stats.kruskal(*groups)
        n_total = sum(len(g) for g in groups)
        k = len(groups)
        epsilon_sq = (h_stat - k + 1) / (n_total - k) if n_total > k else np.nan  # 비모수 효과크기
        rows.append({
            "column": col,
            "kruskal_h": h_stat,
            "p_value": p_value,
            "epsilon_squared": epsilon_sq,
            "n_total": n_total,
        })
        for machine, g in z_df.groupby("Machine_ID"):
            median_rows.append({
                "column": col,
                "Machine_ID": machine,
                "median_z": g[z_col].median(),
                "n": g[z_col].notna().sum(),
            })

    result = pd.DataFrame(rows)
    rejected, p_adj, _, _ = multipletests(result["p_value"], alpha=FDR_ALPHA, method="fdr_bh")
    result["p_fdr"] = p_adj
    result["significant_fdr"] = rejected & (result["epsilon_squared"] >= 0.01)  # 소표본 아니므로 완화된 실질효과 기준
    result = result.sort_values("epsilon_squared", ascending=False)

    medians = pd.DataFrame(median_rows)
    return result, medians


def main() -> None:
    df = load_dataset()

    rate_result = defect_rate_by_machine(df)
    rate_result.to_csv(OUT_DIR / "01_defect_rate_by_machine.csv", index=False, encoding="utf-8-sig")

    kruskal_result, medians = continuous_kruskal_by_machine(df)
    kruskal_result.to_csv(OUT_DIR / "02_continuous_kruskal_by_machine.csv", index=False, encoding="utf-8-sig")

    sig_cols = kruskal_result.loc[kruskal_result["significant_fdr"], "column"].tolist()
    top_medians = medians[medians["column"].isin(sig_cols)].pivot(
        index="column", columns="Machine_ID", values="median_z"
    )
    top_medians.to_csv(OUT_DIR / "03_top_variable_machine_medians.csv", encoding="utf-8-sig")

    sig_defects = rate_result.loc[rate_result["significant_fdr"], "defect"].unique().tolist()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": len(df),
        "defects_with_significant_machine_difference": sig_defects,
        "n_continuous_vars_scanned": len(kruskal_result),
        "n_continuous_vars_significant": int(kruskal_result["significant_fdr"].sum()),
        "top10_continuous_by_effect": kruskal_result.head(10)[["column", "epsilon_squared", "p_fdr"]].to_dict("records"),
    }
    with open(OUT_DIR / "00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("장비 간 발생률 차이가 유의한 defect:", sig_defects)
    print(f"\n장비 간 차이가 유의한 연속형 변수: {int(kruskal_result['significant_fdr'].sum())}개 / {len(kruskal_result)}개")
    print(kruskal_result.loc[kruskal_result["significant_fdr"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
