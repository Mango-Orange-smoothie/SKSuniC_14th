"""파이프라인 전역 상수.

모든 Step0/Goal 모듈은 KEY/GROUP/OPCOND/NORMAL 등을 여기서만 import한다.
각자 재정의하면 층(stratum) 정의가 모듈마다 미묘하게 어긋날 수 있다.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUT_CSV = ROOT / "data" / "raw" / "DP_HealthIndex_Dataset.csv"
# (26.08.05) 멘토 배포 실데이터 — 모니터링 대상(INPUT_CSV)과 합치지 않고 Type C 결정트리
# threshold "학습"에만 쓴다. 불량 사례를 의도적으로 많이 담은 데이터셋이라 정상군 비율이
# 원본과 다르다(step0_preprocessing.py의 load_r1_for_threshold_training 참고).
INPUT_CSV_R1 = ROOT / "DP_HealthIndex_Dataset_r1.csv"
OUTPUT_DIR = ROOT / "analysis_outputs"
PREPROCESSING_DIR = OUTPUT_DIR / "preprocessing"

# Goal2 통합 관계DB(JHdaimma) — 인자↔defect 짝짓기의 팀 공식 출처.
# rel_30_trend_interface.csv는 trend_owner="김시우(추세분석)"로 명시된 인계 파일이고,
# rel_20_tier_table.csv는 그 근거표(재현성 판정 repro_state 포함)다.
RELATIONSHIP_DB_DIR = ROOT / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma"

# 분석키: Lot_ID+Strip_ID만 유일. Strip_ID 단독은 다른 Lot에서 재사용되므로
# 분석키·조인키로 절대 단독 사용 금지 (기존 analysis_step_by_step.py와 동일 규약).
KEY = ["Lot_ID", "Strip_ID"]

# 기존 03_impact_factor_ranking.csv와 동일한 층: Machine을 통제변수로 두는 분석용.
GROUP = ["Machine_ID", "Product_ID", "Recipe_ID"]

# 멘토 피드백: Strip_ID/Lot_ID는 로트 추적용 식별자일 뿐 "운전조건"이 아니다.
# 장비를 비교 대상으로 두거나 Machine-무관 baseline이 필요할 때는 GROUP 대신 OPCOND를 쓴다.
OPCOND = ["Product_ID", "Recipe_ID"]


def NORMAL(frame):
    """정상군 정의: Yield=100 그리고 NG_Code='OK' (기존 스크립트와 동일)."""
    return (frame["Yield"] == 100) & (frame["NG_Code"] == "OK")


# 멘토 피드백: 아래 4개는 로트 추적/작업자 식별용으로, 분석 피처로는 부적합하다고 판단됨.
# 원본 데이터프레임에는 남기되(추적성 보존), 피처셋 구성 시 기본 제외한다.
EXCLUDED_IDENTIFIERS = ["Shift", "Lot_ID", "Strip_ID", "Operator_ID"]

# (26.08.07) 멘토가 준 입력(SPEC / MENTOR_EXCLUDED_VARS / MENTOR_DOMAIN_NOTES /
# MENTOR_EXCLUDED_DEFECTS / MENTOR_PENDING_REVIEW)은 pipeline/mentor.py로 옮겼다 —
# 이 파일은 "우리가 정한 값", mentor.py는 "밖에서 받은 사실"이다. 섞여 있으면 어느 게
# 바꿔도 되는 값인지 매번 헷갈린다(BASELINE_C_DEFECT_MAP 근거 주석이 낡은 채 방치됐던
# 것과 같은 종류의 문제). 위 EXCLUDED_IDENTIFIERS는 멘토 피드백을 반영했지만 최종
# 판단은 팀이 한 것이라 여기 남긴다.


ID_PRODUCTION_COLS = [
    "DateTime", "Machine_ID", "Product_ID", "Shift",
    "Lot_ID", "Strip_ID", "Recipe_ID", "Operator_ID",
]

# fdc_response_defect_parameter_discription.docx 기준 서브시스템 분류.
SUBSYSTEMS = {
    "fdc_laser": [
        "Laser_Power", "Power_Efficiency", "Laser_Centering_Position",
        "Laser_Current", "Laser_Voltage", "Beam_Diameter",
        "Frequency",  # 멘토 피드백(26.07.31): 레이저 변수로 확인됨 — fdc_motion에서 이동
    ],
    "fdc_motion": [
        "Feed_Speed", "Alignment_Time", "Process_Time",
        "Cutting_X_Index", "Cutting_Y_Index",
    ],
    "fdc_thermal": ["Head_Temp", "Cooling_Flow", "Cooling_Water_Temp", "Focus"],
    "fdc_cleaning": [
        "CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
        "Laser_Head_Remain_Time",
    ],
    "fdc_mechanical": ["Vibration"],
    "response": [
        "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
        "Groove_Depth", "Package_Size_1", "Package_Size_2", "Package_Size_3",
        "Package_Size_4", "Coating_Thickness", "Coating_Uniformity",
        "Cutting_Offset", "Surface_Roughness",
    ],
    "defect_binary": [
        "Chipping", "Remain_Coat", "Particle", "Micro_Crack",
        "Laser_Paim", "Edge_Burn",
    ],
    "defect_count": [
        "Chipping_Die", "Remain_Coat_Die", "Particle_Die", "Micro_Crack_Die",
        "Laser_Paim_Die", "Edge_Burn_Die", "Fail_Die",
    ],
    # 공정 결과 라벨: Yield(연속 %), NG_Code(범주형) — 피처가 아니라 결과이므로 별도 취급.
    "outcome": ["Yield", "NG_Code"],
    "undocumented_env_or_infra": [
        "PLC_CPU_Load", "PLC_Memory", "Network_Latency", "LED_Brightness",
        "Room_Noise", "Door_Open_Count", "Fan_RPM", "Vision_Exposure",
        "Maintenance_Count", "Factory_Power",
    ],
}

RESPONSES = SUBSYSTEMS["response"]
DEFECTS_BINARY = SUBSYSTEMS["defect_binary"]
DEFECTS_COUNT = SUBSYSTEMS["defect_count"]
FDC_COLS = (
    SUBSYSTEMS["fdc_laser"] + SUBSYSTEMS["fdc_motion"] + SUBSYSTEMS["fdc_thermal"]
    + SUBSYSTEMS["fdc_cleaning"] + SUBSYSTEMS["fdc_mechanical"]
)

# 미문서화 컬럼별 판단 근거. 전부 "1차 제외"가 아니라 컬럼별로 근거를 남긴다.
UNDOCUMENTED_COL_NOTES = {
    "PLC_CPU_Load": "설비 IT 인프라 텔레메트리로 추정, 공정 물리량 아님 — 1차 제외.",
    "PLC_Memory": "설비 IT 인프라 텔레메트리로 추정, 공정 물리량 아님 — 1차 제외.",
    "Network_Latency": "네트워크 인프라 지표로 추정, 공정 물리량 아님 — 1차 제외.",
    "LED_Brightness": "비전검사 조명 조건으로 추정, 공정 물리량 아님 — 1차 제외.",
    "Room_Noise": "환경 텔레메트리로 추정, 공정 물리량 아님 — 1차 제외.",
    "Door_Open_Count": "환경/보안 이벤트 카운트로 추정, 공정 물리량 아님 — 1차 제외.",
    "Fan_RPM": "설비 냉각팬 등 인프라 지표로 추정, 공정 물리량 아님 — 1차 제외.",
    "Vision_Exposure": "비전검사 카메라 노출값으로 추정, 공정 물리량 아님 — 1차 제외.",
    "Maintenance_Count": (
        "정비 이력 프록시로 추정 — 정비 직후/직전 열화 패턴과 연관될 수 있어 "
        "Goal2(유효인자 발굴)/Goal4(이상탐지)에서 후속 확인 가치 있음. 1차 제외하지 않고 보류."
    ),
    "Factory_Power": "공장 전력 인프라 지표로 추정, 공정 물리량 아님 — 1차 제외.",
}

# 미문서화 컬럼 중 1차 제외 대상 (Maintenance_Count 제외).
UNDOCUMENTED_EXCLUDED = [
    c for c in SUBSYSTEMS["undocumented_env_or_infra"] if c != "Maintenance_Count"
]

# 물리적으로 0이 나올 수 없는(0=센서 드롭아웃 의심) 연속형 FDC 컬럼만 큐레이션.
# 전체 컬럼에 일괄 적용하지 않는다 (예: Cutting_Offset은 부호있는 값이라 0이 정상일 수 있음).
ZERO_IMPLAUSIBLE_COLS = [
    "Cooling_Flow", "CLN_Flow", "CLN_Pressure", "Laser_Power",
    "Feed_Speed", "Coating_Flow", "CLN_Time", "Vibration",
]

# 연속형 변동성 분류 임계값 (median CV 기준). config에서 관리해 매직넘버를 피한다.
CV_STABLE_THRESHOLD = 0.02   # 이 미만이면 '거의 고정값' (stable, 센서 고착 의심 후보)
CV_VARIABLE_THRESHOLD = 0.10  # 이 이상이면 '변동성 큼' (variable)
# [STABLE_THRESHOLD, VARIABLE_THRESHOLD) 구간은 'moderate'.

FLATLINE_RUN_LENGTH = 5  # 동일값이 이 길이 이상 연속되면 flatline(고착) 의심

# 추세검정 유의수준
TREND_ALPHA = 0.05

# 정규화 시 MAD -> 표준편차 근사 스케일 상수 (정규분포 가정 시 1.4826)
MAD_SCALE = 1.4826

# 기존 analysis_step_by_step.py의 4개 도메인 비율 피처와 동일 정의 (재사용, 재구현 금지).
def add_domain_features(df):
    result = df.copy()
    result["Cooling_Thermal_Load"] = result["Cooling_Water_Temp"] / result["Cooling_Flow"]
    result["Laser_Cleaning_Demand"] = result["Laser_Power"] * result["Groove_Depth"]
    result["Cleaning_Capacity"] = result["CLN_Flow"] * result["CLN_Pressure"] * result["CLN_Time"]
    result["Cleaning_Load_Ratio"] = result["Laser_Cleaning_Demand"] / result["Cleaning_Capacity"]
    # 멘토 피드백(26.07.31): Package_Size_1~4는 방향(동서남북) 특정 불필요하다고 확인됨.
    # 센터링이 틀어지면 한쪽은 커지고 반대쪽은 작아지는 비대칭 패턴이 생긴다는 도메인 힌트를
    # "4개 값의 행별 표준편차"로 수식화 — 어느 쌍이 마주보는 방향인지 몰라도 계산 가능하다.
    package_cols = ["Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4"]
    result["Package_Size_Asymmetry"] = result[package_cols].std(axis=1)
    return result


DOMAIN_FEATURES = [
    "Cooling_Thermal_Load", "Laser_Cleaning_Demand", "Cleaning_Capacity", "Cleaning_Load_Ratio",
    "Package_Size_Asymmetry",
]

# ---------------------------------------------------------------------------
# Baseline 유형(A/B/C/E) — Jun 브랜치 `26.07.29 Baseline 관련 작업/`에서 이식.
# 열화 패턴 성격이 컬럼마다 달라 baseline 산출 방식도 유형별로 다르다:
#   A(단조 drift형)  = 초기 안정구간 평균, 악화 방향 존재
#   B(U자형/최적구간형) = OK 데이터 median, 방향 없음(양쪽 다 위험)
#   C(편측 위험 threshold형) = OK/NG 라벨로 결정트리 스텀프 학습한 위험 경계값
#   E(대칭성/정렬형)  = 데이터가 아니라 공정 설계상 이론적 상수값
# 그룹핑은 Product_ID x Recipe_ID(OPCOND)만 사용, Machine_ID는 배제한다 — Jun 실측 결과
# A유형 컬럼의 Recipe별 평균 변동이 그룹 내부 변동의 1~2% 수준이라 Machine 구분 실익이 적었음.
# ---------------------------------------------------------------------------

# A유형(8개): 컬럼명 -> 악화 방향 (True = 값이 올라갈수록 악화, False = 값이 내려갈수록 악화)
BASELINE_A_DIRECTION = {
    "Head_Temp": True,
    # Vibration(26.08.05 재검토): 한때 Particle과 NG 7,792건/54그룹 전부 통과로 결정트리
    # threshold를 만들어 C유형으로 옮겼었으나, 이 방법 자체의 함정을 발견해서 되돌린다 —
    # 관련 없는 변수 19개(Cutting_Y_Index, Process_Time 등)에 같은 방법을 적용해봐도
    # Remain_Coat 기준 2.36~3.5배, Particle 기준 1.67~2.35배 불량률 "점프"가 항상
    # 나온다(결정트리가 표본 안에서 가장 잘 갈리는 지점을 고르는 이상, 순수 노이즈에도
    # 이 정도 분리는 항상 생김 — 다중비교 편향). Vibration→Particle의 실제 분리력은
    # 2.2배로 이 노이즈 범위(1.67~2.35) 안에 들어가 통계적으로 구분이 안 된다
    # (대조: CLN_Pressure→Remain_Coat 20.8배, Surface_Roughness→Particle 16.7배 —
    # 노이즈 천장을 6~10배 넘어서 확실히 진짜). 시간분할 안정성 검증(전/후반 threshold
    # 거의 일치)을 통과했던 건 "패턴이 안정적"이었다는 것이지 "인과관계가 진짜"라는
    # 증거는 아니었다. A유형(target 기반 CUSUM)으로 되돌린다.
    # (26.08.08 재확인) 감시 데이터 기준 정식 스캔에서도 같은 결론이다 — Particle 2.26
    # vs 순열 천장 2.33, Remain_Coat 2.76 vs 천장 3.38로 둘 다 천장 아래다. 다만
    # **아슬아슬하다**는 건 기록해둔다(Particle은 천장의 97%). 위 주석이 근거로 든
    # "무관한 변수 19개의 노이즈 범위" 같은 임시 대조군은 이제 안 쓴다 — 순열검정이
    # 그 역할을 정식으로 한다.
    "Vibration": True,
    "Alignment_Time": True,
    "Process_Time": True,
    "Cooling_Flow": False,
    "Cooling_Water_Temp": True,
    # CLN_Flow(26.08.06 재분류): C유형 재검증 스캔에서 발견 — BASELINE_C_DEFECT_MAP
    # 주석 참고. A유형에서 빠지고 C유형(CLN_Flow -> Remain_Coat)으로 옮겼다.
    "Coating_Flow": False,
    # Groove_Depth(26.08.05 추가): Chipping 확정 원인(Jun, direction=down이 위험)인데
    # A/B/C/E 어디에도 없어서 trend_analysis.py가 이 컬럼에 방향성 조기경보를 전혀 못
    # 내고 있었다(variability_warning만 가능) — 단일 방향 편차형이라 A유형이 맞음.
    # C유형에서 빠진 이유(BASELINE_C_DEFECT_MAP 주석 참고: 원본 데이터 Chipping 4건뿐이라
    # 표본 부족)와는 별개 문제 — A유형은 OK-median 기준 baseline이라 표본 부족 문제 없음.
    "Groove_Depth": False,
}

# B유형(8개 = 원 7개 + CLN_Time 재분류). CLN_Time은 원래 C유형(편측임계) 후보였으나
# 그룹별 위험 방향이 일관되지 않아(54그룹 중 29 low-risky/25 high-risky, 신호도 약함)
# B유형으로 재분류됨 — 근거는 BASELINE_C_DEFECT_MAP 학습 결과.
BASELINE_B_COLUMNS = [
    "Laser_Power", "Power_Efficiency", "Focus", "Beam_Diameter",
    "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "CLN_Time",
    # (26.08.05 추가) 이전엔 타입 없음(NONE)이라 방향성 조기경보가 아예 안 나갔던 7개 중 6개.
    # 89일 전체가 추세 없이 안정적인 노이즈라 A(단조 열화)는 안 맞고, 물리적으로 "정상값에서
    # 벗어나면 양쪽 다 위험"인 공정 파라미터라 이미 B로 분류된 Laser_Power/Power_Efficiency와
    # 같은 성격으로 판단해 B로 편입. Frequency/Feed_Speed/Coating_Thickness/Coating_Uniformity는
    # 멘토 스펙 있음. Laser_Current/Laser_Voltage는 스펙 없고 4개 defect 전부와 상관 r≈0이라
    # 방향성 근거가 없어서(=A유형처럼 "나쁜 방향"을 특정할 근거 없음) B로.
    "Frequency", "Feed_Speed", "Coating_Thickness", "Coating_Uniformity",
    "Laser_Current", "Laser_Voltage",
]
# Coating_Thickness(26.08.08): **C유형 승격 대기 중.** 유형 재검증 스캔(감시 데이터 기준)에서
# Remain_Coat 분리 18.52배로 이미 C인 CLN_Flow(20.93)/CLN_Pressure(19.81)와 같은 급이고,
# 54그룹 전부 low_is_risky로 방향이 일치한다(순열 천장: 분리 3.38 / 방향일관성 0.744).
# 경계 9.699는 멘토 LSL 9.5보다 **위**라 스펙 감시로는 안 잡힌다 — 위험구간 2,263샷 중
# 2,218샷(98.0%)이 스펙 안이고, 그 구간의 Remain_Coat 발생률이 29.9% (스펙 안 나머지는 1.7%).
# 커버리지: 기존 C 2개로 Remain_Coat의 69.3%를 잡는데, 이걸 더하면 94.8%가 된다(단독 기여
# 593건). 그런데도 여기 B로 남겨둔 이유는 **짝짓기의 단일 출처가 Goal2 관계DB**이기 때문이다
# (26.08.08 확정). 관계DB의 Remain_Coat 행은 CLN_Pressure/CLN_Flow 둘뿐이라 이 짝은 기각된
# 게 아니라 평가 대상이 아니었다 — JHdaimma님께 tier 판정 요청 중. 판정이 오면 C로 옮긴다.
# 참고: B->C로 바꿔도 멘토 스펙 검사는 그대로다(trend_analysis의 스펙 위반 판정은 유형과
# 무관하게 공통 적용). 바뀌는 건 CUSUM이 양측->편측(하강만)이 되고 threshold 진입 감시가
# 붙는 것뿐이다. 현재 양측 CUSUM 경보 602건은 상승 317 / 하강 285로 4대에 고르게 흩어져
# 있어(추세 없는 노이즈의 서명) 상승 쪽을 잃는 손실은 크지 않다.
# Laser_Head_Remain_Time: 타입 배정 보류. 이름은 "헤드 잔여수명"인데 실측 확인 결과 연속 샷
# 간 diff의 표준편차(1622~1637)가 전체 분포 자체의 표준편차(1152)보다 커서 자기상관이
# 0에 가깝다 — 서서히 줄어드는 소모품이 아니라 매 샷이 독립적인 난수에 가까움(장비 4대
# 전부 동일 패턴, defect 4종과도 상관 r≈-0.005~+0.002). "정상값"이라는 개념 자체가
# 안 맞아서 A/B/C/E 어디에도 넣지 않는다 — 전처리(rolling 통계)까지만 계산되고
# early_warning 판정에는 안 쓰인다(00_column_classification.csv에는 계속 continuous/
# predictor로 남아 rolling 통계 자체는 참고용으로 볼 수 있음).

BASELINE_C_MIN_SAMPLES_LEAF = 10  # 그룹별 NG 표본이 이 수 미만이면 경계값 추정 skip

# (26.08.08) C유형 "평소 위험구간 진입률"을 어느 구간에서 잴 것인가 — SPC의 Phase I
# (관리한계를 정하는 안정 구간) / Phase II(그 한계로 감시) 구분에 해당한다.
# 예전엔 89일 전체 x 전체 샷으로 쟀는데 두 방향으로 오염됐다(김시우님 지적):
#   (1) 불량 샷이 baseline에 포함 — 불량 샷은 정의상 위험구간에 있을 확률이 높다.
#   (2) 열화 기간의 OK 샷도 포함 — "OK"는 "조건이 정상"이 아니라 "이번엔 안 터짐"이라,
#       분포가 통째로 밀린 뒤의 OK 샷도 위험구간에 들어가 있다.
# 그 결과 열화가 심할수록 자기 baseline이 올라가 경보 문턱이 같이 올라가는 자기강화
# 루프가 생겼다 — DP02 Surface_Roughness는 baseline 63.69%까지 올라가 경보선(2배)이
# 127%가 되어 도달 자체가 불가능했다. 실측: 안정구간 x OK샷으로 재면 4대가 22.3~23.8%
# 로 수렴한다(동일 사양 장비니 이게 맞는 그림). 89일 전체로는 22~56%로 벌어진다.
C_BASELINE_MIN_STABLE_DAYS = 14  # Phase I 구간이 이보다 짧으면 추정을 포기(표본 부족)

# (26.08.08) C유형 "위험구간 진입이 평소보다 많다"의 판정 기준. 예전엔 평소 비율의
# 2.0배(trend_analysis.C_DANGER_RATE_MULTIPLE / build_health_index.DEFECT_ZONE_SPECOUT_
# MULTIPLE)라는 고정 배수였는데, 그러면 평소 비율이 낮은 컬럼은 노이즈에도 뜨고 높은
# 컬럼은 진짜 열화에도 안 뜬다(근거 수치는 common.binomial_alert_count 주석 참고).
# 배수 대신 **오탐 확률**을 고정한다 — 어느 컬럼이든 "평소 상태에서 이만큼 나올 확률이
# 1% 미만"일 때 경보. 스펙 위반 연속 판정(SPEC_RUN_EXPECTED_MAX)이 이미 쓰는 방식과 같다.
C_DANGER_ALPHA = 0.01

# (26.08.05 추가) 멘토 스펙이 있는 컬럼 중 실측 평균이 TARGET에서 스펙 폭(USL-LSL)의 10%
# 이상 벗어난 건 Kerf_Width_Profile(12.0%)과 Coating_Uniformity(13.3%) 둘뿐이었다(나머지
# 8개는 0.0~1.8%로 거의 정확히 일치 — 멘토 스펙 자체의 신뢰도가 높다는 근거). 이 중
# Kerf_Width_Profile/Coating_Uniformity 둘 다, 89일 내내 이 오프셋이 전혀 안 줄어들고
# (추세 아님, 처음부터 계속 벗어나 있음) 그 결과 Type B의 "지속적으로 벌어지는 편차"
# 로직이 국소적인 정상 흔들림만으로 반복 오탐을 냈다(Kerf_Width_Profile 153+110건,
# Coating_Uniformity는 CUSUM 적용 후 88,764건 — 전체 경고의 67%). LSL/USL은 멘토 값을
# 그대로 신뢰하고 TARGET만 실측(OK median)으로 재계산한다 — "스펙을 벗어나면 안 된다"는
# 경계는 유지하되 "정상일 때 어디에 있어야 하는가"는 실측을 따르는 것. (26.08.05 확정)
TARGET_RECOMPUTE_FROM_DATA = {"Kerf_Width_Profile", "Coating_Uniformity"}

# C유형 컬럼 -> 매칭 Defect 플래그 컬럼.
#
# (26.08.08) 이 값은 이제 **폴백**이다 — 정상 경로는 Goal2 관계DB에서 읽는다
# (common.load_defect_pairing_from_db). 여기 손으로 적힌 3개가 DB의 판정과 우연히
# 일치하는 상태였는데, 수동 사본이라 DB가 갱신되면 조용히 어긋난다. DB 파일이 없거나
# 스키마가 바뀌면 이 값으로 되돌아간다(파이프라인이 안 멈추게).
#
# CLN_Time(방향 불일치 -> B로 재분류)과 Groove_Depth(매칭 defect인 Chipping 발생이
# 전체 4건뿐이라 표본 부족)는 여기서 제외됨.
#
# ---------------------------------------------------------------------------
# (26.08.08) 유형 배정 재검증 — 스캔을 R1이 아니라 **감시 데이터(원본)** 로 돌린다
# ---------------------------------------------------------------------------
# 26.08.07에 만든 scan_type_c_candidates를 threshold_source(=R1)로 돌리고 있었는데,
# R1은 불량 시나리오를 의도적으로 주입한 학습셋이라 거기서 나온 분리배수는 주입 레시피를
# 되읽은 값이다. 실제로 두 데이터셋의 답이 달랐다(Remain_Coat 기준, 신호/노이즈):
#
#            컬럼              R1     원본     비고
#   Coating_Thickness         2.69 -> 6.47   R1이 진짜 신호를 **묻고** 있었음
#   CLN_Pressure              2.07 -> 6.92   위와 같음(배정된 C인데도 R1에선 약해 보임)
#   Vibration                 1.65 -> 0.96   R1에서만 보이던 가짜
#   Bottom_Kerf               2.63 -> 0.96   위와 같음
#   Laser_Centering_Position  2.21 -> 0.94   위와 같음
#
# R1에서는 18개 컬럼이 2.0~2.7배에 뭉쳐 구분이 안 됐는데, 원본에서는 3개(18.5~20.9배)와
# 나머지 31개(<=1.0배)로 깨끗이 갈린다. threshold "값"은 표본 때문에 R1에서 배우되,
# "어느 컬럼이 어떤 유형인가"는 실제 감시하는 데이터에서 판단해야 한다.
#
# 판정 기준은 warn_type_c_mismatch docstring에 있고, 두 컷 모두 순열에서 나온다(사람이
# 고른 상수 없음). 원본 기준 전 컬럼 x 전 defect 스캔 결과:
#   통과: Surface_Roughness->Particle(17.74), CLN_Flow->Remain_Coat(20.93),
#         CLN_Pressure->Remain_Coat(19.81)  = 배정된 3건 그대로
#         + Coating_Thickness->Remain_Coat(18.52) = 미배정(위 B목록 주석 참고)
#   기각: Particle 후보 3개(CLN_Flow 3.53 / Coating_Thickness 3.09 / CLN_Pressure 2.74)는
#         Remain_Coat를 통제하니 32~37% 잃고 천장(2.33) 아래로 내려간다 — 교란이다.
#         대조로 Surface_Roughness->Particle은 같은 통제에서 17.7 -> 259.7로 오히려
#         강해진다(독립 원인의 서명). 관계DB의 alert_usable=False 판정과 같은 결론.
#
# 한계: Chipping(원본 4건) / Micro_Crack(41건) / Laser_Paim(0건)은 스텀프가 그룹당
# min_samples_leaf를 못 채워 스캔 자체가 성립하지 않는다. 이 셋의 유형 배정은 데이터로
# 검증할 수 없고 도메인/관계DB 근거로만 간다 — 스캔 결과표에 아예 행이 없는 이유다.
BASELINE_C_DEFECT_MAP = {
    "CLN_Pressure": "Remain_Coat",
    "Surface_Roughness": "Particle",
    # Vibration은 한때 여기 있었으나(NG 7,792건, 54그룹 전부 통과, 시간분할 안정성도 통과)
    # 위 BASELINE_A_DIRECTION의 Vibration 주석 참고 — 표본/안정성 조건은 통과해도 실제
    # 불량률 분리력이 무관한 변수들의 노이즈 수준과 구분이 안 돼서 A유형으로 되돌렸다.
    #
    # (26.08.07) 이 판단의 근거 수치를 여기 주석에 박아두지 않는다 — 예전엔
    # "CLN_Pressure 20.8배 / Surface_Roughness 16.7배"라고 적어놨는데, 파이프라인 밖
    # 일회성 코드로 한 번 재고 주석에만 남긴 값이라 데이터가 바뀌어도 아무도 갱신하지
    # 않았고 실제로 현실과 어긋나 있었다(R1 기준 재계산 시 CLN_Pressure는 4.4배).
    # 이제 step0의 scan_type_c_candidates가 매 실행마다 전 컬럼을 스캔하고 순열검정으로
    # 노이즈 천장을 다시 구해서 00_baseline_C_candidates.csv로 남긴다. 최신 수치는 항상
    # 그 파일을 볼 것. 여기 배정된 3건이 천장 아래로 내려가면 step0가 경고를 띄운다.
    # CLN_Flow(26.08.06 추가): 기존 C유형 2개 이외 32개 컬럼(A/B/E 전체) x 4개 defect를
    # 같은 결정트리 방법으로 전수 스캔해서 찾았다(그 스캔이 26.08.07에 파이프라인 안으로
    # 들어온 scan_type_c_candidates다). Remain_Coat 기준 노이즈 천장을 압도적으로 넘고,
    # 시간분할 검증(전반 threshold=9.82/후반=9.70, 방향 둘 다 low_is_risky)도 통과. CLN_Pressure와 상관계수 -0.004(거의 무관)라 같은 세정 공정의 독립적인
    # 별도 원인. 물리적으로도 타당(세정 유량 부족 -> 코팅 잔류물이 안 씻김).
    # 주의: 장비별로 쪼개보면 CLN_Flow가 9.7 밑으로 내려간 샷이 전체 R1에서 DP04
    # 뿐이다(DP01/02/03은 0건 — 애초에 그 구간에서 운전한 적이 없음). 즉 이 24.8배는
    # "물리 법칙이 4대 공통"이 아니라 "DP04만 저유량 구간에서 실제로 운전했고, 거기서
    # 불량이 급증한다"는 뜻 — 26.08.05_Goal2_통합_Relationship_DB_JHdaimma의 전성재님
    # 매개분석(Goal1, "DP04 한정 원인", build_unified_relationship_db.py의 SEONGJAE_ROLE/
    # DISPUTE_REASON["Remain_Coat","CLN_Flow"])과 정확히 같은 결론이라 교차검증된 셈이다.
    # group_key가 Product x Recipe뿐이라(Machine_ID 없음) 이 threshold는 4대에 공통
    # 적용되지만, DP01/02/03은 그 구간에 아예 안 내려가므로 실질적으로 오탐은 안 난다
    # — 다만 "CLN_Flow는 4대 공통 위험 threshold"라고 서술하면 안 되고 "DP04의 저유량
    # 이력이 만든 threshold"라고 정확히 말할 것.
    # 같은 스캔에서 Chipping/Micro_Crack은 신뢰 불가로 판단해 전부 기각했다 — Chipping
    # 일별 불량률 자체가 전반 9.2%->후반 39.1%로 4배 넘게 요동쳐서, Package_Size처럼
    # 물리적 연관이 없는 컬럼까지 5~84배 "분리"가 나오는 시간축 교란 때문(별도 시간
    # 통제 없이는 이 방법으로 Chipping/Micro_Crack의 threshold를 못 찾는다).
    "CLN_Flow": "Remain_Coat",
}

# E유형(9개): 데이터 분포가 아니라 공정 설계상 "완벽하게 맞았을 때"의 이론 상수값.
# 정렬/대칭 편차형(목표 대비 편차 -> 이상값 0, Kerf_Angle만 완전 수직 90도) + 치수형(목표 5).
BASELINE_E_CONSTANTS = {
    "Laser_Centering_Position": 0,
    "Cutting_X_Index": 0,
    "Cutting_Y_Index": 0,
    "Cutting_Offset": 0,
    "Kerf_Angle": 90,
    "Package_Size_1": 5,
    "Package_Size_2": 5,
    "Package_Size_3": 5,
    "Package_Size_4": 5,
}

EXPECTED_ROW_COUNT = 100_000
EXPECTED_NORMAL_COUNT = 90_783
