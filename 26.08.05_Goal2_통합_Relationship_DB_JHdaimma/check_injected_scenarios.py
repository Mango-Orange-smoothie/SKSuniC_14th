"""주입 시나리오 역추적 — '검정력 부족'과 '진짜 반박'을 구분한다

배경
  이 데이터셋은 멘토가 상황을 일부러 설정해 만든 것이다.
  주입되지 않은 시나리오는 아무리 분석해도 신호가 안 나온다.
  따라서 '데이터가 도메인을 반박했다'와 '그 상황이 데이터에 없다'는 전혀 다르다.

방법
  각 인자가 실제로 얼마나 흔들리는지를 본다.
  고장/실패 수준의 이탈이 존재하지 않는 인자는 애초에 검정이 불가능하다.

  지표
    range_ratio   (최대-최소) / 중앙값 — 전체 변동 폭
    p99_p1_z      z 기준 1~99 백분위 폭 — 꼬리를 뺀 실질 변동 폭
    pct_z_gt3     |z| > 3 인 비율 — 극단 이탈(고장 수준)이 얼마나 있나
    r1_shift      원본 대비 r1에서 중앙값이 얼마나 이동했나 (주입 흔적)

  판정
    변동 자체가 거의 없다        -> 검정불가(시나리오 미주입 의심)
    변동은 있는데 신호가 없다    -> 검정했으나 무관
    r1에서 뚜렷이 이동했다       -> 주입된 시나리오로 추정

실행 (저장소 루트에서):
  python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/check_injected_scenarios.py"
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[1]
SRC = PROJ / "SKSuniC_14th" / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"

src = open(SRC / "build_relationship_db.py", encoding="utf-8").read()
exec(src.split("# ==================================================================== 데이터")[0])
ROOT = PROJ

o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)

# 티어표에 실린 확정 도메인 인자 + Vibration(외부 담당)
WATCH = ["Power_Efficiency", "Laser_Power", "Head_Temp", "Cooling_Flow",
         "Cooling_Water_Temp", "CLN_Flow", "CLN_Pressure", "Surface_Roughness",
         "Vibration"]

rows = []
for c in FEATURES:
    z = df[f"{c}_z"].dropna()
    raw = df[c].dropna()
    med = raw.median()
    ro = o[c].median() if c in o.columns else np.nan
    r1 = r[c].median() if c in r.columns else np.nan
    # r1에서 중앙값이 원본 대비 몇 % 이동했나 (주입 흔적)
    shift = (r1 - ro) / abs(ro) * 100 if pd.notna(ro) and ro != 0 else np.nan
    rows.append(dict(
        factor=c,
        raw_min=round(raw.min(), 3), raw_max=round(raw.max(), 3),
        raw_median=round(med, 3),
        range_ratio_pct=round((raw.max() - raw.min()) / abs(med) * 100, 2) if med else np.nan,
        p1_p99_z=round(z.quantile(.99) - z.quantile(.01), 2),
        pct_z_gt3=round((z.abs() > 3).mean() * 100, 3),
        pct_z_gt5=round((z.abs() > 5).mean() * 100, 4),
        median_original=round(ro, 3) if pd.notna(ro) else None,
        median_r1=round(r1, 3) if pd.notna(r1) else None,
        r1_shift_pct=round(shift, 3) if pd.notna(shift) else None,
        in_tier_table=c in WATCH,
    ))

t = pd.DataFrame(rows)


def verdict(x):
    """변동이 없으면 애초에 검정이 성립하지 않는다."""
    if x.pct_z_gt3 < 0.05:
        return "검정불가(극단 이탈 거의 없음 — 시나리오 미주입 의심)"
    if x.pct_z_gt3 < 0.5:
        return "검정력 낮음(극단 이탈 희소)"
    return "검정 가능(이탈 충분)"


t["testability"] = t.apply(verdict, axis=1)
t = t.sort_values("pct_z_gt3", ascending=False).reset_index(drop=True)
t.to_csv(OUT / "rel_26_scenario_injection_check.csv", index=False, encoding="utf-8-sig")

W = 118
print("=" * W)
print("주입 시나리오 역추적 — 어떤 인자에 '고장 수준' 이탈이 실제로 존재하는가")
print("=" * W)
print("멘토가 상황을 설정해 만든 데이터이므로, 주입되지 않은 시나리오는 검정 자체가 불가능하다.")
print()
print(f"{'인자':24s} {'실제값 범위':>22s} {'폭%':>7s} {'|z|>3':>7s} {'|z|>5':>7s} {'r1이동%':>8s}  판정")
print("-" * W)
for _, x in t.iterrows():
    mark = "★" if x.in_tier_table else " "
    rng = f"{x.raw_min:.2f}~{x.raw_max:.2f}"
    sh = f"{x.r1_shift_pct:+.2f}" if pd.notna(x.r1_shift_pct) else "    -"
    print(f"{mark}{x.factor:23s} {rng:>22s} {x.range_ratio_pct:>7.1f} "
          f"{x.pct_z_gt3:>6.3f}% {x.pct_z_gt5:>6.3f}% {sh:>8s}  {x.testability}")

print("\n" + "=" * W)
print("★ = 티어표에 실린 확정 도메인 인자")
print("=" * W)

print("\n[티어표 인자만 다시 — 검정 가능성 판정]")
w = t[t.in_tier_table]
for _, x in w.iterrows():
    print(f"  {x.factor:22s} |z|>3 {x.pct_z_gt3:>6.3f}%   {x.testability}")

print("\n" + "=" * W)
print("r1에서 중앙값이 크게 이동한 인자 상위 10 — 주입된 시나리오로 추정")
print("=" * W)
s = t.dropna(subset=["r1_shift_pct"]).reindex(
    t.dropna(subset=["r1_shift_pct"]).r1_shift_pct.abs().sort_values(ascending=False).index)
for _, x in s.head(10).iterrows():
    mark = "★" if x.in_tier_table else " "
    print(f"{mark}{x.factor:23s} 원본 {x.median_original:>10.3f}  ->  r1 {x.median_r1:>10.3f}"
          f"   ({x.r1_shift_pct:+.3f}%)")

print(f"\n-> rel_26_scenario_injection_check.csv 저장 ({len(t)}행)")
