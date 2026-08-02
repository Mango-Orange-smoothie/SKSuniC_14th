"""
performance_validation.py

Goal4: Performance Validation

Trend Analysis(early_warning) 방식이 기존 Spec-Out 방식(위험 Threshold를 넘은
경우만 이상으로 판단)보다 얼마나 조기에, 얼마나 많이 이상을 탐지하는지
객관적으로 검증한다.

실행:
  python Goal4_Performance_Validation/performance_validation.py

기존 코드(trend_analysis.py)나 기존 CSV는 전혀 수정하지 않는다.
결과는 이 파일과 같은 폴더의 results/ 아래에만 생성한다. Git 관련 작업은 하지 않는다.
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

PERFORMANCE_SUMMARY_CSV = os.path.join(RESULTS_DIR, "performance_summary.csv")
DETECTION_COMPARISON_CSV = os.path.join(RESULTS_DIR, "detection_comparison.csv")
CONFUSION_MATRIX_CSV = os.path.join(RESULTS_DIR, "confusion_matrix.csv")


def make_plots(table, trend_results, summary_rows, out_dir):
    """가능하면 ROC/PR Curve, Spec vs Trend 탐지건수, Warning 분포 그래프를 만든다.
    그래프 생성은 부가 기능이므로, 실패해도 본 검증 결과(CSV) 생성에는 영향을 주지 않는다.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.metrics import roc_curve, precision_recall_curve, auc
    except ImportError as exc:
        print(f"[그래프 생략] matplotlib/scikit-learn을 불러올 수 없습니다: {exc}")
        return []

    saved = []
    elig = table[table["eligible"]]
    y_true = elig["y_true"].to_numpy()

    def safe_score(series):
        arr = series.to_numpy(dtype=float)
        if np.all(np.isnan(arr)):
            return np.zeros_like(arr)
        fill = np.nanmin(arr) - 1
        return np.nan_to_num(arr, nan=fill)

    # 1) ROC Curve + Precision-Recall Curve
    try:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        for name, col in [("Spec", "spec_score"), ("Trend", "trend_score")]:
            score = safe_score(elig[col])
            fpr, tpr, _ = roc_curve(y_true, score)
            roc_auc = auc(fpr, tpr)
            axes[0].plot(fpr, tpr, label=f"{name} (AUC={roc_auc:.3f})")
        axes[0].plot([0, 1], [0, 1], "k--", linewidth=0.8, label="Random")
        axes[0].set_xlabel("False Positive Rate")
        axes[0].set_ylabel("True Positive Rate")
        axes[0].set_title("ROC Curve")
        axes[0].legend()

        for name, col in [("Spec", "spec_score"), ("Trend", "trend_score")]:
            score = safe_score(elig[col])
            prec, rec, _ = precision_recall_curve(y_true, score)
            pr_auc = auc(rec, prec)
            axes[1].plot(rec, prec, label=f"{name} (AUC={pr_auc:.3f})")
        axes[1].set_xlabel("Recall")
        axes[1].set_ylabel("Precision")
        axes[1].set_title("Precision-Recall Curve")
        axes[1].legend()

        fig.tight_layout()
        path = os.path.join(out_dir, "roc_pr_curve.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        saved.append(path)
    except Exception as exc:
        print(f"[그래프 생략] ROC/PR Curve 생성 실패: {exc}")

    # 2) Spec vs Trend Detection Count
    try:
        methods = [r["method"] for r in summary_rows]
        counts = [r["detection_count"] for r in summary_rows]
        fig, ax = plt.subplots(figsize=(6, 5))
        bars = ax.bar(methods, counts, color=["#7f8fa6", "#e67e22"])
        ax.set_ylabel("Detection Count")
        ax.set_title("Spec vs Trend Detection Count")
        for bar, v in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width() / 2, v, str(v), ha="center", va="bottom")
        fig.tight_layout()
        path = os.path.join(out_dir, "spec_vs_trend_detection_count.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        saved.append(path)
    except Exception as exc:
        print(f"[그래프 생략] Detection Count 그래프 생성 실패: {exc}")

    # 3) Warning Distribution (Trend Analysis 결과의 유형별 분포)
    try:
        counts = trend_results["type"].value_counts()
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.bar(counts.index.astype(str), counts.values, color="#3498db")
        ax.set_ylabel("Count")
        ax.set_xlabel("Baseline Type")
        ax.set_title("Warning Distribution by Type (Trend Analysis)")
        fig.tight_layout()
        path = os.path.join(out_dir, "warning_distribution.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        saved.append(path)
    except Exception as exc:
        print(f"[그래프 생략] Warning Distribution 그래프 생성 실패: {exc}")

    return saved


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("[1/5] Trend Analysis 결과 로드 중...")
    trend_results = pd.read_csv(cst.RESULTS_CSV)
    trend_results["DateTime"] = pd.to_datetime(trend_results["DateTime"])
    print(f"  -> {len(trend_results)}행 로드")

    print("[2/5] 레코드 단위 비교 테이블 생성 중 (원본 데이터 + Baseline_C 위험선 + Trend 결과 결합)...")
    table = cst.build_full_comparison(trend_results)
    elig = table[table["eligible"]]
    print(f"  -> 전체 {len(table)}행 중 비교 가능(eligible, Rolling Window 이후) {len(elig)}행")

    print("[3/5] Confusion Matrix 및 성능지표 계산 중...")
    y_true = elig["y_true"].to_numpy()
    spec_pred = elig["spec_flag"].to_numpy()
    trend_pred = elig["trend_flag"].to_numpy()

    spec_summary = em.summarize_method(y_true, spec_pred, "Spec")
    trend_summary = em.summarize_method(y_true, trend_pred, "Trend")

    confusion_df = pd.DataFrame([
        {"method": "Spec", **em.confusion_counts(y_true, spec_pred)},
        {"method": "Trend", **em.confusion_counts(y_true, trend_pred)},
    ])
    confusion_df.to_csv(CONFUSION_MATRIX_CSV, index=False, encoding="utf-8-sig")

    # 항목 8: Spec은 놓쳤지만 Trend는 잡은 실제 NG 레코드 수
    n_spec_missed_trend_caught = int((elig["y_true"] & ~elig["spec_flag"] & elig["trend_flag"]).sum())
    # 항목 9: Trend가 이상으로 판단했지만 실제로는 NG가 아니었던 레코드 수 (Trend의 FP와 동일)
    n_trend_false_positive = trend_summary["FP"]

    print("[4/5] 실제 NG 발생 대비 조기탐지(lead time) 계산 중...")
    lead_table = cst.compute_lead_times(table)
    lead_table.to_csv(DETECTION_COMPARISON_CSV, index=False, encoding="utf-8-sig")

    mean_lead_spec = lead_table.loc[lead_table["detected_by_spec"], "lead_minutes_spec"].mean()
    mean_lead_trend = lead_table.loc[lead_table["detected_by_trend"], "lead_minutes_trend"].mean()
    median_lead_spec = lead_table.loc[lead_table["detected_by_spec"], "lead_minutes_spec"].median()
    median_lead_trend = lead_table.loc[lead_table["detected_by_trend"], "lead_minutes_trend"].median()
    n_ng_events = len(lead_table)
    n_ng_detected_spec = int(lead_table["detected_by_spec"].sum())
    n_ng_detected_trend = int(lead_table["detected_by_trend"].sum())

    spec_summary["mean_lead_minutes"] = mean_lead_spec
    spec_summary["median_lead_minutes"] = median_lead_spec
    spec_summary["ng_events_detected_before_or_at"] = n_ng_detected_spec
    trend_summary["mean_lead_minutes"] = mean_lead_trend
    trend_summary["median_lead_minutes"] = median_lead_trend
    trend_summary["ng_events_detected_before_or_at"] = n_ng_detected_trend

    summary_rows = [spec_summary, trend_summary]
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(PERFORMANCE_SUMMARY_CSV, index=False, encoding="utf-8-sig")

    print("[5/5] 그래프 생성 중 (ROC/PR Curve, Detection Count, Warning Distribution)...")
    saved_plots = make_plots(table, trend_results, summary_rows, RESULTS_DIR)

    generated_files = [PERFORMANCE_SUMMARY_CSV, DETECTION_COMPARISON_CSV, CONFUSION_MATRIX_CSV] + saved_plots

    print("\n" + "=" * 60)
    print("Goal4 Performance Validation 완료")
    print("=" * 60)

    print("\n[생성된 파일]")
    for p in generated_files:
        print(f"  - {p}")

    print("\n[Spec 방식]")
    print(f"  Detection Count : {spec_summary['detection_count']}")
    print(f"  Precision       : {spec_summary['precision']:.4f}")
    print(f"  Recall          : {spec_summary['recall']:.4f}")
    print(f"  F1-score        : {spec_summary['f1_score']:.4f}")
    print(f"  False Alarm Rate: {spec_summary['false_alarm_rate']:.4f}")
    print(f"  평균 조기탐지(분): {mean_lead_spec:.2f}" if pd.notna(mean_lead_spec) else "  평균 조기탐지(분): N/A")

    print("\n[Trend 방식]")
    print(f"  Detection Count : {trend_summary['detection_count']}")
    print(f"  Precision       : {trend_summary['precision']:.4f}")
    print(f"  Recall          : {trend_summary['recall']:.4f}")
    print(f"  F1-score        : {trend_summary['f1_score']:.4f}")
    print(f"  False Alarm Rate: {trend_summary['false_alarm_rate']:.4f}")
    print(f"  평균 조기탐지(분): {mean_lead_trend:.2f}" if pd.notna(mean_lead_trend) else "  평균 조기탐지(분): N/A")

    print(f"\n[실제 NG 이벤트 수] {n_ng_events}건")
    print(f"  Spec 방식이 사전/동시 탐지한 NG  : {n_ng_detected_spec}건")
    print(f"  Trend 방식이 사전/동시 탐지한 NG : {n_ng_detected_trend}건")

    print(f"\n[항목 8] Spec은 놓쳤지만 Trend가 탐지한 사례 수: {n_spec_missed_trend_caught}건")
    print(f"[항목 9] Trend가 탐지했지만 실제 NG가 아니었던 사례 수: {n_trend_false_positive}건")

    return {
        "spec_summary": spec_summary,
        "trend_summary": trend_summary,
        "n_spec_missed_trend_caught": n_spec_missed_trend_caught,
        "n_trend_false_positive": n_trend_false_positive,
        "n_ng_events": n_ng_events,
    }


if __name__ == "__main__":
    main()
