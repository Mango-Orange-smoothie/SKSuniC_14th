"""가설을 적용하지 않은 전체 상관 분석.

결과:
  01_full_numeric_spearman_matrix.csv  모든 수치 칼럼의 상관행렬
  02_top_numeric_correlation_pairs.csv 절대 상관계수 상위 쌍
  03_categorical_defect_associations.csv 범주형 인자와 결과의 Cramer's V
  04_correlation_scope.csv              포함/제외 칼럼 목록
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
OUT = ROOT / "analysis_outputs" / "full_correlation"
OUT.mkdir(parents=True, exist_ok=True)


def cramers_v(a: pd.Series, b: pd.Series) -> float:
    """두 범주형 변수의 연관성(0=없음, 1=강함)을 계산한다."""
    table = pd.crosstab(a, b)
    observed = table.to_numpy(dtype=float)
    n = observed.sum()
    if n == 0 or min(observed.shape) < 2:
        return np.nan
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / n
    valid = expected > 0
    chi2 = ((observed - expected) ** 2 / np.where(valid, expected, 1)).sum()
    return float(np.sqrt((chi2 / n) / min(observed.shape[0] - 1, observed.shape[1] - 1)))


def main() -> None:
    df = pd.read_excel(ROOT / "DP_HealthIndex_Dataset.xlsx")

    # DateTime/ID는 수치 크기의 차이가 공정 물리량을 뜻하지 않으므로 수치 상관에서는 제외한다.
    excluded = ["DateTime", "Lot_ID", "Strip_ID", "Machine_ID", "Product_ID", "Recipe_ID", "Shift", "Operator_ID", "NG_Code"]
    candidates = [c for c in df.columns if c not in excluded]
    numeric = df[candidates].apply(pd.to_numeric, errors="coerce")
    numeric_cols = numeric.columns[numeric.notna().any()].tolist()
    numeric = numeric[numeric_cols]

    # Spearman = 순위로 변환한 뒤 Pearson 상관. scipy 없이도 계산 가능하다.
    corr = numeric.rank().corr().round(4)
    corr.to_csv(OUT / "01_full_numeric_spearman_matrix.csv", encoding="utf-8-sig")

    pairs = []
    for i, left in enumerate(corr.columns):
        for right in corr.columns[i + 1 :]:
            r = corr.loc[left, right]
            if pd.notna(r):
                pairs.append({"variable_1": left, "variable_2": right, "spearman_r": r, "absolute_r": abs(r)})
    pairs = pd.DataFrame(pairs).sort_values("absolute_r", ascending=False)
    pairs.to_csv(OUT / "02_top_numeric_correlation_pairs.csv", index=False, encoding="utf-8-sig")

    # defect 이진값, die count, Yield/Fail_Die처럼 서로 정의상 연결된 결과변수를 제외한
    # '공정 물리량끼리'의 상관 순위도 별도 제공한다.
    result_columns = [
        "Chipping", "Chipping_Die", "Remain_Coat", "Remain_Coat_Die",
        "Particle", "Particle_Die", "Micro_Crack", "Micro_Crack_Die",
        "Laser_Paim", "Laser_Paim_Die", "Edge_Burn", "Edge_Burn_Die",
        "Fail_Die", "Yield",
    ]
    process_pairs = pairs.loc[
        ~pairs["variable_1"].isin(result_columns) & ~pairs["variable_2"].isin(result_columns)
    ]
    process_pairs.to_csv(OUT / "02b_process_parameter_correlation_pairs.csv", index=False, encoding="utf-8-sig")

    # 범주형 식별 인자는 defect/NG 결과와 Cramer's V로 별도 확인한다.
    categories = ["Machine_ID", "Product_ID", "Recipe_ID", "Shift", "Operator_ID"]
    outcomes = ["NG_Code", "Particle", "Remain_Coat", "Edge_Burn", "Yield"]
    association = [
        {"category": category, "outcome": outcome, "cramers_v": cramers_v(df[category], df[outcome])}
        for category in categories for outcome in outcomes
    ]
    pd.DataFrame(association).sort_values("cramers_v", ascending=False).to_csv(
        OUT / "03_categorical_defect_associations.csv", index=False, encoding="utf-8-sig"
    )

    scope = pd.DataFrame({
        "column": df.columns,
        "analysis_type": ["numeric_spearman" if c in numeric_cols else "categorical_association_or_excluded" for c in df.columns],
    })
    scope.to_csv(OUT / "04_correlation_scope.csv", index=False, encoding="utf-8-sig")

    print(f"수치 칼럼 {len(numeric_cols)}개: 전체 상관행렬과 상관쌍 {len(pairs)}개 저장 완료")
    print(pairs.head(20).to_string(index=False))
    print("\n결과변수 중복을 제외한 공정 물리량 상관 상위 15개")
    print(process_pairs.head(15).to_string(index=False))
    print("\n범주형 인자-결과 연관성 상위 10개")
    print(pd.DataFrame(association).sort_values("cramers_v", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
