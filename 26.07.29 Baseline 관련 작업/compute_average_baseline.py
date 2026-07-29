"""
compute_average_baseline.py

목적
----
Product_ID x Recipe_ID(54개 조합) 별로, FDC/Response 35개 컬럼의 단순 평균(OK 데이터 기준)을
구한다. Machine_ID는 무시하고, A/B/C/E 유형 구분 없이 전 컬럼에 동일한 방식(단순 평균)을 적용한
"확인용/베이스라인 비교용" 산출물이다. 실제 설계(유형별 차등 계산)에는 사용하지 않는다.

입력: DP_HealthIndex_Dataset.csv (100,000행 x 68열)
출력: Average_Baseline.csv (54행 x 37열: Product_ID, Recipe_ID, 35개 컬럼 평균, n_OK_samples)
"""

import pandas as pd

INPUT_CSV = "DP_HealthIndex_Dataset.csv"
OUTPUT_CSV = "Average_Baseline.csv"

# FDC(22) + Response(13) = 35개 컬럼. 기본정보/Defect라벨/노이즈후보 컬럼은 제외한다.
FDC_RESPONSE_COLUMNS = [
    # FDC
    "Laser_Power", "Power_Efficiency", "Laser_Centering_Position", "Frequency", "Feed_Speed",
    "Focus", "Head_Temp", "Vibration", "Laser_Current", "Laser_Voltage", "Beam_Diameter",
    "Alignment_Time", "Process_Time", "Cutting_X_Index", "Cutting_Y_Index",
    "Cooling_Flow", "Cooling_Water_Temp", "CLN_Flow", "CLN_Pressure", "Coating_Flow",
    "CLN_Time", "Laser_Head_Remain_Time",
    # Response
    "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle", "Groove_Depth",
    "Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4",
    "Coating_Thickness", "Coating_Uniformity", "Cutting_Offset", "Surface_Roughness",
]


def main():
    df = pd.read_csv(INPUT_CSV)

    # NG_Code == 'OK'인 행만 사용한다.
    # (Binary Defect 플래그 6개가 전부 0인 행과 정확히 일치함을 확인했음 — 별도 필터 불필요)
    ok = df[df["NG_Code"] == "OK"]

    grouped_mean = ok.groupby(["Product_ID", "Recipe_ID"])[FDC_RESPONSE_COLUMNS].mean().reset_index()
    sample_count = ok.groupby(["Product_ID", "Recipe_ID"]).size().reset_index(name="n_OK_samples")

    result = grouped_mean.merge(sample_count, on=["Product_ID", "Recipe_ID"])
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"그룹 수: {len(result)} (기대값: 6 Product x 9 Recipe = 54)")
    print(f"저장 완료: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
