"""Laser Aging / Cooling Failure -> Chipping 경향성 (인자별 1:1)

전제 — 멘토 확정 도메인 지식:
  (Laser Aging)     -> Chipping 증가
  (Cooling Failure) -> Chipping 증가
  Laser Aging ↓     -> Chipping 증가   (레이저 성능이 떨어질수록 Chipping)

그룹 정의는 김시우님 subsystem 분류를 따른다.
  Laser Aging    = subsystem fdc_laser  + Laser_Head_Remain_Time(헤드 잔여수명)
  Cooling Failure = Cooling_Flow, Cooling_Water_Temp (사용자 지정)
  Head_Temp는 두 그룹 어디에도 단정하지 않고 따로 본다
    — 멘토 인과사슬은 Head_Temp -> 굴절률 -> 센터링 -> Chipping 이고,
      헤드 온도 상승은 냉각 문제일 수도 레이저 노후일 수도 있어 귀속이 미확정이다.

각 인자마다 '값이 오르면 Chipping이 오르는가 내리는가'만 본다. 판정하지 않는다.

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/aging_cooling_trend_chipping.py"
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
others = [c for c in ALL_DEF if c != "Chipping"]
# pure = 다른 불량이 섞이지 않은 순수 Chipping
df["chip"] = ((df["Chipping"] == 1) & (df[others].sum(axis=1) == 0)).astype(int)
BASE = df.chip.mean() * 100

GROUPS = {
    "Laser Aging (레이저 노후·성능저하)": [
        ("Laser_Power", "레이저 출력"),
        ("Power_Efficiency", "레이저 효율"),
        ("Laser_Current", "레이저 전류"),
        ("Laser_Voltage", "레이저 전압"),
        ("Frequency", "펄스 주파수"),
        ("Beam_Diameter", "빔 직경"),
        ("Laser_Centering_Position", "빔 센터링 위치"),
        ("Laser_Head_Remain_Time", "헤드 잔여수명"),
    ],
    "Cooling Failure (냉각 실패)": [
        ("Cooling_Flow", "냉각수 유량"),
        ("Cooling_Water_Temp", "냉각수 온도"),
        ("Cooling_Thermal_Load", "열부하(파생: 수온/유량)"),
    ],
    "귀속 미확정": [
        ("Head_Temp", "헤드 온도 — 멘토 인과사슬 시작점. 냉각/레이저 어느 쪽인지 미확정"),
    ],
}

rows = []
print("=" * 104)
print("Laser Aging / Cooling Failure -> Chipping 경향성")
print("=" * 104)
print("전제: 멘토 확정 — (Laser Aging) -> Chipping 증가 / (Cooling Failure) -> Chipping 증가")
print(f"Chipping(pure) 전체 발생률 {BASE:.3f}%  ({int(df.chip.sum()):,}건 / {len(df):,}행)")
print("\n※ 원본 데이터는 Chipping이 4건뿐이라 경향 산출이 불가능하다. 아래는 통합(원본+r1) 기준이다.")


def trend(col: str) -> dict | None:
    z = f"{col}_z"
    if z not in df.columns:
        return None
    d = df[df[z].notna()].copy()
    d["q"] = pd.qcut(d[z], 10, labels=False, duplicates="drop")
    g = d.groupby("q").agg(raw=(col, "median"), n=("chip", "size"), k=("chip", "sum"))
    g["rate"] = g.k / g.n * 100

    rho, p_rho = stats.spearmanr(d[z], d.chip)
    a = d.loc[d.chip == 1, z].values
    b = d.loc[d.chip == 0, z].values
    rk = pd.Series(np.concatenate([a, b])).rank().values
    u = rk[:len(a)].sum() - len(a) * (len(a) + 1) / 2
    delta = 2 * u / (len(a) * len(b)) - 1
    return dict(col=col, g=g, rho=rho, p=p_rho, delta=delta,
                lo=g.rate.iloc[0], hi=g.rate.iloc[-1],
                raw_lo=g.raw.iloc[0], raw_hi=g.raw.iloc[-1])


for gname, cols in GROUPS.items():
    print("\n" + "#" * 104)
    print(f"# {gname}")
    print("#" * 104)
    for col, desc in cols:
        t = trend(col)
        if t is None:
            print(f"\n  {col} — 컬럼 없음")
            continue
        d_, g = t["delta"], t["g"]
        # 값이 오르면 Chipping은?
        if abs(d_) < 0.05:
            arrow = "경향 없음 (거의 평평)"
        elif d_ > 0:
            arrow = "값 ↑ 이면 Chipping ↑"
        else:
            arrow = "값 ↓ 이면 Chipping ↑"
        print(f"\n  ── {col}  ({desc})")
        print(f"     {arrow}     Cliff's delta {d_:+.4f}   Spearman {t['rho']:+.4f} (p={t['p']:.1e})")
        print(f"     최저분위 {t['lo']:6.3f}%  (실제값 {t['raw_lo']:.3f})"
              f"   →   최고분위 {t['hi']:6.3f}%  (실제값 {t['raw_hi']:.3f})"
              f"   차이 {t['hi']-t['lo']:+.2f}%p")
        bars = "".join(f"{g.rate.iloc[i]/BASE:5.2f}" for i in range(len(g)))
        print(f"     분위별 배수(1→10): {bars}")
        rows.append(dict(group=gname.split(" (")[0], factor=col, description=desc,
                         cliffs_delta=round(d_, 4), spearman=round(t["rho"], 4),
                         p_spearman=t["p"],
                         rate_lowest_decile_pct=round(t["lo"], 4),
                         rate_highest_decile_pct=round(t["hi"], 4),
                         raw_median_lowest=round(t["raw_lo"], 4),
                         raw_median_highest=round(t["raw_hi"], 4),
                         direction=arrow))

# ------------------------------------------------------------------ 그룹 요약
print("\n" + "=" * 104)
print("요약 — 어떤 인자의 증/감이 Chipping을 올리는가 (Cliff's delta 절대값 순)")
print("=" * 104)
res = pd.DataFrame(rows).sort_values("cliffs_delta", key=lambda s: s.abs(), ascending=False)
print(f"{'그룹':16s} {'인자':26s} {'delta':>9s} {'최저분위%':>10s} {'최고분위%':>10s}  방향")
print("-" * 104)
for _, r_ in res.iterrows():
    print(f"{r_.group:16s} {r_.factor:26s} {r_.cliffs_delta:>+9.4f}"
          f" {r_.rate_lowest_decile_pct:>9.3f}% {r_.rate_highest_decile_pct:>9.3f}%  {r_.direction}")

res.to_csv(OUT / "rel_15_aging_cooling_trend_chipping.csv", index=False, encoding="utf-8-sig")
print("\n" + "=" * 104)
print(f"-> rel_15_aging_cooling_trend_chipping.csv 저장 ({len(res)}행)")
print("=" * 104)
