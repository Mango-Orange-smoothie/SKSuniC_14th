"""
evaluate_early_detection.py

Goal4 마무리용 평가 스크립트.
"spec-out만 잡던 기존 방식" 대비 Trend Analysis(trend_analysis.py)가 얼마나 더/먼저
잡아내는지를 두 기준으로 비교한다.

기준 1: 실제 NG_Code 발생(불량이 이미 난 시점)만 아는 방식
        -> 내 early_warning이 그 불량보다 앞서(같은 그룹의 최근 LOOKBACK_N개 관측치 내에서)
           떠 있었는지로 "사전 탐지율"을 계산한다.
기준 2: C유형 위험 Threshold를 이미 "넘은" 시점만 아는 방식(entered_first만, approaching 제외)
        -> approaching + A/B/E형 + 변동성확대 경고가 이 방식으로는 못 잡는 "추가 포착분"이다.

추가로 경보량이 지나치게 많은지 sanity check도 함께 수행한다.

이 스크립트는 trend_analysis.py나 기존 결과 CSV를 수정하지 않는다.
analysis_outputs/goal4_*.csv 만 새로 생성한다.
"""

import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RAW_INPUT_FILES = [
    ("HealthIndex_Dataset.csv", os.path.join(BASE_DIR, "HealthIndex_Dataset.csv")),
    ("DP_HealthIndex_Dataset_r1.csv", os.path.join(BASE_DIR, "DP_HealthIndex_Dataset_r1.csv")),
]
RESULTS_CSV = os.path.join(BASE_DIR, "analysis_outputs", "trend_analysis_results.csv")

OUT_DIR = os.path.join(BASE_DIR, "analysis_outputs")
COMPARISON_NG_CSV = os.path.join(OUT_DIR, "goal4_comparison_vs_ng.csv")
COMPARISON_DEFECT_SPECIFIC_CSV = os.path.join(OUT_DIR, "goal4_comparison_defect_specific.csv")
COMPARISON_THRESHOLD_CSV = os.path.join(OUT_DIR, "goal4_comparison_vs_threshold_only.csv")
SANITY_CHECK_CSV = os.path.join(OUT_DIR, "goal4_sanity_check.csv")

GROUP_KEYS = ["Machine_ID", "Product_ID", "Recipe_ID"]
LOOKBACK_N = 20  # 실제 불량 발생 시점 기준, 그 직전 몇 개 관측치 안에서 경보를 찾을지
WINDOW = 10  # trend_analysis.py와 동일 (전체 유효 분석 행수 추정에 사용)
N_ANALYSIS_COLUMNS = 35  # trend_analysis.py에서 분석하는 연속형 컬럼 수 (로그로 재확인됨)

# C유형 컬럼 -> 원본 NG_Code 값 매핑.
# Baseline_C 파일의 matched_defect 문자열 자체가(원본 파일 단계에서부터) 인코딩이 깨져 있어
# 문자열로 매칭하면 항상 실패한다. 대신 원인이 되는 컬럼명(ASCII, 안전)으로 매칭한다.
COLUMN_TO_NG_CODE = {
    "CLN_Pressure": "REM_COAT",
    "Surface_Roughness": "PARTICLE",
}


def load_results():
    df = pd.read_csv(RESULTS_CSV)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    return df


def compare_vs_ng(results):
    """기준 1: 실제 NG_Code 발생 대비 사전 탐지율."""
    rows = []
    for source_name, path in RAW_INPUT_FILES:
        raw = pd.read_csv(path)
        raw["DateTime"] = pd.to_datetime(raw["DateTime"])
        raw = raw.sort_values(GROUP_KEYS + ["DateTime"]).reset_index(drop=True)

        warn_points = (
            results[results["source_file"] == source_name][GROUP_KEYS + ["DateTime"]]
            .drop_duplicates()
        )
        warn_points["had_warning"] = True

        merged = raw.merge(warn_points, on=GROUP_KEYS + ["DateTime"], how="left")
        merged["had_warning"] = merged["had_warning"].fillna(False)

        # 직전 LOOKBACK_N개 관측치(자기 자신 제외) 안에 경보가 있었는지
        merged["recent_warning"] = (
            merged.groupby(GROUP_KEYS)["had_warning"]
            .transform(lambda s: s.shift(1).rolling(LOOKBACK_N, min_periods=1).max())
            .fillna(0)
            .astype(bool)
        )

        ng_rows = merged[merged["NG_Code"] != "OK"]
        n_ng = len(ng_rows)
        n_ng_preceded = int(ng_rows["recent_warning"].sum())

        # 대조군: OK 행(정상 생산분)에서도 같은 비율로 "직전 경보 있음"이 나오는지.
        # 경보 밀도가 높으면 NG 여부와 무관하게 recent_warning이 항상 True에 가까워질 수 있어,
        # 이 대조군 없이는 사전탐지율만으로 예측력을 주장할 수 없다.
        ok_rows = merged[merged["NG_Code"] == "OK"]
        n_ok = len(ok_rows)
        n_ok_preceded = int(ok_rows["recent_warning"].sum())

        # 순수 우연 기준선: 관측치당 경보 확률(p)만으로 LOOKBACK_N개 중 하나라도 걸릴 확률
        p_warning = merged["had_warning"].mean()
        chance_rate = (1 - (1 - p_warning) ** LOOKBACK_N) * 100

        n_warning_points = int(merged["had_warning"].sum())

        # 경보가 뜬 시점(포함) ~ 이후 LOOKBACK_N개 안에 실제 NG가 있었는지(검증된 조기경보 비율)
        def forward_any_ng(s):
            ng = (s.to_numpy() != "OK").astype(float)
            reversed_roll = pd.Series(ng[::-1]).rolling(LOOKBACK_N, min_periods=1).max().to_numpy()
            return reversed_roll[::-1]

        merged["future_ng"] = (
            merged.groupby(GROUP_KEYS)["NG_Code"].transform(forward_any_ng).astype(bool)
        )
        warned = merged[merged["had_warning"]]
        n_warning_confirmed = int(warned["future_ng"].sum())

        ng_rate = round(n_ng_preceded / n_ng * 100, 2) if n_ng else np.nan
        ok_rate = round(n_ok_preceded / n_ok * 100, 2) if n_ok else np.nan
        rows.append({
            "source_file": source_name,
            "실제_NG_발생건수(기존방식이_잡는_전부)": n_ng,
            "그중_사전에_경보있었던_건수": n_ng_preceded,
            "NG행_사전탐지율(%)": ng_rate,
            "OK행_대조군_비율(%)": ok_rate,
            "순수우연_기준선(%)": round(chance_rate, 2),
            "NG-OK_격차(실제_예측력,%p)": round(ng_rate - ok_rate, 2) if pd.notna(ng_rate) and pd.notna(ok_rate) else np.nan,
            "내_early_warning_총건수": n_warning_points,
            "그중_실제NG로_이어진_건수(검증됨)": n_warning_confirmed,
            "검증된_경보_비율(%)": round(n_warning_confirmed / n_warning_points * 100, 2) if n_warning_points else np.nan,
            "예방형_경보_건수(아직_NG로_안이어짐)": n_warning_points - n_warning_confirmed,
        })

    result = pd.DataFrame(rows)
    result.to_csv(COMPARISON_NG_CSV, index=False, encoding="utf-8-sig")
    return result


def compare_defect_specific(results):
    """C유형 원인 컬럼과 실제 해당 NG_Code가 일치하는 경우만 정밀 비교 (CLN_Pressure->REM_COAT, Surface_Roughness->PARTICLE)."""
    rows = []
    for source_name, path in RAW_INPUT_FILES:
        raw = pd.read_csv(path)
        raw["DateTime"] = pd.to_datetime(raw["DateTime"])
        raw = raw.sort_values(GROUP_KEYS + ["DateTime"]).reset_index(drop=True)

        for column, ng_code in COLUMN_TO_NG_CODE.items():
            warn_points = (
                results[
                    (results["source_file"] == source_name)
                    & (results["type"] == "C")
                    & (results["column"] == column)
                ][GROUP_KEYS + ["DateTime"]]
                .drop_duplicates()
            )
            warn_points["had_warning"] = True

            merged = raw.merge(warn_points, on=GROUP_KEYS + ["DateTime"], how="left")
            merged["had_warning"] = merged["had_warning"].fillna(False)
            merged["recent_warning"] = (
                merged.groupby(GROUP_KEYS)["had_warning"]
                .transform(lambda s: s.shift(1).rolling(LOOKBACK_N, min_periods=1).max())
                .fillna(0)
                .astype(bool)
            )

            ng_rows = merged[merged["NG_Code"] == ng_code]
            n_ng = len(ng_rows)
            n_ng_preceded = int(ng_rows["recent_warning"].sum())
            n_warning_points = int(merged["had_warning"].sum())

            ok_rows = merged[merged["NG_Code"] != ng_code]
            n_ok = len(ok_rows)
            n_ok_preceded = int(ok_rows["recent_warning"].sum())
            ng_rate = round(n_ng_preceded / n_ng * 100, 2) if n_ng else np.nan
            ok_rate = round(n_ok_preceded / n_ok * 100, 2) if n_ok else np.nan

            rows.append({
                "source_file": source_name,
                "defect": ng_code,
                "원인_컬럼": column,
                "해당_컬럼_경보_총건수": n_warning_points,
                "실제_발생건수": n_ng,
                "해당_컬럼_경보가_사전에_있었던_건수": n_ng_preceded,
                "사전탐지율(%)": ng_rate,
                "그외행_대조군_비율(%)": ok_rate,
                "격차(실제_예측력,%p)": round(ng_rate - ok_rate, 2) if pd.notna(ng_rate) and pd.notna(ok_rate) else np.nan,
            })

    result = pd.DataFrame(rows)
    result.to_csv(COMPARISON_DEFECT_SPECIFIC_CSV, index=False, encoding="utf-8-sig")
    return result


def compare_vs_threshold_only(results):
    """기준 2: C유형 threshold를 이미 넘은 시점(entered)만 잡는 기존 방식 대비, 추가로 잡아내는 경보 유형별 건수."""
    c_rows = results[results["type"] == "C"]
    entered = c_rows[c_rows["message"].str.contains("진입했습니다", na=False)]
    approaching = c_rows[c_rows["message"].str.contains("접근하는 추세", na=False)]

    a_rows = results[results["type"] == "A"]
    b_rows = results[results["type"] == "B"]
    e_rows = results[results["type"] == "E"]
    variability_only = results[results["variability_warning"] & (results["type"] == "NONE")]
    variability_any = results[results["variability_warning"]]

    rows = [
        {"구분": "기존 방식이 잡는 것: C유형 위험선 진입(entered)", "건수": len(entered), "기존_방식_포함_여부": "포함"},
        {"구분": "추가 포착: C유형 위험선 접근중(approaching, 아직 미진입)", "건수": len(approaching), "기존_방식_포함_여부": "미포함(추가)"},
        {"구분": "추가 포착: A유형 지속적 열화 추세", "건수": len(a_rows), "기존_방식_포함_여부": "미포함(추가)"},
        {"구분": "추가 포착: B유형 최적값 이탈 추세", "건수": len(b_rows), "기존_방식_포함_여부": "미포함(추가)"},
        {"구분": "추가 포착: E유형 이론값 이탈 추세", "건수": len(e_rows), "기존_방식_포함_여부": "미포함(추가)"},
        {"구분": "추가 포착: 변동성(std) 확대 경보(전체, 유형 중복 포함)", "건수": len(variability_any), "기존_방식_포함_여부": "미포함(추가)"},
    ]
    result = pd.DataFrame(rows)
    result.to_csv(COMPARISON_THRESHOLD_CSV, index=False, encoding="utf-8-sig")
    return result


def sanity_check(results):
    rows = []
    for source_name, _ in RAW_INPUT_FILES:
        sub = results[results["source_file"] == source_name]
        n_warning = len(sub)
        # 전체 분석 대상 행수(윈도우 적용 후, 필터 전) 추정: (100000 - 216그룹*9) * 35컬럼
        n_total_analyzable = (100000 - 216 * (WINDOW - 1)) * N_ANALYSIS_COLUMNS
        raw = pd.read_csv(dict(RAW_INPUT_FILES)[source_name])
        n_actual_ng = int((raw["NG_Code"] != "OK").sum())
        n_actual_ok = int((raw["NG_Code"] == "OK").sum())

        rows.append({
            "source_file": source_name,
            "early_warning_건수": n_warning,
            "전체_분석대상_행수(추정)": n_total_analyzable,
            "경보_비율(%)": round(n_warning / n_total_analyzable * 100, 2),
            "실제_NG_비율(%, 참고용)": round(n_actual_ng / (n_actual_ng + n_actual_ok) * 100, 2),
        })
    result = pd.DataFrame(rows)
    result.to_csv(SANITY_CHECK_CSV, index=False, encoding="utf-8-sig")
    return result


def main():
    print("결과 파일 로드 중...")
    results = load_results()
    print(f"로드 완료: {len(results)}행")

    print("\n===== 기준 1: 실제 NG 발생 대비 사전 탐지율 =====")
    t1 = compare_vs_ng(results)
    print(t1.to_string(index=False))
    print(f"저장: {COMPARISON_NG_CSV}")

    print("\n===== 결함별 정밀 비교 (matched_defect 기준) =====")
    t2 = compare_defect_specific(results)
    print(t2.to_string(index=False))
    print(f"저장: {COMPARISON_DEFECT_SPECIFIC_CSV}")

    print("\n===== 기준 2: 위험선 진입(entered)만 잡던 기존 방식 대비 추가 포착분 =====")
    t3 = compare_vs_threshold_only(results)
    print(t3.to_string(index=False))
    print(f"저장: {COMPARISON_THRESHOLD_CSV}")

    print("\n===== 경보량 sanity check =====")
    t4 = sanity_check(results)
    print(t4.to_string(index=False))
    print(f"저장: {SANITY_CHECK_CSV}")


if __name__ == "__main__":
    main()
