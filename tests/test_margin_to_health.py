"""Health Index 점수 변환 — CLAUDE.md 규칙 3, 규칙 5.

여기서 지키려는 문장은 둘이다.
  - margin(여유 소진율)만으로 점수가 정해진다. 불량 건수는 안 들어간다.
  - **10점 미만 = 관리한계 초과**이고 그 위는 아니다(규칙 5). ALARM_BAND가 그 경계다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def test_여유를_안_썼으면_만점(bhi):
    assert bhi.margin_to_health(0.0) == 100.0


def test_음수_margin은_0으로_취급(bhi):
    """정상값보다 안전한 쪽에 있어도 100점을 넘지 않는다."""
    assert bhi.margin_to_health(-50.0) == 100.0


def test_관리한계_도달점이_ALARM_BAND(bhi):
    """margin 100% = 관리한계(3σ) 도달 = 딱 ALARM_BAND점."""
    assert bhi.margin_to_health(100.0) == pytest.approx(bhi.ALARM_BAND)


def test_ALARM_BAND_미만은_관리한계_초과일_때만(bhi):
    """규칙 5: 10점 미만이라는 건 관리한계를 넘었다는 뜻이어야 한다(그 반대도)."""
    for margin in (0, 25, 50, 99.9, 100, 100.1, 150, 400):
        health = bhi.margin_to_health(margin)
        assert (health < bhi.ALARM_BAND) == (margin > 100), f"margin={margin}, health={health}"


def test_경계에서_두_식이_이어진다(bhi):
    """margin 100% 좌우에서 점프가 없어야 한다 — 선형 구간과 점근 구간이 만나는 지점."""
    assert bhi.margin_to_health(99.999) == pytest.approx(bhi.margin_to_health(100.001), abs=1e-3)


def test_전_구간_단조감소(bhi):
    """여유를 더 썼는데 점수가 오르는 구간이 있으면 안 된다."""
    margins = np.concatenate([np.linspace(0, 100, 201), np.linspace(100, 1000, 181)])
    healths = [bhi.margin_to_health(m) for m in margins]
    assert all(a >= b for a, b in zip(healths, healths[1:]))


def test_스펙아웃끼리도_순위가_남는다(bhi):
    """0~10점 구간을 예약해둔 이유 — 두 배 벗어난 것과 네 배 벗어난 것이 갈려야 한다."""
    assert bhi.margin_to_health(200.0) > bhi.margin_to_health(400.0) > 0


# ---------------------------------------------------------------------------
# 멘토 실측 스펙 기준 margin — direction이 "한쪽으로만 위험"을 어떻게 처리하는지
# ---------------------------------------------------------------------------

LSL, TARGET, USL = 0.0, 10.0, 20.0


def _margin(bhi, values, direction):
    return bhi._real_spec_margin_pct(pd.Series(values), direction, LSL, TARGET, USL)


def test_target에서_0_스펙경계에서_100(bhi):
    got = _margin(bhi, [10.0, 15.0, 20.0], "up")
    assert list(got) == [0.0, 50.0, 100.0]


def test_위로만_위험한_변수는_아래로_벗어나도_여유_소진_아님(bhi):
    """direction=up이면 target 아래는 전부 0 — 그쪽은 위험 방향이 아니다."""
    got = _margin(bhi, [5.0, 0.0, -5.0], "up")
    assert list(got) == [0.0, 0.0, 0.0]


def test_아래로만_위험한_변수는_아래쪽만_센다(bhi):
    got = _margin(bhi, [5.0, 0.0, 15.0], "down")
    assert list(got) == [50.0, 100.0, 0.0]


def test_either는_양쪽_다_센다(bhi):
    got = _margin(bhi, [5.0, 15.0], "either")
    assert list(got) == [50.0, 50.0]


def test_스펙이_한쪽만_있으면_그쪽만_계산(bhi):
    """usl == target이면 위쪽 margin은 정의되지 않는다 — 0이 아니라 NaN이어야 한다."""
    got = bhi._real_spec_margin_pct(pd.Series([15.0, 5.0]), "either", LSL, TARGET, TARGET)
    assert np.isnan(got.iloc[0])
    assert got.iloc[1] == 50.0
