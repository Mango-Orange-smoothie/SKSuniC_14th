"""파이프라인 전역 상수.

모든 Step0/Goal 모듈은 KEY/GROUP/OPCOND/NORMAL 등을 여기서만 import한다.
각자 재정의하면 층(stratum) 정의가 모듈마다 미묘하게 어긋날 수 있다.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUT_CSV = ROOT / "data" / "raw" / "DP_HealthIndex_Dataset.csv"
OUTPUT_DIR = ROOT / "analysis_outputs"
PREPROCESSING_DIR = OUTPUT_DIR / "preprocessing"

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

# 멘토 피드백(26.07.31): 데이터 제공 시 "분석에 활용하지 않아도 되는 변수"로 명시적으로
# 지정됨. FDC/response 값이라 원본 데이터프레임에는 남기되, 피처셋에서는 제외한다.
# 주의: Focus는 Jun의 BURN 분석(Goal2)에서 이미 도메인 후보로 포함돼 있었으므로
# 이 변경 이후 재실행이 필요할 수 있다 — Jun에게 공유할 것.
MENTOR_EXCLUDED_VARS = ["Focus", "Cutting_Offset"]
MENTOR_EXCLUDED_VARS_NOTE = "멘토가 데이터 제공 시 분석에 활용하지 않아도 된다고 명시적으로 지정한 변수 (26.07.31 피드백)."

# 멘토 피드백(26.07.31) — 제외가 아니라 "참고" 성격의 도메인 지식. 통계 분석 시
# 단순 선형/단조 상관만 보지 말고 임계값 효과 가능성을 염두에 둘 것.
MENTOR_DOMAIN_NOTES = {
    "Frequency": "멘토 피드백: 레이저 변수로 확인됨 (fdc_laser로 재분류).",
    "Laser_Head_Remain_Time": (
        "멘토 피드백: 헤드 내 11개 스팟, 스팟당 기준수명 약 2000시간(가상데이터라 그대로 "
        "적용 안 될 수 있음). 잔여시간이 적게 남거나 특정 시점(교체/오버 시점)을 지날 때 "
        "불량이 발생하는 임계값성 패턴이 있을 수 있음 — 선형 상관보다 구간별/임계값 "
        "기반 분석(예: 잔여시간 구간화 후 불량률 비교)을 함께 검토할 것."
    ),
    "Power_Efficiency": (
        "멘토 피드백: 비선형(U자형/최적구간) 특성 — 효율이 높아져도 낮아져도 불량과 "
        "연관될 수 있음. 단순 선형/단조 상관(Mann-Whitney 등)으로만 해석하지 말 것, "
        "|편차| 기준 검정이나 구간화 분석을 함께 검토할 것."
    ),
    "Vibration": (
        "멘토 피드백: 설비 열화(degradation)의 대표 신호. 실제 사고 사례(노후 장비 Y축 "
        "이동 시 진동으로 빔 라인 어긋남 → 대량 스크랩)가 있었음 — Health Index(Goal5) "
        "핵심 후보 변수로 우선 고려할 것."
    ),
    "Kerf_Width_Profile": (
        "멘토 피드백: '7㎛ 지점' 기준으로 정의된 값이지만, 이 합성 데이터에서는 생성 시 "
        "정확히 7㎛로 고정되지 않고 임의 baseline을 썼을 수 있음 — 7㎛를 물리 상수로 "
        "하드코딩하지 말고, baseline을 데이터 분포(정상군 median 등)에서 역산해서 쓸 것 "
        "(Step0의 OK-baseline 방식이 이미 이 원칙을 따름)."
    ),
    "Top_Kerf": "멘토 피드백: Kerf_Width_Profile과 동일한 '7㎛ 기준점 아님' 주의사항 적용.",
    "Groove_Depth": (
        "멘토 피드백: 기준 깊이(7㎛) 대비 편차값이지만, 이 데이터에서 7㎛가 실제 물리 "
        "상수가 아닐 수 있음 — Kerf_Width_Profile과 동일 주의사항, baseline은 데이터로 역산."
    ),
    "Package_Size_1": "멘토 피드백: 4방향(동서남북) 중 하나, 방향 특정 불필요. 센터링 이상 시 비대칭 패턴 발생 — Package_Size_Asymmetry(팀 공용 피처) 참고.",
    "Package_Size_2": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Package_Size_3": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Package_Size_4": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Head_Temp": (
        "멘토 피드백: Head_Temp -> 크리스탈 스팟 온도 변화 -> 굴절률 변화 -> "
        "Laser_Centering_Position 변화 -> Chipping/Kerf 불균일로 이어지는 인과사슬 가설. "
        "Cooling_Flow/Cooling_Water_Temp/Laser_Centering_Position과 함께 묶어 다변량 분석 권장."
    ),
    "Laser_Centering_Position": "멘토 피드백: Head_Temp 인과사슬의 종착점 — 레이저 품질 이상의 핵심 원인 중 하나로 반복 언급됨.",
}

# 멘토 피드백(26.07.31) — 아직 최종 확정이 아니라 "재확인 예정"으로 남은 항목.
# 함부로 제외하지 않고 include_in_downstream_default=True로 유지하되, 강한 경고를 남긴다.
# 특히 Edge_Burn은 Jun의 Goal2 BURN 분석 전체가 이 컬럼을 라벨로 쓰고 있어 영향이 크다 —
# 멘토 재확인 전까지 절대 임의로 제외하지 말 것.
MENTOR_PENDING_REVIEW = {
    "Edge_Burn": (
        "⚠️ 멘토가 '듣도 보도 못한 현상, 무시해도 된다'며 제거를 시사했으나 "
        "최종 확정은 아니었음(잠정). Jun의 Goal2 BURN 분석 전체가 이 라벨을 쓰고 있으므로 "
        "재확인 전까지 절대 임의로 제외하지 말 것 — 멘토 재확인 최우선 필요."
    ),
    "Bottom_Kerf": "멘토가 다른 kerf 컬럼과 값 중복 여부, 순수 샘플링 값인지 재확인 예정이라고 했음 — 결과 해석 시 주의.",
    "Surface_Roughness": (
        "멘토가 drop 여부를 확정하지 않음('필요상 넣어놓은 컬럼'이라고만 언급) — Jun의 "
        "BURN/PARTICLE/CRACK confirmed 목록에 이미 등장하므로 최종 확정 전까지 결과 해석 시 주의."
    ),
    "Cooling_Flow": "멘토가 '컬럼을 다시 봐야겠다'며 설비-컬럼 매핑 재확인을 예고함 — 정확한 매핑 확정 전까지 결과 해석 시 주의.",
    "Cooling_Water_Temp": "멘토가 '컬럼을 다시 봐야겠다'며 설비-컬럼 매핑 재확인을 예고함 — 정확한 매핑 확정 전까지 결과 해석 시 주의.",
}

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

EXPECTED_ROW_COUNT = 100_000
EXPECTED_NORMAL_COUNT = 90_783
