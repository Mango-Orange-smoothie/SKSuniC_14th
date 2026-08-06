
import os
import sys
import numpy as np
import pandas as pd
from scipy import stats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RAW_INPUT_FILES = [
    ("DP_HealthIndex_Dataset.csv", os.path.join(BASE_DIR, "data", "raw", "DP_HealthIndex_Dataset.csv")),
]
# r1(DP_HealthIndex_Dataset_r1.csv, 멘토 배포 파일)은 git에 없고 아직 로컬에도 없어서
# 잠정 제외했다. 파일 받으면 여기에 다시 추가할 것 —
# ("DP_HealthIndex_Dataset_r1.csv", os.path.join(BASE_DIR, "DP_HealthIndex_Dataset_r1.csv")),

CLASSIFICATION_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_column_classification.csv")
STRATUM_STD_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_stratum_baseline_stats_by_opcond.csv")
MACHINE_TREND_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_machine_column_trend.csv")
BASELINE_AB_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_AB.csv")
BASELINE_C_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_C.csv")
BASELINE_E_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_E.csv")

OUTPUT_DIR = os.path.join(BASE_DIR, "analysis_outputs")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "trend_analysis_results.csv")
CROSS_VALIDATION_CSV = os.path.join(OUTPUT_DIR, "trend_cross_validation.csv")

GROUP_KEYS = ["Machine_ID", "Product_ID", "Recipe_ID"]
WINDOW = 10
Z_THRESHOLD = 2.0
VOLATILITY_RATIO_THRESHOLD = 1.5  # 정상(참조) std 대비 이 배수 이상이면 변동성 확대 후보
KENDALL_P_THRESHOLD = 0.05  # 교차검증용 전역 추세 판정(Kendall tau) 유의수준
PERSIST_WINDOW = 5  # (26.08.05) 몇 행 연속으로 조건을 만족해야 "진짜 상태"로 볼지 —
# 노이즈로 임계값 근처를 오락가락하는 걸 "새로 진입"으로 계속 잡던 문제(Surface_Roughness
# 22,948건 중 21,426건이 진입 이벤트였음) 방지용. 1행짜리 순간 판정 대신 지속성 요구.

# (26.08.05 추가) Type C "접근" 판정을 위한 danger_rate 배수. rolling_mean 기반 risk_margin_z는
# 위험선까지 얼마나 남았는지를 "평균"으로 재는데, 평균은 개별 샷의 위험 진입을 지워버린다
# (CLN_Pressure 실측: 개별 샷 6.68%가 threshold 아래인데 rolling mean은 0.00%만 아래로
# 내려감 — 66,824배 차이). 반대로 rolling MIN(윈도우 내 최악값)을 쓰면 10개 중 1개만
# 넘어도 걸려서 오히려 개별 샷 확률의 절반(49.47%)까지 뛰어 과민해진다. 그래서 build_
# health_index.py의 defect_zone_rate(위험구간에 들어간 샷 비율)와 같은 방식 — "윈도우 안
# 위험구간 진입 비율"이 평소(baseline_rate) 대비 이 배수 이상이면 "접근 중"으로 본다.
C_DANGER_RATE_MULTIPLE = 2.0

# (26.08.05 추가) A/B/E유형의 "지속적 편차" 판정을 CUSUM(누적합)으로 교체.
# 기존 방식(WINDOW=10 rolling mean + PERSIST_WINDOW=5 연속조건)은 구조적으로 최소
# WINDOW+PERSIST_WINDOW-1행(그룹당 하루 ~5샷이면 최소 3일)의 지연이 있고, 실측으로는
# CLN_Flow가 실제 하강 시작(2/16) 대비 첫 경고까지 6~7일 걸렸다(rolling mean이 전환
# 자체를 완전히 반영하기까지 추가 지연). CUSUM은 매 샷마다 target 대비 편차를 누적해서
# 작은 편차(CUSUM_K 미만)는 계속 무시하고 버리되, 그보다 큰 편차가 쌓이면 빠르게
# 경보 임계값(CUSUM_H)을 넘는다 — SPC(통계적 공정관리)에서 지속적 이동 감지에 쓰는
# 표준 방법. k=0.5, h=4는 교과서 관례값(약 1시그마 크기의 이동을 합리적인 오탐률로 잡음).
CUSUM_K = 0.7   # 허용 편차(시그마 단위) — 이보다 작은 편차는 누적 안 함(정상 노이즈)
CUSUM_H = 4.5   # 경보 임계값(시그마 단위) — 누적합이 이걸 넘으면 "지속적 이동" 확정
# (26.08.05) 파라미터를 실측으로 두 번 튜닝했다.
#   1차(K=0.5, H=4.0, OPCOND 공통 target): Laser_Power에서 DP02가 다른 장비보다 0.44시그마
#     낮게 89일 내내 고정 운영되는 걸 "지속 이동"으로 잘못 잡아 그 컬럼 알람율이 15.6%까지
#     치솟았다(정상적으론 거의 0%여야 함) — Coating_Uniformity는 거의 전체 행(96,484건)이
#     경보 상태가 됨.
#   2차 시도(그룹별 초반 30샷 평균을 기준점으로): 장비 간 차이 문제는 피했지만, 30개
#     표본만으로 추정한 기준점 자체가 우연히 실제 평균과 어긋나는 그룹이 나왔다(한
#     사례: 초반 30개 평균이 전체 평균보다 0.58시그마 낮게 나와서 그 뒤 447개 샷 내내
#     "위로 지속 이동"으로 오인, 알람율 93%). 표본이 작을수록 이 위험이 커진다.
#   최종: OPCOND 공통 target으로 되돌리고, K를 0.5->0.7, H를 4.0->4.5로 올려 "장비 간
#     자연스러운 0.4~0.6시그마 차이"에는 반응하지 않게 둔감화했다. 실측 검증(아래):
#       Laser_Power/Bottom_Kerf(추세 없는 안정 컬럼) 알람율 0.5%/1.0%대로 하락(20배+ 개선)
#       CLN_Flow(DP04, 실제 2/16~18 하강) 첫 경고 중앙값 2/22 18:06 — 기존 rolling+
#       persistence 방식(2/22~23)과 비슷한 속도를 유지하면서 오탐만 크게 줄였다.
#     SPC 이론상 "민감도(빠른 탐지)"와 "오탐률"은 같은 k/h로 동시에 최적화가 안 되는
#     근본적 트레이드오프라(작은 목표 이동폭 2k와 자연 변동폭이 겹치면 어느 한쪽을
#     포기해야 함), 이 데이터에서는 오탐 억제를 우선했다 — 지연을 더 줄이려면 목표
#     이동폭을 이 정도로 잡는 대신 오탐 증가를 감수해야 한다.


def compute_cusum(z_values):
    """target 기준 정규화된 z-score 시계열(샷 단위, 전체 길이)에 양방향 CUSUM 적용.

    s_pos: 위쪽으로 지속 이동 중이면 커짐(0 아래로는 안 내려감 — 정상/반대방향이면 리셋).
    s_neg: 아래쪽으로 지속 이동 중이면 작아짐(음수, 0 위로는 안 올라감).
    """
    n = len(z_values)
    s_pos = np.zeros(n)
    s_neg = np.zeros(n)
    prev_pos, prev_neg = 0.0, 0.0
    for i in range(n):
        prev_pos = max(0.0, prev_pos + z_values[i] - CUSUM_K)
        prev_neg = min(0.0, prev_neg + z_values[i] + CUSUM_K)
        s_pos[i] = prev_pos
        s_neg[i] = prev_neg
    return s_pos, s_neg

OUTPUT_COLUMNS = [
    "source_file", "DateTime", "Machine_ID", "Product_ID", "Recipe_ID",
    "column", "type", "matched_defect", "baseline", "threshold", "current_value", "rolling_mean", "rolling_std",
    "std_slope", "difference", "slope", "normalized_deviation", "trend_direction",
    "variability_warning", "early_warning", "message",
]
# (26.08.05) Type C 컬럼은 "baseline"과 "threshold"가 서로 다른 개념인데 예전엔 threshold를
# baseline 자리에 그대로 넣어써서, normalized_deviation(추세/경고용 "정상에서 얼마나
# 벗어났는지")이 "위험선에서 얼마나 벗어났는지"로 계산되는 문제가 있었다(안전한 쪽으로
# 멀리 떨어져 있을 뿐인데도 큰 편차로 잡혀 CLN_Pressure 경고의 75%가 사실상 오탐이었음).
# 이제 baseline = 모든 유형 공통으로 "정상 기준값(target)"(Type C는 00_stratum_baseline_
# stats_by_opcond.csv의 Product×Recipe별 OK median, 나머지는 기존과 동일), threshold =
# Type C 전용 위험 경계값으로 분리한다. normalized_deviation/trend_direction은 baseline
# 기준으로(A/B/E와 동일 의미), entered/approaching 판정만 threshold 기준으로 따로 계산.


# ----------------------------------------------------------------------
# 1. 필수 입력 파일 존재 확인 (예외 처리)
# ----------------------------------------------------------------------
def check_required_files():
    required = [p for _, p in RAW_INPUT_FILES] + [
        CLASSIFICATION_CSV, STRATUM_STD_CSV, MACHINE_TREND_CSV, BASELINE_AB_CSV, BASELINE_C_CSV, BASELINE_E_CSV,
    ]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError("다음 필수 입력 파일을 찾을 수 없습니다:\n" + "\n".join(missing))


# ----------------------------------------------------------------------
# 2. 분석 대상 연속형 컬럼 결정 (00_column_classification.csv 기준)
#    - 식별자 / 범주형 / 결함결과 / 제외대상은 자연히 빠짐
#    - data_type == 'continuous' AND analysis_role == 'predictor' 인 것만 채택
# ----------------------------------------------------------------------
def load_analysis_columns():
    cls = pd.read_csv(CLASSIFICATION_CSV)
    mask = (cls["data_type"] == "continuous") & (cls["analysis_role"] == "predictor")
    cols = cls.loc[mask, "column"].tolist()
    return cols


# ----------------------------------------------------------------------
# 3. Baseline 파일 로드 (A/B/C/E)
# ----------------------------------------------------------------------
def load_baseline_maps():
    ab = pd.read_csv(BASELINE_AB_CSV)
    c = pd.read_csv(BASELINE_C_CSV)
    e = pd.read_csv(BASELINE_E_CSV)

    print(f"[Baseline] AB 파일 실제 컬럼: {list(ab.columns)}")
    print(f"[Baseline] C  파일 실제 컬럼: {list(c.columns)}")
    print(f"[Baseline] E  파일 실제 컬럼: {list(e.columns)}")

    column_type = {}      # column -> 'A' / 'B' / 'C' / 'E'
    direction_map = {}    # A유형: column -> 'up' / 'down'
    ab_value_map = {}     # (column, group_key) -> baseline_value  (A/B 공용, group_key='Product|Recipe')
    c_map = {}             # (column, group_key) -> {threshold, risky_direction, matched_defect}
    e_value_map = {}       # column -> baseline_value (이론상수)
    e_std_map = {}         # column -> reference_OK_std (E유형 fallback std)

    for row in ab.itertuples(index=False):
        col = row.column
        column_type[col] = row.type  # 'A' or 'B'
        ab_value_map[(col, row.group_key)] = row.baseline_value
        if row.type == "A":
            direction_map[col] = row.bad_direction

    for row in c.itertuples(index=False):
        col = row.column
        column_type[col] = "C"
        c_map[(col, row.group_key)] = {
            "threshold": row.threshold,
            "risky_direction": row.risky_direction,
            "matched_defect": row.matched_defect,
        }

    for row in e.itertuples(index=False):
        col = row.column
        column_type[col] = "E"
        e_value_map[col] = row.baseline_value
        e_std_map[col] = row.reference_OK_std

    return column_type, direction_map, ab_value_map, c_map, e_value_map, e_std_map


# ----------------------------------------------------------------------
# 4. std fallback + Type C target 참조 테이블
#    analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv 재사용
#    (Product_ID x Recipe_ID x column 단위, OK 데이터 기준 std/median)
#    (26.08.05) median을 Type C 컬럼의 target으로도 쓴다 — Type C는 원래 "위험 threshold"만
#    있고 "정상일 때 이 값이어야 한다"는 target이 없었는데(threshold를 target 자리에 대신
#    써서 문제가 생겼음), 이 파일에 이미 Product×Recipe별 OK median이 있어서(Health Index
#    쪽 provisional_percentile 계산이 이미 같은 파일로 target을 쓰고 있음) 그대로 재사용한다.
# ----------------------------------------------------------------------
def load_stratum_reference_maps():
    strat = pd.read_csv(STRATUM_STD_CSV, usecols=["Product_ID", "Recipe_ID", "column", "std", "median"])
    fb_std, target_map = {}, {}
    for row in strat.itertuples(index=False):
        key = (row.Product_ID, row.Recipe_ID, row.column)
        fb_std[key] = row.std
        target_map[key] = row.median
    return fb_std, target_map


# ----------------------------------------------------------------------
# 5. Rolling 통계 계산 (그룹 내 한 컬럼, 시간순 정렬된 1D array)
# ----------------------------------------------------------------------
def compute_group_rolling(values):
    n = len(values)
    if n < WINDOW:
        return None
    windows = np.lib.stride_tricks.sliding_window_view(values, WINDOW)
    rolling_mean = windows.mean(axis=1)
    rolling_std = windows.std(axis=1, ddof=1)
    difference = windows[:, -1] - windows[:, 0]

    x = np.arange(WINDOW, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    slope = ((windows - rolling_mean.reshape(-1, 1)) * (x - x_mean)).sum(axis=1) / denom

    return rolling_mean, rolling_std, difference, slope


# ----------------------------------------------------------------------
# 5-1. 변동성(std) 확대 추세 계산
#      rolling_std 시계열 자체에 다시 같은 크기(WINDOW)의 창을 대고 기울기를 구한다.
#      앞쪽 (WINDOW-1)개는 변동성 추세를 판단할 이력이 부족해 NaN으로 둔다.
# ----------------------------------------------------------------------
def compute_std_trend(rolling_std):
    n = len(rolling_std)
    std_slope = np.full(n, np.nan)
    if n < WINDOW:
        return std_slope

    windows = np.lib.stride_tricks.sliding_window_view(rolling_std, WINDOW)
    w_mean = windows.mean(axis=1)
    x = np.arange(WINDOW, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    slope = ((windows - w_mean.reshape(-1, 1)) * (x - x_mean)).sum(axis=1) / denom

    std_slope[WINDOW - 1:] = slope
    return std_slope


# ----------------------------------------------------------------------
# 5-2. 지속성 필터 — "1행짜리 순간 판정" 대신 "N행 연속 유지"를 요구
#      (26.08.05 추가) Type C(위험 threshold)의 entered_first가 임계값 근처 노이즈로
#      계속 새로 트리거되던 문제, variability_warning이 10행 표본의 std 추정 자체가
#      원래 흔들림이 커서(표본 10개로 분산 추정은 노이즈가 큼) 너무 자주 뜨던 문제를
#      같은 방식으로 고친다.
# ----------------------------------------------------------------------
def _sustained_state(condition: np.ndarray, persist_n: int) -> np.ndarray:
    """condition이 최근 persist_n행 연속 True인 시점부터를 True로 표시(그 구간 전체, 상태형)."""
    n = len(condition)
    if n < persist_n:
        return np.zeros(n, dtype=bool)
    windows = np.lib.stride_tricks.sliding_window_view(condition, persist_n)
    sustained = windows.all(axis=1)
    full = np.zeros(n, dtype=bool)
    full[persist_n - 1:] = sustained
    return full


def _sustained_first(condition: np.ndarray, persist_n: int) -> np.ndarray:
    """_sustained_state 중에서도 그 상태가 "막 시작된" 시점 1행만 True(이벤트형)."""
    full = _sustained_state(condition, persist_n)
    prev_full = np.concatenate(([False], full[:-1]))
    return full & ~prev_full


# ----------------------------------------------------------------------
# 5-3. Type C "접근" 판정용 정상 danger_rate — 컬럼별로 "평소엔 위험구간에 샷이 얼마나
#      들어가는지"를 미리 재둔다(그룹별 비율의 median, 특정 그룹이 튀어도 안 흔들리게).
#      build_health_index.py의 defect_zone_rate 기준(zone_base_rate)과 같은 방식.
# ----------------------------------------------------------------------
def compute_c_type_baseline_rate(df, column_type, c_map):
    baseline_rate = {}
    c_columns = [col for col, t in column_type.items() if t == "C" and col in df.columns]
    for col in c_columns:
        group_rates = []
        for (product_id, recipe_id), g in df.groupby(["Product_ID", "Recipe_ID"]):
            info = c_map.get((col, f"{product_id}|{recipe_id}"))
            if info is None:
                continue
            values = g[col].to_numpy(dtype=float)
            if info["risky_direction"] == "low_is_risky":
                risky = values < info["threshold"]
            else:
                risky = values > info["threshold"]
            group_rates.append(risky.mean())
        if group_rates:
            baseline_rate[col] = float(np.median(group_rates))
    return baseline_rate


# ----------------------------------------------------------------------
# 6. 파일 단위 처리
# ----------------------------------------------------------------------
def process_file(source_name, path, analysis_columns, column_type, direction_map,
                  ab_value_map, c_map, e_value_map, e_std_map, fallback_std_map,
                  stratum_target_map, state):
    df = pd.read_csv(path)
    n_input_rows = len(df)

    # 공통 분석 가능 컬럼만 사용 (두 파일 컬럼이 다를 경우 대비)
    usable_columns = [c for c in analysis_columns if c in df.columns]
    if len(usable_columns) != len(analysis_columns):
        skipped = set(analysis_columns) - set(usable_columns)
        print(f"[{source_name}] 경고: 원본에 없는 분석 대상 컬럼 {skipped} 은(는) 제외합니다.")

    df["source_file"] = source_name
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df = df.sort_values(GROUP_KEYS + ["DateTime"]).reset_index(drop=True)

    c_baseline_rate = compute_c_type_baseline_rate(df, column_type, c_map)

    total_out_rows = 0
    warning_count = 0
    warning_samples = []

    for group_vals, gdf in df.groupby(GROUP_KEYS, sort=False):
        machine_id, product_id, recipe_id = group_vals
        group_key = f"{product_id}|{recipe_id}"
        gdf = gdf.sort_values("DateTime")
        if len(gdf) < WINDOW:
            continue
        datetimes = gdf["DateTime"].to_numpy()[WINDOW - 1:]

        out_frames = []
        for col in usable_columns:
            values = gdf[col].to_numpy(dtype=float)
            result = compute_group_rolling(values)
            if result is None:
                continue
            rolling_mean, rolling_std, difference, slope = result
            current_value = values[WINDOW - 1:]

            col_type = column_type.get(col)
            baseline = np.nan
            threshold = np.nan
            extra = {}
            if col_type in ("A", "B"):
                baseline = ab_value_map.get((col, group_key), np.nan)
            elif col_type == "C":
                info = c_map.get((col, group_key))
                if info is not None:
                    threshold = info["threshold"]
                    extra = info
                # target(정상 기준값)은 threshold와 별개 — Product×Recipe별 OK median.
                baseline = stratum_target_map.get((product_id, recipe_id, col), np.nan)
            elif col_type == "E":
                baseline = e_value_map.get(col, np.nan)

            baseline_arr = np.full(len(current_value), baseline, dtype=float)
            threshold_arr = np.full(len(current_value), threshold, dtype=float)

            # --- std 안전 대체 로직 ---
            eff_std = rolling_std.copy()
            need_fallback = np.isnan(eff_std) | (eff_std == 0)
            if need_fallback.any():
                fb_val = np.nan
                if col_type == "E":
                    fb_val = e_std_map.get(col, np.nan)
                if fb_val is None or (isinstance(fb_val, float) and np.isnan(fb_val)) or fb_val == 0:
                    fb_val = fallback_std_map.get((product_id, recipe_id, col), np.nan)
                eff_std = np.where(need_fallback, fb_val, eff_std)

            valid_baseline = ~np.isnan(baseline_arr)
            valid_std = (~np.isnan(eff_std)) & (eff_std != 0)
            calc_mask = valid_baseline & valid_std

            # 추세분석 목적: 순간값이 아니라 최근 10개 평균(rolling_mean)이 baseline에서
            # 얼마나 벗어났는지를 기준으로 정규화 편차를 계산한다.
            normalized_deviation = np.full(len(current_value), np.nan)
            normalized_deviation[calc_mask] = (
                (rolling_mean[calc_mask] - baseline_arr[calc_mask]) / eff_std[calc_mask]
            )
            # std를 전혀 구할 수 없는 경우: 상대/절대 편차로 대체 표기(참고용, 조기경보 판정에는 미사용)
            rel_mask = valid_baseline & (~valid_std)
            nz_base = rel_mask & (baseline_arr != 0)
            z_base = rel_mask & (baseline_arr == 0)
            normalized_deviation[nz_base] = (
                (rolling_mean[nz_base] - baseline_arr[nz_base]) / np.abs(baseline_arr[nz_base])
            )
            normalized_deviation[z_base] = rolling_mean[z_base] - baseline_arr[z_base]

            # 조기경보(A/B/E의 persistent 판정)용 로컬 추세 방향. 10개 단위 로컬 slope는
            # 장기 drift 신호와 스케일이 달라(뒤 compute_reference_style_trend 참고)
            # 여기서는 단순 부호 기준을 그대로 쓴다.
            trend_direction = np.where(slope > 0, "up", np.where(slope < 0, "down", "flat"))

            # --- 변동성(std) 확대 추세: 정상 대비 std가 충분히 크고(비율) 계속 커지는 중인지 ---
            std_slope = compute_std_trend(rolling_std)
            ref_std = fallback_std_map.get((product_id, recipe_id, col), np.nan)
            if ref_std is not None and not (isinstance(ref_std, float) and np.isnan(ref_std)) and ref_std > 0:
                std_ratio = rolling_std / ref_std
            else:
                std_ratio = np.full(len(current_value), np.nan)
            variability_raw = (
                ~np.isnan(std_slope) & (std_slope > 0)
                & ~np.isnan(std_ratio) & (std_ratio >= VOLATILITY_RATIO_THRESHOLD)
            )
            # 10행 표본으로 구한 std는 그 자체로 추정 노이즈가 커서, 1행짜리 순간 판정 대신
            # PERSIST_WINDOW행 연속 유지될 때만 "진짜 변동성 확대"로 본다(상태형 — 지속되는
            # 동안 계속 표시).
            variability_warning = _sustained_state(variability_raw, PERSIST_WINDOW)

            early_warning = np.zeros(len(current_value), dtype=bool)
            messages = np.array([""] * len(current_value), dtype=object)

            # --- CUSUM(누적합) — A/B/E유형의 "지속적 편차" 판정에 공통으로 쓴다 ---
            # rolling_mean 기반 WINDOW+PERSIST_WINDOW 방식보다 반응이 빠르다. target(OPCOND
            # 공통 baseline)과 안정적인 참조 std(rolling 아닌 스칼라)로 샷 단위 z-score를
            # 만들고 전체 이력에 누적합을 씌운다 — K/H 튜닝 배경은 위 CUSUM_K/H 주석 참고.
            ref_std_scalar = np.nan
            if col_type == "E":
                ref_std_scalar = e_std_map.get(col, np.nan)
            if ref_std_scalar is None or (isinstance(ref_std_scalar, float) and np.isnan(ref_std_scalar)) or ref_std_scalar == 0:
                ref_std_scalar = fallback_std_map.get((product_id, recipe_id, col), np.nan)
            cusum_pos = cusum_neg = None
            if col_type in ("A", "B", "E") and not np.isnan(baseline) and ref_std_scalar and ref_std_scalar > 0:
                z_full = (values - baseline) / ref_std_scalar
                s_pos_full, s_neg_full = compute_cusum(z_full)
                cusum_pos, cusum_neg = s_pos_full[WINDOW - 1:], s_neg_full[WINDOW - 1:]

            if col_type == "A":
                bad_dir = direction_map.get(col)
                if cusum_pos is not None:
                    ew = (cusum_pos > CUSUM_H) if bad_dir == "up" else (cusum_neg < -CUSUM_H)
                else:
                    ew = np.zeros(len(current_value), dtype=bool)
                early_warning |= ew
                dir_word = "상승" if bad_dir == "up" else "하강"
                for i in np.where(ew)[0]:
                    messages[i] = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                        f"정상 Baseline 대비 지속적인 {dir_word} 추세가 감지되었습니다."
                    )

            elif col_type == "B":
                if cusum_pos is not None:
                    ew = (cusum_pos > CUSUM_H) | (cusum_neg < -CUSUM_H)
                else:
                    ew = np.zeros(len(current_value), dtype=bool)
                early_warning |= ew
                for i in np.where(ew)[0]:
                    side = "높은" if cusum_pos[i] > CUSUM_H else "낮은"
                    messages[i] = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                        f"정상 Baseline(최적값) 대비 {side} 방향으로 지속적으로 벌어지는 편차가 감지되었습니다."
                    )

            elif col_type == "C":
                risky_direction = extra.get("risky_direction") if extra else None
                valid_threshold = ~np.isnan(threshold_arr)
                if risky_direction is not None and valid_threshold.any():
                    if risky_direction == "low_is_risky":
                        entered_raw = (current_value <= threshold_arr) & valid_threshold
                        slope_toward_risk = slope < 0
                        risky_side_raw = values < threshold
                    else:
                        entered_raw = (current_value >= threshold_arr) & valid_threshold
                        slope_toward_risk = slope > 0
                        risky_side_raw = values > threshold
                    # 위험영역에 "PERSIST_WINDOW행 연속" 머물렀을 때만, 그 시작 시점 1행만 경고.
                    # 예전엔 1행만 넘어도 진입으로 잡아서 임계값 근처 노이즈가 계속 "새로 진입"
                    # 취급됐음(Surface_Roughness 22,948건 중 21,426건이 이 케이스였음).
                    entered_first = _sustained_first(entered_raw, PERSIST_WINDOW)
                    # (26.08.05) 예전엔 rolling_mean 기준 risk_margin_z(정상 쪽 편차도 다 잡던
                    # 버그)를 썼다가, 그다음엔 "위험선까지 남은 여유가 Z_THRESHOLD std 미만"으로
                    # 고쳤는데, CLN_Pressure로 검증해보니 rolling MEAN 자체가 개별 샷 위험 진입을
                    # 지워버리는 문제가 있었다(개별 샷 6.68%가 threshold 아래인데 rolling mean은
                    # 356일 중 0번만 아래로 내려감 — 66,824배 차이). 반대로 rolling MIN을 쓰면
                    # 10개 중 1개만 넘어도 걸려 개별샷 확률의 절반(49.47%)까지 과민해진다.
                    # build_health_index.py의 defect_zone_rate(위험구간 진입 샷 비율)와 같은
                    # 방식으로 통일 — 이 WINDOW(10행) 안에서 위험구간에 들어간 샷의 비율이
                    # 평소(baseline_rate) 대비 C_DANGER_RATE_MULTIPLE배 이상이면 "접근 중".
                    windows_risky = np.lib.stride_tricks.sliding_window_view(risky_side_raw, WINDOW)
                    danger_rate = windows_risky.mean(axis=1)
                    base_rate = c_baseline_rate.get(col)
                    if base_rate and base_rate > 0:
                        approaching_raw = (
                            (~entered_raw) & slope_toward_risk & valid_threshold
                            & (danger_rate >= C_DANGER_RATE_MULTIPLE * base_rate)
                        )
                    else:
                        approaching_raw = np.zeros(len(current_value), dtype=bool)
                    # "접근중"도 상태형 메시지("지속적으로 접근하는 추세")라 variability_warning과
                    # 같은 논리로 지속성 요구 — 순간적인 z 튐이 아니라 계속 접근할 때만.
                    approaching = _sustained_state(approaching_raw, PERSIST_WINDOW)
                    ew = entered_first | approaching
                    early_warning |= ew
                    for i in np.where(entered_first)[0]:
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                            f"위험 Threshold({threshold_arr[i]:.4f})에 진입했습니다."
                        )
                    for i in np.where(approaching)[0]:
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}은(는) "
                            f"최근 {WINDOW}개 샷 중 {danger_rate[i]*100:.0f}%가 위험 Threshold"
                            f"({threshold_arr[i]:.4f}) 구간에 들어감(평소 {base_rate*100:.1f}%) — "
                            f"위험 방향으로 지속적으로 접근하는 추세가 감지되었습니다."
                        )

            elif col_type == "E":
                if cusum_pos is not None:
                    ew = (cusum_pos > CUSUM_H) | (cusum_neg < -CUSUM_H)
                else:
                    ew = np.zeros(len(current_value), dtype=bool)
                early_warning |= ew
                for i in np.where(ew)[0]:
                    messages[i] = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                        f"이론 기준값({baseline_arr[i]:.4f}) 대비 지속적으로 벌어지는 편차가 감지되었습니다."
                    )
            # 그 외(Baseline 미매핑 컬럼): baseline/type 정보만 NONE으로 기록
            # 변동성 확대 추세는 A/B/C/E 판정과 별개로, 모든 매핑 컬럼에 공통 적용
            for i in np.where(variability_warning)[0]:
                vmsg = (
                    f"{machine_id} / {product_id} / {recipe_id}의 {col} 변동성이 "
                    f"정상 대비 지속적으로 확대되고 있습니다."
                )
                messages[i] = f"{messages[i]} {vmsg}".strip() if messages[i] else vmsg
            early_warning = early_warning | variability_warning

            matched_defect_val = extra.get("matched_defect", "") if extra else ""
            matched_defect_arr = np.full(len(current_value), matched_defect_val, dtype=object)

            frame = pd.DataFrame({
                "source_file": source_name,
                "DateTime": datetimes,
                "Machine_ID": machine_id,
                "Product_ID": product_id,
                "Recipe_ID": recipe_id,
                "column": col,
                "type": col_type if col_type else "NONE",
                "matched_defect": matched_defect_arr,
                "baseline": baseline_arr,
                "threshold": threshold_arr,
                "current_value": current_value,
                "rolling_mean": rolling_mean,
                "rolling_std": rolling_std,
                "std_slope": std_slope,
                "difference": difference,
                "slope": slope,
                "normalized_deviation": normalized_deviation,
                "trend_direction": trend_direction,
                "variability_warning": variability_warning,
                "early_warning": early_warning,
                "message": messages,
            })
            out_frames.append(frame)

        if not out_frames:
            continue
        group_result = pd.concat(out_frames, ignore_index=True)[OUTPUT_COLUMNS]
        # 계산(Rolling/판정)은 전체 행에 대해 수행하되, 파일에는 early_warning=True인 행만 저장한다.
        ew_rows = group_result[group_result["early_warning"]]
        if len(ew_rows) > 0:
            ew_rows.to_csv(OUTPUT_CSV, mode="a", header=state["first_write"], index=False, encoding="utf-8-sig")
            state["first_write"] = False

        total_out_rows += len(ew_rows)
        warning_count += len(ew_rows)
        if len(warning_samples) < 10 and len(ew_rows) > 0:
            needed = 10 - len(warning_samples)
            warning_samples.extend(ew_rows.head(needed).to_dict("records"))

    return n_input_rows, total_out_rows, warning_count, warning_samples


# ----------------------------------------------------------------------
# 7. 기존 00_machine_column_trend.csv(일별 집계 + Kendall tau 기반)와의 교차검증
#
#    처음에는 본 스크립트가 이미 계산해 둔 10개 단위 로컬 rolling slope의
#    방향(up/down)을 그룹 전체에서 다수결로 집계해 비교했으나, 실제로 확인해보니
#    강한 장기 drift 컬럼(DP02 Vibration)과 no_trend 컬럼(DP01 Laser_Current)의
#    로컬 slope 비율 분포가 통계적으로 거의 동일했다(median 0.73 vs 0.71).
#    즉 10개 단위 로컬 rolling window는 90일치 장기 drift 신호를 애초에
#    분리해내지 못하는 스케일이라, 임계값을 조정해도 해결되지 않는 구조적
#    한계였다. 그래서 교차검증만큼은 조기경보 로직과 별개로, 참조 파일과
#    동일한 방법론(Machine_ID별 일별 평균 집계 -> Kendall tau)으로 다시 계산한다.
# ----------------------------------------------------------------------
def compute_reference_style_trend(path, columns):
    df = pd.read_csv(path, usecols=["DateTime", "Machine_ID"] + columns)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["date"] = df["DateTime"].dt.date

    result = {}
    for machine_id, g in df.groupby("Machine_ID"):
        daily = g.groupby("date")[columns].mean().sort_index().reset_index(drop=True)
        day_idx = np.arange(len(daily))
        for col in columns:
            series = daily[col]
            if series.nunique() < 2 or len(series) < 3:
                result[(machine_id, col)] = "flat"
                continue
            tau, p_value = stats.kendalltau(day_idx, series)
            if pd.isna(tau) or pd.isna(p_value) or p_value >= KENDALL_P_THRESHOLD:
                result[(machine_id, col)] = "flat"
            else:
                result[(machine_id, col)] = "up" if tau > 0 else "down"
    return result


def cross_validate_machine_trend(reference_source_path, analysis_columns):
    ref = pd.read_csv(MACHINE_TREND_CSV)

    trend_class_direction_map = {
        "candidate_upward_drift": "up",
        "candidate_downward_drift": "down",
        "no_trend": "flat",
        "mixed": "flat",
        "not_applicable": None,
    }

    my_trend = compute_reference_style_trend(reference_source_path, analysis_columns)

    rows = []
    for row in ref.itertuples(index=False):
        key = (row.Machine_ID, row.column)
        my_direction = my_trend.get(key)
        if my_direction is None:
            continue
        ref_direction = trend_class_direction_map.get(row.trend_class)
        if ref_direction is None:
            continue
        rows.append({
            "Machine_ID": row.Machine_ID,
            "column": row.column,
            "my_direction": my_direction,
            "reference_trend_class": row.trend_class,
            "reference_direction": ref_direction,
            "agree": my_direction == ref_direction,
        })

    result = pd.DataFrame(rows)
    result.to_csv(CROSS_VALIDATION_CSV, index=False, encoding="utf-8-sig")

    print(f"\n===== 00_machine_column_trend.csv 교차검증 (일별 집계 + Kendall tau 방식) =====")
    if len(result) == 0:
        print("비교 가능한 항목이 없습니다.")
    else:
        n_agree = int(result["agree"].sum())
        n_total = len(result)
        print(f"비교 대상 {n_total}건 중 일치 {n_agree}건({n_agree / n_total * 100:.1f}%), 불일치 {n_total - n_agree}건")
    print(f"저장 파일: {CROSS_VALIDATION_CSV}")
    return result


def main():
    check_required_files()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(OUTPUT_CSV):
        os.remove(OUTPUT_CSV)  # 재실행 시 이전 결과 덮어쓰기 (원본/기존 산출물 아님, 본 스크립트의 출력 파일)

    analysis_columns = load_analysis_columns()
    print(f"[분석 대상 연속형 컬럼] 총 {len(analysis_columns)}개")
    print(analysis_columns)

    column_type, direction_map, ab_value_map, c_map, e_value_map, e_std_map = load_baseline_maps()
    fallback_std_map, stratum_target_map = load_stratum_reference_maps()

    mapped = [c for c in analysis_columns if c in column_type]
    unmapped = [c for c in analysis_columns if c not in column_type]
    print(f"[Baseline 매핑] 유형 매핑된 컬럼 {len(mapped)}개 / 매핑 안 된 컬럼 {len(unmapped)}개")
    print(f"  - 매핑 안 된 컬럼(참고용 rolling 통계만 계산, early_warning 미판정): {unmapped}")

    state = {"first_write": True}
    summary = {}

    for source_name, path in RAW_INPUT_FILES:
        print(f"\n===== 처리 시작: {source_name} =====")
        try:
            n_in, n_out, n_warn, samples = process_file(
                source_name, path, analysis_columns, column_type, direction_map,
                ab_value_map, c_map, e_value_map, e_std_map, fallback_std_map,
                stratum_target_map, state,
            )
        except Exception as exc:
            print(f"[오류] {source_name} 처리 중 예외 발생: {exc}", file=sys.stderr)
            raise
        summary[source_name] = {"n_input_rows": n_in, "n_output_rows": n_out, "n_early_warning": n_warn, "samples": samples}
        print(f"[{source_name}] 입력 행 수: {n_in}")
        print(f"[{source_name}] 결과 행 수: {n_out}")
        print(f"[{source_name}] early_warning 건수: {n_warn}")

    print("\n===== 전체 요약 =====")
    total_out = sum(v["n_output_rows"] for v in summary.values())
    total_warn = sum(v["n_early_warning"] for v in summary.values())
    print(f"결과 파일: {OUTPUT_CSV}")
    print(f"결과 전체 행 수: {total_out}")
    for source_name, v in summary.items():
        print(f"  - {source_name}: 입력 {v['n_input_rows']}행 -> 결과 {v['n_output_rows']}행, early_warning {v['n_early_warning']}건")
    print(f"early_warning 총합: {total_warn}")

    if total_warn == 0:
        print("[점검] early_warning이 0건입니다. 임계값(Z_THRESHOLD) 또는 Baseline 매핑 로직을 점검해야 합니다.")

    cross_validate_machine_trend(RAW_INPUT_FILES[0][1], analysis_columns)

    for source_name, v in summary.items():
        print(f"\n===== {source_name} early_warning 샘플 (최대 10개) =====")
        if not v["samples"]:
            print("(해당 없음)")
        for s in v["samples"]:
            print(f"  [{s['DateTime']}] {s['message']}")

    return summary


if __name__ == "__main__":
    main()
