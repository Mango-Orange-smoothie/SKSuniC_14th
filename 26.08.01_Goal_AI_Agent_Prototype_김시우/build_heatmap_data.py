"""Product×Recipe 히트맵용 집계 — 장비×변수별 경보 진입률을 6×9 격자로 만든다.

왜 별도 스크립트인가: 원자료가 두 개고 둘 다 크다(경보 로그 61k행 + 원본 샷 100k행).
서버가 뜰 때마다 읽으면 느리고, 집계 결과는 6,912개 숫자뿐이라 JSON 하나로 굽는 게 낫다.

**셀 값은 "건수"가 아니라 "비율"이다.** trend_analysis_results.csv는 경보가 난 행만
들어있는 이벤트 로그라(early_warning이 전부 True) 그 자체로는 분모가 없다. 건수만 쓰면
샷이 많은 조합이 자동으로 빨개진다 — 실제로 Product×Recipe별 샷 수는 418~548로 ±13%
차이가 난다. 그래서 원본 데이터에서 (장비,제품,레시피)별 샷 수를 세어 분모로 나눈다.

  cell = 그 조합에서 이 변수가 경보 상태였던 샷 수 / 그 조합의 전체 샷 수

**분자는 행 수가 아니라 샷 수다.** 경보 로그는 (인자, defect) **짝**을 단위로 쓰므로,
한 인자가 두 defect의 원인이면 같은 샷이 두 행으로 나온다 — 그대로 세면 분자만 2배가
되고 분모는 그대로라 비율이 통째로 틀린다(실측: DP04 CLN_Flow PKG_D|RCP_1은 443행이지만
경보 샷은 222개, 512샷 기준 86.5% vs 43.4%). 컬럼 전체로는 CLN_Flow 45.0% /
CLN_Pressure 40.1%가 부풀어 있었고, 최대 셀이 53.0 -> 96.3으로 뛰어 views.view_heatmap의
scale_max(4대 공통 색 눈금)까지 같이 왜곡됐다. 그래서 세기 전에 샷 단위로 중복을 없앤다.

한계: 경보 로그에 샷 식별자(Lot_ID/Strip_ID)가 없어 샷을 DateTime으로 가른다. 같은
(장비,제품,레시피) 안에서 시각이 겹치는 샷이 실제로 있어서, 짝이 하나뿐인 컬럼도
0.17%(전체 51,039행 중 52행)만큼 적게 세어진다. 짝 축을 안 지웠을 때의 최대 100%
과다계수보다 훨씬 작은 오차라 이쪽을 택한다 — 정확히 맞추려면 trend_analysis.py가
Lot_ID+Strip_ID를 실어야 한다.

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


# 경보 로그에서 "샷 하나"를 가리키는 키. matched_defect는 일부러 뺐다 — 한 샷이 두 짝으로
# 두 행이 되는 걸 여기서 하나로 접는 게 이 키의 목적이다(위 docstring 참고).
SHOT_KEY = ["Machine_ID", "Product_ID", "Recipe_ID", "column", "DateTime"]


def main() -> None:
    warn = pd.read_csv(TREND_RESULTS, usecols=SHOT_KEY)
    raw = pd.read_csv(RAW, usecols=["Machine_ID", "Product_ID", "Recipe_ID"])

    # 분모: (장비, 제품, 레시피)별 전체 샷 수
    shots = raw.groupby(["Machine_ID", "Product_ID", "Recipe_ID"]).size()

    # 분자: (장비, 변수, 제품, 레시피)별 경보 **샷** 수 — 짝(인자,defect)마다 생긴
    # 중복 행을 먼저 접는다. 안 접으면 defect가 둘인 컬럼만 비율이 2배가 된다.
    n_rows = len(warn)
    warn = warn.drop_duplicates(SHOT_KEY)
    print(f"경보 로그 {n_rows:,}행 -> 샷 {len(warn):,}개 "
          f"(짝 단위 중복 {n_rows - len(warn):,}행 제거)")
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
