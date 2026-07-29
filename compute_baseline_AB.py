"""
compute_baseline_AB.py

목적
----
파라미터 열화 패턴 유형(A/B/C/E) 분류를 반영해, A유형과 B유형 컬럼의 Baseline(Phase 0 사전 보정
기준값)을 Product_ID x Recipe_ID(54개 조합) 단위로 산출한다. Machine_ID는 그룹핑에서 제외한다
(A유형 컬럼은 실측 결과 Recipe에 따른 평균 변동이 그룹 내부 변동의 1~2% 수준에 불과해 Recipe 구분
실익이 적었고, 이번 산출물은 Machine을 아예 배제하고 Product x Recipe로만 보는 버전이다).

A유형 (단조 drift형, 8개)
    시간에 따라 점진적으로 한 방향으로 나빠지는 유형.
    Baseline = 해당 그룹의 OK 데이터를 시간순 정렬한 뒤, 가장 이른 시점 25개의 평균
    (= 그 그룹의 "초기 안정구간" 값. 장비가 아직 열화되지 않았을 시점의 기준값으로 사용)

B유형 (U자형/최적구간형, 8개 = 원 7개 + CLN_Time 재분류)
    너무 높아도 낮아도 불량이며 특정 구간 안에 있어야 정상인 유형.
    Baseline = 해당 그룹 OK 데이터의 중앙값(median)
    * CLN_Time은 원래 C유형(편측임계) 후보였으나, 실제 데이터로 위험 방향을 추정한 결과 54개 그룹
      중 29개는 "낮을수록 위험", 25개는 "높을수록 위험"으로 방향이 일관되지 않아(신호도 약함) B유형
      으로 재분류했다. (근거는 compute_baseline_C.py 실행 결과 참고)

입력: DP_HealthIndex_Dataset.csv
출력: Baseline_AB_ProductRecipe.csv
"""

import pandas as pd

INPUT_CSV = "DP_HealthIndex_Dataset.csv"
OUTPUT_CSV = "Baseline_AB_ProductRecipe.csv"

INIT_WINDOW = 25  # A유형 "초기 안정구간"으로 볼 최초 표본 개수

# A유형: 컬럼명 -> 악화 방향 (True = 값이 올라갈수록 악화, False = 값이 내려갈수록 악화)
A_TYPE_DIRECTION = {
    "Head_Temp": True,
    "Vibration": True,
    "Alignment_Time": True,
    "Process_Time": True,
    "Cooling_Flow": False,
    "Cooling_Water_Temp": True,
    "CLN_Flow": False,
    "Coating_Flow": False,
}

# B유형: CLN_Time은 C -> B 재분류분
B_TYPE_COLUMNS = [
    "Laser_Power", "Power_Efficiency", "Focus", "Beam_Diameter",
    "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "CLN_Time",
]


def compute_type_a(ok_sorted: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (product, recipe), group in ok_sorted.groupby(["Product_ID", "Recipe_ID"]):
        initial_window = group.head(INIT_WINDOW)
        for column, up_is_bad in A_TYPE_DIRECTION.items():
            rows.append({
                "type": "A",
                "column": column,
                "group_key": f"{product}|{recipe}",
                "baseline_method": f"initial_window_mean(n={INIT_WINDOW}, machine pooled)",
                "baseline_value": round(initial_window[column].mean(), 5),
                "bad_direction": "up" if up_is_bad else "down",
            })
    return pd.DataFrame(rows)


def compute_type_b(ok: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (product, recipe), group in ok.groupby(["Product_ID", "Recipe_ID"]):
        for column in B_TYPE_COLUMNS:
            method = "OK_median (재분류: C->B)" if column == "CLN_Time" else "OK_median"
            rows.append({
                "type": "B",
                "column": column,
                "group_key": f"{product}|{recipe}",
                "baseline_method": method,
                "baseline_value": round(group[column].median(), 5),
            })
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv(INPUT_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])

    ok = df[df["NG_Code"] == "OK"]
    ok_sorted = ok.sort_values("DateTime")  # A유형 초기구간 판단을 위해 시간순 정렬 필수

    baseline_a = compute_type_a(ok_sorted)
    baseline_b = compute_type_b(ok)

    result = pd.concat([baseline_a, baseline_b], ignore_index=True)
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"A유형: {len(baseline_a)}행 (54그룹 x 8컬럼)")
    print(f"B유형: {len(baseline_b)}행 (54그룹 x 8컬럼, CLN_Time 포함)")
    print(f"저장 완료: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
