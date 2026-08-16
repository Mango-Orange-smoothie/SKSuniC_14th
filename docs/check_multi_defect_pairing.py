"""한 인자에 defect가 둘일 때 둘 다 끝까지 살아남는지 확인한다.

  python3 docs/check_multi_defect_pairing.py

(26.08.12) **임시 DB를 만들던 걸 걷어냈다.** 처음 만들 때(26.08.11)는 관계DB가 두 번째
짝을 전부 막고 있어서(CLN_Flow↔Particle이 alert_usable=False) "코드를 고쳐도 산출물이
한 줄도 안 바뀐다" 상태였고, 그래서 rel_30을 복사해 그 값만 True로 돌린 임시 DB로
예고편을 돌렸다. 라벨 확장안(PR #24)이 들어오면서 실제 DB가 그 값을 True로 바꿨으므로,
이제 **진짜 산출물을 그대로 검사**하면 된다 — 임시 패치는 이미 True인 값을 True로
덮는 무의미한 동작이 됐고, 검사 대상이 실제 설정과 달라질 위험만 남았다.

현재 관계DB 기준 다중 defect 인자는 둘이다(CLN_Flow / CLN_Pressure, 각각 Remain_Coat와
Particle). 하나도 없으면 이 스크립트는 검증할 게 없으므로 그 사실을 실패로 알린다 —
조용히 통과하면 "짝이 사라진 것"과 "잘 동작하는 것"을 구분할 수 없다.

확인하는 지점 4곳 (짝이 하나라도 사라지면 실패로 찍는다):
  1. resolve_defect_pairing   컬럼 -> [defect, defect]
  2. compute_baseline_type_c  그룹마다 defect별로 경계값이 따로
  3. 진입률 산출물 2개         matched_defect 축이 살아 있는지
  4. trend_analysis c_map     (컬럼, 그룹) -> 항목 2개

**방향 필터(CLAUDE.md 규칙 6)와 겹치는 지점에 주의한다.** compute_baseline_type_c는
그룹별 학습 방향이 관계DB와 반대면 그 그룹의 행을 안 만든다(CLN_Flow↔Particle이
54그룹 중 7개). 그래서 "모든 그룹에 항목이 2개"는 더 이상 성립하지 않는다 — 그걸
실패로 읽으면 두 기능이 다 멀쩡한데 빨간불이 뜬다. 항목이 1개인 그룹이 **방향 필터로
빠진 그룹과 정확히 일치하는지**를 대신 확인한다.
"""

from pathlib import Path
import sys

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import step0_preprocessing as step0  # noqa: E402
from pipeline.common import load_domain_directions  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if ok else '실패'}] {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def groups_without_threshold(df, factor: str, defect: str, expected_dir: str | None) -> set[str]:
    """이 짝의 경계값이 **정당한 이유로** 없어야 하는 그룹을 독립적으로 다시 구한다.

    이유는 둘뿐이다 — 스텀프가 아예 안 만들어지거나(표본 부족), 학습된 방향이 관계DB와
    반대라 CLAUDE.md 규칙 6으로 제외되거나. 그 외의 이유로 행이 없으면 짝이 조용히
    사라진 것이므로 잡아야 한다.

    **compute_baseline_type_c의 산출물을 쓰지 않는다.** 처음엔 그 결과에서 결측 그룹을
    세어 자기 자신과 비교했는데, 그러면 순환 논리라 무조건 통과한다 — 실제로 "짝을
    통째로 버리는" 회귀를 심어놓고 돌려도 이 검사만 OK로 떴다. 같은 스텀프 함수로
    필터 없이 다시 학습해서 비교 기준을 밖에서 만든다.
    """
    out: set[str] = set()
    for (product, recipe), g in df.groupby(["Product_ID", "Recipe_ID"]):
        result = step0._find_baseline_c_breakpoint(g[factor], g[defect])
        if result is None or (expected_dir is not None
                              and result["risky_direction"] != expected_dir):
            out.add(f"{product}|{recipe}")
    return out


def main() -> None:
    print(__doc__.strip().splitlines()[0])
    print("\n관계DB를 그대로 읽습니다(임시 패치 없음).\n")

    print("[0] 전제 — 관계DB에 defect가 둘인 인자가 있는가")
    pairing = step0.resolve_defect_pairing()
    multi = {f: d for f, d in pairing.items() if len(d) > 1}
    check("다중 defect 인자가 존재", bool(multi), f"{multi}")
    if not multi:
        sys.exit("검증할 다중 defect 짝이 없습니다 — 관계DB에서 두 번째 짝이 사라졌는지 확인하세요.")

    # **대표 하나만 고르지 않는다.** 처음엔 그렇게 썼는데, 지금 다중 defect 인자가 둘이고
    # 그중 방향 필터가 걸린 건 CLN_Flow 하나뿐이라 — 어느 쪽이 뽑히느냐에 따라 정작
    # 검사하려던 경로를 통째로 건너뛴다(실제로 CLN_Pressure가 뽑혀서 "방향 필터 제외 0개"만
    # 확인하고 끝났다). 전부 돈다.
    print(f"      추적 대상: {', '.join(f'{f}↔{"/".join(d)}' for f, d in sorted(multi.items()))}")

    print("\n[1] 짝짓기")
    pairs = step0.defect_pairs()
    for factor, defects in sorted(multi.items()):
        check(f"{factor}에 defect {len(defects)}개", len(pairing.get(factor, [])) == len(defects),
              f"{pairing.get(factor, [])}")
        check(f"{factor} 쌍 목록에 전부", {(factor, d) for d in defects} <= set(pairs))

    print("\n[2] C유형 경계값 — defect마다 따로 학습되는가")
    df = step0.load_and_validate()
    to_check = [(f, d) for f, defects in sorted(multi.items()) for d in defects]
    baseline_c = step0.compute_baseline_type_c(df, to_check)
    print(baseline_c.groupby(["column", "matched_defect"])["threshold"]
          .agg(["size", "median"]).to_string())
    dup = int(baseline_c.duplicated(["column", "matched_defect", "group_key"]).sum())
    check("(컬럼, defect, 그룹)이 유일", dup == 0, f"중복 {dup}행")

    # 인자별로 그룹×defect 경계값을 나란히 놓는다. 아래 [2]/[4]가 같이 쓴다.
    # dropped[factor] = 방향 필터가 그 인자의 두 번째 짝에서 뺀 그룹.
    wide: dict[str, pd.DataFrame] = {}
    dropped: dict[str, set] = {}
    for factor, defects in sorted(multi.items()):
        w = (baseline_c[baseline_c["column"] == factor]
             .pivot_table(index="group_key", columns="matched_defect", values="threshold")
             .reindex(columns=defects))
        wide[factor] = w
        dropped[factor] = set(w.index[w.isna().any(axis=1)])

    # **그룹 하나만 보면 안 된다** — 스텀프가 우연히 같은 분할점을 찾는 그룹이 실제로 있다.
    # 그걸 실패로 읽으면 코드가 멀쩡한데도 빨간불이 뜬다. 전체 그룹의 분포로 판정한다.
    # 방향 필터로 빠진 그룹은 애초에 비교 대상이 아니므로 분모에서 뺀다 — 예전엔 이걸
    # 섞어서 "54그룹 중 47개에서 다름(나머지 7개는 같은 분할점)"이라고 찍었는데, 그 7개는
    # 같은 분할점이 아니라 행 자체가 없는 그룹이었다(우연히 두 수가 같아 더 헷갈렸다).
    for factor, defects in sorted(multi.items()):
        w, both = wide[factor], wide[factor].dropna()
        a, b = defects[0], defects[1]
        n_diff = int((both[a] != both[b]).sum())
        check(f"{factor}: 경계값이 defect마다 독립적으로 학습됨", n_diff > len(both) / 2,
              f"둘 다 학습된 {len(both)}개 그룹 중 {n_diff}개에서 다름 "
              f"(같은 분할점 {len(both) - n_diff}개 · 방향 필터로 빠진 {len(dropped[factor])}개는 "
              f"비교 대상 아님, 전체 {len(w)}그룹)")

    print("\n[3] 진입률 산출물 — matched_defect 축이 살아 있는가")
    zone = step0.compute_daily_defect_zone_rate(df, baseline_c)
    entry = step0.compute_c_entry_rate_baseline(df, baseline_c)
    for name, tbl in (("일별 진입률", zone), ("평소 진입률", entry)):
        for factor, defects in sorted(multi.items()):
            got = sorted(tbl.loc[tbl["column"] == factor, "matched_defect"].unique())
            check(f"{name} — {factor}에 defect {len(defects)}개", got == sorted(defects), f"{got}")

    print("\n[4] trend_analysis — (컬럼, 그룹)에 항목이 둘인가")
    # load_baseline_maps는 파일에서 읽으므로, 방금 만든 baseline_c를 파일로 흉내낸다.
    import trend_analysis  # noqa: E402
    c_map: dict[tuple[str, str], list[dict]] = {}
    for row in baseline_c.itertuples(index=False):
        c_map.setdefault((row.column, row.group_key), []).append(
            {"threshold": row.threshold, "risky_direction": row.risky_direction,
             "matched_defect": row.matched_defect})

    directions = load_domain_directions()
    for factor, defects in sorted(multi.items()):
        keys = {k for k in c_map if k[0] == factor}
        full = {k for k in keys if len(c_map[k]) == len(defects)}
        short = keys - full
        check(f"{factor}: 경보 루프가 defect마다 도는 그룹이 있음", bool(full),
              f"항목 {len(defects)}개인 그룹 {len(full)}개 / 그보다 적은 그룹 {len(short)}개")
        if full:
            sample = sorted(full)[0]
            check(f"{factor}: 그 그룹의 항목이 서로 다른 defect",
                  len({e["matched_defect"] for e in c_map[sample]}) == len(defects),
                  f"{sample[1]} -> {[e['matched_defect'] for e in c_map[sample]]}")

        # 항목이 모자란 그룹은 "짝이 조용히 사라진 것"이 아니라 "방향 필터가 뺀 것"이어야
        # 한다. 이 둘을 구분 못 하면 이 스크립트가 막으려던 회귀(짝이 소리 없이 증발)를
        # 못 잡는다 — 방향 필터가 생긴 뒤 "모든 그룹에 2개"로 검사하다 실패로 찍힌 자리다.
        # 비교 기준은 산출물이 아니라 필터 없이 다시 학습한 값이다(groups_without_threshold).
        expected = set()
        for d in defects:
            expected |= {(factor, g) for g in
                         groups_without_threshold(df, factor, d, directions.get((factor, d)))}
        unexplained = sorted(g for _, g in short - expected)
        check(f"{factor}: 항목이 모자란 그룹은 방향 필터로 빠진 그룹뿐", short == expected,
              f"모자란 그룹 {len(short)}개 vs 독립 재계산 {len(expected)}개"
              + (f" · 설명 안 되는 그룹 {len(unexplained)}개 {unexplained[:3]}"
                 if unexplained else ""))
        for d in defects:
            if wide[factor][d].isna().any():
                print(f"  (참고: {factor}↔{d}의 도메인 방향은 {directions.get((factor, d))} — "
                      f"반대로 학습된 {int(wide[factor][d].isna().sum())}개 그룹은 "
                      f"compute_baseline_type_c가 행을 안 만든다. CLAUDE.md 규칙 6)")
    print("  (참고: C유형 진입률 조회 키는 (장비, 컬럼, defect)다 — 한 컬럼이 두 defect의"
          " 원인이면 경계값이 둘이라 '평소 얼마나 그 구간에 있었나'도 둘이다."
          " 근거는 build_health_index.py의 zone_base_rate 주석. 26.08.17까지는"
          " trend_analysis.compute_c_type_baseline_rate에 있었으나 '접근' 판정과 함께 제거됐다.)")

    print()
    if failures:
        sys.exit(f"실패 {len(failures)}건: {failures}")
    print("전부 통과 — 한 인자의 defect 2개가 경계값·진입률·경보까지 각각 살아남는다.")


if __name__ == "__main__":
    main()
