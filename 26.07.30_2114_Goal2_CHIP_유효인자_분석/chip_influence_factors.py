"""Goal 2 — NG_Code: CHIP 유효인자 발굴.

레이저 다이싱 공정에서 Chipping(모서리 파손) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney+FDR,
RandomForest permutation importance)을 모두 통과한 것만 "유효인자"로 확정한다.

**중요한 주의사항**: 이 defect는 이번 4개 분석 중 가장 희귀하다 — Primary/Broad 라벨 모두
정확히 4건(전체의 0.004%)뿐이다(NG_Code=='CHIP'와 Chipping==1이 완전히 동일한 4건).
train/test 분할 시 test셋에 양성 샘플이 1개만 남는 등 통계적으로 사실상 "패턴 탐지"가
아니라 "4개 사례의 개별 기록"에 가깝다. 결과는 절대 "확정"으로 읽지 말고, 다음 라운드에
더 많은 CHIP 사례가 쌓였을 때 재검증해야 할 극도로 잠정적인 순위로만 취급할 것.
자세한 한계는 DOMAIN_KNOWLEDGE.md 8절 참고.

BURN/PARTICLE/REM_COAT/CRACK과 코드 구조·통계 기준은 동일하다. 다만 Chipping은 팀
HealthIndex 설계서에 가장 명시적인 근거가 많은 defect라(Groove_Depth, Beam_Diameter,
Vibration, Focus가 전부 회의록/PDF에 직접 언급됨), 도메인 가설표는 다른 defect보다
"제 추론" 비중이 낮다.

pipeline/의 공용 전처리 산출물(OPCOND 층화 baseline)과 pipeline/common.py
헬퍼를 그대로 재사용한다. 원본 데이터/공용 pipeline 파일은 전혀 수정하지 않는다.

실행 (저장소 루트에서):
    python "26.07.30_2114_Goal2_CHIP_유효인자_분석/chip_influence_factors.py"

산출물 (이 폴더 안에 저장):
    00_chip_factors_summary.json         실행 메타데이터
    01_chip_rate_by_stratum.csv          Machine/Product/Recipe/OPCOND별 발생률 sanity check
    02_univariate_test_results.csv       Mann-Whitney U + BH-FDR + Cliff's delta (라벨별)
    03_tree_importance.csv               RandomForest permutation importance (라벨별)
    04_chip_influence_factors_final.csv  최종 교차검증 유효인자 표 (메인 산출물)
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
DEFECT_NAME = "CHIP"
NG_CODE_VALUE = "CHIP"
BINARY_COL = "Chipping"

CANDIDATE_COLS = config.FDC_COLS + config.RESPONSES
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
ALL_FEATURE_COLS = CANDIDATE_COLS + TEAM_DOMAIN_FEATURES

LABELS = ["is_chip_primary", "is_chip_broad"]

EFFECT_SIZE_MIN = 0.2
TREE_TOP_N = 10

# Chipping 물리 메커니즘: 절단 경계에서 재질이 매끈하게 제거되지 못하고 깨져나가는 현상.
# 팀 HealthIndex 설계서에 이번 4개 defect 중 가장 명시적인 근거가 많다
# (Groove_Depth/Beam_Diameter/Vibration/Focus 전부 회의록·PDF 직접 인용).
DOMAIN_HYPOTHESIS = {
    "Groove_Depth": ("가공 깊이 — Depth 부족 시 Low-k가 완전히 승화되지 못해 Blade 진입 시 Chipping 발생 (HealthIndex 설계서 C유형 명시적 근거)", "down"),
    "Beam_Diameter": ("빔 품질 — 협소 시 Width 감소로 Chipping 증가, 과다 시 Width 증가로 Die 영역 침범·손상 (HealthIndex 설계서 B유형 명시적 근거)", "either"),
    "Kerf_Width_Profile": ("절단 폭, Beam_Diameter가 만든 결과값이라 동일 메커니즘 상속 (HealthIndex 설계서 명시)", "either"),
    "Top_Kerf": ("절단 폭, Kerf_Width_Profile과 동일 메커니즘 상속", "either"),
    "Bottom_Kerf": ("절단 폭, Kerf_Width_Profile과 동일 메커니즘 상속", "either"),
    "Vibration": ("기계적 불안정 — 스테이지 흔들림으로 나이프 자국 형태로 잘려나가는 대형 불량 원인 (HealthIndex 설계서 회의록 명시적 근거)", "up"),
    "Focus": ("빔 집속 — 헤드온도 변화 시 굴절률 변화로 센터링 불량·Chipping·Depth/Width 이상 발생 (HealthIndex 설계서 PDF 근거 명시)", "either"),
    "Head_Temp": ("방열 능력 — Focus 이상을 매개로 간접적으로 Chipping에 연결 (Focus 메커니즘의 상류 원인)", "up"),
    "Cutting_X_Index": ("정렬/센터링 — 목표 절단선 이탈이 모서리 파손 유발 가능성 (E유형, Chipping이 이 계열의 알려진 실패모드)", "either"),
    "Cutting_Y_Index": ("정렬/센터링 — 위와 동일 이유", "either"),
    "Cutting_Offset": ("정렬/센터링 — 위와 동일 이유", "either"),
    "Laser_Centering_Position": ("정렬/센터링 — 빔 중심 이탈이 비대칭 절단·모서리 손상 유발 가능성", "either"),
    "Kerf_Angle": ("정렬/센터링 — 절단면 수직도 이상이 모서리 파손과 연결될 가능성", "either"),
    "Package_Size_1": ("정렬 불량의 동반지표 — 센터링이 틀어지면 다이 크기 불균형과 동시에 Chipping 위험 증가 가능성", "either"),
    "Package_Size_2": ("정렬 불량의 동반지표 — 위와 동일 이유", "either"),
    "Package_Size_3": ("정렬 불량의 동반지표 — 위와 동일 이유", "either"),
    "Package_Size_4": ("정렬 불량의 동반지표 — 위와 동일 이유", "either"),
    "Laser_Head_Remain_Time": ("헤드 노후 — 빔 품질 저하 시 Chipping 위험 증가 가능성(제 추론)", "down"),
    "Surface_Roughness": ("결과 공변(동반증상 후보) — 모서리 파손 부위가 표면 거칠기를 높일 가능성, 원인 아닐 수 있음", "up"),
}

# 방열/체류시간(Burn 전용), 세정/코팅(Particle·Remain_Coat 전용) 계열은 Chipping의
# 알려진 메커니즘(가공 깊이/폭, 진동, 정렬)과 물리적으로 겹치지 않는다고 판단했다.
NOT_RELATED_TO_DEFECT = {
    "Laser_Power": "에너지 투입 계열 — Burn 전용 메커니즘(열 축적), Chipping(기계적 파손)과 직접 연결고리 없음",
    "Power_Efficiency": "에너지 투입 계열 — Burn 전용 메커니즘, Chipping과 직접 연결고리 없음",
    "Feed_Speed": "체류시간 계열 — Burn 전용 메커니즘(열축적), Chipping과 명시적 연결고리 없음",
    "Frequency": "체류시간/열축적 계열 — Burn 전용 메커니즘, Chipping과 무관",
    "Alignment_Time": "체류시간 계열 — Burn 전용 메커니즘, Chipping과 무관",
    "Process_Time": "체류시간 계열 — Burn 전용 메커니즘, Chipping과 무관",
    "Cooling_Flow": "방열 계열 — Burn 전용 메커니즘(열 축적), Chipping과 직접 연결고리 없음",
    "Cooling_Water_Temp": "방열 계열 — Burn 전용 메커니즘, Chipping과 직접 연결고리 없음",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — Burn 전용 메커니즘, Chipping과 무관",
    "CLN_Flow": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, Chipping과 무관",
    "CLN_Pressure": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, Chipping과 무관",
    "CLN_Time": "세정 계열 — Particle/Remain_Coat 전용 메커니즘, Chipping과 무관",
    "Coating_Flow": "세정/코팅 계열 — Particle/Remain_Coat 전용 메커니즘, Chipping과 무관",
    "Cleaning_Capacity": "팀 공용 피처, 세정 계열 — Chipping과 무관",
    "Cleaning_Load_Ratio": "팀 공용 피처, 세정 계열 — Chipping과 무관",
    "Laser_Cleaning_Demand": "팀 공용 피처, 세정 계열(디브리 발생 수요) — Chipping과 무관",
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
    result["is_chip_primary"] = result["NG_Code"] == NG_CODE_VALUE
    result["is_chip_broad"] = result[BINARY_COL] == 1
    return result


def build_dataset() -> pd.DataFrame:
    df = load_dataset()
    df = add_labels(df)

    baseline_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
    baseline_stats = pd.read_csv(baseline_path)

    df = zscore_transform(df, baseline_stats, config.OPCOND, ALL_FEATURE_COLS)
    return df


# ---------------------------------------------------------------------------
# 1단계: CHIP 발생률 sanity check
# ---------------------------------------------------------------------------

def compute_rate_by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    strata = [["Machine_ID"], ["Product_ID"], ["Recipe_ID"], config.OPCOND]
    frames = []
    for keys in strata:
        g = df.groupby(keys)["is_chip_primary"].agg(n="count", n_defect="sum", rate="mean")
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    df = build_dataset()

    rate_table = compute_rate_by_stratum(df)
    rate_table.to_csv(OUT_DIR / "01_chip_rate_by_stratum.csv", encoding="utf-8-sig", index=False)

    univariate = run_univariate_tests(df)
    univariate.to_csv(OUT_DIR / "02_univariate_test_results.csv", encoding="utf-8-sig", index=False)

    tree_importance = run_tree_importance(df)
    tree_importance.to_csv(OUT_DIR / "03_tree_importance.csv", encoding="utf-8-sig", index=False)

    final_table = build_final_table(univariate, tree_importance)
    final_table.to_csv(OUT_DIR / "04_chip_influence_factors_final.csv", encoding="utf-8-sig", index=False)

    summary = {
        "defect": DEFECT_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows_total": int(len(df)),
        "n_primary": int(df["is_chip_primary"].sum()),
        "n_broad": int(df["is_chip_broad"].sum()),
        "statistical_power_warning": (
            "이번 4개 defect 분석 중 가장 희귀한 이벤트(정확히 4건, 0.004%). "
            "train/test 분할 시 test셋 양성 표본이 1개뿐이라 패턴 탐지가 아니라 "
            "개별 사례 기록에 가깝다. 절대 확정으로 읽지 말 것."
        ),
        "candidate_columns": ALL_FEATURE_COLS,
        "effect_size_min_cliffs_delta": EFFECT_SIZE_MIN,
        "fdr_alpha": config.TREND_ALPHA,
        "tree_top_n": TREE_TOP_N,
        "verdict_counts": final_table["verdict"].value_counts().to_dict(),
        "confirmed_factors": final_table.loc[final_table["verdict"] == "confirmed", "column"].tolist(),
    }
    with open(OUT_DIR / "00_chip_factors_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
