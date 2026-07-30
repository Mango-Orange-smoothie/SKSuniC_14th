"""Goal 2 — NG_Code: BURN 유효인자 발굴.

레이저 다이싱 공정에서 Edge Burn(과열) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney+FDR,
RandomForest permutation importance)을 모두 통과한 것만 "유효인자"로 확정한다.

pipeline/의 공용 전처리 산출물(OPCOND 층화 baseline)과 pipeline/common.py
헬퍼를 그대로 재사용한다 — 층(stratum) 정의를 여기서 새로 만들지 않는다.
원본 데이터/공용 pipeline 파일은 전혀 수정하지 않는다.

실행 (저장소 루트에서):
    python "26.07.30_2001_Goal2_BURN_유효인자_분석/burn_influence_factors.py"

산출물 (이 폴더 안에 저장):
    00_burn_factors_summary.json         실행 메타데이터(표본수/임계값/방법별 합의 요약)
    01_burn_rate_by_stratum.csv          Machine/Product/Recipe/OPCOND별 BURN 발생률 sanity check
    02_univariate_test_results.csv       Mann-Whitney U + BH-FDR + Cliff's delta (라벨별)
    03_tree_importance.csv               RandomForest permutation importance (라벨별)
    04_burn_influence_factors_final.csv  최종 교차검증 유효인자 표 (메인 산출물)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from statsmodels.stats.multitest import multipletests

# 이 스크립트는 pipeline/ 밖(개인 작업 폴더)에 있으므로 저장소 루트를 sys.path에 추가한다.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import (  # noqa: E402
    compute_stratum_baseline_stats,
    load_dataset,
    stratified_split_by_defect,
    zscore_transform,
)

OUT_DIR = Path(__file__).resolve().parent

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES
ENGINEERED_COLS = ["Thermal_Load_Ratio"]  # 신규 피처 - baseline을 직접 계산해야 함
# 팀이 이미 만들어둔 4개 공용 도메인 비율 피처. load_dataset()이 자동으로 붙여주고,
# 00_stratum_baseline_stats_by_opcond.csv에도 이미 baseline이 있어 그대로 재사용한다
# (compute_stratum_baseline_stats 재계산 불필요 — README의 "재구현 금지" 원칙).
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
# 김시우님 00_column_classification.csv의 decision_note가 "Goal2에서 후속 확인 가치 있음"
# 이라고 명시한 컬럼. 원래 undocumented 서브시스템이라 FDC_COLS/RESPONSES에 안 들어가
# 있어서 초판에서 누락됐다가, 전처리 산출물 재확인 과정에서 발견해 추가함. baseline이
# 없어 Thermal_Load_Ratio와 같은 방식으로 직접 계산한다.
NEEDS_CUSTOM_BASELINE = ENGINEERED_COLS + ["Maintenance_Count"]
ALL_FEATURE_COLS = CANDIDATE_COLS + ENGINEERED_COLS + TEAM_DOMAIN_FEATURES + ["Maintenance_Count"]

LABELS = ["is_burn_primary", "is_burn_broad"]

# 통계적으로 유의해도 효과가 미미하면(대표본이라 사소한 차이도 유의해짐) 후보에서 뺀다.
EFFECT_SIZE_MIN = 0.2  # Cliff's delta, small~medium 경계
TREE_TOP_N = 10  # permutation importance 상위 N개만 "트리 기반 지지"로 인정

# 2단계에서 세운 물리 메커니즘 가설 (통계 결과 해석의 기준선).
DOMAIN_HYPOTHESIS = {
    "Laser_Power": ("에너지 투입", "up"),
    "Frequency": ("에너지 투입(펄스 중첩)", "up"),
    "Power_Efficiency": ("에너지 투입", "either"),
    "Feed_Speed": ("체류시간(열 축적)", "down"),
    "Process_Time": ("체류시간(열 축적)", "up"),
    "Alignment_Time": ("체류시간(열 축적)", "up"),
    "Cooling_Flow": ("방열 능력", "down"),
    "Cooling_Water_Temp": ("방열 능력", "up"),
    "Head_Temp": ("방열 능력", "up"),
    "Focus": ("빔 품질/집속", "either"),
    "Beam_Diameter": ("빔 품질/집속", "either"),
    "Laser_Centering_Position": ("빔 품질/집속", "either"),
    "Vibration": ("기계적 불안정(국소 hot spot)", "up"),
    "CLN_Flow": ("이물/잔사(레이저 흡수)", "down"),
    "CLN_Pressure": ("이물/잔사(레이저 흡수)", "down"),
    "CLN_Time": ("이물/잔사(레이저 흡수) — CLN_Flow/Pressure와 동일 계열", "down"),
    "Coating_Flow": ("이물/잔사(레이저 흡수) — 코팅 불균일 시 국소 흡수 편차 가능성", "down"),
    "Laser_Head_Remain_Time": ("헤드 노후", "down"),
    "Kerf_Width_Profile": ("결과 공변(동반증상 후보, 원인 아닐 수 있음)", "either"),
    "Top_Kerf": ("결과 공변, Kerf_Width_Profile과 동일 메커니즘 상속(HealthIndex 설계서 근거)", "either"),
    "Bottom_Kerf": ("결과 공변, Kerf_Width_Profile과 동일 메커니즘 상속(HealthIndex 설계서 근거)", "either"),
    "Kerf_Angle": ("결과 공변(동반증상 후보, 원인 아닐 수 있음)", "either"),
    "Groove_Depth": ("결과 공변(동반증상 후보, 원인 아닐 수 있음)", "either"),
    "Surface_Roughness": ("결과 공변(동반증상 후보, 원인 아닐 수 있음)", "up"),
    "Thermal_Load_Ratio": ("에너지투입/방열 비율(신규 공학 피처)", "up"),
    "Cooling_Thermal_Load": ("방열 능력(팀 공용 피처 = Cooling_Water_Temp/Cooling_Flow)", "up"),
    "Maintenance_Count": (
        "정비 이력 프록시(00_column_classification.csv decision_note가 Goal2 확인 가치 있다고 명시) "
        "— 정비 직후 재교정 불안정 또는 정비 주기가 긴 설비의 누적 열화, 두 상충 가능성이 있어 "
        "방향을 특정하지 않음",
        "either",
    ),
}

# Burn과는 무관하다고 판단한 컬럼 — "안 찾아본 것"이 아니라 "찾아봤는데 알려진 실패모드가
# 열 축적(Burn)이 아니라 정렬/센터링(Chipping 계열)이라 관련 없다고 판단한 것"이다.
# 근거: HealthIndex 설계서(v2) E유형(대칭성/정렬형) 분류.
NOT_RELATED_TO_BURN = {
    "Cutting_X_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 알려진 실패모드는 Chipping이며 열 축적(Burn)과 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 알려진 실패모드는 Chipping이며 열 축적(Burn)과 무관",
    "Cutting_Offset": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 목표 절단선 대비 편차, 열 축적(Burn)과 무관",
    "Package_Size_1": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 패키지 크기 불균형은 센터링 불량 지표, 열 축적과 무관",
    "Package_Size_2": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 패키지 크기 불균형은 센터링 불량 지표, 열 축적과 무관",
    "Package_Size_3": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 패키지 크기 불균형은 센터링 불량 지표, 열 축적과 무관",
    "Package_Size_4": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 패키지 크기 불균형은 센터링 불량 지표, 열 축적과 무관",
    "Laser_Cleaning_Demand": "팀 공용 피처(Laser_Power×Groove_Depth) — 세정 수요(디브리 발생량) 지표라 이물/세정 계열 불량(Particle/Remain_Coat)과 관련, 열 축적(Burn)과는 무관",
    "Cleaning_Capacity": "팀 공용 피처(CLN_Flow×CLN_Pressure×CLN_Time) — 세정 능력 지표, 열 축적(Burn)과 무관",
    "Cleaning_Load_Ratio": "팀 공용 피처(세정수요/세정능력) — 이물/세정 계열 불량과 관련, 열 축적(Burn)과 무관",
}

# 팀 HealthIndex 설계서(v2)에서도 아직 결론을 못 낸 컬럼 — 내(작성자)가 몰라서가 아니라
# 팀 전체가 멘토링 자료로도 실패모드를 확정 못 한 F/G유형이라 억지로 가설을 넣지 않는다.
TEAM_UNDETERMINED = {
    "Laser_Current": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Laser_Voltage": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Coating_Thickness": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후)이 불확실, 팀 미확정",
    "Coating_Uniformity": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후)이 불확실, 팀 미확정",
}


def domain_info(column: str) -> tuple[str, str, bool, str]:
    """(설명 텍스트, 방향 가설, 유효인자 후보로 인정할지 여부, 상태분류) 반환."""
    if column in DOMAIN_HYPOTHESIS:
        mechanism, direction = DOMAIN_HYPOTHESIS[column]
        return mechanism, direction, True, "burn_related"
    if column in NOT_RELATED_TO_BURN:
        return NOT_RELATED_TO_BURN[column], "not_applicable", False, "not_related_to_burn"
    if column in TEAM_UNDETERMINED:
        return TEAM_UNDETERMINED[column], "unknown", False, "team_undetermined"
    return "미분류 — 검토 필요", "unknown", False, "unclassified"


# ---------------------------------------------------------------------------
# 0단계: 데이터 로드, 라벨/공학피처 부착, OPCOND 층화 z-score
# ---------------------------------------------------------------------------

def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    cooling = result["Cooling_Flow"].where(result["Cooling_Flow"].abs() > 1e-9)
    result["Thermal_Load_Ratio"] = (result["Laser_Power"] * result["Frequency"]) / cooling
    return result


def add_burn_labels(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["is_burn_primary"] = result["NG_Code"] == "BURN"
    result["is_burn_broad"] = result["Edge_Burn"] == 1
    return result


def build_dataset() -> pd.DataFrame:
    df = load_dataset()
    df = add_engineered_features(df)
    df = add_burn_labels(df)

    baseline_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
    baseline_stats = pd.read_csv(baseline_path)

    # 신규 공학 피처(Thermal_Load_Ratio)와 Maintenance_Count는 사전 baseline이 없으므로
    # OK행 기준으로 직접 산출.
    engineered_baseline = compute_stratum_baseline_stats(
        df[df["is_normal"]], config.OPCOND, NEEDS_CUSTOM_BASELINE
    )
    baseline_stats_ext = pd.concat([baseline_stats, engineered_baseline], ignore_index=True)

    df = zscore_transform(df, baseline_stats_ext, config.OPCOND, ALL_FEATURE_COLS)
    return df


# ---------------------------------------------------------------------------
# 1단계: BURN 발생률 sanity check (특정 장비/제품/레시피 쏠림 여부)
# ---------------------------------------------------------------------------

def compute_rate_by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    strata = [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], config.OPCOND]
    frames = []
    for keys in strata:
        g = df.groupby(keys)["is_burn_primary"].agg(n="count", n_burn="sum", rate="mean")
        g = g.reset_index()
        g["stratum_type"] = "+".join(keys)
        g = g.rename(columns={k: "stratum_value" for k in keys} if len(keys) == 1 else {})
        if len(keys) == 1:
            g = g.rename(columns={keys[0]: "stratum_value"})
        else:
            g["stratum_value"] = g[keys].astype(str).agg("|".join, axis=1)
            g = g.drop(columns=keys)
        frames.append(g[["stratum_type", "stratum_value", "n", "n_burn", "rate"]])
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 2단계: Mann-Whitney U + BH-FDR + Cliff's delta (라벨별 x 후보컬럼별)
# ---------------------------------------------------------------------------

def _mannwhitney_with_effect(group_vals: pd.Series, rest_vals: pd.Series) -> tuple[float, float, float]:
    group_vals = pd.Series(group_vals).dropna()
    rest_vals = pd.Series(rest_vals).dropna()
    if len(group_vals) < 3 or len(rest_vals) < 3:
        return np.nan, np.nan, np.nan
    u_stat, p_value = scipy_stats.mannwhitneyu(group_vals, rest_vals, alternative="two-sided")
    n1, n2 = len(group_vals), len(rest_vals)
    cliffs_delta = (2 * u_stat) / (n1 * n2) - 1  # group 기준 방향
    return float(u_stat), float(p_value), float(cliffs_delta)


def run_univariate_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in LABELS:
        for col in ALL_FEATURE_COLS:
            z_col = f"{col}_z"
            burn_vals = df.loc[df[label], z_col]
            other_vals = df.loc[~df[label], z_col]
            u_stat, p_value, cliffs_delta = _mannwhitney_with_effect(burn_vals, other_vals)
            rows.append({
                "label": label,
                "column": col,
                "n_group": int(df[label].sum()),
                "n_rest": int((~df[label]).sum()),
                "median_z_group": burn_vals.median(),
                "median_z_rest": other_vals.median(),
                "u_stat": u_stat,
                "p_value": p_value,
                "cliffs_delta": cliffs_delta,
            })
    result = pd.DataFrame(rows)

    result["p_fdr"] = np.nan
    result["fdr_significant"] = False
    for label, idx in result.groupby("label").groups.items():
        pvals = result.loc[idx, "p_value"].fillna(1.0)
        rejected, p_adj, _, _ = multipletests(pvals, alpha=config.TREND_ALPHA, method="fdr_bh")
        result.loc[idx, "p_fdr"] = p_adj
        result.loc[idx, "fdr_significant"] = rejected

    result["effect_size_pass"] = result["cliffs_delta"].abs() >= EFFECT_SIZE_MIN
    result["univariate_flag"] = result["fdr_significant"] & result["effect_size_pass"]
    return result


# ---------------------------------------------------------------------------
# 3단계: RandomForest(class_weight=balanced) permutation importance
# ---------------------------------------------------------------------------

def run_tree_importance(df: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [f"{c}_z" for c in ALL_FEATURE_COLS]
    rows = []
    for label in LABELS:
        train_df, test_df = stratified_split_by_defect(df, label, test_size=0.2, random_state=42)
        x_train = train_df[feature_cols]
        y_train = train_df[label].astype(int)
        x_test = test_df[feature_cols]
        y_test = test_df[label].astype(int)

        model = RandomForestClassifier(
            n_estimators=200, max_depth=8, class_weight="balanced",
            random_state=42, n_jobs=-1,
        )
        model.fit(x_train, y_train)

        perm = permutation_importance(
            model, x_test, y_test, scoring="average_precision",
            n_repeats=15, random_state=42, n_jobs=-1,
        )
        label_rows = pd.DataFrame({
            "label": label,
            "column": ALL_FEATURE_COLS,
            "importance_mean": perm.importances_mean,
            "importance_std": perm.importances_std,
        })
        label_rows["rank"] = label_rows["importance_mean"].rank(ascending=False, method="min").astype(int)
        label_rows["tree_flag"] = (label_rows["rank"] <= TREE_TOP_N) & (label_rows["importance_mean"] > 0)
        rows.append(label_rows)
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# 4단계: 도메인 가설 + 통계 교차검증 병합 -> 최종 유효인자 표
# ---------------------------------------------------------------------------

def build_final_table(univariate: pd.DataFrame, tree_importance: pd.DataFrame) -> pd.DataFrame:
    uni_wide = univariate.pivot(index="column", columns="label",
                                 values=["p_fdr", "cliffs_delta", "univariate_flag"])
    uni_wide.columns = [f"{metric}_{label}" for metric, label in uni_wide.columns]
    uni_wide = uni_wide.reset_index()

    tree_wide = tree_importance.pivot(index="column", columns="label",
                                       values=["importance_mean", "rank", "tree_flag"])
    tree_wide.columns = [f"{metric}_{label}" for metric, label in tree_wide.columns]
    tree_wide = tree_wide.reset_index()

    merged = uni_wide.merge(tree_wide, on="column", how="outer")

    uni_flag_cols = [f"univariate_flag_{label}" for label in LABELS]
    tree_flag_cols = [f"tree_flag_{label}" for label in LABELS]
    for c in uni_flag_cols + tree_flag_cols:
        merged[c] = merged[c].infer_objects(copy=False).fillna(False).astype(bool)

    # "몇 개 방법에서 합의했는가"는 서로 다른 방법론(단변량검정 vs 트리기반 다변량중요도) 기준으로
    # 센다. 같은 방법이 Primary/Broad 두 라벨 모두에서 뜨는 것은 "라벨 일관성"이라는 별개의
    # 보강 증거이지, 독립적인 두 번째 방법이 아니므로 n_methods_agree에 이중으로 잡지 않는다.
    merged["univariate_any_label"] = merged[uni_flag_cols].any(axis=1)
    merged["tree_any_label"] = merged[tree_flag_cols].any(axis=1)
    merged["n_methods_agree"] = merged["univariate_any_label"].astype(int) + merged["tree_any_label"].astype(int)
    merged["n_labels_univariate_flag"] = merged[uni_flag_cols].sum(axis=1).astype(int)
    merged["n_labels_tree_flag"] = merged[tree_flag_cols].sum(axis=1).astype(int)

    domain_lookup = merged["column"].map(domain_info)
    merged["domain_mechanism"] = domain_lookup.map(lambda t: t[0])
    merged["domain_direction_hypothesis"] = domain_lookup.map(lambda t: t[1])
    merged["has_domain_support"] = domain_lookup.map(lambda t: t[2])
    merged["domain_status"] = domain_lookup.map(lambda t: t[3])
    merged["subsystem"] = merged["column"].map(
        lambda c: next((sub for sub, cols in config.SUBSYSTEMS.items() if c in cols), "engineered")
    )

    def verdict(row):
        if row["n_methods_agree"] >= 2 and row["has_domain_support"]:
            return "confirmed"
        if row["n_methods_agree"] >= 2 and not row["has_domain_support"]:
            return "candidate_needs_domain_review"
        if row["n_methods_agree"] == 1 and row["has_domain_support"]:
            return "candidate_weak_signal"
        return "insufficient_evidence"

    merged["verdict"] = merged.apply(verdict, axis=1)

    ordered_cols = [
        "column", "subsystem", "domain_status", "domain_mechanism", "domain_direction_hypothesis",
        "p_fdr_is_burn_primary", "cliffs_delta_is_burn_primary",
        "p_fdr_is_burn_broad", "cliffs_delta_is_burn_broad",
        "importance_mean_is_burn_primary", "rank_is_burn_primary",
        "importance_mean_is_burn_broad", "rank_is_burn_broad",
        "n_methods_agree", "n_labels_univariate_flag", "n_labels_tree_flag", "verdict",
    ]
    merged = merged[ordered_cols].sort_values(
        ["n_methods_agree", "cliffs_delta_is_burn_primary"],
        ascending=[False, False], key=lambda s: s.abs() if s.name == "cliffs_delta_is_burn_primary" else s,
    )
    return merged.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main() -> None:
    df = build_dataset()

    rate_table = compute_rate_by_stratum(df)
    rate_table.to_csv(OUT_DIR / "01_burn_rate_by_stratum.csv", encoding="utf-8-sig", index=False)

    univariate = run_univariate_tests(df)
    univariate.to_csv(OUT_DIR / "02_univariate_test_results.csv", encoding="utf-8-sig", index=False)

    tree_importance = run_tree_importance(df)
    tree_importance.to_csv(OUT_DIR / "03_tree_importance.csv", encoding="utf-8-sig", index=False)

    final_table = build_final_table(univariate, tree_importance)
    final_table.to_csv(OUT_DIR / "04_burn_influence_factors_final.csv", encoding="utf-8-sig", index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows_total": int(len(df)),
        "n_burn_primary": int(df["is_burn_primary"].sum()),
        "n_burn_broad": int(df["is_burn_broad"].sum()),
        "candidate_columns": ALL_FEATURE_COLS,
        "effect_size_min_cliffs_delta": EFFECT_SIZE_MIN,
        "fdr_alpha": config.TREND_ALPHA,
        "tree_top_n": TREE_TOP_N,
        "verdict_counts": final_table["verdict"].value_counts().to_dict(),
        "confirmed_factors": final_table.loc[final_table["verdict"] == "confirmed", "column"].tolist(),
    }
    with open(OUT_DIR / "00_burn_factors_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
