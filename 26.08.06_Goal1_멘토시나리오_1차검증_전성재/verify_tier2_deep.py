"""2차 심화 — 멘토 시나리오 x 진혁님 티어표가 어긋나는 지점을 데이터로 판정 (26.08.06, 전성재).

1차(verify_mentor_scenarios.py)에서 멘토님 시나리오 6개가 r1에서 6/6 확인됐다.
그런데 진혁님 통합 Relationship DB(rel_20 티어표)와 대조하면 **두 군데가 어긋난다**:

  충돌 A — Micro_Crack
    멘토: DP03 Cooling Failure -> Micro_Crack 증가
    진혁: Micro_Crack의 Cooling_Flow는 T3(감시)로 강등. 스트립 단위 delta -0.023,
          데이터셋 간 방향 불일치로 재현 실패. Cooling_Water_Temp는 T4(판단보류).
          -> Micro_Crack 확정 원인 0건
    내 1차: DP03에서 Micro_Crack 실제로 많음(r1 RR 1.16, FDR 3.6e-18)
    => 장비 수준에서는 보이는데 스트립 수준에서는 안 보인다. 어느 쪽이 맞는가?

  충돌 B — Head_Temp 귀속
    멘토: DP03(Cooling Failure) 쪽에 Head_Temp를 넣으심
    진혁: rel_15에서 Head_Temp를 "귀속 미확정 — 냉각/레이저 어느 쪽인지 미확정"으로
          명시적으로 남김 (Chipping과는 delta +0.873으로 매우 강함)
    => Head_Temp는 DP02(레이저 열화)의 신호인가, DP03(냉각 실패)의 신호인가?

장비별 비교는 이 두 질문에 답할 수 있는 각도다 — 스트립 단위 검정은 "어느 장비냐"를
보지 않기 때문에 진혁님 분석에서는 원리적으로 답이 안 나온다.

검증 항목:
  2-1  Micro_Crack: DP03 초과분이 냉각 인자로 설명되는가 (매개분석)
  2-2  Micro_Crack: 냉각이 아니라면 무엇이 DP03의 Micro_Crack을 가르는가 (후보 스캔)
  2-3  Head_Temp 귀속: 레이저 계열과 붙는가 냉각 계열과 붙는가
  2-4  조치 우선순위: 같은 불량에 걸린 인자들이 서로 독립인가 (층별 검증)

주의 — 진혁님 폴더(26.08.05_Goal2_통합_Relationship_DB_JHdaimma)는 현재 브랜치에
체크아웃돼 있지 않다(커밋 f48a8f6은 다른 브랜치). 아래 JH_TIER는 그 커밋의
rel_20_tier_table.csv / rel_15에서 읽어 옮긴 값이며, 브랜치 병합 후에는 파일을 직접
읽도록 바꾸는 것이 맞다.

SHAP/Boosting 미사용 (26.08.05 멘토 지시).

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. python "26.08.06_Goal1_멘토시나리오_1차검증_전성재/verify_tier2_deep.py"
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.linear_model import LogisticRegression
from statsmodels.stats.multitest import multipletests

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
MACHINES = ["DP01", "DP02", "DP03", "DP04"]
FDR_ALPHA = 0.05
EFFECT_SIZE_MIN = 0.2

DATASETS = {
    "원본": "data/raw/DP_HealthIndex_Dataset.csv",
    "r1": "data/raw/DP_HealthIndex_Dataset_r1.csv",
}

# ---------------------------------------------------------------------------
# 진혁님 rel_20_tier_table.csv (커밋 f48a8f6) 판정 — 대조용
# tier: T1 즉시조치 / T2 조건부조치 / T3 감시 / T4 판단보류 / M1 감시지표
# ---------------------------------------------------------------------------
JH_TIER = [
    {"defect": "Chipping", "factor": "Power_Efficiency", "tier": "T1", "role": "원인(FDC)",
     "stat_pass": True, "delta": -0.8789, "repro": "판정불가(원본 표본부족)"},
    {"defect": "Chipping", "factor": "Laser_Power", "tier": "T1", "role": "원인(FDC)",
     "stat_pass": True, "delta": -0.8523, "repro": "판정불가(원본 표본부족)"},
    {"defect": "Chipping", "factor": "Head_Temp", "tier": "T1", "role": "원인(FDC)",
     "stat_pass": True, "delta": 0.8727, "repro": "판정불가(원본 표본부족)"},
    {"defect": "Chipping", "factor": "Cooling_Flow", "tier": "T2", "role": "원인(FDC)",
     "stat_pass": True, "delta": -0.4780, "repro": "판정불가(원본 표본부족)"},
    {"defect": "Chipping", "factor": "Vibration", "tier": "T2", "role": "원인(FDC)",
     "stat_pass": True, "delta": 0.8161, "repro": "판정불가(원본 표본부족)"},
    {"defect": "Remain_Coat", "factor": "CLN_Pressure", "tier": "T1", "role": "원인(FDC)",
     "stat_pass": True, "delta": -0.2466, "repro": "통과"},
    {"defect": "Remain_Coat", "factor": "CLN_Flow", "tier": "T1", "role": "원인(FDC)",
     "stat_pass": True, "delta": -0.5556, "repro": "통과"},
    {"defect": "Particle", "factor": "CLN_Flow", "tier": "T2", "role": "원인(FDC)",
     "stat_pass": False, "delta": -0.0052, "repro": "통과"},
    {"defect": "Particle", "factor": "CLN_Pressure", "tier": "T3", "role": "원인(FDC)",
     "stat_pass": False, "delta": 0.0117, "repro": "통과"},
    {"defect": "Particle", "factor": "Surface_Roughness", "tier": "M1", "role": "감시지표(Response)",
     "stat_pass": True, "delta": 0.6063, "repro": "통과"},
    # --- Micro_Crack: 진혁님이 전부 강등. 확정 원인 0건 ---
    {"defect": "Micro_Crack", "factor": "Cooling_Flow", "tier": "T3", "role": "원인(FDC)",
     "stat_pass": False, "delta": -0.0232, "repro": "실패(데이터셋간 방향 불일치)"},
    {"defect": "Micro_Crack", "factor": "Vibration", "tier": "T3", "role": "원인(FDC)",
     "stat_pass": False, "delta": 0.0633, "repro": "실패(데이터셋간 방향 불일치)"},
    {"defect": "Micro_Crack", "factor": "Cooling_Water_Temp", "tier": "T4", "role": "원인(FDC)",
     "stat_pass": False, "delta": -0.0125, "repro": "실패(데이터셋간 방향 불일치)"},
]

# 2-2 후보 스캔 대상 — 진혁님 냉각 인자가 Micro_Crack을 설명 못 하므로 무엇이 설명하는지 찾는다.
# Focus/Cutting_Offset은 멘토가 "분석에 안 써도 됨"으로 확정해 제외(팀 도메인 1등급).
# 파생변수(Cleaning_Capacity 등 원본 변수의 계산식)도 다중공선성 때문에 제외.
EXCLUDE_FROM_SCAN = {"Focus", "Cutting_Offset"}

# 2-3 Head_Temp 귀속 판정용 — 레이저 계열 vs 냉각 계열
LASER_GROUP = ["Power_Efficiency", "Laser_Power", "Laser_Centering_Position"]
COOLING_GROUP = ["Cooling_Flow", "Cooling_Water_Temp"]


def load(path_str: str) -> pd.DataFrame:
    orig = config.INPUT_CSV
    config.INPUT_CSV = config.ROOT / path_str
    try:
        return load_dataset()
    finally:
        config.INPUT_CSV = orig


def rank_biserial(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    a, b = a.dropna(), b.dropna()
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(2 * u / (len(a) * len(b)) - 1), float(p)


def make_z(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """OPCOND 층별 강건 z-score. 정상군에서만 baseline 학습."""
    baseline = compute_stratum_baseline_stats(df.loc[df["is_normal"]], config.OPCOND, cols)
    return zscore_transform(df, baseline, config.OPCOND, cols)


# ---------------------------------------------------------------------------
# 2-1 — DP03의 Micro_Crack 초과분이 냉각 인자로 설명되는가 (매개분석)
# ---------------------------------------------------------------------------
def step21_mediation(df: pd.DataFrame, dataset_name: str) -> list[dict]:
    """장비 더미만 넣은 모델 vs 냉각 인자를 추가한 모델의 오즈비 변화.

    냉각이 진짜 DP03 Micro_Crack의 원인이라면, 냉각을 보정했을 때 DP03 오즈비가
    1에 가까워져야 한다(08.01 DP04/CLN_Flow에서 103% 감소가 나왔던 그 패턴).
    """
    results = []
    mediator_sets = {
        "냉각 인자(진혁님 도메인)": ["Cooling_Flow", "Cooling_Water_Temp"],
        "냉각 + Vibration": ["Cooling_Flow", "Cooling_Water_Temp", "Vibration"],
    }
    all_cols = sorted({c for v in mediator_sets.values() for c in v})
    z = make_z(df, all_cols)

    for target, defect in [("DP03", "Micro_Crack"), ("DP02", "Chipping")]:
        y = z[defect]
        if y.sum() < 30:
            results.append({"dataset": dataset_name, "machine": target, "defect": defect,
                            "mediator_set": "-", "or_machine_only": np.nan,
                            "or_adjusted": np.nan, "excess_risk_explained_pct": np.nan,
                            "note": f"{defect} {int(y.sum())}건 — 표본 부족으로 판정 불가"})
            continue
        machine_dummy = (z["Machine_ID"] == target).astype(int).to_numpy().reshape(-1, 1)

        base = LogisticRegression(max_iter=2000)
        base.fit(machine_dummy, y)
        or_base = float(np.exp(base.coef_[0][0]))

        for label, mediators in mediator_sets.items():
            zcols = [f"{m}_z" for m in mediators]
            X = np.column_stack([machine_dummy.ravel()] + [z[c].to_numpy() for c in zcols])
            ok = ~np.isnan(X).any(axis=1)
            adj = LogisticRegression(max_iter=2000)
            adj.fit(X[ok], y[ok])
            or_adj = float(np.exp(adj.coef_[0][0]))
            # 초과위험(오즈비-1)이 몇 % 사라졌는가. 100%에 가까울수록 그 인자가 다 설명한 것.
            explained = ((or_base - 1) - (or_adj - 1)) / (or_base - 1) * 100 if or_base != 1 else np.nan
            results.append({
                "dataset": dataset_name, "machine": target, "defect": defect,
                "mediator_set": label, "mediators": ", ".join(mediators),
                "or_machine_only": or_base, "or_adjusted": or_adj,
                "excess_risk_explained_pct": explained, "note": "",
            })
    return results


# ---------------------------------------------------------------------------
# 2-2 — 냉각이 아니라면 무엇이 DP03의 Micro_Crack을 가르는가 (후보 스캔)
# ---------------------------------------------------------------------------
def step22_scan(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    """DP03 안에서 Micro_Crack 행 vs 정상 행의 인자 차이를 전 후보에 대해 훑는다.

    진혁님 스트립 단위 검정은 전체 행 대상이라 "DP03 안에서만" 보는 각도가 빠져 있다.
    장비를 고정하면 장비 간 차이가 교란으로 들어오지 않는다.

    broad/pure 두 라벨로 각각 돌린다 — DP03은 Chipping도 31.6%라, Micro_Crack 행에
    Chipping이 섞여 있으면 레이저 계열 인자가 Chipping 때문에 딸려 들어온다.
    pure(다른 3개 defect가 동시 발생한 행을 양쪽에서 제외)는 진혁님이 rel_20에서
    쓰신 것과 같은 기준이며, 이 오염을 걷어낸다.
    """
    candidates = [c for c in config.FDC_COLS if c in df.columns and c not in EXCLUDE_FROM_SCAN]
    z = make_z(df, candidates)
    others = [d for d in ["Chipping", "Particle", "Remain_Coat", "Laser_Paim"] if d in z.columns]

    out_frames = []
    for label in ("broad", "pure"):
        d = z[z["Machine_ID"] == "DP03"]
        if label == "pure":
            # 다른 defect가 하나라도 같이 난 행은 불량군·비교군 양쪽에서 제외
            d = d[d[others].sum(axis=1) == 0] if others else d
        n_def = int(d["Micro_Crack"].sum())
        if n_def < 30:
            out_frames.append(pd.DataFrame([{
                "dataset": dataset_name, "label": label, "factor": "-", "cliffs_delta": np.nan,
                "p_value": np.nan, "p_fdr": np.nan, "passes": False, "n_defect": n_def,
                "n_rows": len(d), "note": f"Micro_Crack {n_def}건 — 표본 부족으로 판정 불가"}]))
            continue
        rows = []
        for c in candidates:
            delta, p = rank_biserial(d.loc[d["Micro_Crack"] == 1, f"{c}_z"],
                                     d.loc[d["Micro_Crack"] == 0, f"{c}_z"])
            rows.append({"dataset": dataset_name, "label": label, "factor": c,
                         "cliffs_delta": delta, "p_value": p, "n_defect": n_def,
                         "n_rows": len(d), "note": ""})
        sub = pd.DataFrame(rows)
        valid = sub["p_value"].notna()
        sub.loc[valid, "p_fdr"] = multipletests(sub.loc[valid, "p_value"], method="fdr_bh")[1]
        sub["passes"] = (sub["p_fdr"] < FDR_ALPHA) & (sub["cliffs_delta"].abs() >= EFFECT_SIZE_MIN)
        out_frames.append(sub.sort_values("cliffs_delta", key=abs, ascending=False))
    return pd.concat(out_frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 2-3 — Head_Temp 귀속: 레이저 계열인가 냉각 계열인가
# ---------------------------------------------------------------------------
def step23_head_temp(df: pd.DataFrame, dataset_name: str) -> list[dict]:
    """진혁님이 rel_15에 "귀속 미확정"으로 남긴 질문에 장비 각도로 답한다.

    두 가지를 본다:
      (a) Head_Temp가 어느 계열 인자와 더 강하게 붙는가 (Spearman)
      (b) Head_Temp가 어느 장비에서 튀는가 — DP02(레이저 열화)인가 DP03(냉각 실패)인가
    """
    cols = ["Head_Temp"] + LASER_GROUP + COOLING_GROUP
    cols = [c for c in cols if c in df.columns]
    z = make_z(df, cols)
    results = []

    for group_name, group in [("레이저 계열", LASER_GROUP), ("냉각 계열", COOLING_GROUP)]:
        for other in group:
            if other not in df.columns:
                continue
            paired = z[["Head_Temp_z", f"{other}_z"]].dropna()
            r, p = scipy_stats.spearmanr(paired.iloc[:, 0], paired.iloc[:, 1])
            results.append({"dataset": dataset_name, "check": "(a) 계열 상관",
                            "group": group_name, "partner": other,
                            "value": float(r), "p_value": float(p), "n": len(paired)})

    # (c) 장비 안에서의 상관 — 전체 상관은 DP02의 레이저 열화가 통째로 끌고 갈 수 있다.
    # 장비를 고정하면 "그 장비 안에서 Head_Temp가 무엇과 함께 움직이는가"만 남는다.
    for machine in ["DP02", "DP03"]:
        d = z[z["Machine_ID"] == machine]
        for group_name, group in [("레이저 계열", LASER_GROUP), ("냉각 계열", COOLING_GROUP)]:
            for other in group:
                if other not in df.columns:
                    continue
                paired = d[["Head_Temp_z", f"{other}_z"]].dropna()
                if len(paired) < 30:
                    continue
                r, p = scipy_stats.spearmanr(paired.iloc[:, 0], paired.iloc[:, 1])
                results.append({"dataset": dataset_name, "check": f"(c) {machine} 내부 상관",
                                "group": group_name, "partner": other,
                                "value": float(r), "p_value": float(p), "n": len(paired)})

    for machine in MACHINES:
        med = float(z.loc[z["Machine_ID"] == machine, "Head_Temp_z"].median())
        results.append({"dataset": dataset_name, "check": "(b) 장비별 수준",
                        "group": machine, "partner": "Head_Temp median z",
                        "value": med, "p_value": np.nan,
                        "n": int((z["Machine_ID"] == machine).sum())})
    return results


# ---------------------------------------------------------------------------
# 2-4 — 조치 우선순위: 같은 불량에 걸린 인자들이 서로 독립인가
# ---------------------------------------------------------------------------
def step24_independence(df: pd.DataFrame, dataset_name: str) -> list[dict]:
    """A를 5분위 층으로 고정한 뒤에도 B가 불량을 가르면 둘은 별개 조치항목이다.

    불량률이 포화된 층(>=90% 또는 <=1%)은 무엇을 넣어도 갈릴 여지가 없으므로
    판정에서 제외한다 — 이걸 빼먹으면 "층 5개 중 3개에서 유의하지 않음"을
    독립성 부족으로 잘못 읽는다.
    """
    pairs = [
        ("DP02", "Chipping", "Power_Efficiency", "Head_Temp"),
        ("DP02", "Chipping", "Power_Efficiency", "Laser_Power"),
        ("DP03", "Chipping", "Cooling_Flow", "Head_Temp"),
    ]
    cols = sorted({c for _, _, a, b in pairs for c in (a, b)})
    z = make_z(df, [c for c in cols if c in df.columns])
    results = []

    for machine, defect, hold, test in pairs:
        d = z[z["Machine_ID"] == machine]
        if d[defect].sum() < 30:
            results.append({"dataset": dataset_name, "machine": machine, "defect": defect,
                            "hold_fixed": hold, "tested": test, "n_informative_bins": 0,
                            "n_bins_significant": 0, "verdict": "판정 불가(표본 부족)",
                            "max_abs_delta": np.nan})
            continue
        d = d.copy()
        d["bin"] = pd.qcut(d[f"{hold}_z"], 5, labels=False, duplicates="drop")
        n_informative, n_sig, max_delta = 0, 0, 0.0
        for _, g in d.groupby("bin"):
            rate = g[defect].mean()
            if rate >= 0.90 or rate <= 0.01:
                continue  # 포화 — 판정 불가 층
            n_informative += 1
            delta, p = rank_biserial(g.loc[g[defect] == 1, f"{test}_z"],
                                     g.loc[g[defect] == 0, f"{test}_z"])
            if not np.isnan(delta):
                max_delta = max(max_delta, abs(delta))
                if p < FDR_ALPHA and abs(delta) >= EFFECT_SIZE_MIN:
                    n_sig += 1
        verdict = ("독립 — 별개 조치항목" if n_informative and n_sig == n_informative
                   else "일부 층에서만 독립" if n_sig
                   else "중복 — 같은 신호" if n_informative else "판정 불가(전 층 포화)")
        results.append({"dataset": dataset_name, "machine": machine, "defect": defect,
                        "hold_fixed": hold, "tested": test,
                        "n_informative_bins": n_informative, "n_bins_significant": n_sig,
                        "max_abs_delta": max_delta, "verdict": verdict})
    return results


# ---------------------------------------------------------------------------
# 2-5 — Micro_Crack x Vibration 분해: 진혁님 T3 강등 근거와 대조
# ---------------------------------------------------------------------------
def step25_vibration(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """진혁님이 T3로 강등한 Micro_Crack/Vibration을 장비별·데이터셋별로 분해한다.

    처음엔 "DP03에서만 살아나니 장비 한정 인자"로 봤는데, 4대를 다 계산하니 전부
    +0.17~+0.25로 비슷했다 — 장비 한정이 아니라 장비 무관 신호다. 장비를 층으로
    고정해 가중평균해도 pooled와 -0.009밖에 차이가 안 난다(= 장비 분할로 얻는 게 없다).

    남는 문제는 진혁님 기재값(+0.063)이 어느 조합으로도 재현되지 않는다는 것이라,
    비교 가능한 형태로 전부 남긴다.
    """
    rows = []
    pures = {}
    for name, df in datasets.items():
        z = make_z(df, ["Vibration"])
        others = [d for d in ["Chipping", "Particle", "Remain_Coat", "Laser_Paim"]
                  if d in z.columns]
        pure = z[z[others].sum(axis=1) == 0] if others else z
        pures[name] = pure[["Vibration_z", "Micro_Crack"]]

        for scope in ["pooled"] + MACHINES:
            g = pure if scope == "pooled" else pure[pure["Machine_ID"] == scope]
            delta, p = rank_biserial(g.loc[g["Micro_Crack"] == 1, "Vibration_z"],
                                     g.loc[g["Micro_Crack"] == 0, "Vibration_z"])
            row = {"dataset": name, "scope": scope, "n_rows": len(g),
                   "n_micro_crack": int(g["Micro_Crack"].sum()),
                   "micro_crack_rate_pct": float(g["Micro_Crack"].mean() * 100),
                   "vibration_median_z": float(g["Vibration_z"].median()),
                   "cliffs_delta": delta, "p_value": p}
            # 용량반응: Vibration 5분위별 Micro_Crack율이 단조 증가하는가
            if g["Micro_Crack"].sum() >= 30:
                q = pd.qcut(g["Vibration_z"], 5, labels=False, duplicates="drop")
                rates = g.groupby(q)["Micro_Crack"].mean() * 100
                for i, v in enumerate(rates):
                    row[f"mc_rate_Q{i + 1}_pct"] = float(v)
                row["q5_over_q1"] = float(rates.iloc[-1] / rates.iloc[0]) if rates.iloc[0] else np.nan
            rows.append(row)

    # 원본+r1 합본 — 진혁님 rel_20의 n(약 20만)과 같은 범위로 맞춘 비교
    comb = pd.concat(pures.values(), ignore_index=True)
    delta, p = rank_biserial(comb.loc[comb["Micro_Crack"] == 1, "Vibration_z"],
                             comb.loc[comb["Micro_Crack"] == 0, "Vibration_z"])
    rows.append({"dataset": "원본+r1 합침", "scope": "pooled", "n_rows": len(comb),
                 "n_micro_crack": int(comb["Micro_Crack"].sum()),
                 "micro_crack_rate_pct": float(comb["Micro_Crack"].mean() * 100),
                 "vibration_median_z": float(comb["Vibration_z"].median()),
                 "cliffs_delta": delta, "p_value": p})
    rows.append({"dataset": "진혁님 rel_20 기재값", "scope": "pooled", "n_rows": 200000,
                 "n_micro_crack": np.nan, "micro_crack_rate_pct": np.nan,
                 "vibration_median_z": np.nan, "cliffs_delta": 0.0633, "p_value": np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2-6 — 진혁님 rel_20 재현 + pure 라벨 정의 수정 시 판정 변화
# ---------------------------------------------------------------------------
def step26_pure_label(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """진혁님 build_tier_table.py의 pure 라벨이 불량군에만 적용돼 있다.

        df[f"__pure_{d}"] = ((df[d] == 1) & (df[others].sum(axis=1) == 0))
        ...
        cliffs_delta(df.loc[y == 1, zcol], df.loc[y == 0, zcol])

    y==0(비교군)에는 다른 defect가 난 행이 그대로 남는다. 바로 아래 LABEL_DEF 문구는
    "비교군·불량군 양쪽에서 제외"라고 돼 있어 코드와 문서가 어긋난다.

    Micro_Crack에서 특히 문제가 되는 이유: 비교군에 섞여 들어가는 Chipping 행은
    Vibration이 매우 높다(진혁님 자신의 판정으로 Chipping/Vibration delta +0.816).
    "정상"이라고 놓은 비교군이 실은 고진동 행 덩어리라 Micro_Crack의 진동 신호가 상쇄된다.

    두 방식을 나란히 계산해 어느 판정이 실제로 바뀌는지 확인한다. 진혁님이 쓰신
    원본+r1 합본·합본 baseline을 그대로 재현해야 값이 맞으므로 여기서만 따로 로드한다.
    """
    defects = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
    cols = sorted({r["factor"] for r in JH_TIER})

    df = config.add_domain_features(pd.concat(
        [d.assign(source_dataset=n) for n, d in datasets.items()], ignore_index=True))
    df["is_normal"] = config.NORMAL(df)
    df = zscore_transform(
        df, compute_stratum_baseline_stats(df[df["is_normal"]], config.OPCOND, cols),
        config.OPCOND, cols)

    rows = []
    for rec in JH_TIER:
        d, f = rec["defect"], rec["factor"]
        others = [x for x in defects if x != d]
        zcol = f"{f}_z"
        pure_defect = (df[d] == 1) & (df[others].sum(axis=1) == 0)
        # (a) 진혁님 코드 그대로 — 비교군에 다른 defect 포함
        as_coded, _ = rank_biserial(df.loc[pure_defect, zcol], df.loc[~pure_defect, zcol])
        # (b) LABEL_DEF 문구대로 — 양쪽에서 제외
        keep = df[others].sum(axis=1) == 0
        as_documented, _ = rank_biserial(df.loc[keep & (df[d] == 1), zcol],
                                         df.loc[keep & (df[d] == 0), zcol])
        passed_before = abs(rec["delta"]) >= EFFECT_SIZE_MIN
        passed_after = abs(as_documented) >= EFFECT_SIZE_MIN
        rows.append({
            "defect": d, "factor": f, "jh_tier": rec["tier"],
            "jh_recorded_delta": rec["delta"],
            "reproduced_as_coded": as_coded,
            "recomputed_as_documented": as_documented,
            "delta_change": as_documented - as_coded,
            "passed_effect_size_before": passed_before,
            "passed_effect_size_after": passed_after,
            "verdict_changes": passed_before != passed_after,
        })
    return pd.DataFrame(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    med_all, scan_all, ht_all, ind_all = [], [], [], []
    loaded = {}
    for name, path in DATASETS.items():
        df = load(path)
        loaded[name] = df
        med_all += step21_mediation(df, name)
        scan_all.append(step22_scan(df, name))
        ht_all += step23_head_temp(df, name)
        ind_all += step24_independence(df, name)
    vib = step25_vibration(loaded)
    pure_lbl = step26_pure_label(loaded)

    med = pd.DataFrame(med_all)
    scan = pd.concat(scan_all, ignore_index=True)
    ht = pd.DataFrame(ht_all)
    ind = pd.DataFrame(ind_all)
    jh = pd.DataFrame(JH_TIER)

    med.to_csv(OUT_DIR / "05_micro_crack_mediation.csv", encoding="utf-8-sig", index=False)
    scan.to_csv(OUT_DIR / "06_dp03_micro_crack_scan.csv", encoding="utf-8-sig", index=False)
    ht.to_csv(OUT_DIR / "07_head_temp_attribution.csv", encoding="utf-8-sig", index=False)
    ind.to_csv(OUT_DIR / "08_factor_independence.csv", encoding="utf-8-sig", index=False)
    jh.to_csv(OUT_DIR / "09_jh_tier_reference.csv", encoding="utf-8-sig", index=False)
    vib.to_csv(OUT_DIR / "10_vibration_decomposition.csv", encoding="utf-8-sig", index=False)
    pure_lbl.to_csv(OUT_DIR / "11_jh_pure_label_recompute.csv", encoding="utf-8-sig", index=False)

    print("=" * 80)
    print("2-1  DP03의 Micro_Crack 초과분이 냉각 인자로 설명되는가 (매개분석)")
    print("=" * 80)
    for _, r in med.iterrows():
        if r["note"]:
            print(f"[{r['dataset']:3}] {r['machine']} -> {r['defect']:12} {r['note']}")
            continue
        print(f"[{r['dataset']:3}] {r['machine']} -> {r['defect']:12} {r['mediator_set']:22} "
              f"오즈비 {r['or_machine_only']:6.2f} -> {r['or_adjusted']:6.2f}  "
              f"초과위험 설명 {r['excess_risk_explained_pct']:6.1f}%")

    print()
    print("=" * 80)
    print("2-2  그렇다면 무엇이 DP03의 Micro_Crack을 가르는가 (DP03 내부 전수 스캔)")
    print("=" * 80)
    for ds in DATASETS:
        for label in ("broad", "pure"):
            g = scan[(scan["dataset"] == ds) & (scan["label"] == label)]
            if g.empty:
                continue
            if g["factor"].iloc[0] == "-":
                print(f"[{ds}/{label}] {g['note'].iloc[0]}")
                continue
            n_pass = int(g["passes"].sum())
            print(f"[{ds}/{label:5}] 통과 {n_pass}개 / 후보 {len(g)}개 "
                  f"(Micro_Crack {g['n_defect'].iloc[0]}건 / {g['n_rows'].iloc[0]}행) — 상위 6개:")
            for _, r in g.head(6).iterrows():
                mark = "O 통과" if r["passes"] else "- 미달"
                print(f"       {r['factor']:24} delta {r['cliffs_delta']:+.3f}  "
                      f"FDR {r['p_fdr']:.2e}  {mark}")

    print()
    print("=" * 80)
    print("2-3  Head_Temp 귀속 — 레이저 계열인가 냉각 계열인가 (진혁님 미확정 항목)")
    print("=" * 80)
    for ds in DATASETS:
        print(f"[{ds}]")
        a = ht[(ht["dataset"] == ds) & (ht["check"] == "(a) 계열 상관")]
        for _, r in a.iterrows():
            print(f"       {r['group']:8} {r['partner']:24} Spearman r {r['value']:+.3f}")
        b = ht[(ht["dataset"] == ds) & (ht["check"] == "(b) 장비별 수준")]
        line = "  ".join(f"{r['group']} {r['value']:+6.2f}" for _, r in b.iterrows())
        print(f"       장비별 Head_Temp median z:  {line}")
        for machine in ["DP02", "DP03"]:
            c = ht[(ht["dataset"] == ds) & (ht["check"] == f"(c) {machine} 내부 상관")]
            if c.empty:
                continue
            line = "  ".join(f"{r['partner'][:18]} {r['value']:+.3f}" for _, r in c.iterrows())
            print(f"       {machine} 내부 상관: {line}")

    print()
    print("=" * 80)
    print("2-4  조치 우선순위 — 인자끼리 중복인가 별개인가 (층별 검증)")
    print("=" * 80)
    for _, r in ind.iterrows():
        print(f"[{r['dataset']:3}] {r['machine']} {r['defect']:11} "
              f"{r['hold_fixed']:16} 고정 후 {r['tested']:18} "
              f"유효층 {r['n_bins_significant']}/{r['n_informative_bins']}  -> {r['verdict']}")

    print()
    print("=" * 80)
    print("2-5  Micro_Crack x Vibration 분해 — 진혁님 T3 강등(+0.063) 근거와 대조")
    print("=" * 80)
    for _, r in vib.iterrows():
        q = f"  Q5/Q1 {r['q5_over_q1']:.2f}배" if not pd.isna(r.get("q5_over_q1")) else ""
        d = "  nan" if pd.isna(r["cliffs_delta"]) else f"{r['cliffs_delta']:+.4f}"
        print(f"[{r['dataset']:14}] {r['scope']:7} n={r['n_rows']:7d} "
              f"delta {d}{q}")

    print()
    print("=" * 80)
    print("2-6  진혁님 rel_20 재현 + pure 라벨을 문서 문구대로 고쳤을 때의 판정 변화")
    print("=" * 80)
    print(f"{'defect':12} {'factor':20} {'티어':4} {'기재값':>9} {'재현':>9} "
          f"{'수정후':>9} {'변화':>9}")
    for _, r in pure_lbl.iterrows():
        flag = "  ★ 판정 뒤집힘" if r["verdict_changes"] else ""
        print(f"{r['defect']:12} {r['factor']:20} {r['jh_tier']:4} "
              f"{r['jh_recorded_delta']:+9.4f} {r['reproduced_as_coded']:+9.4f} "
              f"{r['recomputed_as_documented']:+9.4f} {r['delta_change']:+9.4f}{flag}")
    n_changed = int(pure_lbl["verdict_changes"].sum())
    print(f"\n  재현 일치: {int((pure_lbl['jh_recorded_delta'] - pure_lbl['reproduced_as_coded']).abs().lt(1e-3).sum())}"
          f"/{len(pure_lbl)}건, 판정 뒤집힘: {n_changed}건")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "1차(멘토 시나리오) x 진혁님 티어표 충돌 지점을 장비 각도로 판정 (26.08.06)",
        "pure_label_finding": (
            "진혁님 build_tier_table.py의 pure 라벨이 불량군에만 적용되고 비교군에는 "
            "적용되지 않는다(코드 82행 vs 바로 아래 LABEL_DEF 문구 불일치). 그 방식으로 "
            "rel_20 13개 항목이 소수점 4자리까지 전부 재현된다. 문서 문구대로 양쪽에서 "
            "제외하면 Micro_Crack/Vibration만 +0.0633 -> +0.2211로 판정이 뒤집히고 "
            "나머지 12건은 판정 유지."
        ),
        "vibration_correction": (
            "최초 해석('Vibration은 DP02·DP03 한정 인자')은 틀렸다. 4대 전부 +0.17~+0.25로 "
            "비슷하고, 장비 층화 가중평균(+0.206)과 pooled(+0.214) 차이가 -0.009라 "
            "장비 분할로 얻는 신호가 없다. 남은 쟁점은 진혁님 기재값 +0.063이 어느 "
            "조합으로도 재현되지 않는다는 것(원본 +0.103 / r1 +0.214 / 합침 +0.227)."
        ),
        "conflicts_examined": {
            "A_micro_crack": "멘토는 DP03 Cooling Failure -> Micro_Crack, 진혁님은 Micro_Crack "
                             "확정 원인 0건(냉각 인자 전부 강등). 장비 수준 vs 스트립 수준 불일치.",
            "B_head_temp": "진혁님 rel_15에 'Head_Temp 귀속 미확정(냉각/레이저)'으로 남은 항목. "
                           "멘토님은 DP03(Cooling Failure) 쪽에 배치하셨다.",
        },
        "jh_source": "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/rel_20_tier_table.csv, rel_15 "
                     "(커밋 f48a8f6 — 현재 브랜치에 미병합, 값을 옮겨 적었음)",
        "method": "OPCOND 층별 강건 z-score. 매개분석은 L1 아닌 기본 로지스틱, "
                  "층별 독립성은 포화 층(불량률 >=90% 또는 <=1%) 제외. SHAP/Boosting 미사용.",
        "datasets": list(DATASETS),
    }
    with open(OUT_DIR / "00b_tier2_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n산출물 저장: {OUT_DIR}")


if __name__ == "__main__":
    main()
