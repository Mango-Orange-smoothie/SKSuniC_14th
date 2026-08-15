"""유닛 테스트 공용 설정.

빌드 스크립트를 통째로 돌려 산출물 숫자를 눈으로 확인하는 검증(CLAUDE.md "검증 방법")은
전체를 다 돌려야 하고, 틀렸을 때 어디가 틀렸는지는 안 알려준다. 여기 있는 것은 그 아래
단계 — **순수 함수 하나씩** 잡아서 규칙대로 도는지 본다. 원자료를 안 읽으므로 빠르다.

`build_health_index.py`는 디렉터리 이름이 숫자로 시작하고 점이 들어가 있어(`26.08.01_...`)
import 문으로 못 불러온다. 경로로 직접 로드한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_BHI_PATH = REPO / "26.08.01_Goal5_HealthIndex_Dashboard_김시우" / "build_health_index.py"


@pytest.fixture(scope="session")
def bhi():
    """build_health_index 모듈. import 시점에 관계DB를 읽으므로 세션에 한 번만 로드한다."""
    spec = importlib.util.spec_from_file_location("build_health_index", _BHI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
