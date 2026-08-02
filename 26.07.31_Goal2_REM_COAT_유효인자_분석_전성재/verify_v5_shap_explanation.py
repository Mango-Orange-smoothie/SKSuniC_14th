"""Goal2 REM_COAT — 5차: SHAP 개별 스트립 설명 (전성재).

지금까지의 방법(permutation importance)은 "전체적으로 어떤 변수가 중요한가"만 답한다.
SHAP(SHapley Additive exPlanations)는 "이 스트립 하나의 예측에 각 변수가 얼마나
기여했는가"를 개별적으로 쪼개서 보여준다 — 나중에 "이 스트립이 왜 불량 예측됐는지"를
현장에 설명하는 대시보드를 만들 때 필요한 형태다.

RandomForestClassifier(v1 검증과 동일 계열, shap.TreeExplainer가 지원)를 새로 학습해서
① 전역 SHAP 중요도(=지금까지의 permutation importance와 같은 순위가 나오는지 교차검증)
② 실제 Remain_Coat=1 스트립 5건을 뽑아 개별 기여도 breakdown
을 산출한다. pipeline/config.py, pipeline/common.py만 재사용.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
DEFECT_COL = "Remain_Coat"
CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]
N_EXAMPLES = 5


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, CANDIDATE_COLS)
    z_df = zscore_transform(df, baseline, config.OPCOND, CANDIDATE_COLS)
    z_cols = [f"{c}_z" for c in CANDIDATE_COLS]
    z_df[z_cols] = z_df[z_cols].fillna(0.0)
    return z_df, z_cols


def main() -> None:
    df = load_dataset()
    z_df, z_cols = build_features(df)

    X = z_df[z_cols]
    y = z_df[DEFECT_COL].astype(int)
    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, z_df.index, test_size=0.3, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=300, max_depth=6, class_weight="balanced_subsample", random_state=42, n_jobs=-1
    )
    clf.fit(X_train, y_train)

    explainer = shap.TreeExplainer(clf)
    # 이진분류: shap_values가 [클래스0, 클래스1] 리스트 또는 (n,features,2) 배열로 나올 수 있어 클래스1만 취함
    raw_shap = explainer.shap_values(X_test)
    if isinstance(raw_shap, list):
        shap_values = raw_shap[1]
    elif raw_shap.ndim == 3:
        shap_values = raw_shap[:, :, 1]
    else:
        shap_values = raw_shap

    # ① 전역 SHAP 중요도
    global_importance = pd.DataFrame({
        "column": [c.replace("_z", "") for c in z_cols],
        "mean_abs_shap": np.abs(shap_values).mean(axis=0),
    }).sort_values("mean_abs_shap", ascending=False)
    global_importance["shap_top10"] = global_importance["column"].isin(
        global_importance.nlargest(10, "mean_abs_shap")["column"]
    )
    global_importance.to_csv(OUT_DIR / "verify_v5_01_shap_global_importance.csv", index=False, encoding="utf-8-sig")

    # ② 실제 Remain_Coat=1 스트립 몇 건을 뽑아 개별 breakdown
    test_defect_positions = np.where(y_test.values == 1)[0]
    rng = np.random.default_rng(42)
    chosen = rng.choice(test_defect_positions, size=min(N_EXAMPLES, len(test_defect_positions)), replace=False)

    base_value = explainer.expected_value
    base_value = base_value[1] if isinstance(base_value, (list, np.ndarray)) and len(np.shape(base_value)) else base_value

    example_rows = []
    for pos in chosen:
        strip_idx = idx_test[pos]
        row_shap = shap_values[pos]
        top_contrib = pd.Series(row_shap, index=[c.replace("_z", "") for c in z_cols]).sort_values(
            key=lambda s: s.abs(), ascending=False
        ).head(5)
        for rank, (col, val) in enumerate(top_contrib.items(), start=1):
            example_rows.append({
                "strip_row_index": int(strip_idx),
                "Machine_ID": z_df.loc[strip_idx, "Machine_ID"],
                "predicted_proba_defect": float(clf.predict_proba(X_test.loc[[X_test.index[pos]]])[0, 1]),
                "base_value": float(base_value),
                "rank": rank,
                "feature": col,
                "raw_value": float(z_df.loc[strip_idx, col]),
                "shap_contribution": float(val),
            })
    examples_df = pd.DataFrame(example_rows)
    examples_df.to_csv(OUT_DIR / "verify_v5_02_shap_example_strips.csv", index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "RandomForestClassifier(n_estimators=300, max_depth=6)",
        "n_test": len(X_test),
        "global_shap_top5": global_importance.head(5)["column"].tolist(),
        "n_example_strips": len(chosen),
        "note": "permutation importance(1차 검증)와 SHAP 전역 중요도 순위가 일치하는지가 교차검증 포인트.",
    }
    with open(OUT_DIR / "verify_v5_00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("전역 SHAP 중요도 top5:", summary["global_shap_top5"])
    print(f"\n예시 스트립 {len(chosen)}건의 개별 기여도는 verify_v5_02_shap_example_strips.csv 참고")


if __name__ == "__main__":
    main()
