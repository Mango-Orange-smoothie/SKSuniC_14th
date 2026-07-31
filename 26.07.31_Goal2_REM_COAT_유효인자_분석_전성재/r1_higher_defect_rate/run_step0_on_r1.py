"""r1(불량률 높인 새 데이터)로 Step0 전처리를 그대로 재실행 (전성재).

pipeline/step0_preprocessing.py, pipeline/config.py, pipeline/common.py의 로직은
단 한 줄도 수정하지 않는다. 입력 파일 경로와 EXPECTED_ROW_COUNT/EXPECTED_NORMAL_COUNT
(원본 데이터 기준으로 하드코딩된 sanity-check 값)만 r1 데이터 기준으로 바꿔서
같은 코드를 다시 돌린다 — "전처리 방법은 그대로, 데이터 값만 교체" 요청에 따른 것.

실행 전 확인한 값: r1 데이터는 100,000행, 정상군(Yield=100 & NG_Code=OK) 58,890건
(김시우님 원본 pipeline의 NORMAL() 정의 그대로 적용해 확인함).
"""

from pathlib import Path

from pipeline import config

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent

config.INPUT_CSV = REPO_ROOT / "data" / "raw" / "DP_HealthIndex_Dataset_r1.csv"
config.EXPECTED_ROW_COUNT = 100_000
config.EXPECTED_NORMAL_COUNT = 58_890
config.OUTPUT_DIR = OUT_DIR
config.PREPROCESSING_DIR = OUT_DIR / "preprocessing"

from pipeline import step0_preprocessing  # noqa: E402  (config 패치 이후에 import해야 함)

if __name__ == "__main__":
    step0_preprocessing.main()
