"""Health Index 상수 3개(14일 / 0.45 / ALARM_BAND 10)를 흔들어 결론이 버티는지 본다.

  python3 docs/check_constant_sensitivity.py

배경 — K/H는 격자 스윕으로 구간을 잡아뒀는데(docs/판정근거_정리.md §4-4, docs/check_cusum_params.py)
Health Index 쪽 상수는 코드 주석에만 근거가 있고 격자로 재본 기록이 없었다.
"상수는 우리가 고른 값이지만 결론(장비 우선순위)은 그 값에 안 달려 있다"를 보이는 게 목적이다.

방법 — 파이프라인 산출물 01_level_trend_by_machine_column.csv의 중간값
(margin_used_pct, alert_active_days, estimated_days_to_control_limit)에서 build_health_index와
같은 식으로 점수를 다시 만든다. [0] 절에서 현행 상수로 원본 health_index를 정확히 재현하는지
먼저 확인하므로, 재현이 깨지면 이 스윕 결과도 믿으면 안 된다.
"""
from pathlib import Path
import sys
import itertools

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우"))
from build_health_index import (  # noqa: E402
    RECENT_WINDOW_DAYS, TREND_PENALTY_MAX_CUT, ALARM_BAND,
)

LEVELS = REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우/01_level_trend_by_machine_column.csv"
MACHINES = ["DP01", "DP02", "DP03", "DP04"]
# 멘토 확정 시나리오. 순위 판정은 "나쁜 순서"로 읽는다.
TRUTH_ORDER = ["DP04", "DP02", "DP03", "DP01"]


def score(df, denom=RECENT_WINDOW_DAYS, cut=TREND_PENALTY_MAX_CUT, band=ALARM_BAND):
    m = df["margin_used_pct"]
    level = pd.Series(
        [(band + (100 - band) * (1 - x / 100)) if x <= 100 else band * 100 / x for x in m],
        index=df.index)
    days = df["alert_active_days"].fillna(0.0)
    est = df["estimated_days_to_control_limit"]
    maturity = (days / denom).clip(upper=1.0)
    urgency = (denom / est).clip(upper=1.0).fillna(0.0)
    strength = pd.concat([maturity, urgency], axis=1).max(axis=1)
    hi = level.copy()
    hit = df["early_warning_active"].fillna(False) & (m <= 100)
    hi[hit] = band + (level[hit] - band) * (1 - cut * strength[hit])
    return hi.round(1), level, maturity, urgency, strength


def machine_scores(df, **kw):
    hi = score(df, **kw)[0]
    cause = df["is_cause_factor"].fillna(False)
    return {m: round(hi[cause & (df.Machine_ID == m)].min(), 1) for m in MACHINES}


def order(sc):
    return sorted(MACHINES, key=lambda m: sc[m])


def main():
    df = pd.read_csv(LEVELS, encoding="utf-8-sig")

    print(f"[0] 재현 확인 — 현행 상수({RECENT_WINDOW_DAYS}일 / {TREND_PENALTY_MAX_CUT} / {ALARM_BAND})로 산출물과 일치하나")
    hi = score(df)[0]
    diff = (hi - df["health_index"]).abs()
    print(f"    변수 180행 최대 오차 {diff.max():.2f}점 · 0.1점 초과 {int((diff > 0.1).sum())}행")
    base = machine_scores(df)
    print(f"    장비 점수 {base} / 산출물 DP01 85.0 DP02 47.6 DP03 50.8 DP04 14.5")

    print(f"\n[1] 상수 하나씩 ±50% — 나쁜 순서가 {' < '.join(TRUTH_ORDER)}로 유지되나")
    sweeps = [
        ("성숙도 분모(일)", "denom", [7, 10, RECENT_WINDOW_DAYS, 18, 21]),
        ("추세 페널티 폭", "cut", [0.0, 0.225, TREND_PENALTY_MAX_CUT, 0.675, 1.0]),
        ("경보밴드(=100-0.9M의 0.9)", "band", [5.0, 7.5, ALARM_BAND, 12.5, 15.0]),
    ]
    for label, key, vals in sweeps:
        print(f"\n  {label}")
        print(f"    {'값':>8}" + "".join(f"{m:>9}" for m in MACHINES) + "   순위")
        for v in vals:
            sc = machine_scores(df, **{key: v})
            ok = "유지" if order(sc) == TRUTH_ORDER else "**뒤집힘**"
            now = "  <- 현재값" if v == {"denom": RECENT_WINDOW_DAYS, "cut": TREND_PENALTY_MAX_CUT,
                                      "band": ALARM_BAND}[key] else ""
            print(f"    {v:>8}" + "".join(f"{sc[m]:>9.1f}" for m in MACHINES) + f"   {ok}{now}")

    print("\n[2] 세 상수 동시 스윕 (5x5x5 = 125조합)")
    flips = []
    for d, c, b in itertools.product([7, 10, 14, 18, 21], [0.0, 0.225, 0.45, 0.675, 1.0],
                                     [5.0, 7.5, 10.0, 12.5, 15.0]):
        sc = machine_scores(df, denom=d, cut=c, band=b)
        if order(sc) != TRUTH_ORDER:
            flips.append((d, c, b, sc))
    print(f"    순위가 뒤집힌 조합 {len(flips)} / 125")
    for f in flips[:10]:
        print(f"      denom={f[0]} cut={f[1]} band={f[2]} -> {f[3]}")

    print("\n[3] 이중 페널티 점검 — Level · 성숙도 S · 긴급도 U 상관 (경보 켜진 변수만)")
    hi, level, mat, urg, strg = score(df)
    on = df["early_warning_active"].fillna(False)
    sub = pd.DataFrame({"Level": level[on], "S": mat[on], "U": urg[on]})
    print(f"    표본 {len(sub)}행 (경보 활성 변수)")
    print("    Pearson")
    print(sub.corr().round(3).to_string())
    print("    Spearman")
    print(sub.corr(method="spearman").round(3).to_string())
    print(f"    U가 0이 아닌 행 {int((sub.U > 0).sum())} / {len(sub)}  "
          f"(estimated_days_to_control_limit이 비어 있으면 U=0)")
    print(f"    S가 1.0(성숙 완료)인 행 {int((sub.S >= 1.0).sum())}")

    print("\n[4] 바닥(ALARM_BAND=10) 근접도 — 20점 미만이 몇 개인가")
    cause = df["is_cause_factor"].fillna(False)
    print(f"    장비 4대 중 20점 미만: {[m for m in MACHINES if base[m] < 20]}")
    print(f"    변수 180행 중 20점 미만 {int((hi < 20).sum())}행 / "
          f"10점 미만(관리한계 초과) {int((hi < 10).sum())}행")
    print(f"    확정 원인 변수 {int(cause.sum())}행 중 20점 미만 {int((hi[cause] < 20).sum())}행")
    low = df[hi < 20][["Machine_ID", "column", "margin_used_pct"]].assign(health=hi[hi < 20])
    print(low.to_string(index=False))


if __name__ == "__main__":
    main()
