"""Chipping/Micro_Crack 다변량 위험 예측 모델 학습 — JHdaimma 방법론 재현 + 저장.

배경: 단변량 확정 원인(CAUSE_FACTORS)만으로는 조기경보 리드타임이 0일이라는 걸
analyze_lead_time.py로 확인했다. JHdaimma가 만든 XGBoost+SHAP 다변량 모델
(Chipping AUC 0.965, Micro_Crack AUC 0.803)이 이미 검증돼 있지만, 학습만 하고
저장은 안 해서(pickle/joblib 없음) 매번 다시 학습해야 했다. 이 스크립트는 그
모델을 실제로 학습해서 파일로 저장한다 — Health Index/AI Agent가 재학습 없이
불러와서 predict_proba로 "지금 이 순간 위험 확률"을 바로 조회할 수 있게 하기 위함.

원본 코드 출처: JHdaimma 브랜치
  26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/build_relationship_db.py
  26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/build_shap_layer.py
config/헬퍼 블록(FEATURES/PROCESS_STAGE/layer_of/zscore 등)은 원본을 거의 그대로 가져왔다
(그녀가 이미 검증한 정의를 다시 만들 이유가 없음). 모델 학습 루프(XGBoost 파라미터, pure
라벨, Machine/source_dataset 더미 통제)도 동일 — 차이는 "3방법 대조/SHAP 설명" 부분을
빼고 "모델 학습 + 저장"에만 집중한 것, 그리고 모델 A(FDC 전용, 원인 후보)만 학습한 것
(모델 B(전체) 확장은 필요시 추가).

**r1 데이터 필요**: DP_HealthIndex_Dataset_r1.csv(멘토 배포, 저장소 루트에 로컬로만 존재,
git 미추적 — 용량 때문에 팀 정책상 안 올림)가 있어야 실행된다. 원본만으로는 Chipping이
4건뿐이라 train/test 분리 자체가 불가능하다. r1은 "학습/검증 전용" 팀 정책에 정확히
부합하는 용도로만 쓴다(원본과 합쳐서 공식 결과로 쓰지 않음 — 여기선 모델 가중치를 만드는
데만 쓰고, 실제 서빙(predict)은 원본 데이터에만 적용한다).

실행 (저장소 루트에서):
  python "26.08.01_Goal_AI_Agent_Prototype_김시우/train_defect_models.py"

산출물: 26.08.01_Goal_AI_Agent_Prototype_김시우/models/{target}_model.joblib
  각 파일에 {"model": XGBClassifier, "features": [...z-score 계산할 원본 컬럼명들],
             "feature_cols": [...학습에 실제 쓴 컬럼명(=_z 붙은 것+더미)],
             "machine_dummy_cols": [...], "auc": float, "pr_auc": float} 딕셔너리 저장.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

RNG = 42

# ==================================================================== JHdaimma config 이식
# (build_relationship_db.py 상단 그대로 — 이미 검증된 정의라 재구현 안 함)
OPCOND = ["Product_ID", "Recipe_ID"]
MAD_SCALE = 1.4826

SUBSYSTEMS = {
    "fdc_laser": ["Laser_Power", "Power_Efficiency", "Laser_Centering_Position",
                  "Laser_Current", "Laser_Voltage", "Beam_Diameter", "Frequency"],
    "fdc_motion": ["Feed_Speed", "Alignment_Time", "Process_Time",
                   "Cutting_X_Index", "Cutting_Y_Index"],
    "fdc_thermal": ["Head_Temp", "Cooling_Flow", "Cooling_Water_Temp"],
    "fdc_cleaning": ["CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
                     "Laser_Head_Remain_Time"],
    "fdc_mechanical": ["Vibration"],
    "response": ["Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
                 "Groove_Depth", "Package_Size_1", "Package_Size_2", "Package_Size_3",
                 "Package_Size_4", "Coating_Thickness", "Coating_Uniformity",
                 "Surface_Roughness"],
}
DOMAIN_FEATURES = ["Cooling_Thermal_Load", "Laser_Cleaning_Demand", "Cleaning_Capacity",
                   "Cleaning_Load_Ratio", "Package_Size_Asymmetry"]
FDC_COLS = (SUBSYSTEMS["fdc_laser"] + SUBSYSTEMS["fdc_motion"] + SUBSYSTEMS["fdc_thermal"]
            + SUBSYSTEMS["fdc_cleaning"] + SUBSYSTEMS["fdc_mechanical"])
RESPONSES = SUBSYSTEMS["response"]
FEATURES = FDC_COLS + RESPONSES + DOMAIN_FEATURES + ["Maintenance_Count"]

# Micro_Crack 후보에서 제외할 "레이저 그루빙 계열"(현업 도메인 제약: 그루빙 문제 아님)
GROOVING_STAGES_COLS = {
    "Laser_Power", "Power_Efficiency", "Laser_Current", "Laser_Voltage", "Beam_Diameter",
    "Laser_Centering_Position", "Frequency", "Head_Temp", "Laser_Head_Remain_Time",
    "Groove_Depth", "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
    "Laser_Cleaning_Demand",
}


def NORMAL(f):
    return (f["Yield"] == 100) & (f["NG_Code"] == "OK")


def add_domain_features(df):
    r = df.copy()
    r["Cooling_Thermal_Load"] = r["Cooling_Water_Temp"] / r["Cooling_Flow"]
    r["Laser_Cleaning_Demand"] = r["Laser_Power"] * r["Groove_Depth"]
    r["Cleaning_Capacity"] = r["CLN_Flow"] * r["CLN_Pressure"] * r["CLN_Time"]
    r["Cleaning_Load_Ratio"] = r["Laser_Cleaning_Demand"] / r["Cleaning_Capacity"]
    pk = ["Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4"]
    r["Package_Size_Asymmetry"] = r[pk].std(axis=1)
    return r


def baseline_stats(df_ok, keys, cols):
    g = df_ok.groupby(keys, dropna=False)
    frames = []
    for c in cols:
        a = g[c].agg(n="count", median="median")
        a["mad"] = g[c].apply(lambda s: (s - s.median()).abs().median())
        a["column"] = c
        frames.append(a.reset_index())
    res = pd.concat(frames, ignore_index=True)
    res["robust_z_scale"] = MAD_SCALE * res["mad"]
    return res


def zscore(df, bl, keys, cols):
    out = df.copy()
    for c in cols:
        sub = bl.loc[bl.column == c, keys + ["median", "robust_z_scale"]].rename(
            columns={"median": "__m", "robust_z_scale": "__s"})
        out = out.merge(sub, on=keys, how="left")
        s = out["__s"].where(out["__s"].abs() > 1e-9)
        out[f"{c}_z"] = (out[c] - out["__m"]) / s
        out = out.drop(columns=["__m", "__s"])
    return out


def layer_of(col):
    return "Response" if col in RESPONSES else ("FDC" if col in FDC_COLS else "Other")


# ==================================================================== 학습
def main() -> None:
    r1_path = REPO_ROOT / "DP_HealthIndex_Dataset_r1.csv"
    if not r1_path.exists():
        print(f"[중단] r1 파일이 없습니다: {r1_path}", file=sys.stderr)
        print("팀 정책상 git엔 없음 — JHdaimma/멘토한테 받아서 저장소 루트에 두세요.", file=sys.stderr)
        sys.exit(1)

    print("[1/3] 데이터 로드 (원본 + r1, 학습 전용 — 팀 정책: r1은 원본과 공식 병합 안 함)")
    o = pd.read_csv(REPO_ROOT / "data" / "raw" / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
    r = pd.read_csv(r1_path, encoding="utf-8-sig")
    o["source_dataset"] = "original"
    r["source_dataset"] = "r1"
    df = add_domain_features(pd.concat([o, r], ignore_index=True))
    df["is_normal"] = NORMAL(df)
    bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
    df = zscore(df, bl, OPCOND, FEATURES)
    print(f"    {len(df):,}행 | 정상군 {df.is_normal.sum():,}")

    mach = pd.get_dummies(df["Machine_ID"], prefix="MACH", drop_first=True).astype(float)
    dsd = pd.get_dummies(df["source_dataset"], prefix="DS", drop_first=True).astype(float)

    TARGETS = {"Chipping": "Chipping", "Micro_Crack": "Micro_Crack"}

    print("\n[2/3] 모델 학습 (A_cause_FDConly — 조절 가능한 FDC 변수만, 원인 후보용)")
    for tname, tcol in TARGETS.items():
        other = "Micro_Crack" if tname == "Chipping" else "Chipping"
        y = ((df[tcol] == 1) & (df[other] == 0)).astype(int).values  # pure 라벨(동시발생 오염 배제)
        keep = ~((df[tcol] == 0) & (df[other] == 1)).values
        print(f"\n=== {tname} === pure 양성 {y[keep].sum():,} / 대조군 {(y[keep]==0).sum():,}")

        base_feats = [c for c in FEATURES if c not in GROOVING_STAGES_COLS] if tname == "Micro_Crack" else FEATURES
        fdc_only = [c for c in base_feats if layer_of(c) == "FDC"]
        fz = [f"{c}_z" for c in fdc_only]

        X = pd.concat([df[fz], mach, dsd], axis=1)[keep]
        yy = y[keep]
        Xtr, Xte, ytr, yte = train_test_split(X, yy, test_size=0.25, random_state=RNG, stratify=yy)
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
        print(f"  피처 {len(fdc_only)}개  ROC-AUC={auc:.4f}  PR-AUC={ap:.4f}  (JHdaimma 원본 참고치: "
              f"{'0.965' if tname=='Chipping' else '0.803'})")

        bundle = {
            "model": clf,
            "raw_features": fdc_only,
            "feature_cols": list(X.columns),
            "machine_dummy_cols": list(mach.columns),
            "source_dummy_cols": list(dsd.columns),
            "target": tname,
            "auc": round(float(auc), 4),
            "pr_auc": round(float(ap), 4),
            "trained_at": pd.Timestamp.now().isoformat(),
        }
        out_path = MODEL_DIR / f"{tname.lower()}_model.joblib"
        joblib.dump(bundle, out_path)
        print(f"  저장: {out_path}")

    print("\n[3/3] 완료")


if __name__ == "__main__":
    main()
