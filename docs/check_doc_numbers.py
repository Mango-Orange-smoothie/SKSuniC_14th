"""문서에 적힌 "현재 상태" 수치를 산출물에서 다시 재서 한 화면에 띄운다.

  python3 docs/check_doc_numbers.py

왜 — 라벨 확장(26.08.11) · 변동성 경보 제거(26.08.16) · "접근" 판정 제거(26.08.17)를
거치면서 문서 수치가 여러 세대로 갈렸다. 어느 문서가 어느 세대인지 사람이 기억으로
구분하면 반드시 섞인다. 발표 전에 이걸 돌려서 인용할 수치를 확인한다.

이 스크립트는 파이프라인을 다시 돌리지 않는다 — 산출물을 읽기만 한다.
값이 문서와 다르면 파이프라인이 아니라 **문서를 고쳐야 한다**
(파이프라인 재현은 build_health_index.py를 직접 실행해서 확인할 것).
"""
from pathlib import Path
import sys

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "docs"))
from check_cusum_params import episodes  # noqa: E402

D = REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우"
MACHINES = ["DP01", "DP02", "DP03", "DP04"]


def main():
    lv = pd.read_csv(D / "01_level_trend_by_machine_column.csv", encoding="utf-8-sig")
    d2 = pd.read_csv(D / "02_health_index_by_defect.csv", encoding="utf-8-sig")
    mc = pd.read_csv(D / "03_health_index_by_machine.csv", encoding="utf-8-sig")
    on = lv[lv.early_warning_active == True]                            # noqa: E712

    print("=" * 72)
    print("[1] 장비 점수")
    for _, r in mc.iterrows():
        w = d2[(d2.Machine_ID == r.Machine_ID)].sort_values("health_index").iloc[0]
        sub = lv[(lv.Machine_ID == r.Machine_ID) & (lv["column"] == w.worst_factor)].iloc[0]
        sigma = abs(sub.control_usl - sub.baseline_median) / 3.0
        dev = abs(sub.current_value - sub.baseline_median) / sigma
        print(f"    {r.Machine_ID}  HI {r.health_index:>5.1f}  1순위 {w.defect:<12}"
              f"주범 {w.worst_factor:<18}목표값에서 {dev:.2f}σ")

    print("\n[2] 불량별 점수 (02_health_index_by_defect.csv)")
    piv = d2.pivot(index="Machine_ID", columns="defect", values="health_index")
    print(piv[["Chipping", "Particle", "Remain_Coat", "Micro_Crack"]].to_string())
    print("    (Micro_Crack은 repro_state=실패라 장비 점수 계산에 불참)")

    print("\n[3] 변수 표 (01_level_trend_by_machine_column.csv)")
    print(f"    행 {len(lv)} = 장비 {lv.Machine_ID.nunique()} x 컬럼 {lv['column'].nunique()}")
    print(f"    spec_source: {lv.spec_source.value_counts().to_dict()}")
    print(f"    spec_status: {lv.spec_status.value_counts().to_dict()}")
    print(f"    margin > 100%(관리한계 초과) {int((lv.margin_used_pct > 100).sum())}행 "
          f"· margin 최대 {lv.margin_used_pct.max()}%")
    print(f"    HI < 10점 {int((lv.health_index < 10).sum())}행 "
          f"· < 20점 {int((lv.health_index < 20).sum())}행")
    print(f"    is_cause_factor=True {int(lv.is_cause_factor.sum())}행")

    print("\n[4] 경보 세기 — boolean이 아니라 alert_level로 읽을 것")
    full, early = on[on.alert_level == "full"], on[on.alert_level == "early"]
    print(f"    활성 경보 {len(on)}건 = full {len(full)}건 + early {len(early)}건 "
          f"· 없음 {len(lv) - len(on)}행")
    print(f"    full  HI {full.health_index.min()} ~ {full.health_index.max()}")
    print(f"    early HI {early.health_index.min()} ~ {early.health_index.max()}")
    print(f"    겹침 없음: {full.health_index.max() < early.health_index.min()}")
    print(f"    장비별 활성 경보 {on.groupby('Machine_ID').size().to_dict()}")
    print(f"    지속일 중앙값 {on.alert_active_days.median()}일 "
          f"· 14일 미만 {int((on.alert_active_days < 14).sum())}건")
    print(f"    기울기 음수(개선 중인데 페널티) {int((on.margin_trend_pct_per_day < 0).sum())}건 "
          f"({(on.margin_trend_pct_per_day < 0).mean() * 100:.0f}%)")
    print(f"    성숙도-기울기 순위상관 "
          f"{on.alert_active_days.corr(on.margin_trend_pct_per_day, method='spearman'):.3f}")
    print(f"    확정 원인이 아닌데 경보 켜진 컬럼 {int((~on.is_cause_factor.fillna(False)).sum())}건")

    print("\n[5] 경보 로그 (analysis_outputs/trend_analysis_results.csv)")
    tr = pd.read_csv(REPO / "analysis_outputs/trend_analysis_results.csv", low_memory=False,
                     encoding="utf-8-sig",
                     usecols=["DateTime", "Machine_ID", "Product_ID", "Recipe_ID",
                              "column", "early_warning"])
    w = tr[tr.early_warning == True].copy()                             # noqa: E712
    w["DateTime"] = pd.to_datetime(w["DateTime"])
    print(f"    경보행 {len(w):,} · 감시 컬럼 {w['column'].nunique()}개")

    ep = episodes(w)
    print(f"\n    (장비x컬럼) 단위")
    print(f"    {'장비':<7}{'에피소드':>9}{'14일↑':>8}{'최장(일)':>10}")
    for m in MACHINES:
        e = ep[ep.machine == m]
        print(f"    {m:<7}{len(e):>9}{int((e.days >= 14).sum()):>8}{e.days.max():>10.1f}")
    print(f"    14일↑ 합계 {int((ep.days >= 14).sum())}건 "
          f"— **끝난 경보까지 포함**한 수다.")
    print(f"\n    ** 발표 자료가 쓰는 '14일 이상 지속' = 지금 켜져 있는 것만 "
          f"= alert_level 'full' = {len(full)}건 "
          f"({on[on.alert_level == 'full'].groupby('Machine_ID').size().to_dict()}).")
    print(f"       판정근거_정리 §4-4와 같은 정의다. 위 {int((ep.days >= 14).sum())}건과 "
          f"섞어 쓰지 말 것. **")

    rows = []
    for (m, p, r, c), g in w.groupby(["Machine_ID", "Product_ID", "Recipe_ID", "column"]):
        t = g.DateTime.sort_values()
        run = (t.diff() > pd.Timedelta(days=1)).cumsum()
        for _, s in t.groupby(run):
            rows.append((m, (s.max() - s.min()) / pd.Timedelta(days=1)))
    se = pd.DataFrame(rows, columns=["machine", "days"])
    print(f"\n    스트림(장비x제품x레시피x컬럼) 단위 — ARL 예측치와 비교할 단위")
    print(f"    {'장비':<7}{'에피소드':>9}{'하루평균':>9}{'14일↑':>8}{'최장(일)':>10}")
    for m in MACHINES:
        e = se[se.machine == m]
        print(f"    {m:<7}{len(e):>9}{len(e)/89:>9.1f}{int((e.days >= 14).sum()):>8}"
              f"{e.days.max():>10.1f}")
    print("\n    ** 두 단위를 섞어 쓰지 말 것. 발표에서 인용할 땐 단위를 같이 적는다. **")
    print("=" * 72)


if __name__ == "__main__":
    main()
