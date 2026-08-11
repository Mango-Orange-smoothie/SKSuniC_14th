"""원인 변수 경보의 **규모**를 집계한다 — early_warning_active(boolean)가 못 보여주는 것.

  python3 docs/check_alert_scale.py

자세한 해석은 docs/점검_원인변수_경보기준.md 참고.
"""

from pathlib import Path
import json

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ALERTS = REPO / "analysis_outputs/trend_analysis_results.csv"
SNAPSHOT = REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우/health_index_data.json"
REL_DB = REPO / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/agent_cause_factors.json"


def main() -> None:
    with open(REL_DB, encoding="utf-8") as f:
        db = json.load(f)
    factors = sorted({**db["cause_factors"], **db.get("monitor_factors", {})})

    t = pd.read_csv(ALERTS, low_memory=False)
    t["d"] = pd.to_datetime(t["DateTime"]).dt.date
    end = t["d"].max()

    with open(SNAPSHOT, encoding="utf-8") as f:
        snap = json.load(f)
    dur, hi, margin = {}, {}, {}
    for m, x in snap["machines"].items():
        for sig in x["defect_signals"].values():
            for fac, c in (sig.get("causes") or {}).items():
                dur[(m, fac)] = c.get("alert_active_days")
                hi[(m, fac)] = c.get("health_index")
                margin[(m, fac)] = c.get("margin_used_pct")

    rows = []
    for (m, col), g in t[t["column"].isin(factors)].groupby(["Machine_ID", "column"]):
        rows.append({
            "장비": m, "인자": col,
            "경보행": len(g),
            "그룹": f"{g.groupby(['Product_ID', 'Recipe_ID']).ngroups}/54",
            "경보일수": f"{g['d'].nunique()}/89",
            "마지막": (end - g["d"].max()).days,
            "지속일": dur.get((m, col)),
            "HI": hi.get((m, col)),
            "margin%": margin.get((m, col)),
        })
    df = pd.DataFrame(rows).sort_values("경보행", ascending=False)

    print(f"로그 마지막 {end} · 전체 {len(t):,}행\n")
    print("=== 확정 원인 인자의 경보 규모 (경보행 내림차순) ===")
    print(df.to_string(index=False))

    near = int((df["마지막"] <= 3).sum())
    print(f"\n마지막 경보가 3일 이내인 조합: {near}/{len(df)}")
    print("=> early_warning_active(마지막 경보 1일 이내)는 사실상 상시 ON\n")

    top = df.head(4)
    rest = df.iloc[4:]
    print("상위 4개 vs 나머지")
    print(f"  상위 4개 경보행 : {top['경보행'].min():,} ~ {top['경보행'].max():,}")
    print(f"  나머지  경보행 : {rest['경보행'].min():,} ~ {rest['경보행'].max():,}")
    print(f"  => 경계 {top['경보행'].min() / rest['경보행'].max():.1f}배\n")

    quiet = df[(df["margin%"].notna()) & (df["margin%"] < 2.5) & (df["지속일"].notna())]
    print("margin 2.5% 미만인데 경보가 켜진 조합 (짧은 경보)")
    print(quiet[["장비", "인자", "HI", "margin%", "지속일", "경보행"]].to_string(index=False))

    # (26.08.11) 위 문제의 조치 결과 — 경보를 세기로 갈랐다(docs/점검_원인변수_경보기준.md §5).
    # 여기서 재는 건 "갈라졌나"가 아니라 **두 무리의 HI 범위가 겹치나**다. 겹치면 배지
    # 색과 옆 점수가 여전히 다른 말을 하고 있다는 뜻이라 갈랐어도 소용이 없다.
    lt = pd.read_csv(REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우"
                            "/01_level_trend_by_machine_column.csv")
    act = lt[lt["early_warning_active"]]
    print(f"\n=== 경보 세기 (전체 {len(lt)}개 조합 중 활성 {len(act)}건) ===")
    for lv in ("full", "early"):
        sub = act[act["alert_level"] == lv]
        if not len(sub):
            continue
        print(f"  {lv:<5} {len(sub):>3}건 · HI {sub['health_index'].min():>5.1f} ~ "
              f"{sub['health_index'].max():>5.1f} · 지속일 {sub['alert_active_days'].min():.1f} ~ "
              f"{sub['alert_active_days'].max():.1f}")
    lo = act[act["alert_level"] == "full"]["health_index"].max()
    hi_ = act[act["alert_level"] == "early"]["health_index"].min()
    print(f"  => HI 범위 {'겹침 없음' if lo < hi_ else '겹침!'} (full 최고 {lo} < early 최저 {hi_})")


if __name__ == "__main__":
    main()
