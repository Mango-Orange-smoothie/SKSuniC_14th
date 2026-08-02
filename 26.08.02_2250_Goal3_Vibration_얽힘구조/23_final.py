"""Goal3 최종 - Vibration 얽힘 구조 (원본/R1 각각 + 재현성)

라벨 규약은 팀 Goal2(26.07.31_2058) 기준을 따른다.
  불량군 : NG_Code == 해당 코드      정상군 : NG_Code == 'OK'
  인자값 : Product_ID x Recipe_ID 그룹 내 z 정규화

  1부/2부  각 데이터의 얽힘 구조 (상관·VIF·PCA는 라벨 무관)
  3부      원본 결과의 R1 재현성
"""
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from common import load, FDC, RESPONSES, ROOT

warnings.filterwarnings("ignore")
pd.set_option("display.width", 240)
from pathlib import Path
OUT = Path(__file__).resolve().parent   # 산출 CSV는 스크립트와 같은 폴더에
OUT.mkdir(parents=True, exist_ok=True)

DS = {"원본": load("base"), "R1": load("r1")}
OTHERS = [c for c in FDC if c != "Vibration"]
CLUSTER = ["Vibration", "Laser_Power", "Power_Efficiency",
           "Laser_Centering_Position", "Focus", "Head_Temp"]
NG = {"Particle": "PARTICLE", "Chipping": "CHIP", "Micro_Crack": "CRACK"}


def zgrp(d, cols):
    """제품 x 레시피 그룹 내 z 정규화 (팀 Goal2 방식)."""
    g = d.groupby(["Product_ID", "Recipe_ID"])
    return pd.DataFrame({c: ((d[c] - g[c].transform("mean")) /
                             g[c].transform("std").replace(0, np.nan)).fillna(0)
                         for c in cols}, index=d.index)


def team_subset(d, defect):
    """팀 규약 : 해당 불량군 + 완전정상군만."""
    m = d.NG_Code.isin([NG[defect], "OK"])
    s = d[m].copy()
    s["y"] = (s.NG_Code == NG[defect]).astype(int)
    return s


# ══════════════════════════════════ 1·2부 : 얽힘 구조 (라벨 무관)
ENT = {}
for nm, d in DS.items():
    print("=" * 92)
    print(f"■ {nm}  n={len(d):,}   Vibration 평균 {d.Vibration.mean():.5f} "
          f"표준편차 {d.Vibration.std():.5f}")

    corr = pd.Series({c: d.Vibration.corr(d[c]) for c in OTHERS})
    corr = corr.reindex(corr.abs().sort_values(ascending=False).index)

    Z = np.column_stack([(d[c] - d[c].mean()) / d[c].std(ddof=0) for c in FDC])
    vif = pd.Series([variance_inflation_factor(Z, i) for i in range(len(FDC))],
                    index=FDC).sort_values(ascending=False)

    p = PCA().fit(StandardScaler().fit_transform(d[CLUSTER]))
    resp = pd.Series({c: d.Vibration.corr(d[c]) for c in RESPONSES})
    resp = resp.reindex(resp.abs().sort_values(ascending=False).index)

    ENT[nm] = dict(corr=corr, vif=vif, pc1=p.explained_variance_ratio_[0],
                   load=pd.Series(p.components_[0], index=CLUSTER), resp=resp)

    print(f"  [상관]   |r|>=0.3 인자 {int((corr.abs()>=.3).sum())}개 / {len(OTHERS)}개   "
          f"최대 {corr.iloc[0]:+.3f} ({corr.index[0]})")
    print(f"  [VIF]    5 초과 {int((vif>5).sum())}개   최대 {vif.iloc[0]:.2f} ({vif.index[0]})   "
          f"Vibration {vif['Vibration']:.2f}")
    print(f"  [PCA]    6인자 PC1 설명력 {p.explained_variance_ratio_[0]*100:.1f}%")
    print(f"  [Response] |r|>=0.3 응답 {int((resp.abs()>=.3).sum())}개 / {len(RESPONSES)}개   "
          f"최대 {resp.iloc[0]:+.3f} ({resp.index[0]})")
    print("\n  상관 상위 8:")
    print("   " + corr.head(8).round(3).to_string().replace("\n", "\n   "))
    print("  Response 상위 6:")
    print("   " + resp.head(6).round(3).to_string().replace("\n", "\n   "))
    print()

pd.DataFrame({n: ENT[n]["corr"] for n in DS}).to_csv(OUT / "01_corr_fdc.csv", encoding="utf-8-sig")
pd.DataFrame({n: ENT[n]["vif"] for n in DS}).to_csv(OUT / "02_vif.csv", encoding="utf-8-sig")
pd.DataFrame({n: ENT[n]["resp"] for n in DS}).to_csv(OUT / "03_corr_response.csv", encoding="utf-8-sig")
pd.DataFrame({n: ENT[n]["load"] for n in DS}).to_csv(OUT / "04_pca_loadings.csv", encoding="utf-8-sig")

# ══════════════════════════════════ 효과 & 상호작용 (팀 라벨)
print("=" * 92)
print("■ Vibration 효과 · 상호작용 (팀 라벨 규약: 불량군 vs NG_Code=='OK')")
eff_rows, int_all = [], []
for nm, d in DS.items():
    for defect, code in NG.items():
        s = team_subset(d, defect)
        n_pos = int(s.y.sum())
        if n_pos < 30:
            eff_rows.append(dict(데이터=nm, 불량=defect, n_불량=n_pos, n_정상=int((1-s.y).sum()),
                                 OR=np.nan, lo=np.nan, hi=np.nan, 유의상호작용=np.nan))
            print(f"  {nm:4s} {defect:12s} 불량 {n_pos}건 - 표본 부족")
            continue
        Zs = zgrp(s, FDC)
        y = s.y.to_numpy()

        m = sm.Logit(y, sm.add_constant(Zs[["Vibration"]])).fit(disp=0)
        b, se = m.params["Vibration"], m.bse["Vibration"]

        ctrl = pd.get_dummies(s.Machine_ID, prefix="M", drop_first=True).astype(float)
        rows = []
        for c in OTHERS:
            X = pd.concat([pd.DataFrame({"zVib": Zs.Vibration.values, "zX": Zs[c].values,
                                         "inter": Zs.Vibration.values * Zs[c].values}),
                           ctrl.reset_index(drop=True)], axis=1)
            try:
                mm = sm.Logit(y, sm.add_constant(X)).fit(disp=0, maxiter=250)
            except Exception:
                continue
            rows.append(dict(데이터=nm, 불량=defect, factor=c, b_int=mm.params["inter"],
                             z_int=mm.tvalues["inter"], p_int=mm.pvalues["inter"]))
        r = pd.DataFrame(rows)
        r["q_int"] = multipletests(r.p_int, method="fdr_bh")[1]
        r = r.reindex(r.z_int.abs().sort_values(ascending=False).index)
        int_all.append(r)
        nsig = int((r.q_int < .05).sum())

        eff_rows.append(dict(데이터=nm, 불량=defect, n_불량=n_pos, n_정상=int((1-s.y).sum()),
                             OR=np.exp(b), lo=np.exp(b-1.96*se), hi=np.exp(b+1.96*se),
                             유의상호작용=nsig))
        print(f"  {nm:4s} {defect:12s} 불량 {n_pos:>6,} / 정상 {int((1-s.y).sum()):>6,}   "
              f"OR {np.exp(b):>6.3f} [{np.exp(b-1.96*se):.2f}–{np.exp(b+1.96*se):.2f}]   "
              f"유의 상호작용 {nsig:2d}/31" +
              (f"  → {', '.join(r[r.q_int<.05].factor.head(4))}" if nsig else ""))

eff = pd.DataFrame(eff_rows)
eff.to_csv(OUT / "05_effect_interaction.csv", index=False, encoding="utf-8-sig")
if int_all:
    pd.concat(int_all).to_csv(OUT / "06_interaction_detail.csv", index=False, encoding="utf-8-sig")

# ══════════════════════════════════ 3부 재현성
print("\n" + "=" * 92)
print("■ 3부 · 재현성")

print("\n[A] 얽힘 구조")
comp = pd.DataFrame({"원본": ENT["원본"]["corr"], "R1": ENT["R1"]["corr"]})
comp = comp.reindex(comp.R1.abs().sort_values(ascending=False).index)
comp["부호일치"] = np.where(comp.원본 * comp.R1 > 0, "○", "×")
comp.to_csv(OUT / "07_replication_corr.csv", encoding="utf-8-sig")
print(comp.head(8).round(3).to_string())
top = comp.head(6)
print(f"\n  상위 6개 인자 부호 일치 : {int((top.부호일치=='○').sum())}/6")
print(f"  전체 31개 부호 일치     : {int((comp.부호일치=='○').sum())}/31")
print(f"  |r|>=0.3 인자 수 : 원본 {int((comp.원본.abs()>=.3).sum())}개 → R1 {int((comp.R1.abs()>=.3).sum())}개")
print(f"  PC1 설명력       : 원본 {ENT['원본']['pc1']*100:.1f}% → R1 {ENT['R1']['pc1']*100:.1f}%")
print(f"  VIF>5 인자 수    : 원본 {int((ENT['원본']['vif']>5).sum())}개 → "
      f"R1 {int((ENT['R1']['vif']>5).sum())}개")

print("\n[B] Vibration 효과 방향")
for defect in NG:
    a = eff[(eff.데이터 == "원본") & (eff.불량 == defect)].iloc[0]
    b_ = eff[(eff.데이터 == "R1") & (eff.불량 == defect)].iloc[0]
    if np.isnan(a.OR):
        v = f"원본 불량 {int(a.n_불량)}건 → 판정 불가"
    else:
        same = (a.OR - 1) * (b_.OR - 1) > 0
        v = "방향 일치" if same else "★ 방향 불일치"
    print(f"  {defect:12s} 원본 {a.OR if not np.isnan(a.OR) else float('nan'):.3f} "
          f"(n={int(a.n_불량):,})  →  R1 {b_.OR:.3f} (n={int(b_.n_불량):,})   {v}")

print("\n[C] 상호작용")
for defect in NG:
    a = eff[(eff.데이터 == "원본") & (eff.불량 == defect)].iloc[0]
    b_ = eff[(eff.데이터 == "R1") & (eff.불량 == defect)].iloc[0]
    if np.isnan(a.유의상호작용):
        print(f"  {defect:12s} 원본 판정불가  →  R1 {int(b_.유의상호작용)}개")
        continue
    sa = set(pd.concat(int_all).query("데이터=='원본' and 불량==@defect and q_int<0.05").factor)
    sb = set(pd.concat(int_all).query("데이터=='R1' and 불량==@defect and q_int<0.05").factor)
    print(f"  {defect:12s} 원본 {len(sa)}개  →  R1 {len(sb)}개   공통 {len(sa & sb)}개")

print(f"\n저장 -> {OUT}")
