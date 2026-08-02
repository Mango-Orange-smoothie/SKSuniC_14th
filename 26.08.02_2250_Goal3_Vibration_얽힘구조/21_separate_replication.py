"""Goal3 - 원본 / R1 각각의 Vibration 얽힘 구조 + 원본 결과의 R1 재현성

  1부  원본 단독 : Vibration이 무엇과 얽혀 있는가
  2부  R1 단독   : Vibration이 무엇과 얽혀 있는가
  3부  재현성    : 원본에서 얻은 결론이 R1에서 다시 나오는가
"""
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from common import load, FDC, RESPONSES, ROOT

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
OUT = ROOT / "out" / "separate"
OUT.mkdir(parents=True, exist_ok=True)

DS = {"원본": load("base"), "R1": load("r1")}
OTHERS = [c for c in FDC if c != "Vibration"]
TARGETS = ["Particle", "Chipping", "Micro_Crack"]
CLUSTER = ["Vibration", "Laser_Power", "Power_Efficiency",
           "Laser_Centering_Position", "Focus", "Head_Temp"]


def z(s):
    return (s - s.mean()) / s.std(ddof=0)


# ══════════════════════════════════════════ 1·2부 : 각 데이터의 얽힘 구조
def entangle(d, nm):
    print(f"\n{'='*90}\n■ {nm}  (n={len(d):,})")
    print(f"  Vibration  평균 {d.Vibration.mean():.5f}  표준편차 {d.Vibration.std():.5f}  "
          f"범위 [{d.Vibration.min():.4f}, {d.Vibration.max():.4f}]")
    print("  불량률: " + "  ".join(f"{t} {d[t].mean()*100:.3f}%({int(d[t].sum()):,}건)"
                                 for t in TARGETS))

    # (1) 설비인자 상관
    corr = pd.Series({c: d.Vibration.corr(d[c]) for c in OTHERS})
    corr = corr.reindex(corr.abs().sort_values(ascending=False).index)
    print(f"\n  [상관] |r|>=0.3 인 인자: {int((corr.abs() >= .3).sum())}개 / {len(OTHERS)}개")
    print("   " + corr.head(8).round(3).to_string().replace("\n", "\n   "))

    # (2) VIF
    Z = np.column_stack([z(d[c]) for c in FDC])
    vif = pd.Series([variance_inflation_factor(Z, i) for i in range(len(FDC))], index=FDC)
    vif = vif.sort_values(ascending=False)
    print(f"\n  [VIF] 최대 {vif.iloc[0]:.2f} ({vif.index[0]}),  Vibration {vif['Vibration']:.2f},  "
          f"5 초과 인자 {int((vif > 5).sum())}개")

    # (3) PCA
    p = PCA().fit(StandardScaler().fit_transform(d[CLUSTER]))
    print(f"  [PCA] 6개 인자 PC1 설명력 {p.explained_variance_ratio_[0]*100:.1f}%")
    print("        적재: " + ", ".join(f"{c}={v:+.2f}" for c, v in zip(CLUSTER, p.components_[0])))

    # (4) Response 상관
    rc = pd.Series({c: d.Vibration.corr(d[c]) for c in RESPONSES})
    rc = rc.reindex(rc.abs().sort_values(ascending=False).index)
    print(f"\n  [Response] |r|>=0.3 인 응답: {int((rc.abs() >= .3).sum())}개 / {len(RESPONSES)}개")
    print("   " + rc.head(6).round(3).to_string().replace("\n", "\n   "))

    return dict(corr=corr, vif=vif, pc1=p.explained_variance_ratio_[0],
                loadings=pd.Series(p.components_[0], index=CLUSTER), resp=rc)


E = {nm: entangle(d, nm) for nm, d in DS.items()}

pd.DataFrame({nm: E[nm]["corr"] for nm in DS}).to_csv(
    OUT / "01_corr_fdc.csv", encoding="utf-8-sig")
pd.DataFrame({nm: E[nm]["vif"] for nm in DS}).to_csv(
    OUT / "02_vif.csv", encoding="utf-8-sig")
pd.DataFrame({nm: E[nm]["resp"] for nm in DS}).to_csv(
    OUT / "03_corr_response.csv", encoding="utf-8-sig")
pd.DataFrame({nm: E[nm]["loadings"] for nm in DS}).assign(
    PC1설명력=[E[nm]["pc1"] for nm in DS] + [np.nan] * (len(CLUSTER) - 2)
).to_csv(OUT / "04_pca.csv", encoding="utf-8-sig")


# ══════════════════════════════════════════ 효과 (불량별 OR)
def effects(d):
    sd = d.Vibration.std(ddof=0)
    out = {}
    for t in TARGETS:
        if d[t].sum() < 20:
            out[t] = dict(n=int(d[t].sum()), OR=np.nan, lo=np.nan, hi=np.nan, p=np.nan)
            continue
        m = sm.Logit(d[t].to_numpy(),
                     sm.add_constant((d.Vibration / sd).to_frame("v"))).fit(disp=0)
        b, se = m.params["v"], m.bse["v"]
        out[t] = dict(n=int(d[t].sum()), OR=np.exp(b), lo=np.exp(b - 1.96 * se),
                      hi=np.exp(b + 1.96 * se), p=m.pvalues["v"])
    return out


EF = {nm: effects(d) for nm, d in DS.items()}


# ══════════════════════════════════════════ 상호작용 (각 데이터 별도)
def interactions(d, t):
    if d[t].sum() < 30:
        return None
    y, zv = d[t].to_numpy(), z(d.Vibration)
    ctrl = pd.get_dummies(d.Machine_ID, prefix="M", drop_first=True).astype(float)
    rows = []
    for c in OTHERS:
        X = pd.concat([pd.DataFrame({"zVib": zv, "zX": z(d[c]), "inter": zv * z(d[c])})
                       .reset_index(drop=True), ctrl.reset_index(drop=True)], axis=1)
        try:
            m = sm.Logit(y, sm.add_constant(X)).fit(disp=0, maxiter=250)
        except Exception:
            continue
        rows.append(dict(factor=c, b_int=m.params["inter"], z_int=m.tvalues["inter"],
                         p_int=m.pvalues["inter"]))
    r = pd.DataFrame(rows)
    r["q_int"] = multipletests(r.p_int, method="fdr_bh")[1]
    return r.reindex(r.z_int.abs().sort_values(ascending=False).index)


print(f"\n{'='*90}\n■ 상호작용 (Vibration × 인자, 설비 통제, FDR 보정)")
INT = {}
for nm, d in DS.items():
    for t in TARGETS:
        r = interactions(d, t)
        INT[(nm, t)] = r
        if r is None:
            print(f"  {nm:4s} {t:12s} 표본 부족 - 생략")
        else:
            sig = r[r.q_int < .05]
            print(f"  {nm:4s} {t:12s} 유의 {len(sig):2d}/31  "
                  f"상위: {', '.join(sig.factor.head(4)) if len(sig) else '없음'}")
pd.concat([v.assign(데이터=k[0], 불량=k[1]) for k, v in INT.items() if v is not None]
          ).to_csv(OUT / "05_interaction.csv", index=False, encoding="utf-8-sig")


# ══════════════════════════════════════════ 3부 : 재현성
print(f"\n{'='*90}\n■ 3부 · 원본 결과가 R1에서 재현되는가")

# (A) 얽힘 구조 재현
print("\n[A] 얽힘 구조")
comp = pd.DataFrame({"원본": E["원본"]["corr"], "R1": E["R1"]["corr"]})
comp = comp.reindex(comp.R1.abs().sort_values(ascending=False).index)
comp["부호일치"] = np.where(comp.원본 * comp.R1 > 0, "○", "×")
comp["원본_강함"] = np.where(comp.원본.abs() >= .3, "○", "×")
comp["R1_강함"] = np.where(comp.R1.abs() >= .3, "○", "×")
print(comp.head(8).round(3).to_string())
comp.to_csv(OUT / "06_replication_corr.csv", encoding="utf-8-sig")
print(f"\n  |r|>=0.3 인자 수 : 원본 {int((comp.원본.abs()>=.3).sum())}개  →  "
      f"R1 {int((comp.R1.abs()>=.3).sum())}개")
print(f"  PC1 설명력      : 원본 {E['원본']['pc1']*100:.1f}%  →  R1 {E['R1']['pc1']*100:.1f}%")
print(f"  VIF 5 초과 인자  : 원본 {int((E['원본']['vif']>5).sum())}개  →  "
      f"R1 {int((E['R1']['vif']>5).sum())}개")

# (B) 효과 재현
print("\n[B] Vibration 효과 (OR per +1SD)")
rows = []
for t in TARGETS:
    a, b = EF["원본"][t], EF["R1"][t]
    if np.isnan(a["OR"]):
        verdict = "원본 표본부족 → 판정불가"
    elif np.isnan(b["OR"]):
        verdict = "R1 표본부족"
    else:
        same = (a["OR"] - 1) * (b["OR"] - 1) > 0
        overlap = not (a["hi"] < b["lo"] or b["hi"] < a["lo"])
        verdict = ("재현 (방향·크기 일치)" if same and overlap else
                   "방향 일치, 크기 차이" if same else "★ 방향 불일치")
    rows.append(dict(불량=t, 원본_n=a["n"], 원본_OR=a["OR"],
                     원본_CI=f"[{a['lo']:.2f}–{a['hi']:.2f}]" if not np.isnan(a["OR"]) else "-",
                     R1_n=b["n"], R1_OR=b["OR"],
                     R1_CI=f"[{b['lo']:.2f}–{b['hi']:.2f}]" if not np.isnan(b["OR"]) else "-",
                     판정=verdict))
rep = pd.DataFrame(rows)
print(rep.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
rep.to_csv(OUT / "07_replication_effect.csv", index=False, encoding="utf-8-sig")

# (C) 유효인자 순위 재현 (Cliff delta)
print("\n[C] 불량별 유효인자 순위 재현 (Cliff δ)")
for t in TARGETS:
    sc = {}
    for nm, d in DS.items():
        if d[t].sum() < 30:
            continue
        pos, neg = d[d[t] == 1], d[d[t] == 0]
        sc[nm] = pd.Series({c: 2 * (stats.mannwhitneyu(pos[c], neg[c]).statistic /
                                    (len(pos) * len(neg))) - 1 for c in FDC})
    if len(sc) < 2:
        print(f"\n  {t}: 원본 표본부족({int(DS['원본'][t].sum())}건) → 순위 비교 불가")
        continue
    tb = pd.DataFrame(sc)
    tb["원본순위"] = tb["원본"].abs().rank(ascending=False).astype(int)
    tb["R1순위"] = tb["R1"].abs().rank(ascending=False).astype(int)
    tb["부호일치"] = np.where(tb["원본"] * tb["R1"] > 0, "○", "×")
    tb = tb.sort_values("R1순위")
    rho = stats.spearmanr(tb["원본"].abs(), tb["R1"].abs()).statistic
    top5_overlap = len(set(tb.nsmallest(5, "원본순위").index) &
                       set(tb.nsmallest(5, "R1순위").index))
    print(f"\n  ■ {t}  순위상관 ρ={rho:+.3f}   상위5 겹침 {top5_overlap}/5")
    print(tb.head(8).round(3).to_string())
    tb.to_csv(OUT / f"08_rank_replication_{t}.csv", encoding="utf-8-sig")

# (D) 상호작용 재현
print("\n[D] 상호작용 재현")
for t in TARGETS:
    a, b = INT[("원본", t)], INT[("R1", t)]
    if a is None or b is None:
        print(f"  {t:12s} 판정불가 (원본 표본부족)")
        continue
    sa = set(a[a.q_int < .05].factor)
    sb = set(b[b.q_int < .05].factor)
    print(f"  {t:12s} 원본 {len(sa):2d}개 / R1 {len(sb):2d}개 / 공통 {len(sa & sb):2d}개"
          + (f"  → {', '.join(sorted(sa & sb))}" if sa & sb else ""))

print(f"\n저장 -> {OUT}")
