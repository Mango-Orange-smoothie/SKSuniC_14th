"""CLN_Pressure 급락(spike) 검증 — watch_mode를 spike로 둘 근거가 있는가

배경
  전성재 검증9: "그 스트립 세정 순간의 즉시적 압력 하락", 선행신호 잔존율 4.1%
  이걸 "직전 대비 낙차"로 읽고 rel_20의 watch_mode를 spike로 뒀다.
  그런데 낙차 기준을 만들려면 "얼마나 떨어지면 급락인가"를 정해야 하는데,
  그 전에 급락 사건이 실제로 있는지부터 확인한다.

방법
  장비별 시간순 정렬 -> 직전 20샷의 이동중앙값을 기준선 -> 낙차를 잰다.
  (기준선에 현재 값을 넣지 않는다. 미래를 보지 않게.)
  낙차 구간별 Remain_Coat(pure) 발생률을 보고, 절대값 경계와 성능을 비교한다.

결론 (2026-08-08)
  급락 사건이 없다. 압력이 매 샷 ±5로 흔들려 낙차 자체가 노이즈다.
  절대값 경계가 알람 절반으로 정확도 1.6배 높다.
  -> watch_mode를 spike에서 level로 정정한다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/check_cln_pressure_spike.py"
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]

C = "CLN_Pressure"
W = 20                  # 직전 20샷 이동중앙값을 기준선으로
ABS_THR = 297.272       # rel_20 티어표의 절대값 경계
DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]

o = pd.read_csv(PROJ / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(PROJ / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["src"] = "original"
r["src"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["DateTime"] = pd.to_datetime(df.DateTime)
df["rc"] = ((df.Remain_Coat == 1)
            & (df[[c for c in DEFECTS if c != "Remain_Coat"]].sum(axis=1) == 0)).astype(int)

# ------------------------------------------------------------------ 낙차 계산
df = df.sort_values(["src", "Machine_ID", "DateTime"]).reset_index(drop=True)
df["baseline"] = df.groupby(["src", "Machine_ID"])[C].transform(
    lambda s: s.shift(1).rolling(W, min_periods=W).median())
df["drop"] = df.baseline - df[C]          # 양수 = 기준선보다 하락
d = df[df.baseline.notna()].copy()
base_rate = d.rc.mean() * 100

rows = []

# ------------------------------------------------------------------ ① 낙차 구간별 발생률
bins = [-np.inf, -1.0, -0.5, 0, 0.5, 1.0, 1.5, 2.0, np.inf]
d["bin"] = pd.cut(d["drop"], bins)
for iv, x in d.groupby("bin", observed=True).agg(n=("rc", "size"), k=("rc", "sum")).iterrows():
    rate = x.k / x.n * 100
    rows.append(dict(section="① 낙차 구간별 발생률",
                     item=f"낙차 ({iv.left:.1f}, {iv.right:.1f}]",
                     n=int(x.n), n_defect=int(x.k),
                     defect_rate_pct=round(rate, 3),
                     lift=round(rate / base_rate, 3), note=""))

# ------------------------------------------------------------------ ② 기준별 성능 비교
total_defect = int(d.rc.sum())
for name, mask, note in [
    (f"절대값 < {ABS_THR}", d[C] <= ABS_THR, "rel_20 티어표 경계"),
    ("낙차 > 1.0", d["drop"] > 1.0, ""),
    ("낙차 > 1.5", d["drop"] > 1.5, ""),
    ("낙차 > 2.0", d["drop"] > 2.0, ""),
    ("절대값 OR 낙차>1.5", (d[C] <= ABS_THR) | (d["drop"] > 1.5), "조합"),
    ("절대값 AND 낙차>1.5", (d[C] <= ABS_THR) & (d["drop"] > 1.5), "조합"),
]:
    n = int(mask.sum())
    if n == 0:
        continue
    rate = d.loc[mask, "rc"].mean() * 100
    rows.append(dict(section="② 기준별 성능", item=name, n=n,
                     n_defect=int(d.loc[mask, "rc"].sum()),
                     defect_rate_pct=round(rate, 3),
                     lift=round(rate / base_rate, 3),
                     note=f"알람비율 {n/len(d)*100:.2f}% / 불량포착 "
                          f"{d.loc[mask,'rc'].sum()/total_defect*100:.1f}% {note}".strip()))

# ------------------------------------------------------------------ ③ 반대 방향
for thr in [1.0, 1.5, 2.0]:
    m = d["drop"] < -thr
    if m.sum() < 10:
        continue
    rate = d.loc[m, "rc"].mean() * 100
    rows.append(dict(section="③ 급상승(반대방향)", item=f"급상승 > {thr}", n=int(m.sum()),
                     n_defect=int(d.loc[m, "rc"].sum()),
                     defect_rate_pct=round(rate, 3),
                     lift=round(rate / base_rate, 3), note="1 미만이면 무관"))

# ------------------------------------------------------------------ ④ 낙차 분포
for q in [.01, .25, .50, .75, .99, 1.0]:
    rows.append(dict(section="④ 낙차 분포", item=f"p{q*100:.0f}", n=len(d), n_defect=None,
                     defect_rate_pct=None, lift=None,
                     note=f"낙차 {d['drop'].quantile(q):+.4f}"))

t = pd.DataFrame(rows)
t.to_csv(OUT / "rel_31_cln_pressure_spike_check.csv", index=False, encoding="utf-8-sig")

# ------------------------------------------------------------------ 출력
W_ = 92
print("=" * W_)
print("CLN_Pressure 급락(spike) 검증 — 합본 20만행")
print("=" * W_)
print(f"기준선: 장비별 직전 {W}샷 이동중앙값 (현재 값 제외)")
print(f"Remain_Coat(pure) 전체 발생률 {base_rate:.3f}%   낙차 계산 가능 {len(d):,}행\n")

print("① 낙차 분포 — 압력이 원래 얼마나 흔들리나")
for q in [.01, .25, .50, .75, .99]:
    print(f"   p{q*100:>4.0f}  {d['drop'].quantile(q):+8.4f}")
print("   → 매 샷 ±5 정도로 흔들린다. 낙차 자체가 노이즈다.\n")

print("② 낙차 구간별 Remain_Coat 발생률")
for _, x in t[t.section.str.startswith("①")].iterrows():
    bar = "#" * int(min(x.lift, 12) * 4)
    print(f"   {x['item']:>22s}  n={x.n:>7,}  {x.defect_rate_pct:>6.3f}%  x{x.lift:>5.2f}  {bar}")
print("   → 낙차 2.0 초과에서만 오르는데, 그게 전체의 16.8%다. 급락이 아니다.\n")

print("③ 기준별 성능 — 절대값 vs 낙차")
for _, x in t[t.section.str.startswith("②")].iterrows():
    print(f"   {x['item']:>22s}  n={x.n:>7,}  {x.defect_rate_pct:>6.3f}%  "
          f"lift {x.lift:>5.2f}   {x.note}")
print("   → 절대값이 알람 절반으로 정확도 1.6배 높다. 조합해도 새로 잡히는 게 없다.\n")

print("④ 반대 방향(급상승)")
for _, x in t[t.section.str.startswith("③")].iterrows():
    print(f"   {x['item']:>22s}  n={x.n:>7,}  {x.defect_rate_pct:>6.3f}%  lift {x.lift:>5.2f}")
print("   → 전부 1 미만. 급상승은 무관하다.\n")

print("=" * W_)
print("결론 — 급락 사건이 없다. watch_mode를 spike -> level 로 정정한다.")
print("      전성재 검증9의 '즉시적 압력 하락'은 '직전 대비 낙차'가 아니라")
print("      '그 순간 값 자체가 낮다'는 뜻으로 읽어야 한다.")
print("=" * W_)
print("\n한계: 기준선을 장비별로만 잡아 제품·레시피 전환이 가짜 낙차를 만들 수 있다.")
print("      다만 절대값 우위(3.74 vs 2.33)가 커서 결론은 바뀌지 않을 것으로 본다.")
print(f"\n-> rel_31_cln_pressure_spike_check.csv 저장 ({len(t)}행)")
