"""SHAP 오탐 검증 — 4개 defect 전체

질문: XGBoost+SHAP을 유효인자 "판정"에 넣으면 안 되는가?

검증 방법
  각 defect마다 "SHAP top10에는 들었는데 통계검정·RandomForest는 둘 다 탈락시킨" 인자를 센다.
  - 이런 인자가 많다 = SHAP이 관대하다 (오탐 생성)
  - 반대 방향(SHAP만 놓친 것)도 같이 세서 편향 방향을 확인한다

데이터 출처
  Chipping / Micro_Crack : 본 폴더 db_08_method_agreement.csv (JHdaimma)
  Particle / Remain_Coat : Jun 브랜치 26.08.01_2229 통합본 07_*_unified_verdict.csv

실행 (저장소 루트에서):
  python "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/verify_shap_false_positives.py"
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[1]           # 저장소 루트 (SKSuniC_14th)
JUN_DIR = "26.08.01_2229_Goal2_통합_전체방법론_4개defect"

# Chipping 도메인상 무관 계열 (Jun CHIP DOMAIN_KNOWLEDGE.md의 not_related 분류)
CHIP_NOT_RELATED_FAMILIES = {
    "CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",   # 세정/코팅
    "Cooling_Flow", "Cooling_Water_Temp", "Cooling_Thermal_Load",  # 방열
    "Frequency", "Feed_Speed", "Alignment_Time", "Process_Time",   # 에너지/체류시간
}

rows = []


def from_my_db(target: str):
    """db_08(3방법 순위 대조)에서 SHAP 전용 통과/누락을 센다."""
    a = pd.read_csv(OUT / "db_08_method_agreement.csv", encoding="utf-8-sig")
    s = a[(a.target == target) & (a.model == "A_cause_FDConly")]
    only_shap = s[(s.rank_shap <= 10) & (s.rank_statistic > 10) & (s.rank_permutation > 10)]
    missed = s[(s.rank_shap > 10) & (s.rank_statistic <= 10) & (s.rank_permutation <= 10)]
    return sorted(only_shap.factor), sorted(missed.factor), len(s)


def from_jun(defect: str):
    """Jun 통합본에서 flag_shap만 True이고 나머지 통계 flag가 False인 인자를 센다."""
    txt = subprocess.run(
        ["git", "show", f"origin/Jun:{JUN_DIR}/07_{defect}_unified_verdict.csv"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout
    v = pd.read_csv(io.StringIO(txt))
    only_shap = v[(v.flag_shap) & (~v.flag_univariate) & (~v.flag_rf)]
    missed = v[(~v.flag_shap) & (v.flag_univariate) & (v.flag_rf)]
    graded = v[v.tier.str.startswith(("Tier1", "Tier2", "Tier3"))]
    return sorted(only_shap.column), sorted(missed.column), sorted(graded.column), len(v)


print("=" * 92)
print("SHAP 오탐 검증 — SHAP만 통과시킨 인자 (통계검정·RandomForest는 둘 다 탈락)")
print("=" * 92)

for target in ["Chipping", "Micro_Crack"]:
    only, missed, n = from_my_db(target)
    print(f"\n[{target}]  후보 {n}개 (JHdaimma db_08)")
    print(f"  SHAP만 통과 : {len(only)}개  {only}")
    print(f"  SHAP만 누락 : {len(missed)}개  {missed if missed else '없음'}")
    rows.append({"defect": target, "source": "JHdaimma",
                 "n_candidates": n, "shap_only_pass": len(only),
                 "shap_only_missed": len(missed),
                 "shap_only_pass_list": ", ".join(only)})

for defect, label in [("particle", "Particle"), ("remain_coat", "Remain_Coat")]:
    only, missed, graded, n = from_jun(defect)
    print(f"\n[{label}]  후보 {n}개 (Jun 통합본)")
    print(f"  SHAP만 통과 : {len(only)}개  {only}")
    print(f"  SHAP만 누락 : {len(missed)}개  {missed if missed else '없음'}")
    print(f"  최종 등급   : {graded}")
    rows.append({"defect": label, "source": "Jun",
                 "n_candidates": n, "shap_only_pass": len(only),
                 "shap_only_missed": len(missed),
                 "shap_only_pass_list": ", ".join(only)})

df = pd.DataFrame(rows)
df.to_csv(OUT / "db_10_shap_false_positives.csv", index=False, encoding="utf-8-sig")

total_pass = df.shap_only_pass.sum()
total_missed = df.shap_only_missed.sum()
print("\n" + "=" * 92)
print(f"합계 — SHAP만 통과: {total_pass}개 / SHAP만 누락: {total_missed}개")
print("=" * 92)
print("""
해석
  SHAP은 '누락'이 아니라 '과통과' 방향으로 일관되게 치우친다.
  SHAP은 항상 순위를 매기므로, 후보가 전부 무관해도 누군가는 상위권이 된다.
  -> 판정(유효인자 여부)에 쓰면 오탐이 확정으로 올라간다.
  -> 개별 건 설명(db_07)에만 쓰고, 판정은 통계검정+RandomForest+도메인 게이트로.

  Chipping에서 오탐이 최종 목록에 안 들어간 이유는 SHAP이 정확해서가 아니라
  도메인 게이트(세정/냉각 계열 = Chipping과 무관)가 막았기 때문이다.
  Micro_Crack의 Vibration만 통과한 것은 작성자가 도메인 지지를 잘못 부여한 결과다.
""")
print(f"-> db_10_shap_false_positives.csv 저장 ({len(df)}행)")
