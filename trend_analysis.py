
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

OUTPUT_COLUMNS = [
    "source_file", "DateTime", "Machine_ID", "Product_ID", "Recipe_ID",
    "column", "type", "matched_defect", "baseline", "current_value", "rolling_mean", "rolling_std",
    "std_slope", "difference", "slope", "normalized_deviation", "trend_direction",
    "variability_warning", "early_warning", "message",
]


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
# 4. std fallback 참조 테이블 (표준편차 0/NaN일 때 안전 대체용)
#    기존 analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv 재사용
#    (Product_ID x Recipe_ID x column 단위의 기존 표준편차)
# ----------------------------------------------------------------------
def load_fallback_std_map():
    strat = pd.read_csv(STRATUM_STD_CSV, usecols=["Product_ID", "Recipe_ID", "column", "std"])
    fb = {}
    for row in strat.itertuples(index=False):
        fb[(row.Product_ID, row.Recipe_ID, row.column)] = row.std
    return fb


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
# 6. 파일 단위 처리
# ----------------------------------------------------------------------
def process_file(source_name, path, analysis_columns, column_type, direction_map,
                  ab_value_map, c_map, e_value_map, e_std_map, fallback_std_map,
                  state):
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
            extra = {}
            if col_type in ("A", "B"):
                baseline = ab_value_map.get((col, group_key), np.nan)
            elif col_type == "C":
                info = c_map.get((col, group_key))
                if info is not None:
                    baseline = info["threshold"]
                    extra = info
            elif col_type == "E":
                baseline = e_value_map.get(col, np.nan)

            baseline_arr = np.full(len(current_value), baseline, dtype=float)

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
            variability_warning = (
                ~np.isnan(std_slope) & (std_slope > 0)
                & ~np.isnan(std_ratio) & (std_ratio >= VOLATILITY_RATIO_THRESHOLD)
            )

            early_warning = np.zeros(len(current_value), dtype=bool)
            messages = np.array([""] * len(current_value), dtype=object)

            if col_type == "A":
                bad_dir = direction_map.get(col)
                dev_dir = np.where(current_value > baseline_arr, "up", "down")
                strong_dev = calc_mask & (np.abs(normalized_deviation) >= Z_THRESHOLD)
                ew = strong_dev & (trend_direction == bad_dir) & (dev_dir == bad_dir) & valid_baseline
                early_warning |= ew
                dir_word = "상승" if bad_dir == "up" else "하강"
                for i in np.where(ew)[0]:
                    messages[i] = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                        f"정상 Baseline 대비 지속적인 {dir_word} 추세가 감지되었습니다."
                    )

            elif col_type == "B":
                # 일시적 이상값이 아니라 baseline에서 계속 멀어지는 지속 추세일 때만 경고
                dev_dir = np.where(rolling_mean > baseline_arr, "up", "down")
                persistent = (trend_direction == dev_dir)
                ew = calc_mask & (np.abs(normalized_deviation) >= Z_THRESHOLD) & persistent
                early_warning |= ew
                for i in np.where(ew)[0]:
                    side = "높은" if rolling_mean[i] > baseline_arr[i] else "낮은"
                    messages[i] = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                        f"정상 Baseline(최적값) 대비 {side} 방향으로 지속적으로 벌어지는 편차가 감지되었습니다."
                    )

            elif col_type == "C":
                risky_direction = extra.get("risky_direction") if extra else None
                if risky_direction is not None and valid_baseline.any():
                    if risky_direction == "low_is_risky":
                        entered_raw = (current_value <= baseline_arr) & valid_baseline
                        slope_toward_risk = slope < 0
                    else:
                        entered_raw = (current_value >= baseline_arr) & valid_baseline
                        slope_toward_risk = slope > 0
                    # 위험영역에 처음 진입한 시점만 경고 (이미 진입해 있던 이후 시점은 반복 경고하지 않음)
                    prev_entered = np.concatenate(([False], entered_raw[:-1]))
                    entered_first = entered_raw & ~prev_entered
                    approaching = (
                        (~entered_raw) & slope_toward_risk & calc_mask
                        & (np.abs(normalized_deviation) >= Z_THRESHOLD)
                    )
                    ew = entered_first | approaching
                    early_warning |= ew
                    for i in np.where(entered_first)[0]:
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                            f"위험 Threshold({baseline_arr[i]:.4f})에 진입했습니다."
                        )
                    for i in np.where(approaching)[0]:
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}은(는) "
                            f"현재 위험 Threshold 이내이지만, 위험 방향으로 지속적으로 접근하는 추세가 감지되었습니다."
                        )

            elif col_type == "E":
                # 일시적 이상값이 아니라 이론값에서 계속 멀어지는 지속 추세일 때만 경고
                dev_dir = np.where(rolling_mean > baseline_arr, "up", "down")
                persistent = (trend_direction == dev_dir)
                ew = calc_mask & (np.abs(normalized_deviation) >= Z_THRESHOLD) & persistent
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
    fallback_std_map = load_fallback_std_map()

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
                ab_value_map, c_map, e_value_map, e_std_map, fallback_std_map, state,
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
