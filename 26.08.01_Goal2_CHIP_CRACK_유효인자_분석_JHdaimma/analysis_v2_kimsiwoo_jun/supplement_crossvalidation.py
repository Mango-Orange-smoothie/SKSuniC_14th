"""보충 검증 — 전부 김시우/Jun 브랜치 규약 안에서 수행

1) Jun의 '이중 라벨(primary/broad)' 설계를 이용한 그루빙 신호 정체 규명
   CRACK에서 그루빙 컬럼들이 broad 라벨에서만 신호가 나오고 primary에서는 0인 현상 →
   Chipping 동시발생 오염 가설을 검증한다.
2) 김시우 pipeline/README.md가 Goal2에 요구한 교차검증 수행
   (02b_process_parameter_correlation_pairs.csv 대조 — Jun/전성재 모두 파일 미발견으로 미수행)
3) 데이터셋별 재현성 (Jun의 Cliff's delta 지표 그대로 사용)
"""
import numpy as np, pandas as pd
from pathlib import Path
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
src = open(OUT / "chip_crack_factors_v2.py", encoding="utf-8").read()
exec(src.split("# =============================================================== 0단계")[0])

o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"; r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["is_normal"] = NORMAL(df)
df = add_domain_features(df)
baseline = compute_stratum_baseline_stats(df[df.is_normal], OPCOND, ALL_FEATURE_COLS)
df = zscore_transform(df, baseline, OPCOND, ALL_FEATURE_COLS)


def delta(mask, col):
    gv = df.loc[mask, f"{col}_z"].dropna(); rv = df.loc[~mask, f"{col}_z"].dropna()
    if len(gv) < 3 or len(rv) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(gv, rv, alternative="two-sided")
    return (2 * u) / (len(gv) * len(rv)) - 1, p


print("=" * 84)
print("1) CRACK — 그루빙 신호는 Chipping 동시발생 오염인가?")
print("=" * 84)
prim = df.NG_Code == "CRACK"
broad = df.Micro_Crack == 1
pure = (df.Micro_Crack == 1) & (df.Chipping == 0)
print(f"  primary(NG_Code==CRACK)        n={prim.sum():,}")
print(f"  broad(Micro_Crack==1)          n={broad.sum():,}")
print(f"  pure(Micro_Crack=1 & Chip=0)   n={pure.sum():,}")
print(f"  broad 중 Chipping 동시발생      n={(broad & (df.Chipping == 1)).sum():,} "
      f"({(broad & (df.Chipping == 1)).sum()/broad.sum()*100:.1f}%)\n")

cols = ["Surface_Roughness", "Vibration", "Cooling_Flow",
        "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Focus", "Head_Temp",
        "Laser_Power", "Power_Efficiency", "Frequency", "Groove_Depth"]
rows = []
print(f"  {'column':24s} {'그루빙':6s} {'primary':>9s} {'broad':>9s} {'pure':>9s}  판정")
for c in cols:
    dp, _ = delta(prim, c); db, _ = delta(broad, c); du, _ = delta(pure, c)
    g = "예" if c in LASER_GROOVING_COLS else "아니오"
    verdict = ""
    if abs(db) >= 0.2 and abs(du) < 0.2:
        verdict = "<< broad에서만 신호 = Chipping 오염"
    elif abs(du) >= 0.2:
        verdict = "<< pure에서도 유지 = 진짜 신호"
    print(f"  {c:24s} {g:6s} {dp:+9.3f} {db:+9.3f} {du:+9.3f}  {verdict}")
    rows.append({"column": c, "is_laser_grooving": c in LASER_GROOVING_COLS,
                 "cliffs_delta_primary": round(float(dp), 4),
                 "cliffs_delta_broad": round(float(db), 4),
                 "cliffs_delta_pure": round(float(du), 4)})
pd.DataFrame(rows).to_csv(OUT / "05_crack_grooving_contamination_check.csv",
                          index=False, encoding="utf-8-sig")

# ---- pure 라벨로 Jun 방식 트리 중요도 재실행
print("\n  [pure Micro_Crack 라벨로 RandomForest 재실행 — Jun 방식 동일]")
d2 = df[df.Chipping == 0].copy()
d2["is_crack_pure"] = (d2.Micro_Crack == 1).astype(int)
fz = [f"{c}_z" for c in ALL_FEATURE_COLS]
tr, te = train_test_split(d2, test_size=0.2, random_state=42, stratify=d2.is_crack_pure)
mdl = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                             random_state=42, n_jobs=-1).fit(tr[fz], tr.is_crack_pure)
tes = te.sample(n=min(20000, len(te)), random_state=42)
perm = permutation_importance(mdl, tes[fz], tes.is_crack_pure, scoring="average_precision",
                              n_repeats=15, random_state=42, n_jobs=-1)
pi = pd.DataFrame({"column": ALL_FEATURE_COLS, "importance_mean": perm.importances_mean})
pi["is_laser_grooving"] = pi.column.isin(LASER_GROOVING_COLS)
pi = pi.sort_values("importance_mean", ascending=False)
pi["rank"] = range(1, len(pi) + 1)
pi.to_csv(OUT / "06_crack_pure_tree_importance.csv", index=False, encoding="utf-8-sig")
for _, x in pi.head(10).iterrows():
    print(f"    {x['rank']:>2}. {x['column']:24s} imp={x['importance_mean']:+.5f}"
          f"{'  *그루빙*' if x['is_laser_grooving'] else ''}")

print("\n" + "=" * 84)
print("2) 김시우 README 요구 교차검증 — 02b 상관쌍 대조")
print("=" * 84)
import subprocess
repo = ROOT / "SKSuniC_14th"
txt = subprocess.run(["git", "show",
                      "origin/김시우:analysis_outputs/full_correlation/02b_process_parameter_correlation_pairs.csv"],
                     cwd=repo, capture_output=True, text=True, encoding="utf-8").stdout
pairs = pd.read_csv(pd.io.common.StringIO(txt))
print(f"  김시우 02b 상관쌍 {len(pairs)}건 로드")
chip_key = ["Kerf_Width_Profile", "Laser_Power", "Power_Efficiency",
            "Laser_Centering_Position", "Focus", "Groove_Depth"]
crack_key = ["Surface_Roughness", "Vibration"]
print("\n  [CHIP 유효인자 간 상관 — 중복신호 여부 확인]")
sel = pairs[(pairs.variable_1.isin(chip_key)) & (pairs.variable_2.isin(chip_key))]
for _, x in sel.iterrows():
    print(f"    {x.variable_1:26s} <-> {x.variable_2:22s} spearman={x.spearman_r:+.4f}")
print("\n  [CRACK 유효인자 관련 상관]")
sel2 = pairs[(pairs.variable_1.isin(crack_key)) | (pairs.variable_2.isin(crack_key))]
for _, x in sel2.head(10).iterrows():
    print(f"    {x.variable_1:26s} <-> {x.variable_2:22s} spearman={x.spearman_r:+.4f}")
pd.concat([sel, sel2]).drop_duplicates().to_csv(
    OUT / "07_crossvalidation_with_kimsiwoo_02b.csv", index=False, encoding="utf-8-sig")

print("\n" + "=" * 84)
print("3) 데이터셋별 재현성 (Jun의 Cliff's delta 지표)")
print("=" * 84)
for tname, lab in [("CHIP", df.Chipping == 1), ("CRACK", df.Micro_Crack == 1)]:
    print(f"\n  [{tname}]")
    keys = (["Kerf_Width_Profile", "Laser_Power", "Power_Efficiency", "Focus", "Vibration"]
            if tname == "CHIP" else
            ["Surface_Roughness", "Vibration", "Frequency", "Focus", "Kerf_Width_Profile"])
    print(f"    {'column':24s} {'원본':>10s} {'r1':>10s} {'통합':>10s}")
    rr = []
    for c in keys:
        vals = {}
        for ds in ["original", "r1"]:
            sub = df.source_dataset == ds
            gv = df.loc[sub & lab, f"{c}_z"].dropna(); rv = df.loc[sub & ~lab, f"{c}_z"].dropna()
            if len(gv) < 3:
                vals[ds] = np.nan; continue
            u, _ = scipy_stats.mannwhitneyu(gv, rv, alternative="two-sided")
            vals[ds] = (2 * u) / (len(gv) * len(rv)) - 1
        dall, _ = delta(lab, c)
        print(f"    {c:24s} {vals['original']:+10.3f} {vals['r1']:+10.3f} {dall:+10.3f}")
        rr.append({"target": tname, "column": c,
                   "delta_original": round(float(vals["original"]), 4),
                   "delta_r1": round(float(vals["r1"]), 4),
                   "delta_combined": round(float(dall), 4)})
    pd.DataFrame(rr).to_csv(OUT / f"08_reproducibility_{tname.lower()}.csv",
                            index=False, encoding="utf-8-sig")
print("\n완료")
