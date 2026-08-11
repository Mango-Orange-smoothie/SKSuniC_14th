"""Cooling Failure 2개 컬럼 -> Micro_Crack 경향성 (1:1 대응)

전제 — 멘토 확정 도메인 지식:
  Cooling Failure -> Micro_Crack 증가
  Cooling Failure를 나타내는 컬럼: Cooling_Water_Temp, Cooling_Flow

기대 방향
  Cooling_Flow       낮아지면(↓) Micro_Crack 증가   -> 음의 경향
  Cooling_Water_Temp 높아지면(↑) Micro_Crack 증가   -> 양의 경향

이 스크립트는 판정하지 않는다. 두 인자와 Micro_Crack의 경향성만
1:1로 나란히 보여준다. 효과가 안 나와도 그대로 싣는다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/cooling_trend_micro_crack.py"
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]
SRC = PROJ / "SKSuniC_14th" / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"

src = open(SRC / "build_relationship_db.py", encoding="utf-8").read()
exec(src.split("# ==================================================================== 데이터")[0])
ROOT = PROJ  # exec가 덮어쓴 ROOT 복원

o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["src"] = "original"
r["src"] = "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)

ALL_DEF = ["Chipping", "Particle", "Remain_Coat", "Micro_Crack"]
others = [c for c in ALL_DEF if c != "Micro_Crack"]
# pure = 다른 불량이 섞이지 않은 순수 Micro_Crack (경향성을 흐리지 않으려고)
df["mc"] = ((df["Micro_Crack"] == 1) & (df[others].sum(axis=1) == 0)).astype(int)

COOLING = {
    "Cooling_Flow": ("낮을수록 위험", "down"),
    "Cooling_Water_Temp": ("높을수록 위험", "up"),
}
BASE = df.mc.mean() * 100
rows = []

print("=" * 100)
print("Cooling Failure 2개 컬럼 -> Micro_Crack 경향성")
print("=" * 100)
print(f"전제: 멘토 확정 — Cooling Failure -> Micro_Crack 증가")
print(f"Micro_Crack(pure) 전체 발생률 {BASE:.3f}%  ({int(df.mc.sum()):,}건 / {len(df):,}행)")

for col, (hyp, direction) in COOLING.items():
    z = f"{col}_z"
    print("\n" + "#" * 100)
    print(f"# {col}   —   도메인 기대: {hyp}")
    print("#" * 100)

    d = df[df[z].notna()].copy()

    # ---------------- 구간별 발생률 (10분위)
    d["q"] = pd.qcut(d[z], 10, labels=False, duplicates="drop")
    g = d.groupby("q").agg(z_min=(z, "min"), z_max=(z, "max"),
                           raw_med=(col, "median"),
                           n=("mc", "size"), defect=("mc", "sum"))
    g["rate_pct"] = g.defect / g.n * 100
    g["lift"] = g.rate_pct / BASE

    print(f"\n  10분위 구간별 Micro_Crack 발생률")
    print(f"  {'분위':>4s} {'z범위':>18s} {'실제값(중앙)':>12s} {'n':>8s} {'불량':>6s} {'발생률':>8s} {'배수':>6s}  그래프")
    print("  " + "-" * 96)
    for q, rr in g.iterrows():
        bar = "*" * int(round(rr.lift * 20))
        print(f"  {int(q)+1:>4d} [{rr.z_min:>+6.2f},{rr.z_max:>+6.2f}] {rr.raw_med:>12.2f}"
              f" {int(rr.n):>8,} {int(rr.defect):>6,} {rr.rate_pct:>7.3f}% {rr.lift:>6.2f}  {bar}")
        rows.append(dict(factor=col, domain_expectation=hyp, decile=int(q) + 1,
                         z_min=round(rr.z_min, 3), z_max=round(rr.z_max, 3),
                         raw_median=round(rr.raw_med, 3), n=int(rr.n),
                         n_micro_crack=int(rr.defect),
                         micro_crack_rate_pct=round(rr.rate_pct, 4),
                         lift_vs_overall=round(rr.lift, 3)))

    # ---------------- 경향성 지표
    rho, p_rho = stats.spearmanr(d[z], d.mc)
    a = d.loc[d.mc == 1, z].values
    b = d.loc[d.mc == 0, z].values
    ranks = pd.Series(np.concatenate([a, b])).rank().values
    u = ranks[:len(a)].sum() - len(a) * (len(a) + 1) / 2
    delta = 2 * u / (len(a) * len(b)) - 1
    lo, hi = g.rate_pct.iloc[0], g.rate_pct.iloc[-1]

    exp_sign = -1 if direction == "down" else +1
    match = "도메인 기대와 같은 방향" if np.sign(delta) == exp_sign else "도메인 기대와 반대 방향"
    if abs(delta) < 0.02:
        match += " (다만 크기가 거의 0)"

    print(f"\n  경향성 요약")
    print(f"    Spearman 상관     {rho:+.4f}  (p={p_rho:.2e})   ← 단조 경향의 세기")
    print(f"    Cliff's delta     {delta:+.4f}                  ← 불량군이 정상군보다 큰가")
    print(f"    최저분위 발생률    {lo:.3f}%")
    print(f"    최고분위 발생률    {hi:.3f}%   (차이 {hi-lo:+.3f}%p)")
    print(f"    방향 판정         {match}")

    # ---------------- 층화 (데이터셋 / 장비)
    print(f"\n  층화 — 같은 경향이 유지되는가")
    print(f"    {'구분':16s} {'n':>9s} {'Cliff delta':>12s} {'최저분위%':>10s} {'최고분위%':>10s}")
    print("    " + "-" * 62)
    for lab, sub in ([("전체", d)]
                     + [(f"데이터셋 {s}", d[d.src == s]) for s in ["original", "r1"]]
                     + [(f"장비 {m}", d[d.Machine_ID == m]) for m in sorted(d.Machine_ID.dropna().unique())]):
        if sub.mc.sum() < 5:
            print(f"    {lab:16s} {len(sub):>9,} {'표본부족':>12s}")
            continue
        aa = sub.loc[sub.mc == 1, z].values
        bb = sub.loc[sub.mc == 0, z].values
        rk = pd.Series(np.concatenate([aa, bb])).rank().values
        uu = rk[:len(aa)].sum() - len(aa) * (len(aa) + 1) / 2
        dd = 2 * uu / (len(aa) * len(bb)) - 1
        sub = sub.copy()
        sub["q"] = pd.qcut(sub[z], 10, labels=False, duplicates="drop")
        gg = sub.groupby("q").mc.mean() * 100
        print(f"    {lab:16s} {len(sub):>9,} {dd:>+12.4f} {gg.iloc[0]:>9.3f}% {gg.iloc[-1]:>9.3f}%")

pd.DataFrame(rows).to_csv(OUT / "rel_14_cooling_trend_micro_crack.csv",
                          index=False, encoding="utf-8-sig")
print("\n" + "=" * 100)
print(f"-> rel_14_cooling_trend_micro_crack.csv 저장 ({len(rows)}행)")
print("=" * 100)
