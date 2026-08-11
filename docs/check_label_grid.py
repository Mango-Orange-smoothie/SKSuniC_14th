"""`pure` 라벨이 **어느 짝을 얼마나 가렸는지**를 관계DB 11개 짝 전부에 대해 잰다.

check_cln_flow_particle_label.py가 CLN_Flow↔Particle 하나에 대해 하는 일을 티어표
전체(rel_20_tier_table.csv, 멘토 확정 11개 짝)로 넓힌 것이다. 경계값은 DB 것 그대로
쓰고 **라벨만** 바꾼다 — 우리가 경계를 다시 학습하지 않는다.

  python3 docs/check_label_grid.py

두 데이터셋을 따로 잰다. 합치면 안 되는 이유: 원본 10만 행에는 Chipping이 4건,
Micro_Crack이 41건뿐이라 그 짝들의 비율이 의미가 없다. r1이 그 불량들이 실제로 들어
있는 쪽이다. 또 티어표가 `n_risky_original`/`n_risky_r1`을 데이터셋별로 갖고 있어서,
따로 재야 "내가 DB와 같은 위험구간을 보고 있나"를 매 줄에서 대조할 수 있다.

자세한 해석은 docs/검증_라벨정의가_가린_짝_전수조사.md 참고.
"""

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
TIER = REPO / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/rel_20_tier_table.csv"
DATASETS = {
    "original": (REPO / "data/raw/DP_HealthIndex_Dataset.csv", "n_risky_original"),
    "r1": (REPO / "DP_HealthIndex_Dataset_r1.csv", "n_risky_r1"),
}
DEFECTS = ["Chipping", "Remain_Coat", "Particle", "Micro_Crack"]


def risky_mask(d: pd.DataFrame, row: pd.Series) -> pd.Series:
    """DB의 경계값과 위험구간 방향을 그대로 적용한다(방향을 우리가 정하지 않는다)."""
    thr = float(row["alert_threshold_raw"])
    lo = float(str(row["risky_range_raw"]).split("~")[0])
    return d[row["factor"]] <= thr if lo < thr else d[row["factor"]] >= thr


def measure(d: pd.DataFrame, row: pd.Series) -> dict:
    defect = row["defect"]
    others = [c for c in DEFECTS if c != defect]
    risky = risky_mask(d, row)
    co_occurring = d[others].sum(axis=1) > 0
    y = d[defect] == 1

    def ratio(mask: pd.Series) -> float | None:
        a, b = y[mask & risky], y[mask & ~risky]
        if not len(a) or not len(b) or b.mean() == 0:
            return None
        return round(a.mean() / b.mean(), 2)

    n_defect_risky = int((y & risky).sum())
    return {
        "n_risky": int(risky.sum()),
        # pure: 다른 불량이 같이 난 행을 비교군·불량군 **양쪽에서** 뺀다(DB의 정의).
        "pure": ratio(~co_occurring),
        # 이진: 그 불량 컬럼이 1이면 전부 센다.
        "binary": ratio(pd.Series(True, index=d.index)),
        "n_defect_risky": n_defect_risky,
        "co_pct": (round(int((y & risky & co_occurring).sum()) / n_defect_risky * 100)
                   if n_defect_risky else None),
    }


def main() -> None:
    tier = pd.read_csv(TIER, encoding="utf-8-sig")
    # 한 인자가 여러 defect를 가지면 그게 pure 라벨이 깎는 대상이다 — 표시해준다.
    multi = {f for f, n in tier.groupby("factor").size().items() if n > 1}

    for name, (path, db_col) in DATASETS.items():
        d = pd.read_csv(path, low_memory=False)
        print(f"\n{'='*84}\n{name} ({len(d):,}행)  ·  불량 "
              + ", ".join(f"{c} {int(d[c].sum()):,}" for c in DEFECTS))
        print(f"{'='*84}")
        print(f"{'tier':<5}{'인자 ↔ 불량':<36}{'위험구간':>9}{'':2}"
              f"{'pure배':>9}{'이진배':>9}{'동반%':>7}")
        drift = []
        for _, r in tier.iterrows():
            m = measure(d, r)
            # 내가 DB와 같은 위험구간을 보고 있나. 어긋나면 아래 숫자를 믿으면 안 된다.
            same = "  " if m["n_risky"] == int(r[db_col]) else " ≠"
            if same == " ≠":
                drift.append(f"{r['factor']}↔{r['defect']} 내 {m['n_risky']:,} / DB {int(r[db_col]):,}")
            mark = "*" if r["factor"] in multi else " "
            cells = [f"{v:>9.2f}" if v is not None else f"{'—':>9}"
                     for v in (m["pure"], m["binary"])]
            co = f"{m['co_pct']:>7}" if m["co_pct"] is not None else f"{'—':>7}"
            print(f"{r['tier']:<5}{mark}{r['factor'] + ' ↔ ' + r['defect']:<35}"
                  f"{m['n_risky']:>9,}{same}{cells[0]}{cells[1]}{co}")
        if drift:
            # 경계값을 z가 아니라 대표 raw값으로 적용해서 생기는 반올림 차이다(전부 0.3% 미만).
            print("  ≠ 위험구간 샷 수가 DB와 다른 줄 — " + " · ".join(drift))

    print("\n* = 그 인자가 티어표에 defect를 2개 이상 갖고 있다 — pure 라벨이 깎는 대상")
    print("동반% = 위험구간 안의 그 불량 샷 중 다른 불량이 같이 난 비율(= pure가 버리는 몫)")
    print("배수 1.0 미만 = 위험구간이 정상구간보다 덜 난다(역전) -> alert_usable=False")


if __name__ == "__main__":
    main()
