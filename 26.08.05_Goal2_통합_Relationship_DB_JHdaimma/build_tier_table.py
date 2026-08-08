"""유효인자 티어표 — 확정 도메인 지식 + 통계검정 + RandomForest

멘토 방향성 반영 (2026-08-05)
  1. 숫자마다 '무슨 근거로 나온 값인지' 추적 가능하게 (가시성)
  2. FDC-FDC를 엮지 않는다. 인과사슬 없이 원인 -> 결과 1:1만.
  3. 티어 기준을 엄격/근거/가시성 있게 명시
  4. 액션 타입(즉시조치/조건부조치/감시/추세알람)을 넣는다
  5. 경고가 울리는 값의 범위를 실제 단위로 보여준다
  6. SOP는 아직 미수령 -> 칸을 비워둔다

확정 도메인 지식 13건만 후보로 쓴다. 추정 도메인은 쓰지 않는다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_tier_table.py"
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from statsmodels.stats.multitest import multipletests

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]
SRC = PROJ / "SKSuniC_14th" / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"

src = open(SRC / "build_relationship_db.py", encoding="utf-8").read()
exec(src.split("# ==================================================================== 데이터")[0])
ROOT = PROJ  # exec가 덮어쓴 ROOT 복원

RNG = 42
ALPHA = 0.05
EFFECT_MIN = 0.2       # Cliff's delta 하한 (교과서 관례: 0.15 미만 = 무시할 수준)
RF_TOP_PCT = 0.25      # 후보 수 비례 상위 25% (고정 top-10은 defect마다 엄격함이 달라짐)

# ==================================================================== 확정 도메인 지식 13건
# (defect, factor, 기대방향, 감시방식, 근거)
#   기대방향 "down" = 값이 낮아지면 불량 증가  -> Cliff's delta 음수를 기대
#   기대방향 "up"   = 값이 높아지면 불량 증가  -> Cliff's delta 양수를 기대
DOMAIN = [
    ("Particle",    "Surface_Roughness",  "up",   "level", "멘토 확정"),
    ("Particle",    "CLN_Flow",           "down", "level", "멘토 확정"),
    # 2026-08-06 방향 정정 — CLN_Pressure 증가 -> Particle 감소 (공정 도메인 확정).
    # 이전에는 "증가 -> Particle 증가"로 두어 Remain_Coat와 상충(트레이드오프)했으나,
    # 정정 후 두 defect 모두 "압력을 올리면 좋아지는" 같은 방향이 되어 상충이 사라진다.
    ("Particle",    "CLN_Pressure",       "down", "level", "멘토 확정 (26.08.06 방향 정정)"),
    # 2026-08-08 watch_mode 정정: spike -> level.
    #   전성재 검증9의 "즉시적 압력 하락"을 "직전 대비 낙차"로 읽고 spike로 뒀으나,
    #   낙차를 실제로 재보니 급락 사건이 없었다(rel_31 참조).
    #   압력이 매 샷 ±5로 흔들려 낙차 자체가 노이즈이고, 낙차>2.0이 전체의 16.8%나 된다.
    #   절대값 경계(lift 3.74, 알람 8.6%)가 낙차 기준(lift 2.33, 알람 16.8%)보다 낫다.
    #   "선행신호가 없다"는 미리 예고 없이 그 순간 값이 낮다는 뜻이지 낙차를 재라는 뜻이 아니었다.
    ("Remain_Coat", "CLN_Pressure",       "down", "level", "멘토 확정 (그 순간 값이 낮을 때 위험)"),
    ("Remain_Coat", "CLN_Flow",           "down", "level", "멘토 확정"),
    ("Micro_Crack", "Cooling_Flow",       "down", "level", "멘토 확정"),
    ("Micro_Crack", "Cooling_Water_Temp", "up",   "level", "멘토 확정"),
    ("Chipping",    "Power_Efficiency",   "down", "level", "멘토 확정"),
    ("Chipping",    "Laser_Power",        "down", "level", "멘토 확정"),
    ("Chipping",    "Head_Temp",          "up",   "level", "멘토 확정"),
    ("Chipping",    "Cooling_Flow",       "down", "level", "멘토 확정"),
]

# Vibration은 유효인자 판정에서 제외한다 (2026-08-06 결정).
#   Chipping/Vibration, Micro_Crack/Vibration 2건을 뺐다.
#   사유 — 유효인자(원인) 트랙이 아니라 별도 알람 트랙으로 운영하기로 했다.
#          추세 상승과 spec 이탈만 감시해 알람을 주고, 조치 지시는 하지 않는다.
#   따라서 티어표에는 넣지 않는다. 알람 규칙은 별도 산출물로 관리한다.
VIBRATION_EXCLUDED = [
    ("Chipping", "Vibration"),
    ("Micro_Crack", "Vibration"),
]

DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]

# ==================================================================== 데이터 준비
print("[1/5] 데이터 로드 · 층별 기준선 · 강건 z-score")
o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)

BASELINE_DEF = (f"OPCOND({'×'.join(OPCOND)}) 층별 정상군 median 기준, "
                f"산포는 MAD×{MAD_SCALE} (강건 z-score)")
print(f"    {len(df):,}행 · 정상군 {df.is_normal.sum():,} · 피처 {len(FEATURES)}개")

# pure 라벨: 다른 3개 defect가 하나도 없는 순수 케이스
for d in DEFECTS:
    others = [x for x in DEFECTS if x != d]
    df[f"__pure_{d}"] = ((df[d] == 1) & (df[others].sum(axis=1) == 0)).astype(int)
LABEL_DEF = "pure 라벨 — 나머지 3개 defect가 동시 발생한 행을 비교군·불량군 양쪽에서 제외"


def cliffs_delta(a, b):
    """Cliff's delta = P(a>b) - P(a<b). Mann-Whitney U를 -1~+1로 환산."""
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    u, p = sps.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p, len(a), len(b)


# ==================================================================== 통계검정 · RF
print("[2/5] 통계검정 (Mann-Whitney U + Cliff's delta + BH-FDR)")
uni, rf = {}, {}
for d in DEFECTS:
    y = df[f"__pure_{d}"].values
    rows = []
    for c in FEATURES:
        dl, p, n1, n0 = cliffs_delta(df.loc[y == 1, f"{c}_z"], df.loc[y == 0, f"{c}_z"])
        rows.append(dict(factor=c, delta=dl, p_raw=p, n_defect=n1, n_normal=n0))
    t = pd.DataFrame(rows)
    t["p_fdr"] = multipletests(t.p_raw, alpha=ALPHA, method="fdr_bh")[1]
    uni[d] = t.set_index("factor")
    print(f"    {d:12s} 불량(pure) {int(y.sum()):>6,}건 · 검정 {len(FEATURES)}회 · BH-FDR 보정")

print(f"[3/5] RandomForest 순열중요도 (상위 {RF_TOP_PCT:.0%} 기준)")
RF_SPEC = ("RandomForest(트리 200, 최대깊이 8, class_weight=balanced) 학습 후 "
           "검증셋에서 한 컬럼씩 무작위 셔플 10회 → PR-AUC(average_precision) 하락폭 평균")
for d in DEFECTS:
    y = df[f"__pure_{d}"].values
    fz = [f"{c}_z" for c in FEATURES]
    tr, te = train_test_split(df.assign(_y=y), test_size=0.2, random_state=RNG, stratify=y)
    m = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                               random_state=RNG, n_jobs=-1).fit(tr[fz], tr._y)
    tes = te.sample(n=min(20000, len(te)), random_state=RNG)
    pi = permutation_importance(m, tes[fz], tes._y, scoring="average_precision",
                                n_repeats=10, random_state=RNG, n_jobs=-1)
    t = pd.DataFrame({"factor": FEATURES, "imp": pi.importances_mean,
                      "imp_std": pi.importances_std})
    t["rank"] = t.imp.rank(ascending=False, method="min").astype(int)
    t["n_candidates"] = len(FEATURES)
    t["rank_cut"] = int(np.ceil(len(FEATURES) * RF_TOP_PCT))
    rf[d] = t.set_index("factor")
    print(f"    {d:12s} 후보 {len(FEATURES)}개 → 통과선 상위 {t.rank_cut.iloc[0]}위")


# ==================================================================== 경보 임계값 (실제 단위)
def alert_range(d: str, c: str, direction: str) -> dict:
    """DecisionTree stump(깊이1)로 경계를 찾고, 실제 단위 범위와 구간별 불량률을 낸다."""
    y = df[f"__pure_{d}"].values
    x = df[[f"{c}_z"]].dropna()
    yy = y[x.index]
    st = DecisionTreeClassifier(max_depth=1, class_weight="balanced",
                                random_state=RNG).fit(x, yy)
    thr_z = float(st.tree_.threshold[0])
    risky = x[f"{c}_z"] <= thr_z if direction == "down" else x[f"{c}_z"] > thr_z
    raw = df.loc[x.index, c]
    n_r, n_s = int(risky.sum()), int((~risky).sum())
    if n_r == 0 or n_s == 0:
        return {}
    rate_r = yy[risky.values].mean() * 100
    rate_s = yy[~risky.values].mean() * 100
    thr_raw = float(raw[risky].max() if direction == "down" else raw[risky].min())
    return dict(
        alert_threshold_z=round(thr_z, 3),
        alert_threshold_raw=round(thr_raw, 3),
        normal_range_raw=f"{raw[~risky].quantile(.05):.2f} ~ {raw[~risky].quantile(.95):.2f}",
        risky_range_raw=f"{raw[risky].quantile(.05):.2f} ~ {raw[risky].quantile(.95):.2f}",
        rate_in_normal_pct=round(rate_s, 3),
        rate_in_risky_pct=round(rate_r, 3),
        risk_ratio=round(rate_r / rate_s, 2) if rate_s > 0 else None,
        n_in_normal=n_s, n_in_risky=n_r,
        threshold_method="DecisionTree stump(max_depth=1, class_weight=balanced)로 분할점 탐색",
    )


# ==================================================================== 재현성
def repro(d: str, c: str) -> dict:
    out = {}
    for ds in ["original", "r1"]:
        s = (df.source_dataset == ds).values
        y = df[f"__pure_{d}"].values
        if (y[s] == 1).sum() < 10:
            out[ds] = np.nan
            continue
        dl, _, _, _ = cliffs_delta(df.loc[s & (y == 1), f"{c}_z"], df.loc[s & (y == 0), f"{c}_z"])
        out[ds] = round(dl, 4)
    n_ok = 0
    for mid in sorted(df.Machine_ID.dropna().unique()):
        s = (df.Machine_ID == mid).values
        y = df[f"__pure_{d}"].values
        if (y[s] == 1).sum() < 50:
            continue
        dl, _, _, _ = cliffs_delta(df.loc[s & (y == 1), f"{c}_z"], df.loc[s & (y == 0), f"{c}_z"])
        n_ok += int(abs(dl) >= EFFECT_MIN)
    # 원본 데이터의 해당 defect 표본 수 — '재현 실패'와 '표본 부족으로 판정 불가'를 구분하기 위함
    n_orig = int((df[f"__pure_{d}"].values[(df.source_dataset == "original").values] == 1).sum())
    return dict(delta_original=out.get("original"), delta_r1=out.get("r1"),
                n_defect_original=n_orig, n_machines_pass=n_ok)


# ==================================================================== 티어 판정
print("[4/5] 티어 판정")
LAYER = {c: ("Response" if c in RESPONSES else "FDC") for c in FEATURES}
ACTION = {
    "T1": "즉시조치", "T2": "조건부조치", "T3": "감시", "T4": "판단보류",
    "M1": "감시(경보)", "M2": "감시(경보·단서필요)", "M3": "감시(사후탐지)",
}

rows = []
for d, c, exp_dir, watch, ev in DOMAIN:
    u, t = uni[d].loc[c], rf[d].loc[c]
    delta, p_fdr = u.delta, u.p_fdr
    exp_sign = -1 if exp_dir == "down" else +1
    dir_ok = (np.sign(delta) == exp_sign)

    stat_pass = bool(p_fdr < ALPHA and abs(delta) >= EFFECT_MIN)
    rf_pass = bool(t["rank"] <= t.rank_cut and t.imp > 0)
    rp = repro(d, c)
    both = [rp["delta_original"], rp["delta_r1"]]
    # 재현성은 3값이다. '실패'와 '표본이 없어 검사 자체를 못 함'은 다르게 취급해야 한다.
    # Chipping은 원본 데이터에 pure 표본이 4건뿐이라 원본측 계산이 불가능하다.
    if any(pd.isna(x) for x in both):
        repro_state = "판정불가(원본 표본부족)"
    elif np.sign(both[0]) == np.sign(both[1]) == exp_sign:
        repro_state = "통과"
    else:
        repro_state = "실패(데이터셋간 방향 불일치)"
    repro_pass = repro_state == "통과"

    layer = LAYER[c]
    n_pass = int(stat_pass) + int(rf_pass)

    # --- 티어 규칙 (원인 트랙 / 감시지표 트랙 분리)
    if not dir_ok:
        tier, reason = "T4", "도메인 기대와 데이터 방향이 반대 — 판단 보류"
    elif layer == "Response":
        if n_pass == 2 and repro_pass:
            tier, reason = "M1", "방향일치 + 통계검정·RF 모두 통과 + 두 데이터셋 재현"
        elif n_pass >= 1:
            tier, reason = "M2", f"방향일치 + 2개 검정 중 {n_pass}개 통과 (재현 {'O' if repro_pass else 'X'})"
        else:
            tier, reason = "M3", "방향일치하나 통계검정·RF 모두 미달 — 사후 탐지용"
    else:
        if n_pass == 2 and repro_pass:
            tier, reason = "T1", "방향일치 + 통계검정·RF 모두 통과 + 두 데이터셋 재현"
        elif n_pass == 2 and repro_state.startswith("판정불가"):
            # 재현을 '못 한' 것이지 '실패한' 것이 아니다. 원본에 표본이 없어서다.
            tier = "T1"
            reason = (f"방향일치 + 통계검정·RF 모두 통과. 재현성은 원본 표본 부족"
                      f"(pure {rp['n_defect_original']}건)으로 판정불가 — 실패 아님")
        elif n_pass == 2:
            tier, reason = "T2", "방향일치 + 통계검정·RF 모두 통과, 단 두 데이터셋 방향 불일치"
        elif n_pass == 1:
            tier, reason = "T2", f"방향일치 + 2개 검정 중 1개만 통과 ({'통계검정' if stat_pass else 'RandomForest'})"
        else:
            tier, reason = "T3", "도메인 확정·방향일치하나 통계검정·RF 모두 미달 — 감시만"

    action = ACTION[tier]
    if watch == "trend":
        action = "추세알람(정비)" if tier in ("T1", "T2") else "추세감시"
    elif watch == "spike":
        action = "급락알람" if tier in ("T1", "T2") else "급락감시"

    rows.append(dict(
        tier=tier, defect=d, factor=c,
        role=("원인(FDC)" if layer == "FDC" else "감시지표(Response)"),
        action_type=action, watch_mode=watch,
        domain_direction=f"{c} {'감소' if exp_dir=='down' else '증가'} → {d} 증가",
        domain_evidence=ev,
        # --- 통계검정 (가시성)
        stat_pass=stat_pass, cliffs_delta=round(delta, 4),
        p_fdr=f"{p_fdr:.2e}", n_defect=int(u.n_defect), n_normal=int(u.n_normal),
        stat_method="Mann-Whitney U 양측검정 → Cliff's delta 환산, BH-FDR 다중비교 보정",
        stat_criterion=f"p_FDR < {ALPHA} AND |delta| >= {EFFECT_MIN}",
        # --- RandomForest (가시성)
        rf_pass=rf_pass, rf_importance=round(float(t.imp), 6),
        rf_importance_std=round(float(t.imp_std), 6),
        rf_rank=f"{int(t['rank'])}/{int(t.n_candidates)}",
        rf_criterion=f"상위 {RF_TOP_PCT:.0%}(={int(t.rank_cut)}위) 이내 AND 중요도 > 0",
        rf_method=RF_SPEC,
        # --- 재현성
        repro_pass=repro_pass, repro_state=repro_state, **rp,
        # --- 공통 근거
        comparison_group=LABEL_DEF, baseline=BASELINE_DEF,
        tier_reason=reason,
        # --- SOP (미수령)
        sop_action="", sop_check="", sop_status="SOP 미수령 — 멘토 제공 대기",
    ))
    rows[-1].update(alert_range(d, c, exp_dir))

tt = pd.DataFrame(rows)
# 경보 방향 자체 점검 — 위험구간의 불량률이 정상구간보다 낮으면 경보를 걸면 안 된다.
tt["alert_usable"] = tt.risk_ratio.fillna(0) > 1.0
tt.loc[~tt.alert_usable, "alert_warning"] = (
    "위험구간 불량률이 정상구간보다 낮음 — 이 경계값으로 경보를 걸면 안 됨")
tt["alert_warning"] = tt.alert_warning.fillna("")
order = {"T1": 0, "T2": 1, "T3": 2, "T4": 3, "M1": 4, "M2": 5, "M3": 6}
tt = tt.assign(_o=tt.tier.map(order)).sort_values(
    ["_o", "defect"], kind="stable").drop(columns="_o").reset_index(drop=True)
tt.to_csv(OUT / "rel_20_tier_table.csv", index=False, encoding="utf-8-sig")

# ==================================================================== 출력
print("[5/5] 완료\n")
W = 118
print("=" * W)
print(f"유효인자 티어표 — 확정 도메인 {len(DOMAIN)}건 × (통계검정 + RandomForest)")
print(f"※ Vibration {len(VIBRATION_EXCLUDED)}건은 제외 — 별도 알람 트랙(추세·spec 이탈)으로 운영")
print("=" * W)
print(f"{'티어':4s} {'defect':12s} {'인자':20s} {'액션':14s}"
      f" {'delta':>8s} {'통계':>4s} {'RF':>4s}  {'재현성':22s}")
print("-" * W)
for _, x in tt.iterrows():
    print(f"{x.tier:4s} {x.defect:12s} {x.factor:20s} {x.action_type:14s}"
          f" {x.cliffs_delta:>+8.3f} {'O' if x.stat_pass else 'X':>4s}"
          f" {'O' if x.rf_pass else 'X':>4s}  {x.repro_state:22s}")

print("\n" + "=" * W)
print("경보 임계값 — 어떤 값을 넘으면 울리는가 (실제 단위)")
print("=" * W)
print(f"{'defect':12s} {'인자':20s} {'정상 범위':>22s} {'위험 범위':>22s} {'불량률(정상→위험)':>22s}")
print("-" * W)
for _, x in tt.iterrows():
    if pd.isna(x.get("alert_threshold_raw")):
        continue
    mark = "" if x.alert_usable else "   ⚠ 경보 불가(방향 역전)"
    print(f"{x.defect:12s} {x.factor:20s} {str(x.normal_range_raw):>22s} "
          f"{str(x.risky_range_raw):>22s} "
          f"{x.rate_in_normal_pct:>8.2f}% → {x.rate_in_risky_pct:>6.2f}% ({x.risk_ratio}배){mark}")

print("\n" + "=" * W)
print(f"티어 분포: " + " · ".join(f"{k} {int((tt.tier==k).sum())}건"
                                for k in ["T1", "T2", "T3", "T4", "M1", "M2", "M3"]
                                if (tt.tier == k).sum()))
print(f"-> rel_20_tier_table.csv 저장 ({len(tt)}행 × {len(tt.columns)}열)")
print("=" * W)
