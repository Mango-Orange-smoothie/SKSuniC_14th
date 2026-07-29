"""
compute_baseline_E.py

목적
----
E유형(대칭성/정렬형) 9개 컬럼의 Baseline을 산출한다. E유형은 A/B/C유형과 달리 데이터 분포에서
기준값을 추정하지 않고, 공정의 물리적 의미상 "완벽하게 맞았을 때"의 이론적 상수값을 baseline으로
고정한다. 따라서 Product/Recipe/Machine 그룹핑이 필요 없다(공정 조건과 무관하게 항상 동일한
이상값을 가져야 하는 컬럼들이기 때문).

정렬/대칭 편차형 (5개) — 목표 대비 편차이므로 이상값 = 0
    Laser_Centering_Position : 중심 대비 편차 (Centering 오차)
    Cutting_X_Index          : Cutting Offset (X축)
    Cutting_Y_Index          : Cutting Offset (Y축)
    Cutting_Offset           : 목표 line 대비 오차
    Kerf_Angle               : 절단면 기울기. 완전 수직이 이상값이므로 90도

치수형 (4개) — Package_Size_1~4, 목표 치수 = 5
    (Product_ID/Recipe_ID와 무관하게 공정 설계상 목표 치수를 5로 봄)

참고용 검증(reference_OK_mean/std)
    이론 상수를 그대로 baseline으로 채택하되, 실제 OK 데이터의 평균/표준편차를 함께 계산해
    이론값과 실측값이 크게 어긋나지 않는지 확인할 수 있도록 참고 컬럼으로 남긴다.
    (baseline_value 자체를 바꾸는 데는 사용하지 않음 — 이론상수 고정 방식이 최종 결정.)

입력: DP_HealthIndex_Dataset.csv
출력: Baseline_E_이론상수.csv
"""

import pandas as pd

INPUT_CSV = "DP_HealthIndex_Dataset.csv"
OUTPUT_CSV = "Baseline_E_이론상수.csv"

E_THEORETICAL_CONSTANTS = {
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


def main():
    df = pd.read_csv(INPUT_CSV)
    ok = df[df["NG_Code"] == "OK"]

    rows = []
    for column, constant in E_THEORETICAL_CONSTANTS.items():
        rows.append({
            "type": "E",
            "column": column,
            "baseline_method": "theoretical_constant",
            "baseline_value": constant,
            "reference_OK_mean": round(ok[column].mean(), 5),
            "reference_OK_std": round(ok[column].std(), 5),
        })

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"E유형: {len(result)}행 (그룹핑 없음, 이론상수 고정)")
    print(result.to_string(index=False))
    print(f"저장 완료: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
