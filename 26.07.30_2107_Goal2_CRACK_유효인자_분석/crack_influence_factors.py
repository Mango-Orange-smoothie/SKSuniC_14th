"""Goal 2 — NG_Code: CRACK 유효인자 발굴.

레이저 다이싱 공정에서 Micro_Crack(미세균열) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney+FDR,
RandomForest permutation importance)을 모두 통과한 것만 "유효인자"로 확정한다.

**중요한 주의사항**: 이 defect는 극희귀 이벤트다 — Primary 라벨(NG_Code=='CRACK') 34건,
Broad 라벨(Micro_Crack==1) 41건, 전체의 0.03~0.04%뿐이다. 통계 검정력이 BURN/PARTICLE/
REM_COAT보다 훨씬 약하므로 결과를 "확정"이 아니라 "가설 순위"로 읽어야 한다. 자세한
한계는 DOMAIN_KNOWLEDGE.md 8절 참고.

BURN/PARTICLE/REM_COAT 분석과 코드 구조·통계 기준은 동일하지만, Crack의 물리 메커니즘
(열/기계적 스트레스로 인한 파단)에 맞춰 도메인 가설은 새로 세웠다. 팀 HealthIndex
설계서에는 Crack에 대한 명시적 메커니즘 서술이 거의 없어(주로 Chipping/Remain_Coat/Burn
위주), 이번 도메인 가설 대부분은 레이저 가공 일반 물리(열충격, 피로파괴)에 기반한
작성자의 추론이다 — 아래 표에 "제 추론"으로 명시했다.

pipeline/의 공용 전처리 산출물(OPCOND 층화 baseline)과 pipeline/common.py
헬퍼를 그대로 재사용한다. 원본 데이터/공용 pipeline 파일은 전혀 수정하지 않는다.

실행 (저장소 루트에서):
    python "26.07.30_2107_Goal2_CRACK_유효인자_분석/crack_influence_factors.py"

산출물 (이 폴더 안에 저장):
    00_crack_factors_summary.json         실행 메타데이터
    01_crack_rate_by_stratum.csv          Machine/Product/Recipe/OPCOND별 발생률 sanity check
    02_univariate_test_results.csv        Mann-Whitney U + BH-FDR + Cliff's delta (라벨별)
    03_tree_importance.csv                RandomForest permutation importance (라벨별)
    04_crack_influence_factors_final.csv  최종 교차검증 유효인자 표 (메인 산출물)
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
DEFECT_NAME = "CRACK"
NG_CODE_VALUE = "CRACK"
BINARY_COL = "Micro_Crack"

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
NEEDS_CUSTOM_BASELINE = ["Maintenance_Count"]
ALL_FEATURE_COLS = CANDIDATE_COLS + TEAM_DOMAIN_FEATURES + NEEDS_CUSTOM_BASELINE

LABELS = ["is_crack_primary", "is_crack_broad"]

EFFECT_SIZE_MIN = 0.2
TREE_TOP_N = 10

# Micro_Crack 물리 메커니즘: 재료의 파단강도를 넘어서는 열적/기계적 스트레스가 미세균열을
# 만든다는 게 핵심 가설. 팀 문서에 명시적 근거가 거의 없어 대부분 레이저 가공 일반
# 물리(열충격, 진동 피로)에 기반한 작성자의 추론이다 — DOMAIN_KNOWLEDGE.md에서
# "제 추론" 여부를 컬럼별로 명시했다.
DOMAIN_HYPOTHESIS = {
    "Laser_Power": ("에너지 투입 — 급격한 국소 가열이 열충격 스트레스 유발(제 추론)", "up"),
    "Power_Efficiency": ("에너지 변환 이상 — 비정상 에너지 전달이 국소 스트레스 유발 가능성(제 추론)", "either"),
    "Head_Temp": ("방열 능력 — 방열 여력 저하 시 열충격 스트레스 증가(제 추론, Burn과 메커니즘 축 공유)", "up"),
    "Cooling_Flow": ("방열 능력 — 냉각 부족 시 급격한 온도구배로 열충격 스트레스 증가(제 추론)", "down"),
    "Cooling_Water_Temp": ("방열 능력 — 냉각수 온도 상승 시 열충격 스트레스 증가(제 추론)", "up"),
    "Cooling_Thermal_Load": ("팀 공용 피처, 방열 능력 — 위와 동일 메커니즘(제 추론)", "up"),
    "Focus": ("빔 품질/집속 — 초점 이탈 시 국소 에너지밀도 이상이 응력 집중 유발 가능성(제 추론)", "either"),
    "Beam_Diameter": ("빔 품질/집속 — 위와 동일 이유(제 추론)", "either"),
    "Laser_Centering_Position": ("빔 품질/집속 — 편심이 비대칭 열/응력 분포 유발 가능성(제 추론)", "either"),
    "Vibration": ("기계적 스트레스 — 진동에 의한 반복 응력이 피로파괴형 미세균열 유발(제 추론)", "up"),
    "Feed_Speed": ("기계적/열적 스트레스 — 빠를수록 기계적 응력속도 증가, 느릴수록 열축적 증가로 상충되는 두 메커니즘이 공존(제 추론)", "either"),
    "Frequency": ("열피로 — 펄스 반복에 의한 열-기계 피로 축적 가능성(제 추론, Burn의 펄스중첩 가설과 연결)", "up"),
    "Process_Time": ("누적 스트레스 노출 — 공정시간이 길수록 누적 응력 노출 증가(제 추론)", "up"),
    "Alignment_Time": ("누적 스트레스 노출 — 위와 동일 이유(제 추론)", "up"),
    "Groove_Depth": ("응력 집중 — 그루브가 깊을수록 절단 팁(선단)에 응력이 집중될 가능성(제 추론)", "up"),
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하 시 국소 응력집중 가능성(제 추론)", "down"),
    "Surface_Roughness": ("결과 공변(동반증상 후보) — 균열이 표면 거칠기를 바꿀 가능성, 원인 아닐 수 있음(제 추론)", "up"),
    "Maintenance_Count": (
        "정비 이력 프록시(00_column_classification.csv decision_note가 Goal2 확인 가치 있다고 명시) "
        "— 정비 직후 재교정 스트레스 또는 정비 주기가 긴 설비의 누적 피로, 상충 가능성 있어 미특정",
        "either",
    ),
}

# 정렬/센터링, 세정 계열은 파단(균열) 메커니즘과 직접 연결고리가 없다고 판단했다.
NOT_RELATED_TO_DEFECT = {
    "Cutting_X_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 파단 스트레스와 무관",
    "Cutting_Y_Index": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 파단 스트레스와 무관",
    "Cutting_Offset": "정렬/센터링 계열(HealthIndex 설계서 E유형) — Chipping 메커니즘, 파단 스트레스와 무관",
    "Kerf_Angle": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 절단면 수직도, 파단 스트레스와 무관",
    "Package_Size_1": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 파단과 무관",
    "Package_Size_2": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 파단과 무관",
    "Package_Size_3": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 파단과 무관",
    "Package_Size_4": "정렬/센터링 계열(HealthIndex 설계서 E유형) — 다이 크기 불균형은 센터링 지표, 파단과 무관",
    "Kerf_Width_Profile": "절단 폭 — 재질 제거 폭 지표, 파단 스트레스와는 별개 메커니즘(Particle/Chipping 계열)",
    "Top_Kerf": "절단 폭, Kerf_Width_Profile과 동일 이유로 무관",
    "Bottom_Kerf": "절단 폭, Kerf_Width_Profile과 동일 이유로 무관",
    "CLN_Flow": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, 파단 스트레스와 무관",
    "CLN_Pressure": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, 파단 스트레스와 무관",
    "CLN_Time": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, 파단 스트레스와 무관",
    "Coating_Flow": "세정/코팅 계열 — Particle/Remain_Coat 전용 메커니즘, 파단 스트레스와 무관",
    "Cleaning_Capacity": "팀 공용 피처, 세정 계열 — 파단 스트레스와 무관",
    "Cleaning_Load_Ratio": "팀 공용 피처, 세정 계열 — 파단 스트레스와 무관",
    "Laser_Cleaning_Demand": "팀 공용 피처, 세정 계열(디브리 발생 수요) — 파단 스트레스와 무관",
}

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
    result["is_crack_primary"] = result["NG_Code"] == NG_CODE_VALUE
    result["is_crack_broad"] = result[BINARY_COL] == 1
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
# 1단계: CRACK 발생률 sanity check
# ---------------------------------------------------------------------------

def compute_rate_by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    strata = [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], config.OPCOND]
    frames = []
    for keys in strata:
        g = df.groupby(keys)["is_crack_primary"].agg(n="count", n_defect="sum", rate="mean")
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
    # Windows 콘솔(cp949)에서 한글 특수문자(em-dash 등) 출력 시 깨지는 것 방지.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    df = build_dataset()

    rate_table = compute_rate_by_stratum(df)
    rate_table.to_csv(OUT_DIR / "01_crack_rate_by_stratum.csv", encoding="utf-8-sig", index=False)

    univariate = run_univariate_tests(df)
    univariate.to_csv(OUT_DIR / "02_univariate_test_results.csv", encoding="utf-8-sig", index=False)

    tree_importance = run_tree_importance(df)
    tree_importance.to_csv(OUT_DIR / "03_tree_importance.csv", encoding="utf-8-sig", index=False)

    final_table = build_final_table(univariate, tree_importance)
    final_table.to_csv(OUT_DIR / "04_crack_influence_factors_final.csv", encoding="utf-8-sig", index=False)

    summary = {
        "defect": DEFECT_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows_total": int(len(df)),
        "n_primary": int(df["is_crack_primary"].sum()),
        "n_broad": int(df["is_crack_broad"].sum()),
        "statistical_power_warning": (
            "극희귀 이벤트(Primary 34건, Broad 41건). 결과를 확정이 아닌 가설 순위로 읽을 것"
        ),
        "candidate_columns": ALL_FEATURE_COLS,
        "effect_size_min_cliffs_delta": EFFECT_SIZE_MIN,
        "fdr_alpha": config.TREND_ALPHA,
        "tree_top_n": TREE_TOP_N,
        "verdict_counts": final_table["verdict"].value_counts().to_dict(),
        "confirmed_factors": final_table.loc[final_table["verdict"] == "confirmed", "column"].tolist(),
    }
    with open(OUT_DIR / "00_crack_factors_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
