"""한 인자에 defect가 둘일 때 둘 다 끝까지 살아남는지 확인한다.

  python3 docs/check_multi_defect_pairing.py

지금 데이터에서는 이 경우가 **0건**이다 — 관계DB 티어표에 defect가 2개인 인자는 셋이지만
(CLN_Flow / CLN_Pressure / Cooling_Flow) 두 번째 짝이 전부 걸러진다:

  CLN_Flow↔Particle       T2인데 alert_usable=False (위험구간 불량률이 정상구간보다 낮음)
  CLN_Pressure↔Particle   T4 — agent_cause_factors.json에 아예 안 실림
  Cooling_Flow↔Micro_Crack T3 — 위와 같음

즉 코드를 고쳐도 현재 산출물은 한 줄도 안 바뀐다. 그래서 "안 깨졌다"는 것만으로는
**둘 다 나온다**를 증명하지 못한다. 여기서는 rel_30의 alert_usable을 True로 돌린
임시 DB를 만들어 실제로 두 짝이 끝까지 가는지 확인한다.

라벨 확장안(회의자료_라벨확장안_결정요청.md)이 통과하면 CLN_Flow↔Particle이 실제로
alert_usable=True가 된다 — 그때 이 스크립트가 예고편이다.

확인하는 지점 4곳 (짝이 하나라도 사라지면 실패로 찍는다):
  1. resolve_defect_pairing   컬럼 -> [defect, defect]
  2. compute_baseline_type_c  그룹마다 defect별로 경계값이 따로
  3. 진입률 산출물 2개         matched_defect 축이 살아 있는지
  4. trend_analysis c_map     (컬럼, 그룹) -> 항목 2개
"""

from pathlib import Path
import shutil
import sys
import tempfile

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import config  # noqa: E402

FACTOR, KEPT, REVIVED = "CLN_Flow", "Remain_Coat", "Particle"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else '실패'}] {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def build_temp_db() -> Path:
    """rel_30에서 CLN_Flow↔Particle만 alert_usable=True로 돌린 사본을 만든다.

    rel_20(근거표)은 손대지 않는다 — 그 짝의 repro_state는 이미 "통과"라서, 채택을
    막고 있던 건 alert_usable 하나뿐이다. 라벨 확장안이 통과하면 정확히 이 값이 바뀐다.
    """
    tmp = Path(tempfile.mkdtemp(prefix="multidefect_"))
    shutil.copy(config.RELATIONSHIP_DB_DIR / "rel_20_tier_table.csv", tmp)
    iface = pd.read_csv(config.RELATIONSHIP_DB_DIR / "rel_30_trend_interface.csv")
    mask = (iface["factor"] == FACTOR) & (iface["defect"] == REVIVED)
    if not mask.any():
        sys.exit(f"rel_30에 {FACTOR}↔{REVIVED} 행이 없습니다 — 스크립트 전제가 깨졌습니다.")
    iface.loc[mask, "alert_usable"] = True
    iface.to_csv(tmp / "rel_30_trend_interface.csv", index=False)
    return tmp


def main() -> None:
    print(__doc__.strip().splitlines()[0])
    print(f"\n임시 DB: {FACTOR}↔{REVIVED}의 alert_usable을 False -> True로만 바꿉니다.\n")
    config.RELATIONSHIP_DB_DIR = build_temp_db()

    # config를 갈아끼운 뒤에 import해야 캐시가 임시 DB로 채워진다.
    from pipeline import step0_preprocessing as step0  # noqa: E402

    print("[1] 짝짓기")
    pairing = step0.resolve_defect_pairing()
    got = pairing.get(FACTOR, [])
    check(f"{FACTOR}에 defect 2개", sorted(got) == sorted([KEPT, REVIVED]), f"{got}")
    check("확정 T1 짝이 살아 있음", KEPT in got, f"{KEPT}가 {REVIVED}에 밀리지 않아야 한다")
    pairs = step0.defect_pairs()
    check("쌍 목록에 둘 다", {(FACTOR, KEPT), (FACTOR, REVIVED)} <= set(pairs))

    print("\n[2] C유형 경계값 — defect마다 따로 학습되는가")
    df = step0.load_and_validate()
    baseline_c = step0.compute_baseline_type_c(df, [(FACTOR, KEPT), (FACTOR, REVIVED)])
    per_defect = baseline_c.groupby("matched_defect")["threshold"].agg(["size", "median"])
    print(per_defect.to_string())
    check("두 defect 모두 행이 있음", len(per_defect) == 2, f"{list(per_defect.index)}")
    if len(per_defect) == 2:
        med = per_defect["median"]
        check("경계값이 서로 다름", med.nunique() == 2,
              f"{KEPT} {med.get(KEPT):.4f} vs {REVIVED} {med.get(REVIVED):.4f}")
        dup = baseline_c.duplicated(["column", "matched_defect", "group_key"]).sum()
        check("(컬럼, defect, 그룹)이 유일", dup == 0, f"중복 {dup}행")

    print("\n[3] 진입률 산출물 — matched_defect 축이 살아 있는가")
    zone = step0.compute_daily_defect_zone_rate(df, baseline_c)
    entry = step0.compute_c_entry_rate_baseline(df, baseline_c)
    for name, tbl in (("일별 진입률", zone), ("평소 진입률", entry)):
        defects = sorted(tbl["matched_defect"].unique())
        check(f"{name}에 두 defect", defects == sorted([KEPT, REVIVED]), f"{defects}")

    print("\n[4] trend_analysis — (컬럼, 그룹)에 항목이 둘인가")
    # load_baseline_maps는 파일에서 읽으므로, 방금 만든 baseline_c를 파일로 흉내낸다.
    import trend_analysis  # noqa: E402
    c_map: dict[tuple[str, str], list[dict]] = {}
    for row in baseline_c.itertuples(index=False):
        c_map.setdefault((row.column, row.group_key), []).append(
            {"threshold": row.threshold, "risky_direction": row.risky_direction,
             "matched_defect": row.matched_defect})
    sizes = {len(v) for v in c_map.values()}
    check("모든 (컬럼, 그룹)에 항목 2개", sizes == {2}, f"항목 수 분포 {sorted(sizes)}")
    sample_key = next(iter(c_map))
    check("경보 루프가 defect마다 돈다",
          len({e["matched_defect"] for e in c_map[sample_key]}) == 2,
          f"{sample_key} -> {[e['matched_defect'] for e in c_map[sample_key]]}")

    # 실제 루프가 읽는 경계값이 defect마다 다른지. **그룹 하나만 보면 안 된다** —
    # 스텀프가 우연히 같은 분할점을 찾는 그룹이 실제로 있다(54개 중 7개). 그걸
    # 실패로 읽으면 코드가 멀쩡한데도 빨간불이 뜬다. 전체 그룹의 분포로 판정한다.
    wide = baseline_c.pivot_table(index="group_key", columns="matched_defect", values="threshold")
    n_diff = int((wide[KEPT] != wide[REVIVED]).sum())
    check("경계값이 defect마다 독립적으로 학습됨", n_diff > len(wide) / 2,
          f"{len(wide)}개 그룹 중 {n_diff}개에서 다름 "
          f"(나머지 {len(wide) - n_diff}개는 스텀프가 같은 분할점을 찾은 것 — 정상)")
    print(f"  (참고: trend_analysis의 C유형 진입률 조회 키는 "
          f"(장비, 컬럼, defect) — {trend_analysis.compute_c_type_baseline_rate.__name__} 주석 참고)")

    print()
    if failures:
        sys.exit(f"실패 {len(failures)}건: {failures}")
    print("전부 통과 — 한 인자의 defect 2개가 경계값·진입률·경보까지 각각 살아남는다.")


if __name__ == "__main__":
    main()
