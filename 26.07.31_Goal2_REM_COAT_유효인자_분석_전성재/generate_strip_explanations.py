"""REM_COAT 불량 스트립 즉답용 설명 DB 생성 (전성재).

AI Agent가 "이 스트립 왜 불량났어?"라는 질문에 매번 모델을 새로 돌리지 않고
즉시 조회만 하면 되도록, Remain_Coat=1인 전체 스트립(2,332건)에 대해 SHAP
기여도 기반 자연어 설명을 미리 계산해서 JSON으로 저장한다.

verify_v5_shap_explanation.py와 같은 모델(RandomForest)/피처셋을 쓰되, 예시
5건이 아니라 **불량 스트립 전체**로 확장했다. 조회 키는 Lot_ID+Strip_ID
(pipeline/config.py의 분석키 규약과 동일 — Strip_ID 단독은 다른 Lot에서
재사용되므로 절대 단독 키로 쓰면 안 됨).

산출물: strip_explanations.json — {"LOT_ID|STRIP_ID": {...}} 형태
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
TOP_N_FACTORS = 3

DIRECTION_PHRASE = {
    True: "낮게",   # 기여도가 양수(불량 쪽)인데 값이 baseline보다 낮으면 "낮게 나와서"
    False: "높게",
}


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, CANDIDATE_COLS)
    z_df = zscore_transform(df, baseline, config.OPCOND, CANDIDATE_COLS)
    z_cols = [f"{c}_z" for c in CANDIDATE_COLS]
    z_df[z_cols] = z_df[z_cols].fillna(0.0)
    return z_df, z_cols


def make_sentence(machine: str, top_factors: list[dict], proba: float) -> str:
    if not top_factors:
        return f"{machine} 장비에서 불량 예측(확률 {proba:.0%})됐지만 뚜렷한 기여 인자를 찾지 못했습니다."
    lead = top_factors[0]
    direction = "낮아서" if lead["shap_contribution"] > 0 and lead["z_value"] < 0 else (
        "높아서" if lead["shap_contribution"] > 0 else "정상 범위였지만"
    )
    sentence = f"{machine} 장비 스트립, 불량 예측확률 {proba:.0%}. 주 원인: {lead['feature']}이(가) {direction} 불량 쪽으로 작용."
    if len(top_factors) > 1:
        others = ", ".join(f["feature"] for f in top_factors[1:])
        sentence += f" (보조 요인: {others})"
    return sentence


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

    # 조회 DB는 전체 데이터(train+test 안 가리고) 대상으로 만든다 — 실제 서비스에서는
    # "이미 일어난 불량"을 설명하는 용도라 train/test 분리가 의미 없음.
    explainer = shap.TreeExplainer(clf)
    all_defect_idx = z_df.index[z_df[DEFECT_COL] == 1]
    X_all_defect = z_df.loc[all_defect_idx, z_cols]

    raw_shap = explainer.shap_values(X_all_defect)
    if isinstance(raw_shap, list):
        shap_values = raw_shap[1]
    elif raw_shap.ndim == 3:
        shap_values = raw_shap[:, :, 1]
    else:
        shap_values = raw_shap

    probas = clf.predict_proba(X_all_defect)[:, 1]

    lookup: dict[str, dict] = {}
    feature_names = [c.replace("_z", "") for c in z_cols]
    for i, strip_idx in enumerate(all_defect_idx):
        row = z_df.loc[strip_idx]
        key = f"{row['Lot_ID']}|{row['Strip_ID']}"
        row_shap = pd.Series(shap_values[i], index=feature_names)
        top = row_shap.reindex(row_shap.abs().sort_values(ascending=False).index).head(TOP_N_FACTORS)
        top_factors = [
            {
                "feature": feat,
                "shap_contribution": float(val),
                "z_value": float(row[feat + "_z"]) if pd.notna(row[feat + "_z"]) else None,
                "raw_value": float(row[feat]) if pd.notna(row[feat]) else None,
            }
            for feat, val in top.items()
        ]
        lookup[key] = {
            "Lot_ID": row["Lot_ID"],
            "Strip_ID": row["Strip_ID"],
            "Machine_ID": row["Machine_ID"],
            "Product_ID": row["Product_ID"],
            "Recipe_ID": row["Recipe_ID"],
            "DateTime": str(row["DateTime"]),
            "predicted_proba_defect": float(probas[i]),
            "top_factors": top_factors,
            "explanation_ko": make_sentence(row["Machine_ID"], top_factors, probas[i]),
        }

    with open(OUT_DIR / "strip_explanations.json", "w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, indent=1)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "AI Agent가 '이 스트립 왜 불량났어?' 질문에 즉시 조회로 답하기 위한 사전계산 DB",
        "key_format": "Lot_ID|Strip_ID (pipeline/config.py KEY 규약과 동일, Strip_ID 단독 사용 금지)",
        "n_strips": len(lookup),
        "model": "RandomForestClassifier(n_estimators=300, max_depth=6), verify_v5와 동일 설정",
        "usage_example": "lookup['LOT005662|STRIP14965']['explanation_ko']",
    }
    with open(OUT_DIR / "strip_explanations_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"불량 스트립 {len(lookup)}건에 대한 설명 DB 생성 완료")
    sample_key = next(iter(lookup))
    print(f"예시 ({sample_key}): {lookup[sample_key]['explanation_ko']}")


if __name__ == "__main__":
    main()
