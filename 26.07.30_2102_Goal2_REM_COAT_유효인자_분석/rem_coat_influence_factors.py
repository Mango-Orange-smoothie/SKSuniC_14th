"""Goal 2 — NG_Code: REM_COAT 유효인자 발굴.

레이저 다이싱 공정에서 Remain_Coat(코팅 잔류) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney+FDR,
RandomForest permutation importance)을 모두 통과한 것만 "유효인자"로 확정한다.

BURN/PARTICLE 분석과 코드 구조·통계 기준은 동일하지만, Remain_Coat의 물리 메커니즘
(세정 공정이 보호 코팅을 다 씻어내지 못함)에 맞춰 도메인 가설은 새로 세웠다.
특히 이 defect는 "세정 부족"이 사실상 유일한 알려진 메커니즘이라, 절단(레이저) 관련
변수 대부분을 무관으로 분류했다 — Particle과 반드시 비교해서 읽을 것.

pipeline/의 공용 전처리 산출물(OPCOND 층화 baseline)과 pipeline/common.py
헬퍼를 그대로 재사용한다. 원본 데이터/공용 pipeline 파일은 전혀 수정하지 않는다.

실행 (저장소 루트에서):
    python "26.07.30_2102_Goal2_REM_COAT_유효인자_분석/rem_coat_influence_factors.py"

산출물 (이 폴더 안에 저장):
    00_rem_coat_factors_summary.json         실행 메타데이터
    01_rem_coat_rate_by_stratum.csv          Machine/Product/Recipe/OPCOND별 발생률 sanity check
    02_univariate_test_results.csv           Mann-Whitney U + BH-FDR + Cliff's delta (라벨별)
    03_tree_importance.csv                   RandomForest permutation importance (라벨별)
    04_rem_coat_influence_factors_final.csv  최종 교차검증 유효인자 표 (메인 산출물)
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
    compute_stratum_baseline_stats,
    load_dataset,
    stratified_split_by_defect,
    zscore_transform,
)

OUT_DIR = Path(__file__).resolve().parent
DEFECT_NAME = "REM_COAT"
NG_CODE_VALUE = "REM_COAT"
BINARY_COL = "Remain_Coat"

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
NEEDS_CUSTOM_BASELINE = ["Maintenance_Count"]
ALL_FEATURE_COLS = CANDIDATE_COLS + TEAM_DOMAIN_FEATURES + NEEDS_CUSTOM_BASELINE

LABELS = ["is_remcoat_primary", "is_remcoat_broad"]

EFFECT_SIZE_MIN = 0.2
TREE_TOP_N = 10

# Remain_Coat 물리 메커니즘: 다이싱 전 웨이퍼 표면을 보호하기 위해 바른 코팅을,
# 다이싱 후 세정 공정이 완전히 씻어내지 못하고 남기는 것. 절단(레이저) 자체보다
# "세정 공정이 코팅을 얼마나 잘 제거하는가"에 좌우되는 defect라고 판단했다 — 그래서
# Particle 분석과 달리 레이저/빔 관련 변수 대부분을 무관으로 분류했다(5절 참고).
DOMAIN_HYPOTHESIS = {
    "CLN_Flow": ("세정 능력 — 유량 부족 시 코팅 미제거 (HealthIndex 설계서 CLN_Pressure 근거와 동일 계열)", "down"),
    "CLN_Pressure": ("세정 능력 — 압력 부족 시 코팅 미제거 (HealthIndex 설계서 C유형 명시적 근거)", "down"),
    "CLN_Time": ("세정 능력 — 시간 부족 시 코팅 미제거 (HealthIndex 설계서 C유형 추정 근거)", "down"),
    "Coating_Flow": ("코팅 도포 균일성 — 불균일 도포 시 일부 영역 과도포되어 제거 어려움 가능성", "either"),
    "Surface_Roughness": ("결과 공변(동반증상 후보) — 코팅 잔류가 표면 거칠기를 바꿀 가능성, 원인 아닐 수 있음", "either"),
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하가 코팅 소작(燒灼) 효율에 간접 영향 가능성(약한 가설)", "down"),
    "Cleaning_Capacity": ("팀 공용 피처(CLN_Flow×Pressure×Time) — 세정 능력 종합지표, 이 defect의 핵심 메커니즘", "down"),
    "Cleaning_Load_Ratio": ("팀 공용 피처(디브리수요/세정능력) — 분자가 원래 디브리(Particle) 기준이라 이 defect엔 다소 부정확할 수 있으나 세정능력 축은 공유", "up"),
    "Maintenance_Count": (
        "정비 이력 프록시(00_column_classification.csv decision_note가 Goal2 확인 가치 있다고 명시) "
        "— 세정계 정비와 연관될 수 있으나 방향 상충 가능성이 있어 특정하지 않음",
        "either",
    ),
}

# 코팅 제거는 절단(레이저) 서브시스템과 물리적으로 분리된 "세정" 서브시스템의 일이라고
# 판단했다 — 레이저 출력/빔 품질/진동/절단 깊이가 코팅을 얼마나 씻어내는지에 직접
# 영향을 준다는 근거를 찾지 못했다. 정렬/센터링, 방열/체류시간 계열도 Particle과 동일한
# 이유로 무관.
NOT_RELATED_TO_DEFECT = {
    "Laser_Centering_Position": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 세정과 무관",
    "Cutting_X_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 세정과 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 세정과 무관",
    "Cutting_Offset": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 세정과 무관",
    "Kerf_Angle": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 절단면 수직도, 세정과 무관",
    "Package_Size_1": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 세정과 무관",
    "Package_Size_2": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 세정과 무관",
    "Package_Size_3": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 세정과 무관",
    "Package_Size_4": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 세정과 무관",
    "Head_Temp": "방열/체류시간 계열 — Burn 전용 메커니즘(열 축적), 세정 효율과 직접 연결고리 없음",
    "Cooling_Flow": "방열/체류시간 계열 — Burn 전용 메커니즘, 세정 효율과 직접 연결고리 없음",
    "Cooling_Water_Temp": "방열/체류시간 계열 — Burn 전용 메커니즘, 세정 효율과 직접 연결고리 없음",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — Burn 전용 메커니즘, 세정과 무관",
    "Frequency": "방열/체류시간 계열 — Burn 전용 메커니즘(펄스 중첩→열), 세정과 무관",
    "Alignment_Time": "방열/체류시간 계열 — Burn 전용 메커니즘, 세정과 무관",
    "Process_Time": "방열/체류시간 계열 — Burn 전용 메커니즘, 세정과 무관",
    "Feed_Speed": "방열/체류시간 계열 — Burn 전용 메커니즘, 세정과 무관",
    "Laser_Power": "절단(레이저) 서브시스템 — 코팅 제거는 별도의 세정 서브시스템이 담당한다고 판단, 세정 효율과 직접 연결고리 없음",
    "Power_Efficiency": "절단(레이저) 서브시스템 — 코팅 제거는 별도의 세정 서브시스템, 세정 효율과 직접 연결고리 없음",
    "Focus": "절단(레이저) 서브시스템 — 코팅 제거는 별도의 세정 서브시스템, 세정 효율과 직접 연결고리 없음",
    "Beam_Diameter": "절단(레이저) 서브시스템 — 코팅 제거는 별도의 세정 서브시스템, 세정 효율과 직접 연결고리 없음",
    "Vibration": "기계적 진동 — Particle(디브리 비산)과는 관련 있으나 코팅 화학적/유체적 제거 효율과는 무관",
    "Groove_Depth": "절단 깊이 — 코팅층 제거량과는 별개(코팅은 표면층, Groove는 기판 절단 깊이)",
    "Kerf_Width_Profile": "절단 폭 — 코팅 제거와 무관, Chipping/Particle 계열",
    "Top_Kerf": "절단 폭, Kerf_Width_Profile과 동일 이유로 무관",
    "Bottom_Kerf": "절단 폭, Kerf_Width_Profile과 동일 이유로 무관",
    "Laser_Cleaning_Demand": "팀 공용 피처(Laser_Power×Groove_Depth) — '디브리 발생 수요' 개념이라 Particle에 더 적합, Remain_Coat(코팅 자체 잔류)와는 개념이 다름",
}

TEAM_UNDETERMINED = {
    "Laser_Current": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Laser_Voltage": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족(팀 미확정)",
    "Coating_Thickness": (
        "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실. "
        "**REM_COAT에서는 데이터 누수 위험이 특히 큼**: 세정 후 측정값이라면 "
        "잔류 코팅량과 사실상 동어반복이 되어 '원인'이 아니라 '같은 것을 두 번 재는' 문제가 된다. "
        "측정 시점 확인 전까지는 후보에서 제외."
    ),
    "Coating_Uniformity": (
        "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실. "
        "Coating_Thickness와 동일한 데이터 누수 위험으로 제외."
    ),
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
    result["is_remcoat_primary"] = result["NG_Code"] == NG_CODE_VALUE
    result["is_remcoat_broad"] = result[BINARY_COL] == 1
    return result


def build_dataset() -> pd.DataFrame:
    df = load_dataset()
    df = add_labels(df)

    baseline_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
    baseline_stats = pd.read_csv(baseline_path)

    custom_baseline = compute_stratum_baseline_stats(
        df[df["is_normal"]], config.OPCOND, NEEDS_CUSTOM_BASELINE
    )
    baseline_stats_ext = pd.concat([baseline_stats, custom_baseline], ignore_index=True)

    df = zscore_transform(df, baseline_stats_ext, config.OPCOND, ALL_FEATURE_COLS)
    return df


# ---------------------------------------------------------------------------
# 1단계: REM_COAT 발생률 sanity check
# ---------------------------------------------------------------------------

def compute_rate_by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    strata = [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], config.OPCOND]
    frames = []
    for keys in strata:
        g = df.groupby(keys)["is_remcoat_primary"].agg(n="count", n_defect="sum", rate="mean")
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
    rate_table.to_csv(OUT_DIR / "01_rem_coat_rate_by_stratum.csv", encoding="utf-8-sig", index=False)

    univariate = run_univariate_tests(df)
    univariate.to_csv(OUT_DIR / "02_univariate_test_results.csv", encoding="utf-8-sig", index=False)

    tree_importance = run_tree_importance(df)
    tree_importance.to_csv(OUT_DIR / "03_tree_importance.csv", encoding="utf-8-sig", index=False)

    final_table = build_final_table(univariate, tree_importance)
    final_table.to_csv(OUT_DIR / "04_rem_coat_influence_factors_final.csv", encoding="utf-8-sig", index=False)

    summary = {
        "defect": DEFECT_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows_total": int(len(df)),
        "n_primary": int(df["is_remcoat_primary"].sum()),
        "n_broad": int(df["is_remcoat_broad"].sum()),
        "candidate_columns": ALL_FEATURE_COLS,
        "effect_size_min_cliffs_delta": EFFECT_SIZE_MIN,
        "fdr_alpha": config.TREND_ALPHA,
        "tree_top_n": TREE_TOP_N,
        "verdict_counts": final_table["verdict"].value_counts().to_dict(),
        "confirmed_factors": final_table.loc[final_table["verdict"] == "confirmed", "column"].tolist(),
    }
    with open(OUT_DIR / "00_rem_coat_factors_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
