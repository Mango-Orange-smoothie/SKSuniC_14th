"""DP Health Index: 단계별 탐색 분석 스크립트.

실행:
  python analysis_step_by_step.py

원본 Excel 파일은 수정하지 않습니다. 분석 결과는 analysis_outputs/에 저장됩니다.
"""

from pathlib import Path
import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).parent
INPUT_FILE = ROOT / "DP_HealthIndex_Dataset.xlsx"
OUTPUT_DIR = ROOT / "analysis_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

KEY = ["Lot_ID", "Strip_ID"]
GROUP = ["Machine_ID", "Product_ID", "Recipe_ID"]
NORMAL = lambda frame: (frame["Yield"] == 100) & (frame["NG_Code"] == "OK")

PROCESS = {
    "cooling_laser": {
        "fdc": ["Cooling_Flow", "Cooling_Water_Temp", "Head_Temp", "Vibration"],
        "responses": ["Cutting_Offset", "Focus"],
        "defects": ["Edge_Burn"],
    },
    "coating": {
        "fdc": ["Coating_Flow"],
        "responses": ["Coating_Thickness", "Coating_Uniformity"],
        "defects": ["Particle", "Particle_Die"],
    },
    "cleaning": {
        "fdc": ["CLN_Flow", "CLN_Pressure", "CLN_Time"],
        # 상류 레이저 공정 결과: 세정 요구량을 설명하기 위한 통제 변수
        "upstream": ["Laser_Power", "Groove_Depth"],
        "responses": ["Surface_Roughness"],
        "defects": ["Particle", "Particle_Die", "Remain_Coat", "Remain_Coat_Die"],
    },
}


def save_table(table: pd.DataFrame | pd.Series, filename: str) -> None:
    """분석 표를 CSV로 저장한다. Excel에서도 바로 열 수 있다."""
    if isinstance(table, pd.Series):
        table = table.to_frame()
    table.to_csv(OUTPUT_DIR / filename, encoding="utf-8-sig")


def load_and_validate() -> pd.DataFrame:
    """1단계: 데이터 로드와 분석 키 검증."""
    df = pd.read_excel(INPUT_FILE)
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
    """2단계: 도메인 가설에 맞는 상호작용/요구량 변수를 만든다."""
    result = df.copy()
    result["Cooling_Thermal_Load"] = (
        result["Cooling_Water_Temp"] / result["Cooling_Flow"]
    )
    result["Laser_Cleaning_Demand"] = result["Laser_Power"] * result["Groove_Depth"]
    result["Cleaning_Capacity"] = (
        result["CLN_Flow"] * result["CLN_Pressure"] * result["CLN_Time"]
    )
    result["Cleaning_Load_Ratio"] = (
        result["Laser_Cleaning_Demand"] / result["Cleaning_Capacity"]
    )
    return result


def correlation_screen(df: pd.DataFrame) -> None:
    """3단계: 공정별 FDC-Response/Defect 상관 후보를 빠르게 선별한다."""
    # scipy 없이도 Spearman 상관을 계산한다: 각 변수의 순위를 Pearson 상관한다.
    def spearman(x: pd.Series, y: pd.Series) -> float:
        paired = pd.concat([x, y], axis=1).dropna()
        if len(paired) < 2 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
            return np.nan
        return paired.iloc[:, 0].rank().corr(paired.iloc[:, 1].rank())

    records = []
    for stage, cols in PROCESS.items():
        inputs = cols["fdc"] + cols.get("upstream", [])
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
    인과관계 확정이 아니라 후속 검증 후보 순위다.
    """
    numeric = [
        "Cooling_Flow", "Cooling_Water_Temp", "Head_Temp", "Vibration",
        "Coating_Flow", "CLN_Flow", "CLN_Pressure", "CLN_Time",
        "Laser_Power", "Groove_Depth", "Cooling_Thermal_Load",
        "Cleaning_Load_Ratio",
    ]
    rankings = []
    for defect in ["Edge_Burn", "Particle", "Remain_Coat"]:
        for feature in numeric:
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
    """6단계: 설비별 일 단위 추세와 defect/Yield 결과를 연결한다."""
    trend = (
        df.assign(date=df["DateTime"].dt.date)
        .groupby(["Machine_ID", "date"], as_index=False)
        .agg(
            Head_Temp=("Head_Temp", "mean"),
            Coating_Uniformity=("Coating_Uniformity", "mean"),
            Surface_Roughness=("Surface_Roughness", "mean"),
            Yield=("Yield", "mean"),
            Particle_rate=("Particle", "mean"),
            Remain_Coat_rate=("Remain_Coat", "mean"),
            Edge_Burn_rate=("Edge_Burn", "mean"),
            samples=("Yield", "size"),
        )
    )
    for col in ["Head_Temp", "Coating_Uniformity", "Surface_Roughness", "Yield"]:
        trend[f"{col}_7d_ma"] = trend.groupby("Machine_ID")[col].transform(
            lambda x: x.rolling(7, min_periods=3).mean()
        )
    save_table(trend, "05_machine_daily_trend.csv")
    return trend


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
