"""Step 0: 데이터 전처리 & 피처 기반.

Goal 1~6(장비/제품 비교, 유효인자 발굴, 상호작용, 이상탐지, Health Index, SOP 초안)
모듈이 공통으로 참조할 컬럼 분류·변동성/추세 분류·baseline·정규화 기반을 만든다.
원본 CSV는 절대 수정하지 않는다. 실행: `python -m pipeline.step0_preprocessing`

산출물 (analysis_outputs/preprocessing/):
  00_column_classification.csv        컬럼별 분류/변동성/추세 요약 (68개 원본 컬럼 전체)
  00_machine_column_trend.csv         (Machine, 연속형 컬럼)별 추세검정 상세
  00_missing_sensor_fault_flags.csv   결측/불가능한 0값/flatline(고착) 플래그
  00_stratum_baseline_stats_by_opcond.csv        Product×Recipe grain OK-baseline
  00_stratum_baseline_stats_by_machine_opcond.csv Machine×Product×Recipe grain OK-baseline
  00_baseline_AB.csv                  A(단조 drift형)/B(U자형) 컬럼 Baseline (Jun 이식)
  00_baseline_C.csv                   C(편측 위험 threshold형) 컬럼 위험 경계값 (Jun 이식)
  00_baseline_E.csv                   E(대칭성/정렬형) 컬럼 이론 상수 Baseline (Jun 이식)
  00_preprocessing_summary.json       요약 통계 + assert 결과 + 다운스트림 기본 컬럼 목록
  00_baseline_C_candidates.csv        C유형 후보 전수 스캔 + 순열검정 노이즈 천장

산출물 (analysis_outputs/ 루트 — 소비자 경로를 안 깨뜨리려고 여기 저장):
  05_machine_daily_trend.csv          장비x날짜 defect 발생률 + 공정변수 7일 이동평균
                                      (build_health_index/agent.py가 읽음)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.tree import DecisionTreeClassifier

from pipeline import config
from pipeline import mentor
from pipeline.mentor import SPEC
from pipeline.common import (
    compute_stratum_baseline_stats,
    load_defect_pairing_from_db,
    mann_kendall,
    save_table,
    zscore_transform,
)

_DEFECT_PAIRING_CACHE: dict[str, str] | None = None


def resolve_defect_pairing() -> dict[str, str]:
    """인자↔defect 짝짓기의 단일 출처 — Goal2 관계DB 우선, 실패하면 config 폴백.

    (26.08.08) 예전엔 config.BASELINE_C_DEFECT_MAP 하드코딩이 유일한 출처였다.
    관계DB(rel_30/rel_20)가 팀 공식 판정이고 rel_30은 아예 추세분석 앞으로 만들어진
    인계 파일인데 파이프라인이 안 읽고 있었다 — 근거는 common.load_defect_pairing_from_db
    주석 참고. 무엇이 왜 제외됐는지 매 실행마다 찍어서, 조용히 바뀌는 일이 없게 한다.
    """
    global _DEFECT_PAIRING_CACHE
    if _DEFECT_PAIRING_CACHE is not None:
        return _DEFECT_PAIRING_CACHE

    fallback = dict(config.BASELINE_C_DEFECT_MAP)
    loaded = load_defect_pairing_from_db()
    if loaded is None:
        print("[관계DB] rel_30/rel_20을 읽을 수 없어 config.BASELINE_C_DEFECT_MAP로 진행합니다.")
        _DEFECT_PAIRING_CACHE = fallback
        return _DEFECT_PAIRING_CACHE

    pairing, detail = loaded
    print(f"[관계DB] 짝짓기 {len(pairing)}건 채택 (alert_usable=True AND repro_state=통과)")
    for row in detail.itertuples(index=False):
        mark = "채택" if row.adopted else "제외"
        print(f"   {mark} {row.factor} ↔ {row.defect}"
              f"  (alert_usable={row.alert_usable}, repro_state={row.repro_state})")
    if pairing != fallback:
        print(f"   [주의] config 폴백값과 다릅니다 — config={fallback}")
    _DEFECT_PAIRING_CACHE = pairing
    return _DEFECT_PAIRING_CACHE

CONTINUOUS_TREND_COLS = config.FDC_COLS + config.RESPONSES + ["Yield"]
CONTINUOUS_BASELINE_COLS = CONTINUOUS_TREND_COLS + config.DOMAIN_FEATURES
# flatline(고착) 탐지는 센서성 연속값에만 의미가 있다. Yield는 정상 공정에서
# 정의상 100이 매우 자주 반복되므로(공정이 잘 돌아간다는 뜻) 여기서 제외한다.
SENSOR_FLATLINE_CHECK_COLS = config.FDC_COLS + config.RESPONSES

# 05_machine_daily_trend.csv의 defect rate 대상. 멘토가 제외 확정한 Edge_Burn은 빼고,
# Laser_Paim은 Health Index/Agent가 안 보는 defect라 기존 trend_table과 동일하게 4개만 쓴다.
DEFECT_RATE_SOURCE_COLS = ["Particle", "Remain_Coat", "Micro_Crack", "Chipping"]


# ---------------------------------------------------------------------------
# 1단계: 로드 & 키/정상군 검증
# ---------------------------------------------------------------------------

def load_r1_for_threshold_training() -> pd.DataFrame | None:
    """R1(멘토 배포 실데이터)을 Type C 결정트리 threshold "학습"에만 쓴다.

    (26.08.05) R1은 원본과 합치지 않는다 — 모니터링 대상(매일 감시하는 데이터)은 계속
    원본(config.INPUT_CSV)이고, R1은 "위험 threshold가 어디인지 배우는" 용도로만 쓴다.
    실제로 R1은 불량 사례를 의도적으로 많이 담은 학습셋이라(OK 58,890 vs 원본 90,783,
    NG_Code 분포: CHIP 24,171/REM_COAT 6,934/CRACK 4,887/PARTICLE 4,841) load_and_validate의
    EXPECTED_NORMAL_COUNT 검증을 그대로 적용하면 안 되고(다른 성격의 데이터셋이라 당연히
    다름), 행 수만 확인한다. 원본 4건뿐이던 Chipping이 R1에서는 24,171건이라 그룹(54개)
    전부 min_samples_leaf=10을 넉넉히 넘겨 — 원본으로는 표본 부족으로 통계적 검증
    자체가 불가능했던 Chipping/Micro_Crack 관련 threshold도 이제 학습 가능하다.
    """
    if not config.INPUT_CSV_R1.exists():
        print(f"[경고] R1 파일 없음({config.INPUT_CSV_R1}) — Type C threshold를 원본으로 학습합니다"
              "(표본 부족한 defect는 여전히 threshold를 못 만듦).")
        return None
    df = pd.read_csv(config.INPUT_CSV_R1)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    if len(df) != config.EXPECTED_ROW_COUNT:
        print(f"[경고] R1 행 수가 예상과 다릅니다: {len(df)} != {config.EXPECTED_ROW_COUNT} — 그대로 진행합니다.")
    return df


def load_and_validate() -> pd.DataFrame:
    df = pd.read_csv(config.INPUT_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["is_normal"] = config.NORMAL(df)

    n_rows = len(df)
    n_unique_keys = df[config.KEY].drop_duplicates().shape[0]
    n_dup_keys = int(df.duplicated(config.KEY).sum())
    n_normal = int(df["is_normal"].sum())

    assert n_rows == config.EXPECTED_ROW_COUNT, (
        f"행 수가 예상과 다릅니다: {n_rows} != {config.EXPECTED_ROW_COUNT} "
        "(원본 데이터셋이 바뀌었을 수 있음 — 계속 진행 전 확인 필요)"
    )
    assert n_dup_keys == 0, f"Lot_ID+Strip_ID 키 중복 {n_dup_keys}건 발견 — 분석키 규약 위반"
    assert n_normal == config.EXPECTED_NORMAL_COUNT, (
        f"정상군 수가 예상과 다릅니다: {n_normal} != {config.EXPECTED_NORMAL_COUNT}"
    )

    df = config.add_domain_features(df)
    return df


# ---------------------------------------------------------------------------
# 2단계: 변동성 지표 (스케일 불변, 타입별로 다르게)
# ---------------------------------------------------------------------------

def _dispersion_ratio(values: pd.Series) -> float:
    """스케일-불변 변동성 비율.

    평균이 0에서 충분히 떨어져 있으면 CV(std/mean)를, Cutting_Offset처럼
    부호 있는/0 중심 컬럼은 CV가 발산하므로 관측 range 대비 std로 대체한다.
    """
    if len(values) < 5:
        return np.nan
    mean = values.mean()
    std = values.std()
    if std == 0:
        return 0.0
    if abs(mean) > 0.1 * std:
        return abs(std / mean)
    rng = values.max() - values.min()
    return std / rng if rng > 1e-9 else 0.0


def _classify_ratio(ratio: float) -> str:
    if pd.isna(ratio):
        return "unknown"
    if ratio < config.CV_STABLE_THRESHOLD:
        return "stable"
    if ratio < config.CV_VARIABLE_THRESHOLD:
        return "moderate"
    return "variable"


def variability_continuous(df_normal: pd.DataFrame, col: str) -> tuple[float, str, str]:
    ratios = []
    for _, g in df_normal.groupby(config.OPCOND):
        r = _dispersion_ratio(g[col].dropna())
        if pd.notna(r):
            ratios.append(r)
    if not ratios:
        return np.nan, "unknown", "cv_or_range_normalized"
    return float(np.median(ratios)), _classify_ratio(float(np.median(ratios))), "cv_or_range_normalized"


def variability_binary(df_all: pd.DataFrame, col: str) -> tuple[float, str, str]:
    """이진 defect: variance=p(1-p)는 무의미하므로 층별 발생률의 CV를 사용.

    NORMAL(OK) 정의상 defect 컬럼은 정상군에서 항상 0이므로 반드시 전체 데이터(df_all)로
    계산해야 한다 — 정상군(df_normal)으로 계산하면 발생률이 모든 층에서 0이 되어 무의미해진다.
    주의: 희귀 이벤트는 층별 표본이 작을수록 발생률 CV가 표본 노이즈만으로도
    커지는 경향이 있다 — 'variable' 판정을 과도하게 신뢰하지 말 것 (dispersion_method 참고).
    """
    rates = df_all.groupby(config.OPCOND)[col].mean().dropna()
    if len(rates) < 2 or rates.mean() == 0:
        return np.nan, "unknown", "rate_cv"
    cv = rates.std() / rates.mean()
    return float(cv), _classify_ratio(float(cv)), "rate_cv"


def variability_count(df_all: pd.DataFrame, col: str) -> tuple[float, str, str]:
    """count(die 단위) 컬럼: index of dispersion(var/mean, Poisson 과산포 진단).

    defect count 컬럼은 정상군에서 항상 0이므로 전체 데이터(df_all)로 계산한다 (위와 동일 이유).
    """
    ratios = []
    for _, g in df_all.groupby(config.OPCOND):
        s = g[col].dropna()
        if len(s) < 5 or s.mean() == 0:
            continue
        ratios.append(s.var() / s.mean())
    ratios = [r for r in ratios if pd.notna(r)]
    if not ratios:
        return np.nan, "unknown", "index_of_dispersion"
    median_ratio = float(np.median(ratios))
    cls = "stable" if median_ratio < 0.5 else ("moderate" if median_ratio < 2.0 else "variable")
    return median_ratio, cls, "index_of_dispersion"


# ---------------------------------------------------------------------------
# 3단계: 노이즈 vs 실제 열화추세 (장비별, OPCOND 잔차 기반)
# ---------------------------------------------------------------------------

def compute_machine_daily_series(df: pd.DataFrame, opcond_baseline: pd.DataFrame) -> pd.DataFrame:
    """장비×컬럼별 OPCOND 정규화 z-잔차를 날짜 단위로 집계한 long-format 시계열.

    다른 팀원(추세/조기경보 분석 담당)이 원본 행(샷) 단위로 직접 rolling window를
    돌리면, Machine×Product×Recipe로 쪼갤 때 하루 평균 샷 수가 5개 안팎이라
    "10개 윈도우"가 실제로는 1~2일치밖에 안 돼서 몇 주 단위로 서서히 진행되는
    열화 추세를 통계적으로 잡을 표본이 부족해지는 문제가 생긴다(day-vs-shot
    단위 불일치). 이 표를 rolling/조기경보 분석의 공통 입력으로 쓰면 이 문제를
    원천적으로 피할 수 있다 — 이미 날짜 단위로 집계·정규화되어 있다.

    Product/Recipe 조합이 날마다 달라도, 먼저 조건별로 정규화했기 때문에
    "그 장비가 자기 기대 baseline 대비 드리프트하는지"를 올바르게 반영한다.
    """
    z_df = zscore_transform(df, opcond_baseline, config.OPCOND, CONTINUOUS_TREND_COLS)
    z_df["date"] = z_df["DateTime"].dt.date

    rows = []
    for machine, g in z_df.groupby("Machine_ID"):
        daily = g.groupby("date")
        n_shots = daily.size()
        for col in CONTINUOUS_TREND_COLS:
            zcol = f"{col}_z"
            daily_mean = daily[col].mean()
            daily_mean_z = daily[zcol].mean()
            frame = pd.DataFrame({
                "Machine_ID": machine,
                "column": col,
                "date": daily_mean.index,
                "n_shots": n_shots.reindex(daily_mean.index).values,
                "daily_mean": daily_mean.values,
                "daily_mean_z": daily_mean_z.reindex(daily_mean.index).values,
            })
            rows.append(frame)
    return pd.concat(rows, ignore_index=True).sort_values(["Machine_ID", "column", "date"])


DAILY_TREND_MA_COLS = ["Head_Temp", "Coating_Uniformity", "Surface_Roughness", "Yield"]
DAILY_TREND_WINDOW = 7      # 일평균도 하루하루 튀어서 눈으로 추세를 보려면 매끄럽게 해야 함
DAILY_TREND_MIN_PERIODS = 3  # 시작 시점에 7일이 안 모여도 3일치면 계산(안 그러면 첫 6일이 전부 NaN)


def compute_machine_daily_trend(df: pd.DataFrame) -> pd.DataFrame:
    """장비×날짜별 defect 발생률 + 주요 공정변수 일평균(+7일 이동평균).

    (26.08.07 이관) 원래 analysis_step_by_step.py의 trend_table()이 만들던 표인데, 그
    스크립트는 8/1 이후 정지된 초기 탐색용이고 이 산출물만 파이프라인 핵심으로 남아 있었다
    — build_health_index(최근 7일 실제 불량 발생 판정)와 agent.py("언제 불량 났었어?" 조회)가
    둘 다 이걸 읽는다. 그런데 실행 순서 안내 어디에도 그 스크립트가 없어서, 원본 데이터가
    바뀌면 이 파일만 낡은 채 남아 Health Index가 옛날 데이터로 "최근 7일"을 판정할 위험이
    있었다. step0로 옮겨서 항상 같이 갱신되게 한다.

    defect rate를 mean()으로 구하는 게 핵심 — defect 컬럼이 0/1이라 평균이 곧 발생 비율이다
    (그날 270샷 중 27개가 1이면 mean=0.1=10%). 별도 나눗셈이 필요 없다.

    이동평균은 장비별로 따로 굴린다(groupby.transform) — 안 그러면 DP01 마지막 날과 DP02
    첫날이 같은 창에 섞인다.
    """
    defect_cols = {f"{d}_rate": (d, "mean") for d in DEFECT_RATE_SOURCE_COLS}
    trend = (
        df.assign(date=df["DateTime"].dt.date)
        .groupby(["Machine_ID", "date"], as_index=False)
        .agg(
            **{c: (c, "mean") for c in DAILY_TREND_MA_COLS},
            **defect_cols,
            samples=("Yield", "size"),
        )
    )
    for col in DAILY_TREND_MA_COLS:
        trend[f"{col}_{DAILY_TREND_WINDOW}d_ma"] = trend.groupby("Machine_ID")[col].transform(
            lambda x: x.rolling(DAILY_TREND_WINDOW, min_periods=DAILY_TREND_MIN_PERIODS).mean()
        )
    return trend


def compute_daily_defect_zone_rate(df: pd.DataFrame, baseline_c: pd.DataFrame) -> pd.DataFrame:
    """C유형 컬럼: 날짜×장비별로 "불량 위험구간에 들어간 샷 비율"을 집계한다.

    (26.08.05 추가) 왜 필요한가 — C유형 threshold는 개별 샷 데이터로 학습한 경계라
    샷 단위로만 의미가 있는데, Health Index는 일평균을 그 경계와 비교하고 있었다.
    일평균은 수백 샷을 평균낸 값이라 분산이 훨씬 작아서, 실측으로 확인해보니
    개별 샷은 6.4~6.7%가 경계를 넘는데도(그래서 Remain_Coat가 실제로 발생) 일평균은
    356일 내내 단 하루도 경계를 안 넘었다. 그 결과 이 컬럼들의 health가 영구히
    97~100에 고정돼 경보를 낼 수 없는 상태였다(compute_boundary_z docstring이 경고한
    day-vs-shot granularity 불일치와 같은 문제).

    그래서 "일평균이 경계에서 얼마나 떨어졌나" 대신 "그날 샷 중 몇 %가 경계를
    넘었나"를 센다 — 불량이 샷 단위 사건이므로 이게 맞는 granularity다.

    threshold는 Product_ID x Recipe_ID 그룹마다 다르므로, 샷별로 자기 그룹의
    threshold를 적용한 뒤 장비×날짜로 집계한다(그룹 대표값 하나로 뭉개지 않음).
    """
    thr_map = {
        (r.column, r.group_key): (r.threshold, r.risky_direction)
        for r in baseline_c.itertuples(index=False)
    }
    columns = sorted({c for c, _ in thr_map})

    work = df[["Machine_ID", "Product_ID", "Recipe_ID", "DateTime"] + columns].copy()
    work["date"] = work["DateTime"].dt.date
    work["group_key"] = work["Product_ID"] + "|" + work["Recipe_ID"]

    rows = []
    for col in columns:
        thr = work["group_key"].map(lambda gk: thr_map.get((col, gk), (np.nan, None))[0])
        direction = work["group_key"].map(lambda gk: thr_map.get((col, gk), (np.nan, None))[1])
        in_zone = np.where(
            direction == "low_is_risky", work[col] < thr,
            np.where(direction == "high_is_risky", work[col] > thr, np.nan),
        )
        tmp = pd.DataFrame({
            "Machine_ID": work["Machine_ID"],
            "date": work["date"],
            "in_zone": pd.to_numeric(pd.Series(in_zone, index=work.index), errors="coerce"),
        }).dropna(subset=["in_zone"])
        agg = tmp.groupby(["Machine_ID", "date"])["in_zone"].agg(["size", "sum"])
        agg = agg.reset_index().rename(columns={"size": "n_shots", "sum": "n_in_zone"})
        agg["column"] = col
        agg["defect_zone_rate"] = agg["n_in_zone"] / agg["n_shots"]
        rows.append(agg[["Machine_ID", "column", "date", "n_shots", "n_in_zone", "defect_zone_rate"]])

    return pd.concat(rows, ignore_index=True).sort_values(["Machine_ID", "column", "date"])


def find_stable_baseline_days(daily_rate: pd.Series) -> int:
    """일별 진입률 계열에서 "아직 상승 추세가 없는" 초기 구간(Phase I)의 길이를 돌려준다.

    최소 길이부터 하루씩 늘려가며 Mann-Kendall을 다시 검정하고, 상승 추세가 유의해지는
    순간 직전에서 끊는다. 진입률은 "위험구간에 들어간 비율"이라 올라가는 것만 나빠지는
    방향이므로 tau > 0 쪽만 본다(low/high_is_risky는 in_zone 계산에서 이미 흡수됨).

    구간을 늘려가며 반복 검정하므로 유의수준이 명목값보다 느슨해지지만, 그 방향의 오류는
    "안정 구간을 실제보다 짧게 잡는" 쪽 = baseline을 보수적으로 낮게 잡는 쪽이라 경보를
    놓치지 않는다. 반대로 길게 잡으면 열화가 baseline에 섞여 경보가 죽는다(config.py
    C_BASELINE_MIN_STABLE_DAYS 주석 참고).
    """
    s = daily_rate.dropna()
    if len(s) < config.C_BASELINE_MIN_STABLE_DAYS:
        return len(s)
    for end in range(config.C_BASELINE_MIN_STABLE_DAYS, len(s) + 1):
        window = s.iloc[:end]
        tau, p_value = mann_kendall(pd.Series(np.arange(len(window))), window)
        if pd.notna(p_value) and p_value < config.TREND_ALPHA and tau > 0:
            return end - 1
    return len(s)


def compute_c_entry_rate_baseline(df: pd.DataFrame, baseline_c: pd.DataFrame) -> pd.DataFrame:
    """C유형 컬럼의 "평소 위험구간 진입률"을 안정 구간 x OK샷 기준으로 산출한다.

    (26.08.08 신설) 왜 여기서 한 번에 만드는가 — 예전엔 이 값을 소비자가 각자 계산했고,
    정의가 셋으로 갈려 있었다: trend_analysis.py는 그룹별 진입률의 median(전체 샷),
    build_health_index.py는 일별 진입률의 median(전체 샷). 같은 이름으로 화면에 찍히는
    값과 경보를 내는 값이 달랐다. 단일 출처로 합친다.

    안정 구간은 (장비 x 컬럼) 단위로 정한다 — Product x Recipe 그룹까지 쪼개면 그룹당
    하루 5샷 수준이라 일별 계열 자체가 성립하지 않는다. 반면 진입률 자체는 그룹별로
    내는데(같은 안정 구간 안에서), threshold가 그룹마다 다르고 실측 그룹간 편차도
    작지 않기 때문이다(CLN_Pressure 1.2~9.0%, Surface_Roughness 13~33%).

    반환 컬럼: Machine_ID / column / group_key / stable_days / n_ok_shots / n_in_zone /
    baseline_rate. 장비 단위 대표값이 필요한 소비자는 group_key 축으로 median을 잡는다
    (기존 trend_analysis.py와 같은 방식).
    """
    thr_map = {
        (r.column, r.group_key): (r.threshold, r.risky_direction)
        for r in baseline_c.itertuples(index=False)
    }
    columns = sorted({c for c, _ in thr_map})

    work = df[["Machine_ID", "Product_ID", "Recipe_ID", "DateTime", "NG_Code"] + columns].copy()
    work["date"] = work["DateTime"].dt.date
    work["group_key"] = work["Product_ID"] + "|" + work["Recipe_ID"]
    # baseline은 OK 샷만 — 불량 샷은 정의상 위험구간 쪽에 몰려 있어 섞으면 기준이 밀린다.
    work = work.loc[work["NG_Code"] == "OK"]

    rows = []
    for col in columns:
        thr = work["group_key"].map(lambda gk: thr_map.get((col, gk), (np.nan, None))[0])
        direction = work["group_key"].map(lambda gk: thr_map.get((col, gk), (np.nan, None))[1])
        in_zone = np.where(
            direction == "low_is_risky", work[col] < thr,
            np.where(direction == "high_is_risky", work[col] > thr, np.nan),
        )
        tmp = pd.DataFrame({
            "Machine_ID": work["Machine_ID"],
            "group_key": work["group_key"],
            "date": work["date"],
            "in_zone": pd.to_numeric(pd.Series(in_zone, index=work.index), errors="coerce"),
        }).dropna(subset=["in_zone"])

        for machine, mg in tmp.groupby("Machine_ID"):
            daily = mg.groupby("date")["in_zone"].mean().sort_index()
            stable_days = find_stable_baseline_days(daily)
            stable_dates = set(daily.index[:stable_days])
            phase1 = mg.loc[mg["date"].isin(stable_dates)]
            for group_key, gg in phase1.groupby("group_key"):
                n = len(gg)
                if not n:
                    continue
                rows.append({
                    "Machine_ID": machine,
                    "column": col,
                    "group_key": group_key,
                    "stable_days": stable_days,
                    "n_ok_shots": n,
                    "n_in_zone": int(gg["in_zone"].sum()),
                    "baseline_rate": float(gg["in_zone"].mean()),
                })

    return pd.DataFrame(rows).sort_values(["Machine_ID", "column", "group_key"])


def compute_machine_column_trend(daily_series: pd.DataFrame) -> pd.DataFrame:
    """compute_machine_daily_series 결과에 Mann-Kendall(=kendalltau)+OLS 기울기 검정.

    89일 전체 구간을 한 번에 검정하는 방식이라(요약 통계 하나), 언제부터/얼마나
    나빠지고 있는지 날짜별 추이를 보려면 daily_series를 직접 rolling으로 쓸 것
    — 이 표는 "장기적으로 드리프트가 있는 조합이 맞는지"를 확정하는 용도다.
    """
    rows = []
    for (machine, col), g in daily_series.groupby(["Machine_ID", "column"]):
        series = g.sort_values("date")["daily_mean_z"]
        day_index = np.arange(len(series))
        tau, p_value = mann_kendall(pd.Series(day_index), series)

        ols_slope, ols_pvalue = np.nan, np.nan
        valid = series.dropna()
        if len(valid) >= 3:
            x = sm.add_constant(np.arange(len(valid)))
            model = sm.OLS(valid.values, x).fit()
            ols_slope = float(model.params[1])
            ols_pvalue = float(model.pvalues[1])

        if pd.notna(p_value) and p_value < config.TREND_ALPHA:
            trend_class = "candidate_upward_drift" if tau > 0 else "candidate_downward_drift"
        else:
            trend_class = "no_trend"

        rows.append(
            {
                "Machine_ID": machine,
                "column": col,
                "n_days": len(valid),
                "kendall_tau": tau,
                "kendall_p_value": p_value,
                "ols_slope_per_day": ols_slope,
                "ols_p_value": ols_pvalue,
                "trend_class": trend_class,
            }
        )
    return pd.DataFrame(rows)


def summarize_column_trend(machine_trend: pd.DataFrame) -> dict[str, str]:
    """장비별 추세를 컬럼 단위로 요약: 하나라도 유의한 상승/하강이 있으면 candidate_*."""
    summary = {}
    for col, g in machine_trend.groupby("column"):
        classes = set(g["trend_class"])
        has_up = "candidate_upward_drift" in classes
        has_down = "candidate_downward_drift" in classes
        if has_up and has_down:
            summary[col] = "mixed"
        elif has_up:
            summary[col] = "candidate_upward_drift"
        elif has_down:
            summary[col] = "candidate_downward_drift"
        else:
            summary[col] = "no_trend"
    return summary


# ---------------------------------------------------------------------------
# 4단계: 결측 / 물리적으로 불가능한 0값 / flatline(고착) 탐지
# ---------------------------------------------------------------------------

def detect_missing_sensor_faults(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    df_sorted = df.sort_values(["Machine_ID", "DateTime"])

    flatline_counts: dict[str, int] = {}
    for col in SENSOR_FLATLINE_CHECK_COLS:
        flagged = 0
        for _, g in df_sorted.groupby("Machine_ID"):
            s = g[col]
            same_as_prev = s.eq(s.shift())
            run_id = (~same_as_prev).cumsum()
            run_len = s.groupby(run_id).transform("size")
            flagged += int((run_len >= config.FLATLINE_RUN_LENGTH).sum())
        flatline_counts[col] = flagged

    rows = []
    for col in df.columns:
        if col in ("DateTime", "is_normal"):
            continue
        missing = int(df[col].isna().sum())
        zero_count = int((df[col] == 0).sum()) if col in config.ZERO_IMPLAUSIBLE_COLS else 0
        flat = flatline_counts.get(col, 0)
        rows.append(
            {
                "column": col,
                "missing_count": missing,
                "missing_rate": missing / total,
                "zero_implausible_count": zero_count,
                "zero_implausible_rate": zero_count / total,
                "flatline_flagged_count": flat,
                "flatline_flagged_rate": flat / total,
                "suggested_handling": "flag_only",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5단계: 컬럼 분류 taxonomy
# ---------------------------------------------------------------------------

def _subsystem_of(col: str) -> str:
    for name, cols in config.SUBSYSTEMS.items():
        if col in cols:
            return name
    return "id_production"


def _data_type_of(col: str) -> str:
    if col == "DateTime":
        return "datetime"
    if col in ("Lot_ID", "Strip_ID"):
        return "id"
    if col in ("Machine_ID", "Product_ID", "Recipe_ID", "Shift", "Operator_ID", "NG_Code"):
        return "categorical"
    if col in config.DEFECTS_BINARY:
        return "binary"
    if col in config.DEFECTS_COUNT or col in ("Door_Open_Count", "Fan_RPM", "Maintenance_Count"):
        return "count"
    return "continuous"


def _analysis_role_of(col: str) -> str:
    if col == "DateTime":
        return "datetime"
    if col in config.EXCLUDED_IDENTIFIERS:
        return "identifier_excluded"
    if col in mentor.MENTOR_EXCLUDED_VARS:
        return "mentor_excluded"
    if col in ("Machine_ID", "Product_ID", "Recipe_ID"):
        return "context_stratum"
    if col in ("Yield", "NG_Code"):
        return "target_outcome"
    if col in mentor.MENTOR_EXCLUDED_DEFECTS:
        return "mentor_excluded_defect"
    if col in config.DEFECTS_BINARY or col in config.DEFECTS_COUNT:
        return "target_defect"
    if col in config.UNDOCUMENTED_EXCLUDED:
        return "undocumented_excluded"
    if col == "Maintenance_Count":
        return "undocumented_retained"
    return "predictor"  # FDC_* / response


def build_column_classification(
    df: pd.DataFrame,
    df_normal: pd.DataFrame,
    trend_summary: dict[str, str],
    fault_flags: pd.DataFrame,
) -> pd.DataFrame:
    fault_lookup = fault_flags.set_index("column")
    rows = []
    for col in df.columns:
        if col in ("is_normal",) or col in config.DOMAIN_FEATURES:
            continue  # 원본 68개 컬럼만; 파생 도메인 피처는 별도 문서화
        data_type = _data_type_of(col)
        role = _analysis_role_of(col)
        subsystem = _subsystem_of(col)

        ratio, var_class, disp_method = np.nan, "not_applicable", "not_applicable"
        if data_type == "continuous" and col in CONTINUOUS_TREND_COLS:
            # 연속형 FDC/response: '정상 공정의 안정성'을 보는 것이 목적이므로 OK행 기준(df_normal).
            ratio, var_class, disp_method = variability_continuous(df_normal, col)
        elif data_type == "binary":
            # defect 발생률은 OK행에서 항상 0이므로 전체 데이터(df) 기준으로 계산.
            ratio, var_class, disp_method = variability_binary(df, col)
        elif data_type == "count":
            ratio, var_class, disp_method = variability_count(df, col)

        trend_class = trend_summary.get(col, "not_applicable")

        decision_note = config.UNDOCUMENTED_COL_NOTES.get(col, "")
        if not decision_note:
            if role == "identifier_excluded":
                decision_note = "멘토 피드백: 로트 추적/작업자 식별용, 분석 피처로 부적합 — 원본엔 보존, 피처셋에서 제외."
            elif role == "mentor_excluded":
                decision_note = mentor.MENTOR_EXCLUDED_VARS_NOTE
            elif role == "mentor_excluded_defect":
                decision_note = mentor.MENTOR_EXCLUDED_DEFECTS_NOTE
            elif role == "context_stratum":
                decision_note = "장비/제품/레시피 층 정의 및 범주형 통제변수로 사용."
            elif role == "target_outcome":
                decision_note = "공정 결과 라벨 — 피처가 아니라 타깃/검증값(Goal2 타깃, Goal5 검증)."
            elif role == "target_defect":
                decision_note = "defect 타깃 — Goal2/4의 예측 대상."

        mentor_note = mentor.MENTOR_DOMAIN_NOTES.get(col)
        if mentor_note:
            decision_note = f"{decision_note} {mentor_note}".strip() if decision_note else mentor_note

        pending_note = mentor.MENTOR_PENDING_REVIEW.get(col)
        if pending_note:
            decision_note = f"{decision_note} {pending_note}".strip() if decision_note else pending_note

        include_default = role in (
            "predictor", "context_stratum", "target_defect", "target_outcome", "undocumented_retained",
        )

        f = fault_lookup.loc[col] if col in fault_lookup.index else None
        rows.append(
            {
                "column": col,
                "subsystem": subsystem,
                "data_type": data_type,
                "analysis_role": role,
                "variability_class": var_class,
                "variability_ratio": ratio,
                "dispersion_method": disp_method,
                "degradation_trend_class": trend_class,
                "missing_rate": float(f["missing_rate"]) if f is not None else np.nan,
                "zero_fault_rate": float(f["zero_implausible_rate"]) if f is not None else np.nan,
                "flatline_fault_rate": float(f["flatline_flagged_rate"]) if f is not None else np.nan,
                "is_operation_condition_key": col in config.OPCOND,
                "is_excluded_identifier": col in config.EXCLUDED_IDENTIFIERS,
                "is_mentor_excluded": col in mentor.MENTOR_EXCLUDED_VARS,
                "is_mentor_excluded_defect": col in mentor.MENTOR_EXCLUDED_DEFECTS,
                "mentor_pending_review": col in mentor.MENTOR_PENDING_REVIEW,
                "include_in_downstream_default": include_default,
                "decision_note": decision_note,
            }
        )
    result = pd.DataFrame(rows)
    assert len(result) == 68, f"컬럼 분류표가 68개 원본 컬럼을 모두 포함해야 함 (실제 {len(result)}개)"
    return result


# ---------------------------------------------------------------------------
# 6단계: Baseline 유형(A/B/C/E) — Jun 브랜치 `26.07.29 Baseline 관련 작업/` 이식
# ---------------------------------------------------------------------------

def _ok_median_baseline(ok_df: pd.DataFrame, columns: list[str]) -> dict[tuple[str, str], float]:
    """그룹(Product_ID x Recipe_ID)별 OK median. A/B유형이 공유하는 단일 계산 — 중복 방지.

    (26.08.05 정정) A유형은 원래 "그룹 내 맨 처음 25행 평균"을 썼는데, Vibration/Head_Temp처럼
    시간이 지나며 서서히 나빠지는 게 정상인 열화형 변수엔 이 방식이 구조적으로 안 맞았다 —
    데이터 수집 초기(제일 양호했던 시점)를 기준으로 삼으니 이후 거의 모든 시점이 "비정상적으로
    나쁘게" 보이는 편향이 생겼다(실측 확인: PKG_A|RCP_1에서 Vibration은 4개 장비 전부의 정상
    median이 이 초기값보다 0.44~0.93 표준편차 높았음). A와 B의 차이는 baseline 계산법이 아니라
    "방향성이 정해져 있는가(A)/양방향 다 위험한가(B)"에 있어야 하므로, 계산은 B와 통일한다.
    """
    result: dict[tuple[str, str], float] = {}
    for (product, recipe), group in ok_df.groupby(["Product_ID", "Recipe_ID"]):
        group_key = f"{product}|{recipe}"
        for column in columns:
            result[(column, group_key)] = round(group[column].median(), 5)
    return result


def compute_baseline_type_a(ok_df: pd.DataFrame) -> pd.DataFrame:
    """A유형(방향성 있는 단조 drift형): 그룹별 baseline + 확정된 악화 방향.

    (26.08.05) SPEC(pipeline/mentor.py, 멘토 실측)에 있는 컬럼은 OK median 대신
    멘토의 TARGET을 baseline으로 쓴다 — "실측 중앙값"보다 "멘토가 맞다고 한 값"이
    더 권위 있는 기준이라서다. SPEC에 없는 컬럼은 기존처럼 OK median.
    """
    medians = _ok_median_baseline(ok_df, list(config.BASELINE_A_DIRECTION.keys()))
    rows = []
    for (column, group_key), median_value in medians.items():
        if column in SPEC:
            baseline_value, method = SPEC[column]["TARGET"], "mentor_target"
        else:
            baseline_value, method = median_value, "opcond_OK_median"
        rows.append({
            "type": "A",
            "column": column,
            "group_key": group_key,
            "baseline_method": method,
            "baseline_value": baseline_value,
            "bad_direction": "up" if config.BASELINE_A_DIRECTION[column] else "down",
        })
    return pd.DataFrame(rows)


def compute_baseline_type_b(ok_df: pd.DataFrame) -> pd.DataFrame:
    """B유형(U자형/최적구간형, 방향 무관): 그룹별 baseline.

    (26.08.05) A유형과 동일하게, SPEC에 있는 컬럼은 멘토 TARGET을 우선한다.
    단, config.TARGET_RECOMPUTE_FROM_DATA에 있는 컬럼(현재 Kerf_Width_Profile)은
    예외 — 실측 평균이 멘토 TARGET에서 스펙 폭의 12%나 벗어나 있고 89일 내내 안
    줄어드는 정적 오프셋이라, LSL/USL(위험 경계)은 멘토 값을 신뢰하되 TARGET(정상
    기준값)만 OK median으로 재계산한다.
    """
    medians = _ok_median_baseline(ok_df, config.BASELINE_B_COLUMNS)
    rows = []
    for (column, group_key), median_value in medians.items():
        if column in SPEC and column in config.TARGET_RECOMPUTE_FROM_DATA:
            baseline_value, method = median_value, "opcond_OK_median (target 재계산, LSL/USL은 멘토값 유지)"
        elif column in SPEC:
            baseline_value, method = SPEC[column]["TARGET"], "mentor_target"
        elif column == "CLN_Time":
            baseline_value, method = median_value, "opcond_OK_median (재분류: C->B)"
        else:
            baseline_value, method = median_value, "opcond_OK_median"
        rows.append({
            "type": "B",
            "column": column,
            "group_key": group_key,
            "baseline_method": method,
            "baseline_value": baseline_value,
        })
    return pd.DataFrame(rows)


def _find_baseline_c_breakpoint(values: pd.Series, defect_flags: pd.Series) -> dict | None:
    """단일 컬럼 x 단일 Defect 플래그에 대해 결정트리 스텀프로 위험 경계값을 추정한다."""
    n_ng = int(defect_flags.sum())
    if n_ng < config.BASELINE_C_MIN_SAMPLES_LEAF:
        return None  # NG 표본 부족 -> 추정 불가

    x = values.to_numpy().reshape(-1, 1)
    y = defect_flags.to_numpy()

    # (26.08.08) class_weight="balanced" 추가 — Goal2 관계DB(rel_20_tier_table.csv)의
    # threshold_method 컬럼이 "DecisionTree stump(max_depth=1, class_weight=balanced)"로
    # 명시돼 있는데 여기만 빠져 있었다. 불량률이 2~8%인 불균형 데이터라 가중치 없이는
    # 다수 클래스(정상)를 맞히는 쪽으로 분할점이 끌린다. 같은 방법이라고 문서에 적힌
    # 두 구현이 다른 값을 내면 안 되므로 DB 쪽에 맞춘다(김시우님 지적).
    tree = DecisionTreeClassifier(
        max_depth=1, min_samples_leaf=config.BASELINE_C_MIN_SAMPLES_LEAF,
        class_weight="balanced", random_state=0,
    )
    tree.fit(x, y)

    if tree.tree_.feature[0] == -2:
        return None  # 분기 자체가 생성되지 않음 (분리 불가능)

    threshold = tree.tree_.threshold[0]
    below = defect_flags[values < threshold]
    above = defect_flags[values >= threshold]
    if len(below) == 0 or len(above) == 0:
        return None

    ng_rate_below = below.mean()
    ng_rate_above = above.mean()
    risky_direction = "low_is_risky" if ng_rate_below > ng_rate_above else "high_is_risky"

    return {
        "threshold": round(float(threshold), 5),
        "n_NG": n_ng,
        "NG_rate_below": round(float(ng_rate_below), 5),
        "NG_rate_above": round(float(ng_rate_above), 5),
        "risky_direction": risky_direction,
    }


def compute_baseline_type_c(df: pd.DataFrame) -> pd.DataFrame:
    """C유형(편측 위험 threshold형): OK+NG 전체 데이터로 그룹별 위험 경계값 학습.

    OK 데이터만으로는 위험선을 추정할 수 없다(정상 범위 내부 분포만 보고서는
    어디부터 위험한지 알 수 없음) — 그래서 다른 유형과 달리 df_normal이 아니라
    전체 df를 입력으로 받는다.
    """
    rows = []
    for (product, recipe), group in df.groupby(["Product_ID", "Recipe_ID"]):
        for column, defect_col in resolve_defect_pairing().items():
            result = _find_baseline_c_breakpoint(group[column], group[defect_col])
            if result is None:
                continue
            rows.append({
                "column": column,
                "matched_defect": defect_col,
                "group_key": f"{product}|{recipe}",
                **result,
            })
    return pd.DataFrame(rows)


def _stump_separation(values: pd.Series, defect_flags: pd.Series) -> dict | None:
    """_find_baseline_c_breakpoint에 "분리배수"(경계 아래위 불량률 비)를 덧붙인다."""
    result = _find_baseline_c_breakpoint(values, defect_flags)
    if result is None:
        return None
    lo, hi = result["NG_rate_below"], result["NG_rate_above"]
    if min(lo, hi) <= 0:
        return None  # 한쪽이 0이면 배수가 무한대 — 표본 부족 신호로 보고 제외
    result["separation_ratio"] = max(lo, hi) / min(lo, hi)
    return result


def scan_type_c_candidates(
    df: pd.DataFrame, columns: list[str], defect_cols: list[str], n_permutations: int = 40, seed: int = 0
) -> pd.DataFrame:
    """전 컬럼 x 전 defect에 결정트리 스텀프를 돌려 C유형 후보를 스캔한다(순열검정 포함).

    (26.08.07 추가) 왜 필요한가 — 지금까지 C유형 배정은 resolve_defect_pairing()(관계DB)에
    하드코딩돼 있고, compute_baseline_type_c는 **거기 이미 적힌 컬럼만** threshold를
    계산한다. 즉 파이프라인이 새 후보를 스스로 발견할 수도, 기존 배정이 여전히 유효한지
    확인할 수도 없었다. 실제로 근거 계산은 파이프라인 밖 일회성 코드로 돌리고 결과 수치는
    config.py 주석에만 남겼는데, 그 주석이 이미 현실과 어긋난 게 확인됐다(CLN_Pressure를
    "20.8배"로 적어놨지만 R1 기준 재계산 결과는 4.5배).

    핵심 문제는 **결정트리는 아무 컬럼에나 돌려도 threshold를 반드시 만들어낸다**는 것이다
    (표본 안에서 가장 잘 갈리는 지점을 고르는 알고리즘이므로 순수 노이즈에도 분리가 생김).
    그래서 "분리가 되는가"가 아니라 "우연히 생길 수준을 넘는가"로 판단해야 한다.

    노이즈 천장은 **순열검정**으로 구한다 — 같은 데이터에서 defect 라벨만 무작위로 섞어
    같은 스캔을 돌리면, 그때 나오는 분리배수가 "인과가 전혀 없을 때 이 방법이 만들어내는
    분리"의 분포다. 그 분포의 p95를 천장으로 쓴다. 예전처럼 "무관해 보이는 컬럼들의 값"을
    천장으로 삼으면 어느 컬럼이 무관한지를 미리 알아야 해서 순환논리가 된다.

    관측 통계량이 "그룹별 배수의 median"이므로 순열 통계량도 같은 수준에서 만든다
    (순열 1회 x 컬럼 1개 = 천장 표본 1개). 유형 배정 자체를 자동화하지는 않는다 — 방향
    (A유형 bad_direction)이나 이론 상수(E유형)는 데이터가 아니라 물리 지식에서 나오기
    때문이다. 이 표는 사람이 내린 배정이 데이터와 어긋날 때 드러나게 하는 용도다
    (main의 불일치 경고 참고).
    """
    rng = np.random.default_rng(seed)
    groups = [(g[columns + defect_cols]) for _, g in df.groupby(["Product_ID", "Recipe_ID"])]

    rows = []
    for defect in defect_cols:
        null_ratios = []      # 컬럼 1개 = 표본 1개 (개별 검정용 p95)
        null_max_ratios = []  # 순열 1회 = 표본 1개, 그 안의 전 컬럼 최댓값 (FWER용)
        null_max_consistency = []  # 방향일관성도 같은 방식으로 천장을 만든다
        for _ in range(n_permutations):
            this_perm, this_perm_cons = [], []
            for col in columns:
                per_group, per_dir = [], []
                for g in groups:
                    shuffled = pd.Series(rng.permutation(g[defect].to_numpy()), index=g.index)
                    s = _stump_separation(g[col], shuffled)
                    if s is not None:
                        per_group.append(s["separation_ratio"])
                        per_dir.append(s["risky_direction"])
                if per_group:
                    this_perm.append(float(np.median(per_group)))
                    cnt = pd.Series(per_dir).value_counts()
                    this_perm_cons.append(float(cnt.iloc[0] / len(per_dir)))
            null_ratios.extend(this_perm)
            if this_perm:
                null_max_ratios.append(max(this_perm))
                null_max_consistency.append(max(this_perm_cons))
        noise_ceiling = float(np.percentile(null_ratios, 95)) if null_ratios else np.nan
        # (26.08.08) 다중비교 보정 천장. p95 천장은 "컬럼 하나를 골라 검정했을 때"의 기준이라,
        # 34개 컬럼을 전부 훑는 이 스캔에 그대로 쓰면 컬럼당 5%씩 오탐이 쌓인다(기대 1.7개).
        # 실제로 그 차이가 판정을 가른다 — Vibration->Particle은 p95(2.054)는 넘지만 보정
        # 천장은 못 넘는다(2.26 vs 2.34). Bonferroni 대신 Westfall-Young 최댓값 통계량을
        # 쓴다: 순열 1회마다 "그 순열에서 가장 잘 갈린 컬럼"을 기록하면, 그 분포가 곧
        # "아무 관계 없을 때 34개 중 최고가 어디까지 가는가"라 FWER을 정확히 통제한다
        # (컬럼 간 상관을 자동 반영하므로 Bonferroni보다 덜 보수적이고, p99.93 같은
        #  극단 분위수를 직접 추정할 필요가 없어 순열 횟수도 훨씬 적게 든다).
        fwer_ceiling = float(np.percentile(null_max_ratios, 95)) if null_max_ratios else np.nan
        # 방향일관성 천장도 같은 논리로 순열에서 만든다. 예전엔 0.8을 손으로 박아뒀는데
        # 근거가 없었다 — 스텀프는 관계가 없어도 그룹마다 어느 한쪽을 "위험"으로 반드시
        # 고르므로, 순수 노이즈에서도 일관성이 꽤 높게 나올 수 있다(그 수준이 얼마인지는
        # 그룹 수/표본에 따라 달라져서 상수로 못 박는다). 34개 중 최고를 천장으로 쓴다.
        cons_ceiling = float(np.percentile(null_max_consistency, 95)) if null_max_consistency else np.nan

        for col in columns:
            ratios, thresholds, directions = [], [], []
            for g in groups:
                s = _stump_separation(g[col], g[defect])
                if s is None:
                    continue
                ratios.append(s["separation_ratio"])
                thresholds.append(s["threshold"])
                directions.append(s["risky_direction"])
            if not ratios:
                continue
            counts = pd.Series(directions).value_counts()
            separation = float(np.median(ratios))
            consistency = float(counts.iloc[0] / len(directions))
            rows.append({
                "defect": defect,
                "column": col,
                "n_groups_fitted": len(ratios),
                "separation_ratio_median": round(separation, 3),
                "noise_ceiling_p95": round(noise_ceiling, 3),
                "noise_ceiling_fwer": round(fwer_ceiling, 3),
                "consistency_ceiling_fwer": round(cons_ceiling, 3),
                # 천장 대비 몇 배인가 — 1.0 이하면 순수 노이즈와 구분 불가.
                "signal_over_noise": round(separation / noise_ceiling, 2) if noise_ceiling else np.nan,
                # C유형 채택 기준(아래 두 조건 동시 충족) — warn_type_c_mismatch 주석 참고.
                "passes_fwer": bool(separation > fwer_ceiling) if fwer_ceiling else False,
                "passes_direction": bool(consistency > cons_ceiling) if cons_ceiling else False,
                "threshold_median": round(float(np.median(thresholds)), 5),
                "dominant_direction": str(counts.index[0]),
                # 그룹마다 위험 방향이 갈리면 대표값 하나로 못 줄인다(CLN_Time이 이래서 B유형).
                "direction_consistency": round(consistency, 3),
                "has_mentor_spec": col in SPEC,
                "assigned_type_c": resolve_defect_pairing().get(col) == defect,
            })
    return pd.DataFrame(rows).sort_values(["defect", "separation_ratio_median"], ascending=[True, False])


def warn_type_c_mismatch(candidates: pd.DataFrame) -> None:
    """스캔 결과를 요약하고, 배정과 데이터가 어긋나면 양방향으로 경고한다.

    (26.08.08) **C유형 채택 기준을 여기 한 번만 적어두고 전 컬럼에 똑같이 적용한다.**
    예전엔 기준이 글로만 있고(노이즈 천장 p95 + 방향일관성 0.8) 실제 배정은 그때그때
    사람이 했는데, 그러면 지적받은 컬럼만 검토되고 나머지는 방치된다. 기준은 둘이다:

      (1) 분리배수 > 순열 최댓값 천장(FWER 95%)  — 34컬럼을 동시에 훑는 다중비교 보정
      (2) 방향일관성 > 순열 최댓값 천장(FWER 95%) — 전 그룹이 같은 쪽을 위험으로 지목

    둘 다 순열에서 나온 값이라 사람이 고른 상수가 없다.

    남은 판단 하나는 데이터로 못 정한다 — **"정상 target"이 정의되는 변수인가**. 정의되면
    양측 변수라 B/A가 맞다(C는 편측 위험선만 그을 수 있는 변수를 위한 것). 다만 이건
    "멘토 스펙이 있으면 자동 B"가 아니다. 스펙은 있는데 불량이 뛰는 경계가 스펙 **안쪽**에
    있으면 스펙 감시만으론 못 잡는다 — 그 경우는 스펙 검사(유형 무관 공통 적용)와 C유형
    threshold를 둘 다 거는 게 맞다.

    그래서 경고는 **양방향**으로 낸다. 배정됐는데 기준 미달인 것뿐 아니라, 기준을 통과했는데
    배정이 없는 것도 띄운다(예전엔 후자를 일부러 뺐는데, 그러면 사람이 표를 직접 열어보지
    않는 한 새 후보가 영영 안 보인다 — 실제로 Coating_Thickness->Remain_Coat가 그렇게
    묻혀 있었다). 통과했다고 자동 배정하지는 않는다 — 짝짓기의 단일 출처는 Goal2 관계DB다.
    """
    if candidates.empty:
        return
    print("\n[C유형 스캔] 순열검정 천장 대비 신호 강도 (상세: 00_baseline_C_candidates.csv)")
    for defect, g in candidates.groupby("defect"):
        print(f"  {defect}: 분리 천장 {g['noise_ceiling_fwer'].iloc[0]}배(FWER) / "
              f"{g['noise_ceiling_p95'].iloc[0]}배(p95), 방향일관성 천장 "
              f"{g['consistency_ceiling_fwer'].iloc[0]}")
        passed = g[g["passes_fwer"] & g["passes_direction"]]
        for r in passed.itertuples(index=False):
            mark = "배정됨" if r.assigned_type_c else "미배정"
            print(f"    통과 {r.column:26s} 분리 {r.separation_ratio_median:8.3f} "
                  f"방향 {r.direction_consistency:.3f} [{mark}]")

    assigned = candidates[candidates["assigned_type_c"]]
    missing_rows = set(resolve_defect_pairing().items()) - set(zip(assigned["column"], assigned["defect"]))
    weak = assigned[~(assigned["passes_fwer"] & assigned["passes_direction"])]
    for r in weak.itertuples(index=False):
        print(f"  [경고] {r.column}->{r.defect}는 C유형으로 배정돼 있으나 이번 스캔에서 기준 미달"
              f"(분리 {r.separation_ratio_median} vs 천장 {r.noise_ceiling_fwer}, "
              f"방향일관성 {r.direction_consistency} vs 천장 {r.consistency_ceiling_fwer}) — 재검토 필요.")
    for col, defect in sorted(missing_rows):
        print(f"  [경고] {col}->{defect}는 C유형으로 배정돼 있으나 스캔에서 threshold 학습 자체가 안 됨"
              f"(표본 부족 등) — 재검토 필요.")
    unassigned = candidates[candidates["passes_fwer"] & candidates["passes_direction"]
                            & ~candidates["assigned_type_c"]]
    for r in unassigned.itertuples(index=False):
        print(f"  [후보] {r.column}->{r.defect}는 기준을 통과했으나 관계DB에 짝이 없음"
              f"(분리 {r.separation_ratio_median}배, 방향일관성 {r.direction_consistency}, "
              f"경계 {r.threshold_median}) — 관계DB 판정 요청 대상.")
    if weak.empty and not missing_rows:
        print(f"  배정된 C유형 {len(assigned)}건 모두 기준 통과.")


def compute_baseline_type_e(ok_df: pd.DataFrame) -> pd.DataFrame:
    """E유형(대칭성/정렬형): 그룹핑 없는 이론 상수 + 참고용 실측 OK mean/std."""
    rows = []
    for column, constant in config.BASELINE_E_CONSTANTS.items():
        rows.append({
            "type": "E",
            "column": column,
            "baseline_method": "theoretical_constant",
            "baseline_value": constant,
            "reference_OK_mean": round(ok_df[column].mean(), 5),
            "reference_OK_std": round(ok_df[column].std(), 5),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _apply_mentor_target_override(baseline_df: pd.DataFrame) -> pd.DataFrame:
    """SPEC(pipeline/mentor.py)에 있는 컬럼은 median을 멘토 TARGET으로 덮어쓴다.

    z-score 중심이 "실제 그동안 어땠는지"(median)가 아니라 "원래 어때야 하는지"(TARGET)여야
    맞다 — 실측이 TARGET에서 미세하게 벗어나 있으면 median 기준으론 그 편차 자체가
    안 보인다(자기 자신을 기준으로 삼으니 항상 0으로 보임). median_source 컬럼에
    "mentor_target"/"empirical"로 출처를 남긴다. scale(mad/robust_z_scale)은 그대로
    실측 분산을 쓴다 — TARGET은 "어디가 0이어야 하는지"만 바꾸고 "얼마나 흩어져 있는지"는
    안 바꾸는 게 맞기 때문.
    """
    result = baseline_df.copy()
    result["median_source"] = "empirical"
    for column, spec in SPEC.items():
        mask = result["column"] == column
        if mask.any():
            result.loc[mask, "median"] = spec["TARGET"]
            result.loc[mask, "median_source"] = "mentor_target"
    return result


def main() -> None:
    df = load_and_validate()
    df_normal = df.loc[df["is_normal"]]

    opcond_baseline = _apply_mentor_target_override(
        compute_stratum_baseline_stats(df_normal, config.OPCOND, CONTINUOUS_BASELINE_COLS)
    )
    machine_opcond_baseline = _apply_mentor_target_override(
        compute_stratum_baseline_stats(df_normal, config.GROUP, CONTINUOUS_BASELINE_COLS)
    )
    save_table(opcond_baseline, "00_stratum_baseline_stats_by_opcond.csv", subdir="preprocessing")
    save_table(machine_opcond_baseline, "00_stratum_baseline_stats_by_machine_opcond.csv", subdir="preprocessing")

    daily_series = compute_machine_daily_series(df, opcond_baseline)
    save_table(daily_series, "00_machine_daily_series.csv", subdir="preprocessing")

    machine_trend = compute_machine_column_trend(daily_series)
    save_table(machine_trend, "00_machine_column_trend.csv", subdir="preprocessing")

    # 장비×날짜 defect 발생률 — build_health_index/agent가 읽는다(analysis_outputs 루트).
    # 경로/파일명은 기존 소비자를 안 깨뜨리려고 그대로 둔다.
    save_table(compute_machine_daily_trend(df), "05_machine_daily_trend.csv")
    trend_summary = summarize_column_trend(machine_trend)

    fault_flags = detect_missing_sensor_faults(df)
    save_table(fault_flags, "00_missing_sensor_fault_flags.csv", subdir="preprocessing")

    classification = build_column_classification(df, df_normal, trend_summary, fault_flags)
    save_table(classification, "00_column_classification.csv", subdir="preprocessing")

    # Baseline A/B/C/E는 원본(Jun) 산출물 값을 그대로 재현하기 위해 df_normal(is_normal=
    # Yield==100 & NG_Code=='OK')이 아니라 Jun이 쓴 정의(NG_Code=='OK'만)로 별도 필터링한다.
    # is_normal보다 느슨한 정의라 df_normal의 부분집합이 아닐 수 있음 — 의도된 차이.
    ok_ng_code = df.loc[df["NG_Code"] == "OK"]
    baseline_a = compute_baseline_type_a(ok_ng_code)
    baseline_b = compute_baseline_type_b(ok_ng_code)
    baseline_ab = pd.concat([baseline_a, baseline_b], ignore_index=True)
    save_table(baseline_ab, "00_baseline_AB.csv", subdir="preprocessing")

    # (26.08.05) threshold "학습"은 R1(불량 사례 충분)으로, 실제 모니터링 대상(defect_zone_rate
    # 집계, 이후 trend_analysis.py 감시)은 계속 원본 df로 — R1은 원본과 합치지 않는다
    # (load_r1_for_threshold_training docstring 참고).
    r1_df = load_r1_for_threshold_training()
    threshold_source = r1_df if r1_df is not None else df

    # (26.08.07) C유형 배정이 여전히 데이터와 맞는지 매 실행마다 확인한다. compute_baseline_
    # type_c는 config에 이미 적힌 컬럼만 계산하므로 자기 배정을 검증할 수 없다 —
    # scan_type_c_candidates는 반대로 전 컬럼을 돌려서 사람 판단과 대조한다.
    # Yield는 제외한다 — 정의상 불량률의 반대편(Fail_Die vs 100-Yield Spearman 1.000)이라
    # 어떤 defect든 완벽히 가른다(누수). "원인"이 아니라 "결과"라 후보가 될 수 없다.
    #
    # (26.08.08) 스캔 대상을 threshold_source(R1)에서 **원본 df**로 되돌린다. R1은 불량
    # 시나리오를 의도적으로 주입한 학습셋이라, 거기서 나온 분리배수는 "주입 레시피"를
    # 되읽은 값이지 공정의 성질이 아니다(Chipping 기준 Kerf_Width_Profile 116배 같은
    # 값이 그 증거 — 원본에서는 그런 분리가 존재하지 않는다). threshold "값"을 R1에서
    # 배우는 건 표본 부족 때문에 불가피하지만, **어떤 컬럼이 어떤 유형인가**는 실제로
    # 감시하는 데이터에서 판단해야 한다.
    scan_cols = [c for c in CONTINUOUS_TREND_COLS
                 if c in df.columns and c != "Yield"]
    scan_defects = [d for d in config.DEFECTS_BINARY
                    if d in df.columns and d not in mentor.MENTOR_EXCLUDED_DEFECTS]
    c_candidates = scan_type_c_candidates(df, scan_cols, scan_defects)
    save_table(c_candidates, "00_baseline_C_candidates.csv", subdir="preprocessing")
    warn_type_c_mismatch(c_candidates)

    baseline_c = compute_baseline_type_c(threshold_source)
    save_table(baseline_c, "00_baseline_C.csv", subdir="preprocessing")

    # C유형 threshold는 샷 단위 경계라 일평균과 직접 비교하면 안 된다(위 함수 docstring 참고).
    # Health Index가 쓸 "그날 위험구간에 들어간 샷 비율"을 여기서 미리 집계해둔다.
    # (여기는 원본 df 그대로 — threshold는 R1에서 배웠지만, 적용/감시 대상은 원본이다.)
    defect_zone_rate = compute_daily_defect_zone_rate(df, baseline_c)
    save_table(defect_zone_rate, "00_machine_daily_defect_zone_rate.csv", subdir="preprocessing")

    # "평소 진입률"의 단일 출처 — trend_analysis.py(경보)와 build_health_index.py(화면)가
    # 각자 다르게 계산하던 값을 여기서 한 번만 만든다. 안정 구간 x OK샷 기준.
    c_entry_baseline = compute_c_entry_rate_baseline(df, baseline_c)
    save_table(c_entry_baseline, "00_baseline_C_entry_rate.csv", subdir="preprocessing")

    baseline_e = compute_baseline_type_e(ok_ng_code)
    save_table(baseline_e, "00_baseline_E.csv", subdir="preprocessing")

    # 정합성 체크: Fail_Die와 (100-Yield)는 정의상 강하게 연관되어야 함 — 안 그러면 파이프라인 버그.
    consistency_check = df["Fail_Die"].corr(100 - df["Yield"], method="spearman")
    assert consistency_check > 0.5, (
        f"Fail_Die와 (100-Yield)의 Spearman 상관이 비정상적으로 낮음 ({consistency_check:.3f}) — "
        "데이터 로드/조인 버그 의심"
    )

    include_cols = classification.loc[classification["include_in_downstream_default"], "column"].tolist()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(df),
        "unique_key_count": int(df[config.KEY].drop_duplicates().shape[0]),
        "normal_count": int(df["is_normal"].sum()),
        "fail_die_vs_yield_spearman": float(consistency_check),
        "include_in_downstream_default_columns": include_cols,
        "subsystem_column_counts": {
            name: len(cols) for name, cols in config.SUBSYSTEMS.items()
        },
        "mentor_excluded_columns": mentor.MENTOR_EXCLUDED_VARS,
        "mentor_excluded_defects": mentor.MENTOR_EXCLUDED_DEFECTS,
        "mentor_pending_review_columns": mentor.MENTOR_PENDING_REVIEW,
        "notes": [
            "die 단위 x,y 좌표 없음 — 공간(DBSCAN) 클러스터링은 이번 범위 제외.",
            "결측/불가능0/flatline은 flag_only 정책 — 자동 보간 없음.",
            "OPCOND=[Product_ID,Recipe_ID], GROUP=[Machine_ID,Product_ID,Recipe_ID] — 용도 다름, README 참고.",
            "mentor_pending_review_columns은 아직 멘토 최종 확정 전 — 임의 제외 금지, 결과 해석 시 주의.",
        ],
    }
    with open(config.PREPROCESSING_DIR / "00_preprocessing_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: Step0 산출물은 {config.PREPROCESSING_DIR}에 저장되었습니다.")
    print(f"  - 컬럼 분류: {len(classification)}개 컬럼")
    print(f"  - 다운스트림 기본 포함 컬럼: {len(include_cols)}개")
    print(f"  - Fail_Die vs (100-Yield) Spearman: {consistency_check:.3f}")


if __name__ == "__main__":
    main()
