"""Product×Recipe 히트맵용 집계 — 장비×변수별 경보 진입률을 6×9 격자로 만든다.

왜 별도 스크립트인가: 원자료가 두 개고 둘 다 크다(경보 로그 52k행 + 원본 샷 100k행).
서버가 뜰 때마다 읽으면 느리고, 집계 결과는 6,912개 숫자뿐이라 JSON 하나로 굽는 게 낫다.

**셀 값은 "건수"가 아니라 "비율"이다.** trend_analysis_results.csv는 경보가 난 행만
들어있는 이벤트 로그라(early_warning이 전부 True) 그 자체로는 분모가 없다. 건수만 쓰면
샷이 많은 조합이 자동으로 빨개진다 — 실제로 Product×Recipe별 샷 수는 418~548로 ±13%
차이가 난다. 그래서 원본 데이터에서 (장비,제품,레시피)별 샷 수를 세어 분모로 나눈다.

  cell = 그 조합에서 이 변수가 경보 상태였던 샷 수 / 그 조합의 전체 샷 수

실행:
  python3 build_heatmap_data.py
산출물: heatmap_data.json (dashboard.html이 /api/view/heatmap을 통해 읽는다)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TREND_RESULTS = ROOT / "analysis_outputs" / "trend_analysis_results.csv"
RAW = ROOT / "data" / "raw" / "DP_HealthIndex_Dataset.csv"
OUT = HERE / "heatmap_data.json"


def main() -> None:
    warn = pd.read_csv(TREND_RESULTS, usecols=["Machine_ID", "Product_ID", "Recipe_ID", "column"])
    raw = pd.read_csv(RAW, usecols=["Machine_ID", "Product_ID", "Recipe_ID"])

    # 분모: (장비, 제품, 레시피)별 전체 샷 수
    shots = raw.groupby(["Machine_ID", "Product_ID", "Recipe_ID"]).size()

    # 분자: (장비, 변수, 제품, 레시피)별 경보 샷 수
    warned = warn.groupby(["Machine_ID", "column", "Product_ID", "Recipe_ID"]).size()

    products = sorted(raw["Product_ID"].unique())
    recipes = sorted(raw["Recipe_ID"].unique())
    machines = sorted(raw["Machine_ID"].unique())

    cells: dict[str, dict[str, dict[str, float]]] = {}
    for (machine, column, product, recipe), n_warn in warned.items():
        denom = shots.get((machine, product, recipe))
        if not denom:
            continue
        rate = round(100.0 * n_warn / denom, 1)
        cells.setdefault(machine, {}).setdefault(column, {})[f"{product}|{recipe}"] = rate

    payload = {
        "products": products,
        "recipes": recipes,
        "machines": machines,
        "unit": "percent_of_shots_in_alert",
        "shots": {f"{m}|{p}|{r}": int(n) for (m, p, r), n in shots.items()},
        "cells": cells,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    n_cells = sum(len(v) for cols in cells.values() for v in cols.values())
    print(f"{OUT.name} 생성 — 장비 {len(machines)}대 × 변수 {len(next(iter(cells.values())))}개, 셀 {n_cells:,}개")
    print(f"격자: {len(products)} products × {len(recipes)} recipes = {len(products) * len(recipes)}칸")


if __name__ == "__main__":
    main()
