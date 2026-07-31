"""Goal2 REM_COAT 유효인자 2차 검증 — Machine/OPCOND를 통제한 다변량 분석 (전성재).

1차 검증(verify_rem_coat_factors.py)과 Jun 브랜치 분석 둘 다 단변량 비교였다:
"불량군 vs 정상군에서 이 변수값이 다른가"만 보고, Machine/Product/Recipe가 다르면
변수값도 불량률도 같이 달라질 수 있다는 confounding을 통제하지 않았다.

01_rem_coat_rate_by_stratum.csv에서 DP04만 불량률이 뚜렷이 높다는 걸 이미 확인했으므로,
DP04가 우연히 CLN_Pressure 설정도 다르면 "CLN_Pressure가 원인"이 아니라 "DP04라서"인
가짜상관일 위험이 있다 (ANALYSIS_GUIDE.md가 경고하는 바로 그 문제).

이번엔 완전히 다른 두 방법으로 confounding을 통제해서 재확인한다:
  A. OPCOND(Product x Recipe) 층별 강건 z-score로 정규화한 뒤, Machine_ID 더미변수를
     공변량으로 넣은 L1(Lasso) 로지스틱 회귀 — "같은 장비, 같은 제품/레시피 조건에서도
     이 변수가 여전히 불량과 관련 있는가"를 직접 검정
  B. HistGradientBoostingClassifier + permutation importance (ROC-AUC 기준) — 1차 검증의
     RandomForest와는 다른 트리 앙상블 계열, 다른 스코어링 지표

pipeline/config.py, pipeline/common.py(공용 baseline/zscore 함수)만 재사용.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegressionCV
from sklearn.model_selection import train_test_split

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
DEFECT_COL = "Remain_Coat"
CONTINUOUS_CANDIDATES = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES
COEF_MEANINGFUL_THRESHOLD = 0.15  # |표준화 로지스틱 계수| 이 값 이상 -> 1 stratum-SD 변화당 odds >=16% 변화


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """OPCOND baseline으로 강건 z-score 정규화 (Machine 차이는 남기고, Product/Recipe 차이만 제거)."""
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, CONTINUOUS_CANDIDATES)
    z_df = zscore_transform(df, baseline, config.OPCOND, CONTINUOUS_CANDIDATES)
    z_cols = [f"{c}_z" for c in CONTINUOUS_CANDIDATES]
    z_df[z_cols] = z_df[z_cols].fillna(0.0)  # baseline 없는 극소표본 층은 중립값 처리
    return z_df, z_cols


def multivariate_logit(df: pd.DataFrame, z_cols: list[str]) -> pd.DataFrame:
    machine_dummies = pd.get_dummies(df["Machine_ID"], prefix="Machine", drop_first=True)
    X = pd.concat([df[z_cols].reset_index(drop=True), machine_dummies.reset_index(drop=True)], axis=1)
    y = df[DEFECT_COL].astype(int).reset_index(drop=True)

    model = LogisticRegressionCV(
        penalty="l1", solver="liblinear", Cs=5, cv=3, scoring="average_precision",
        class_weight="balanced", max_iter=1000, n_jobs=-1, random_state=42,
    )
    model.fit(X, y)

    coefs = pd.Series(model.coef_[0], index=X.columns)
    result = coefs.loc[z_cols].rename("logit_coef").reset_index().rename(columns={"index": "z_column"})
    result["column"] = result["z_column"].str.replace("_z$", "", regex=True)
    result["odds_ratio_per_stratum_sd"] = np.exp(result["logit_coef"])
    result["meaningful_after_machine_control"] = result["logit_coef"].abs() >= COEF_MEANINGFUL_THRESHOLD
    return result[["column", "logit_coef", "odds_ratio_per_stratum_sd", "meaningful_after_machine_control"]]


def gradient_boosting_importance(df: pd.DataFrame, z_cols: list[str]) -> pd.DataFrame:
    X = df[z_cols]
    y = df[DEFECT_COL].astype(int)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)

    clf = HistGradientBoostingClassifier(max_depth=4, random_state=42, class_weight="balanced")
    clf.fit(X_train, y_train)

    perm = permutation_importance(clf, X_test, y_test, n_repeats=15, random_state=42, scoring="roc_auc", n_jobs=-1)
    result = pd.DataFrame({
        "z_column": z_cols,
        "gb_importance_mean": perm.importances_mean,
    })
    result["column"] = result["z_column"].str.replace("_z$", "", regex=True)
    result["gb_top10"] = result["column"].isin(result.nlargest(10, "gb_importance_mean")["column"])
    return result[["column", "gb_importance_mean", "gb_top10"]]


def main() -> None:
    df = load_dataset()
    z_df, z_cols = build_features(df)

    logit_result = multivariate_logit(z_df, z_cols)
    gb_result = gradient_boosting_importance(z_df, z_cols)

    merged = logit_result.merge(gb_result, on="column", how="outer")
    merged["confirmed_v2_machine_controlled"] = merged["meaningful_after_machine_control"] & merged["gb_top10"]
    merged = merged.sort_values("logit_coef", key=lambda s: s.abs(), ascending=False)
    merged.to_csv(OUT_DIR / "verify_v2_04_machine_controlled_factors.csv", index=False, encoding="utf-8-sig")

    confirmed = merged.loc[merged["confirmed_v2_machine_controlled"], "column"].tolist()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "OPCOND z-score + Machine_ID 더미 통제 L1 로지스틱 회귀 + HistGradientBoosting permutation importance(ROC-AUC)",
        "coef_meaningful_threshold": COEF_MEANINGFUL_THRESHOLD,
        "confirmed_v2_machine_controlled": confirmed,
        "note": "1차 검증(verify_rem_coat_factors.py)과 Jun 브랜치 분석은 Machine/OPCOND confounding을 통제하지 않은 단변량 비교였음 — 이번이 통제 후 재확인.",
    }
    with open(OUT_DIR / "verify_v2_00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Machine 통제 후에도 유의미한 컬럼: {confirmed}")
    print(merged.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
