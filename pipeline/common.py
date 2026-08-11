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


def load_defect_pairing_from_db() -> tuple[dict[str, list[str]], pd.DataFrame] | None:
    """Goal2 관계DB에서 "이 인자는 이 defect로 감시한다" 짝짓기를 읽어온다.

    (26.08.08 신설) 왜 필요한가 — 이 짝짓기가 config.BASELINE_C_DEFECT_MAP에 손으로
    적혀 있었다. 지금은 DB 판정과 일치하지만 수동 사본이라 DB가 갱신되면 조용히
    어긋난다. 실제로 이번에 확인해보니 우리가 안 읽고 있던 정보가 세 가지 있었다:

      - alert_usable=False: "위험구간 불량률이 정상구간보다 낮음 — 이 경계값으로
        경보를 걸면 안 됨". 우리 코드엔 이 개념 자체가 없었다.
      - repro_state: 감시 데이터(원본)에서도 재현되는지에 대한 팀 공식 판정.
        Chipping 짝 인자들은 원본 defect 표본이 3건뿐이라 "판정불가"다 — 이걸 모르고
        C유형에 넣으면 감시 데이터에서 경보가 0건 나온다(실측 확인).
      - watch_mode: 짝마다 "수준(level)"이냐 "순간 급락(spike)"이냐. CUSUM은 지속적
        수준 이동용이라 spike와는 구조적으로 안 맞는다. (26.08.11 현재 8행 전부
        level이다 — CLN_Pressure가 유일한 spike였는데 급락 사건이 실제로 없음이
        확인돼 level로 정정됐다(554816b). 아래 채택 판정은 이 값을 보지 않는다.)

    채택 조건은 두 파일의 AND다 — rel_30(인계 파일)의 alert_usable이 True이고,
    rel_20(근거표)의 repro_state가 "통과"인 짝만 쓴다. 지금 데이터에서는 결과가
    현행 하드코딩 3개와 같다(CLN_Pressure/CLN_Flow/Surface_Roughness).

    (26.08.11) **한 인자에 defect가 여럿이면 전부 돌려준다** — 값이 defect 하나가
    아니라 리스트다. 예전엔 dict(zip(...))으로 컬럼당 하나만 담았는데, 그러면 둘
    이상 채택된 순간 조용히 하나가 사라졌다. 게다가 경고 문구는 "첫 행만 사용합니다"
    였지만 dict(zip)은 나중 값이 덮어쓰므로 실제로는 **마지막 행**이 남았다. 순서가
    tier와 무관하니 확정 T1 짝이 T2 짝에 밀릴 수 있었다(CLN_Flow: Remain_Coat T1이
    Particle T2에 밀림 — alert_usable 덕에 지금까지 안 터졌을 뿐이다).

    반환: ({column: [defect, ...]}, 판정 근거가 담긴 DataFrame). 파일이 없거나 필요한
    컬럼이 없으면 None — 호출부가 config 폴백으로 되돌아간다.
    """
    iface = config.RELATIONSHIP_DB_DIR / "rel_30_trend_interface.csv"
    tiers = config.RELATIONSHIP_DB_DIR / "rel_20_tier_table.csv"
    if not iface.exists() or not tiers.exists():
        return None
    need_iface = {"factor", "defect", "alert_usable"}
    need_tiers = {"factor", "defect", "repro_state", "watch_mode"}
    try:
        i_df = pd.read_csv(iface)
        t_df = pd.read_csv(tiers)
    except Exception:
        return None
    if not need_iface <= set(i_df.columns) or not need_tiers <= set(t_df.columns):
        return None

    merged = i_df[list(need_iface)].merge(
        t_df[list(need_tiers)], on=["factor", "defect"], how="left"
    )
    merged["adopted"] = (
        merged["alert_usable"].astype(str).str.lower().eq("true")
        & merged["repro_state"].astype(str).str.strip().eq("통과")
    )
    adopted = merged.loc[merged["adopted"]]
    if adopted.empty:
        return None
    # 한 인자에 defect가 여럿이면 전부 담는다. 경고가 아니라 정상 경로다 —
    # 하류(C유형 경계값·경보·화면)가 defect마다 따로 처리한다.
    pairing: dict[str, list[str]] = {}
    for factor, defect in zip(adopted["factor"], adopted["defect"]):
        pairing.setdefault(str(factor), []).append(str(defect))
    multi = {f: d for f, d in pairing.items() if len(d) > 1}
    if multi:
        print(f"[관계DB] 한 인자에 defect가 둘 이상 채택됨 — {multi}. 전부 감시합니다.")
    return pairing, merged


# rel_30의 threshold_direction 문구 -> 우리 코드의 방향 이름.
_DIRECTION_WORDS = {
    "아래로 내려가면 위험": "low_is_risky",
    "위로 올라가면 위험": "high_is_risky",
}


def load_domain_directions() -> dict[tuple[str, str], str]:
    """관계DB가 확정한 짝별 위험 방향 — {(인자, defect): 'low_is_risky'|'high_is_risky'}.

    (26.08.11 신설) 왜 필요한가 — C유형 경계값은 그룹(Product×Recipe)마다 결정트리
    스텀프로 따로 학습하는데, 그때 위험 방향도 같이 나온다. 그 방향이 도메인과 반대로
    나오는 그룹이 있다. 실측: CLN_Flow↔Particle은 54개 그룹 중 7개가 "높으면 위험"으로
    나온다(나머지 47개와 rel_30은 "낮으면 위험").

    "세정 유량이 **높아서** 파티클이 생긴다"는 건 물리적으로 말이 안 된다 — 그 7개
    그룹에서 잡힌 건 이 인자가 아니라 다른 원인일 것이다. 그래서 그런 그룹은 이 짝의
    근거로 쓰지 않는다(호출부: step0의 compute_baseline_type_c).

    방향의 단일 출처는 rel_30이다. 우리가 데이터에서 다시 정하지 않는다 — 그러면
    "인자↔불량 관계는 관계DB가 단일 출처"라는 규칙이 방향에서만 깨진다.
    파일이 없거나 열이 없으면 빈 dict를 돌려주고, 호출부는 필터를 걸지 않는다
    (조용히 다 버리는 것보다 예전 동작이 낫다).
    """
    path = config.RELATIONSHIP_DB_DIR / "rel_30_trend_interface.csv"
    if not path.exists():
        return {}
    try:
        t = pd.read_csv(path)
    except Exception:
        return {}
    if not {"factor", "defect", "threshold_direction"} <= set(t.columns):
        print("[관계DB] 경고: rel_30에 threshold_direction 열이 없습니다 — "
              "도메인 방향 필터를 건너뜁니다.")
        return {}
    out: dict[tuple[str, str], str] = {}
    for row in t.itertuples(index=False):
        word = _DIRECTION_WORDS.get(str(row.threshold_direction).strip())
        if word:
            out[(str(row.factor), str(row.defect))] = word
    return out


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
