"""defect 발생 전 원인변수가 며칠 전부터 "위험 신호"를 보였는지 실측 — 조기경보 리드타임 분석.

배경: trend_analysis.py의 PERSIST_WINDOW(몇 행 연속 유지돼야 경보인지)를 감으로 정하지
않고, "실제로 defect 나기 전에 원인변수가 얼마나 일찍부터 이상했는지"를 데이터로
확인해서 근거로 삼기 위해 만들었다.

방법론:
  1. CAUSE_FACTORS(build_health_index.py, 확정 원인 11개)의 defect별 원인변수마다:
  2. 그 defect가 실제로 발생한 모든 행(원본 데이터, Lot/Strip 단위 개별 샷)에 대해:
  3. 같은 장비(Machine_ID)의 시간순 데이터에서, 그 defect 발생 시점까지 최근
     LOOKBACK_ROWS(3000)행을 가져온다.
  4. 원인변수의 "margin"(0~100+, 100=스펙/임시경계 도달)을 매 행 계산한다.
       - 멘토 실측 스펙 있는 변수(pipeline/mentor.py): TARGET 대비 LSL/USL까지 거리 비율
       - 없는 변수: OPCOND z-score를 boundary_z(정상군 p0.5~p99.5 기반 임시경계)로 나눈 값
     둘 다 direction(up/down/either)에 따라 위험한 쪽만 카운트(안전한 쪽은 margin=0).
  5. margin >= RISK_MARGIN_THRESHOLD(50)를 "위험 상태"로 정의.
  6. defect 발생 그 행 자체가 위험 상태였는지 확인. 위험 상태였다면, 거기서부터
     시간을 거슬러 올라가며 "위험 상태가 끊기지 않고 계속된 첫 시점"을 찾는다
     (그 사이 단 1행이라도 안전 상태로 빠지면 그 지점에서 구간이 끊긴 것으로 봄).
  7. 리드타임 = defect 발생 시각 − 그 위험 구간이 시작된 시각 (일 단위).
  8. defect 발생 행 자체가 애초에 위험 상태가 아니었으면 "전조 없음"으로 집계
     (리드타임 계산 대상에서 제외 — 애초에 이 변수 기준으로는 예측 불가능했다는 뜻).

핵심 발견(26.08.05, 100,000행 원본 데이터 기준):
  - 대부분의 (원인변수, defect) 조합에서 "전조 있음" 비율 자체가 0~50%로 낮음.
  - 전조가 있는 경우조차 평균 리드타임이 0.0일 — 위험 상태가 defect 발생과 거의
    동시에 나타나지, 며칠 전부터 서서히 쌓이지 않음.
  - 결론: 지금 확정된 원인변수를 "단변량"으로 보는 한, 조기경보에 쓸 수 있는 시간적
    여유가 이 데이터엔 거의 없다. JHdaimma의 다변량(SHAP/RandomForest) 모델처럼
    여러 변수 조합을 봐야 진짜 조기경보가 가능할 가능성이 높다 — 다음 단계 후보.
  - 실무 함의: trend_analysis.py의 PERSIST_WINDOW를 늘려도 "미리 아는" 이득이
    없다(어차피 리드타임이 0이라) — 늘릴수록 그냥 감지만 늦어진다. 노이즈 필터링
    목적의 최소한만 유지하는 쪽이 낫다.

실행 (저장소 루트에서):
  python "26.08.01_Goal5_HealthIndex_Dashboard_김시우/analyze_lead_time.py"

산출물: 이 폴더의 05_lead_time_analysis.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import config
from pipeline.common import load_dataset, zscore_transform, compute_stratum_baseline_stats
from pipeline.mentor import SPEC
import build_health_index as bhi

OUT_DIR = Path(__file__).resolve().parent

RISK_MARGIN_THRESHOLD = 50  # margin이 이 값 이상이면 "위험 상태" — 관례적 컷오프, 최적화 안 됨
LOOKBACK_ROWS = 3000  # defect 시점 기준 최대 몇 행 전까지 거슬러 볼지 (한 장비의 리드타임 탐색 범위)


def main() -> None:
    df = load_dataset()
    df_normal = df.loc[df["is_normal"]]

    cause_cols = list(bhi.CAUSE_FACTORS.keys())
    opcond_baseline = compute_stratum_baseline_stats(df_normal, config.OPCOND, cause_cols)
    boundary_z = bhi.compute_boundary_z(opcond_baseline)
    z_df = zscore_transform(df, opcond_baseline, config.OPCOND, cause_cols)

    df = df.sort_values(["Machine_ID", "DateTime"]).reset_index(drop=True)
    z_df = z_df.loc[df.index]

    results = []
    for factor, meta in bhi.CAUSE_FACTORS.items():
        direction = meta["direction"]
        real_spec = SPEC.get(factor)

        for defect in meta["defects"]:
            if defect not in df.columns:
                continue
            defect_idx = df.index[df[defect] == 1]
            gaps = []
            for di in defect_idx:
                machine = df.loc[di, "Machine_ID"]
                dt = df.loc[di, "DateTime"]
                window_mask = (df["Machine_ID"] == machine) & (df["DateTime"] <= dt)
                sub_idx = df.index[window_mask][-LOOKBACK_ROWS:]

                if real_spec:
                    vals = df.loc[sub_idx, factor].values
                    lsl, target, usl = real_spec["LSL"], real_spec["TARGET"], real_spec["USL"]
                    above = vals >= target
                    margin = np.where(above, (vals - target) / (usl - target) * 100,
                                       (target - vals) / (target - lsl) * 100)
                else:
                    zvals = z_df.loc[sub_idx, f"{factor}_z"].values
                    b_z = boundary_z.get(factor, np.nan)
                    if direction == "down":
                        zvals = -zvals
                    elif direction == "either":
                        zvals = np.abs(zvals)
                    margin = zvals / b_z * 100
                    above = np.ones(len(margin), dtype=bool)

                if direction == "up":
                    margin = np.where(above, margin, 0)
                elif direction == "down":
                    margin = np.where(above, 0, margin)

                risky = margin >= RISK_MARGIN_THRESHOLD
                if len(risky) and risky[-1]:
                    idx = len(risky) - 1
                    while idx > 0 and risky[idx - 1]:
                        idx -= 1
                    dt_series = df.loc[sub_idx, "DateTime"].values
                    gap_days = (dt_series[-1] - dt_series[idx]) / np.timedelta64(1, "D")
                    gaps.append(gap_days)

            source = "mentor_spec" if real_spec else "provisional_percentile"
            n_events = len(defect_idx)
            results.append({
                "factor": factor,
                "defect": defect,
                "spec_source": source,
                "n_events": n_events,
                "n_전조있음": len(gaps),
                "전조비율_pct": round(len(gaps) / n_events * 100, 1) if n_events else None,
                "평균리드타임_일": round(float(np.mean(gaps)), 3) if gaps else None,
                "최대리드타임_일": round(float(np.max(gaps)), 3) if gaps else None,
            })

    result_df = pd.DataFrame(results)
    result_df.to_csv(OUT_DIR / "05_lead_time_analysis.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 140)
    print(result_df.to_string(index=False))
    print(f"\n저장: {OUT_DIR / '05_lead_time_analysis.csv'}")


if __name__ == "__main__":
    main()
