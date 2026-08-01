"""통합 분석(unified_full_methodology.py)의 Tier1/Tier2/Tier2b 인자에 대해,
원본/r1 데이터셋을 나눠서 각각 Cliff's delta(pure 라벨)를 재계산한다.

목적: 통합 데이터에서 나온 효과크기가 두 데이터셋 모두에서 재현되는지, 아니면
한쪽 데이터셋이 신호를 만들고 다른 쪽이 희석/반박하는지 구분한다 — 후자라면
"공통 원인"이 아니라 "이 데이터셋의 시나리오에 국한된 신호"로 봐야 한다.

가볍게 유지하기 위해 Mann-Whitney(Cliff's delta)만 재계산한다(트리/SHAP 재학습 안 함).

산출물: 09_reproducibility_by_dataset.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PARENT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import compute_stratum_baseline_stats, zscore_transform  # noqa: E402

OUT = Path(__file__).resolve().parent
OPCOND = config.OPCOND

DEFECTS = {
    "Particle": {"ng": "PARTICLE", "bin": "Particle"},
    "Remain_Coat": {"ng": "REM_COAT", "bin": "Remain_Coat"},
    "Chipping": {"ng": "CHIP", "bin": "Chipping"},
    "Micro_Crack": {"ng": "CRACK", "bin": "Micro_Crack"},
}
ALL_DEFECT_BIN_COLS = [v["bin"] for v in DEFECTS.values()]


def cliffs(a, b):
    a = pd.Series(a).dropna(); b = pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


print("[0] 데이터 로드 (원본 + r1, 이번엔 데이터셋별로도 baseline 재계산)")
o = pd.read_csv(DATA_PARENT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(DATA_PARENT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"

rows = []
for tname, tspec in DEFECTS.items():
    unified = pd.read_csv(OUT / f"07_{tname.lower()}_unified_verdict.csv", encoding="utf-8-sig")
    target_cols = unified.loc[unified.tier.str.startswith("Tier"), "column"].tolist()
    if not target_cols:
        continue
    print(f"  [{tname}] 재현성 확인 대상: {target_cols}")

    for dsname, part in [("original", o), ("r1", r)]:
        part = part.copy()
        part["is_normal"] = (part["Yield"] == 100) & (part["NG_Code"] == "OK")
        part = config.add_domain_features(part)
        cols_needed = [c for c in target_cols if c in part.columns or c in config.DOMAIN_FEATURES]
        bl = compute_stratum_baseline_stats(part[part.is_normal], OPCOND, cols_needed)
        part = zscore_transform(part, bl, OPCOND, cols_needed)

        others = [b for b in ALL_DEFECT_BIN_COLS if b != tspec["bin"]]
        pure = (part[tspec["bin"]] == 1) & (part[others] == 0).all(axis=1)
        n_pure = int(pure.sum())
        for c in cols_needed:
            d, p = cliffs(part.loc[pure, f"{c}_z"], part.loc[~pure, f"{c}_z"])
            rows.append({"defect": tname, "column": c, "dataset": dsname,
                        "n_pure": n_pure, "cliffs_delta": round(d, 4) if pd.notna(d) else None,
                        "p_value": p})

result = pd.DataFrame(rows)
wide = result.pivot_table(index=["defect", "column"], columns="dataset", values="cliffs_delta").reset_index()
wide.columns.name = None
wide["reproducible"] = wide.apply(
    lambda r: "양쪽 모두 |delta|>=0.2, 동일 방향" if (
        pd.notna(r.get("original")) and pd.notna(r.get("r1"))
        and abs(r["original"]) >= 0.2 and abs(r["r1"]) >= 0.2
        and np.sign(r["original"]) == np.sign(r["r1"])
    ) else (
        "한쪽 데이터셋에서만 신호 - 재현 안 됨" if (
            pd.notna(r.get("original")) and pd.notna(r.get("r1"))
            and (abs(r["original"]) >= 0.2) != (abs(r["r1"]) >= 0.2)
        ) else "약함/판단보류"
    ), axis=1)
wide.to_csv(OUT / "09_reproducibility_by_dataset.csv", index=False, encoding="utf-8-sig")
print("\n" + wide.to_string(index=False))
print("\n완료 —", OUT / "09_reproducibility_by_dataset.csv")
