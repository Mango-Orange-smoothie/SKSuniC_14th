"""라벨만 바꿨을 때 **Cliff's delta와 통계검정 판정**이 어떻게 달라지는지 잰다.

check_label_grid.py가 경계값(risk_ratio/alert_usable) 축을 재는 데 비해, 이 스크립트는
티어를 실제로 정하는 축인 통계검정(Mann-Whitney U → Cliff's delta, BH-FDR)을 잰다.

  python3 docs/check_label_delta.py

**윤진혁님 build_tier_table.py의 전처리를 그대로 재사용한다** — 층별 기준선, 강건
z-score, 피처 목록, 정상군 정의를 우리가 다시 만들지 않고 build_relationship_db.py를
exec해서 같은 함수를 쓴다. 그래야 나온 숫자를 님 표와 직접 대조할 수 있고, 실제로
`pure` 쪽 delta가 rel_20_tier_table.csv와 소수점까지 일치한다(출력의 `DB` 열).

**RandomForest와 재현성(두 데이터셋 방향 일치)은 여기서 안 돌린다.** 그래서 이 결과로
최종 tier를 예측하면 안 된다 — tier는 통계검정 + RF + 재현성 셋을 다 봐야 정해진다.
여기서 말할 수 있는 건 "통계검정 축에서 무엇이 달라지는가"까지다.

자세한 해석은 JHdaimma_협의요청_라벨재실행.md 참고.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests

REPO = Path(__file__).resolve().parent.parent
DB_SRC = REPO / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/build_relationship_db.py"
TIER = REPO / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/rel_20_tier_table.csv"

# build_relationship_db.py의 "데이터" 섹션 앞부분(상수·함수 정의)만 가져온다.
# build_tier_table.py가 쓰는 것과 같은 수법이라 새 전처리를 만들지 않는다.
_src = DB_SRC.read_text(encoding="utf-8")
exec(_src.split("# ==================================================================== 데이터")[0])
ROOT = REPO  # exec가 덮어쓴 ROOT 복원 (build_tier_table.py도 같은 줄이 있다)

ALPHA = 0.05
EFFECT_MIN = 0.2        # build_tier_table.py와 같은 값
DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
# build_tier_table.py의 DOMAIN에서 (defect, factor, 기대방향)만 옮긴 것.
DOMAIN = [
    ("Particle", "Surface_Roughness", "up"), ("Particle", "CLN_Flow", "down"),
    ("Particle", "CLN_Pressure", "down"), ("Remain_Coat", "CLN_Pressure", "down"),
    ("Remain_Coat", "CLN_Flow", "down"), ("Micro_Crack", "Cooling_Flow", "down"),
    ("Micro_Crack", "Cooling_Water_Temp", "up"), ("Chipping", "Power_Efficiency", "down"),
    ("Chipping", "Laser_Power", "down"), ("Chipping", "Head_Temp", "up"),
    ("Chipping", "Cooling_Flow", "down"),
]


def cliffs_delta(a, b) -> tuple[float, float]:
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    u, p = sps.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


def deltas(df: pd.DataFrame, label: str) -> dict[str, pd.DataFrame]:
    out = {}
    for d in DEFECTS:
        others = [x for x in DEFECTS if x != d]
        y = (((df[d] == 1) & (df[others].sum(axis=1) == 0)).values if label == "pure"
             else (df[d] == 1).values)
        rows = [dict(factor=c, **dict(zip(("delta", "p_raw"),
                                          cliffs_delta(df.loc[y == 1, f"{c}_z"],
                                                       df.loc[y == 0, f"{c}_z"]))))
                for c in FEATURES]
        t = pd.DataFrame(rows)
        t["p_fdr"] = multipletests(t.p_raw, alpha=ALPHA, method="fdr_bh")[1]
        out[d] = t.set_index("factor")
    return out


def verdict(delta: float, p_fdr: float, expect: str) -> tuple[bool, bool]:
    """(방향 일치, 통계검정 통과) — build_tier_table.py의 dir_ok / stat_pass와 같은 식."""
    return (np.sign(delta) == (-1 if expect == "down" else +1),
            bool(p_fdr < ALPHA and abs(delta) >= EFFECT_MIN))


def main() -> None:
    o = pd.read_csv(REPO / "data/raw/DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
    r = pd.read_csv(REPO / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
    o["source_dataset"], r["source_dataset"] = "original", "r1"
    df = add_domain_features(pd.concat([o, r], ignore_index=True))
    df["is_normal"] = NORMAL(df)
    bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
    df = zscore(df, bl, OPCOND, FEATURES)

    pure, binary = deltas(df, "pure"), deltas(df, "binary")
    db = pd.read_csv(TIER, encoding="utf-8-sig").set_index(["defect", "factor"])

    print(f"{'불량 ↔ 인자':<36}{'DB':>9}{'pure':>9}{'이진':>9}   판정 (방향·통계검정)")
    print("-" * 92)
    for d, c, exp in DOMAIN:
        pu, bi = pure[d].loc[c], binary[d].loc[c]
        pdir, pstat = verdict(pu.delta, pu.p_fdr, exp)
        bdir, bstat = verdict(bi.delta, bi.p_fdr, exp)
        was = f"{'방향O' if pdir else '방향X'}·{'통과' if pstat else '미달'}"
        now = f"{'방향O' if bdir else '방향X'}·{'통과' if bstat else '미달'}"
        flag = "  <<< 바뀜" if (pdir, pstat) != (bdir, bstat) else ""
        print(f"{d + ' ↔ ' + c:<36}{db.loc[(d, c), 'cliffs_delta']:>9.4f}"
              f"{pu.delta:>9.4f}{bi.delta:>9.4f}   {was} -> {now}{flag}")

    print("\nDB = rel_20_tier_table.csv의 cliffs_delta. pure 열과 일치해야 이 재계산을 믿을 수 있다.")
    print(f"통계검정 통과 = p_fdr < {ALPHA} AND |delta| >= {EFFECT_MIN} (build_tier_table.py와 동일)")
    print("RandomForest·재현성은 안 돌렸다 — 최종 tier는 여기서 예측할 수 없다.")


if __name__ == "__main__":
    main()
