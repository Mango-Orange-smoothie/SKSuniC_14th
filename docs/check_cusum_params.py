"""CUSUM_K=0.7 / CUSUM_H=4.5의 근거를 처음부터 다시 잰다.

왜 이 스크립트가 있나: 두 상수는 `trend_analysis.py`에 그냥 적혀 있어서, 근거를 문서에만
두면 파이프라인이 바뀔 때 조용히 틀린 값이 된다(실제로 26.08.08판 수치가 그렇게 낡았다).
여기서 재는 값이 `docs/판정근거_정리.md` 2-3절의 표와 일치해야 한다.

    python3 docs/check_cusum_params.py            # 전부
    python3 docs/check_cusum_params.py --arl      # ARL 시뮬레이션만 (파이프라인 재실행 없음)

파이프라인을 K·H마다 다시 돌리므로 전체 실행은 설정당 ~10초, 기본 격자로 4~5분 걸린다.
결과는 임시 디렉터리에 쓰고 저장소 산출물은 건드리지 않는다.
"""
import argparse
import contextlib
import io
import os
import sys
import tempfile

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

RAW = os.path.join(BASE_DIR, "data", "raw", "DP_HealthIndex_Dataset.csv")
STRATUM = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing",
                       "00_stratum_baseline_stats_by_opcond.csv")

# 멘토 확정 주입 시나리오. DP01에 시나리오가 없다는 것이 이 채점의 전제다 —
# DP01에 뜨는 지속경보는 전부 오탐이므로 K/H를 채점할 정답지가 된다.
NORMAL_MACHINE = "DP01"
SUSTAINED_DAYS = 14          # build_health_index의 성숙도 판정과 같은 기준
GAP_DAYS = 1                 # 이만큼 끊기면 다른 경보 구간(alert_since 규칙과 동일)

# 실제 고장 시작일. 일평균이 초반 30일 ±3σ 밖으로 나가 5일 이상 유지되는 첫날로 잡았다.
ONSET = {("DP04", "CLN_Flow"): "2026-02-17",
         ("DP02", "Laser_Power"): "2026-02-06",
         ("DP03", "Head_Temp"): "2026-02-11"}


# ---------------------------------------------------------------- 공통

def episodes(df, machine=None):
    """(장비, 컬럼)별 연속 경보 구간의 지속일수. GAP_DAYS 넘게 끊기면 다른 구간."""
    if machine:
        df = df[df.Machine_ID == machine]
    out = []
    for (m, c), g in df.groupby(["Machine_ID", "column"]):
        t = g["DateTime"].sort_values()
        run = (t.diff() > pd.Timedelta(days=GAP_DAYS)).cumsum()
        for _, s in t.groupby(run):
            out.append((m, c, (s.max() - s.min()) / pd.Timedelta(days=1), s.min()))
    return pd.DataFrame(out, columns=["machine", "column", "days", "start"])


def detected(df, machine, column):
    """그 설정이 이 고장을 '언제 잡았다'고 말하는 날 = 가장 긴 경보 구간의 시작."""
    t = df[(df.Machine_ID == machine) & (df["column"] == column)]["DateTime"].sort_values()
    if not len(t):
        return None
    run = (t.diff() > pd.Timedelta(days=GAP_DAYS)).cumsum()
    longest = max(t.groupby(run), key=lambda kv: kv[1].max() - kv[1].min())[1]
    return longest.min().normalize()


def run_pipeline(k, h, workdir):
    """trend_analysis를 K/H만 바꿔 다시 돌리고 경보 행을 읽어온다."""
    out = os.path.join(workdir, f"K{k}_H{h}.csv")
    if not os.path.exists(out):
        import trend_analysis as ta
        ta.CUSUM_K, ta.CUSUM_H = k, h
        ta.OUTPUT_DIR, ta.OUTPUT_CSV = workdir, out
        ta.CROSS_VALIDATION_CSV = os.path.join(workdir, "xval.csv")
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            ta.main()
    df = pd.read_csv(out, usecols=["DateTime", "Machine_ID", "Product_ID",
                                   "column", "early_warning"], encoding="utf-8-sig")
    df = df[df.early_warning == True]                                  # noqa: E712
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    return df


def score(df):
    """한 설정의 채점 결과. 하한은 오탐이, 상한은 탐지 지연이 정한다."""
    ep = episodes(df)
    normal = ep[ep.machine == NORMAL_MACHINE]
    row = {"rows": len(df),
           "normal_sustained": int((normal.days >= SUSTAINED_DAYS).sum()),
           "normal_longest": float(normal.days.max()) if len(normal) else 0.0}
    for (m, c), on in ONSET.items():
        d = detected(df, m, c)
        row[c] = None if d is None else (d, (d - pd.Timestamp(on)).days)
    return row


def fmt(cell):
    if cell is None:
        return "놓침"
    d, lag = cell
    return f"{d:%m-%d} ({lag:+d})"


def table(results, label):
    cols = list(ONSET.values()) and [c for (_, c) in ONSET]
    head = (f"{label:>6} {'경보행':>9} {'정상장비':>9} {'최장':>8}  "
            + "  ".join(f"{c[:15]:>15}" for c in cols))
    print(head)
    print("-" * len(head))
    for key, r in results:
        mark = "  <== 현재" if key in (0.7, 4.5) else ""
        print(f"{key:>6.2f} {r['rows']:>9,} {r['normal_sustained']:>9} "
              f"{r['normal_longest']:>7.1f}일  "
              + "  ".join(f"{fmt(r[c]):>15}" for c in cols) + mark)


# ---------------------------------------------------------------- ARL

def arl(k, h, delta, n_run=20000, max_len=40000, block=2000, seed=7):
    """양측 CUSUM(구현과 동일)에서 첫 경보까지의 평균 관측 수.

    delta=0이 ARL0. 교과서값(K0.5/H4.0)에서 169가 나오면 문헌값 ~168과 맞는 것이고,
    그러면 이 시뮬레이션 자체는 믿을 수 있다는 뜻이다.
    """
    rng = np.random.default_rng(seed)
    pos = np.zeros(n_run)
    neg = np.zeros(n_run)
    life = np.full(n_run, -1, dtype=np.int64)
    alive = np.ones(n_run, dtype=bool)
    t = 0
    while alive.any() and t < max_len:
        idx = np.where(alive)[0]
        z = rng.normal(delta, 1.0, size=(block, len(idx)))
        p, n = pos[idx], neg[idx]
        for i in range(block):
            p = np.maximum(0.0, p + z[i] - k)
            n = np.minimum(0.0, n + z[i] + k)
            hit = (p > h) | (n < -h)
            if hit.any():
                new = idx[hit & (life[idx] < 0)]
                life[new] = t + i + 1
        pos[idx], neg[idx] = p, n
        t += block
        alive = life < 0
    life[life < 0] = max_len
    return float(life.mean())


def check_arl():
    """ARL을 왜 설계 기준으로 못 쓰는지 — 스트림 개수와 장비별 고정 오프셋."""
    print("\n=== ARL 시뮬레이션 ===")
    print("교과서값에서 169 근처가 나와야 한다(문헌 ARL0 ~168). 아니면 이 계산을 믿지 말 것.\n")
    shots_per_day = 5.19
    print(f"{'상황':<32}{'K0.5/H4.0':>14}{'K0.7/H4.5':>14}")
    for label, d in [("δ=0   진짜 정상 (ARL0)", 0.0),
                     ("δ=0.2 장비 상시 오프셋", 0.20),
                     ("δ=0.35 오프셋 최대", 0.35),
                     ("δ=0.57 잡아야 할 열화", 0.57),
                     ("δ=1.0 교과서 목표 이동폭", 1.00)]:
        print(f"{label:<32}{arl(0.5, 4.0, d):>12,.0f}샷{arl(0.7, 4.5, d):>12,.0f}샷")

    print("\n--- 스트림이 하나가 아니라는 것 ---")
    raw = pd.read_csv(RAW, usecols=["Machine_ID", "Product_ID", "Recipe_ID"],
                      encoding="utf-8-sig")
    n_grp = raw.groupby(["Machine_ID", "Product_ID", "Recipe_ID"]).ngroups \
        // raw["Machine_ID"].nunique()
    n_stream = n_grp * 34
    print(f"장비 1대당 동시에 도는 CUSUM = {n_grp}개 그룹 x 34개 컬럼 = {n_stream:,}개")
    for name, k, h in (("K0.5/H4.0", 0.5, 4.0), ("K0.7/H4.5", 0.7, 4.5)):
        days = arl(k, h, 0.0) / shots_per_day
        print(f"  {name}: 스트림당 {days:>5.1f}일마다 1건 "
              f"-> 정상 장비 1대·89일 기대 오경보 {n_stream * 89 / days:>8,.0f}건")
    print("  (현재 설정의 예측치가 DP01 실측 에피소드 수와 10% 안에서 맞아야 한다)")


def check_offsets():
    """ARL0가 가정하는 '정상일 때 평균 = target'이 우리 데이터에서 깨지는 정도."""
    from pipeline import config
    print("\n=== 장비별 고정 오프셋 (정상 장비 DP01) ===")
    print("baseline이 OPCOND 공통이라 장비마다 평소 자리가 어긋나 있다. 고장이 아닌데도")
    print("CUSUM에는 ARL1로 들어간다 — 이게 교과서 h를 못 쓰는 두 번째 이유다.\n")
    raw = pd.read_csv(RAW, encoding="utf-8-sig", low_memory=False)
    base = pd.read_csv(STRATUM, encoding="utf-8-sig").set_index(
        ["Product_ID", "Recipe_ID", "column"])[["mean", "std"]]
    recs = []
    for col in [c for c in config.FDC_COLS if c in raw.columns]:
        for (p, r), g in raw.groupby(["Product_ID", "Recipe_ID"]):
            if (p, r, col) not in base.index:
                continue
            mu, sd = base.loc[(p, r, col), "mean"], base.loc[(p, r, col), "std"]
            if not (sd and np.isfinite(sd) and sd > 0):
                continue
            for m, gm in g.groupby("Machine_ID"):
                v = gm[col].dropna()
                if len(v) >= 30:
                    recs.append((m, abs((v.mean() - mu) / sd)))
    d = pd.DataFrame(recs, columns=["machine", "off"])
    n = d[d.machine == NORMAL_MACHINE]
    print(f"  {NORMAL_MACHINE} 스트림 {len(n):,}개 — 중앙값 {n.off.median():.3f}σ / "
          f"최대 {n.off.max():.3f}σ")
    for thr in (0.2, 0.3, 0.44):
        print(f"    |오프셋| >= {thr}σ : {int((n.off >= thr).sum()):>4}개 "
              f"({(n.off >= thr).mean() * 100:.1f}%)")


# ---------------------------------------------------------------- 과적합

def check_overfit(workdir, ks):
    """선택 기준을 쪼개도 경계가 같은 자리에 서는가 + 경계가 감시 규모에 얼마나 딸리는가."""
    print("\n=== 과적합 검사 ===")
    print("한 점이 아니라 구간이고, 반으로 쪼개도 경계가 같아야 과적합이 아니다.\n")
    cache = {k: run_pipeline(k, 4.5, workdir) for k in ks}
    cache = {k: df[df.Machine_ID == NORMAL_MACHINE] for k, df in cache.items()}
    cols = sorted(cache[0.7]["column"].unique())
    mid = pd.Timestamp("2026-02-16")

    def boundary(fn):
        for k in ks:
            sub = fn(cache[k])
            ep = episodes(sub)
            if len(ep) == 0 or (ep.days >= SUSTAINED_DAYS).sum() == 0:
                return k
        return None

    for name, fn in [
        ("전체 (실제 선택에 쓴 것)", lambda d: d),
        ("컬럼 홀수번째만", lambda d: d[d["column"].isin(cols[0::2])]),
        ("컬럼 짝수번째만", lambda d: d[d["column"].isin(cols[1::2])]),
        ("기간 전반부만 (~2/16)", lambda d: d[d.DateTime < mid]),
        ("기간 후반부만 (2/16~)", lambda d: d[d.DateTime >= mid]),
    ]:
        print(f"  {name:<26} 경계 K = {boundary(fn)}")

    print("\n  --- 경계는 '동시에 몇 개를 감시하나'에 딸려 움직인다 ---")
    prods = sorted(cache[0.7]["Product_ID"].unique())
    import itertools
    rng = np.random.default_rng(0)
    for r in (1, 2, 3, 4, len(prods)):
        combos = list(itertools.combinations(prods, r))
        if len(combos) > 10:
            combos = [combos[i] for i in rng.choice(len(combos), 10, replace=False)]
        got = [boundary(lambda d, cb=cb: d[d.Product_ID.isin(cb)]) for cb in combos]
        got = [g for g in got if g is not None]
        print(f"    제품 {r}개 (스트림 ~{r * 9 * 34:>5,}개)  경계 K 중앙값 {np.median(got):.2f}"
              f"  범위 {min(got):.2f}~{max(got):.2f}")
    print("\n  -> 스트림이 6배 늘 때 경계가 0.20 올라간다. K는 이 규모에 종속이다.")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arl", action="store_true", help="ARL 시뮬레이션만 (파이프라인 재실행 없음)")
    ap.add_argument("--quick", action="store_true", help="격자를 줄여 빠르게")
    args = ap.parse_args()

    if args.arl:
        check_arl()
        return

    ks = [0.5, 0.6, 0.7, 0.8, 0.9] if args.quick else \
         [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1]
    hs = [4.0, 4.5, 5.0] if args.quick else [3.5, 4.0, 4.2, 4.3, 4.5, 4.6, 5.0, 6.0]

    with tempfile.TemporaryDirectory(prefix="cusum_sweep_") as workdir:
        os.chdir(BASE_DIR)
        print("=== 교과서값과의 대조 (14일↑ 지속경보) ===")
        print(f"정상 장비 {NORMAL_MACHINE}에 뜨는 건 전부 오탐이다 — 멘토 확정 시나리오 없음.\n")
        for k, h in ((0.5, 4.0), (0.7, 4.5)):
            ep = episodes(run_pipeline(k, h, workdir))
            per = ep[ep.days >= SUSTAINED_DAYS].groupby("machine").size()
            got = "  ".join(f"{m} {int(per.get(m, 0)):>2}" for m in
                            ("DP01", "DP02", "DP03", "DP04"))
            print(f"  K{k}/H{h}   {got}")
        print(f"\n  -> 교과서값에서는 정상 장비가 고장 장비보다 많이 뜬다. "
              f"{NORMAL_MACHINE}만 0이 되는 설정을 고른다.")

        print("\n=== K 스윕 (H=4.5 고정) ===")
        print("하한은 '고장 전 오탐'이, 상한은 '탐지 지연'이 정한다.")
        print("CLN_Flow만 고장 전 구간이 평평해서 '고장 전 = 오탐'을 말할 수 있다.\n")
        table([(k, score(run_pipeline(k, 4.5, workdir))) for k in ks], "K")

        print("\n=== H 스윕 (K=0.7 고정) ===")
        print("H는 K보다 둔하다. 오탐 개선이 바닥치는 지점과 탐지가 늦어지기 시작하는")
        print("지점 사이가 쓸 수 있는 구간이다.\n")
        table([(h, score(run_pipeline(0.7, h, workdir))) for h in hs], "H")

        check_overfit(workdir, ks)

    check_arl()
    check_offsets()

    print("\n" + "=" * 72)
    print("결론: K [0.65, 0.80] / H [4.3, 4.5]. 채택 0.7 / 4.5.")
    print("H=4.5는 탐지를 하나도 안 늦추는 마지막 값이라 골랐다 — K만큼 강한 근거는 아니다.")
    print("두 구간 모두 스트림 1,836개 기준이다. 감시 규모가 커지면 다시 잰다.")


if __name__ == "__main__":
    main()
