"""팀 Goal2 규약(NG_Code 주라벨) 적용 시 내 결과가 어떻게 바뀌는가

팀 규약 (26.07.31_2058_Goal2_PARTICLE_후속검증)
  - 주 라벨 : NG_Code == 'PARTICLE'  (= Particle==1 AND Remain_Coat==0)
  - 정상군  : NG_Code == 'OK'        (다른 불량 섞지 않음)
  - 보조 라벨 Particle==1 은 REM_COAT 오염 있음
"""
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from common import load, FDC, ROOT

warnings.filterwarnings("ignore")
pd.set_option("display.width", 240)
OUT = ROOT / "out" / "labelcheck"
OUT.mkdir(parents=True, exist_ok=True)

DS = {"원본": load("base"), "R1": load("r1")}


def cliff(a, b):
    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    return 2 * (u.statistic / (len(a) * len(b))) - 1, u.pvalue


for nm, d in DS.items():
    print("=" * 92)
    print(f"■ {nm}")
    print("  NG_Code 분포:", d.NG_Code.value_counts().to_dict())

    # 팀 규약이 이 데이터에서도 성립하는가
    strict = d.NG_Code == "PARTICLE"
    equiv = (d.Particle == 1) & (d.Remain_Coat == 0)
    print(f"  NG_Code=='PARTICLE' {int(strict.sum()):,}건 vs "
          f"(Particle==1 & Remain_Coat==0) {int(equiv.sum()):,}건 → "
          f"불일치 {int((strict != equiv).sum()):,}건")
    print(f"  보조 라벨 Particle==1 : {int((d.Particle == 1).sum()):,}건 "
          f"(차이 {int((d.Particle == 1).sum() - strict.sum()):,}건이 오염분)")

    # strict vs broad 비교
    pos_s, neg_s = d[strict], d[d.NG_Code == "OK"]
    pos_b, neg_b = d[d.Particle == 1], d[d.Particle == 0]
    rows = []
    for c in FDC + ["Freq_dev"]:
        ds_, ps_ = cliff(pos_s[c].to_numpy(), neg_s[c].to_numpy())
        db_, pb_ = cliff(pos_b[c].to_numpy(), neg_b[c].to_numpy())
        rows.append(dict(factor=c, delta_strict=ds_, p_strict=ps_,
                         delta_broad=db_, 배율=abs(db_) / max(abs(ds_), 1e-6)))
    r = pd.DataFrame(rows)
    r["q_strict"] = multipletests(r.p_strict, method="fdr_bh")[1]
    r["strict_통과"] = np.where(r.delta_strict.abs() >= 0.2, "○", "×")
    r["broad_통과"] = np.where(r.delta_broad.abs() >= 0.2, "○", "×")
    r = r.reindex(r.delta_broad.abs().sort_values(ascending=False).index)
    r.to_csv(OUT / f"strict_vs_broad_{nm}.csv", index=False, encoding="utf-8-sig")

    print(f"\n  [주라벨 vs 보조라벨] 팀 기준 |δ|>=0.2 통과 인자")
    print(f"   주라벨(NG_Code): {r[r.strict_통과=='○'].factor.tolist()}")
    print(f"   보조라벨(Particle==1): {r[r.broad_통과=='○'].factor.tolist()}")
    print(f"\n  상위 10 (보조라벨 기준 정렬):")
    print("   " + r.head(10)[["factor", "delta_strict", "delta_broad", "배율",
                              "strict_통과", "broad_통과"]].to_string(
        index=False, float_format=lambda v: f"{v:+.4f}").replace("\n", "\n   "))
    print()
