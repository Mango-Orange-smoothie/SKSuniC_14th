"""Step0/Goal 모듈이 공유하는 헬퍼 함수.

기존 analysis_step_by_step.py의 save_table 규약(utf-8-sig CSV, analysis_outputs/ 하위)을
그대로 따르되, 서브폴더 저장을 지원하도록 확장한다.

(26.08.07) 이 파일의 함수는 성격이 두 가지인데 섞여 있으면 오해를 부른다 — 실제로
"아무도 안 쓰니 죽은 코드"로 잘못 진단된 적이 있다. 아래 두 구역으로 나눠서 표시한다.

  [파이프라인 연결] step0/Goal 스크립트가 실제로 호출하는 함수. 시그니처를 바꾸면
      호출부가 깨진다.
  [제공 도구] 강제 적용하지 않고 "Goal 담당자가 필요할 때 갖다 쓰라"고 만들어 둔 것
      (pipeline/README.md "추가 피처 엔지니어링 도구" 참고). 지금 호출부가 없는 건
      정상이며, 미사용이라고 지우면 안 된다 — 동작 검증까지 마치고 문서화해 둔 팀 자산이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.model_selection import train_test_split as _sk_train_test_split

from pipeline import config


def load_dataset(add_domain_features: bool = True) -> pd.DataFrame:
    """DP_HealthIndex_Dataset.csv를 로드한다 (xlsx 대비 약 73배 빠름).

    원본 파일은 절대 수정하지 않는다.
    """
    df = pd.read_csv(config.INPUT_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["is_normal"] = config.NORMAL(df)
    if add_domain_features:
        df = config.add_domain_features(df)
    return df


def save_table(table: pd.DataFrame | pd.Series, filename: str, subdir: str | None = None) -> None:
    """분석 표를 CSV로 저장한다 (Excel에서도 바로 열 수 있는 utf-8-sig)."""
    if isinstance(table, pd.Series):
        table = table.to_frame()
    out_dir = config.OUTPUT_DIR / subdir if subdir else config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / filename, encoding="utf-8-sig", index=False)


def spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman 순위상관. NaN 쌍 제거, 값이 1종류뿐이면 NaN 반환."""
    paired = pd.concat([x, y], axis=1).dropna()
    if len(paired) < 2 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
        return np.nan
    r, _ = scipy_stats.spearmanr(paired.iloc[:, 0], paired.iloc[:, 1])
    return float(r)


# ---------------------------------------------------------------------------
# [파이프라인 연결] step0/Goal 스크립트가 실제로 호출하는 함수
# ---------------------------------------------------------------------------

def mann_kendall(time_index: pd.Series, values: pd.Series) -> tuple[float, float]:
    """Mann-Kendall 단조추세 검정과 수학적으로 동일한 결과를 주는 Kendall's tau.

    pymannkendall 미설치 환경에서 scipy.stats.kendalltau(순서, 값)로 대체.
    반환: (tau, p_value). 유효 표본이 3개 미만이면 (nan, nan).
    """
    paired = pd.concat([pd.Series(time_index).reset_index(drop=True),
                         pd.Series(values).reset_index(drop=True)], axis=1).dropna()
    if len(paired) < 3 or paired.iloc[:, 1].nunique() < 2:
        return np.nan, np.nan
    tau, p_value = scipy_stats.kendalltau(paired.iloc[:, 0], paired.iloc[:, 1])
    return float(tau), float(p_value)


def compute_stratum_baseline_stats(
    df_normal: pd.DataFrame, stratum_keys: list[str], columns: list[str]
) -> pd.DataFrame:
    """OK행 기준 층별(median/MAD 포함) baseline 통계표를 long format으로 산출.

    04_provisional_control_limits.csv(median, 0.5~99.5분위)의 일반화이며 대체가 아니다.
    """
    grouped = df_normal.groupby(stratum_keys, dropna=False)
    frames = []
    for col in columns:
        g = grouped[col]
        agg = g.agg(n="count", mean="mean", std="std", median="median", min="min", max="max")
        agg["mad"] = g.apply(lambda s: (s - s.median()).abs().median())
        agg["p0_5"] = g.quantile(0.005)
        agg["p99_5"] = g.quantile(0.995)
        agg["column"] = col
        frames.append(agg.reset_index())
    result = pd.concat(frames, ignore_index=True)
    safe_mean = result["mean"].where(result["mean"].abs() > 1e-9)
    result["cv"] = result["std"] / safe_mean
    result["robust_z_scale"] = config.MAD_SCALE * result["mad"]
    cols_order = stratum_keys + [
        "column", "n", "mean", "std", "cv", "median", "mad",
        "robust_z_scale", "p0_5", "p99_5", "min", "max",
    ]
    return result[cols_order]


def zscore_transform(
    df: pd.DataFrame, baseline_long: pd.DataFrame, stratum_keys: list[str], columns: list[str]
) -> pd.DataFrame:
    """baseline_long(compute_stratum_baseline_stats 산출물)을 이용해 강건 z-score를 붙인다.

    z = (value - stratum_median) / (MAD_SCALE * stratum_MAD)
    평균/표준편차 대신 median/MAD를 쓰는 이유: 평균은 이미 열화·불량 tail에 끌려가
    baseline으로 부적합하기 때문 (OK행에서만 학습했더라도 tail-sensitivity 자체는 남음).
    """
    result = df.copy()
    for col in columns:
        sub = baseline_long.loc[baseline_long["column"] == col, stratum_keys + ["median", "robust_z_scale"]]
        sub = sub.rename(columns={"median": "__median", "robust_z_scale": "__scale"})
        result = result.merge(sub, on=stratum_keys, how="left")
        scale = result["__scale"].where(result["__scale"].abs() > 1e-9)
        result[f"{col}_z"] = (result[col] - result["__median"]) / scale
        result = result.drop(columns=["__median", "__scale"])
    return result


def binomial_alert_count(base_rate: float, n_trials: int, alpha: float) -> int:
    """평소 비율 base_rate에서 n_trials 중 k개 이상이 우연히 나올 확률이 alpha 미만이
    되는 최소 k를 돌려준다. 도달 불가능하면 n_trials + 1(= 절대 경보 안 뜸).

    (26.08.08 신설) 왜 "평소의 몇 배" 대신 이걸 쓰는가 — 고정 배수는 평소 비율에 따라
    엄격도가 제멋대로 달라진다. 10샷 창 기준 실측(2.0배일 때 평소에도 우연히 통과할 확률):
        CLN_Flow      평소  0.5% -> 10샷 중 1개면 통과 ->  4.7%
        CLN_Pressure  평소  6.4% -> 10샷 중 2개면 통과 -> 13.0%
        Surface_Rough 평소 32.0% -> 10샷 중 7개면 통과 ->  1.5%
    같은 "2배"가 컬럼마다 8.7배 차이 나는 기준이 된다(김시우님 지적). 배수를 고정하지
    말고 **오탐 확률을 고정**해야 컬럼 간에 비교 가능한 기준이 된다.

    base_rate=0이어도 정의된다(k=1) — 예전엔 "비율이 정의 안 됨"이라 별도 분기로
    빠졌는데, 이 식은 같은 공식이 자연히 그 답을 준다.
    """
    if not np.isfinite(base_rate) or base_rate < 0 or n_trials < 1:
        return n_trials + 1
    p = min(max(float(base_rate), 0.0), 1.0)
    for k in range(1, n_trials + 1):
        # sf(k-1) = P(X >= k)
        if scipy_stats.binom.sf(k - 1, n_trials, p) < alpha:
            return k
    return n_trials + 1


# ---------------------------------------------------------------------------
# [제공 도구] 강제 적용 안 함 — 필요할 때 갖다 쓰는 용도. 호출부가 없는 게 정상이며
# 미사용이라고 지우면 안 된다(pipeline/README.md "추가 피처 엔지니어링 도구" 참고).
# ---------------------------------------------------------------------------

def add_spec_deviation_features(
    df: pd.DataFrame, baseline_long: pd.DataFrame, stratum_keys: list[str], columns: list[str]
) -> pd.DataFrame:
    """OK군 층별 0.5~99.5 분위수를 임시 USL/LSL로 삼아 스펙이탈량 피처를 만든다.

    공식 SPEC 컬럼이 없는 데이터셋이라(04_provisional_control_limits.csv와 동일 철학),
    compute_stratum_baseline_stats가 이미 만들어둔 p0_5/p99_5를 대체 스펙 상하한으로 쓴다.
    Power_Efficiency처럼 "너무 높아도 너무 낮아도 위험"한 U자형(either) 변수는 부호 있는
    z-score로 평균을 내면 양/음이 서로 상쇄돼 사라지므로, 항상 0 이상인 이탈량으로 바꿔야
    선형/트리 모델이 바로 잡아낸다.

    exceedance = max(0, X - USL) + max(0, LSL - X)  (스펙 안이면 0)
    """
    result = df.copy()
    for col in columns:
        sub = baseline_long.loc[baseline_long["column"] == col, stratum_keys + ["p0_5", "p99_5"]]
        sub = sub.rename(columns={"p0_5": "__lsl", "p99_5": "__usl"})
        result = result.merge(sub, on=stratum_keys, how="left")
        over = (result[col] - result["__usl"]).clip(lower=0)
        under = (result["__lsl"] - result[col]).clip(lower=0)
        result[f"{col}_spec_exceedance"] = over + under
        result = result.drop(columns=["__usl", "__lsl"])
    return result


def add_ratio_features(df: pd.DataFrame, ratios: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """두 컬럼의 비율/상호작용 피처를 0나눔 방지하며 추가한다.

    단일 변수 하나로는 신호가 약해도 두 변수의 비율이 핵심 원인인 경우가 있다
    (예: Bottom_Kerf/Top_Kerf로 절단면 기울기 경향 포착). ratios는
    {새_컬럼명: (분자_컬럼, 분모_컬럼)} 형태 — 어떤 조합을 쓸지는 도메인 판단이라
    여기서 임의로 정하지 않고 호출부(Goal 담당자)가 결정한다.
    """
    result = df.copy()
    for name, (numer, denom) in ratios.items():
        safe_denom = result[denom].where(result[denom].abs() > 1e-9)
        result[name] = result[numer] / safe_denom
    return result


def add_rolling_trend_features(
    df: pd.DataFrame, group_col: str, time_col: str, columns: list[str], window: int = 5
) -> pd.DataFrame:
    """장비(group_col)별 시간순 정렬 후 최근 window개 샷의 rolling mean/std와 직전값 대비
    변화량(delta)을 붙인다.

    Cooling_Water_Temp/Laser_Head_Remain_Time처럼 단발성 수치 1개는 정상이어도 누적
    변동(drift)이 서서히 진행되며 불량으로 이어지는 경우, 그 시점 z-score만으로는 못
    잡는 신호를 잡기 위함. window는 팀 공용 상수로 승격하지 않고 인자로 노출한다 —
    Goal마다 적정 길이가 다를 수 있어(Machine_ID 그루핑) 실험적으로 바꿔볼 여지를 남긴다.

    주의: 원본 행(샷) 단위 df에 바로 쓰면 Machine×Product×Recipe 조합당 하루 평균
    샷 수가 적어(이 데이터셋 기준 ~5개) window=5~10이 실제로는 1~2일치밖에 안 될 수
    있다 — 여러 날에 걸친 추세를 보려면 `00_machine_daily_series.csv`(Step0 산출물,
    이미 날짜 단위로 집계됨)를 df로 넘길 것.
    """
    result = df.sort_values([group_col, time_col]).copy()
    for col in columns:
        grouped = result.groupby(group_col)[col]
        result[f"{col}_roll{window}_mean"] = grouped.transform(
            lambda s: s.rolling(window, min_periods=2).mean()
        )
        result[f"{col}_roll{window}_std"] = grouped.transform(
            lambda s: s.rolling(window, min_periods=2).std()
        )
        result[f"{col}_delta"] = grouped.diff()
    return result.sort_index()


def stratified_split_by_defect(
    df: pd.DataFrame,
    defect_col: str,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """defect_col의 발생률이 train/test에서 동일하게 유지되도록 층화 분할.

    Goal2는 defect 6종(Chipping/Remain_Coat/Particle/Micro_Crack/Laser_Paim/Edge_Burn)을
    각각 독립된 이진분류 문제로 다루므로, 모델을 학습할 때마다 그 defect 컬럼 하나만
    stratify 기준으로 삼는다 (6개를 동시에 맞추는 멀티라벨 층화가 아님 — sklearn
    train_test_split은 단일 라벨 stratify만 지원하고, 이 프로젝트 구조상 그걸로 충분함).

    Micro_Crack/Edge_Burn처럼 발생률이 낮은 defect는 무작위 분할 시 test set에 양성
    샘플이 거의 안 남을 수 있어 층화가 특히 중요하다.
    """
    labels = df[defect_col]
    counts = labels.value_counts()
    if labels.nunique() < 2 or counts.min() < 2:
        raise ValueError(
            f"'{defect_col}' 컬럼은 층화 분할이 불가능합니다 (클래스가 1개뿐이거나 "
            f"양성/음성 샘플 중 하나가 2개 미만 — 실제 분포: {counts.to_dict()}). "
            "이 defect는 stratify 없이 분할하거나 건너뛰세요."
        )
    train_df, test_df = _sk_train_test_split(
        df, test_size=test_size, random_state=random_state, stratify=labels
    )
    return train_df, test_df


def time_based_split(
    df: pd.DataFrame,
    time_col: str = "DateTime",
    test_fraction: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """시간순 정렬 후 뒷부분을 test로 떼어내는 분할 (미래 구간을 학습에서 완전히 제외).

    이 프로젝트의 핵심 목표가 '시간이 지나며 서서히 진행되는 열화 추세' 탐지이므로,
    무작위(층화) split은 미래 데이터가 학습에 섞여 실제로는 못 잡을 패턴도 모델이
    미리 본 것처럼 맞히게 만들어 성능을 과대평가할 위험이 있다. '이 모델이 미래
    드리프트를 실제로 탐지할 수 있는가'를 검증할 때는 stratified_split_by_defect
    대신(혹은 함께) 이 함수를 쓴다. defect 비율은 보장하지 않는다(시간순이 우선).
    """
    ordered = df.sort_values(time_col)
    cutoff = int(len(ordered) * (1 - test_fraction))
    train_df = ordered.iloc[:cutoff]
    test_df = ordered.iloc[cutoff:]
    return train_df, test_df
