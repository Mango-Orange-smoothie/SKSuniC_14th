"""
evaluation_metrics.py

Goal4: Performance Validation에서 쓰는 표준 탐지 성능 지표 계산 함수 모음.
순수 함수만 포함하며, 파일 입출력은 하지 않는다(재사용 가능한 유틸리티 모듈).
"""

import numpy as np


def confusion_counts(y_true, y_pred):
    """y_true/y_pred(불리언 배열)로부터 TP/FP/FN/TN 카운트를 계산한다."""
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = np.asarray(y_pred, dtype=bool)
    tp = int(np.sum(y_true & y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))
    tn = int(np.sum(~y_true & ~y_pred))
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn}


def precision_score(tp, fp):
    denom = tp + fp
    return tp / denom if denom > 0 else np.nan


def recall_score(tp, fn):
    denom = tp + fn
    return tp / denom if denom > 0 else np.nan


def f1_score(precision, recall):
    if precision is None or recall is None:
        return np.nan
    if np.isnan(precision) or np.isnan(recall) or (precision + recall) == 0:
        return np.nan
    return 2 * precision * recall / (precision + recall)


def false_alarm_rate(fp, tn):
    """False Positive Rate = FP / (FP + TN): 실제 정상인데 잘못 경보를 울린 비율."""
    denom = fp + tn
    return fp / denom if denom > 0 else np.nan


def detection_rate(tp, fn):
    """Recall과 동일한 값이지만, 비교표의 'Detection Rate' 항목명에 맞춰 별도로 제공한다."""
    return recall_score(tp, fn)


def summarize_method(y_true, y_pred, method_name):
    """한 탐지 방식(Spec 또는 Trend)에 대한 성능지표 전체를 dict로 요약한다."""
    counts = confusion_counts(y_true, y_pred)
    p = precision_score(counts["TP"], counts["FP"])
    r = recall_score(counts["TP"], counts["FN"])
    f1 = f1_score(p, r)
    far = false_alarm_rate(counts["FP"], counts["TN"])
    return {
        "method": method_name,
        "detection_count": counts["TP"] + counts["FP"],
        "TP": counts["TP"],
        "FP": counts["FP"],
        "FN": counts["FN"],
        "TN": counts["TN"],
        "precision": p,
        "recall": r,
        "f1_score": f1,
        "detection_rate": r,
        "false_alarm_rate": far,
    }
