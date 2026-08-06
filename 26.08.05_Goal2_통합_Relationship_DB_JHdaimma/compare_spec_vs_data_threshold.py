"""멘토 공식 스펙 vs 데이터에서 찾은 위험 경계 — 간극 검증

질문
  멘토가 준 규격(LSL/USL)대로 검사하면 잡히지 않는 불량이 있는가?

방법
  1. 각 인자마다 데이터에서 위험 경계를 찾는다 (rel_20_tier_table.csv의 값 사용,
     DecisionTree stump가 불량률이 가장 크게 갈리는 지점을 찾은 값)
  2. 그 위험 구간에 속한 행 중 '규격상으로는 정상'인 비율을 센다
  3. 그 구간의 실제 불량률을 낸다

스펙 출처
  origin/김시우 pipeline/spec.py — "멘토가 직접 제공한 공식 스펙(USL/LSL/TARGET). 26.08.05 수령"
  이 스크립트는 pipeline/을 수정하지 않고 값만 읽어 쓴다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/compare_spec_vs_data_threshold.py"
"""
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]

# 멘토 공식 스펙 (origin/김시우 pipeline/spec.py, 26.08.05 수령)
SPEC = {
    "Laser_Power": (17.8, 18.5, 19.2),
    "Power_Efficiency": (92, 95, 98),
    "Laser_Centering_Position": (-3, 0, 3),
    "Frequency": (98, 100, 102),
    "Feed_Speed": (248, 250, 252),
    "Head_Temp": (38, 42, 47),
    "Focus": (-4, 0, 4),
    "Kerf_Width_Profile": (49.2, 50, 50.8),
    "Coating_Thickness": (9.5, 10, 10.5),
    "Coating_Uniformity": (97, 99, 100),
}
DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]

tier = pd.read_csv(OUT / "rel_20_tier_table.csv", encoding="utf-8-sig")
o = pd.read_csv(PROJ / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(PROJ / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
df = pd.concat([o, r], ignore_index=True)

rows = []
for _, x in tier.iterrows():
    c = x.factor
    if c not in SPEC:
        continue
    lsl, tgt, usl = SPEC[c]
    thr = x.alert_threshold_raw
    down = "감소" in x.domain_direction     # 값이 낮아질 때 위험한가

    risky = df[c] <= thr if down else df[c] > thr
    in_spec = (df[c] >= lsl) & (df[c] <= usl)
    both = risky & in_spec                  # 위험구간인데 규격은 정상

    others = [z for z in DEFECTS if z != x.defect]
    pure = (df[x.defect] == 1) & (df[others].sum(axis=1) == 0)

    rows.append(dict(
        defect=x.defect, factor=c, tier=x.tier,
        spec_LSL=lsl, spec_TARGET=tgt, spec_USL=usl,
        data_threshold=thr,
        risky_side=("낮을수록 위험" if down else "높을수록 위험"),
        # 스펙 경계와 데이터 경계 사이의 간극 (규격 내인데 위험한 폭)
        gap_from_spec=round(thr - lsl if down else usl - thr, 3),
        n_risky=int(risky.sum()),
        n_risky_but_in_spec=int(both.sum()),
        pct_risky_in_spec=round(both.sum() / risky.sum() * 100, 2) if risky.sum() else None,
        defect_rate_in_gap_pct=round(pure[both].mean() * 100, 3) if both.sum() else None,
        defect_rate_overall_pct=round(pure.mean() * 100, 3),
        spec_source="멘토 제공 공식 스펙 (26.08.05, 김시우 pipeline/spec.py)",
        threshold_source="DecisionTree stump(깊이1)로 불량률이 가장 크게 갈리는 지점 탐색",
    ))

t = pd.DataFrame(rows).sort_values("defect_rate_in_gap_pct", ascending=False).reset_index(drop=True)
t.to_csv(OUT / "rel_27_spec_vs_data_threshold.csv", index=False, encoding="utf-8-sig")

W = 106
print("=" * W)
print("멘토 공식 스펙 vs 데이터가 말하는 위험선")
print("=" * W)
print(f"{'인자':24s} {'LSL':>7s} {'TARGET':>7s} {'USL':>7s} {'데이터경계':>10s} {'간극':>8s}  방향")
print("-" * W)
for _, x in t.iterrows():
    print(f"{x.factor:24s} {x.spec_LSL:>7.1f} {x.spec_TARGET:>7.1f} {x.spec_USL:>7.1f}"
          f" {x.data_threshold:>10.3f} {x.gap_from_spec:>8.2f}  {x.risky_side}")

print("\n" + "=" * W)
print("규격은 정상인데 위험 구간에 있는 제품")
print("=" * W)
for _, x in t.iterrows():
    print(f"{x.factor:24s} 위험구간 {x.n_risky:>7,}행 중 규격내 {x.n_risky_but_in_spec:>7,}행"
          f" ({x.pct_risky_in_spec:>5.1f}%)  →  {x.defect} 불량률 {x.defect_rate_in_gap_pct:>6.2f}%"
          f"  (전체 평균 {x.defect_rate_overall_pct:.2f}%)")

print("\n" + "=" * W)
print("해석 — 규격 검사만으로는 이 구간의 불량을 잡을 수 없다.")
print("      단, 이 데이터는 멘토가 시나리오를 주입해 만든 것이므로")
print("      실제 라인에서도 같은 간극이 있는지는 별도 확인이 필요하다.")
print("=" * W)
print(f"-> rel_27_spec_vs_data_threshold.csv 저장 ({len(t)}행)")
