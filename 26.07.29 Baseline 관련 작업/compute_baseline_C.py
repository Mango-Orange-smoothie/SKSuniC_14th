"""
compute_baseline_C.py

목적
----
C유형(편측임계형) 컬럼의 Baseline은 A/B유형과 달리 "정상값"이 아니라 "위험선(위험 경계값)"이다.
OK 데이터만으로는 위험선을 추정할 수 없으므로(정상 범위 내부의 분포만 보고서는 어디부터 위험한지
알 수 없음), 실제 불량(NG) 라벨과 함께 결정트리 스텀프(depth=1)를 이용해 Product_ID x Recipe_ID
그룹별로 위험 경계값을 추정한다.

대상 (컬럼 -> 매칭 Defect)
    CLN_Pressure       -> Remain_Coat   (세정 압력이 낮으면 코팅 잔류물이 남는 결함과 연결)
    Surface_Roughness  -> Particle      (표면 거칠기가 높으면 파티클 결함과 연결)

    * 원래 후보였던 CLN_Time과 Groove_Depth는 이 산출물에서 제외한다.
      - CLN_Time: 방향성이 불일치(그룹별 위험 방향이 뒤섞임)해 B유형(중앙값 기준)으로 재분류.
      - Groove_Depth: 매칭 Defect(Chipping)의 실제 발생 건수가 전체 데이터에서 4건뿐이라
        결정트리로 유의미한 경계값을 학습할 표본이 부족함. (별도로 Baseline_GrooveDepth_잠정치.csv에서
        OK 데이터 기반 잠정 경계값만 계산)

방법
----
그룹(Product_ID x Recipe_ID)마다:
    1. 해당 그룹의 컬럼 값(X)과 매칭 Defect 플래그(y, 0/1)를 추출
    2. NG 표본이 min_samples_leaf(=10) 미만이면 학습 데이터가 부족해 skip
    3. DecisionTreeClassifier(max_depth=1, min_samples_leaf=10)로 단일 분기점 학습
    4. 학습된 분기점(threshold)을 기준으로 좌/우 NG 발생률을 계산해 위험 방향(risky_direction) 결정
       - threshold 미만 구간 NG율이 더 높으면 "low_is_risky"
       - threshold 이상 구간 NG율이 더 높으면 "high_is_risky"

입력: DP_HealthIndex_Dataset.csv
출력: Baseline_C_위험선_ProductRecipe.csv
"""

import pandas as pd
from sklearn.tree import DecisionTreeClassifier

INPUT_CSV = "DP_HealthIndex_Dataset.csv"
OUTPUT_CSV = "Baseline_C_위험선_ProductRecipe.csv"

MIN_SAMPLES_LEAF = 10

# C유형 컬럼 -> 매칭 Defect 플래그 컬럼
C_TYPE_DEFECT_MAP = {
    "CLN_Pressure": "Remain_Coat",
    "Surface_Roughness": "Particle",
}


def find_breakpoint(values: pd.Series, defect_flags: pd.Series):
    """단일 컬럼 x 단일 Defect 플래그에 대해 결정트리 스텀프로 위험 경계값을 추정한다."""
    n_ng = int(defect_flags.sum())
    if n_ng < MIN_SAMPLES_LEAF:
        return None  # NG 표본 부족 -> 추정 불가

    X = values.to_numpy().reshape(-1, 1)
    y = defect_flags.to_numpy()

    tree = DecisionTreeClassifier(max_depth=1, min_samples_leaf=MIN_SAMPLES_LEAF, random_state=0)
    tree.fit(X, y)

    if tree.tree_.feature[0] == -2:
        return None  # 분기 자체가 생성되지 않음 (분리 불가능)

    threshold = tree.tree_.threshold[0]

    below = defect_flags[values < threshold]
    above = defect_flags[values >= threshold]
    if len(below) == 0 or len(above) == 0:
        return None

    ng_rate_below = below.mean()
    ng_rate_above = above.mean()
    risky_direction = "low_is_risky" if ng_rate_below > ng_rate_above else "high_is_risky"

    return {
        "threshold": round(float(threshold), 5),
        "n_NG": n_ng,
        "NG_rate_below": round(float(ng_rate_below), 5),
        "NG_rate_above": round(float(ng_rate_above), 5),
        "risky_direction": risky_direction,
    }


def main():
    df = pd.read_csv(INPUT_CSV)

    rows = []
    for (product, recipe), group in df.groupby(["Product_ID", "Recipe_ID"]):
        for column, defect_col in C_TYPE_DEFECT_MAP.items():
            result = find_breakpoint(group[column], group[defect_col])
            if result is None:
                continue
            rows.append({
                "column": column,
                "matched_defect": defect_col,
                "group_key": f"{product}|{recipe}",
                **result,
            })

    result_df = pd.DataFrame(rows)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"총 {len(result_df)}행 (기대값: 54그룹 x 2컬럼 = 108, NG 부족 그룹은 제외될 수 있음)")
    for column in C_TYPE_DEFECT_MAP:
        n = len(result_df[result_df["column"] == column])
        print(f"  {column}: {n}개 그룹")
    print(f"저장 완료: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
