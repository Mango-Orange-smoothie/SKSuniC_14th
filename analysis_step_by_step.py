"""DP Health Index: 단계별 탐색 분석 스크립트.

실행 (저장소 루트에서):
  python analysis_step_by_step.py

원본 데이터 파일은 수정하지 않습니다. 분석 결과는 analysis_outputs/에 저장됩니다.

2026-08-01 업데이트: 도메인 가설(PROCESS)을 멘토링 정리본(`FDC_전처리_멘토링_정리.md`)과
Jun의 Goal2 개별 defect 분석(`DOMAIN_KNOWLEDGE.md`, BURN/PARTICLE/REM_COAT/CRACK/CHIP)
기준으로 다시 작성했다. 기존 버전은 냉각/코팅/세정 3개 공정, defect 3개(Edge_Burn 포함)만
다뤘는데, 다음 두 가지를 반영해 PARTICLE/REM_COAT/MICRO_CRACK/CHIPPING 4개 defect로
확장했다:
  1. Edge_Burn은 멘토 최종 확인 결과 유효한 실패모드가 아니라 분석 대상에서 제외됨
     (`pipeline/config.py`의 MENTOR_EXCLUDED_DEFECTS와 동일 결정).
  2. Focus/Cutting_Offset은 멘토가 분석 비활용을 명시한 변수라 후보에서 제외
     (`pipeline/config.py`의 MENTOR_EXCLUDED_VARS와 동일 결정).
KEY/GROUP/NORMAL/도메인 피처는 `pipeline/config.py`를 그대로 재사용한다 — 여기서 다시
정의하면 Step0와 기준이 어긋날 위험이 있다.
"""

from pathlib import Path
import json

import numpy as np
import pandas as pd

from pipeline import config
from pipeline.common import spearman

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "analysis_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

KEY = config.KEY
GROUP = config.GROUP
NORMAL = config.NORMAL

# 도메인 가설 그룹 (defect 1개당 1개 그룹). 출처: FDC_전처리_멘토링_정리.md +
# Jun의 Goal2 DOMAIN_KNOWLEDGE.md(PARTICLE/REM_COAT/CRACK/CHIP, 26.07.31).
# Focus/Cutting_Offset(멘토 제외 변수)은 후보에서 뺐다. Edge_Burn(멘토 제외 defect)은
# 그룹 자체를 없앴다.
PROCESS = {
    "particle": {
        # 핵심 가설: "디브리 발생량(레이저 어블레이션) vs 세정 능력"의 밸런스 문제.
        "fdc": [
            "Laser_Power", "Power_Efficiency", "Beam_Diameter",
            "CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
            "Laser_Head_Remain_Time", "Vibration",
        ],
        "responses": ["Groove_Depth", "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Surface_Roughness"],
        "domain_features": ["Laser_Cleaning_Demand", "Cleaning_Capacity", "Cleaning_Load_Ratio"],
        "defect_binary": "Particle",
        "defects": ["Particle", "Particle_Die"],
    },
    "remain_coat": {
        # 핵심 가설: 절단(레이저) 문제가 아니라 후속 세정 공정의 문제.
        # Jun의 REM_COAT 분석에서 레이저/빔 서브시스템 전체를 무관으로 판단한 것을 반영.
        "fdc": ["CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow", "Laser_Head_Remain_Time"],
        # Coating_Thickness/Coating_Uniformity는 Jun이 데이터 누수(측정 시점 불확실) 위험을
        # 지적해 후보에서 제외 — Surface_Roughness만 결과 공변 후보로 남긴다.
        "responses": ["Surface_Roughness"],
        "domain_features": ["Cleaning_Capacity", "Cleaning_Load_Ratio"],
        "defect_binary": "Remain_Coat",
        "defects": ["Remain_Coat", "Remain_Coat_Die"],
    },
    "micro_crack": {
        # 핵심 가설: 열충격(급격한 온도변화) + 기계적 피로. 멘토는 "레이저 그루빙 공정
        # 자체의 문제는 아닐 수 있다"고 했지만, 데이터 내 FDC 변수로 검증 가능한 가설만 후보로 둠.
        "fdc": [
            "Laser_Power", "Power_Efficiency", "Head_Temp", "Cooling_Flow", "Cooling_Water_Temp",
            "Beam_Diameter", "Laser_Centering_Position", "Vibration", "Feed_Speed", "Frequency",
            "Process_Time", "Alignment_Time", "Laser_Head_Remain_Time",
        ],
        "responses": ["Groove_Depth", "Surface_Roughness", "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf"],
        "domain_features": ["Cooling_Thermal_Load"],
        "defect_binary": "Micro_Crack",
        "defects": ["Micro_Crack", "Micro_Crack_Die"],
    },
    "chipping": {
        # 핵심 가설: 절단 경계 정렬/센터링 불량 + 기계적 불안정(진동). 팀 HealthIndex
        # 설계서에 가장 명시적 근거가 많이 남은 defect (Groove_Depth, Beam_Diameter, Vibration).
        "fdc": [
            "Beam_Diameter", "Vibration", "Head_Temp", "Laser_Head_Remain_Time",
            "Cutting_X_Index", "Cutting_Y_Index", "Laser_Centering_Position",
        ],
        "responses": [
            "Groove_Depth", "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle",
            "Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4",
            "Surface_Roughness",
        ],
        # Package_Size_Asymmetry: 멘토가 설명한 "센터링 틀어지면 한쪽은 커지고 반대쪽은
        # 작아지는 비대칭 패턴"을 수식화한 팀 공용 피처 (pipeline/config.py에서 생성).
        "domain_features": ["Package_Size_Asymmetry"],
        "defect_binary": "Chipping",
        "defects": ["Chipping", "Chipping_Die"],
    },
}


def save_table(table: pd.DataFrame | pd.Series, filename: str) -> None:
    """분석 표를 CSV로 저장한다. Excel에서도 바로 열 수 있다."""
    if isinstance(table, pd.Series):
        table = table.to_frame()
    table.to_csv(OUTPUT_DIR / filename, encoding="utf-8-sig")


def load_and_validate() -> pd.DataFrame:
    """1단계: 데이터 로드와 분석 키 검증."""
    df = pd.read_csv(config.INPUT_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["is_normal"] = NORMAL(df)

    summary = pd.DataFrame(
        {
            "value": [
                len(df),
                df[KEY].drop_duplicates().shape[0],
                int(df.duplicated(KEY).sum()),
                int(df["Strip_ID"].duplicated().sum()),
                int(df["is_normal"].sum()),
            ]
        },
        index=[
            "전체 행 수",
            "Lot_ID + Strip_ID 고유 건수",
            "Lot_ID + Strip_ID 중복 행 수",
            "Strip_ID 단독 중복 행 수 (분석키로 사용 금지)",
            "정상군 수 (Yield=100, NG_Code=OK)",
        ],
    )
    save_table(summary, "01_data_validation.csv")
    return df


def add_domain_features(df: pd.DataFrame) -> pd.DataFrame:
    """2단계: 도메인 가설에 맞는 상호작용/요구량 변수를 만든다.

    pipeline/config.py의 정의를 그대로 재사용한다 (Package_Size_Asymmetry 포함,
    재구현하지 않음 — 두 군데서 다르게 계산되는 사고를 방지).
    """
    return config.add_domain_features(df)


def correlation_screen(df: pd.DataFrame) -> None:
    """3단계: defect별 FDC-Response/Defect 상관 후보를 빠르게 선별한다."""
    records = []
    for stage, cols in PROCESS.items():
        inputs = cols["fdc"] + cols["domain_features"]
        outputs = cols["responses"] + cols["defects"]
        for x in inputs:
            for y in outputs:
                records.append(
                    {
                        "stage": stage,
                        "input": x,
                        "output": y,
                        "spearman_r_all": spearman(df[x], df[y]),
                        "spearman_r_normal": spearman(
                            df.loc[df["is_normal"], x], df.loc[df["is_normal"], y]
                        ),
                    }
                )
    result = pd.DataFrame(records)
    result["abs_r_all"] = result["spearman_r_all"].abs()
    result = result.sort_values("abs_r_all", ascending=False)
    save_table(result, "02_correlation_screen.csv")


def first_pass_impact_models(df: pd.DataFrame) -> None:
    """4단계: defect별 영향 인자를 1차 선별한다.

    Machine×Product×Recipe 안에서 defect 발생군과 정상군의 표준화된 평균 차이를
    계산한다. 제품/Recipe 차이로 생기는 가짜 상관을 줄인 선별 지표이며,
    인과관계 확정이 아니라 후속 검증 후보 순위다. 후보 피처는 PROCESS 딕셔너리의
    defect별 도메인 가설(fdc + domain_features)을 그대로 사용한다.
    """
    rankings = []
    for stage, cols in PROCESS.items():
        defect = cols["defect_binary"]
        features = cols["fdc"] + cols["domain_features"]
        for feature in features:
            effects = []
            for _, part in df.groupby(GROUP):
                positive = part.loc[part[defect] == 1, feature]
                negative = part.loc[part[defect] == 0, feature]
                if len(positive) < 3 or len(negative) < 10:
                    continue
                pooled_std = part[feature].std()
                if pd.notna(pooled_std) and pooled_std > 0:
                    effects.append(((positive.mean() - negative.mean()) / pooled_std, len(positive)))
            if effects:
                effect, weight = zip(*effects)
                weighted_effect = float(np.average(effect, weights=weight))
                rankings.append(
                    {
                        "defect": defect,
                        "feature": feature,
                        "weighted_standardized_difference": weighted_effect,
                        "absolute_effect": abs(weighted_effect),
                        "valid_strata": len(effects),
                    }
                )

    result = pd.DataFrame(rankings).sort_values(["defect", "absolute_effect"], ascending=[True, False])
    save_table(result, "03_impact_factor_ranking.csv")

    # Micro_Crack(41건)/Chipping(4건)처럼 극희귀 defect는 Machine×Product×Recipe 어느 층에도
    # 3건 이상 몰려있지 않아(실측: 최대 2건/1건) 이 방식(층별 3+/10+ 표본 요구)으로는
    # 구조적으로 결과가 안 나온다 — 버그가 아니라 표본 부족의 정직한 결과다. 이 두 defect는
    # 층 단위가 아닌 행 단위 검정(Jun/윤진혁의 Goal2 CRACK/CHIP 분석 방식)이 필요하다.
    covered = set(result["defect"]) if not result.empty else set()
    all_defects = {cols["defect_binary"] for cols in PROCESS.values()}
    missing = sorted(all_defects - covered)
    if missing:
        print(
            f"참고: {missing}는 층별(Machine×Product×Recipe) 표본 부족으로 이 방식에서 "
            "결과가 없음 — 극희귀 defect라 행 단위 검정(Jun/윤진혁 Goal2 분석 참고) 필요."
        )


def provisional_control_limits(df: pd.DataFrame) -> None:
    """5단계: 정상군에서 Product×Recipe별 임시 관리한계를 계산한다.

    공식 SPEC이 없으므로 이 값은 '통계적 경보 기준'이며 공식 판정 SPEC이 아니다.
    """
    normal = df.loc[df["is_normal"]].copy()
    measures = ["Coating_Uniformity", "Surface_Roughness"]
    output = []
    for measure in measures:
        grouped = normal.groupby(["Product_ID", "Recipe_ID"])[measure]
        frame = grouped.agg(
            normal_count="count",
            median="median",
            lower_warning=lambda x: x.quantile(0.005),
            upper_warning=lambda x: x.quantile(0.995),
        ).reset_index()
        frame.insert(0, "measure", measure)
        output.append(frame)
    save_table(pd.concat(output, ignore_index=True), "04_provisional_control_limits.csv")


def trend_table(df: pd.DataFrame) -> pd.DataFrame:
    """6단계: 설비별 일 단위 추세와 defect/Yield 결과.

    (26.08.07) 계산 자체는 pipeline/step0_preprocessing.py의 compute_machine_daily_trend로
    옮겼다 — 이 스크립트는 8/1 이후 정지된 초기 탐색용인데 이 산출물만 파이프라인 핵심으로
    남아 있었기 때문이다(build_health_index의 "최근 7일 실제 불량 발생" 판정과 agent.py의
    "언제 불량 났었어?" 조회가 둘 다 읽는다). 실행 순서 안내 어디에도 이 스크립트가 없어서,
    원본이 바뀌면 이 파일만 낡은 채 남을 위험이 있었다.

    여기서는 step0가 만든 결과를 읽어 쓰기만 한다 — 같은 계산을 두 벌 두면 갈라진다.
    """
    path = OUTPUT_DIR / "05_machine_daily_trend.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 없음 — 먼저 `python -m pipeline.step0_preprocessing`을 실행하세요."
        )
    return pd.read_csv(path)


def create_visual_data(df: pd.DataFrame, trend: pd.DataFrame) -> None:
    """7단계: 대시보드에 쓸 가볍고 재사용 가능한 집계 데이터 저장."""
    histogram = {}
    for col in ["Coating_Uniformity", "Surface_Roughness"]:
        edges = np.histogram_bin_edges(df[col], bins=32)
        histogram[col] = {
            "edges": edges.round(5).tolist(),
            "normal": np.histogram(df.loc[df.is_normal, col], bins=edges)[0].tolist(),
            "ng": np.histogram(df.loc[~df.is_normal, col], bins=edges)[0].tolist(),
        }
    machine_daily = trend[["Machine_ID", "date", "Head_Temp_7d_ma", "Yield_7d_ma"]].copy()
    machine_daily["date"] = machine_daily["date"].astype(str)
    data = {"histogram": histogram, "machine_daily": machine_daily.round(4).to_dict(orient="records")}
    with open(OUTPUT_DIR / "07_visual_data.json", "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)


def main() -> None:
    df = load_and_validate()
    df = add_domain_features(df)
    correlation_screen(df)
    first_pass_impact_models(df)
    provisional_control_limits(df)
    trend = trend_table(df)
    create_visual_data(df, trend)
    print(f"완료: 결과는 {OUTPUT_DIR}에 저장되었습니다.")


if __name__ == "__main__":
    main()
