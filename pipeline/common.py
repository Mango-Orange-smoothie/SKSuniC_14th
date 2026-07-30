"""Step0/Goal 모듈이 공유하는 헬퍼 함수.

기존 analysis_step_by_step.py의 save_table 규약(utf-8-sig CSV, analysis_outputs/ 하위)을
그대로 따르되, 서브폴더 저장을 지원하도록 확장한다.
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


def robust_stats(series: pd.Series) -> dict:
    """단일 시리즈의 median/MAD 기반 강건 통계."""
    values = series.dropna()
    if len(values) == 0:
        return {"median": np.nan, "mad": np.nan, "mean": np.nan, "std": np.nan, "cv": np.nan}
    median = values.median()
    mad = (values - median).abs().median()
    mean = values.mean()
    std = values.std()
    cv = std / mean if mean not in (0,) and abs(mean) > 1e-9 else np.nan
    return {"median": median, "mad": mad, "mean": mean, "std": std, "cv": cv}


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
