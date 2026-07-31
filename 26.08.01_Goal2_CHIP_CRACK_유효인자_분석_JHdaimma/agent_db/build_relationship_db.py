"""AI Agent용 Relationship DB 생성 — Chipping / Micro_Crack

산출물 (agent_db/):
  db_01_factors.csv          유효인자 판정표 (원인 / 감시지표 구분)
  db_02_relationships.csv    FDC -> Response -> Defect 관계 엣지 (그래프용)
  db_03_thresholds.csv       위험선 (Jun C유형 방식 = 결정트리 스텀프)
  db_04_domain_knowledge.csv 공정 도메인 지식 (단계 매핑 + 메커니즘 + 출처)
  db_05_binning.csv          임계값성 변수 구간별 불량률 (멘토 지시)
  db_00_metadata.json        실행 정보 / 제약 / 주의사항

반영한 규약
  - 김시우 pipeline (d39bbff, 멘토 피드백 2차 반영본)
      OPCOND 층, OK-baseline median/MAD z-score, Focus/Cutting_Offset 제외,
      Frequency=fdc_laser, Package_Size_Asymmetry 신규 피처, pending_review 플래그
  - Jun Goal2 방법론
      이중 라벨, Mann-Whitney U + BH-FDR + Cliff's delta(>=0.2),
      RandomForest permutation importance(top-10), verdict 로직, C유형 위험선
  - 멘토 피드백
      Power_Efficiency 비선형(U자) -> |편차| 검정 병행
      Laser_Head_Remain_Time 임계값성 -> 구간화 분석
      Head_Temp 인과사슬, Vibration 열화 대표신호
  - 현업 도메인 지식
      Micro_Crack은 레이저 그루빙 문제가 아님 -> 그루빙 단계 컬럼 제외
      HBM DP 공정: 코팅 -> 레이저 그루빙 -> 세정 -> 블레이드 다이싱
  - 확장(본인)
      pure 라벨(Chipping 동시발생 제거)로 오염 검증
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from statsmodels.stats.multitest import multipletests

RNG = 42
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
OUT.mkdir(exist_ok=True)

# ==================================================================== 김시우 config (d39bbff)
OPCOND = ["Product_ID", "Recipe_ID"]
MAD_SCALE = 1.4826
TREND_ALPHA = 0.05
EFFECT_SIZE_MIN = 0.2
TREE_TOP_N = 10

MENTOR_EXCLUDED = ["Focus", "Cutting_Offset"]
MENTOR_PENDING = ["Edge_Burn", "Bottom_Kerf", "Surface_Roughness",
                  "Cooling_Flow", "Cooling_Water_Temp"]

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

SUBSYSTEM_OF = {c: s for s, cols in SUBSYSTEMS.items() for c in cols}
for c in DOMAIN_FEATURES:
    SUBSYSTEM_OF[c] = "engineered"
SUBSYSTEM_OF["Maintenance_Count"] = "undocumented_env_or_infra"

# ==================================================================== 공정 단계 매핑
# 원칙(26.08.01 정정):
#   1) 컬럼의 계통 분류는 **김시우 00_column_classification.csv의 subsystem이 기준**이다.
#      (위 SUBSYSTEM_OF 딕셔너리가 그 사본)
#   2) 공정 단계(stage)는 팀문서·멘토 근거가 있을 때만 배정한다.
#      근거 없이 작성자가 추측한 배정은 "unassigned"로 두고 근거 유형을 명시한다.
#
# [정정 이력] 초판에서 Vibration을 "4_blade_dicing / 확실"로 배정했으나 근거가 없었다.
#   팀 설계서 회의록: "장비 노후화로 스테이지 축 이동 시 설비가 흔들려 나이프 자국 형태로
#                     잘려 나가는 대형 불량 원인"
#   멘토 피드백:      "설비 열화의 대표 신호. 노후 장비 Y축 이동 시 진동으로 빔 라인 어긋남"
#   -> 두 근거 모두 **장비/스테이지 레벨 진동**이며 블레이드를 특정하지 않는다.
#      멘토 사례는 오히려 레이저 빔 라인 영향이다. 특정 단계에 배정하지 않는다.
#   초판의 "블레이드 채터/스핀들 런아웃" 서술은 작성자 추론이었으므로 삭제한다.
#
# stage_evidence: 팀문서 / 멘토_확정 / 김시우분류 / 작성자_추론 / 멘토_미확정
PROCESS_STAGE_FULL = {
    # ---- 보호 코팅
    "Coating_Flow": ("1_coating", "팀문서", ""),
    "Coating_Thickness": ("1_coating", "팀문서", ""),
    "Coating_Uniformity": ("1_coating", "팀문서", ""),
    # ---- 레이저 그루빙 (제어) : 김시우 fdc_laser와 일치
    "Laser_Power": ("2_laser_grooving", "팀문서", ""),
    "Power_Efficiency": ("2_laser_grooving", "팀문서", ""),
    "Laser_Current": ("2_laser_grooving", "팀문서", ""),
    "Laser_Voltage": ("2_laser_grooving", "팀문서", ""),
    "Beam_Diameter": ("2_laser_grooving", "팀문서", ""),
    "Laser_Centering_Position": ("2_laser_grooving", "팀문서", ""),
    "Frequency": ("2_laser_grooving", "멘토_확정", "멘토가 레이저 변수로 확정"),
    "Head_Temp": ("2_laser_grooving", "멘토_확정",
                  "멘토 인과사슬(헤드온도->굴절률->센터링) 근거. 김시우 subsystem은 fdc_thermal"),
    "Laser_Head_Remain_Time": ("2_laser_grooving", "멘토_확정",
                               "멘토: 헤드 내 11스팟x약2000h. 김시우 subsystem은 fdc_cleaning"),
    # ---- 레이저 그루빙 결과 (김시우 response)
    "Groove_Depth": ("2R_grooving_result", "팀문서", ""),
    "Kerf_Width_Profile": ("2R_grooving_result", "팀문서", ""),
    "Top_Kerf": ("2R_grooving_result", "팀문서", ""),
    "Bottom_Kerf": ("2R_grooving_result", "팀문서", ""),
    "Kerf_Angle": ("2R_grooving_result", "팀문서", ""),
    # ---- 세정
    "CLN_Flow": ("3_cleaning", "팀문서", ""), "CLN_Pressure": ("3_cleaning", "팀문서", ""),
    "CLN_Time": ("3_cleaning", "팀문서", ""),
    # ---- 장비 레벨 (특정 단계에 속하지 않음)
    "Vibration": ("0_equipment_mechanical", "팀문서+멘토_확정",
                  "장비/스테이지 레벨 진동. 김시우 subsystem=fdc_mechanical. "
                  "레이저·다이싱 양쪽에 영향(멘토 사례는 빔 라인 어긋남)"),
    "Maintenance_Count": ("0_equipment_mechanical", "김시우분류", "정비 이력 프록시"),
    # ---- 단계 미배정 (작성자가 근거 없이 배정했던 항목 — 김시우 subsystem만 신뢰)
    "Feed_Speed": ("unassigned", "작성자_추론", "김시우 subsystem=fdc_motion. 레이저 이송인지 다이싱 이송인지 불명"),
    "Alignment_Time": ("unassigned", "작성자_추론", "김시우 subsystem=fdc_motion"),
    "Process_Time": ("unassigned", "작성자_추론", "김시우 subsystem=fdc_motion"),
    "Cutting_X_Index": ("unassigned", "작성자_추론", "김시우 subsystem=fdc_motion. 정렬 계통"),
    "Cutting_Y_Index": ("unassigned", "작성자_추론", "김시우 subsystem=fdc_motion. 정렬 계통"),
    "Cooling_Flow": ("unassigned", "멘토_미확정", "멘토가 설비-컬럼 매핑 재확인 예정"),
    "Cooling_Water_Temp": ("unassigned", "멘토_미확정", "멘토가 설비-컬럼 매핑 재확인 예정"),
    "Surface_Roughness": ("unassigned", "멘토_미확정",
                          "멘토가 drop 여부 미확정. 절단면 품질 지표로 추정되나 어느 단계인지 미확인"),
    "Package_Size_1": ("unassigned", "작성자_추론", "김시우 subsystem=response. 정렬 동반지표"),
    "Package_Size_2": ("unassigned", "작성자_추론", "김시우 subsystem=response"),
    "Package_Size_3": ("unassigned", "작성자_추론", "김시우 subsystem=response"),
    "Package_Size_4": ("unassigned", "작성자_추론", "김시우 subsystem=response"),
    # ---- 파생 피처 (구성 원료의 단계를 상속)
    "Laser_Cleaning_Demand": ("2R_grooving_result", "팀문서", "Laser_Power x Groove_Depth"),
    "Cleaning_Capacity": ("3_cleaning", "팀문서", "CLN_Flow x Pressure x Time"),
    "Cleaning_Load_Ratio": ("3_cleaning", "팀문서", "세정 수요/능력 비율"),
    "Cooling_Thermal_Load": ("unassigned", "멘토_미확정", "Cooling_* 매핑 미확정 상속"),
    "Package_Size_Asymmetry": ("unassigned", "작성자_추론", "김시우 신규 피처. Package_Size 계열 상속"),
}
# 기존 코드 호환용 (stage, evidence) 튜플
PROCESS_STAGE = {c: (v[0], v[1]) for c, v in PROCESS_STAGE_FULL.items()}
STAGE_NOTE = {c: v[2] for c, v in PROCESS_STAGE_FULL.items()}

# Micro_Crack 후보에서 제외할 "레이저 그루빙 계열" — 현업 확정 제약의 적용 대상.
# 단계 미배정(unassigned) 컬럼은 제외 대상이 아니다.
GROOVING_STAGES = {"2_laser_grooving", "2R_grooving_result"}

# ==================================================================== 조치 가능성(layer)
# FDC      = 설비에서 직접 돌릴 수 있는 손잡이 -> "원인 후보"
# Response = 가공 후 측정된 결과값, 직접 조절 불가 -> "감시 지표"
#
# [정정 26.08.01] 초판은 layer를 공정 단계 이름(stage.endswith("_result"))으로 판정했다.
#   단계 배정이 바뀌자 파생 피처의 역할까지 흔들리는 버그가 있었다
#   (Package_Size_Asymmetry가 감시지표 -> 원인후보로 잘못 이동).
#   layer는 **컬럼이 무엇으로 만들어졌는지**로만 결정하며 단계 라벨과 무관하다.
#
# 파생 피처: 구성 원료 중 Response가 하나라도 섞이면 직접 조절할 수 없으므로 Response.
DERIVED_LAYER = {
    "Cooling_Thermal_Load": "FDC",         # Cooling_Water_Temp / Cooling_Flow — 둘 다 FDC
    "Cleaning_Capacity": "FDC",            # CLN_Flow x CLN_Pressure x CLN_Time — 전부 FDC
    "Laser_Cleaning_Demand": "Response",   # Laser_Power(FDC) x Groove_Depth(Response) 포함
    "Cleaning_Load_Ratio": "Response",     # Laser_Cleaning_Demand(Response) 포함
    "Package_Size_Asymmetry": "Response",  # Package_Size_1~4 — 전부 Response
}


def layer_of(col):
    if col in DERIVED_LAYER:
        return DERIVED_LAYER[col]
    if col in RESPONSES:
        return "Response"
    if col in FDC_COLS:
        return "FDC"
    return "Other"

# ==================================================================== 도메인 가설 (출처 명시)
DOMAIN_HYPO = {
 "CHIP": {
  "Groove_Depth": ("깊이 부족 시 low-k 미승화 -> 블레이드가 잔류 low-k 직접 타격 -> 박리/파손", "down", "팀설계서C유형+공정지식"),
  "Kerf_Width_Profile": ("레이저 홈 폭 < 블레이드 폭이면 블레이드가 안 파인 low-k 가장자리 침범", "either", "팀설계서+공정지식"),
  "Top_Kerf": ("홈 폭 계열 — Kerf_Width_Profile과 동일 메커니즘", "either", "팀설계서"),
  "Bottom_Kerf": ("홈 폭 계열 — 동일 메커니즘 (⚠멘토 값중복 재확인 예정)", "either", "팀설계서"),
  "Beam_Diameter": ("빔 협소 시 홈 폭 감소 -> Chipping / 과다 시 Die 영역 침범", "either", "팀설계서B유형"),
  "Laser_Power": ("출력 부족 -> low-k 불완전 승화 -> 잔류물에 블레이드 충돌 (Jun은 Burn전용으로 오분류했음)", "down", "공정지식+데이터반증"),
  "Power_Efficiency": ("실제 조사 에너지 이상 -> 승화 불완전 (⚠멘토: U자형 비선형)", "either", "공정지식+멘토"),
  "Head_Temp": ("헤드온도->크리스탈 스팟온도->굴절률->센터링 변화->Chipping/Kerf 불균일", "up", "멘토 인과사슬"),
  "Laser_Centering_Position": ("Head_Temp 인과사슬 종착점 — 빔 중심 이탈로 비대칭 절단", "either", "멘토 인과사슬"),
  "Vibration": ("장비 노후화로 스테이지 축 이동 시 설비가 흔들려 나이프 자국 형태의 대형 불량 발생", "up", "팀설계서 회의록 명시 + 멘토 사고사례"),
  "Kerf_Angle": ("홈 단면 형상 이상 -> 응력 집중", "either", "팀설계서E유형"),
  "Package_Size_Asymmetry": ("센터링 이상 시 4방향 다이 크기 비대칭 발생", "up", "멘토+김시우신규피처"),
  "Package_Size_1": ("정렬 불량 동반지표", "either", "팀설계서E유형"),
  "Package_Size_2": ("정렬 불량 동반지표", "either", "팀설계서E유형"),
  "Package_Size_3": ("정렬 불량 동반지표", "either", "팀설계서E유형"),
  "Package_Size_4": ("정렬 불량 동반지표", "either", "팀설계서E유형"),
  "Cutting_X_Index": ("절단선 이탈 -> 모서리 파손", "either", "팀설계서E유형"),
  "Cutting_Y_Index": ("절단선 이탈 -> 모서리 파손", "either", "팀설계서E유형"),
  "Laser_Head_Remain_Time": ("헤드 수명 소진 -> 빔 품질 저하 (⚠멘토: 임계값성)", "down", "멘토"),
  "Surface_Roughness": ("결과 공변 — 파손부가 거칠기를 높일 가능성 (⚠멘토 drop 미확정)", "up", "Jun+주의"),
  "Laser_Cleaning_Demand": ("Laser_Power x Groove_Depth — 승화 부담 지표", "either", "팀공용피처"),
 },
 "CRACK": {
  # 현업: Micro_Crack은 레이저 그루빙 문제가 아님 -> 블레이드/기계 계열만 가설로 인정
  "Vibration": ("장비/스테이지 진동(김시우 subsystem=fdc_mechanical). 멘토가 설비 열화 대표신호로 지목, 노후 장비 Y축 이동 시 진동으로 빔 라인 어긋나 대량 스크랩 발생 사례 있음. [추론] 반복 응력에 의한 피로 균열 경로는 미검증", "up", "멘토_확정(변수 중요성) + 작성자_추론(균열 경로)"),
  "Feed_Speed": ("[추론] 이송속도가 응력에 영향 — 김시우 subsystem=fdc_motion, 레이저/다이싱 어느 쪽 이송인지 미확인", "either", "작성자_추론"),
  "Cooling_Flow": ("[추론] 냉각 부족 -> 열충격. ⚠멘토가 설비-컬럼 매핑 재확인 예정이라 어느 계통 냉각인지 미확정", "down", "작성자_추론+멘토_미확정"),
  "Cooling_Water_Temp": ("[추론] 냉각수 온도 상승 -> 열충격. ⚠멘토 매핑 재확인 예정", "up", "작성자_추론+멘토_미확정"),
  "Cooling_Thermal_Load": ("냉각 부담 종합 지표", "up", "팀공용피처"),
  "Process_Time": ("[추론] 누적 응력 노출 — 김시우 subsystem=fdc_motion", "up", "작성자_추론"),
  "Alignment_Time": ("[추론] 누적 응력 노출 — 김시우 subsystem=fdc_motion", "up", "작성자_추론"),
  "Surface_Roughness": ("절단면 거칠기. Vibration이 압도적 1위 드라이버(perm.imp 0.424)라 균열과 공통 원인을 공유하는 동반지표로 보임. Jun도 '결과 공변, 원인 아닐 수 있음'으로 표기. ⚠멘토 drop 여부 미확정", "up", "데이터_실증 + 멘토_미확정"),
  "Maintenance_Count": ("정비 이력 프록시 — 블레이드 교체/드레싱 주기 간접 반영 가능", "either", "김시우decision_note"),
 },
}
NOT_RELATED_NOTE = {
 "CHIP": "세정/코팅 계열 — Particle/Remain_Coat 전용 메커니즘, Chipping과 무관 (Jun 판단 유지)",
 "CRACK": "[현업] Micro_Crack은 레이저 그루빙 공정 문제가 아님 — 그루빙 계열 제외 / 세정계열은 파단과 무관",
}
TEAM_UNDET = {"Laser_Current": "설계서F유형 불확실", "Laser_Voltage": "설계서F유형 불확실",
              "Coating_Thickness": "설계서G유형 측정시점 불확실",
              "Coating_Uniformity": "설계서G유형 측정시점 불확실"}


# ==================================================================== 헬퍼 (김시우 common.py)
def NORMAL(f):
    return (f["Yield"] == 100) & (f["NG_Code"] == "OK")


def add_domain_features(df):
    r = df.copy()
    r["Cooling_Thermal_Load"] = r["Cooling_Water_Temp"] / r["Cooling_Flow"]
    r["Laser_Cleaning_Demand"] = r["Laser_Power"] * r["Groove_Depth"]
    r["Cleaning_Capacity"] = r["CLN_Flow"] * r["CLN_Pressure"] * r["CLN_Time"]
    r["Cleaning_Load_Ratio"] = r["Laser_Cleaning_Demand"] / r["Cleaning_Capacity"]
    pk = ["Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4"]
    r["Package_Size_Asymmetry"] = r[pk].std(axis=1)   # 김시우 신규 (멘토 힌트 수식화)
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


def cliffs(a, b):
    a = pd.Series(a).dropna(); b = pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


# ==================================================================== 데이터
print("[1/7] 데이터 로드 (원본 + r1)")
o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"; r["source_dataset"] = "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
print(f"    {len(df):,}행 | 정상군 {df.is_normal.sum():,} | 피처 {len(FEATURES)}개 "
      f"(Focus/Cutting_Offset 제외 반영)")

bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)
ZC = [f"{c}_z" for c in FEATURES]
# 비선형(U자) 검정용 |편차|
for c in FEATURES:
    df[f"{c}_absz"] = df[f"{c}_z"].abs()

TARGETS = {
    "Chipping": {"ng": "CHIP", "bin": "Chipping", "key": "CHIP"},
    "Micro_Crack": {"ng": "CRACK", "bin": "Micro_Crack", "key": "CRACK"},
}

# ==================================================================== db_01 유효인자
print("[2/7] 유효인자 판정 (Jun 방법론 + 삼중라벨 + 비선형 + 재현성)")
factor_rows = []
for tname, spec in TARGETS.items():
    other = "Micro_Crack" if tname == "Chipping" else "Chipping"
    labels = {
        "primary": (df.NG_Code == spec["ng"]).values,
        "broad": (df[spec["bin"]] == 1).values,
        "pure": ((df[spec["bin"]] == 1) & (df[other] == 0)).values,
    }
    print(f"  [{tname}] primary={labels['primary'].sum():,} "
          f"broad={labels['broad'].sum():,} pure={labels['pure'].sum():,}")

    # 현업 도메인 제약: Micro_Crack은 그루빙 계열 제외
    if tname == "Micro_Crack":
        feats = [c for c in FEATURES if PROCESS_STAGE[c][0] not in GROOVING_STAGES]
    else:
        feats = FEATURES
    print(f"       후보 피처 {len(feats)}개")

    # --- 단변량 (선형/단조) + 비선형(|편차|)
    uni = {}
    for lab, mask in labels.items():
        rows = []
        for c in feats:
            d, p = cliffs(df.loc[mask, f"{c}_z"], df.loc[~mask, f"{c}_z"])
            dn, pn = cliffs(df.loc[mask, f"{c}_absz"], df.loc[~mask, f"{c}_absz"])
            rows.append({"column": c, "delta": d, "p": p, "delta_abs": dn, "p_abs": pn})
        t = pd.DataFrame(rows)
        t["p_fdr"] = multipletests(t.p.fillna(1), alpha=TREND_ALPHA, method="fdr_bh")[1]
        t["p_fdr_abs"] = multipletests(t.p_abs.fillna(1), alpha=TREND_ALPHA, method="fdr_bh")[1]
        uni[lab] = t.set_index("column")

    # --- 트리 중요도 (Jun 방식, primary/broad/pure 각각)
    tree = {}
    for lab, mask in labels.items():
        y = mask.astype(int)
        fz = [f"{c}_z" for c in feats]
        tr, te = train_test_split(df, test_size=0.2, random_state=RNG, stratify=y)
        ytr = tr[spec["bin"]].values if lab != "primary" else (tr.NG_Code == spec["ng"]).astype(int).values
        # 라벨을 프레임에 부착해서 분할 일관성 유지
        dd = df.copy(); dd["_y"] = y
        if lab == "pure":
            dd = dd[~((dd[spec["bin"]] == 0) & (dd[other] == 1))]  # 상대결함 단독행 제외
        tr, te = train_test_split(dd, test_size=0.2, random_state=RNG, stratify=dd._y)
        m = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                                   random_state=RNG, n_jobs=-1).fit(tr[fz], tr._y)
        tes = te.sample(n=min(20000, len(te)), random_state=RNG)
        pi = permutation_importance(m, tes[fz], tes._y, scoring="average_precision",
                                    n_repeats=10, random_state=RNG, n_jobs=-1)
        t = pd.DataFrame({"column": feats, "imp": pi.importances_mean})
        t["rank"] = t.imp.rank(ascending=False, method="min").astype(int)
        tree[lab] = t.set_index("column")

    # --- 데이터셋별 / 장비별 재현성
    repro = {}
    for c in feats:
        ds = {}
        for d_ in ["original", "r1"]:
            sub = (df.source_dataset == d_).values
            m2 = labels["broad"] & sub
            if m2.sum() < 10:
                ds[d_] = np.nan; continue
            ds[d_], _ = cliffs(df.loc[m2, f"{c}_z"], df.loc[sub & ~labels["broad"], f"{c}_z"])
        mach = []
        for mid in ["DP01", "DP02", "DP03", "DP04"]:
            sub = (df.Machine_ID == mid).values
            m2 = labels["broad"] & sub
            if m2.sum() < 50:
                continue
            dd, _ = cliffs(df.loc[m2, f"{c}_z"], df.loc[sub & ~labels["broad"], f"{c}_z"])
            mach.append(dd)
        repro[c] = {"delta_original": ds.get("original"), "delta_r1": ds.get("r1"),
                    "n_machines_tested": len(mach),
                    "n_machines_effect_ge_02": int(sum(abs(x) >= 0.2 for x in mach if pd.notna(x)))}

    for c in feats:
        stage, conf = PROCESS_STAGE[c]
        hypo = DOMAIN_HYPO[spec["key"]].get(c)
        if hypo:
            mech, direction, source = hypo
            dstatus, support = "defect_related", True
        elif c in TEAM_UNDET:
            mech, direction, source = TEAM_UNDET[c], "unknown", "팀미확정"
            dstatus, support = "team_undetermined", False
        else:
            mech, direction, source = NOT_RELATED_NOTE[spec["key"]], "not_applicable", "도메인판단"
            dstatus, support = "not_related_to_defect", False

        up, ub, uu = uni["primary"].loc[c], uni["broad"].loc[c], uni["pure"].loc[c]
        tp, tb, tu = tree["primary"].loc[c], tree["broad"].loc[c], tree["pure"].loc[c]

        uni_flag = bool((ub.p_fdr < .05 and abs(ub.delta) >= EFFECT_SIZE_MIN)
                        or (uu.p_fdr < .05 and abs(uu.delta) >= EFFECT_SIZE_MIN))
        nonlin_flag = bool(uu.p_fdr_abs < .05 and abs(uu.delta_abs) >= EFFECT_SIZE_MIN)
        # Jun 원본 규약: rank<=10 AND importance>0 (importance>0 조건 복원)
        tree_flag = bool((tb["rank"] <= TREE_TOP_N and tb.imp > 0)
                         or (tu["rank"] <= TREE_TOP_N and tu.imp > 0))

        # --- broad에서만 신호가 나오고 pure(상대 결함 제외)에서 단변량이 꺼지는 경우 ---
        # 두 가지를 구분해야 한다:
        #   (a) 순수 오염       : pure에서 다변량 신호도 없음 -> 상대 결함이 끌고 온 가짜 신호
        #   (b) 공통 원인(shared): pure에서도 트리 상위 + 장비 재현 + 도메인 지지가 남음
        #                         -> 두 결함 모두를 유발하는 진짜 원인. 배제하면 안 된다.
        drops_in_pure = bool(abs(ub.delta) >= EFFECT_SIZE_MIN
                             and abs(uu.delta) < EFFECT_SIZE_MIN)
        survives_multivariate = bool(tu["rank"] <= TREE_TOP_N and tu.imp > 0
                                     and repro[c]["n_machines_effect_ge_02"] >= 2
                                     and support)

        n_methods = int(uni_flag) + int(tree_flag)
        if drops_in_pure and survives_multivariate:
            verdict = f"shared_cause_with_{other}"
        elif drops_in_pure:
            verdict = f"contaminated_by_{other}"
        elif n_methods >= 2 and support:
            verdict = "confirmed"
        elif n_methods >= 2 and not support:
            verdict = "candidate_needs_domain_review"
        elif n_methods == 1 and support:
            verdict = "candidate_weak_signal"
        elif nonlin_flag and support:
            verdict = "candidate_nonlinear_only"
        else:
            verdict = "insufficient_evidence"

        layer = layer_of(c)
        role = ("감시지표" if layer == "Response" else "원인후보") if verdict.startswith(
            ("confirmed", "candidate", "shared_cause")) else "-"

        rp = repro[c]
        cautions = []
        if c in MENTOR_PENDING:
            cautions.append("멘토 재확인 대기")
        if "미확정" in conf or "추정" in conf:
            cautions.append(f"공정단계 매핑 {conf}")
        if c == "Power_Efficiency":
            cautions.append("멘토: U자형 비선형 — 단조검정 과소평가 가능")
        if c == "Laser_Head_Remain_Time":
            cautions.append("멘토: 임계값성 — db_05_binning 참조")

        factor_rows.append({
            "target": tname, "factor": c, "layer": layer, "subsystem": SUBSYSTEM_OF[c],
            "process_stage": stage, "stage_confidence": conf,
            "is_laser_grooving": stage in GROOVING_STAGES,
            "role": role, "verdict": verdict,
            "domain_status": dstatus, "domain_mechanism": mech,
            "direction_hypothesis": direction, "domain_source": source,
            "delta_primary": round(up.delta, 4), "delta_broad": round(ub.delta, 4),
            "delta_pure": round(uu.delta, 4),
            "p_fdr_broad": f"{ub.p_fdr:.3e}", "p_fdr_pure": f"{uu.p_fdr:.3e}",
            "delta_nonlinear_abs_pure": round(uu.delta_abs, 4),
            "tree_imp_broad": round(tb.imp, 6), "tree_rank_broad": int(tb["rank"]),
            "tree_imp_pure": round(tu.imp, 6), "tree_rank_pure": int(tu["rank"]),
            "flag_univariate": uni_flag, "flag_nonlinear": nonlin_flag,
            "flag_tree": tree_flag, "n_methods_agree": n_methods,
            "delta_original_dataset": None if pd.isna(rp["delta_original"]) else round(rp["delta_original"], 4),
            "delta_r1_dataset": None if pd.isna(rp["delta_r1"]) else round(rp["delta_r1"], 4),
            "n_machines_effect_ge_02": rp["n_machines_effect_ge_02"],
            "n_machines_tested": rp["n_machines_tested"],
            "caution": " / ".join(cautions) if cautions else "",
        })

fac = pd.DataFrame(factor_rows)
order = {"confirmed": 0, "shared_cause_with_Chipping": 1, "shared_cause_with_Micro_Crack": 1,
         "candidate_needs_domain_review": 2, "candidate_weak_signal": 3,
         "candidate_nonlinear_only": 4, "contaminated_by_Chipping": 5,
         "contaminated_by_Micro_Crack": 5, "insufficient_evidence": 6}
fac["_o"] = fac.verdict.map(lambda v: order.get(v, 9))
fac = fac.sort_values(["target", "_o", "tree_rank_pure"]).drop(columns="_o")
fac.to_csv(OUT / "db_01_factors.csv", index=False, encoding="utf-8-sig")
print(f"    -> db_01_factors.csv ({len(fac)}행)")

# ==================================================================== db_02 관계 엣지
print("[3/7] FDC -> Response -> Defect 관계 엣지")
edges = []

# (a) Response -> Defect : 감시지표 엣지 (pure 라벨 기준, 오염 배제)
for tname, spec in TARGETS.items():
    other = "Micro_Crack" if tname == "Chipping" else "Chipping"
    pure = ((df[spec["bin"]] == 1) & (df[other] == 0)).values
    sub = fac[(fac.target == tname) & (fac.layer == "Response")]
    for _, x in sub.iterrows():
        if x.verdict.startswith(("confirmed", "shared_cause", "candidate_weak_signal",
                                 "candidate_needs_domain_review")):
            edges.append({"source": x.factor, "source_layer": "Response",
                          "target": tname, "target_layer": "Defect",
                          "relation": "monitors", "strength": abs(x.delta_pure),
                          "direction": "up" if x.delta_pure > 0 else "down",
                          "method": "Cliffs delta (pure label)", "verdict": x.verdict})

# (b) FDC -> Defect : 원인 엣지
for tname in TARGETS:
    sub = fac[(fac.target == tname) & (fac.layer.isin(["FDC", "Engineered"]))]
    for _, x in sub.iterrows():
        if x.verdict.startswith(("confirmed", "shared_cause", "candidate_weak_signal",
                                 "candidate_needs_domain_review", "candidate_nonlinear_only")):
            edges.append({"source": x.factor, "source_layer": x.layer,
                          "target": tname, "target_layer": "Defect",
                          "relation": "causes", "strength": abs(x.delta_pure),
                          "direction": x.direction_hypothesis,
                          "method": "Cliffs delta (pure label)", "verdict": x.verdict})

# (c) FDC -> Response : 다리 엣지 (무엇이 그 측정값을 만드나)
key_responses = ["Kerf_Width_Profile", "Groove_Depth", "Surface_Roughness",
                 "Top_Kerf", "Bottom_Kerf", "Kerf_Angle", "Package_Size_Asymmetry"]
fz_fdc = [f"{c}_z" for c in FDC_COLS]
for resp in key_responses:
    y = df[f"{resp}_z"].fillna(0).values
    tr, te = train_test_split(df, test_size=0.2, random_state=RNG)
    m = RandomForestRegressor(n_estimators=120, max_depth=10, random_state=RNG,
                              n_jobs=-1).fit(tr[fz_fdc], tr[f"{resp}_z"].fillna(0))
    tes = te.sample(n=min(15000, len(te)), random_state=RNG)
    r2 = m.score(tes[fz_fdc], tes[f"{resp}_z"].fillna(0))
    pi = permutation_importance(m, tes[fz_fdc], tes[f"{resp}_z"].fillna(0),
                                n_repeats=5, random_state=RNG, n_jobs=-1)
    s = pd.Series(pi.importances_mean, index=FDC_COLS).sort_values(ascending=False)
    print(f"    {resp:24s} R2={r2:.3f}  top: " + ", ".join(f"{i}({s[i]:.3f})" for i in s.index[:3]))
    for drv in s.index[:5]:
        if s[drv] <= 0.001:
            continue
        corr = np.corrcoef(df[f"{drv}_z"].fillna(0), y)[0, 1]
        edges.append({"source": drv, "source_layer": "FDC",
                      "target": resp, "target_layer": "Response",
                      "relation": "drives", "strength": round(float(s[drv]), 5),
                      "direction": "up" if corr > 0 else "down",
                      "method": f"RF permutation importance (model R2={r2:.3f})",
                      "verdict": "-"})

# (d) Defect <-> Defect
both = int(((df.Chipping == 1) & (df.Micro_Crack == 1)).sum())
phi = float(np.corrcoef(df.Chipping, df.Micro_Crack)[0, 1])
edges.append({"source": "Chipping", "source_layer": "Defect", "target": "Micro_Crack",
              "target_layer": "Defect", "relation": "co_occurs", "strength": round(abs(phi), 4),
              "direction": "up" if phi > 0 else "down",
              "method": f"phi coefficient (동시발생 {both:,}건)", "verdict": "-"})

ed = pd.DataFrame(edges).sort_values(["target_layer", "target", "strength"],
                                     ascending=[True, True, False])
ed["strength"] = ed.strength.astype(float).round(5)
ed.to_csv(OUT / "db_02_relationships.csv", index=False, encoding="utf-8-sig")
print(f"    -> db_02_relationships.csv ({len(ed)}행)")

# ==================================================================== db_03 위험선
print("[4/7] 위험선 (Jun C유형 = 결정트리 스텀프)")
th_rows = []
TH_TARGETS = {
    "Chipping": ["Kerf_Width_Profile", "Groove_Depth", "Laser_Power", "Power_Efficiency",
                 "Top_Kerf", "Bottom_Kerf", "Vibration", "Head_Temp",
                 "Laser_Centering_Position", "Package_Size_Asymmetry"],
    "Micro_Crack": ["Vibration", "Surface_Roughness", "Cooling_Flow", "Cooling_Water_Temp",
                    "Feed_Speed", "Cooling_Thermal_Load"],
}
for tname, cols in TH_TARGETS.items():
    spec = TARGETS[tname]; other = "Micro_Crack" if tname == "Chipping" else "Chipping"
    ylab = ((df[spec["bin"]] == 1) & (df[other] == 0)).astype(int)
    for c in cols:
        # 전역 (z-score 기준) — Agent가 조건 무관하게 쓸 수 있는 기준
        X = df[[f"{c}_z"]].fillna(0).values
        if ylab.sum() < 30:
            continue
        t = DecisionTreeClassifier(max_depth=1, min_samples_leaf=200,
                                   random_state=0).fit(X, ylab)
        if t.tree_.feature[0] == -2:
            continue
        thr = float(t.tree_.threshold[0])
        below = ylab[X[:, 0] < thr]; above = ylab[X[:, 0] >= thr]
        rb, ra = below.mean(), above.mean()
        risky = "low_is_risky" if rb > ra else "high_is_risky"
        # 원단위 환산 (전체 정상군 median/MAD 기준 근사)
        med = df.loc[df.is_normal, c].median()
        scale = MAD_SCALE * (df.loc[df.is_normal, c] - med).abs().median()
        th_rows.append({
            "target": tname, "variable": c, "scope": "global_zscore",
            "threshold_z": round(thr, 4),
            "threshold_raw_approx": round(float(med + thr * scale), 5),
            "risky_direction": risky,
            "defect_rate_below": round(float(rb) * 100, 3),
            "defect_rate_above": round(float(ra) * 100, 3),
            "risk_ratio": round(float(max(rb, ra) / max(min(rb, ra), 1e-9)), 2),
            "n_below": int((X[:, 0] < thr).sum()), "n_above": int((X[:, 0] >= thr).sum()),
            "n_defect": int(ylab.sum()),
            "note": "pure 라벨(상대 결함 동시발생 제외) 기준. Jun C유형 방식.",
        })
th = pd.DataFrame(th_rows).sort_values(["target", "risk_ratio"], ascending=[True, False])
th.to_csv(OUT / "db_03_thresholds.csv", index=False, encoding="utf-8-sig")
print(f"    -> db_03_thresholds.csv ({len(th)}행)")
for _, x in th.head(8).iterrows():
    print(f"    {x.target:12s} {x.variable:24s} z={x.threshold_z:+.2f} "
          f"({x.risky_direction})  불량률 {x.defect_rate_below:.2f}% vs {x.defect_rate_above:.2f}%"
          f"  위험비 {x.risk_ratio}배")

# ==================================================================== db_04 도메인 지식
print("[5/7] 공정 도메인 지식 테이블")
STAGE_DESC = {
    "0_equipment_mechanical": "장비 기계계통 — 특정 공정 단계에 속하지 않고 레이저·다이싱 양쪽에 영향",
    "unassigned": "공정 단계 미배정 — 근거 부족. 김시우 subsystem 분류만 신뢰할 것",
    "0_equipment": "설비 상태/정비 이력",
    "1_coating": "보호 코팅 도포 — 레이저 debris가 웨이퍼 표면에 붙는 것을 방지",
    "2_laser_grooving": "레이저 그루빙 — scribe lane의 low-k+금속층을 승화(ablation)로 제거",
    "2R_grooving_result": "레이저 그루빙 결과 측정값 (홈 깊이/폭/각도)",
    "3_cleaning": "세정 — 레이저 debris 및 보호 코팅 제거",
    "4_blade_dicing": "블레이드 다이싱 — 벌크 실리콘 절단 (low-k는 이미 제거된 상태)",
    "4R_dicing_result": "다이싱 결과 측정값 (절단면 품질/다이 치수)",
}
# ---------------------------------------------------------------------------
# 근거 유형(evidence_type) 분류 규약 — 확정된 사실과 추론을 절대 섞지 않는다.
#
#   현업_확정   : 현업/담당자가 명시적으로 확인해준 사실
#   멘토_확정   : 멘토 피드백으로 확정된 사항
#   팀문서      : 팀 HealthIndex 설계서 / 회의록에 명시된 내용
#   데이터_실증 : 이 분석의 데이터로 직접 검증한 관찰 결과 (수치 병기)
#   작성자_추론 : 일반 공정 물리에서 도출한 작성자의 해석. **검증되지 않았음.**
#                 틀릴 수 있으며, 현업 확인 전까지 사실로 인용하면 안 된다.
#
# reliability: 확정 / 검증됨 / 미검증(추론)
# ---------------------------------------------------------------------------
DEFECT_KNOWLEDGE = [
    # ---- Chipping
    ("Chipping", "2_laser_grooving + 4_blade_dicing",
     "모서리 파손 — 절단 경계에서 재질이 매끈하게 제거되지 못하고 깨져나가는 현상",
     "팀문서", "확정", "HealthIndex 설계서에 Chipping 관련 명시적 서술 다수"),
    ("Chipping", "2_laser_grooving",
     "Groove_Depth 부족 시 low-k가 완전히 승화되지 못해 Blade 진입 시 Chipping 발생",
     "팀문서", "확정", "HealthIndex 설계서 C유형 명시 인용"),
    ("Chipping", "2_laser_grooving",
     "Beam_Diameter 협소 시 Width 감소로 Chipping 증가, 과다 시 Die 영역 침범",
     "팀문서", "확정", "HealthIndex 설계서 B유형 명시 인용"),
    ("Chipping", "4_blade_dicing",
     "장비 노후로 스테이지 축 이동 시 진동 발생 -> 나이프 자국 형태의 대형 불량",
     "팀문서", "확정", "HealthIndex 설계서 회의록 명시. 멘토도 실제 스크랩 사고 사례로 재확인"),
    ("Chipping", "2_laser_grooving",
     "Head_Temp -> 크리스탈 스팟 온도 -> 굴절률 -> Laser_Centering_Position -> Chipping/Kerf 불균일",
     "멘토_확정", "확정", "멘토가 제시한 인과사슬 (26.07.31)"),
    ("Chipping", "2_laser_grooving",
     "Laser_Power / Power_Efficiency 저하가 Chipping 상위 인자로 확인됨 "
     "(3방법 모두 top10, SHAP 모델A 2·3위, Groove_Depth R2=0.606 / Kerf_Width_Profile R2=0.954의 주 드라이버)",
     "데이터_실증", "검증됨", "Jun 브랜치는 이 둘을 'Burn 전용'으로 무관 처리했으나 데이터가 반박"),
    ("Chipping", "2_laser_grooving",
     "[추론] 레이저 홈 폭이 블레이드 폭보다 좁으면 블레이드가 안 파인 low-k 가장자리를 "
     "침범해 Chipping이 난다 — 레이저 다이싱 일반 물리에서 도출한 해석",
     "작성자_추론", "미검증(추론)",
     "⚠ 검증되지 않은 해석. 실제 블레이드 폭 데이터가 없어 확인 불가. 현업 확인 필요"),

    # ---- Micro_Crack
    ("Micro_Crack", "4_blade_dicing",
     "Micro_Crack은 레이저 그루빙 공정의 문제가 아니다",
     "현업_확정", "확정",
     "현업이 명시적으로 확인해준 제약. 이 분석의 그루빙 계열 15개 컬럼 제외 근거"),
    ("Micro_Crack", "4_blade_dicing",
     "그루빙 계열 변수는 Chipping 동시발생 행에서만 신호가 나오고, 해당 행을 제거하면 "
     "효과크기가 0으로 소멸 (예: Kerf_Width_Profile broad +0.534 -> pure -0.023, "
     "Focus +0.511 -> -0.014, Head_Temp +0.512 -> -0.001). "
     "그루빙 15개를 전부 제외해도 모델 성능은 AUC 0.9152 -> 0.9056으로 거의 불변",
     "데이터_실증", "검증됨", "현업 확정 사항을 데이터가 독립적으로 뒷받침한 결과"),
    ("Micro_Crack", "4_blade_dicing",
     "Vibration이 Micro_Crack 원인 1위 (SHAP 모델A 1위, 3방법 모두 top10, 4개 장비 중 3대 재현). "
     "Surface_Roughness의 압도적 1위 드라이버이기도 함(perm. imp 0.424)",
     "데이터_실증", "검증됨", "멘토가 언급한 실제 스크랩 사고 사례와도 일치"),
    ("Micro_Crack", "4_blade_dicing",
     "[추론] 레이저 HAZ는 scribe lane 내부에 국한되고 블레이드가 그 자리를 제거하므로 "
     "그루빙 기여가 작다 — 현업 확정 사항('그루빙 문제 아님')을 설명하기 위해 작성자가 붙인 해석",
     "작성자_추론", "미검증(추론)",
     "⚠ 검증되지 않은 해석. 이 설명이 틀려도 위의 현업_확정·데이터_실증 항목은 영향받지 않음"),
    ("Micro_Crack", "4_blade_dicing",
     "[추론] 블레이드 절삭 응력/진동 채터/백그라인딩 잔류 손상이 표면하 손상층을 만들고 "
     "그것이 미세균열이 된다 — 레이저 다이싱 일반 물리에서 도출",
     "작성자_추론", "미검증(추론)",
     "⚠ 데이터에 블레이드 파라미터(마모/드레싱/런아웃)가 없어 직접 검증 불가"),
    ("Micro_Crack", "4_blade_dicing",
     "[추론] HBM은 박형화+적층 본딩이라 die break strength 저하가 치명적 — "
     "다이싱 시 균열이 본딩 단계에서 전파되어 스택 전체 불량으로 확대될 수 있음",
     "작성자_추론", "미검증(추론)",
     "⚠ 이 데이터셋으로는 후공정 전파 여부를 확인할 수 없음"),
]

dk_rows = []
for item, stage, desc, ev, rel, note in DEFECT_KNOWLEDGE:
    dk_rows.append({"kind": "defect_mechanism", "item": item, "process_stage": stage,
                    "description": desc, "evidence_type": ev, "reliability": rel,
                    "note": note, "source": ev})
for s, desc in STAGE_DESC.items():
    dk_rows.append({"kind": "process_stage", "item": s, "process_stage": s,
                    "description": desc, "evidence_type": "현업_확정", "reliability": "확정",
                    "note": "현업이 알려준 HBM DP 공정 흐름", "source": "현업_확정"})
for c, (stage, conf) in PROCESS_STAGE.items():
    rel = ("미검증(추론)" if "작성자_추론" in conf else
           "재확인 대기" if "미확정" in conf else "확정")
    note = STAGE_NOTE.get(c, "")
    dk_rows.append({"kind": "column_stage_mapping", "item": c, "process_stage": stage,
                    "description": STAGE_DESC.get(stage, ""),
                    "evidence_type": conf, "reliability": rel,
                    "note": f"김시우 subsystem={SUBSYSTEM_OF.get(c,'-')}"
                            + (f" / {note}" if note else ""),
                    "source": conf})

MENTOR_NOTES = {
    "Focus": "멘토: 분석에 활용하지 않아도 됨 -> 제외 (26.07.31)",
    "Cutting_Offset": "멘토: 분석에 활용하지 않아도 됨 -> 제외 (26.07.31)",
    "Frequency": "멘토: 레이저 변수로 확인 -> fdc_laser 재분류. Micro_Crack 그루빙 제외 대상",
    "Power_Efficiency": "멘토: U자형 비선형 — 단조 상관만으로 판단 금지",
    "Vibration": "멘토: 설비 열화 대표신호. 실제 사고사례(노후장비 Y축 진동->빔라인 어긋남->대량 스크랩)",
    "Laser_Head_Remain_Time": "멘토: 헤드 내 11스팟, 스팟당 기준수명 약 2000h. 임계값성 패턴 가능",
    "Head_Temp": "멘토 인과사슬: Head_Temp->크리스탈 스팟온도->굴절률->Laser_Centering_Position->Chipping/Kerf",
    "Kerf_Width_Profile": "멘토: 7um 기준점이 합성데이터에서 물리상수 아닐 수 있음 — 하드코딩 금지, baseline 역산",
    "Top_Kerf": "멘토: 7um 기준점 주의사항 동일",
    "Groove_Depth": "멘토: 7um 기준 편차값이나 물리상수 아닐 수 있음 — baseline 역산",
    "Edge_Burn": "[재확인대기] 멘토가 무시해도 된다 시사했으나 미확정. Jun BURN 분석 전체 영향",
    "Bottom_Kerf": "[재확인대기] 다른 kerf 컬럼과 값 중복 여부",
    "Surface_Roughness": "[재확인대기] drop 여부 미확정 (필요상 넣어놓은 컬럼이라고만 언급)",
    "Cooling_Flow": "[재확인대기] 설비-컬럼 매핑 재확인 예정",
    "Cooling_Water_Temp": "[재확인대기] 설비-컬럼 매핑 재확인 예정",
    "Package_Size_Asymmetry": "멘토 힌트(센터링 이상->4방향 비대칭)를 김시우가 신규 피처로 수식화",
}
for c, n in MENTOR_NOTES.items():
    pending = c in MENTOR_PENDING
    dk_rows.append({"kind": "mentor_feedback", "item": c,
                    "process_stage": PROCESS_STAGE.get(c, ("-", ""))[0],
                    "description": n,
                    "evidence_type": "멘토_미확정" if pending else "멘토_확정",
                    "reliability": "재확인 대기" if pending else "확정",
                    "note": "멘토 재확인 전까지 결과 해석 주의" if pending else "",
                    "source": "멘토 피드백 26.07.31"})
pd.DataFrame(dk_rows).to_csv(OUT / "db_04_domain_knowledge.csv",
                             index=False, encoding="utf-8-sig")
print("    -> db_04_domain_knowledge.csv (%d행)" % len(dk_rows))

# ==================================================================== db_05 구간화
print("[6/7] 임계값성 변수 구간화 (멘토 지시)")
bin_rows = []
BIN_VARS = ["Laser_Head_Remain_Time", "Maintenance_Count", "Power_Efficiency",
            "Vibration", "Kerf_Width_Profile", "Groove_Depth"]
for c in BIN_VARS:
    if c == "Laser_Head_Remain_Time":
        edges_b = [1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]
    elif c == "Maintenance_Count":
        edges_b = list(range(0, 22, 3))
    else:
        q = np.quantile(df[c].dropna(), np.linspace(0, 1, 11))
        edges_b = sorted(set(np.round(q, 5)))
    df["_bin"] = pd.cut(df[c], bins=edges_b, include_lowest=True)
    for tname, spec in TARGETS.items():
        other = "Micro_Crack" if tname == "Chipping" else "Chipping"
        pure = ((df[spec["bin"]] == 1) & (df[other] == 0)).astype(int)
        g = pure.groupby(df["_bin"], observed=True).agg(["mean", "count", "sum"])
        overall = pure.mean()
        for iv, row in g.iterrows():
            if row["count"] < 200:
                continue
            bin_rows.append({
                "variable": c, "target": tname, "bin": str(iv),
                "bin_left": float(iv.left), "bin_right": float(iv.right),
                "n": int(row["count"]), "n_defect": int(row["sum"]),
                "defect_rate_pct": round(float(row["mean"]) * 100, 4),
                "lift_vs_overall": round(float(row["mean"] / max(overall, 1e-9)), 3),
                "overall_rate_pct": round(float(overall) * 100, 4),
            })
df = df.drop(columns="_bin")
bn = pd.DataFrame(bin_rows)
bn.to_csv(OUT / "db_05_binning.csv", index=False, encoding="utf-8-sig")
print("    -> db_05_binning.csv (%d행)" % len(bn))
for c in ["Laser_Head_Remain_Time", "Power_Efficiency"]:
    for tt in ["Chipping", "Micro_Crack"]:
        s = bn[(bn.variable == c) & (bn.target == tt)]
        if len(s):
            print("    [%s / %s] lift %.2f ~ %.2f" %
                  (c, tt, s.lift_vs_overall.min(), s.lift_vs_overall.max()))

# ==================================================================== db_00 메타데이터
print("[7/7] 메타데이터")
meta = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "purpose": "AI Agent(3 Relationship Analyzer / 5 Root Cause Analyzer)용 관계 DB",
    "datasets": {
        "original": {"rows": int(len(o)), "chipping": int(o.Chipping.sum()),
                     "micro_crack": int(o.Micro_Crack.sum())},
        "r1": {"rows": int(len(r)), "chipping": int(r.Chipping.sum()),
               "micro_crack": int(r.Micro_Crack.sum())},
        "combined_rows": int(len(df)), "normal_rows": int(df.is_normal.sum()),
        "key_overlap_note": "Lot_ID+Strip_ID 기준 8,597건(8.6%)만 중복 — 독립 표본으로 간주해 통합",
    },
    "feature_set": {"n_features": len(FEATURES),
                    "excluded_by_mentor": MENTOR_EXCLUDED,
                    "pending_mentor_review": MENTOR_PENDING,
                    "new_team_feature": "Package_Size_Asymmetry"},
    "methodology": {
        "preprocessing": "김시우 pipeline d39bbff — OPCOND층 OK-baseline median/MAD 강건 z-score",
        "statistics": "Jun Goal2 — Mann-Whitney U + BH-FDR(a=0.05) + Cliffs delta(>=0.2), "
                      "RandomForest(200,depth8,balanced) permutation importance(AP) top-10",
        "labels": "primary(NG_Code) / broad(이진컬럼) / pure(상대 결함 동시발생 제외)",
        "nonlinear": "멘토 U자형 지적 반영 — |z편차| 기준 Mann-Whitney 병행",
        "thresholds": "Jun C유형 — DecisionTree stump(depth=1)로 위험 경계값 추정",
        "not_used": "전성재 브랜치 방법론(L1 로지스틱/HistGradientBoosting/Machine 통제 다변량) 미사용",
    },
    "domain_constraints": [
        "Micro_Crack은 레이저 그루빙 공정 문제가 아님(현업) -> 그루빙 단계 컬럼을 후보에서 제외",
        "HBM DP 공정: 보호코팅 -> 레이저 그루빙(low-k 승화) -> 세정 -> 블레이드 다이싱",
        "Response 계열은 원인이 아니라 감시지표로 분류 — 조치는 FDC에서",
    ],
    "known_limitations": [
        "블레이드 관련 파라미터(마모도/드레싱/스핀들 런아웃) 컬럼이 데이터에 없음 — "
        "Chipping/Micro_Crack 모두 블레이드 단계 불량이라 Vibration이 유일한 프록시",
        "Surface_Roughness는 멘토 drop 여부 미확정 — Micro_Crack 감시지표 결론이 이에 의존",
        "Edge_Burn 제외 여부 미확정 — Jun BURN 분석 전체에 영향",
        "r1은 DP02/DP03에 열화를 주입한 시나리오 데이터 — 실제 라인 재현 여부 별도 확인 필요",
        "Cooling_Flow/Cooling_Water_Temp 설비-컬럼 매핑 미확정",
    ],
    "open_questions_for_mentor": [
        "Surface_Roughness는 실제 측정값인가, 형식상 컬럼인가?",
        "Edge_Burn을 최종 제외하는가?",
        "Bottom_Kerf가 다른 kerf 컬럼과 값이 중복인가?",
        "블레이드 관련 파라미터(마모/드레싱/런아웃)를 추가로 받을 수 있는가?",
    ],
}
with open(OUT / "db_00_metadata.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 78)
print("DB 생성 완료:", OUT)
for p in sorted(OUT.glob("db_*")):
    print("  " + p.name)
print("=" * 78)
print("\n--- 최종 유효인자 요약 ---")
KEEP = ["confirmed", "shared_cause_with_Chipping", "shared_cause_with_Micro_Crack",
        "candidate_needs_domain_review", "candidate_weak_signal", "candidate_nonlinear_only"]
for tname in TARGETS:
    s = fac[(fac.target == tname) & (fac.verdict.isin(KEEP))]
    print("\n[%s]" % tname)
    for _, x in s.iterrows():
        print("  %-30s %-6s %-24s delta_pure=%+.3f rank=%2d  %s"
              % (x.verdict, x.role, x.factor, x.delta_pure, x.tree_rank_pure, x.process_stage))
