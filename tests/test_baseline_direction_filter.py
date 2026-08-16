"""C유형 경계값 학습과 도메인 방향 필터 — CLAUDE.md 규칙 6.

실제 사례는 `CLN_Flow↔Particle`이다. 54그룹 중 7개가 "높으면 위험"으로 학습됐는데
세정 유량이 높아서 파티클이 는다는 건 물리적으로 말이 안 되므로 그 그룹은 이 짝의
근거로 안 쓴다. 여기서는 그 상황을 **합성 데이터로 축소 재현**해서, 필터가

  (1) 방향이 반대인 그룹의 행을 안 만들고,
  (2) 방향이 맞는 그룹은 그대로 두고,
  (3) DB에 방향이 없는 짝은 건드리지 않는지

를 본다. 원자료를 안 읽으므로 빠르고, 스텀프가 무슨 값을 찍었는지와 무관하게
"방향이 반대면 버린다"는 규칙 자체만 검사한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline import step0_preprocessing as step0


COLUMN, DEFECT = "TestFlow", "TestDefect"


def _group(product: str, recipe: str, low_is_bad: bool, n: int = 120) -> pd.DataFrame:
    """한 그룹치 합성 데이터. 위험한 쪽 절반에만 불량을 몰아준다.

    스텀프가 min_samples_leaf(10)를 만족하는 분기를 찾도록 양쪽을 넉넉히 나눈다.
    """
    rng = np.random.default_rng(0)
    half = n // 2
    values = np.concatenate([rng.normal(1.0, 0.05, half), rng.normal(9.0, 0.05, half)])
    flags = np.zeros(n, dtype=int)
    bad_slice = slice(0, 15) if low_is_bad else slice(n - 15, n)
    flags[bad_slice] = 1
    return pd.DataFrame({
        "Product_ID": product, "Recipe_ID": recipe,
        COLUMN: values, DEFECT: flags,
    })


@pytest.fixture
def df_two_groups():
    """G_ok는 "낮으면 위험", G_bad는 반대로 "높으면 위험"으로 학습될 데이터."""
    return pd.concat([
        _group("P1", "G_ok", low_is_bad=True),
        _group("P1", "G_bad", low_is_bad=False),
    ], ignore_index=True)


# ---------------------------------------------------------------------------
# 스텀프 자체 — 방향을 데이터에서 제대로 읽어내는지 (필터의 입력이 맞아야 한다)
# ---------------------------------------------------------------------------

def test_불량이_아래쪽에_몰리면_low_is_risky(df_two_groups):
    g = df_two_groups.query("Recipe_ID == 'G_ok'")
    result = step0._find_baseline_c_breakpoint(g[COLUMN], g[DEFECT])
    assert result is not None
    assert result["risky_direction"] == "low_is_risky"
    assert result["NG_rate_below"] > result["NG_rate_above"]


def test_불량이_위쪽에_몰리면_high_is_risky(df_two_groups):
    g = df_two_groups.query("Recipe_ID == 'G_bad'")
    result = step0._find_baseline_c_breakpoint(g[COLUMN], g[DEFECT])
    assert result is not None
    assert result["risky_direction"] == "high_is_risky"


def test_NG_표본이_부족하면_추정_안_함():
    """표본이 없어서 못 잰 것을 경계값으로 내보내면 안 된다."""
    n = 100
    values = pd.Series(np.linspace(0, 10, n))
    flags = pd.Series([1] * (step0.config.BASELINE_C_MIN_SAMPLES_LEAF - 1) + [0] * (n - step0.config.BASELINE_C_MIN_SAMPLES_LEAF + 1))
    assert step0._find_baseline_c_breakpoint(values, flags) is None


def test_전부_정상이면_추정_안_함():
    values = pd.Series(np.linspace(0, 10, 100))
    assert step0._find_baseline_c_breakpoint(values, pd.Series([0] * 100)) is None


# ---------------------------------------------------------------------------
# 방향 필터 — compute_baseline_type_c
# ---------------------------------------------------------------------------

def _run(monkeypatch, df, domain: dict) -> pd.DataFrame:
    monkeypatch.setattr(step0, "load_domain_directions", lambda: domain)
    return step0.compute_baseline_type_c(df, pairs=[(COLUMN, DEFECT)])


def test_도메인과_반대로_학습된_그룹만_빠진다(monkeypatch, df_two_groups):
    out = _run(monkeypatch, df_two_groups, {(COLUMN, DEFECT): "low_is_risky"})
    assert list(out["group_key"]) == ["P1|G_ok"]
    assert (out["risky_direction"] == "low_is_risky").all()


def test_도메인이_반대_방향이면_반대로_빠진다(monkeypatch, df_two_groups):
    """필터가 "무조건 low만 남긴다"가 아니라 진짜 DB 값을 따르는지 확인한다."""
    out = _run(monkeypatch, df_two_groups, {(COLUMN, DEFECT): "high_is_risky"})
    assert list(out["group_key"]) == ["P1|G_bad"]


def test_DB에_없는_짝은_그대로_둔다(monkeypatch, df_two_groups):
    """경보 전용 컬럼처럼 비교 대상이 없는 짝은 필터가 손대지 않는다."""
    out = _run(monkeypatch, df_two_groups, {})
    assert set(out["group_key"]) == {"P1|G_ok", "P1|G_bad"}


def test_남은_행은_짝_정보를_들고_있다(monkeypatch, df_two_groups):
    """한 컬럼이 두 defect의 원인일 수 있으므로 matched_defect 축이 살아 있어야 한다."""
    out = _run(monkeypatch, df_two_groups, {(COLUMN, DEFECT): "low_is_risky"})
    assert set(out["matched_defect"]) == {DEFECT}
    assert set(out["column"]) == {COLUMN}


def test_한_컬럼_두_defect면_그룹당_두_행(monkeypatch):
    """CLN_Flow가 Remain_Coat와 Particle 둘의 원인인 상황 — 경계값이 짝마다 따로 나온다."""
    df = _group("P1", "G_ok", low_is_bad=True)
    df["OtherDefect"] = df[DEFECT]
    monkeypatch.setattr(step0, "load_domain_directions", lambda: {})
    out = step0.compute_baseline_type_c(df, pairs=[(COLUMN, DEFECT), (COLUMN, "OtherDefect")])
    assert len(out) == 2
    assert set(out["matched_defect"]) == {DEFECT, "OtherDefect"}
