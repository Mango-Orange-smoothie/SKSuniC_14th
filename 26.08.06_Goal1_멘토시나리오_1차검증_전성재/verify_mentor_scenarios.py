"""멘토님 장비별 고장 시나리오 1차 검증 (26.08.06, 전성재).

멘토님이 주신 시나리오를 "가설"로 놓고 데이터로 확인한다. 블라인드 스캔(08.01)과 반대
방향의 접근 — 저쪽은 힌트 없이 훑어서 방법론을 검증했고, 이쪽은 도메인/멘토 가설을
먼저 세우고 맞는지만 본다.

멘토님 시나리오:
  DP02 (Laser Aging)     -> Chipping 증가, Laser_Paim 증가
  DP03 (Cooling Failure) -> Micro_Crack 증가, Chipping 약간 증가
  DP04 (Cleaning Failure)-> Particle 증가, Remain_Coat 증가

멘토님이 주신 인과사슬:
  DP02: Laser Aging -> Power_Efficiency 감소 -> Kerf 증가 -> Chipping 증가
  DP03: Head_Temp / Cooling Failure -> Micro_Crack, Chipping 증가
  DP04: Cleaning Failure -> CLN_Flow 감소 -> Remain_Coat 증가

주의 — 08.05 멘토 지시 3항은 "인자끼리 엮지 말 것"이었는데, 이번 피드백의 DP02 사슬은
인자끼리 엮은 형태(Power_Efficiency -> Kerf)다. 멘토님이 직접 주신 사슬이라 그대로
검증하되, 3단계 결과에는 "이건 1:1 대응이 아니라 사슬"임을 명시한다.

검증 3단계:
  1단계  시나리오 결과(불량): 그 장비에서 그 defect가 실제로 더 많이 나는가
  2단계  사슬의 각 고리(인자): 그 장비에서 그 인자가 멘토가 말한 방향으로 벗어났는가
  3단계  사슬의 연결: Power_Efficiency -> Kerf -> Chipping 이 실제로 이어지는가

"Kerf"는 멘토님이 어느 컬럼인지 특정하지 않으셔서 4개(Kerf_Angle, Top_Kerf,
Bottom_Kerf, Kerf_Width_Profile) 전부 검증하고 어느 것이 맞는지 데이터가 답하게 한다.

장비 비교는 Goal1과 동일하게 OPCOND(Product x Recipe) 층별 강건 z-score로 정규화한 뒤
타깃 vs 나머지 3대 개별 비교(pairwise). one-vs-rest를 쓰면 극단적인 장비 하나가 "나머지
그룹" 평균을 끌고 가 정상 장비까지 이상으로 잡힌다(08.01에서 실제로 겪음).

SHAP/Boosting 미사용 (26.08.05 멘토 지시).

실행: PYTHONPATH=. python "26.08.06_Goal1_멘토시나리오_1차검증_전성재/verify_mentor_scenarios.py"
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.stats.multitest import multipletests

from pipeline import config
from pipeline.common import compute_stratum_baseline_stats, load_dataset, zscore_transform

OUT_DIR = Path(__file__).resolve().parent
MACHINES = ["DP01", "DP02", "DP03", "DP04"]
EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = 0.05

DATASETS = {
    "원본": "data/raw/DP_HealthIndex_Dataset.csv",
    "r1": "data/raw/DP_HealthIndex_Dataset_r1.csv",
}

# ---------------------------------------------------------------------------
# 1단계 입력 — 멘토 시나리오의 "결과"(장비 -> 불량)
# strength: 멘토님 표현 그대로. "약간"은 효과가 작을 것으로 예고된 것이라 판정 시 참고.
# ---------------------------------------------------------------------------
MENTOR_DEFECT_CLAIMS = [
    {"machine": "DP02", "defect": "Chipping", "scenario": "Laser Aging", "strength": "증가"},
    {"machine": "DP02", "defect": "Laser_Paim", "scenario": "Laser Aging", "strength": "증가"},
    {"machine": "DP03", "defect": "Micro_Crack", "scenario": "Cooling Failure", "strength": "증가"},
    {"machine": "DP03", "defect": "Chipping", "scenario": "Cooling Failure", "strength": "약간 증가"},
    {"machine": "DP04", "defect": "Particle", "scenario": "Cleaning Failure", "strength": "증가"},
    {"machine": "DP04", "defect": "Remain_Coat", "scenario": "Cleaning Failure", "strength": "증가"},
]

# ---------------------------------------------------------------------------
# 2단계 입력 — 멘토 사슬의 각 고리(장비 -> 인자, 예상 방향)
# expected_direction: "down"=그 장비에서 낮아야 시나리오와 일치, "up"=높아야 일치
# kerf_candidate: 멘토가 "Kerf"라고만 하셔서 어느 컬럼인지 데이터로 확인할 대상
# ---------------------------------------------------------------------------
KERF_CANDIDATES = ["Kerf_Angle", "Top_Kerf", "Bottom_Kerf", "Kerf_Width_Profile"]

MENTOR_FACTOR_CLAIMS = [
    {"machine": "DP02", "factor": "Power_Efficiency", "expected": "down",
     "chain_step": "Laser Aging -> Power_Efficiency 감소", "kerf_candidate": False},
    *[{"machine": "DP02", "factor": k, "expected": "up",
       "chain_step": "Power_Efficiency 감소 -> Kerf 증가", "kerf_candidate": True}
      for k in KERF_CANDIDATES],
    {"machine": "DP03", "factor": "Head_Temp", "expected": "up",
     "chain_step": "Cooling Failure -> Head_Temp 상승", "kerf_candidate": False},
    {"machine": "DP03", "factor": "Cooling_Flow", "expected": "down",
     "chain_step": "Cooling Failure -> 냉각 유량 부족", "kerf_candidate": False},
    {"machine": "DP04", "factor": "CLN_Flow", "expected": "down",
     "chain_step": "Cleaning Failure -> CLN_Flow 감소", "kerf_candidate": False},
]

FACTORS = sorted({c["factor"] for c in MENTOR_FACTOR_CLAIMS})
DEFECTS = sorted({c["defect"] for c in MENTOR_DEFECT_CLAIMS})


def load(path_str: str) -> pd.DataFrame:
    orig = config.INPUT_CSV
    config.INPUT_CSV = config.ROOT / path_str
    try:
        return load_dataset()
    finally:
        config.INPUT_CSV = orig


def rank_biserial(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Cliff's delta(= rank-biserial)와 Mann-Whitney p. 표본 부족이면 NaN."""
    a, b = a.dropna(), b.dropna()
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(2 * u / (len(a) * len(b)) - 1), float(p)


# ---------------------------------------------------------------------------
# 1단계 — 시나리오 결과: 그 장비에서 그 defect가 실제로 더 나는가
# ---------------------------------------------------------------------------
def step1_defect_claims(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    rows = []
    for claim in MENTOR_DEFECT_CLAIMS:
        machine, defect = claim["machine"], claim["defect"]
        if defect not in df.columns:
            continue
        target = df.loc[df["Machine_ID"] == machine, defect]
        others = df.loc[df["Machine_ID"] != machine, defect]
        n_t, n_o = int(target.sum()), int(others.sum())
        rate_t = float(target.mean()) if len(target) else np.nan
        rate_o = float(others.mean()) if len(others) else np.nan

        # Fisher 정확검정 — Chipping/Laser_Paim은 원본에서 발생 건수가 매우 적어
        # 카이제곱 근사가 깨진다(기대도수 5 미만). 건수가 적어도 유효한 Fisher를 쓴다.
        table = [[n_t, len(target) - n_t], [n_o, len(others) - n_o]]
        try:
            odds, p = scipy_stats.fisher_exact(table, alternative="two-sided")
        except ValueError:
            odds, p = np.nan, np.nan

        rows.append({
            "dataset": dataset_name,
            "machine": machine,
            "defect": defect,
            "scenario": claim["scenario"],
            "mentor_says": claim["strength"],
            "n_defect_at_machine": n_t,
            "n_rows_at_machine": len(target),
            "rate_at_machine": rate_t,
            "rate_at_others": rate_o,
            # 나머지 3대가 0건이면 위험비가 정의되지 않는다. 타깃에 발생이 있으면
            # "무한대"(그 장비에서만 발생)로, 양쪽 다 0이면 판정 불가(NaN)로 둔다 —
            # NaN으로 뭉뚱그리면 r1 Laser_Paim(DP02 1902건 vs 나머지 0건)처럼
            # 가장 강한 지지가 "방향 반대"로 뒤집혀 찍힌다.
            "risk_ratio": (float(rate_t / rate_o) if rate_o and rate_o > 0
                           else (np.inf if rate_t and rate_t > 0 else np.nan)),
            "odds_ratio": float(odds) if odds is not None else np.nan,
            "p_value": p,
        })
    out = pd.DataFrame(rows)
    valid = out["p_value"].notna()
    out.loc[valid, "p_fdr"] = multipletests(out.loc[valid, "p_value"], method="fdr_bh")[1]
    # 판정: 멘토가 말한 "증가" 방향이어야 하고(risk_ratio>1), FDR 유의해야 한다.
    out["direction_matches"] = out["risk_ratio"] > 1
    out["supported"] = out["direction_matches"] & (out["p_fdr"] < FDR_ALPHA)
    return out


# ---------------------------------------------------------------------------
# 2단계 — 사슬의 각 고리: 그 장비에서 그 인자가 예상 방향으로 벗어났는가
# ---------------------------------------------------------------------------
def step2_factor_claims(df: pd.DataFrame, dataset_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, FACTORS)
    z = zscore_transform(df, baseline, config.OPCOND, FACTORS)

    pair_rows = []
    for claim in MENTOR_FACTOR_CLAIMS:
        machine, factor = claim["machine"], claim["factor"]
        zcol = f"{factor}_z"
        t_idx = z["Machine_ID"] == machine
        for other in MACHINES:
            if other == machine:
                continue
            delta, p = rank_biserial(z.loc[t_idx, zcol], z.loc[z["Machine_ID"] == other, zcol])
            pair_rows.append({
                "dataset": dataset_name, "machine": machine, "vs_machine": other,
                "factor": factor, "chain_step": claim["chain_step"],
                "expected_direction": claim["expected"],
                "cliffs_delta": delta, "p_value": p,
            })
    pairs = pd.DataFrame(pair_rows)
    valid = pairs["p_value"].notna()
    pairs.loc[valid, "p_fdr"] = multipletests(pairs.loc[valid, "p_value"], method="fdr_bh")[1]
    pairs["sig_pair"] = (pairs["p_fdr"] < FDR_ALPHA) & (pairs["cliffs_delta"].abs() >= EFFECT_SIZE_MIN)
    # 멘토가 말한 방향으로 유의하게 벗어났는가 (down이면 delta<0, up이면 delta>0)
    expected_sign = np.where(pairs["expected_direction"] == "down", -1, 1)
    pairs["sig_in_expected_direction"] = pairs["sig_pair"] & (np.sign(pairs["cliffs_delta"]) == expected_sign)

    rows = []
    for claim in MENTOR_FACTOR_CLAIMS:
        machine, factor = claim["machine"], claim["factor"]
        g = pairs[(pairs["machine"] == machine) & (pairs["factor"] == factor)]
        n_expected = int(g["sig_in_expected_direction"].sum())
        # 반대 방향으로 유의한 경우 — 시나리오와 정반대라 별도로 센다
        n_opposite = int((g["sig_pair"] & ~g["sig_in_expected_direction"]).sum())
        rows.append({
            "dataset": dataset_name,
            "machine": machine,
            "factor": factor,
            "chain_step": claim["chain_step"],
            "kerf_candidate": claim["kerf_candidate"],
            "expected_direction": claim["expected"],
            "median_z_at_machine": float(z.loc[z["Machine_ID"] == machine, f"{factor}_z"].median()),
            "n_machines_worse_expected_dir": n_expected,
            "n_machines_opposite_dir": n_opposite,
            "mean_delta_vs_others": float(g["cliffs_delta"].mean()),
            # 3대 전부 = 그 장비 고유 신호(가장 강한 근거), 2대 이상 = 나쁜 편
            # (2대 기준을 쓰는 이유: DP02·DP03처럼 둘 다 냉각이 나쁘면 서로를 가려
            #  3대 기준을 못 넘는다 — 08.05에서 확인)
            "supported_all3": n_expected == 3,
            "supported_2plus": n_expected >= 2,
        })
    return pd.DataFrame(rows), pairs


# ---------------------------------------------------------------------------
# 3단계 — 사슬의 연결: Power_Efficiency -> Kerf -> Chipping 이 이어지는가
# 멘토님이 직접 주신 사슬이라 검증하지만, 이건 인자끼리 엮은 형태(08.05 지시 3항과 반대)다.
# ---------------------------------------------------------------------------
def step3_chain_links(df: pd.DataFrame, dataset_name: str, best_kerf: str) -> list[dict]:
    cols = ["Power_Efficiency", best_kerf]
    df_normal = df.loc[df["is_normal"]]
    baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, cols)
    z = zscore_transform(df, baseline, config.OPCOND, cols)

    results = []

    # 고리 A: Power_Efficiency 감소 -> Kerf 증가  (음의 상관이어야 사슬과 일치)
    for scope, sub in [("전체", z), ("DP02만", z[z["Machine_ID"] == "DP02"])]:
        paired = sub[[f"Power_Efficiency_z", f"{best_kerf}_z"]].dropna()
        if len(paired) < 30:
            continue
        r, p = scipy_stats.spearmanr(paired.iloc[:, 0], paired.iloc[:, 1])
        results.append({
            "dataset": dataset_name, "link": "A. Power_Efficiency 감소 -> Kerf 증가",
            "kerf_column": best_kerf, "scope": scope, "metric": "Spearman r",
            "value": float(r), "p_value": float(p), "n": len(paired),
            "expected": "음수(효율 낮을수록 Kerf 큼)",
            "matches_mentor": bool(r < 0 and p < FDR_ALPHA),
        })

    # 고리 B: Kerf 증가 -> Chipping 증가 (Chipping 행의 Kerf z가 더 높아야 일치)
    if "Chipping" in z.columns:
        for scope, sub in [("전체", z), ("DP02만", z[z["Machine_ID"] == "DP02"])]:
            ng = sub.loc[sub["Chipping"] == 1, f"{best_kerf}_z"]
            ok = sub.loc[sub["Chipping"] == 0, f"{best_kerf}_z"]
            delta, p = rank_biserial(ng, ok)
            if np.isnan(delta):
                results.append({
                    "dataset": dataset_name, "link": "B. Kerf 증가 -> Chipping 증가",
                    "kerf_column": best_kerf, "scope": scope, "metric": "Cliff's delta",
                    "value": np.nan, "p_value": np.nan, "n": int(len(ng)),
                    "expected": "양수(Chipping 행의 Kerf가 큼)",
                    "matches_mentor": None, "note": f"Chipping 발생 {len(ng)}건 — 표본 부족으로 판정 불가",
                })
                continue
            results.append({
                "dataset": dataset_name, "link": "B. Kerf 증가 -> Chipping 증가",
                "kerf_column": best_kerf, "scope": scope, "metric": "Cliff's delta",
                "value": float(delta), "p_value": float(p), "n": int(len(ng)),
                "expected": "양수(Chipping 행의 Kerf가 큼)",
                "matches_mentor": bool(delta > 0 and p < FDR_ALPHA),
            })
    return results


def main() -> None:
    # Windows 기본 콘솔(cp949)에서 한글/em dash 출력이 깨지지 않게 강제
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    step1_all, step2_all, pairs_all, step3_all = [], [], [], []

    # 팀 방침(pipeline/README.md)은 원본과 r1을 합치지 않는 것이지만, 진혁님 rel_20이
    # 합본(20만 행) 기준이라 대조할 수 있도록 "합침"을 세 번째로 같이 돌린다.
    # 합본은 z-score baseline도 합본 정상군에서 학습되므로 값이 달라진다 —
    # 원본/r1 각각의 결과를 대체하는 게 아니라 진혁님 결과와 맞대보기 위한 것이다.
    frames = {name: load(path) for name, path in DATASETS.items()}
    frames["합침"] = pd.concat(
        [d.assign(source_dataset=n) for n, d in frames.items()], ignore_index=True)

    for name, df in frames.items():
        step1_all.append(step1_defect_claims(df, name))
        s2, pairs = step2_factor_claims(df, name)
        step2_all.append(s2)
        pairs_all.append(pairs)

        # 3단계는 2단계에서 가장 강하게 지지된 Kerf 컬럼으로 수행 —
        # 멘토가 "Kerf"라고만 하셨으므로 데이터가 고른 것을 쓴다.
        kerf = s2[s2["kerf_candidate"]].sort_values(
            ["n_machines_worse_expected_dir", "mean_delta_vs_others"], ascending=[False, False])
        best_kerf = kerf.iloc[0]["factor"] if len(kerf) else "Kerf_Angle"
        step3_all.append(pd.DataFrame(step3_chain_links(df, name, best_kerf)))

    step1 = pd.concat(step1_all, ignore_index=True)
    step2 = pd.concat(step2_all, ignore_index=True)
    pairs = pd.concat(pairs_all, ignore_index=True)
    step3 = pd.concat([s for s in step3_all if len(s)], ignore_index=True)

    step1.to_csv(OUT_DIR / "01_mentor_defect_claims.csv", encoding="utf-8-sig", index=False)
    step2.to_csv(OUT_DIR / "02_mentor_chain_factors.csv", encoding="utf-8-sig", index=False)
    pairs.to_csv(OUT_DIR / "03_factor_pairwise_detail.csv", encoding="utf-8-sig", index=False)
    step3.to_csv(OUT_DIR / "04_dp02_chain_links.csv", encoding="utf-8-sig", index=False)

    print("=" * 78)
    print("1단계 — 멘토 시나리오 결과(장비 -> 불량)")
    print("=" * 78)
    for _, r in step1.iterrows():
        if r["supported"]:
            mark = "O 지지"
        elif r["n_defect_at_machine"] == 0 and r["rate_at_others"] == 0:
            mark = "? 양쪽 0건"
        elif r["direction_matches"]:
            mark = "- 방향맞음/무의미"
        else:
            mark = "X 반대"
        rr = r["risk_ratio"]
        rr_txt = "  inf" if np.isinf(rr) else ("  nan" if pd.isna(rr) else f"{rr:6.2f}")
        print(f"[{r['dataset']:3}] {r['machine']} -> {r['defect']:12} "
              f"{r['rate_at_machine']*100:6.2f}% vs {r['rate_at_others']*100:6.2f}% "
              f"(RR {rr_txt}, n={r['n_defect_at_machine']:5d}, "
              f"FDR {r['p_fdr']:.2e})  {mark}  [멘토: {r['mentor_says']}]")

    print()
    print("=" * 78)
    print("2단계 — 멘토 사슬의 각 고리(장비 -> 인자)")
    print("=" * 78)
    for _, r in step2.iterrows():
        if r["supported_all3"]:
            mark = "O 3대 전부"
        elif r["supported_2plus"]:
            mark = "O 2대 이상"
        elif r["n_machines_opposite_dir"] > 0:
            mark = f"X 반대방향 {r['n_machines_opposite_dir']}대"
        else:
            mark = "- 차이없음"
        kerf_tag = " (Kerf 후보)" if r["kerf_candidate"] else ""
        print(f"[{r['dataset']:3}] {r['machine']} {r['factor']:20} "
              f"기대 {r['expected_direction']:4} z={r['median_z_at_machine']:+7.2f} "
              f"일치 {r['n_machines_worse_expected_dir']}/3  {mark}{kerf_tag}")

    print()
    print("=" * 78)
    print("3단계 — DP02 사슬 연결 (인자끼리 엮은 검증 — 멘토 요청)")
    print("=" * 78)
    for _, r in step3.iterrows():
        note = r.get("note", "")
        mark = {True: "O 일치", False: "X 불일치", None: "? 판정불가"}.get(r["matches_mentor"], "? 판정불가")
        val = "nan" if pd.isna(r["value"]) else f"{r['value']:+.3f}"
        print(f"[{r['dataset']:3}] {r['link']:34} [{r['scope']:6}] "
              f"{r['metric']} {val} (n={r['n']})  {mark} {note}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "멘토님 장비별 고장 시나리오/인과사슬을 가설로 놓고 1차 검증 (26.08.06)",
        "method": (
            "OPCOND(Product x Recipe) 층별 강건 z-score 정규화 후 타깃 장비 vs 나머지 3대 "
            f"개별 비교(pairwise). |Cliff's delta|>={EFFECT_SIZE_MIN} 및 BH-FDR<{FDR_ALPHA}이면서 "
            "멘토가 말한 방향과 일치할 때만 '지지'로 판정. defect 발생률은 Fisher 정확검정"
            "(원본 Chipping/Laser_Paim 건수가 적어 카이제곱 근사가 깨짐). SHAP/Boosting 미사용."
        ),
        "caveat_chain_vs_rule3": (
            "3단계(Power_Efficiency -> Kerf -> Chipping)는 인자끼리 엮은 사슬 검증으로, "
            "08.05 멘토 지시 3항('인자-불량 1:1만, 인자끼리 엮지 말 것')과 형식이 상충한다. "
            "이번 피드백에서 멘토님이 직접 사슬을 제시하셔서 검증했으므로, 어느 규칙이 "
            "우선인지 확인 필요."
        ),
        "kerf_ambiguity": (
            "멘토님이 'Kerf'라고만 하셔서 어느 컬럼인지 불명확 — "
            f"{KERF_CANDIDATES} 4개를 모두 검증하고 데이터가 고르게 했다."
        ),
        "n_defect_claims": len(MENTOR_DEFECT_CLAIMS),
        "n_factor_claims": len(MENTOR_FACTOR_CLAIMS),
        "datasets": list(DATASETS) + ["합침(원본+r1, 진혁님 rel_20 대조용)"],
        "step1_supported": step1.groupby("dataset")["supported"].sum().to_dict(),
        "step2_supported_2plus": step2.groupby("dataset")["supported_2plus"].sum().to_dict(),
    }
    with open(OUT_DIR / "00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n산출물 저장: {OUT_DIR}")


if __name__ == "__main__":
    main()
