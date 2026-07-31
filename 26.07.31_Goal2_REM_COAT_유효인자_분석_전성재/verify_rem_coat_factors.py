"""Goal2 REM_COAT 유효인자 독립 검증 (전성재).

Jun 브랜치(Mango-Orange-smoothie)의 `04_rem_coat_influence_factors_final.csv` 판정
(confirmed: CLN_Pressure)이 데이터로 재현되는지, 별도로 작성한 코드로 직접 확인한다.
pipeline/config.py, pipeline/common.py(공용 KEY/GROUP/OPCOND/NORMAL 정의)는 그대로
재사용하고, 통계 검정 코드는 새로 작성했다 — 원본 REM_COAT 분석 스크립트는 참고하지 않았다.

방법:
  1. Mann-Whitney U 검정 (Remain_Coat=1 vs 0 두 집단 분포 비교, 비모수)
  2. Benjamini-Hochberg FDR 보정 (후보 컬럼 다수라 다중비교 보정 필수)
  3. Rank-biserial correlation(=Cliff's delta와 수학적으로 동일한 효과크기)로 실질적 크기 확인
     — n=100,000이면 사소한 차이도 p<0.05가 나오므로 유의성만으로 판단하면 안 됨
  4. RandomForest permutation importance로 교차검증 (단일 변수 검정과 다른 방법론)
  5. 두 방법 모두에서 상위로 잡히는 컬럼만 "유효인자 후보"로 최종 판정

실행: python "26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/verify_rem_coat_factors.py"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from statsmodels.stats.multitest import multipletests

from pipeline import config
from pipeline.common import load_dataset

OUT_DIR = Path(__file__).resolve().parent
DEFECT_COL = "Remain_Coat"
EFFECT_SIZE_MIN = 0.2  # Cliff's delta 기준 (small=0.147, medium=0.33 관례상 0.2를 실질적 하한으로 사용)
FDR_ALPHA = 0.05

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]


def rank_biserial(defect_vals: pd.Series, ok_vals: pd.Series, u_stat: float) -> float:
    """Mann-Whitney U -> rank-biserial correlation (Cliff's delta와 동일한 값)."""
    n1, n2 = len(defect_vals), len(ok_vals)
    return float(2 * u_stat / (n1 * n2) - 1)


def univariate_scan(df: pd.DataFrame) -> pd.DataFrame:
    is_defect = df[DEFECT_COL] == 1
    rows = []
    for col in CANDIDATE_COLS:
        vals = df[col].dropna()
        defect_vals = df.loc[is_defect, col].dropna()
        ok_vals = df.loc[~is_defect, col].dropna()
        if len(defect_vals) < 5 or len(ok_vals) < 5:
            rows.append({"column": col, "p_value": np.nan, "effect_rank_biserial": np.nan, "n_defect": len(defect_vals)})
            continue
        u_stat, p_value = scipy_stats.mannwhitneyu(defect_vals, ok_vals, alternative="two-sided")
        effect = rank_biserial(defect_vals, ok_vals, u_stat)
        rows.append({
            "column": col,
            "p_value": float(p_value),
            "effect_rank_biserial": effect,
            "n_defect": len(defect_vals),
            "median_defect": float(defect_vals.median()),
            "median_ok": float(ok_vals.median()),
        })
    result = pd.DataFrame(rows)
    valid = result["p_value"].notna()
    result.loc[valid, "p_fdr"] = multipletests(result.loc[valid, "p_value"], alpha=FDR_ALPHA, method="fdr_bh")[1]
    result["univariate_significant"] = (result["p_fdr"] < FDR_ALPHA) & (result["effect_rank_biserial"].abs() >= EFFECT_SIZE_MIN)
    return result.sort_values("effect_rank_biserial", key=lambda s: s.abs(), ascending=False)


def tree_importance(df: pd.DataFrame) -> pd.DataFrame:
    X = df[CANDIDATE_COLS].fillna(df[CANDIDATE_COLS].median())
    y = df[DEFECT_COL].astype(int)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )
    clf = RandomForestClassifier(
        n_estimators=300, max_depth=6, class_weight="balanced_subsample", random_state=42, n_jobs=-1
    )
    clf.fit(X_train, y_train)
    perm = permutation_importance(
        clf, X_test, y_test, n_repeats=15, random_state=42, scoring="average_precision", n_jobs=-1
    )
    result = pd.DataFrame({
        "column": CANDIDATE_COLS,
        "importance_mean": perm.importances_mean,
        "importance_std": perm.importances_std,
    }).sort_values("importance_mean", ascending=False)
    result["tree_top10"] = result["column"].isin(result.nlargest(10, "importance_mean")["column"])
    return result


def main() -> None:
    df = load_dataset()
    n_defect = int(df[DEFECT_COL].sum())
    print(f"행 수: {len(df)}, Remain_Coat=1: {n_defect} ({n_defect/len(df):.4%})")

    uni = univariate_scan(df)
    uni.to_csv(OUT_DIR / "verify_01_univariate_mannwhitney.csv", index=False, encoding="utf-8-sig")

    tree = tree_importance(df)
    tree.to_csv(OUT_DIR / "verify_02_tree_permutation_importance.csv", index=False, encoding="utf-8-sig")

    merged = uni.merge(tree[["column", "importance_mean", "tree_top10"]], on="column", how="left")
    merged["confirmed_by_both_methods"] = merged["univariate_significant"] & merged["tree_top10"]
    merged = merged.sort_values("effect_rank_biserial", key=lambda s: s.abs(), ascending=False)
    merged.to_csv(OUT_DIR / "verify_03_cross_validated_factors.csv", index=False, encoding="utf-8-sig")

    confirmed = merged.loc[merged["confirmed_by_both_methods"], "column"].tolist()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defect_col": DEFECT_COL,
        "n_rows": len(df),
        "n_defect": n_defect,
        "defect_rate": n_defect / len(df),
        "effect_size_min": EFFECT_SIZE_MIN,
        "fdr_alpha": FDR_ALPHA,
        "confirmed_by_both_methods": confirmed,
        "note": (
            "Jun 브랜치 04_rem_coat_influence_factors_final.csv의 confirmed 판정(CLN_Pressure)과 "
            "독립적으로 재현되는지 비교하기 위한 검증. 통계 코드는 새로 작성, pipeline/config.py, "
            "pipeline/common.py만 재사용."
        ),
    }
    with open(OUT_DIR / "verify_00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n두 방법 모두에서 유의한 컬럼: {confirmed}")
    print(f"산출물 저장 위치: {OUT_DIR}")


if __name__ == "__main__":
    main()
