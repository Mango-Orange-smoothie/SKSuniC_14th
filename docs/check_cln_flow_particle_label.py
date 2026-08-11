"""CLN_Flow↔Particle 경계가 역전된 원인이 라벨 정의임을 재현한다.

관계DB의 경계값(rel_20_tier_table.csv)을 그대로 쓰고 **라벨만** 바꿔서 위험구간/정상구간
파티클률을 다시 센다. 경계값을 우리가 다시 학습하지 않는다 — 판정 기준은 DB 것 그대로다.

  python3 docs/check_cln_flow_particle_label.py

자세한 해석은 docs/검증_CLNFlow_Particle_경계가_사라진_이유.md 참고.
"""

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data/raw/DP_HealthIndex_Dataset.csv"
TIER = REPO / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/rel_20_tier_table.csv"

DEFECTS = ["Chipping", "Remain_Coat", "Particle", "Micro_Crack"]
FACTOR, DEFECT = "CLN_Flow", "Particle"


def main() -> None:
    tier = pd.read_csv(TIER, encoding="utf-8-sig")
    row = tier[(tier.factor == FACTOR) & (tier.defect == DEFECT)]
    if row.empty:
        raise SystemExit(f"티어표에 {FACTOR}↔{DEFECT} 행이 없습니다.")
    row = row.iloc[0]
    thr = float(row["alert_threshold_raw"])

    d = pd.read_csv(RAW, low_memory=False)
    others = [c for c in DEFECTS if c != DEFECT]
    # 경계 방향은 티어표의 risky_range로 판단한다(우리가 정하지 않는다).
    lo = float(str(row["risky_range_raw"]).split("~")[0])
    risky = d[FACTOR] <= thr if lo < thr else d[FACTOR] >= thr

    print(f"{FACTOR}↔{DEFECT}  경계값 {thr}  (DB 표기 risk_ratio {row['risk_ratio']})")
    print(f"비교군: {row['comparison_group']}\n")

    labels = {
        "pure  (다른 불량 0개인 샷만 셈 — 현재 DB)": (d[DEFECT] == 1) & (d[others].sum(axis=1) == 0),
        "이진  (해당 불량 컬럼이 1이면 전부)": d[DEFECT] == 1,
    }
    print(f"{'라벨':<42}{'위험구간':>10}{'정상구간':>10}{'배수':>9}")
    for name, y in labels.items():
        a, b = y[risky].mean() * 100, y[~risky].mean() * 100
        ratio = f"{a / b:.2f}배" if b else "inf"
        print(f"{name:<42}{a:>9.2f}%{b:>9.2f}%{ratio:>9}")
    print(f"\n위험구간 {int(risky.sum()):,}샷 / 정상구간 {int((~risky).sum()):,}샷")

    inr = d[risky]
    p = inr[inr[DEFECT] == 1]
    both = int((p[others].sum(axis=1) > 0).sum())
    print(f"\n위험구간 안의 {DEFECT} 샷 {len(p):,}")
    print(f"  다른 불량 동반  {both:,} ({both / len(p) * 100:.0f}%)  <- pure 라벨이 버리는 것")
    print(f"  단독           {len(p) - both:,}")
    for o in others:
        n = int((p[o] == 1).sum())
        if n:
            print(f"    └ {o} 동반: {n:,}")


if __name__ == "__main__":
    main()
