"""baseline 선택이 결론을 바꾸는가 — 민감도 검증

세 가지 baseline으로 같은 검정을 돌려 Cliff's delta를 비교한다.

  (A) 김시우님이 브랜치에 커밋한 baseline 파일 그대로 사용
      = 원본 100,000행의 OK(90,783건)만으로 만든 기준
      -> "알려진 정상 상태 대비 얼마나 벗어났나"를 재는 셈
  (B) 내 v2가 실제로 쓴 것: 통합 200,000행의 OK(149,673건)로 재계산
  (C) v1이 쓴 것: 통합 데이터 전체 행(불량 포함)으로 계산  <- 김시우 방식 아님
"""
import io, subprocess
import numpy as np, pandas as pd
from pathlib import Path
from scipy import stats as scipy_stats

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
exec(open(OUT / "chip_crack_factors_v2.py", encoding="utf-8").read()
     .split("# =============================================================== 0단계")[0])

o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"; r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["is_normal"] = NORMAL(df)
df = add_domain_features(df)

# (A) 김시우 커밋 baseline
txt = subprocess.run(
    ["git", "show",
     "origin/김시우:analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv"],
    cwd=ROOT / "SKSuniC_14th", capture_output=True, text=True, encoding="utf-8").stdout
bl_kim = pd.read_csv(io.StringIO(txt))[OPCOND + ["column", "median", "robust_z_scale"]]

# (B) 통합 OK로 재계산 (v2가 실제 사용)
bl_comb = compute_stratum_baseline_stats(df[df.is_normal], OPCOND, ALL_FEATURE_COLS)

dfA = zscore_transform(df, bl_kim, OPCOND, ALL_FEATURE_COLS)
dfB = zscore_transform(df, bl_comb, OPCOND, ALL_FEATURE_COLS)

# (C) 전체 행 median/MAD (v1 방식)
dfC = df.copy()
g = df.groupby(OPCOND, observed=True)
for c in ALL_FEATURE_COLS:
    med = g[c].transform("median")
    mad = g[c].transform(lambda s: np.median(np.abs(s - np.median(s))))
    sc = (mad * MAD_SCALE).where(lambda s: s > 1e-12, 1.0)
    dfC[f"{c}_z"] = (df[c] - med) / sc


def delta(frame, mask, col):
    gv = frame.loc[mask, f"{col}_z"].dropna(); rv = frame.loc[~mask, f"{col}_z"].dropna()
    u, _ = scipy_stats.mannwhitneyu(gv, rv, alternative="two-sided")
    return (2 * u) / (len(gv) * len(rv)) - 1


cases = {
    "CHIP (Chipping==1)": df.Chipping == 1,
    "CRACK broad (Micro_Crack==1)": df.Micro_Crack == 1,
    "CRACK pure (Crack=1 & Chip=0)": (df.Micro_Crack == 1) & (df.Chipping == 0),
}
cols_of_interest = {
    "CHIP (Chipping==1)": ["Kerf_Width_Profile", "Laser_Power", "Power_Efficiency",
                           "Focus", "Vibration", "Groove_Depth"],
    "CRACK broad (Micro_Crack==1)": ["Surface_Roughness", "Vibration", "Frequency",
                                     "Kerf_Width_Profile", "Focus"],
    "CRACK pure (Crack=1 & Chip=0)": ["Surface_Roughness", "Vibration", "Frequency",
                                      "Kerf_Width_Profile", "Focus", "CLN_Flow"],
}

rows = []
for name, mask in cases.items():
    print(f"\n{'='*82}\n{name}   (n={int(mask.sum()):,})\n{'='*82}")
    print(f"  {'컬럼':<24s} {'(A)김시우 커밋':>14s} {'(B)통합OK[v2사용]':>18s} {'(C)전체행[v1]':>14s}")
    for c in cols_of_interest[name]:
        a = delta(dfA, mask, c); b = delta(dfB, mask, c); cc = delta(dfC, mask, c)
        mark = "   <- 판정변화" if (abs(a) >= 0.2) != (abs(b) >= 0.2) else ""
        print(f"  {c:<24s} {a:>14.3f} {b:>18.3f} {cc:>14.3f}{mark}")
        rows.append({"case": name, "column": c,
                     "delta_A_kimsiwoo_committed": round(float(a), 4),
                     "delta_B_combined_ok_used_in_v2": round(float(b), 4),
                     "delta_C_all_rows_v1": round(float(cc), 4)})
pd.DataFrame(rows).to_csv(OUT / "09_baseline_sensitivity.csv", index=False, encoding="utf-8-sig")
print("\n완료")
