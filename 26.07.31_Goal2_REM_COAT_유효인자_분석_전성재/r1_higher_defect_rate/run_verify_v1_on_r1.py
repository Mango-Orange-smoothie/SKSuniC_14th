"""r1 데이터로 1차 검증(Mann-Whitney + RandomForest)을 그대로 재실행 (전성재).

verify_rem_coat_factors.py의 통계 로직은 전혀 건드리지 않는다. config.INPUT_CSV와
결과 저장 경로만 r1용으로 바꿔치기해서 같은 함수를 그대로 호출한다.
"""

import sys
from pathlib import Path

from pipeline import config

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent

config.INPUT_CSV = REPO_ROOT / "data" / "raw" / "DP_HealthIndex_Dataset_r1.csv"

sys.path.insert(0, str(PARENT_DIR))
import verify_rem_coat_factors as v1  # noqa: E402

v1.OUT_DIR = OUT_DIR  # 결과를 r1 폴더에 저장 (원본 검증 결과 덮어쓰지 않음)

if __name__ == "__main__":
    v1.main()
