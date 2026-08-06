"""Goal2 — Chipping / Micro_Crack 유효인자 발굴 (원본 + r1 통합)

참고 브랜치: 김시우(pipeline/ 전처리 규약) + Jun(유효인자 발굴 방법론) **만** 사용.
             전성재 브랜치 방법론(L1 로지스틱 / HistGradientBoosting / Machine 통제
             다변량)은 이번 분석에서 일절 사용하지 않는다.

[김시우 브랜치에서 그대로 가져온 것]
  - config.KEY/GROUP/OPCOND/NORMAL, SUBSYSTEMS, add_domain_features, MAD_SCALE, TREND_ALPHA
  - common.compute_stratum_baseline_stats (OK행 기준 OPCOND 층 median/MAD baseline)
  - common.zscore_transform (강건 z-score: (x - median) / (1.4826 * MAD))
  - common.stratified_split_by_defect (라벨 층화 분할)
  - 00_column_classification.csv 의 include_in_downstream_default / degradation_trend_class

[Jun 브랜치에서 그대로 가져온 것]
  - 이중 라벨(primary = NG_Code, broad = 이진 defect 컬럼)
  - Mann-Whitney U(two-sided) + BH-FDR(alpha=0.05) + Cliff's delta(기준 |d| >= 0.2)
  - RandomForestClassifier(n_estimators=200, max_depth=8, class_weight='balanced')
    + permutation_importance(scoring='average_precision', n_repeats=15), top-10 기준
  - verdict 로직 (confirmed / candidate_needs_domain_review / candidate_weak_signal /
    insufficient_evidence)
  - DOMAIN_HYPOTHESIS / NOT_RELATED_TO_DEFECT / TEAM_UNDETERMINED 도메인 가설표

[이번 분석에서 달라진 것]
  1) 입력 데이터: 원본 100,000행 + r1(멘토 신규) 100,000행 = 200,000행 통합
  2) 현업 도메인 지식 반영: "Micro_Crack은 레이저 그루빙 공정의 문제가 아니다"
     -> Jun의 CRACK DOMAIN_HYPOTHESIS 중 레이저 그루빙 계열을 NOT_RELATED_TO_DEFECT로 이동
  3) 김시우 README가 요구한 02b 상관쌍 교차검증 수행 (Jun/전성재는 파일 미발견으로 미수행)
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

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
OUT.mkdir(exist_ok=True)

# =============================================================== 김시우 pipeline/config.py
OPCOND = ["Product_ID", "Recipe_ID"]
MAD_SCALE = 1.4826
TREND_ALPHA = 0.05

SUBSYSTEMS = {
    "fdc_laser": ["Laser_Power", "Power_Efficiency", "Laser_Centering_Position",
                  "Laser_Current", "Laser_Voltage", "Beam_Diameter"],
    "fdc_motion": ["Feed_Speed", "Frequency", "Alignment_Time", "Process_Time",
                   "Cutting_X_Index", "Cutting_Y_Index"],
    "fdc_thermal": ["Head_Temp", "Cooling_Flow", "Cooling_Water_Temp", "Focus"],
    "fdc_cleaning": ["CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
                     "Laser_Head_Remain_Time"],
    "fdc_mechanical": ["Vibration"],
    "response": ["Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
                 "Groove_Depth", "Package_Size_1", "Package_Size_2", "Package_Size_3",
                 "Package_Size_4", "Coating_Thickness", "Coating_Uniformity",
                 "Cutting_Offset", "Surface_Roughness"],
}
FDC_COLS = (SUBSYSTEMS["fdc_laser"] + SUBSYSTEMS["fdc_motion"] + SUBSYSTEMS["fdc_thermal"]
            + SUBSYSTEMS["fdc_cleaning"] + SUBSYSTEMS["fdc_mechanical"])
RESPONSES = SUBSYSTEMS["response"]
DOMAIN_FEATURES = ["Cooling_Thermal_Load", "Laser_Cleaning_Demand",
                   "Cleaning_Capacity", "Cleaning_Load_Ratio"]
ALL_FEATURE_COLS = FDC_COLS + RESPONSES + DOMAIN_FEATURES + ["Maintenance_Count"]

EFFECT_SIZE_MIN = 0.2   # Jun 기준
TREE_TOP_N = 10         # Jun 기준


def NORMAL(f):
    return (f["Yield"] == 100) & (f["NG_Code"] == "OK")


def add_domain_features(df):
    r = df.copy()
    r["Cooling_Thermal_Load"] = r["Cooling_Water_Temp"] / r["Cooling_Flow"]
    r["Laser_Cleaning_Demand"] = r["Laser_Power"] * r["Groove_Depth"]
    r["Cleaning_Capacity"] = r["CLN_Flow"] * r["CLN_Pressure"] * r["CLN_Time"]
    r["Cleaning_Load_Ratio"] = r["Laser_Cleaning_Demand"] / r["Cleaning_Capacity"]
    return r


def compute_stratum_baseline_stats(df_normal, stratum_keys, columns):
    """김시우 common.py 동일 구현 (OK행 기준 층별 median/MAD)."""
    grouped = df_normal.groupby(stratum_keys, dropna=False)
    frames = []
    for col in columns:
        g = grouped[col]
        agg = g.agg(n="count", median="median")
        agg["mad"] = g.apply(lambda s: (s - s.median()).abs().median())
        agg["column"] = col
        frames.append(agg.reset_index())
    result = pd.concat(frames, ignore_index=True)
    result["robust_z_scale"] = MAD_SCALE * result["mad"]
    return result[stratum_keys + ["column", "n", "median", "mad", "robust_z_scale"]]


def zscore_transform(df, baseline_long, stratum_keys, columns):
    """김시우 common.py 동일 구현."""
    result = df.copy()
    for col in columns:
        sub = baseline_long.loc[baseline_long["column"] == col,
                                stratum_keys + ["median", "robust_z_scale"]]
        sub = sub.rename(columns={"median": "__median", "robust_z_scale": "__scale"})
        result = result.merge(sub, on=stratum_keys, how="left")
        scale = result["__scale"].where(result["__scale"].abs() > 1e-9)
        result[f"{col}_z"] = (result[col] - result["__median"]) / scale
        result = result.drop(columns=["__median", "__scale"])
    return result


# =============================================================== 도메인 가설표 (Jun 브랜치)
# --------------------------------------------------- CHIP (Jun 원본 그대로 — 수정 없음)
CHIP_DOMAIN = {
    "Groove_Depth": ("가공 깊이 — Depth 부족 시 Low-k 미승화로 Blade 진입 시 Chipping (설계서 C유형 명시)", "down"),
    "Beam_Diameter": ("빔 품질 — 협소 시 Width 감소로 Chipping 증가, 과다 시 Die 영역 침범 (설계서 B유형 명시)", "either"),
    "Kerf_Width_Profile": ("절단 폭 — Beam_Diameter가 만든 결과값, 동일 메커니즘 상속 (설계서 명시)", "either"),
    "Top_Kerf": ("절단 폭 — Kerf_Width_Profile과 동일 메커니즘 상속", "either"),
    "Bottom_Kerf": ("절단 폭 — Kerf_Width_Profile과 동일 메커니즘 상속", "either"),
    "Vibration": ("기계적 불안정 — 스테이지 흔들림으로 나이프 자국형 대형 불량 (설계서 회의록 명시)", "up"),
    "Focus": ("빔 집속 — 헤드온도 변화 시 굴절률 변화로 센터링 불량·Chipping·Depth/Width 이상 (설계서 PDF 명시)", "either"),
    "Head_Temp": ("방열 능력 — Focus 이상을 매개로 간접 연결 (Focus 메커니즘의 상류 원인)", "up"),
    "Cutting_X_Index": ("정렬/센터링 — 목표 절단선 이탈이 모서리 파손 유발 (E유형)", "either"),
    "Cutting_Y_Index": ("정렬/센터링 — 위와 동일", "either"),
    "Cutting_Offset": ("정렬/센터링 — 위와 동일", "either"),
    "Laser_Centering_Position": ("정렬/센터링 — 빔 중심 이탈이 비대칭 절단·모서리 손상 유발", "either"),
    "Kerf_Angle": ("정렬/센터링 — 절단면 수직도 이상이 모서리 파손과 연결 가능", "either"),
    "Package_Size_1": ("정렬 불량 동반지표 — 센터링 틀어짐 시 다이 크기 불균형 동반", "either"),
    "Package_Size_2": ("정렬 불량 동반지표 — 위와 동일", "either"),
    "Package_Size_3": ("정렬 불량 동반지표 — 위와 동일", "either"),
    "Package_Size_4": ("정렬 불량 동반지표 — 위와 동일", "either"),
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하 시 Chipping 위험 증가 (추론)", "down"),
    "Surface_Roughness": ("결과 공변 — 모서리 파손이 거칠기를 높일 가능성, 원인 아닐 수 있음", "up"),
    "Maintenance_Count": ("정비 이력 프록시 (김시우 decision_note가 Goal2 확인 가치 명시)", "either"),
}
CHIP_NOT_RELATED = {
    "Laser_Power": "에너지 투입 계열 — Burn 전용(열 축적), Chipping(기계적 파손)과 연결고리 없음",
    "Power_Efficiency": "에너지 투입 계열 — Burn 전용, Chipping과 연결고리 없음",
    "Feed_Speed": "체류시간 계열 — Burn 전용(열축적), Chipping과 명시적 연결고리 없음",
    "Frequency": "체류시간/열축적 계열 — Burn 전용, Chipping과 무관",
    "Alignment_Time": "체류시간 계열 — Burn 전용, Chipping과 무관",
    "Process_Time": "체류시간 계열 — Burn 전용, Chipping과 무관",
    "Cooling_Flow": "방열 계열 — Burn 전용, Chipping과 연결고리 없음",
    "Cooling_Water_Temp": "방열 계열 — Burn 전용, Chipping과 연결고리 없음",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — Burn 전용, Chipping과 무관",
    "CLN_Flow": "세정 계열 — Particle/Remain_Coat 전용, Chipping과 무관",
    "CLN_Pressure": "세정 계열 — Particle/Remain_Coat 전용, Chipping과 무관",
    "CLN_Time": "세정 계열 — Particle/Remain_Coat 전용, Chipping과 무관",
    "Coating_Flow": "세정/코팅 계열 — Particle/Remain_Coat 전용, Chipping과 무관",
    "Cleaning_Capacity": "팀 공용 피처, 세정 계열 — Chipping과 무관",
    "Cleaning_Load_Ratio": "팀 공용 피처, 세정 계열 — Chipping과 무관",
    "Laser_Cleaning_Demand": "팀 공용 피처, 세정 계열 — Chipping과 무관",
}

# --------------------------------------------------- CRACK (Jun 원본 + 현업 도메인 지식 반영)
# 현업 확인: "Micro_Crack은 레이저 그루빙 공정의 문제가 아니다"
# -> Jun이 DOMAIN_HYPOTHESIS에 넣었던 레이저 그루빙 계열을 전부 NOT_RELATED로 이동한다.
LASER_GROOVING_COLS = [
    "Laser_Power", "Power_Efficiency", "Laser_Current", "Laser_Voltage",
    "Beam_Diameter", "Laser_Centering_Position", "Frequency", "Feed_Speed",
    "Focus", "Head_Temp", "Laser_Head_Remain_Time",
    "Groove_Depth", "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
    "Laser_Cleaning_Demand",
]

CRACK_DOMAIN = {
    # --- 기계적 스트레스 (비-그루빙) : 현업 지식 적용 후 남는 핵심 축
    "Vibration": ("기계적 스트레스 — 진동에 의한 반복 응력이 피로파괴형 미세균열 유발", "up"),
    # --- 방열/열충격 (냉각계통. 레이저 그루빙 제어인자가 아니라 냉각 설비 계통)
    "Cooling_Flow": ("방열 능력 — 냉각 부족 시 급격한 온도구배로 열충격 스트레스 증가", "down"),
    "Cooling_Water_Temp": ("방열 능력 — 냉각수 온도 상승 시 열충격 스트레스 증가", "up"),
    "Cooling_Thermal_Load": ("팀 공용 피처, 방열 능력 — 위와 동일 메커니즘", "up"),
    # --- 누적 스트레스 노출 (모션 계통)
    "Process_Time": ("누적 스트레스 노출 — 공정시간이 길수록 누적 응력 노출 증가", "up"),
    "Alignment_Time": ("누적 스트레스 노출 — 위와 동일", "up"),
    # --- 결과 공변
    "Surface_Roughness": ("결과 공변 — 균열이 표면 거칠기를 바꿀 가능성, 원인 아닐 수 있음", "up"),
    "Maintenance_Count": ("정비 이력 프록시 (김시우 decision_note가 Goal2 확인 가치 명시)", "either"),
}
CRACK_NOT_RELATED = {
    # (A) 현업 도메인 지식으로 신규 제외 — Jun 원본에서는 defect_related였던 항목
    "Laser_Power": "[현업] Micro_Crack은 레이저 그루빙 문제가 아님 — 그루빙 에너지 투입 인자라 제외",
    "Power_Efficiency": "[현업] 레이저 그루빙 제어인자 — 제외",
    "Head_Temp": "[현업] 레이저 헤드 온도 = 그루빙 계통 — 제외",
    "Focus": "[현업] 레이저 빔 집속 = 그루빙 제어인자 — 제외",
    "Beam_Diameter": "[현업] 레이저 빔 직경 = 그루빙 제어인자 — 제외",
    "Laser_Centering_Position": "[현업] 레이저 빔 중심 = 그루빙 제어인자 — 제외",
    "Feed_Speed": "[현업] 그루빙 이송속도 — 제외",
    "Frequency": "[현업] 레이저 펄스 주파수 = 그루빙 제어인자 — 제외 (Jun 원본의 CRACK 1위 인자였음)",
    "Groove_Depth": "[현업] 그루브 깊이 = 그루빙 결과값 — 제외",
    "Laser_Head_Remain_Time": "[현업] 레이저 헤드 수명 = 그루빙 계통 — 제외",
    # (B) Jun 원본에서 이미 not_related였던 항목 (유지)
    "Cutting_X_Index": "정렬/센터링 계열(설계서 E유형) — Chipping 메커니즘, 파단과 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(설계서 E유형) — Chipping 메커니즘, 파단과 무관",
    "Cutting_Offset": "정렬/센터링 계열(설계서 E유형) — Chipping 메커니즘, 파단과 무관",
    "Kerf_Angle": "[현업+Jun] 그루빙 절단면 수직도 — 파단과 무관",
    "Package_Size_1": "정렬/센터링 계열(설계서 E유형) — 파단과 무관",
    "Package_Size_2": "정렬/센터링 계열(설계서 E유형) — 파단과 무관",
    "Package_Size_3": "정렬/센터링 계열(설계서 E유형) — 파단과 무관",
    "Package_Size_4": "정렬/센터링 계열(설계서 E유형) — 파단과 무관",
    "Kerf_Width_Profile": "[현업+Jun] 그루빙 절단 폭 — 파단과 별개 메커니즘",
    "Top_Kerf": "[현업+Jun] 그루빙 절단 폭 — 파단과 무관",
    "Bottom_Kerf": "[현업+Jun] 그루빙 절단 폭 — 파단과 무관",
    "CLN_Flow": "세정 계열 — Particle/Remain_Coat 전용, 파단과 무관",
    "CLN_Pressure": "세정 계열 — Particle/Remain_Coat 전용, 파단과 무관",
    "CLN_Time": "세정 계열 — Particle/Remain_Coat 전용, 파단과 무관",
    "Coating_Flow": "세정/코팅 계열 — Particle/Remain_Coat 전용, 파단과 무관",
    "Cleaning_Capacity": "팀 공용 피처, 세정 계열 — 파단과 무관",
    "Cleaning_Load_Ratio": "팀 공용 피처, 세정 계열 — 파단과 무관",
    "Laser_Cleaning_Demand": "[현업+Jun] 그루빙 파생피처(Laser_Power×Groove_Depth) — 제외",
}

TEAM_UNDETERMINED_COMMON = {
    "Laser_Current": "설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Laser_Voltage": "설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Coating_Thickness": "설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실, 팀 미확정",
    "Coating_Uniformity": "설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실, 팀 미확정",
}

TARGETS = {
    "CHIP": {"ng_code": "CHIP", "binary": "Chipping",
             "domain": CHIP_DOMAIN, "not_related": CHIP_NOT_RELATED,
             "undetermined": {k: v for k, v in TEAM_UNDETERMINED_COMMON.items()}},
    "CRACK": {"ng_code": "CRACK", "binary": "Micro_Crack",
              "domain": CRACK_DOMAIN, "not_related": CRACK_NOT_RELATED,
              "undetermined": {k: v for k, v in TEAM_UNDETERMINED_COMMON.items()
                               if k in ("Coating_Thickness", "Coating_Uniformity")}},
}


def make_domain_info(spec):
    def domain_info(column):
        if column in spec["domain"]:
            mech, direction = spec["domain"][column]
            return mech, direction, True, "defect_related"
        if column in spec["not_related"]:
            return spec["not_related"][column], "not_applicable", False, "not_related_to_defect"
        if column in spec["undetermined"]:
            return spec["undetermined"][column], "unknown", False, "team_undetermined"
        return "미분류 — 검토 필요", "unknown", False, "unclassified"
    return domain_info


# =============================================================== 0단계: 데이터 로드/통합
print("[0] 데이터 로드 및 통합 (원본 + r1)")
o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["DateTime"] = pd.to_datetime(df["DateTime"])
df["is_normal"] = NORMAL(df)
df = add_domain_features(df)
print(f"    통합 {len(df):,}행 (original {len(o):,} + r1 {len(r):,}), 정상군 {df.is_normal.sum():,}건")

# 김시우 방식: OK행 기준 OPCOND 층 baseline -> 강건 z-score
print("[0] OPCOND 층 baseline 산출 및 강건 z-score 변환 (김시우 pipeline 방식)")
baseline = compute_stratum_baseline_stats(df[df.is_normal], OPCOND, ALL_FEATURE_COLS)
baseline.to_csv(OUT / "00_stratum_baseline_by_opcond_combined.csv",
                index=False, encoding="utf-8-sig")
df = zscore_transform(df, baseline, OPCOND, ALL_FEATURE_COLS)

summary = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "n_rows": int(len(df)), "n_normal": int(df.is_normal.sum()),
           "method": "김시우 pipeline 전처리 + Jun 유효인자 방법론 (전성재 방법론 미사용)",
           "targets": {}}

all_final = {}

for tname, spec in TARGETS.items():
    print(f"\n{'='*76}\n### TARGET: {tname}\n{'='*76}")
    lab_p, lab_b = f"is_{tname.lower()}_primary", f"is_{tname.lower()}_broad"
    df[lab_p] = df["NG_Code"] == spec["ng_code"]
    df[lab_b] = df[spec["binary"]] == 1
    LABELS = [lab_p, lab_b]
    print(f"  primary({spec['ng_code']}) = {df[lab_p].sum():,}건 | "
          f"broad({spec['binary']}==1) = {df[lab_b].sum():,}건")

    # ---------- 1단계: 발생률 sanity check (Jun 방식)
    frames = []
    for keys in [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], ["source_dataset"], OPCOND]:
        g = df.groupby(keys)[lab_p].agg(n="count", n_defect="sum", rate="mean").reset_index()
        g["stratum_type"] = "+".join(keys)
        if len(keys) == 1:
            g = g.rename(columns={keys[0]: "stratum_value"})
        else:
            g["stratum_value"] = g[keys].astype(str).agg("|".join, axis=1)
            g = g.drop(columns=keys)
        frames.append(g[["stratum_type", "stratum_value", "n", "n_defect", "rate"]])
    pd.concat(frames, ignore_index=True).to_csv(
        OUT / f"01_{tname.lower()}_rate_by_stratum.csv", index=False, encoding="utf-8-sig")

    # ---------- 2단계: Mann-Whitney U + BH-FDR + Cliff's delta (Jun 방식)
    print("  [2] Mann-Whitney U + BH-FDR + Cliff's delta")
    rows = []
    for label in LABELS:
        for col in ALL_FEATURE_COLS:
            gv = df.loc[df[label], f"{col}_z"].dropna()
            rv = df.loc[~df[label], f"{col}_z"].dropna()
            if len(gv) < 3 or len(rv) < 3:
                u = p = d = np.nan
            else:
                u, p = scipy_stats.mannwhitneyu(gv, rv, alternative="two-sided")
                d = (2 * u) / (len(gv) * len(rv)) - 1
            rows.append({"label": label, "column": col, "n_group": int(df[label].sum()),
                         "n_rest": int((~df[label]).sum()),
                         "median_z_group": gv.median(), "median_z_rest": rv.median(),
                         "u_stat": u, "p_value": p, "cliffs_delta": d})
    uni = pd.DataFrame(rows)
    uni["p_fdr"] = np.nan; uni["fdr_significant"] = False
    for label, idx in uni.groupby("label").groups.items():
        rej, padj, _, _ = multipletests(uni.loc[idx, "p_value"].fillna(1.0),
                                        alpha=TREND_ALPHA, method="fdr_bh")
        uni.loc[idx, "p_fdr"] = padj
        uni.loc[idx, "fdr_significant"] = rej
    uni["effect_size_pass"] = uni["cliffs_delta"].abs() >= EFFECT_SIZE_MIN
    uni["univariate_flag"] = uni["fdr_significant"] & uni["effect_size_pass"]
    uni.to_csv(OUT / f"02_{tname.lower()}_univariate_test_results.csv",
               index=False, encoding="utf-8-sig")

    # ---------- 3단계: RandomForest permutation importance (Jun 방식)
    print("  [3] RandomForest(200, depth8, balanced) + permutation importance(AP, 15회)")
    feat_z = [f"{c}_z" for c in ALL_FEATURE_COLS]
    trows = []
    for label in LABELS:
        tr, te = train_test_split(df, test_size=0.2, random_state=42, stratify=df[label])
        model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                       class_weight="balanced", random_state=42, n_jobs=-1)
        model.fit(tr[feat_z], tr[label].astype(int))
        # 200,000행 규모라 permutation 대상 test셋을 20,000으로 서브샘플 (Jun의 n_repeats=15 유지)
        te_s = te.sample(n=min(20000, len(te)), random_state=42)
        perm = permutation_importance(model, te_s[feat_z], te_s[label].astype(int),
                                      scoring="average_precision", n_repeats=15,
                                      random_state=42, n_jobs=-1)
        lr_ = pd.DataFrame({"label": label, "column": ALL_FEATURE_COLS,
                            "importance_mean": perm.importances_mean,
                            "importance_std": perm.importances_std})
        lr_["rank"] = lr_["importance_mean"].rank(ascending=False, method="min").astype(int)
        lr_["tree_flag"] = (lr_["rank"] <= TREE_TOP_N) & (lr_["importance_mean"] > 0)
        trows.append(lr_)
    tree = pd.concat(trows, ignore_index=True)
    tree.to_csv(OUT / f"03_{tname.lower()}_tree_importance.csv",
                index=False, encoding="utf-8-sig")

    # ---------- 4단계: 도메인 + 통계 병합, verdict (Jun 방식)
    print("  [4] 도메인 가설 + 통계 교차검증 병합")
    uw = uni.pivot(index="column", columns="label",
                   values=["p_fdr", "cliffs_delta", "univariate_flag"])
    uw.columns = [f"{m}_{l}" for m, l in uw.columns]; uw = uw.reset_index()
    tw = tree.pivot(index="column", columns="label",
                    values=["importance_mean", "rank", "tree_flag"])
    tw.columns = [f"{m}_{l}" for m, l in tw.columns]; tw = tw.reset_index()
    m = uw.merge(tw, on="column", how="outer")

    ufc = [f"univariate_flag_{l}" for l in LABELS]
    tfc = [f"tree_flag_{l}" for l in LABELS]
    for c in ufc + tfc:
        m[c] = m[c].infer_objects(copy=False).fillna(False).astype(bool)
    m["univariate_any_label"] = m[ufc].any(axis=1)
    m["tree_any_label"] = m[tfc].any(axis=1)
    m["n_methods_agree"] = m["univariate_any_label"].astype(int) + m["tree_any_label"].astype(int)
    m["n_labels_univariate_flag"] = m[ufc].sum(axis=1).astype(int)
    m["n_labels_tree_flag"] = m[tfc].sum(axis=1).astype(int)

    dinfo = make_domain_info(spec)
    dl = m["column"].map(dinfo)
    m["domain_mechanism"] = dl.map(lambda t: t[0])
    m["domain_direction_hypothesis"] = dl.map(lambda t: t[1])
    m["has_domain_support"] = dl.map(lambda t: t[2])
    m["domain_status"] = dl.map(lambda t: t[3])
    m["subsystem"] = m["column"].map(
        lambda c: next((s for s, cols in SUBSYSTEMS.items() if c in cols), "engineered"))
    m["is_laser_grooving"] = m["column"].isin(LASER_GROOVING_COLS)

    def verdict(row):
        if row["n_methods_agree"] >= 2 and row["has_domain_support"]:
            return "confirmed"
        if row["n_methods_agree"] >= 2 and not row["has_domain_support"]:
            return "candidate_needs_domain_review"
        if row["n_methods_agree"] == 1 and row["has_domain_support"]:
            return "candidate_weak_signal"
        return "insufficient_evidence"

    m["verdict"] = m.apply(verdict, axis=1)
    order = {"confirmed": 0, "candidate_needs_domain_review": 1,
             "candidate_weak_signal": 2, "insufficient_evidence": 3}
    m["_o"] = m["verdict"].map(order)
    m = m.sort_values(["_o", f"importance_mean_{lab_p}"],
                      ascending=[True, False]).drop(columns="_o")
    m.to_csv(OUT / f"04_{tname.lower()}_influence_factors_final.csv",
             index=False, encoding="utf-8-sig")
    all_final[tname] = m

    print(f"\n  --- {tname} 판정 결과 ---")
    for v in ["confirmed", "candidate_needs_domain_review", "candidate_weak_signal"]:
        sub = m[m.verdict == v]
        if len(sub) == 0:
            continue
        print(f"  [{v}] {len(sub)}건")
        for _, x in sub.iterrows():
            groov = " *그루빙*" if x["is_laser_grooving"] else ""
            print(f"     {x['column']:24s} delta_p={x[f'cliffs_delta_{lab_p}']:+.3f} "
                  f"delta_b={x[f'cliffs_delta_{lab_b}']:+.3f} "
                  f"imp={x[f'importance_mean_{lab_p}']:+.5f} "
                  f"rank={x[f'rank_{lab_p}']:>2.0f}{groov}")
    summary["targets"][tname] = {
        "n_primary": int(df[lab_p].sum()), "n_broad": int(df[lab_b].sum()),
        "confirmed": m.loc[m.verdict == "confirmed", "column"].tolist(),
        "needs_domain_review": m.loc[m.verdict == "candidate_needs_domain_review",
                                     "column"].tolist(),
    }

with open(OUT / "00_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("\n완료 —", OUT)
