"""Goal 2 — PARTICLE 유효인자 후속 검증.

Jun 브랜치의 `26.07.30_2055_Goal2_PARTICLE_유효인자_분석/`이 1차 스크리닝을 끝내고
confirmed 2건(Surface_Roughness, Vibration)을 냈다. 그 README가 스스로 "더 봐야 한다"고
남긴 미해결 질문들을 데이터로 검증하는 것이 이 모듈의 목적이다. 같은 스크리닝을 다시
돌리지 않는다.

  검증1  Surface_Roughness는 원인인가 결과인가        (Jun: "결과 공변일 가능성이 매우 높다")
  검증2  particle 심각도(Die 수)와의 용량-반응 관계    (검증1의 독립적 교차확인)
  검증3  Cleaning_Load_Ratio 비율 정의 재검토          (Jun: "비율 계산 방식 재검토 여지")
  검증4  PARTICLE ∩ REM_COAT 동시발생의 공통 근본원인  (Jun: "세정 부족 공유 가능성 시사")
  검증5  OPCOND vs GROUP 층 선택 민감도                (팀 내 층 정의가 분석마다 다름)

검증5를 넣은 이유: Jun의 분석은 OPCOND(Product×Recipe) 층화를 썼는데, 기존
`analysis_outputs/03_impact_factor_ranking.csv`와 `pipeline/README.md`의 GROUP 설명은
Machine을 통제변수로 두는 쪽이다. 층을 바꾸면 "장비 간 차이"가 신호에 포함되느냐 아니냐가
달라지고, 그에 따라 조치 주체가 공정 파라미터냐 설비 정비냐로 갈린다. 결론이 층 선택에
얼마나 민감한지 확인하지 않으면 어느 쪽 조치를 권고할지 정할 수 없다.

통계 규약(Mann-Whitney U + BH-FDR + Cliff's delta, 효과크기 임계값 0.2)은 Jun의
분석과 동일하게 유지해 숫자를 직접 비교할 수 있게 했다.

실행 (저장소 루트에서):
    python "26.07.31_2058_Goal2_PARTICLE_후속검증/particle_followup_validation.py"
    python "26.07.31_2058_Goal2_PARTICLE_후속검증/particle_followup_validation.py" --data "D:/경로/DP_HealthIndex_Dataset.csv"

산출물 (이 폴더 안에 저장):
    00_followup_summary.json                실행 메타데이터 + 검증별 결론
    01_surface_roughness_temporal.csv       검증1: 동시점 vs 선행(lag) 판별력
    02_dose_response_particle_die.csv       검증2: Die 수 구간별 z 프로파일
    03_cleaning_load_ratio_variants.csv     검증3: 비율 정의 4종 비교
    04_particle_remcoat_cooccurrence.csv    검증4: 동시발생 그룹별 세정계 프로파일
    05_stratum_sensitivity.csv              검증5: OPCOND vs GROUP 효과크기 비교
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.stats.multitest import multipletests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

PRIMARY_LABEL = "is_particle_primary"   # NG_Code == 'PARTICLE'
BROAD_LABEL = "is_particle_broad"       # Particle == 1
LABELS = [PRIMARY_LABEL, BROAD_LABEL]

# Jun의 분석과 동일한 판정 임계값 — 바꾸면 숫자를 직접 비교할 수 없게 된다.
EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = config.TREND_ALPHA

# 검증1에서 "선행 신호"를 볼 때 쓸 직전 스트립 개수.
LAG_WINDOWS = [5, 20, 50]

# 검증1/2의 주 대상. Vibration은 대조군 역할 — 설비 조작 인자이므로 진짜 상류 원인이라면
# 선행 구간에서도 신호가 남아야 한다. Surface_Roughness만 선행 신호가 사라진다면
# "동시에 측정된 결과"라는 해석이 강해진다.
TEMPORAL_TARGETS = ["Surface_Roughness", "Vibration"]

# 검증4에서 볼 세정 계열 인자.
CLEANING_COLS = [
    "CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
    "Cleaning_Capacity", "Laser_Cleaning_Demand", "Cleaning_Load_Ratio",
]

# 검증5 후보: Jun이 쓴 것과 동일한 피처셋.
ALL_FEATURE_COLS = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]


# ---------------------------------------------------------------------------
# 공통 헬퍼 — Jun의 분석과 계산이 동일해야 숫자를 비교할 수 있다
# ---------------------------------------------------------------------------

def cliffs_delta(group_vals: pd.Series, rest_vals: pd.Series) -> tuple[float, float, int, int]:
    """Mann-Whitney U 기반 Cliff's delta. 반환: (delta, p_value, n_group, n_rest).

    delta = 2*U/(n1*n2) - 1 이며 -1~+1. 부호가 +면 group 쪽 값이 크다.
    """
    g = pd.Series(group_vals).dropna()
    r = pd.Series(rest_vals).dropna()
    if len(g) < 3 or len(r) < 3:
        return np.nan, np.nan, len(g), len(r)
    u_stat, p_value = scipy_stats.mannwhitneyu(g, r, alternative="two-sided")
    delta = (2 * u_stat) / (len(g) * len(r)) - 1
    return float(delta), float(p_value), len(g), len(r)


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result[PRIMARY_LABEL] = result["NG_Code"] == "PARTICLE"
    result[BROAD_LABEL] = result["Particle"] == 1
    return result


def stratified_z(df: pd.DataFrame, stratum_keys: list[str], columns: list[str]) -> pd.DataFrame:
    """정상군(OK) 기준 층별 baseline을 만들고 robust z를 붙인다.

    Jun은 step0가 미리 저장해둔 00_stratum_baseline_stats_by_opcond.csv를 읽었지만,
    그 파일 자체가 compute_stratum_baseline_stats(OK행, OPCOND) 산출물이므로 여기서
    직접 계산해도 결과는 동일하다. 이 브랜치에 analysis_outputs/가 없어도 돌아가게
    하려고 직접 계산 방식을 택했다.
    """
    baseline = compute_stratum_baseline_stats(df.loc[df["is_normal"]], stratum_keys, columns)
    return zscore_transform(df, baseline, stratum_keys, columns)


# ---------------------------------------------------------------------------
# 검증 1 — Surface_Roughness는 원인인가 결과인가 (시간 선행성)
# ---------------------------------------------------------------------------

def temporal_precedence(df_z: pd.DataFrame) -> pd.DataFrame:
    """같은 설비의 '직전 스트립들' 값이 현재 스트립의 particle을 예측하는지 본다.

    논리: 어떤 인자가 particle의 원인이라면, 그 인자가 나빠진 상태가 particle 발생보다
    시간적으로 앞서야 한다. 반대로 particle의 '결과'(동반증상)라면 같은 스트립에서
    동시에 측정될 때만 신호가 보이고, 직전 스트립들에는 신호가 없어야 한다.

    현재 행을 반드시 제외하기 위해 shift(1) 후 rolling 평균을 쓴다. 설비별로 따로
    계산하는 이유는 스트립 순서가 설비 안에서만 의미가 있기 때문이다.

    주의: 이것은 인과 증명이 아니라 '결과 공변 가설을 반증할 수 있는가' 하는 검사다.
    두 인자가 공통 원인을 공유해 함께 서서히 움직인다면 선행 신호도 함께 나타날 수 있다.
    """
    ordered = df_z.sort_values(["Machine_ID", "DateTime"]).copy()
    rows = []

    for col in TEMPORAL_TARGETS:
        z_col = f"{col}_z"
        for label in LABELS:
            # 동시점: Jun이 잰 것과 같은 값 (비교 기준선)
            delta_now, p_now, n_g, n_r = cliffs_delta(
                ordered.loc[ordered[label], z_col], ordered.loc[~ordered[label], z_col]
            )
            for window in LAG_WINDOWS:
                lag_col = ordered.groupby("Machine_ID")[z_col].transform(
                    lambda s, w=window: s.shift(1).rolling(w, min_periods=max(3, w // 2)).mean()
                )
                delta_lag, p_lag, n_g_lag, n_r_lag = cliffs_delta(
                    lag_col[ordered[label]], lag_col[~ordered[label]]
                )
                # 선행 신호가 동시점 신호의 몇 %나 남아 있는가
                retention = (
                    abs(delta_lag) / abs(delta_now) if pd.notna(delta_now) and abs(delta_now) > 1e-9 else np.nan
                )
                rows.append({
                    "column": col,
                    "label": label,
                    "lag_window_strips": window,
                    "n_group": n_g,
                    "n_rest": n_r,
                    "cliffs_delta_concurrent": delta_now,
                    "p_concurrent": p_now,
                    "cliffs_delta_lagged": delta_lag,
                    "p_lagged": p_lag,
                    "n_group_lagged": n_g_lag,
                    "signal_retention_ratio": retention,
                })

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    pvals = result["p_lagged"].fillna(1.0)
    rejected, p_adj, _, _ = multipletests(pvals, alpha=FDR_ALPHA, method="fdr_bh")
    result["p_lagged_fdr"] = p_adj
    result["lagged_significant"] = rejected & (result["cliffs_delta_lagged"].abs() >= EFFECT_SIZE_MIN)

    def interpret(row):
        if pd.isna(row["cliffs_delta_lagged"]):
            return "판정불가"
        if row["lagged_significant"]:
            return "선행신호 유지 — 상류 원인 가능성 잔존"
        if pd.notna(row["signal_retention_ratio"]) and row["signal_retention_ratio"] < 0.15:
            return "선행신호 소멸 — 결과 공변(동반증상) 해석 지지"
        return "선행신호 약함 — 판단 보류"

    result["interpretation"] = result.apply(interpret, axis=1)
    return result


# ---------------------------------------------------------------------------
# 검증 2 — particle 심각도(Die 수)와의 용량-반응 관계
# ---------------------------------------------------------------------------

def dose_response(df_z: pd.DataFrame) -> pd.DataFrame:
    """particle이 난 스트립 안에서, 불량 Die 수가 많을수록 인자값이 더 극단인가?

    Surface_Roughness가 particle의 '결과'라면, particle이 많이 붙은 스트립일수록
    표면이 더 거칠어야 한다 — 즉 Die 수와 강한 단조 증가 관계가 나와야 한다.
    반대로 원인 인자라면 발생 여부는 갈라도 개수까지 비례할 이유는 약하다.

    검증1과 독립적인 증거다. 검증1은 시간 축, 이쪽은 심각도 축을 본다.

    표본을 두 가지로 나눠 각각 계산한다. `Particle==1` 전체(broad)에는 REM_COAT
    동시발생 1,337건이 섞여 있어서, 세정계 인자에서 관측되는 용량-반응이 실제로는
    REM_COAT 쪽 신호일 수 있기 때문이다(검증4 참고). 동시발생 건을 뺀
    `particle_only`에서도 관계가 유지돼야 particle 고유의 심각도 인자라고 말할 수 있다.
    """
    samples = {
        "broad_particle_all": df_z[BROAD_LABEL],
        "particle_only_excl_remcoat": df_z[BROAD_LABEL] & (df_z["Remain_Coat"] == 0),
    }

    rows = []
    for sample_name, mask in samples.items():
        positive = df_z.loc[mask]
        for col in TEMPORAL_TARGETS + CLEANING_COLS:
            z_col = f"{col}_z"
            if z_col not in positive.columns:
                continue
            paired = positive[[z_col, "Particle_Die"]].dropna()
            if len(paired) < 30 or paired["Particle_Die"].nunique() < 3:
                continue
            rho, p_value = scipy_stats.spearmanr(paired["Particle_Die"], paired[z_col])

            # 구간별 중앙값으로 단조성을 눈으로도 확인할 수 있게 남긴다.
            buckets = paired.groupby("Particle_Die")[z_col].agg(n="count", median_z="median")
            buckets = buckets.loc[buckets["n"] >= 20]
            monotone = np.nan
            if len(buckets) >= 3:
                monotone, _ = scipy_stats.spearmanr(buckets.index, buckets["median_z"])

            rows.append({
                "sample": sample_name,
                "column": col,
                "n_particle_rows": len(paired),
                "spearman_rho_vs_die_count": float(rho),
                "p_value": float(p_value),
                "n_die_buckets_used": int(len(buckets)),
                "bucket_median_monotonicity": float(monotone) if pd.notna(monotone) else np.nan,
                "die_bucket_medians": json.dumps(
                    {int(k): round(float(v), 4) for k, v in buckets["median_z"].items()}, ensure_ascii=False
                ),
            })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    rejected, p_adj, _, _ = multipletests(result["p_value"].fillna(1.0), alpha=FDR_ALPHA, method="fdr_bh")
    result["p_fdr"] = p_adj
    result["significant"] = rejected

    # 두 표본에서 관계가 유지되는지 — REM_COAT 오염 여부 판정
    pivot = result.pivot(index="column", columns="sample", values="spearman_rho_vs_die_count")
    if set(samples).issubset(pivot.columns):
        # Spearman rho가 이 값 미만이면 10만 행에서 p값이 유의해도 실질적 의미가 없다고 본다.
        rho_floor = 0.05

        def contamination(col: str) -> str:
            broad = pivot.at[col, "broad_particle_all"]
            only = pivot.at[col, "particle_only_excl_remcoat"]
            if pd.isna(broad) or pd.isna(only):
                return "판정불가"
            if abs(broad) < rho_floor and abs(only) < rho_floor:
                return "양쪽 모두 무신호 — 심각도와 무관"
            if abs(broad) >= rho_floor and abs(only) < rho_floor:
                return "REM_COAT 동시발생 제거 시 소멸 — particle 고유 신호 아님"
            if abs(broad) < rho_floor <= abs(only):
                return "동시발생 제거 후에만 발현 — 오염에 가려져 있던 신호"
            if np.sign(broad) != np.sign(only):
                return "부호 역전 — 해석 불가, 재검토 필요"
            return "동시발생 제거 후에도 유지 — particle 고유 심각도 인자"
        result["contamination_check"] = result["column"].map(contamination)

    return result.sort_values(
        ["sample", "spearman_rho_vs_die_count"], key=lambda s: s.abs() if s.name != "sample" else s,
        ascending=[True, False],
    )


# ---------------------------------------------------------------------------
# 검증 3 — Cleaning_Load_Ratio 비율 정의 재검토
# ---------------------------------------------------------------------------

def cleaning_ratio_variants(df: pd.DataFrame, df_z: pd.DataFrame) -> pd.DataFrame:
    """세정 밸런스(수요/능력)를 표현하는 4가지 정의를 같은 검정에 태워 비교한다.

    Jun의 관찰: 분자(Laser_Cleaning_Demand)와 분모(Cleaning_Capacity)는 개별적으로
    트리 중요도에서 신호가 잡히는데, 둘을 나눈 비율은 오히려 신호가 약했다.

    원인 가설: 나눗셈은 두 변수의 스케일 차이와 분모의 롱테일에 지배당한다.
    Cleaning_Capacity는 세 변수의 곱(CLN_Flow×Pressure×Time)이라 분산이 크게 부풀어
    있어서, 비율을 취하면 분모 변동이 분자 신호를 덮어버릴 수 있다.

    대안:
      original : Demand / Capacity                    (현재 팀 공용 정의)
      log      : log(Demand) - log(Capacity)          곱셈 구조를 덧셈으로 펴서 롱테일 완화
      z_diff   : Demand_z - Capacity_z                층 정규화 후 차이 (스케일 무관)
      rank_diff: pct_rank(Demand) - pct_rank(Capacity) 층 내 순위 차이 (분포 형태 무관)
    """
    demand = df["Laser_Cleaning_Demand"]
    capacity = df["Cleaning_Capacity"]
    positive = (demand > 0) & (capacity > 0)

    variants = pd.DataFrame(index=df.index)
    variants["clr_original"] = demand / capacity
    variants["clr_log"] = np.where(positive, np.log(demand.where(positive)) - np.log(capacity.where(positive)), np.nan)

    frame = df[config.OPCOND].copy()
    frame["clr_original"] = variants["clr_original"]
    frame["clr_log"] = variants["clr_log"]
    frame["is_normal"] = df["is_normal"]

    # original/log는 원값이므로 다른 인자와 같은 조건에서 비교하려면 OPCOND 층화 z가 필요하다.
    frame_z = stratified_z(frame, config.OPCOND, ["clr_original", "clr_log"])

    # z_diff / rank_diff는 정의 자체가 이미 층 상대값이라 추가 z를 하지 않는다.
    z_diff = df_z["Laser_Cleaning_Demand_z"] - df_z["Cleaning_Capacity_z"]

    def pct_rank_within_opcond(series: pd.Series) -> pd.Series:
        return series.groupby([df[k] for k in config.OPCOND]).rank(pct=True)

    rank_diff = pct_rank_within_opcond(demand) - pct_rank_within_opcond(capacity)

    candidates = {
        "clr_original (현재 팀 공용 정의)": frame_z["clr_original_z"],
        "clr_log = log(Demand)-log(Capacity)": frame_z["clr_log_z"],
        "clr_z_diff = Demand_z - Capacity_z": z_diff,
        "clr_rank_diff = 층내 순위차": rank_diff,
    }

    rows = []
    for name, values in candidates.items():
        for label in LABELS:
            delta, p_value, n_g, n_r = cliffs_delta(values[df_z[label]], values[~df_z[label]])
            rows.append({
                "variant": name,
                "label": label,
                "n_group": n_g,
                "n_rest": n_r,
                "nan_rate": float(values.isna().mean()),
                "cliffs_delta": delta,
                "abs_cliffs_delta": abs(delta) if pd.notna(delta) else np.nan,
                "p_value": p_value,
            })

    result = pd.DataFrame(rows)
    rejected, p_adj, _, _ = multipletests(result["p_value"].fillna(1.0), alpha=FDR_ALPHA, method="fdr_bh")
    result["p_fdr"] = p_adj
    result["passes_jun_criteria"] = rejected & (result["abs_cliffs_delta"] >= EFFECT_SIZE_MIN)
    return result.sort_values("abs_cliffs_delta", ascending=False)


# ---------------------------------------------------------------------------
# 검증 4 — PARTICLE ∩ REM_COAT 동시발생의 공통 근본원인
# ---------------------------------------------------------------------------

def cooccurrence_profile(df_z: pd.DataFrame) -> pd.DataFrame:
    """particle만 / 코팅잔류만 / 둘 다 / 정상 — 네 그룹의 세정계 인자 프로파일 비교.

    Jun의 관찰: Particle==1(7,792)과 NG_Code=='PARTICLE'(6,455)의 차이 1,337건이 전부
    REM_COAT와 동시발생. 두 불량이 "세정 부족"이라는 근본원인을 공유한다면, '둘 다'
    그룹의 세정 능력 지표가 단독 그룹들보다 더 나쁜 쪽으로 치우쳐야 한다.

    반대로 '둘 다' 그룹이 단독 그룹과 다르지 않다면 단순 우연한 동시발생이고,
    두 불량은 따로 관리해야 한다.
    """
    particle = df_z["Particle"] == 1
    remain = df_z["Remain_Coat"] == 1

    groups = {
        "particle_only": particle & ~remain,
        "remain_coat_only": ~particle & remain,
        "both": particle & remain,
        "normal_ok": df_z["is_normal"],
    }

    rows = []
    for col in CLEANING_COLS:
        z_col = f"{col}_z"
        if z_col not in df_z.columns:
            continue
        samples = [df_z.loc[mask, z_col].dropna() for mask in groups.values()]
        usable = [s for s in samples if len(s) >= 3]
        kruskal_p = np.nan
        if len(usable) >= 2:
            _, kruskal_p = scipy_stats.kruskal(*usable)

        baseline = df_z.loc[groups["normal_ok"], z_col]
        record = {"column": col, "kruskal_p_across_groups": float(kruskal_p) if pd.notna(kruskal_p) else np.nan}
        for name, mask in groups.items():
            values = df_z.loc[mask, z_col]
            record[f"n_{name}"] = int(values.notna().sum())
            record[f"median_z_{name}"] = float(values.median()) if values.notna().any() else np.nan
            if name != "normal_ok":
                delta, _, _, _ = cliffs_delta(values, baseline)
                record[f"cliffs_delta_{name}_vs_normal"] = delta
        rows.append(record)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    # 공통 근본원인이 성립하려면 '둘 다' 그룹뿐 아니라 단독 그룹 '양쪽 모두'에서
    # 효과가 나타나야 한다. 한쪽 단독 그룹만 극단이라면 그 인자는 그 불량 전용이고,
    # '둘 다' 그룹의 신호는 그쪽에서 넘어온 것이다.
    def verdict(row):
        both = row.get("cliffs_delta_both_vs_normal")
        p_only = row.get("cliffs_delta_particle_only_vs_normal")
        r_only = row.get("cliffs_delta_remain_coat_only_vs_normal")
        if any(pd.isna(v) for v in (both, p_only, r_only)):
            return "판정불가"
        p_hit = abs(p_only) >= EFFECT_SIZE_MIN
        r_hit = abs(r_only) >= EFFECT_SIZE_MIN
        if p_hit and r_hit and np.sign(p_only) == np.sign(r_only):
            return "공통 근본원인 가설 지지 — 두 불량 단독 그룹 모두에서 발현"
        if r_hit and not p_hit:
            return "REM_COAT 전용 인자 — particle 단독 그룹에서는 무신호"
        if p_hit and not r_hit:
            return "PARTICLE 전용 인자 — REM_COAT 단독 그룹에서는 무신호"
        if abs(both) >= EFFECT_SIZE_MIN:
            return "동시발생 그룹에서만 발현 — 조합 조건 검토 필요"
        return "세 그룹 모두 효과크기 미달"

    result["cooccurrence_verdict"] = result.apply(verdict, axis=1)
    return result


# ---------------------------------------------------------------------------
# 검증 5 — OPCOND vs GROUP 층 선택 민감도
# ---------------------------------------------------------------------------

def stratum_sensitivity(df_opcond_z: pd.DataFrame, df_group_z: pd.DataFrame) -> pd.DataFrame:
    """같은 검정을 OPCOND 층과 GROUP 층에서 각각 돌려 결론이 뒤집히는지 본다.

    OPCOND = [Product_ID, Recipe_ID]            → 장비 간 차이가 신호에 '포함'된다
    GROUP  = [Machine_ID, Product_ID, Recipe_ID] → 장비 간 차이를 '제거'하고 본다

    두 결과가 갈리면 그 인자의 효과는 설비 간 차이에서 나온 것이다. 실무적으로는
    "공정 파라미터를 조정하라"가 아니라 "특정 설비를 정비하라"가 조치가 되므로,
    Goal 6(SOP)에서 조치 주체가 달라진다. 반대로 둘 다 유지되면 설비를 통제해도
    남는 공정 인자라는 뜻이다.
    """
    rows = []
    for col in ALL_FEATURE_COLS:
        z_col = f"{col}_z"
        if z_col not in df_opcond_z.columns or z_col not in df_group_z.columns:
            continue
        for label in LABELS:
            d_op, p_op, n_g, _ = cliffs_delta(
                df_opcond_z.loc[df_opcond_z[label], z_col], df_opcond_z.loc[~df_opcond_z[label], z_col]
            )
            d_gr, p_gr, _, _ = cliffs_delta(
                df_group_z.loc[df_group_z[label], z_col], df_group_z.loc[~df_group_z[label], z_col]
            )
            rows.append({
                "column": col,
                "label": label,
                "n_group": n_g,
                "cliffs_delta_opcond": d_op,
                "p_opcond": p_op,
                "cliffs_delta_group": d_gr,
                "p_group": p_gr,
                "delta_shrinkage": (
                    1 - abs(d_gr) / abs(d_op) if pd.notna(d_op) and abs(d_op) > 1e-9 and pd.notna(d_gr) else np.nan
                ),
            })

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    for stratum in ("opcond", "group"):
        rejected, p_adj, _, _ = multipletests(
            result[f"p_{stratum}"].fillna(1.0), alpha=FDR_ALPHA, method="fdr_bh"
        )
        result[f"p_fdr_{stratum}"] = p_adj
        result[f"flag_{stratum}"] = rejected & (result[f"cliffs_delta_{stratum}"].abs() >= EFFECT_SIZE_MIN)

    def verdict(row):
        if row["flag_opcond"] and row["flag_group"]:
            return "층 무관하게 유효 — 공정 인자로 조치 가능"
        if row["flag_opcond"] and not row["flag_group"]:
            return "장비 통제 시 소멸 — 설비 간 차이가 원천(설비 정비 이슈)"
        if not row["flag_opcond"] and row["flag_group"]:
            return "장비 통제 시에만 발현 — 층 혼재로 가려져 있던 신호"
        return "양쪽 모두 미달"

    result["stratum_verdict"] = result.apply(verdict, axis=1)
    return result.sort_values("cliffs_delta_opcond", key=abs, ascending=False)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Goal 2 PARTICLE 유효인자 후속 검증")
    parser.add_argument("--data", help="원본 CSV 경로 (기본값: pipeline.config.INPUT_CSV)")
    args = parser.parse_args()

    if args.data:
        config.INPUT_CSV = Path(args.data)
    if not Path(config.INPUT_CSV).exists():
        raise SystemExit(
            f"원본 데이터를 찾을 수 없습니다: {config.INPUT_CSV}\n--data 로 CSV 경로를 지정하세요."
        )

    print(f"[0/6] 데이터 로드: {config.INPUT_CSV}")
    df = add_labels(load_dataset())
    print(f"      {len(df):,}행 · NG_Code=PARTICLE {int(df[PRIMARY_LABEL].sum()):,}건 "
          f"· Particle==1 {int(df[BROAD_LABEL].sum()):,}건")

    print(f"[1/6] OPCOND 층화 z ({'×'.join(config.OPCOND)})")
    df_op = stratified_z(df, config.OPCOND, ALL_FEATURE_COLS)

    print(f"[2/6] GROUP 층화 z ({'×'.join(config.GROUP)})")
    df_gr = stratified_z(df, config.GROUP, ALL_FEATURE_COLS)

    print("[3/6] 검증1: Surface_Roughness 시간 선행성")
    temporal = temporal_precedence(df_op)
    temporal.to_csv(OUT_DIR / "01_surface_roughness_temporal.csv", encoding="utf-8-sig", index=False)

    print("[4/6] 검증2: Die 수 용량-반응 / 검증3: 세정 비율 정의")
    dose = dose_response(df_op)
    dose.to_csv(OUT_DIR / "02_dose_response_particle_die.csv", encoding="utf-8-sig", index=False)
    ratios = cleaning_ratio_variants(df, df_op)
    ratios.to_csv(OUT_DIR / "03_cleaning_load_ratio_variants.csv", encoding="utf-8-sig", index=False)

    print("[5/6] 검증4: PARTICLE ∩ REM_COAT 동시발생")
    cooc = cooccurrence_profile(df_op)
    cooc.to_csv(OUT_DIR / "04_particle_remcoat_cooccurrence.csv", encoding="utf-8-sig", index=False)

    print("[6/6] 검증5: OPCOND vs GROUP 층 민감도")
    sensitivity = stratum_sensitivity(df_op, df_gr)
    sensitivity.to_csv(OUT_DIR / "05_stratum_sensitivity.csv", encoding="utf-8-sig", index=False)

    primary_temporal = temporal.loc[temporal["label"] == PRIMARY_LABEL]
    flipped = sensitivity.loc[
        (sensitivity["label"] == PRIMARY_LABEL)
        & (sensitivity["stratum_verdict"] != "양쪽 모두 미달")
        & (sensitivity["flag_opcond"] != sensitivity["flag_group"])
    ]
    best_ratio = ratios.loc[ratios["label"] == PRIMARY_LABEL].nlargest(1, "abs_cliffs_delta")

    summary = {
        "analysis": "PARTICLE 유효인자 후속 검증",
        "builds_on": "26.07.30_2055_Goal2_PARTICLE_유효인자_분석 (Jun 브랜치)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(df)),
        "n_primary_label": int(df[PRIMARY_LABEL].sum()),
        "n_broad_label": int(df[BROAD_LABEL].sum()),
        "criteria": {"effect_size_min_cliffs_delta": EFFECT_SIZE_MIN, "fdr_alpha": FDR_ALPHA},
        "검증1_시간선행성": {
            row["column"] + f"_lag{row['lag_window_strips']}": row["interpretation"]
            for _, row in primary_temporal.iterrows()
        },
        "검증2_용량반응_오염검사": dose.loc[dose["sample"] == "particle_only_excl_remcoat"][
            ["column", "spearman_rho_vs_die_count", "bucket_median_monotonicity", "contamination_check"]
        ].to_dict(orient="records"),
        "검증3_최적_비율정의": (
            best_ratio[["variant", "cliffs_delta", "passes_jun_criteria"]].to_dict(orient="records")[0]
            if not best_ratio.empty else None
        ),
        "검증4_동시발생_판정": dict(zip(cooc["column"], cooc["cooccurrence_verdict"])),
        "검증5_층민감도_결론바뀐인자": flipped[
            ["column", "cliffs_delta_opcond", "cliffs_delta_group", "stratum_verdict"]
        ].to_dict(orient="records"),
        "notes": [
            "인과관계 확정이 아니라 후속 검증 후보의 우선순위를 좁히는 과정이다.",
            "검증1은 인과 증명이 아니라 '결과 공변 해석을 반증할 수 있는가'를 보는 검사다.",
            "통계 기준(Cliff's delta 0.2, BH-FDR)은 Jun의 1차 분석과 동일하게 유지했다.",
        ],
    }
    with open(OUT_DIR / "00_followup_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n완료: {OUT_DIR}\n")
    print("=== 검증1: Surface_Roughness 시간 선행성 (NG_Code=PARTICLE) ===")
    print(primary_temporal[
        ["column", "lag_window_strips", "cliffs_delta_concurrent",
         "cliffs_delta_lagged", "signal_retention_ratio", "interpretation"]
    ].to_string(index=False))
    print("\n=== 검증2: Die 수 용량-반응 + REM_COAT 오염 검사 ===")
    print(dose.loc[dose["sample"] == "particle_only_excl_remcoat"][
        ["column", "n_particle_rows", "spearman_rho_vs_die_count",
         "bucket_median_monotonicity", "contamination_check"]
    ].to_string(index=False))

    print("\n=== 검증3: 세정 밸런스 비율 정의 비교 (NG_Code=PARTICLE) ===")
    print(ratios.loc[ratios["label"] == PRIMARY_LABEL][
        ["variant", "cliffs_delta", "p_fdr", "passes_jun_criteria"]
    ].to_string(index=False))

    print("\n=== 검증4: PARTICLE ∩ REM_COAT 동시발생 (세정계 인자) ===")
    print(cooc[[
        "column", "cliffs_delta_particle_only_vs_normal",
        "cliffs_delta_remain_coat_only_vs_normal", "cliffs_delta_both_vs_normal",
        "cooccurrence_verdict",
    ]].to_string(index=False))
    print("\n=== 검증5: 층 선택으로 결론이 바뀌는 인자 ===")
    print(flipped[["column", "cliffs_delta_opcond", "cliffs_delta_group", "stratum_verdict"]].to_string(index=False)
          if not flipped.empty else "  (없음 — 층 선택에 결론이 강건함)")


if __name__ == "__main__":
    main()
