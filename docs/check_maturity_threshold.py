"""성숙도 기준일(14일)을 흔들어본다 — 결과가 그 값에 의존하는지 확인.

  python3 docs/check_maturity_threshold.py

14일은 "경보가 울리는 선"이 아니라 이미 울린 경보를 full/early로 가르는 선이다
(경보 자체는 trend_analysis.py의 CUSUM H=4.5σ가 켠다). 기존 근거는 "14일이 정상/고장을
완벽히 가른다"였는데, 그것만으로는 "왜 13도 15도 아닌 14냐"에 답이 안 된다.
여기서는 기준일 T를 쓸어서 **완전분리되는 T의 구간 전체**를 구한다.

결과 해석은 이 스크립트 출력의 [4] 절이 전부다 — 별도 검증 문서는 아직 없다.
"""

from pathlib import Path
import sys

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ALERTS = REPO / "analysis_outputs/trend_analysis_results.csv"

# 상수는 재정의하지 않고 대시보드 쪽 단일 출처에서 가져온다(trend_analysis의 CUSUM_K를
# build_health_index가 import해 쓰는 것과 같은 방식). 여기서 새 튜닝값을 만들면
# "14일이 특별하지 않다"는 이 문서의 결론 자체가 무의미해진다.
sys.path.insert(0, str(REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우"))
from build_health_index import (  # noqa: E402
    RECENT_WINDOW_DAYS,             # = 14. 지금 쓰는 성숙도 기준
    TREND_WARNING_ACTIVE_WITHIN_DAYS,  # = 1. 경보 이어붙이기 간격
)

# 멘토 확정 주입 시나리오. DP01만 정상이라 "오탐" 표본은 1대뿐이다(문서 §5 주의).
NORMAL = "DP01"
FAULTY = ["DP02", "DP03", "DP04"]
SCENARIO = {"DP01": "(없음)", "DP02": "Laser Aging",
            "DP03": "Cooling Failure", "DP04": "Cleaning Failure"}

SWEEP = [1, 2, 3, 4, 5, 7, 10, 14, 21, 28, 35, 39, 40, 42, 50, 60]


def active_alert_days() -> pd.DataFrame:
    """(장비, 컬럼)별 '지금 활성인 경보가 며칠째인가'.

    build_health_index.load_trend_status()와 같은 절차다 — 경보 간격이
    TREND_WARNING_ACTIVE_WITHIN_DAYS 이내면 같은 상태가 이어진 것으로 이어붙이고,
    마지막 경보가 그 안에 있으면 지금도 켜져 있는 것으로 본다. 샷 단위 early_warning
    행을 그대로 세면 안 된다(그러면 정상 장비 DP01에서도 컬럼이 우수수 뜬다).
    """
    tr = pd.read_csv(ALERTS, usecols=["DateTime", "Machine_ID", "column"])
    tr["DateTime"] = pd.to_datetime(tr["DateTime"])
    latest = tr["DateTime"].max()
    gap = pd.Timedelta(days=TREND_WARNING_ACTIVE_WITHIN_DAYS)

    rows = []
    for (machine, col), g in tr.groupby(["Machine_ID", "column"]):
        times = g["DateTime"].sort_values()
        if (latest - times.iloc[-1]) > gap:
            continue  # 지금은 꺼진 경보
        run_id = (times.diff() > gap).cumsum()
        since = times[run_id == run_id.iloc[-1]].min()
        rows.append({"machine": machine, "column": col,
                     "days": round((latest - since) / pd.Timedelta(days=1), 2)})
    return pd.DataFrame(rows), latest


def main() -> None:
    df, latest = active_alert_days()
    print(f"데이터 마지막 시각 {latest:%Y-%m-%d %H:%M} · 활성 경보 {len(df)}건 "
          f"(장비x컬럼) · 현재 성숙도 기준 {RECENT_WINDOW_DAYS}일\n")

    print("[1] 장비별 활성 경보")
    print(f"{'장비':<6}{'시나리오':<18}{'컬럼수':>6}{'지속일 합':>10}{'최장':>9}")
    for m in [NORMAL] + FAULTY:
        s = df[df.machine == m]["days"]
        print(f"{m:<6}{SCENARIO[m]:<18}{len(s):>6}{s.sum():>10.1f}{s.max():>9.2f}")

    print(f"\n[2] {NORMAL}(정상)의 최장 경보 5개 — 완전분리 구간의 하한을 정하는 값")
    for _, r in df[df.machine == NORMAL].nlargest(5, "days").iterrows():
        print(f"    {r['column']:<22}{r['days']:>7.2f}일")

    print("\n[3] 기준일 T 스윕 — T일 이상 지속된 경보 개수")
    print(f"{'T(일)':>6}{NORMAL:>7}" + "".join(f"{m:>6}" for m in FAULTY) + "   판별")
    perfect = []
    for T in SWEEP:
        cnt = {m: int((df[df.machine == m].days >= T).sum())
               for m in [NORMAL] + FAULTY}
        ok = cnt[NORMAL] == 0 and all(cnt[m] >= 1 for m in FAULTY)
        if ok:
            perfect.append(T)
        mark = "완전분리" if ok else ("오탐" if cnt[NORMAL] else "미탐")
        now = "  <- 현재값" if T == RECENT_WINDOW_DAYS else ""
        print(f"{T:>6}{cnt[NORMAL]:>7}" + "".join(f"{cnt[m]:>6}" for m in FAULTY)
              + f"   {mark}{now}")

    # 구간의 정확한 경계는 스윕 격자가 아니라 실측 지속일에서 직접 나온다.
    lo = df[df.machine == NORMAL].days.max()          # 이 값 초과여야 오탐 0
    tops = {m: df[df.machine == m].days.max() for m in FAULTY}
    hi = min(tops.values())                            # 이 값 이하여야 미탐 0
    slowest = min(tops, key=tops.get)

    print(f"\n[4] 완전분리(3/3 탐지, 0/1 오탐) 구간")
    print(f"    하한 {lo:.2f}일 초과  <- {NORMAL} 최장 경보")
    print(f"    상한 {hi:.2f}일 이하  <- {slowest} 최장 경보(고장 3대 중 가장 짧음)")
    print(f"    갭 {hi / lo:.1f}배 · 스윕 격자에서 통과한 T: {perfect}")

    if lo < RECENT_WINDOW_DAYS <= hi:
        print(f"\n=> {RECENT_WINDOW_DAYS}일은 이 구간 안이고, 하한에서 "
              f"{RECENT_WINDOW_DAYS / lo:.1f}배 / 상한까지 {hi / RECENT_WINDOW_DAYS:.1f}배 여유가 있다.")
        print("   결론이 14라는 값에 의존하지 않는다 = 14를 잘 골라서 맞은 게 아니다.")
    else:
        print(f"\n=> [경고] {RECENT_WINDOW_DAYS}일이 완전분리 구간을 벗어났다. "
              "데이터가 바뀌었으니 기준일을 다시 판단해야 한다.")


if __name__ == "__main__":
    main()
