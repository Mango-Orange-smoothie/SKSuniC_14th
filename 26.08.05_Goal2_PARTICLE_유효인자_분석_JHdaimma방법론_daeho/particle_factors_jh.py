"""Goal2 — PARTICLE 유효인자 발굴 (진혁님 방법론 이식, 원본 + r1 통합 200,000행)

[방법론 출처]
  진혁님(JHdaimma) 브랜치
    26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/analysis_v2_kimsiwoo_jun/
      chip_crack_factors_v2.py     <- 이 파일의 뼈대. 통계 로직 전부 그대로.
      supplement_crossvalidation.py <- 08_reproducibility 산출 방식
      baseline_sensitivity_check.py <- 09_baseline_sensitivity 산출 방식
    SHAP_판정제외_근거.md (26.08.03)
      -> SHAP은 유효인자 판정에서 제외. 판정은 통계검정 + RandomForest 2방법만 사용.
         (4개 defect 전체에서 SHAP 오탐 24건 vs 누락 1건)

  진혁님 스크립트가 김시우님/승준님 브랜치에서 가져온 것도 그대로 승계한다:
    [김시우] OPCOND/NORMAL/SUBSYSTEMS, OK행 기준 층별 median/MAD 강건 z-score
    [승준]   이중 라벨(primary=NG_Code, broad=이진컬럼),
             Mann-Whitney U + BH-FDR + Cliff's delta(>=0.2),
             RandomForest(200, depth8, balanced) + permutation_importance(AP, 15회) top-10,
             verdict 로직(confirmed / candidate_needs_domain_review /
                          candidate_weak_signal / insufficient_evidence)

[이번 분석에서 새로 채운 것]
  1) TARGET = PARTICLE. 도메인 가설표는 승준님
     26.07.30_2055_Goal2_PARTICLE_유효인자_분석/DOMAIN_KNOWLEDGE.md 3/5/6절을 그대로 옮겼다
     (defect_related 19 + not_related 17 + team_undetermined 4 = 40, ALL_FEATURE_COLS와 정확히 일치).
     ※ 승준님 문서 본문은 "18개"라고 적었으나 표에는 19개다(Maintenance_Count 포함 여부 차이).
  2) 비교군 4종 대조표(10_comparison_group_contrast.csv) 추가.
     진혁님 방법의 비교군은 `~label`(정상 + 다른 불량 전부)이고, 대호님 규약은
     정상군 = NG_Code=='OK'다. 승준님 방법 G는 pure vs ~pure를 쓴다.
     어느 것을 쓰느냐로 r1 결과의 부호가 갈리므로 넷을 같은 표에 병기한다.
     **판정(verdict)은 진혁님 방법(`~label`) 기준으로만 낸다. 나머지는 대조용이다.**

[환경 호환성 때문에 손댄 2곳 — 통계 로직 아님]
  1) pandas 3.0에서 제거된 infer_objects(copy=False) -> fillna(False).astype(bool)
  2) RandomForest는 NaN/inf를 못 받는다. RF 입력에 한해 개수를 세어 0으로 치환한다
     (= "그 층 정상 중앙값과 같음", 중립값). 통계검정은 순위 기반이라 원값 그대로 사용.

실행 (이 폴더 안에서):
    py -3 particle_factors_jh.py                 # PARTICLE (기본)
    py -3 particle_factors_jh.py --target CHIP   # 진혁님 산출물 대조용
    py -3 particle_factors_jh.py --data <CSV폴더>

데이터 CSV 2개는 기본적으로 이 폴더의 상위에서 찾는다(`--data` 또는 환경변수
DP_DATA_DIR로 지정 가능). 용량 때문에 커밋하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument("--target", default="PARTICLE", choices=["PARTICLE", "CHIP"])
parser.add_argument("--data", default=None, help="두 CSV가 있는 폴더")
args = parser.parse_args()

DATA = Path(args.data).expanduser() if args.data else (
    Path(os.environ["DP_DATA_DIR"]).expanduser() if os.environ.get("DP_DATA_DIR")
    else HERE.parent)

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

ALL_DEFECT_BIN_COLS = ["Chipping", "Remain_Coat", "Particle", "Micro_Crack"]

EFFECT_SIZE_MIN = 0.2   # 승준님 기준
TREE_TOP_N = 10         # 승준님 기준


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


def cliffs(a, b):
    """Mann-Whitney U -> Cliff's delta. (2U)/(n1*n2) - 1"""
    a = pd.Series(a).dropna()
    b = pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


# ====================================================== 도메인 가설표 — PARTICLE
# 출처: 승준님 26.07.30_2055_Goal2_PARTICLE_유효인자_분석/DOMAIN_KNOWLEDGE.md
#       3절(메커니즘별 가설) / 5절(무관 판단) / 6절(팀 미확정)
# 대호님 후속검증(26.07.31_2058)이 세정계 4개를 기각했지만, 가설표에서는 빼지 않는다 —
# 통계가 독립적으로 재기각하는지 보기 위함. 결과표에 daeho_followup_status로 병기한다.
PARTICLE_DOMAIN = {
    # 에너지 투입 (어블레이션량 = 디브리 소스)
    "Laser_Power": ("에너지 투입 — 에너지↑ → 제거 재질량↑ → 디브리 소스", "up"),
    "Power_Efficiency": ("에너지 변환 이상 — 효율 이상 시 비정상 어블레이션 가능성", "either"),
    # 빔 품질/집속
    "Focus": ("빔 품질/집속 — 빔 이상 시 비정상 어블레이션(스패터) 증가 가능성", "either"),
    "Beam_Diameter": ("빔 품질/집속 — 위와 동일 메커니즘", "either"),
    # 세정 능력 (Particle의 1차 메커니즘)
    "CLN_Flow": ("세정 능력 — 세정 부족 시 디브리 잔류 (Particle의 1차 메커니즘)", "down"),
    "CLN_Pressure": ("세정 능력 — 위와 동일", "down"),
    "CLN_Time": ("세정 능력 — 위와 동일", "down"),
    # 코팅
    "Coating_Flow": ("코팅 이슈 — 코팅 불균일 → 박리가 particle 소스 가능성(약한 가설)", "down"),
    # 헤드 노후
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하 → 스패터 증가 가능성", "down"),
    # 기계적 진동
    "Vibration": ("기계적 진동 — 진동 → 디브리 비산/재부착", "up"),
    # 가공 제거량
    "Groove_Depth": ("가공 제거량 — 더 깊게 깎을수록 디브리 발생량 증가", "up"),
    "Kerf_Width_Profile": ("가공 제거량 — 더 넓게 깎을수록 디브리 발생량 증가", "up"),
    "Top_Kerf": ("가공 제거량 — 위와 동일", "up"),
    "Bottom_Kerf": ("가공 제거량 — 위와 동일", "up"),
    # 결과 공변
    "Surface_Roughness": ("결과 공변 — particle이 표면에 남아 거칠기 상승. 원인 아니라 증상", "up"),
    # 팀 공용 파생 피처
    "Laser_Cleaning_Demand": ("팀 공용 피처 — 디브리 발생 수요(Laser_Power x Groove_Depth)", "up"),
    "Cleaning_Capacity": ("팀 공용 피처 — 세정 능력(CLN_Flow x CLN_Pressure x CLN_Time)", "down"),
    "Cleaning_Load_Ratio": ("팀 공용 피처 — 수요/능력 밸런스(승준님 핵심 가설)", "up"),
    # 정비 이력
    "Maintenance_Count": ("정비 이력 프록시 — 김시우님 decision_note가 Goal2 확인 가치 명시", "either"),
}
PARTICLE_NOT_RELATED = {
    # 정렬/센터링 계열 (설계서 E유형) — 알려진 실패모드는 Chipping, 디브리 발생과 무관
    "Laser_Centering_Position": "정렬/센터링 계열(E유형) — Chipping 메커니즘, 디브리 발생과 무관",
    "Cutting_X_Index": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Cutting_Offset": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Kerf_Angle": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Package_Size_1": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Package_Size_2": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Package_Size_3": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    "Package_Size_4": "정렬/센터링 계열(E유형) — 디브리 발생과 무관",
    # 방열/체류시간 계열 — BURN의 열 축적 메커니즘 전용. Particle은 물질 문제이지 열 문제 아님
    "Head_Temp": "방열 계열 — 열 축적 메커니즘 전용, Particle은 물질(디브리) 문제",
    "Cooling_Flow": "방열 계열 — 위와 동일",
    "Cooling_Water_Temp": "방열 계열 — 위와 동일",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — 위와 동일",
    "Frequency": "체류시간/열축적 계열 — 위와 동일",
    "Alignment_Time": "체류시간 계열 — 위와 동일",
    "Process_Time": "체류시간 계열 — 위와 동일",
    "Feed_Speed": "체류시간 계열 — 위와 동일",
}

# ====================================================== 도메인 가설표 — CHIP (이식 검증용)
# 진혁님 chip_crack_factors_v2.py 원문 그대로. --target CHIP 실행 시에만 사용한다.
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

TEAM_UNDETERMINED_COMMON = {
    "Laser_Current": "설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Laser_Voltage": "설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Coating_Thickness": "설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실, 팀 미확정",
    "Coating_Uniformity": "설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실, 팀 미확정",
}

# 대호님 26.07.31_2058 후속검증 결론 (주석 컬럼용, 판정에는 영향 없음)
DAEHO_FOLLOWUP = {
    "Vibration": "검증1·5: 유일한 원인 후보. 선행신호 잔존율 33.5%, 층 무관 강건(축소 2.3%)",
    "Surface_Roughness": "검증1: 결과 공변 확정 — 선행신호 잔존율 7.5%. 원인 아님, 탐지지표로만",
    "CLN_Pressure": "검증4: 기각 — particle 단독군 delta -0.002, REM_COAT 전용(-0.536)",
    "CLN_Flow": "검증4: 기각 — particle 단독군 delta -0.005",
    "Cleaning_Capacity": "검증4: 기각 — particle 단독군 delta -0.004",
    "Cleaning_Load_Ratio": "검증3·4: 기각 — 비율 정의 4종 전부 무신호(최대 |delta| 0.012)",
}

TARGETS = {
    "PARTICLE": {"ng_code": "PARTICLE", "binary": "Particle",
                 "domain": PARTICLE_DOMAIN, "not_related": PARTICLE_NOT_RELATED,
                 "undetermined": TEAM_UNDETERMINED_COMMON},
    "CHIP": {"ng_code": "CHIP", "binary": "Chipping",
             "domain": CHIP_DOMAIN, "not_related": CHIP_NOT_RELATED,
             "undetermined": TEAM_UNDETERMINED_COMMON},
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
TNAME = args.target
SPEC = TARGETS[TNAME]
LOW = TNAME.lower()

print(f"[0] 데이터 로드 및 통합 (원본 + r1)  |  TARGET = {TNAME}")
o = pd.read_csv(DATA / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(DATA / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["DateTime"] = pd.to_datetime(df["DateTime"])
df["is_normal"] = NORMAL(df)
df = add_domain_features(df)
print(f"    통합 {len(df):,}행 (original {len(o):,} + r1 {len(r):,}), 정상군 {df.is_normal.sum():,}건")

print("[0] OPCOND 층 baseline 산출 및 강건 z-score 변환 (김시우 pipeline 방식)")
baseline = compute_stratum_baseline_stats(df[df.is_normal], OPCOND, ALL_FEATURE_COLS)
baseline.to_csv(OUT / "00_stratum_baseline_by_opcond_combined.csv",
                index=False, encoding="utf-8-sig")
df = zscore_transform(df, baseline, OPCOND, ALL_FEATURE_COLS)

FEAT_Z = [f"{c}_z" for c in ALL_FEATURE_COLS]

# --- 라벨 정의 (승준님 이중 라벨 + 승준님 통합본의 pure/keep)
lab_p, lab_b = f"is_{LOW}_primary", f"is_{LOW}_broad"
df[lab_p] = df["NG_Code"] == SPEC["ng_code"]
df[lab_b] = df[SPEC["binary"]] == 1
LABELS = [lab_p, lab_b]

others = [c for c in ALL_DEFECT_BIN_COLS if c != SPEC["binary"]]
broad_mask = df[lab_b]
pure_mask = broad_mask & (df[others] == 0).all(axis=1)
# 승준님 unified_full_methodology.py:498 — "이 defect는 없는데 다른 defect가 있는" 오염행 제외
keep_mask = ~(~broad_mask & (df[others] == 1).any(axis=1))
ok_mask = df["NG_Code"] == "OK"

print(f"    primary({SPEC['ng_code']}) = {df[lab_p].sum():,}건 | "
      f"broad({SPEC['binary']}==1) = {df[lab_b].sum():,}건 | "
      f"pure = {int(pure_mask.sum()):,}건 | 정상(OK) = {int(ok_mask.sum()):,}건")

# --- 라벨 등가식 점검 (대호님 원본 분석의 assert를 건수 기록으로 대체)
label_audit = {}
for ds in ["original", "r1"]:
    sub = df.source_dataset == ds
    a = sub & df[lab_p]
    b = sub & pure_mask
    mismatch = int((a ^ b).sum())
    codes = df.loc[sub & (a ^ b), "NG_Code"].value_counts().to_dict()
    label_audit[ds] = {"n_primary": int(a.sum()), "n_pure": int(b.sum()),
                       "mismatch": mismatch,
                       "mismatch_ng_code": {str(k): int(v) for k, v in codes.items()}}
    print(f"    [라벨 점검/{ds}] primary={int(a.sum()):,} pure={int(b.sum()):,} "
          f"불일치={mismatch:,} {codes if mismatch else ''}")

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "target": TNAME,
    "n_rows": int(len(df)), "n_normal": int(df.is_normal.sum()),
    "n_features": len(ALL_FEATURE_COLS),
    "method": ("진혁님(JHdaimma) chip_crack_factors_v2.py 방법론 이식 — "
               "김시우 전처리 + 승준 통계방법론, SHAP 미사용(진혁님 08-03 결정)"),
    "label_equivalence_audit": label_audit,
}

# =============================================================== 1단계: 발생률 sanity check
print("  [1] 발생률 sanity check")
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
    OUT / f"01_{LOW}_rate_by_stratum.csv", index=False, encoding="utf-8-sig")

# =============================================================== 2단계: 단변량 (진혁님 방식 그대로)
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
uni["p_fdr"] = np.nan
uni["fdr_significant"] = False
for label, idx in uni.groupby("label").groups.items():
    rej, padj, _, _ = multipletests(uni.loc[idx, "p_value"].fillna(1.0),
                                    alpha=TREND_ALPHA, method="fdr_bh")
    uni.loc[idx, "p_fdr"] = padj
    uni.loc[idx, "fdr_significant"] = rej
uni["effect_size_pass"] = uni["cliffs_delta"].abs() >= EFFECT_SIZE_MIN
uni["univariate_flag"] = uni["fdr_significant"] & uni["effect_size_pass"]
uni.to_csv(OUT / f"02_{LOW}_univariate_test_results.csv", index=False, encoding="utf-8-sig")

# =============================================================== 3단계: RandomForest
print("  [3] RandomForest(200, depth8, balanced) + permutation importance(AP, 15회)")
X_all = df[FEAT_Z]
n_nan = int(X_all.isna().to_numpy().sum())
n_inf = int(np.isinf(X_all.to_numpy(dtype="float64", na_value=0.0)).sum())
if n_nan or n_inf:
    print(f"      [환경] RF 입력 NaN {n_nan:,}개 / inf {n_inf:,}개 -> 0으로 치환 "
          f"(통계검정은 원값 사용)")
summary["rf_input_cleanup"] = {"n_nan_replaced": n_nan, "n_inf_replaced": n_inf}
X_rf = X_all.replace([np.inf, -np.inf], np.nan).fillna(0.0)

trows = []
for label in LABELS:
    idx_tr, idx_te = train_test_split(np.arange(len(df)), test_size=0.2,
                                      random_state=42, stratify=df[label].to_numpy())
    y = df[label].astype(int).to_numpy()
    model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                   class_weight="balanced", random_state=42, n_jobs=-1)
    model.fit(X_rf.iloc[idx_tr], y[idx_tr])
    # 200,000행 규모라 permutation 대상 test셋을 20,000으로 서브샘플 (진혁님 주석 그대로)
    rng = np.random.default_rng(42)
    sub = rng.choice(idx_te, size=min(20000, len(idx_te)), replace=False)
    perm = permutation_importance(model, X_rf.iloc[sub], y[sub],
                                  scoring="average_precision", n_repeats=15,
                                  random_state=42, n_jobs=-1)
    lr_ = pd.DataFrame({"label": label, "column": ALL_FEATURE_COLS,
                        "importance_mean": perm.importances_mean,
                        "importance_std": perm.importances_std})
    lr_["rank"] = lr_["importance_mean"].rank(ascending=False, method="min").astype(int)
    lr_["tree_flag"] = (lr_["rank"] <= TREE_TOP_N) & (lr_["importance_mean"] > 0)
    trows.append(lr_)
tree = pd.concat(trows, ignore_index=True)
tree.to_csv(OUT / f"03_{LOW}_tree_importance.csv", index=False, encoding="utf-8-sig")

# =============================================================== 4단계: 도메인 + 통계 병합
print("  [4] 도메인 가설 + 통계 교차검증 병합")
uw = uni.pivot(index="column", columns="label",
               values=["p_fdr", "cliffs_delta", "univariate_flag"])
uw.columns = [f"{m}_{l}" for m, l in uw.columns]
uw = uw.reset_index()
tw = tree.pivot(index="column", columns="label",
                values=["importance_mean", "rank", "tree_flag"])
tw.columns = [f"{m}_{l}" for m, l in tw.columns]
tw = tw.reset_index()
m = uw.merge(tw, on="column", how="outer")

ufc = [f"univariate_flag_{l}" for l in LABELS]
tfc = [f"tree_flag_{l}" for l in LABELS]
for c in ufc + tfc:
    # 진혁님 원문은 infer_objects(copy=False) — pandas 3.0에서 copy 인자 제거됨
    m[c] = m[c].fillna(False).astype(bool)
m["univariate_any_label"] = m[ufc].any(axis=1)
m["tree_any_label"] = m[tfc].any(axis=1)
m["n_methods_agree"] = m["univariate_any_label"].astype(int) + m["tree_any_label"].astype(int)
m["n_labels_univariate_flag"] = m[ufc].sum(axis=1).astype(int)
m["n_labels_tree_flag"] = m[tfc].sum(axis=1).astype(int)

dinfo = make_domain_info(SPEC)
dl = m["column"].map(dinfo)
m["domain_mechanism"] = dl.map(lambda t: t[0])
m["domain_direction_hypothesis"] = dl.map(lambda t: t[1])
m["has_domain_support"] = dl.map(lambda t: t[2])
m["domain_status"] = dl.map(lambda t: t[3])
m["subsystem"] = m["column"].map(
    lambda c: next((s for s, cols in SUBSYSTEMS.items() if c in cols), "engineered"))
m["daeho_followup_status"] = m["column"].map(DAEHO_FOLLOWUP).fillna("")


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
m.to_csv(OUT / f"04_{LOW}_influence_factors_final.csv", index=False, encoding="utf-8-sig")

print(f"\n  --- {TNAME} 판정 결과 ---")
for v in ["confirmed", "candidate_needs_domain_review", "candidate_weak_signal"]:
    sub = m[m.verdict == v]
    if len(sub) == 0:
        continue
    print(f"  [{v}] {len(sub)}건")
    for _, x in sub.iterrows():
        print(f"     {x['column']:24s} delta_p={x[f'cliffs_delta_{lab_p}']:+.3f} "
              f"delta_b={x[f'cliffs_delta_{lab_b}']:+.3f} "
              f"imp={x[f'importance_mean_{lab_p}']:+.5f} "
              f"rank={x[f'rank_{lab_p}']:>2.0f}")

summary["verdicts"] = {
    "n_primary": int(df[lab_p].sum()), "n_broad": int(df[lab_b].sum()),
    "n_pure": int(pure_mask.sum()),
    "confirmed": m.loc[m.verdict == "confirmed", "column"].tolist(),
    "needs_domain_review": m.loc[m.verdict == "candidate_needs_domain_review", "column"].tolist(),
    "weak_signal": m.loc[m.verdict == "candidate_weak_signal", "column"].tolist(),
}

# =============================================================== 08: 원본/r1 재현성
# 진혁님 supplement_crossvalidation.py 3) 과 동일 방식 (broad 라벨 vs ~broad)
print("\n  [8] 원본/r1 재현성 (진혁님 supplement_crossvalidation.py 방식)")
rr = []
for c in ALL_FEATURE_COLS:
    vals = {}
    for ds in ["original", "r1"]:
        s = df.source_dataset == ds
        d, _ = cliffs(df.loc[s & broad_mask, f"{c}_z"], df.loc[s & ~broad_mask, f"{c}_z"])
        vals[ds] = d
    dall, _ = cliffs(df.loc[broad_mask, f"{c}_z"], df.loc[~broad_mask, f"{c}_z"])
    rr.append({"target": TNAME, "column": c,
               "delta_original": round(float(vals["original"]), 4),
               "delta_r1": round(float(vals["r1"]), 4),
               "delta_combined": round(float(dall), 4)})
repro = pd.DataFrame(rr).sort_values("delta_combined", key=abs, ascending=False)
repro.to_csv(OUT / f"08_reproducibility_{LOW}.csv", index=False, encoding="utf-8-sig")
print(repro.head(8).to_string(index=False))

# =============================================================== 09: baseline 민감도
# 진혁님 baseline_sensitivity_check.py 방식 — (B)통합 OK baseline vs (C)전체행 baseline
print("\n  [9] baseline 민감도 (통합OK[사용] vs 전체행)")
dfC = df.copy()
gC = df.groupby(OPCOND, observed=True)
for c in ALL_FEATURE_COLS:
    med = gC[c].transform("median")
    mad = gC[c].transform(lambda s: np.median(np.abs(s - np.median(s))))
    sc = (mad * MAD_SCALE).where(lambda s: s > 1e-12, 1.0)
    dfC[f"{c}_z"] = (df[c] - med) / sc

srows = []
for c in ALL_FEATURE_COLS:
    b, _ = cliffs(df.loc[broad_mask, f"{c}_z"], df.loc[~broad_mask, f"{c}_z"])
    cc, _ = cliffs(dfC.loc[broad_mask, f"{c}_z"], dfC.loc[~broad_mask, f"{c}_z"])
    srows.append({"case": f"{TNAME} broad", "column": c,
                  "delta_B_combined_ok_used": round(float(b), 4),
                  "delta_C_all_rows": round(float(cc), 4),
                  "verdict_changed": bool((abs(b) >= EFFECT_SIZE_MIN) != (abs(cc) >= EFFECT_SIZE_MIN))})
sens = pd.DataFrame(srows)
sens.to_csv(OUT / f"09_baseline_sensitivity_{LOW}.csv", index=False, encoding="utf-8-sig")
n_chg = int(sens.verdict_changed.sum())
print(f"      baseline 선택으로 판정이 바뀐 인자: {n_chg}건")
summary["baseline_sensitivity_verdict_changed"] = n_chg

# =============================================================== 10: 비교군 4종 대조 (신규)
print("\n  [10] 비교군 4종 대조 — 팀 간 숫자 불일치의 원인 규명")
VARIANTS = {
    # (이름, 불량군 마스크, 비교군 마스크, 설명)
    "A_jh_primary_vs_rest": (df[lab_p], ~df[lab_p],
                             "진혁님 방법 — 비교군 = 정상 + 다른 불량 전부 (판정 근거)"),
    "B_jun_pure_vs_notpure": (pure_mask, ~pure_mask,
                              "승준님 방법 G — unified_full_methodology.py:253"),
    "C_keep_pure_vs_clean": (pure_mask, keep_mask & ~pure_mask,
                             "keep 마스크 보정 — 다른 defect 있는 행 제외 (:498의 keep)"),
    "D_primary_vs_ok_only": (df[lab_p], ok_mask,
                             "대호님 규약 — 정상군 = NG_Code=='OK'"),
}
crows = []
for ds in ["original", "r1", "combined"]:
    s = pd.Series(True, index=df.index) if ds == "combined" else (df.source_dataset == ds)
    for vname, (gm, rm, note) in VARIANTS.items():
        for c in ALL_FEATURE_COLS:
            d, p = cliffs(df.loc[s & gm, f"{c}_z"], df.loc[s & rm, f"{c}_z"])
            crows.append({"dataset": ds, "variant": vname, "column": c,
                          "n_group": int((s & gm).sum()), "n_rest": int((s & rm).sum()),
                          "cliffs_delta": None if pd.isna(d) else round(float(d), 4),
                          "p_value": None if pd.isna(p) else float(p),
                          "note": note})
contrast = pd.DataFrame(crows)
contrast.to_csv(OUT / f"10_comparison_group_contrast_{LOW}.csv", index=False, encoding="utf-8-sig")

piv = (contrast[contrast.column == "Vibration"]
       .pivot(index="variant", columns="dataset", values="cliffs_delta")
       .reindex(columns=["original", "r1", "combined"]))
print(f"\n      Vibration — 비교군별 Cliff's delta ({TNAME})")
print(piv.to_string())
summary["vibration_by_comparison_group"] = {
    v: {k: (None if pd.isna(x) else float(x)) for k, x in row.items()}
    for v, row in piv.iterrows()
}

with open(OUT / f"00_summary_{LOW}.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("\n완료 —", OUT)
