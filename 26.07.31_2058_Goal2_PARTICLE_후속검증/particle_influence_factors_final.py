"""Goal 2 — PARTICLE 영향인자 최종 도출.

"Particle 불량의 영향인자는 무엇인가"에 대한 단일 답표를 만든다.
인자 40개 전체를 세 가지 방법에 동시에 태우고, 그 결과를 하나의 판정으로 합친다.

  방법 A  단변량 검정   Mann-Whitney U + BH-FDR + Cliff's delta
  방법 B  다변량 중요도  RandomForest permutation importance
  방법 C  시간 선행성    직전 스트립 이력으로도 판별되는가 (원인 vs 결과 구분)

방법 C가 이 표의 핵심이다. A와 B는 "불량 난 장에서 값이 다른가"만 보므로,
불량의 *결과*로 값이 변한 인자도 상위로 올라온다(Surface_Roughness가 실제로 그랬다).
원인 후보와 동반증상을 갈라놓지 않으면 Goal 6(SOP)에서 조치할 수 없는 항목이 섞인다.

## 라벨과 대조군

검정군은 `NG_Code == 'PARTICLE'` 6,455건. 데이터 확인 결과 이 조건은
`Particle==1 AND Remain_Coat==0`과 **완전히 일치**한다(불일치 0건). 즉 이 라벨에는
REM_COAT 동시발생이 애초에 섞여 있지 않다. 반면 보조 라벨 `Particle==1`(7,792건)에는
REM_COAT 동시발생 1,337건이 포함돼 세정계 인자에 가짜 신호를 만든다
(같은 폴더 `04_particle_remcoat_cooccurrence.csv` 참고). 두 라벨 결과를 나란히 실어
어떤 인자가 그 오염 때문에 떠올랐는지 표에서 바로 보이게 했다.

대조군은 `NG_Code == 'OK'` 90,783건으로 한정한다. Jun의 1차 분석은 "검정군 외 나머지
전부"를 대조군으로 썼는데, 거기에는 다른 불량 3,110건(REM_COAT/BURN/CRACK/CHIP)이
섞여 있다. 정상만으로 좁히면 대비가 더 깨끗해진다.

## 선행 작업

1차 스크리닝은 Jun 브랜치 `26.07.30_2055_Goal2_PARTICLE_유효인자_분석/`에서 이미 수행됐다.
도메인 가설표는 그 분석의 것을 그대로 쓴다(재작성하지 않음 — 팀 도메인 판단이므로).
통계 임계값(Cliff's delta 0.2, BH-FDR alpha)도 동일하게 유지해 숫자를 비교할 수 있게 했다.

실행 (저장소 루트에서):
    python "26.07.31_2058_Goal2_PARTICLE_후속검증/particle_influence_factors_final.py" --data "원본CSV경로"

산출물:
    06_particle_influence_factors_FINAL.csv   인자 40개 최종 판정표 (메인 산출물)
    06_particle_influence_factors_FINAL.json  요약
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from statsmodels.stats.multitest import multipletests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

# 팀 규약 — Jun의 1차 분석과 동일하게 유지 (바꾸면 숫자 비교가 깨진다)
EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = config.TREND_ALPHA
TREE_TOP_N = 10

# 시간 선행성: 직전 몇 장의 이력을 볼 것인가. 현재 장은 항상 제외한다.
LAG_WINDOW = 50
# 선행 효과크기가 동시점의 이 비율 미만이면 "동시점에만 나타남"으로 본다.
RETENTION_FLOOR = 0.15

FEATURE_COLS = config.FDC_COLS + config.RESPONSES + config.DOMAIN_FEATURES + ["Maintenance_Count"]

# 조작 가능 여부 — Goal 6(SOP)에서 조치 항목이 될 수 있는지 가른다.
# response는 통계적으로 유효해도 '돌릴 수 있는 손잡이'가 아니라 '같이 움직이는 계기판'이다.
def action_type(column: str) -> str:
    if column in config.FDC_COLS:
        return "조작가능(FDC)"
    if column in config.RESPONSES:
        return "관측지표(response)"
    if column in config.DOMAIN_FEATURES:
        return "파생지표(조작불가)"
    return "이력지표"


# ---------------------------------------------------------------------------
# 도메인 가설 — Jun의 1차 분석(26.07.30_2055)에서 그대로 가져왔다.
# 팀의 도메인 판단이므로 임의로 고치지 않는다. 수정이 필요하면 Jun과 합의 후 양쪽을 함께 고친다.
# ---------------------------------------------------------------------------

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
    "Maintenance_Count": ("정비 이력 프록시 — 세정계 부품 교체/재교정과 연관 가능, 방향은 특정하지 않음", "either"),
}

NOT_RELATED = {
    "Laser_Centering_Position": "정렬/센터링 계열 — Chipping 메커니즘, 디브리와 무관",
    "Cutting_X_Index": "정렬/센터링 계열 — Chipping 메커니즘, 디브리와 무관",
    "Cutting_Y_Index": "정렬/센터링 계열 — Chipping 메커니즘, 디브리와 무관",
    "Cutting_Offset": "정렬/센터링 계열 — Chipping 메커니즘, 디브리와 무관",
    "Kerf_Angle": "정렬/센터링 계열 — 절단면 수직도, 디브리와 무관",
    "Package_Size_1": "정렬/센터링 계열 — 다이 크기 불균형은 센터링 지표",
    "Package_Size_2": "정렬/센터링 계열 — 다이 크기 불균형은 센터링 지표",
    "Package_Size_3": "정렬/센터링 계열 — 다이 크기 불균형은 센터링 지표",
    "Package_Size_4": "정렬/센터링 계열 — 다이 크기 불균형은 센터링 지표",
    "Head_Temp": "방열 계열 — Burn 전용 메커니즘(열 축적)",
    "Cooling_Flow": "방열 계열 — Burn 전용 메커니즘(열 축적)",
    "Cooling_Water_Temp": "방열 계열 — Burn 전용 메커니즘(열 축적)",
    "Cooling_Thermal_Load": "팀 공용 피처, 방열 계열 — Burn 전용 메커니즘",
    "Frequency": "체류시간/열축적 계열 — Burn 전용 메커니즘(펄스 중첩→열)",
    "Alignment_Time": "체류시간/열축적 계열 — Burn 전용 메커니즘",
    "Process_Time": "체류시간/열축적 계열 — Burn 전용 메커니즘",
    "Feed_Speed": "체류시간 계열로 확립된 것은 Burn 메커니즘 — 디브리와의 관계는 근거 약함",
}

TEAM_UNDETERMINED = {
    "Laser_Current": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족",
    "Laser_Voltage": "HealthIndex 설계서 F유형(불확실형) — 전기적 제어수치, 실패모드 근거 부족",
    "Coating_Thickness": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실",
    "Coating_Uniformity": "HealthIndex 설계서 G유형(미해결형) — 측정 시점(가공전/후) 불확실",
}


def domain_info(column: str) -> tuple[str, str, bool, str]:
    if column in DOMAIN_HYPOTHESIS:
        mechanism, direction = DOMAIN_HYPOTHESIS[column]
        return mechanism, direction, True, "defect_related"
    if column in NOT_RELATED:
        return NOT_RELATED[column], "not_applicable", False, "not_related_to_defect"
    if column in TEAM_UNDETERMINED:
        return TEAM_UNDETERMINED[column], "unknown", False, "team_undetermined"
    return "미분류 — 검토 필요", "unknown", False, "unclassified"


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def cliffs_delta(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Cliff's delta와 Mann-Whitney p값.

    delta = 2*U/(n1*n2) - 1. a에서 무작위로 뽑은 값이 b에서 뽑은 값보다 클 확률을
    -1~+1로 옮긴 것이다. 0이면 두 분포가 겹쳐 구별되지 않는다.
    """
    a = pd.Series(a).dropna()
    b = pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u_stat, p_value = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return float((2 * u_stat) / (len(a) * len(b)) - 1), float(p_value)


# ---------------------------------------------------------------------------
# 방법 A — 단변량 검정
# ---------------------------------------------------------------------------

def univariate(df_z: pd.DataFrame, defect_mask: pd.Series, normal_mask: pd.Series) -> pd.DataFrame:
    """불량군과 정상군의 층화 z 분포를 인자별로 비교한다."""
    rows = []
    for col in FEATURE_COLS:
        z_col = f"{col}_z"
        delta, p_value = cliffs_delta(df_z.loc[defect_mask, z_col], df_z.loc[normal_mask, z_col])
        rows.append({
            "column": col,
            "median_z_defect": float(df_z.loc[defect_mask, z_col].median()),
            "median_z_normal": float(df_z.loc[normal_mask, z_col].median()),
            "cliffs_delta": delta,
            "p_value": p_value,
        })
    result = pd.DataFrame(rows)
    rejected, p_adj, _, _ = multipletests(result["p_value"].fillna(1.0), alpha=FDR_ALPHA, method="fdr_bh")
    result["p_fdr"] = p_adj
    result["univariate_flag"] = rejected & (result["cliffs_delta"].abs() >= EFFECT_SIZE_MIN)
    return result


# ---------------------------------------------------------------------------
# 방법 B — RandomForest permutation importance
# ---------------------------------------------------------------------------

def tree_importance(
    df_z: pd.DataFrame,
    defect_mask: pd.Series,
    normal_mask: pd.Series,
    exclude: list[str] | None = None,
    suffix: str = "",
) -> pd.DataFrame:
    """40개 인자를 동시에 넣고, 각 인자를 뒤섞었을 때 예측력이 얼마나 떨어지는지 측정.

    단변량 검정과 달리 인자 간 상관을 어느 정도 감안하고, 비선형 관계도 잡는다.
    두 방법이 서로 다른 방식으로 틀리기 때문에 함께 본다.

    `exclude`를 쓰는 이유: permutation importance는 압도적으로 강한 인자가 하나 있으면
    모델이 그것만으로 예측을 끝내버려서, 나머지 인자를 뒤섞어도 성능이 안 떨어진다.
    그러면 실제로 유효한 2순위 인자들의 중요도가 전부 0 근처로 눌리고 순위가 잡음이 된다.
    Surface_Roughness(효과크기 0.717)가 정확히 그 경우라, 방법 C에서 '불량의 결과'로
    판정된 인자를 뺀 모델을 따로 돌려 나머지 인자들을 제대로 비교한다.
    """
    z_cols = [f"{c}_z" for c in FEATURE_COLS if not exclude or c not in exclude]
    frame = df_z.loc[defect_mask | normal_mask, z_cols].copy()
    target = defect_mask.loc[frame.index].astype(int)

    usable = frame.columns[frame.isna().mean() <= 0.05].tolist()
    frame = frame[usable].dropna()
    target = target.loc[frame.index]

    x_train, x_test, y_train, y_test = train_test_split(
        frame, target, test_size=0.2, random_state=42, stratify=target
    )
    model = RandomForestClassifier(
        n_estimators=200, max_depth=8, class_weight="balanced", random_state=42, n_jobs=-1
    )
    model.fit(x_train, y_train)
    perm = permutation_importance(
        model, x_test, y_test, scoring="average_precision", n_repeats=15, random_state=42, n_jobs=-1
    )

    result = pd.DataFrame({
        "column": [c[:-2] for c in usable],
        f"tree_importance{suffix}": perm.importances_mean,
        f"tree_importance_std{suffix}": perm.importances_std,
    })
    result[f"tree_rank{suffix}"] = (
        result[f"tree_importance{suffix}"].rank(ascending=False, method="min").astype(int)
    )
    result[f"tree_flag{suffix}"] = (
        (result[f"tree_rank{suffix}"] <= TREE_TOP_N) & (result[f"tree_importance{suffix}"] > 0)
    )
    return result


# ---------------------------------------------------------------------------
# 방법 C — 시간 선행성 (원인 vs 결과 구분)
# ---------------------------------------------------------------------------

def temporal(df_z: pd.DataFrame, defect_mask: pd.Series, normal_mask: pd.Series) -> pd.DataFrame:
    """직전 스트립들의 이력만으로도 불량을 판별할 수 있는지 본다.

    인자가 원인이라면 불량이 나기 전에 이미 이상해져 있어야 한다. 반대로 불량의
    결과로 값이 변한 인자라면, 같은 스트립에서 잴 때만 갈리고 직전 이력에는 신호가 없다.

    현재 스트립을 반드시 제외하기 위해 shift(1) 후 rolling 평균을 쓴다.
    설비별로 따로 계산하는 이유는 스트립 순서가 설비 안에서만 의미를 갖기 때문이다.
    """
    ordered = df_z.sort_values(["Machine_ID", "DateTime"])
    d_mask = defect_mask.loc[ordered.index]
    n_mask = normal_mask.loc[ordered.index]

    rows = []
    for col in FEATURE_COLS:
        z_col = f"{col}_z"
        lagged = ordered.groupby("Machine_ID")[z_col].transform(
            lambda s: s.shift(1).rolling(LAG_WINDOW, min_periods=LAG_WINDOW // 2).mean()
        )
        delta_lag, p_lag = cliffs_delta(lagged[d_mask], lagged[n_mask])
        rows.append({"column": col, "lagged_cliffs_delta": delta_lag, "lagged_p_value": p_lag})

    result = pd.DataFrame(rows)
    rejected, p_adj, _, _ = multipletests(result["lagged_p_value"].fillna(1.0), alpha=FDR_ALPHA, method="fdr_bh")
    result["lagged_p_fdr"] = p_adj
    result["lagged_significant"] = rejected
    return result


# ---------------------------------------------------------------------------
# 최종 판정
# ---------------------------------------------------------------------------

def build_final(
    strict: pd.DataFrame,
    broad: pd.DataFrame,
    tree_all: pd.DataFrame,
    tree_excl: pd.DataFrame,
    temp: pd.DataFrame,
    excluded_from_tree: list[str],
) -> pd.DataFrame:
    merged = (
        strict.rename(columns={
            "cliffs_delta": "cliffs_delta_strict", "p_fdr": "p_fdr_strict",
            "univariate_flag": "univariate_flag_strict",
        })[["column", "median_z_defect", "median_z_normal",
            "cliffs_delta_strict", "p_fdr_strict", "univariate_flag_strict"]]
        .merge(
            broad.rename(columns={"cliffs_delta": "cliffs_delta_broad"})[["column", "cliffs_delta_broad"]],
            on="column", how="left")
        .merge(tree_all[["column", "tree_importance_all", "tree_rank_all", "tree_flag_all"]],
               on="column", how="left")
        .merge(tree_excl[["column", "tree_importance_excl", "tree_rank_excl", "tree_flag_excl"]],
               on="column", how="left")
        .merge(temp[["column", "lagged_cliffs_delta", "lagged_p_fdr", "lagged_significant"]],
               on="column", how="left")
    )

    for col in ("tree_flag_all", "tree_flag_excl", "lagged_significant"):
        merged[col] = merged[col].fillna(False).astype(bool)

    # 결과 공변으로 판정돼 모델에서 뺀 인자는 전체 모델 결과를, 나머지는 그 인자를 뺀
    # 모델 결과를 채택한다. 후자가 2순위 이하 인자들을 제대로 비교한 값이기 때문이다.
    is_excluded = merged["column"].isin(excluded_from_tree)
    merged["tree_flag"] = np.where(is_excluded, merged["tree_flag_all"], merged["tree_flag_excl"])
    merged["tree_rank"] = np.where(is_excluded, merged["tree_rank_all"], merged["tree_rank_excl"])
    merged["tree_importance"] = np.where(
        is_excluded, merged["tree_importance_all"], merged["tree_importance_excl"]
    )
    merged["tree_flag"] = merged["tree_flag"].astype(bool)

    info = merged["column"].map(domain_info)
    merged["domain_mechanism"] = info.map(lambda t: t[0])
    merged["domain_direction"] = info.map(lambda t: t[1])
    merged["has_domain_support"] = info.map(lambda t: t[2])
    merged["domain_status"] = info.map(lambda t: t[3])
    merged["subsystem"] = merged["column"].map(
        lambda c: next((s for s, cols in config.SUBSYSTEMS.items() if c in cols), "engineered")
    )
    merged["action_type"] = merged["column"].map(action_type)

    # 선행 신호가 동시점 신호의 몇 %나 남는가 — 원인/결과 구분의 핵심 지표.
    # 동시점 신호 자체가 잡음 수준이면 비율은 의미가 없다(0을 0으로 나누는 꼴이라
    # 수백 %가 찍힌다). 그래서 동시점 효과크기가 이 값 미만이면 계산하지 않는다.
    retention_denominator_floor = 0.05
    merged["signal_retention"] = np.where(
        merged["cliffs_delta_strict"].abs() >= retention_denominator_floor,
        merged["lagged_cliffs_delta"].abs() / merged["cliffs_delta_strict"].abs(),
        np.nan,
    )

    # 보조 라벨에서만 커지는 인자 = REM_COAT 동시발생이 만든 신호
    merged["remcoat_inflated"] = (
        (merged["cliffs_delta_broad"].abs() >= EFFECT_SIZE_MIN)
        & (merged["cliffs_delta_strict"].abs() < EFFECT_SIZE_MIN)
    )

    merged["n_methods_agree"] = (
        merged["univariate_flag_strict"].astype(int) + merged["tree_flag"].astype(int)
    )

    def verdict(row):
        if row["remcoat_inflated"]:
            return "기각 — REM_COAT 동시발생이 만든 신호"
        if row["n_methods_agree"] >= 2 and row["has_domain_support"]:
            if row["lagged_significant"] and pd.notna(row["signal_retention"]) \
                    and row["signal_retention"] >= RETENTION_FLOOR:
                return "영향인자 — 원인 후보 (선행 신호 있음)"
            return "영향인자 — 동시 관측만 (원인 아님, 탐지지표로 활용)"
        if row["n_methods_agree"] >= 2:
            return "통계적 신호 있으나 도메인 근거 없음 — 검토 필요"
        if row["n_methods_agree"] == 1 and row["has_domain_support"]:
            return "약한 신호 — 후보 보류"
        return "근거 부족"

    merged["FINAL_VERDICT"] = merged.apply(verdict, axis=1)

    order = [
        "column", "FINAL_VERDICT", "action_type", "subsystem", "domain_status",
        "cliffs_delta_strict", "p_fdr_strict", "univariate_flag_strict",
        "tree_importance", "tree_rank", "tree_flag",
        "lagged_cliffs_delta", "signal_retention", "lagged_significant",
        "cliffs_delta_broad", "remcoat_inflated",
        "n_methods_agree", "median_z_defect", "median_z_normal",
        "tree_rank_all", "tree_rank_excl",
        "domain_direction", "domain_mechanism",
    ]
    return merged[order].sort_values(
        ["n_methods_agree", "cliffs_delta_strict"], ascending=[False, False],
        key=lambda s: s.abs() if s.name == "cliffs_delta_strict" else s,
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PARTICLE 영향인자 최종 도출")
    parser.add_argument("--data", help="원본 CSV 경로")
    args = parser.parse_args()

    if args.data:
        config.INPUT_CSV = Path(args.data)
    if not Path(config.INPUT_CSV).exists():
        raise SystemExit(f"원본 데이터를 찾을 수 없습니다: {config.INPUT_CSV}")

    print(f"[1/5] 데이터 로드: {config.INPUT_CSV}")
    df = load_dataset()

    defect = df["NG_Code"] == "PARTICLE"
    broad_defect = df["Particle"] == 1
    normal = df["NG_Code"] == "OK"

    # 문서화된 전제 확인 — 깨지면 이 분석의 라벨 해석이 달라진다.
    assert (defect == (broad_defect & (df["Remain_Coat"] == 0))).all(), \
        "NG_Code=='PARTICLE'이 Particle==1 & Remain_Coat==0과 불일치 — 라벨 정의 재확인 필요"

    print(f"      검정군 {int(defect.sum()):,}건 · 대조군(정상) {int(normal.sum()):,}건 "
          f"· 보조라벨 {int(broad_defect.sum()):,}건")

    print(f"[2/5] OPCOND 층화 z ({'×'.join(config.OPCOND)}, 정상군 기준)")
    baseline = compute_stratum_baseline_stats(df.loc[df["is_normal"]], config.OPCOND, FEATURE_COLS)
    df_z = zscore_transform(df, baseline, config.OPCOND, FEATURE_COLS)

    print("[3/6] 방법 A: 단변량 검정 (주 라벨 + 보조 라벨)")
    strict_uni = univariate(df_z, defect, normal)
    broad_uni = univariate(df_z, broad_defect, normal)

    print(f"[4/6] 방법 C: 시간 선행성 (직전 {LAG_WINDOW}장 이력)")
    temp = temporal(df_z, defect, normal)

    # 강한 동시점 신호를 갖지만 선행 신호가 없는 인자 = 불량의 결과. 이런 인자가 모델에
    # 남아 있으면 나머지 인자의 permutation importance를 전부 눌러버리므로 따로 식별한다.
    diagnostics = strict_uni.merge(temp, on="column")
    concurrent_only = diagnostics.loc[
        diagnostics["univariate_flag"]
        & (diagnostics["lagged_cliffs_delta"].abs() / diagnostics["cliffs_delta"].abs() < RETENTION_FLOOR),
        "column",
    ].tolist()
    print(f"      결과 공변으로 판정 → 트리 모델에서 제외: {concurrent_only or '없음'}")

    print("[5/6] 방법 B: RandomForest permutation importance (전체 모델)")
    tree_all = tree_importance(df_z, defect, normal, suffix="_all")

    print("[6/6] 방법 B': 결과 공변 인자 제외 모델 — 2순위 이하 인자 비교용")
    tree_excl = tree_importance(df_z, defect, normal, exclude=concurrent_only, suffix="_excl")

    final = build_final(strict_uni, broad_uni, tree_all, tree_excl, temp, concurrent_only)
    final.to_csv(OUT_DIR / "06_particle_influence_factors_FINAL.csv", encoding="utf-8-sig", index=False)

    counts = final["FINAL_VERDICT"].value_counts().to_dict()
    summary = {
        "analysis": "PARTICLE 영향인자 최종 도출",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_definition": "NG_Code=='PARTICLE' (== Particle==1 AND Remain_Coat==0, 검증됨)",
        "n_defect": int(defect.sum()),
        "n_normal_control": int(normal.sum()),
        "n_features": len(FEATURE_COLS),
        "stratum": config.OPCOND,
        "criteria": {
            "cliffs_delta_min": EFFECT_SIZE_MIN,
            "fdr_alpha": FDR_ALPHA,
            "tree_top_n": TREE_TOP_N,
            "lag_window_strips": LAG_WINDOW,
            "signal_retention_floor": RETENTION_FLOOR,
        },
        "excluded_from_tree_as_consequence": concurrent_only,
        "verdict_counts": counts,
        "influence_factors": final.loc[
            final["FINAL_VERDICT"].str.startswith("영향인자"),
            ["column", "FINAL_VERDICT", "action_type", "cliffs_delta_strict", "signal_retention"],
        ].to_dict(orient="records"),
        "notes": [
            "인과관계 확정이 아니라 후속 검증 후보의 우선순위다.",
            "시간 선행성은 인과 증명이 아니라 '결과 공변 해석을 반증할 수 있는가'를 보는 검사다.",
            "1차 스크리닝은 Jun 브랜치 26.07.30_2055에서 수행됨. 도메인 가설표는 그것을 그대로 사용.",
        ],
    }
    with open(OUT_DIR / "06_particle_influence_factors_FINAL.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {OUT_DIR}\n")
    print("=== PARTICLE 영향인자 최종 판정 ===")
    print(final[[
        "column", "action_type", "cliffs_delta_strict", "tree_rank",
        "lagged_cliffs_delta", "signal_retention", "FINAL_VERDICT",
    ]].head(15).to_string(index=False))
    print("\n=== 판정별 건수 ===")
    for k, v in counts.items():
        print(f"  {v:>2}건  {k}")


if __name__ == "__main__":
    main()
