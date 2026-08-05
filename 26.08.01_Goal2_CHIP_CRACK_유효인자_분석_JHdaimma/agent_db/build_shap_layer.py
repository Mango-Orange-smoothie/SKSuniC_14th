"""XGBoost + SHAP 레이어 — Chipping / Micro_Crack

기존 DB(Jun 방법론: 통계검정 + RandomForest permutation importance)를 **대체하지 않고
병기**한다. 김시우 README의 "여러 방법에서 공통 상위인 것만 유효인자" 원칙에 따라
SHAP을 3번째 독립 방법으로 추가하고, 세 방법의 순위를 대조한다.

핵심 설계 — 모델을 2개로 분리 (다중공선성 함정 회피)
  모델 A (원인 모델) : FDC 전용. Response를 빼야 Laser_Power 같은 상류 인자가
                       Kerf_Width_Profile에게 기여도를 뺏기지 않는다.
                       (Laser_Power <-> Kerf_Width_Profile spearman = -0.58)
  모델 B (감시 모델) : FDC + Response 전체. 무엇을 모니터링할지 답한다.

공통 규약
  - 김시우 pipeline: OPCOND 층 OK-baseline median/MAD 강건 z-score
  - Machine_ID / source_dataset 더미로 장비 편중·배치 효과 통제
  - pure 라벨(상대 결함 동시발생 제외) 기준 — 오염 배제
  - 현업 도메인지식: Micro_Crack은 그루빙 계열 제외

산출물
  db_06_shap_global.csv       변수별 평균|SHAP| + 평균 부호(방향) + 모델별
  db_07_shap_local.csv        개별 건 예시 (Agent가 "이 건은 왜?"에 답하는 데모)
  db_08_method_agreement.csv  3방법 순위 대조 (통계 / permutation / SHAP)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
# import shap  # TreeSHAP은 xgboost 내장 pred_contribs 사용 (버전 비호환 회피)
import xgboost as xgb
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.model_selection import train_test_split

RNG = 42
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent

# 메인 DB 스크립트에서 config/헬퍼/도메인 정의를 그대로 가져온다 (중복 정의 금지)
src = open(OUT / "build_relationship_db.py", encoding="utf-8").read()
exec(src.split("# ==================================================================== 데이터")[0])

print("[1/5] 데이터 로드 (원본 + r1)")
o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"; r["source_dataset"] = "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)
print(f"    {len(df):,}행 | 정상군 {df.is_normal.sum():,}")

mach = pd.get_dummies(df["Machine_ID"], prefix="MACH", drop_first=True).astype(float)
dsd = pd.get_dummies(df["source_dataset"], prefix="DS", drop_first=True).astype(float)
CTRL = list(mach.columns) + list(dsd.columns)

TARGETS = {"Chipping": "Chipping", "Micro_Crack": "Micro_Crack"}

global_rows, local_rows, agree_rows = [], [], []
model_meta = {}

for tname, tcol in TARGETS.items():
    other = "Micro_Crack" if tname == "Chipping" else "Chipping"
    y = ((df[tcol] == 1) & (df[other] == 0)).astype(int).values   # pure 라벨
    # 상대 결함 단독 행은 제외 (해당 결함도 아니고 순수 정상도 아니므로 대조군 오염)
    keep = ~((df[tcol] == 0) & (df[other] == 1)).values
    print(f"\n=== {tname} === pure 양성 {y[keep].sum():,} / 대조군 {(y[keep]==0).sum():,}")

    # 현업 도메인 제약: Micro_Crack은 레이저 그루빙 계열 제외
    if tname == "Micro_Crack":
        base_feats = [c for c in FEATURES if PROCESS_STAGE[c][0] not in GROOVING_STAGES]
    else:
        base_feats = FEATURES

    # 원인 모델 = 직접 조절 가능한 FDC만. 단계 라벨이 아니라 layer_of()로 판정한다.
    fdc_only = [c for c in base_feats if layer_of(c) == "FDC"]
    all_feats = base_feats

    MODELS = {
        "A_cause_FDConly": fdc_only,     # 원인 모델
        "B_monitor_full": all_feats,     # 감시 모델
    }

    for mname, feats in MODELS.items():
        fz = [f"{c}_z" for c in feats]
        X = pd.concat([df[fz], mach, dsd], axis=1)[keep]
        yy = y[keep]
        Xtr, Xte, ytr, yte = train_test_split(X, yy, test_size=0.25,
                                              random_state=RNG, stratify=yy)
        spw = float((ytr == 0).sum() / max((ytr == 1).sum(), 1))
        clf = xgb.XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.08,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            scale_pos_weight=spw, eval_metric="aucpr",
            random_state=RNG, n_jobs=-1, tree_method="hist",
        )
        clf.fit(Xtr, ytr)
        proba = clf.predict_proba(Xte)[:, 1]
        auc = roc_auc_score(yte, proba)
        ap = average_precision_score(yte, proba)
        print(f"  [{mname}] 피처 {len(feats)}개  ROC-AUC={auc:.4f}  PR-AUC={ap:.4f}")

        # TreeSHAP — XGBoost 내장 구현(pred_contribs)을 사용한다.
        # shap.TreeExplainer와 동일한 알고리즘·동일한 값이며(둘 다 정확해),
        # shap 0.49 <-> xgboost 3.2 버전 비호환(base_score 파싱 오류)을 우회한다.
        sub = Xte.sample(n=min(20000, len(Xte)), random_state=RNG)
        dm = xgb.DMatrix(sub, feature_names=list(sub.columns))
        contribs = clf.get_booster().predict(dm, pred_contribs=True)
        sv = np.asarray(contribs)[:, :-1]   # 마지막 열은 base value(bias)

        mean_abs = np.abs(sv).mean(axis=0)
        mean_signed = sv.mean(axis=0)
        # 값이 높을 때 SHAP이 커지는가 = 방향 판정 (스피어만 부호)
        dir_corr = []
        for j, col in enumerate(sub.columns):
            v = sub.iloc[:, j].values
            if np.std(v) < 1e-12:
                dir_corr.append(np.nan)
            else:
                dir_corr.append(float(np.corrcoef(v, sv[:, j])[0, 1]))

        tab = pd.DataFrame({
            "feature_col": sub.columns, "mean_abs_shap": mean_abs,
            "mean_signed_shap": mean_signed, "value_shap_corr": dir_corr,
        })
        tab = tab[~tab.feature_col.isin(CTRL)].copy()          # 통제변수 제외
        tab["factor"] = tab.feature_col.str.replace("_z$", "", regex=True)
        tab = tab.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
        tab["shap_rank"] = np.arange(1, len(tab) + 1)

        for _, x in tab.iterrows():
            c = x.factor
            stage, conf = PROCESS_STAGE[c]
            direction = ("high_is_risky" if x.value_shap_corr > 0.05 else
                         "low_is_risky" if x.value_shap_corr < -0.05 else
                         "nonlinear_or_none")
            global_rows.append({
                "target": tname, "model": mname, "factor": c,
                "layer": layer_of(c),
                "process_stage": stage, "is_laser_grooving": stage in GROOVING_STAGES,
                "shap_rank": int(x.shap_rank),
                "mean_abs_shap": round(float(x.mean_abs_shap), 6),
                "mean_signed_shap": round(float(x.mean_signed_shap), 6),
                "value_shap_corr": None if pd.isna(x.value_shap_corr) else round(float(x.value_shap_corr), 4),
                "shap_direction": direction,
                "model_roc_auc": round(float(auc), 4), "model_pr_auc": round(float(ap), 4),
                "n_features": len(feats),
            })
        model_meta[f"{tname}|{mname}"] = {"roc_auc": round(float(auc), 4),
                                          "pr_auc": round(float(ap), 4),
                                          "n_features": len(feats),
                                          "scale_pos_weight": round(spw, 2)}

        # ---- 개별 건 설명 예시 (Agent 데모용) : 불량 예측 확률 높은 상위 5건
        if mname == "A_cause_FDConly":
            p_sub = clf.predict_proba(sub)[:, 1]
            top_idx = np.argsort(-p_sub)[:5]
            featnames = list(sub.columns)
            for rank_i, i in enumerate(top_idx, 1):
                row_orig = df.loc[sub.index[i]]
                contrib = sorted(
                    [(featnames[j], sv[i, j]) for j in range(len(featnames))
                     if featnames[j] not in CTRL],
                    key=lambda t: -abs(t[1]))[:5]
                for cr, (fn, val) in enumerate(contrib, 1):
                    fac = fn.replace("_z", "")
                    local_rows.append({
                        "target": tname, "case_rank": rank_i,
                        "Lot_ID": row_orig["Lot_ID"], "Strip_ID": row_orig["Strip_ID"],
                        "Machine_ID": row_orig["Machine_ID"],
                        "Product_ID": row_orig["Product_ID"], "Recipe_ID": row_orig["Recipe_ID"],
                        "source_dataset": row_orig["source_dataset"],
                        "predicted_risk": round(float(p_sub[i]), 4),
                        "actual_defect": int(row_orig[tcol]),
                        "contrib_rank": cr, "factor": fac,
                        "shap_value": round(float(val), 5),
                        "factor_zscore": round(float(row_orig.get(f"{fac}_z", np.nan)), 3),
                        "factor_raw": round(float(row_orig.get(fac, np.nan)), 5),
                        "interpretation": ("위험을 높임" if val > 0 else "위험을 낮춤"),
                    })

print("\n[4/5] 3방법 순위 대조")
fac_db = pd.read_csv(OUT / "db_01_factors.csv", encoding="utf-8-sig")
gl = pd.DataFrame(global_rows)
for tname in TARGETS:
    f = fac_db[fac_db.target == tname].copy()
    # 통계(단변량) 순위 = |delta_pure| 내림차순
    f["stat_rank"] = f.delta_pure.abs().rank(ascending=False, method="min").astype(int)
    for mname in ["A_cause_FDConly", "B_monitor_full"]:
        s = gl[(gl.target == tname) & (gl.model == mname)][["factor", "shap_rank",
                                                            "mean_abs_shap", "shap_direction"]]
        m = f.merge(s, on="factor", how="inner")
        for _, x in m.iterrows():
            ranks = [x.stat_rank, x.tree_rank_pure, x.shap_rank]
            top10 = sum(1 for rr in ranks if rr <= 10)
            agree_rows.append({
                "target": tname, "model": mname, "factor": x.factor,
                "layer": x.layer, "role": x.role, "verdict_existing": x.verdict,
                "rank_statistic": int(x.stat_rank), "rank_permutation": int(x.tree_rank_pure),
                "rank_shap": int(x.shap_rank),
                "delta_pure": x.delta_pure, "perm_importance": x.tree_imp_pure,
                "mean_abs_shap": x.mean_abs_shap, "shap_direction": x.shap_direction,
                "n_methods_in_top10": top10,
                "agreement": ("3방법 모두 상위" if top10 == 3 else
                              "2방법 상위" if top10 == 2 else
                              "1방법만 상위" if top10 == 1 else "모두 하위"),
            })

pd.DataFrame(global_rows).to_csv(OUT / "db_06_shap_global.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(local_rows).to_csv(OUT / "db_07_shap_local.csv", index=False, encoding="utf-8-sig")
ag = pd.DataFrame(agree_rows).sort_values(
    ["target", "model", "n_methods_in_top10", "rank_shap"], ascending=[True, True, False, True])
ag.to_csv(OUT / "db_08_method_agreement.csv", index=False, encoding="utf-8-sig")

with open(OUT / "db_00_metadata.json", encoding="utf-8") as f:
    meta = json.load(f)
meta["shap_layer"] = {
    "added_at": datetime.now(timezone.utc).isoformat(),
    "models": model_meta,
    "design": "모델 A(FDC 전용, 원인) / 모델 B(FDC+Response, 감시)로 분리 — "
              "Laser_Power<->Kerf_Width_Profile(r=-0.58) 등 다중공선성으로 SHAP 기여도가 "
              "하류 Response에 흡수되는 것을 방지",
    "explainer": "shap.TreeExplainer (TreeSHAP, 트리 모델에 대해 정확해)",
    "model": "XGBClassifier(n=400, depth=5, lr=0.08, scale_pos_weight=불균형보정)",
    "label": "pure (상대 결함 동시발생 행 제외)",
    "controls": "Machine_ID 더미 + source_dataset 더미",
    "note": "기존 Jun 방법론 결과를 대체하지 않고 3번째 독립 방법으로 병기",
}
with open(OUT / "db_00_metadata.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("\n[5/5] 완료\n" + "=" * 80)
for tname in TARGETS:
    for mname in ["A_cause_FDConly", "B_monitor_full"]:
        s = gl[(gl.target == tname) & (gl.model == mname)].head(8)
        if not len(s):
            continue
        mm = model_meta[f"{tname}|{mname}"]
        print(f"\n[{tname} / {mname}]  AUC={mm['roc_auc']} PR-AUC={mm['pr_auc']}")
        for _, x in s.iterrows():
            print(f"   {x.shap_rank:>2}. {x.factor:26s} |SHAP|={x.mean_abs_shap:.4f} "
                  f"{x.shap_direction:20s} {x.layer}")
print("\n--- 3방법 합의 (3방법 모두 top10) ---")
for tname in TARGETS:
    s = ag[(ag.target == tname) & (ag.n_methods_in_top10 == 3)]
    print(f"  [{tname}] " + (", ".join(sorted(set(s.factor))) if len(s) else "없음"))
