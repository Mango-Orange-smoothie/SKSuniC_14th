"""Goal 2 — NG_Code: PARTICLE 유효인자 발굴.

레이저 다이싱 공정에서 Particle(이물/파티클) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney+FDR,
RandomForest permutation importance)을 모두 통과한 것만 "유효인자"로 확정한다.

BURN 분석(`26.07.30_2001_Goal2_BURN_유효인자_분석/`)과 동일한 방법론·코드 구조를 쓰되,
Particle의 물리 메커니즘(디브리 발생/세정 밸런스)에 맞춰 도메인 가설을 처음부터 다시
세웠다 — Burn의 가설표를 그대로 복사하지 않았다.

pipeline/의 공용 전처리 산출물(OPCOND 층화 baseline)과 pipeline/common.py
헬퍼를 그대로 재사용한다. 원본 데이터/공용 pipeline 파일은 전혀 수정하지 않는다.

실행 (저장소 루트에서):
    python "26.07.30_2055_Goal2_PARTICLE_유효인자_분석/particle_influence_factors.py"

산출물 (이 폴더 안에 저장):
    00_particle_factors_summary.json         실행 메타데이터
    01_particle_rate_by_stratum.csv          Machine/Product/Recipe/OPCOND별 발생률 sanity check
    02_univariate_test_results.csv           Mann-Whitney U + BH-FDR + Cliff's delta (라벨별)
    03_tree_importance.csv                   RandomForest permutation importance (라벨별)
    04_particle_influence_factors_final.csv  최종 교차검증 유효인자 표 (메인 산출물)
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import (  # noqa: E402
    load_dataset,
    stratified_split_by_defect,
    zscore_transform,
)

OUT_DIR = Path(__file__).resolve().parent
DEFECT_NAME = "PARTICLE"
NG_CODE_VALUE = "PARTICLE"
BINARY_COL = "Particle"

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES
# Particle 전용 신규 공학피처는 만들지 않았다 — 핵심 가설("디브리 발생 수요 vs 세정 능력")을
# 팀 공용 피처 Cleaning_Load_Ratio가 이미 정확히 수식화하고 있어 중복 재구현하지 않는다.
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
ALL_FEATURE_COLS = CANDIDATE_COLS + TEAM_DOMAIN_FEATURES

LABELS = ["is_particle_primary", "is_particle_broad"]

EFFECT_SIZE_MIN = 0.2
TREE_TOP_N = 10

# Particle 물리 메커니즘: 레이저 어블레이션으로 제거된 재질이 디브리(particle)가 되고,
# 세정 공정이 이를 제대로 제거하지 못하면 particle 불량으로 남는다.
# "디브리 발생량 vs 세정 능력"의 밸런스 문제라는 게 핵심 가설 — Burn의 "에너지투입 vs 방열"과
# 구조적으로 동형이지만 물리적 실체는 다르다(열이 아니라 물질).
DOMAIN_HYPOTHESIS = {
    "Laser_Power": ("에너지 투입 — 어블레이션(재질 제거)량 증가로 디브리 발생 소스", "up"),
    "Power_Efficiency": ("에너지 변환 효율 이상 — 비정상 어블레이션 가능성", "either"),
    "Focus": ("빔 품질/집속 — 초점 이탈 시 비정상 어블레이션(스패터) 증가 가능성", "either"),
    "Beam_Diameter": ("빔 품질/집속 — 빔 이상 시 비정상 어블레이션(스패터) 증가 가능성", "either"),
    "CLN_Flow": ("세정 능력 — 유량 부족 시 디브리 잔류", "down"),
    "CLN_Pressure": ("세정 능력 — 압력 부족 시 디브리 잔류", "down"),
    "CLN_Time": ("세정 능력 — 시간 부족 시 디브리 잔류", "down"),
    "Coating_Flow": ("코팅 불균일 — 코팅 박리가 particle 소스가 될 가능성", "down"),
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하 시 스패터 증가 가능성", "down"),
    "Vibration": ("기계적 진동 — 디브리 비산/재부착", "up"),
    "Groove_Depth": ("가공 제거량 — 깊을수록 디브리 발생량 증가", "up"),
    "Kerf_Width_Profile": ("가공 제거량 — 넓을수록 디브리 발생량 증가", "up"),
    "Top_Kerf": ("가공 제거량, Kerf_Width_Profile과 동일 메커니즘 상속", "up"),
    "Bottom_Kerf": ("가공 제거량, Kerf_Width_Profile과 동일 메커니즘 상속", "up"),
    "Surface_Roughness": ("결과 공변(동반증상 후보) — particle이 표면에 남아 거칠기 증가 가능성, 원인 아닐 수 있음", "up"),
    "Laser_Cleaning_Demand": ("팀 공용 피처(Laser_Power×Groove_Depth) — 디브리 발생 수요 지표", "up"),
    "Cleaning_Capacity": ("팀 공용 피처(CLN_Flow×Pressure×Time) — 세정 능력 종합지표", "down"),
    "Cleaning_Load_Ratio": ("팀 공용 피처(수요/능력) — 핵심 밸런스 가설을 직접 수식화", "up"),
}

# 정렬/센터링 계열(HealthIndex 설계서 E유형)과 방열 계열(Burn 전용 메커니즘)은
# 디브리 발생·세정과 물리적 연결고리가 없다고 판단했다.
NOT_RELATED_TO_DEFECT = {
    "Laser_Centering_Position": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 디브리 발생과 무관",
    "Cutting_X_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 디브리 발생과 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 디브리 발생과 무관",
    "Cutting_Offset": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 디브리 발생과 무관",
    "Kerf_Angle": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 절단면 수직도, 디브리 발생과 무관",
    "Package_Size_1": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 디브리와 무관",
    "Package_Size_2": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 디브리와 무관",
    "Package_Size_3": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 디브리와 무관",
    "Package_Size_4": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 디브리와 무관",
    "Head_Temp": "방열 계열 — Burn 전용 메커니즘(열 축적), 디브리 발생과 직접 연결고리 없음",
    "Cooling_Flow": "방열 계열 — Burn 전용 메커니즘(열 축적), 디브리 발생과 직접 연결고리 없음",
    "Cooling_Water_Temp": "방열 계열 — Burn 전용 메커니즘(열 축적), 디브리 발생과 직접 연결고리 없음",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — Burn 전용 메커니즘, 디브리 발생과 무관",
    "Frequency": "체류시간/열축적 계열 — Burn 전용 메커니즘(펄스 중첩→열), 디브리 발생과 직접 연결고리 약함",
    "Alignment_Time": "체류시간/열축적 계열 — Burn 전용 메커니즘, 디브리 발생과 직접 연결고리 약함",
    "Process_Time": "체류시간/열축적 계열 — Burn 전용 메커니즘, 디브리 발생과 직접 연결고리 약함",
    "Feed_Speed": "체류시간 계열로 확립된 것은 Burn 메커니즘(열축적) — 디브리 발생량과의 관계는 방향을 특정할 근거가 약해 무관으로 분류",
}

# 팀 HealthIndex 설계서에서도 F/G유형(불확실/미해결)으로 남겨둔 컬럼 — 정의 자체가
# 데이터 속성 문제(측정 시점 불확실 등)라 어떤 defect를 보든 동일하게 유지한다.
TEAM_UNDETERMINED = {
    "Laser_Current": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Laser_Voltage": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Coating_Thickness": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후)이 불확실, 팀 미확정",
    "Coating_Uniformity": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후)이 불확실, 팀 미확정",
}


def domain_info(column: str) -> tuple[str, str, bool, str]:
    if column in DOMAIN_HYPOTHESIS:
        mechanism, direction = DOMAIN_HYPOTHESIS[column]
        return mechanism, direction, True, "defect_related"
    if column in NOT_RELATED_TO_DEFECT:
        return NOT_RELATED_TO_DEFECT[column], "not_applicable", False, "not_related_to_defect"
    if column in TEAM_UNDETERMINED:
        return TEAM_UNDETERMINED[column], "unknown", False, "team_undetermined"
    return "미분류 — 검토 필요", "unknown", False, "unclassified"


# ---------------------------------------------------------------------------
# 0단계: 데이터 로드, 라벨 부착, OPCOND 층화 z-score
# ---------------------------------------------------------------------------

def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["is_particle_primary"] = result["NG_Code"] == NG_CODE_VALUE
    result["is_particle_broad"] = result[BINARY_COL] == 1
    return result


def build_dataset() -> pd.DataFrame:
    df = load_dataset()
    df = add_labels(df)

    baseline_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
    baseline_stats = pd.read_csv(baseline_path)  # 팀 공용 피처 4개 baseline도 이미 포함되어 있음

    df = zscore_transform(df, baseline_stats, config.OPCOND, ALL_FEATURE_COLS)
    return df


# ---------------------------------------------------------------------------
# 1단계: PARTICLE 발생률 sanity check
# ---------------------------------------------------------------------------

def compute_rate_by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    strata = [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], config.OPCOND]
    frames = []
    for keys in strata:
        g = df.groupby(keys)["is_particle_primary"].agg(n="count", n_defect="sum", rate="mean")
        g = g.reset_index()
        g["stratum_type"] = "+".join(keys)
        if len(keys) == 1:
            g = g.rename(columns={keys[0]: "stratum_value"})
        else:
            g["stratum_value"] = g[keys].astype(str).agg("|".join, axis=1)
            g = g.drop(columns=keys)
        frames.append(g[["stratum_type", "stratum_value", "n", "n_defect", "rate"]])
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 2단계: Mann-Whitney U + BH-FDR + Cliff's delta
# ---------------------------------------------------------------------------

def _mannwhitney_with_effect(group_vals: pd.Series, rest_vals: pd.Series) -> tuple[float, float, float]:
    group_vals = pd.Series(group_vals).dropna()
    rest_vals = pd.Series(rest_vals).dropna()
    if len(group_vals) < 3 or len(rest_vals) < 3:
        return np.nan, np.nan, np.nan
    u_stat, p_value = scipy_stats.mannwhitneyu(group_vals, rest_vals, alternative="two-sided")
    n1, n2 = len(group_vals), len(rest_vals)
    cliffs_delta = (2 * u_stat) / (n1 * n2) - 1
    return float(u_stat), float(p_value), float(cliffs_delta)


def run_univariate_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in LABELS:
        for col in ALL_FEATURE_COLS:
            z_col = f"{col}_z"
            group_vals = df.loc[df[label], z_col]
            rest_vals = df.loc[~df[label], z_col]
            u_stat, p_value, cliffs_delta = _mannwhitney_with_effect(group_vals, rest_vals)
            rows.append({
                "label": label,
                "column": col,
                "n_group": int(df[label].sum()),
                "n_rest": int((~df[label]).sum()),
                "median_z_group": group_vals.median(),
                "median_z_rest": rest_vals.median(),
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
# 3단계: RandomForest permutation importance
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
        f"p_fdr_{LABELS[0]}", f"cliffs_delta_{LABELS[0]}",
        f"p_fdr_{LABELS[1]}", f"cliffs_delta_{LABELS[1]}",
        f"importance_mean_{LABELS[0]}", f"rank_{LABELS[0]}",
        f"importance_mean_{LABELS[1]}", f"rank_{LABELS[1]}",
        "n_methods_agree", "n_labels_univariate_flag", "n_labels_tree_flag", "verdict",
    ]
    merged = merged[ordered_cols].sort_values(
        ["n_methods_agree", f"cliffs_delta_{LABELS[0]}"],
        ascending=[False, False], key=lambda s: s.abs() if s.name == f"cliffs_delta_{LABELS[0]}" else s,
    )
    return merged.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main() -> None:
    df = build_dataset()

    rate_table = compute_rate_by_stratum(df)
    rate_table.to_csv(OUT_DIR / "01_particle_rate_by_stratum.csv", encoding="utf-8-sig", index=False)

    univariate = run_univariate_tests(df)
    univariate.to_csv(OUT_DIR / "02_univariate_test_results.csv", encoding="utf-8-sig", index=False)

    tree_importance = run_tree_importance(df)
    tree_importance.to_csv(OUT_DIR / "03_tree_importance.csv", encoding="utf-8-sig", index=False)

    final_table = build_final_table(univariate, tree_importance)
    final_table.to_csv(OUT_DIR / "04_particle_influence_factors_final.csv", encoding="utf-8-sig", index=False)

    summary = {
        "defect": DEFECT_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows_total": int(len(df)),
        "n_primary": int(df["is_particle_primary"].sum()),
        "n_broad": int(df["is_particle_broad"].sum()),
        "candidate_columns": ALL_FEATURE_COLS,
        "effect_size_min_cliffs_delta": EFFECT_SIZE_MIN,
        "fdr_alpha": config.TREND_ALPHA,
        "tree_top_n": TREE_TOP_N,
        "verdict_counts": final_table["verdict"].value_counts().to_dict(),
        "confirmed_factors": final_table.loc[final_table["verdict"] == "confirmed", "column"].tolist(),
    }
    with open(OUT_DIR / "00_particle_factors_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
