"""티어표 검증 — 음성 대조군(플라시보) · 데이터 단독 순위

원인인자_검증_전말.md 의 6부·7부를 재현하는 스크립트다.
**읽기 전용이다. 저장소에 아무것도 쓰지 않는다.** 결과는 화면에만 찍는다.

무엇을 확인하나
  TEST 1  플라시보 : 가짜 인자 3개를 진짜 39개와 같은 판에 넣고 경쟁시킨다.
                     - 표준정규 난수
                     - 균등 난수
                     - Head_Temp_z 를 무작위로 섞은 것  ← 분포 동일, 관계만 파괴. 가장 엄격
                     합격선을 넘으면 우리 기준이 헐겁다는 뜻이므로 발표에서 쓰면 안 된다.

  TEST 2  통과율   : 39개 전 컬럼에 티어표와 똑같은 합격 기준을 걸면 몇 개가 통과하나.
                     "통계+RF 만으로는 못 거른다 → 도메인 게이트가 실제로 일한다"의 근거.

  TEST 3  단독순위 : 도메인을 모르는 척하고 데이터만으로 줄 세웠을 때
                     멘토 확정 11쌍이 어디에 있나. 순환논증("답 받아놓고 푼 것 아니냐") 방어.

설정은 build_tier_table.py 와 완전히 동일하다 (라벨 '다'안 · 강건 z · RF 200/8/balanced ·
순열중요도 PR-AUC 10회 · 합격선 상위 25%).

실행 (저장소 루트에서):
  python "SKSuniC_14th/26.08.05_Goal2_통합_Relationship_DB_JHdaimma/verify_negative_control.py"
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SRC = PROJ / "SKSuniC_14th" / "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma" / "agent_db"

# build_relationship_db.py 의 헤더(상수·전처리 함수)만 가져온다. 데이터 섹션 이후는 실행하지 않는다.
src = open(SRC / "build_relationship_db.py", encoding="utf-8").read()
exec(src.split("# ==================================================================== 데이터")[0])
ROOT = PROJ  # exec 가 덮어쓴 ROOT 복원 — 저장소에 아무것도 안 쓴다

RNG, ALPHA, EFFECT_MIN, RF_TOP_PCT = 42, 0.05, 0.2, 0.25
DEFECTS = ["Chipping", "Micro_Crack", "Particle", "Remain_Coat"]
BINARY_LABEL_DEFECTS = ("Micro_Crack", "Particle")

# 멘토 확정 도메인 11쌍 (build_tier_table.py 의 DOMAIN 과 동일)
DOMAIN_PAIRS = {
    ("Particle", "Surface_Roughness"), ("Particle", "CLN_Flow"), ("Particle", "CLN_Pressure"),
    ("Remain_Coat", "CLN_Pressure"), ("Remain_Coat", "CLN_Flow"),
    ("Micro_Crack", "Cooling_Flow"), ("Micro_Crack", "Cooling_Water_Temp"),
    ("Chipping", "Power_Efficiency"), ("Chipping", "Laser_Power"),
    ("Chipping", "Head_Temp"), ("Chipping", "Cooling_Flow"),
}

print("[1/4] 데이터 로드 · 층별 기준선 · 강건 z-score")
o = pd.read_csv(ROOT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(ROOT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"], r["source_dataset"] = "original", "r1"
df = add_domain_features(pd.concat([o, r], ignore_index=True))
df["is_normal"] = NORMAL(df)
bl = baseline_stats(df[df.is_normal], OPCOND, FEATURES)
df = zscore(df, bl, OPCOND, FEATURES)
print(f"    {len(df):,}행 · 정상군 {df.is_normal.sum():,} · 진짜 피처 {len(FEATURES)}개")

# ---------------------------------------------------------------- 가짜 인자 3개 주입
# 이미 z-score 공간이므로 표준정규를 그대로 넣는다. 세 번째는 실제 Head_Temp_z 를
# 무작위로 섞은 것 — 분포는 완전히 같고 라벨과의 관계만 파괴된다.
rs = np.random.RandomState(RNG)
FAKE = ["__FAKE_정규난수", "__FAKE_균등난수", "__FAKE_HeadTemp섞음"]
df["__FAKE_정규난수_z"] = rs.standard_normal(len(df))
df["__FAKE_균등난수_z"] = rs.uniform(-1.7, 1.7, len(df))
df["__FAKE_HeadTemp섞음_z"] = rs.permutation(df["Head_Temp_z"].values)
ALLF = list(FEATURES) + FAKE
print(f"    가짜 인자 3개 주입 → 총 {len(ALLF)}개로 경쟁시킨다")

# ---------------------------------------------------------------- 라벨 ('다'안 그대로)
for d in DEFECTS:
    others = [x for x in DEFECTS if x != d]
    if d in BINARY_LABEL_DEFECTS:
        df[f"__pure_{d}"] = (df[d] == 1).astype(int)
    else:
        df[f"__pure_{d}"] = ((df[d] == 1) & (df[others].sum(axis=1) == 0)).astype(int)


def cliffs_delta(a, b):
    """Cliff's delta = P(a>b) - P(a<b). Mann-Whitney U 를 -1~+1 로 환산."""
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    u, p = sps.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


print("[2/4] 통계검정 — 42개 전부 (진짜 39 + 가짜 3)")
uni = {}
for d in DEFECTS:
    y = df[f"__pure_{d}"].values
    ctl = (y == 0) & df.is_normal.values          # 비교군은 '확실한 정상품' 만
    rows = []
    for c in ALLF:
        dl, p = cliffs_delta(df.loc[y == 1, f"{c}_z"], df.loc[ctl, f"{c}_z"])
        rows.append(dict(factor=c, delta=dl, p_raw=p))
    t = pd.DataFrame(rows)
    t["p_fdr"] = multipletests(t.p_raw, alpha=ALPHA, method="fdr_bh")[1]
    t["stat_pass"] = (t.p_fdr < ALPHA) & (t.delta.abs() >= EFFECT_MIN)
    uni[d] = t.set_index("factor")
    print(f"    {d:12s} 불량 {int(y.sum()):>6,}건 · 통계 통과 {int(t.stat_pass.sum())}/{len(ALLF)}")

print("[3/4] RandomForest 순열중요도 — 가짜 3개를 같이 경쟁시킨다")
rf = {}
cut = max(1, int(round(len(ALLF) * RF_TOP_PCT)))
for d in DEFECTS:
    y = df[f"__pure_{d}"].values
    fz = [f"{c}_z" for c in ALLF]
    tr, te = train_test_split(df.assign(_y=y), test_size=0.2, random_state=RNG, stratify=y)
    m = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                               random_state=RNG, n_jobs=-1).fit(tr[fz], tr._y)
    tes = te.sample(n=min(20000, len(te)), random_state=RNG)
    pi = permutation_importance(m, tes[fz], tes._y, scoring="average_precision",
                                n_repeats=10, random_state=RNG, n_jobs=-1)
    t = pd.DataFrame({"factor": ALLF, "imp": pi.importances_mean})
    t["rank"] = t.imp.rank(ascending=False, method="min").astype(int)
    t["rf_pass"] = (t["rank"] <= cut) & (t.imp > 0)
    rf[d] = t.set_index("factor")
    print(f"    {d:12s} RF 통과 {int(t.rf_pass.sum())}/{len(ALLF)}  (합격선 상위 {cut}위)")

# ==================================================================== TEST 1
print("\n" + "=" * 78)
print(f"  TEST 1 — 플라시보: 가짜 인자 3개가 어디에 랭크되나  (합격선 상위 {cut}위)")
print("=" * 78)
print(f"  {'가짜 인자':<22}" + "".join(f"{d:>16}" for d in DEFECTS))
print("  " + "-" * 86)
ok = True
for f in FAKE:
    line = f"  {f:<22}"
    for d in DEFECTS:
        if rf[d].loc[f, "rf_pass"]:
            ok = False
            line += f"{rf[d].loc[f, 'rank']:>6}/{len(ALLF)} ❌통과!"
        else:
            line += f"{rf[d].loc[f, 'rank']:>8}/{len(ALLF)}    "
    print(line)
print("\n  통계검정 쪽 (합격선 |delta| >= 0.2)")
for f in FAKE:
    line = f"  {f:<22}"
    for d in DEFECTS:
        mk = "❌" if uni[d].loc[f, "stat_pass"] else "  "
        line += f"{uni[d].loc[f, 'delta']:>+11.4f}{mk:>5}"
    print(line)

# ==================================================================== TEST 2
print("\n" + "=" * 78)
print("  TEST 2 — 통과율: 진짜 39개 중 몇 개가 두 관문을 다 통과하나")
print("=" * 78)
print(f"  {'defect':<14}{'통계통과':>10}{'RF통과':>10}{'둘 다':>10}   둘 다 통과한 인자")
print("  " + "-" * 74)
for d in DEFECTS:
    s, rp = uni[d].loc[list(FEATURES), "stat_pass"], rf[d].loc[list(FEATURES), "rf_pass"]
    both = s & rp
    tagged = [f"{c}{'*' if (d, c) in DOMAIN_PAIRS else ''}" for c in FEATURES if both[c]]
    print(f"  {d:<14}{int(s.sum()):>8}/39{int(rp.sum()):>8}/39{int(both.sum()):>8}/39   "
          + ", ".join(tagged[:6]) + (" …" if len(tagged) > 6 else ""))
print("\n  * = 멘토 확정 도메인 쌍")
print("  → 통계+RF 만으로는 못 거른다. 도메인 게이트가 실제로 후보를 줄이고 있다는 뜻이다.")

# ==================================================================== TEST 3
print("\n" + "=" * 78)
print("  TEST 3 — 데이터만으로 RF 순위를 매겼을 때 멘토 확정 인자의 위치")
print("=" * 78)
for d in DEFECTS:
    t = rf[d].loc[list(FEATURES)].sort_values("rank")
    mine = sorted([f for (dd, f) in DOMAIN_PAIRS if dd == d], key=lambda f: rf[d].loc[f, "rank"])
    print(f"\n  ── {d}   (멘토 확정 {len(mine)}건) · 데이터만으로 뽑은 상위 8개")
    for f, row in t.head(8).iterrows():
        print(f"       {row['rank']:>2}위  {f:<28}" + ("  ★ 멘토 확정" if (d, f) in DOMAIN_PAIRS else ""))
    print("     멘토 확정 위치: " + " · ".join(f"{f}({rf[d].loc[f,'rank']}위)" for f in mine))

print("\n" + "=" * 78)
print("  요약")
print("=" * 78)
for topn in (3, 5, 10):
    hit = sum(1 for (d, f) in DOMAIN_PAIRS if rf[d].loc[f, "rank"] <= topn)
    print(f"    멘토 확정 11쌍 중 상위 {topn:>2}위 이내 : {hit}/11 건")
worst = min(min(rf[d].loc[f, "rank"] for d in DEFECTS) for f in FAKE)
print(f"\n    플라시보 {'⭕ 통과 0번' if ok else '❌ 가짜가 합격선을 넘었다 — 발표에 쓰지 말 것'}"
      f"  (가장 높이 올라간 가짜 {worst}/{len(ALLF)}위, 합격선 {cut}위)")
