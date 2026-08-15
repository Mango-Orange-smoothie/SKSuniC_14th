"""경보 기준선 — `binomial_alert_count`.

이 함수를 만든 이유가 "평소의 몇 배" 같은 고정 배수는 평소 비율에 따라 엄격도가
제멋대로 달라지기 때문이다(같은 2배가 컬럼마다 8.7배 차이 나는 기준이 됨). 배수 대신
**오탐 확률을 고정**한다. 그래서 여기서 검사할 것은 개별 숫자보다 그 성질이다 —
평소 비율이 높을수록 기준 k도 높아야 하고, alpha를 조이면 k가 안 내려가야 한다.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as scipy_stats

from pipeline.common import binomial_alert_count


def test_k는_실제로_오탐확률을_만족하는_최소값():
    """정의 그대로 — P(X >= k) < alpha이고, k-1에서는 아직 아니어야 한다."""
    n, alpha = 10, 0.05
    for base_rate in (0.005, 0.064, 0.32):
        k = binomial_alert_count(base_rate, n, alpha)
        assert scipy_stats.binom.sf(k - 1, n, base_rate) < alpha
        if k > 1:
            assert scipy_stats.binom.sf(k - 2, n, base_rate) >= alpha


def test_평소_비율이_높을수록_기준도_높다():
    ks = [binomial_alert_count(p, 10, 0.05) for p in (0.005, 0.064, 0.32)]
    assert ks == sorted(ks)
    assert len(set(ks)) > 1, "비율이 64배 차이 나는데 기준이 같으면 고정배수와 다를 게 없다"


def test_평소_불량이_0이면_한_건이_곧_경보():
    """예전엔 '비율이 정의 안 됨'으로 따로 빠졌던 자리 — 같은 공식이 자연히 k=1을 준다."""
    assert binomial_alert_count(0.0, 10, 0.05) == 1


def test_도달_불가능하면_절대_경보_안_뜬다():
    """평소가 이미 90%면 10샷 중 몇 개가 나와도 놀랄 일이 아니다 -> n+1(도달 불가)."""
    n = 10
    assert binomial_alert_count(0.9, n, 0.05) == n + 1


def test_alpha를_조이면_기준이_안_내려간다():
    ks = [binomial_alert_count(0.064, 10, a) for a in (0.10, 0.05, 0.01, 0.001)]
    assert all(a <= b for a, b in zip(ks, ks[1:]))


def test_k는_1과_n_사이거나_도달불가():
    for p in np.linspace(0, 0.5, 11):
        k = binomial_alert_count(float(p), 20, 0.05)
        assert 1 <= k <= 21


@pytest.mark.parametrize("base_rate, n_trials", [
    (float("nan"), 10),
    (-0.1, 10),
    (0.05, 0),
])
def test_말이_안_되는_입력은_도달불가로_막는다(base_rate, n_trials):
    """터지지 않고, 그렇다고 경보를 남발하지도 않는다."""
    assert binomial_alert_count(base_rate, n_trials, 0.05) == n_trials + 1
