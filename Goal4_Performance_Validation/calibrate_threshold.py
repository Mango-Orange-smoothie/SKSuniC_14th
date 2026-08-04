"""
calibrate_threshold.py

Goal4 후속: Trend Analysis의 early_warning이 "너무 자주 떠서" NG행과 OK행을
잘 구분하지 못한다는 문제(evaluate_early_detection.py, performance_validation.py
양쪽에서 공통으로 확인됨)를 해결하기 위한 사후 임계값 보정(방향 B).

trend_analysis.py 자체는 수정하지 않는다. 이미 계산되어 있는 trend_score
(같은 시점에 동시에 early_warning=True인 컬럼 개수, 0~35)를 이용해,
"몇 개 컬럼 이상 동시 경보일 때만 진짜 경보로 볼지" 임계값을 1~35까지
바꿔가며 두 가지 기준으로 성능을 재계산한다.

기준 1) compare_spec_vs_trend.py의 표준 confusion matrix (같은 행 기준
        Precision/Recall/F1/False Alarm Rate) - performance_validation.py와
        동일한 방법론, threshold만 다르게.
기준 2) evaluate_early_detection.py 방식의 "직전 LOOKBACK_N개 관측치 내
        경보 여부"로 NG행 사전탐지율과 OK행 대조군 비율의 격차
        (실제 예측력)를 계산. 이 격차가 threshold를 올릴수록 커지는지 확인한다.

이 스크립트는 기존 코드(trend_analysis.py, compare_spec_vs_trend.py 등)나
기존 CSV를 전혀 수정하지 않는다. results/ 아래에 새 파일만 생성한다.
GitHub에는 올리지 않는다(이번 단계는 로컬 검증용).
"""

import os
import sys

import numpy as np
import pandas as pd

GOAL4_DIR = os.path.dirname(os.path.abspath(__file__))
if GOAL4_DIR not in sys.path:
    sys.path.insert(0, GOAL4_DIR)

import compare_spec_vs_trend as cst
import evaluation_metrics as em

RESULTS_DIR = os.path.join(GOAL4_DIR, "results")
CALIBRATION_CSV = os.path.join(RESULTS_DIR, "threshold_calibration.csv")
CALIBRATION_GAP_CSV = os.path.join(RESULTS_DIR, "threshold_calibration_gap.csv")
CALIBRATION_PLOT = os.path.join(RESULTS_DIR, "threshold_calibration.png")

LOOKBACK_N = 20  # evaluate_early_detection.py와 동일한 정의(직전 몇 개 관측치를 볼지)
THRESHOLDS = list(range(1, 11))  # 컬럼 1개~10개 동시 경보까지 (그 이상은 표본이 너무 적어짐)


# ----------------------------------------------------------------------
# 기준 1: 같은 행 기준 confusion matrix를 threshold별로 재계산
# ----------------------------------------------------------------------
def sweep_confusion_matrix(table):
    elig = table[table["eligible"]]
    y_true = elig["y_true"].to_numpy()
    trend_score = elig["trend_score"].to_numpy()

    rows = []
    for th in THRESHOLDS:
        pred = trend_score >= th
        summary = em.summarize_method(y_true, pred, f"trend_score>={th}")
        summary["threshold"] = th
        summary["n_flagged_rows"] = int(pred.sum())
        rows.append(summary)

    result = pd.DataFrame(rows)
    cols = ["threshold", "n_flagged_rows", "detection_count", "TP", "FP", "FN", "TN",
            "precision", "recall", "f1_score", "false_alarm_rate"]
    result = result[cols]
    result.to_csv(CALIBRATION_CSV, index=False, encoding="utf-8-sig")
    return result


# ----------------------------------------------------------------------
# 기준 2: evaluate_early_detection.py 방식의 NG-OK 격차를 threshold별로 재계산
# ----------------------------------------------------------------------
def sweep_ng_ok_gap(table):
    rows = []
    for source_name in table["source_file"].unique():
        sub = table[(table["source_file"] == source_name) & (table["eligible"])].copy()
        sub = sub.sort_values(cst.ta.GROUP_KEYS + ["DateTime"])

        for th in THRESHOLDS:
            sub["had_warning"] = sub["trend_score"] >= th
            sub["recent_warning"] = (
                sub.groupby(cst.ta.GROUP_KEYS)["had_warning"]
                .transform(lambda s: s.shift(1).rolling(LOOKBACK_N, min_periods=1).max())
                .fillna(0)
                .astype(bool)
            )

            ng_rows = sub[sub["y_true"]]
            ok_rows = sub[~sub["y_true"]]
            n_ng, n_ok = len(ng_rows), len(ok_rows)
            ng_rate = round(ng_rows["recent_warning"].mean() * 100, 2) if n_ng else np.nan
            ok_rate = round(ok_rows["recent_warning"].mean() * 100, 2) if n_ok else np.nan
            gap = round(ng_rate - ok_rate, 2) if pd.notna(ng_rate) and pd.notna(ok_rate) else np.nan

            rows.append({
                "source_file": source_name,
                "threshold": th,
                "n_warning_rows": int(sub["had_warning"].sum()),
                "NG행_사전탐지율(%)": ng_rate,
                "OK행_대조군_비율(%)": ok_rate,
                "격차(%p)": gap,
            })

    result = pd.DataFrame(rows)
    result.to_csv(CALIBRATION_GAP_CSV, index=False, encoding="utf-8-sig")
    return result


def make_plot(cm_result, gap_result):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        print(f"[그래프 생략] matplotlib을 불러올 수 없습니다: {exc}")
        return None

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].plot(cm_result["threshold"], cm_result["precision"], marker="o", label="Precision")
    axes[0].plot(cm_result["threshold"], cm_result["recall"], marker="o", label="Recall")
    axes[0].plot(cm_result["threshold"], cm_result["f1_score"], marker="o", label="F1")
    axes[0].plot(cm_result["threshold"], cm_result["false_alarm_rate"], marker="o", label="False Alarm Rate")
    axes[0].set_xlabel("trend_score threshold (동시 경보 컬럼 수)")
    axes[0].set_ylabel("score")
    axes[0].set_title("Threshold vs Precision/Recall/F1/FAR")
    axes[0].legend()

    for source_name, g in gap_result.groupby("source_file"):
        axes[1].plot(g["threshold"], g["격차(%p)"], marker="o", label=source_name)
    axes[1].axhline(0, color="gray", linewidth=0.8, linestyle="--")
    axes[1].set_xlabel("trend_score threshold (동시 경보 컬럼 수)")
    axes[1].set_ylabel("NG-OK 격차 (%p, 클수록 실제 예측력 있음)")
    axes[1].set_title("Threshold vs NG-OK Gap (실제 예측력)")
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(CALIBRATION_PLOT, dpi=150)
    plt.close(fig)
    return CALIBRATION_PLOT


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("[1/3] 원본 + Baseline_C + Trend 결과 결합 테이블 생성 중 (compare_spec_vs_trend.py 재사용)...")
    trend_results = pd.read_csv(cst.RESULTS_CSV)
    trend_results["DateTime"] = pd.to_datetime(trend_results["DateTime"])
    table = cst.build_full_comparison(trend_results)
    print(f"  -> {len(table)}행 (eligible {int(table['eligible'].sum())}행)")

    print("[2/3] 기준1: threshold별 Confusion Matrix / Precision / Recall / F1 / FAR 재계산 중...")
    cm_result = sweep_confusion_matrix(table)
    print(cm_result.to_string(index=False))
    print(f"저장: {CALIBRATION_CSV}")

    print("\n[3/3] 기준2: threshold별 NG-OK 대조군 격차 재계산 중 (LOOKBACK_N={})...".format(LOOKBACK_N))
    gap_result = sweep_ng_ok_gap(table)
    print(gap_result.to_string(index=False))
    print(f"저장: {CALIBRATION_GAP_CSV}")

    plot_path = make_plot(cm_result, gap_result)
    if plot_path:
        print(f"그래프 저장: {plot_path}")

    best_f1_row = cm_result.loc[cm_result["f1_score"].idxmax()]
    best_gap = gap_result.loc[gap_result["격차(%p)"].idxmax()]

    print("\n" + "=" * 60)
    print("임계값 보정 결과 요약")
    print("=" * 60)
    print(f"F1 기준 최적 threshold: {int(best_f1_row['threshold'])}"
          f" (Precision={best_f1_row['precision']:.4f}, Recall={best_f1_row['recall']:.4f},"
          f" F1={best_f1_row['f1_score']:.4f}, FAR={best_f1_row['false_alarm_rate']:.4f})")
    print(f"NG-OK 격차 기준 최적 threshold: {int(best_gap['threshold'])}"
          f" ({best_gap['source_file']}, 격차={best_gap['격차(%p)']:.2f}%p)")

    return {"confusion_matrix_sweep": cm_result, "gap_sweep": gap_result}


if __name__ == "__main__":
    main()
