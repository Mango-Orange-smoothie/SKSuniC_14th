"""'r1에서 진동이 반대 방향' 관측의 원인 규명 : 다중공선성 재현 실험

  Step1  전체 인자 투입 로지스틱 -> Vibration 부호가 뒤집히는가 (팀 결과 재현)
  Step2  VIF / 조건수로 공선성 정량화
  Step3  PCA -> 공통 잠재인자(설비 열화축)가 있는가
  Step4  GBM + permutation importance -> 트리 모형에서도 Vibration이 가려지는가
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from common import load, FDC, RESPONSES, ROOT

pd.set_option("display.width", 240)
OUT = ROOT / "out" / "direction"
OUT.mkdir(parents=True, exist_ok=True)

D = {"원본": load("base"), "R1": load("r1")}
TARGETS = ["Chipping", "Particle", "Micro_Crack"]
CLUSTER = ["Vibration", "Laser_Power", "Power_Efficiency", "Laser_Centering_Position",
           "Focus", "Head_Temp", "Cooling_Flow"]


def zs(d, cols):
    return pd.DataFrame({c: (d[c] - d[c].mean()) / d[c].std(ddof=0) for c in cols},
                        index=d.index)


# ---------------------------------------------------- Step1 전체 투입 모형
print("=" * 96)
print("[Step1] 전체 FDC 32개 인자를 한 모형에 넣었을 때 Vibration 계수")
rows = []
for t in TARGETS:
    for nm, d in D.items():
        if d[t].sum() < 20:
            continue
        X = sm.add_constant(zs(d, FDC))
        m = sm.Logit(d[t].to_numpy(), X).fit(disp=0, maxiter=400)
        b, se = m.params["Vibration"], m.bse["Vibration"]
        # 단변량
        m0 = sm.Logit(d[t].to_numpy(), sm.add_constant(zs(d, ["Vibration"]))).fit(disp=0)
        rows.append(dict(defect=t, data=nm, n_pos=int(d[t].sum()),
                         OR_단독=np.exp(m0.params["Vibration"]),
                         OR_전체투입=np.exp(b), z=b / se, p=m.pvalues["Vibration"],
                         부호반전="★ 예" if (np.exp(m0.params["Vibration"]) - 1) *
                         (np.exp(b) - 1) < 0 else "아니오"))
r1 = pd.DataFrame(rows)
print(r1.to_string(index=False, float_format=lambda v: f"{v:.4g}"))
r1.to_csv(OUT / "full_model_signflip.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------- Step2 VIF
print("\n" + "=" * 96)
print("[Step2] 다중공선성 - VIF (10 초과면 심각)")
vif_tbl = {}
for nm, d in D.items():
    X = zs(d, FDC).to_numpy()
    vif_tbl[nm] = [variance_inflation_factor(X, i) for i in range(len(FDC))]
vif = pd.DataFrame(vif_tbl, index=FDC)
vif = vif.reindex(vif["R1"].sort_values(ascending=False).index)
print(vif.head(10).round(2).to_string())
vif.to_csv(OUT / "vif.csv", encoding="utf-8-sig")
for nm, d in D.items():
    ev = np.linalg.eigvalsh(np.corrcoef(zs(d, FDC).to_numpy(), rowvar=False))
    print(f"  {nm} 조건수(√λmax/λmin) = {np.sqrt(ev.max()/max(ev.min(),1e-12)):.1f}")

# ---------------------------------------------------- Step3 PCA
print("\n" + "=" * 96)
print("[Step3] 공통 잠재인자 탐색 - 얽힌 7개 인자 PCA")
for nm, d in D.items():
    Z = StandardScaler().fit_transform(d[CLUSTER])
    p = PCA().fit(Z)
    print(f"\n{nm}: 설명분산 " +
          ", ".join(f"PC{i+1}={v*100:.1f}%" for i, v in enumerate(p.explained_variance_ratio_[:3])))
    print("  PC1 적재량:", ", ".join(f"{c}={v:+.2f}" for c, v in zip(CLUSTER, p.components_[0])))

# ---------------------------------------------------- Vibration -> Response
print("\n" + "=" * 96)
print("[보조] Vibration이 공정 Response를 끌고 가는가 (r)")
rr = pd.DataFrame({nm: [d.Vibration.corr(d[c]) for c in RESPONSES] for nm, d in D.items()},
                  index=RESPONSES)
rr["차이"] = rr["R1"].abs() - rr["원본"].abs()
print(rr.reindex(rr["R1"].abs().sort_values(ascending=False).index).round(3).to_string())

# ---------------------------------------------------- Step4 permutation importance
print("\n" + "=" * 96)
print("[Step4] GBM permutation importance - 공선 인자와 함께 넣으면 Vibration이 가려지는가")
d = D["R1"]
for t in TARGETS:
    X = d[FDC].astype(float)
    y = d[t].to_numpy()
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    gb = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08,
                                        l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
    pi = permutation_importance(gb, Xte, yte, n_repeats=5, random_state=0,
                                scoring="roc_auc", n_jobs=1)
    imp = pd.Series(pi.importances_mean, index=FDC).sort_values(ascending=False)
    rank = list(imp.index).index("Vibration") + 1
    print(f"\n■ {t}: Vibration 중요도 순위 {rank}/32 (값 {imp['Vibration']:.4f})")
    print("   상위5:", ", ".join(f"{k}={v:.4f}" for k, v in imp.head(5).items()))

    # 공선 인자 제거 후 재평가
    keep = [c for c in FDC if c not in
            ("Laser_Power", "Power_Efficiency", "Laser_Centering_Position", "Focus", "Head_Temp")]
    Xtr2, Xte2 = Xtr[keep], Xte[keep]
    gb2 = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08,
                                         l2_regularization=1.0, random_state=0).fit(Xtr2, ytr)
    pi2 = permutation_importance(gb2, Xte2, yte, n_repeats=5, random_state=0,
                                 scoring="roc_auc", n_jobs=1)
    imp2 = pd.Series(pi2.importances_mean, index=keep).sort_values(ascending=False)
    print(f"   공선인자 5개 제거 후 Vibration 순위 "
          f"{list(imp2.index).index('Vibration')+1}/{len(keep)} (값 {imp2['Vibration']:.4f})")
