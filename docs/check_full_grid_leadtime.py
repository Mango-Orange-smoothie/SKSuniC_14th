"""전체 조합(장비 x 컬럼) 탐지 격자 — CUSUM 지속경보 vs 관리도(3σ) 최초 이탈.

  python3 docs/check_full_grid_leadtime.py

왜 만들었나 — 지금까지 리드타임은 확정 시나리오 3짝(DP02 Laser_Power / DP03 Head_Temp /
DP04 CLN_Flow)에서만 보고했다. "나머지 컬럼은?"에 답할 수 있어야 한다.

정답(고장 시작일)은 3짝 말고는 없다. 그래서 정답이 필요 없는 기준으로 잰다 —
**같은 데이터·같은 baseline에서 관리도(Shewhart 3σ)가 언제 잡았을까**와 비교한다.
관리도는 교과서 절차라 우리가 튜닝할 여지가 없으므로 공정한 대조군이 된다.

정의
  CUSUM 탐지일  = (장비, 제품, 레시피, 컬럼) 스트림에서 14일 이상 지속된 경보의 최초 시작일
                  (장비x컬럼으로 이어붙이지 않는다 — 그러면 다른 그룹의 깜빡임이 이어져 부풀려진다)
  관리도 탐지일 = 그 조합의 일평균이 target ± 3σ 밖으로 나가 3일 이상 유지되는 첫날
  선행일       = 관리도 탐지일 - CUSUM 탐지일  (양수면 CUSUM이 먼저)
"""
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data/raw/DP_HealthIndex_Dataset.csv"
BASE = REPO / "analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv"
ALERTS = REPO / "analysis_outputs/trend_analysis_results.csv"

SUSTAINED_DAYS = 14      # build_health_index의 성숙도 기준과 동일
GAP_DAYS = 1
SIGMA = 3.0              # Shewhart 관리한계
CTRL_PERSIST_DAYS = 3    # 관리도 쪽도 "한 번 튄 것"은 안 센다(1점 규칙이 아니라 유지 조건)


def cusum_detection():
    tr = pd.read_csv(ALERTS, low_memory=False, encoding="utf-8-sig",
                     usecols=["DateTime", "Machine_ID", "Product_ID", "Recipe_ID",
                              "column", "early_warning"])
    tr = tr[tr.early_warning == True]                                   # noqa: E712
    tr["DateTime"] = pd.to_datetime(tr["DateTime"])
    rows = []
    for (m, p, r, c), g in tr.groupby(["Machine_ID", "Product_ID", "Recipe_ID", "column"]):
        t = g.DateTime.sort_values()
        run = (t.diff() > pd.Timedelta(days=GAP_DAYS)).cumsum()
        for _, s in t.groupby(run):
            days = (s.max() - s.min()) / pd.Timedelta(days=1)
            if days >= SUSTAINED_DAYS:
                rows.append({"Machine_ID": m, "Product_ID": p, "Recipe_ID": r,
                             "column": c, "cusum_date": s.min().normalize(), "days": days})
    ep = pd.DataFrame(rows)
    return ep.sort_values("cusum_date").groupby(
        ["Machine_ID", "Product_ID", "Recipe_ID", "column"], as_index=False).first()


def control_detection(cols):
    base = pd.read_csv(BASE, encoding="utf-8-sig")
    base = base[base["column"].isin(cols)].set_index(["Product_ID", "Recipe_ID", "column"])
    raw = pd.read_csv(RAW, encoding="utf-8-sig",
                      usecols=["DateTime", "Machine_ID", "Product_ID", "Recipe_ID"] + list(cols))
    raw["date"] = pd.to_datetime(raw["DateTime"]).dt.normalize()
    long = raw.melt(id_vars=["date", "Machine_ID", "Product_ID", "Recipe_ID"],
                    value_vars=list(cols), var_name="column", value_name="v").dropna(subset=["v"])
    daily = long.groupby(["Machine_ID", "Product_ID", "Recipe_ID", "column", "date"],
                         as_index=False)["v"].mean()
    key = daily.set_index(["Product_ID", "Recipe_ID", "column"]).index
    daily["target"] = base["median"].reindex(key).values
    daily["sd"] = base["std"].reindex(key).values
    daily = daily.dropna(subset=["target", "sd"])
    daily["out"] = (daily.v - daily.target).abs() > SIGMA * daily.sd

    rows = []
    for k, g in daily.sort_values("date").groupby(
            ["Machine_ID", "Product_ID", "Recipe_ID", "column"]):
        o = g.out.values
        dates = g.date.values
        for i in range(len(o) - CTRL_PERSIST_DAYS + 1):
            if o[i:i + CTRL_PERSIST_DAYS].all():
                rows.append(dict(zip(["Machine_ID", "Product_ID", "Recipe_ID", "column"], k),
                                 **{"ctrl_date": pd.Timestamp(dates[i])}))
                break
    return pd.DataFrame(rows)


def main():
    cu = cusum_detection()
    cols = sorted(cu["column"].unique())
    ct = control_detection(cols)
    df = cu.merge(ct, on=["Machine_ID", "Product_ID", "Recipe_ID", "column"], how="left")
    df["lead"] = (df.ctrl_date - df.cusum_date) / pd.Timedelta(days=1)

    print(f"CUSUM 지속경보(>={SUSTAINED_DAYS}일)가 뜬 스트림 {len(df)}개 "
          f"· 감시 컬럼 {len(cols)}개 · 장비 4대\n")

    print("[1] 장비별")
    print(f"{'장비':<7}{'지속경보 스트림':>14}{'관리도도 잡음':>13}{'관리도가 못잡음':>15}{'평균 선행(일)':>13}{'중앙':>7}")
    for m in ["DP01", "DP02", "DP03", "DP04"]:
        g = df[df.Machine_ID == m]
        hit = g.dropna(subset=["ctrl_date"])
        print(f"{m:<7}{len(g):>14}{len(hit):>13}{len(g) - len(hit):>15}"
              f"{hit.lead.mean() if len(hit) else float('nan'):>13.1f}"
              f"{hit.lead.median() if len(hit) else float('nan'):>7.1f}")

    print("\n[2] 컬럼별 (지속경보가 뜬 컬럼만)")
    print(f"{'컬럼':<26}{'스트림':>7}{'관리도':>7}{'평균선행':>9}{'CUSUM이 먼저':>12}")
    for c, g in df.groupby("column"):
        hit = g.dropna(subset=["ctrl_date"])
        first = (hit.lead > 0).sum()
        print(f"{c:<26}{len(g):>7}{len(hit):>7}"
              f"{(hit.lead.mean() if len(hit) else float('nan')):>9.1f}{first:>12}")

    hit = df.dropna(subset=["ctrl_date"])
    print(f"\n[3] 전체")
    print(f"    지속경보 스트림 {len(df)}개 중 관리도도 잡은 것 {len(hit)}개 "
          f"({len(hit)/len(df)*100:.1f}%)")
    print(f"    CUSUM이 먼저 {int((hit.lead > 0).sum())}개 / 같은 날 {int((hit.lead == 0).sum())}개 "
          f"/ 관리도가 먼저 {int((hit.lead < 0).sum())}개")
    print(f"    평균 선행 {hit.lead.mean():.1f}일 · 중앙값 {hit.lead.median():.1f}일 "
          f"· 최대 {hit.lead.max():.0f}일")
    print(f"    관리도가 끝까지 못 잡은 스트림 {len(df) - len(hit)}개 "
          f"({(len(df)-len(hit))/len(df)*100:.1f}%) — CUSUM만 잡은 열화")

    out = REPO / "docs/발표_표_전체격자_리드타임.csv"
    df.sort_values(["Machine_ID", "column"]).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n    상세: {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
