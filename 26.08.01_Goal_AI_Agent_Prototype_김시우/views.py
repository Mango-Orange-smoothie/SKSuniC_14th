"""대시보드 뷰 빌더 — 선택(스코프)과 표현(뷰)을 분리한 화면용 데이터.

## 왜 이 파일이 따로 있나

이전 화면(chat.html, 26.08.11에 삭제)은 "질문 → 답변 + 패널"이라 화면 상태가 전적으로
Claude의 도구 호출에 달려 있었다. 자유도가 높아 무엇을 물어볼 수 있는지 알 수 없고,
같은 질문이 매번 같은 화면에 도착한다는 보장도 없었다. dashboard.html은 그 반대로 간다 —
화면이 가질 수 있는 상태를 먼저 유한하게 정의하고, 사이드바 클릭이든 자연어 질문이든
**똑같은 상태 객체 하나**를 만들어낸다. 이 파일이 그 상태를 데이터로 바꾸는 곳이다.

## 뷰 상태 스키마

    {"view": "trend"   , "machine": "DP04", "factor": "CLN_Flow"}
    {"view": "defect"  , "machine": "DP04", "defects": ["Remain_Coat", ...]}
    {"view": "heatmap" , "machine": "DP04", "factor": "CLN_Flow"}
    {"view": "compare" ,                    "factor": "CLN_Flow"}

뷰마다 필요한 스코프가 다르다는 게 핵심이다. compare는 장비를 안 받는다(4대 고정이
그 뷰의 정의다). defect는 변수를 안 받는다. 선택기를 뷰에 따라 켜고 끄는 근거가 여기다.

## 데이터 출처

agent.py가 이미 읽어둔 프레임을 그대로 재사용한다(LEVEL_TREND/DAILY_SERIES/DAILY_TREND/
CAUSE_FACTORS). agent를 import해도 API 키는 필요 없다 — anthropic 클라이언트는 ask()
안에서 만들어지므로 키 없이도 이 모듈과 대시보드의 그래프·히트맵은 전부 동작한다.
키가 필요한 건 챗봇 답변뿐이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import agent

HERE = Path(__file__).resolve().parent
HEATMAP_DATA = HERE / "heatmap_data.json"

DEFECTS = ["Chipping", "Remain_Coat", "Particle", "Micro_Crack"]

# 변수를 평평하게 32개 늘어놓으면 못 고른다. 관계DB의 role을 그대로 그룹 이름으로 쓴다 —
# 새 분류를 발명하지 않고, DB가 쓰는 용어(FDC/Response)를 화면에도 그대로 노출한다.
#   FDC      = 공정에서 조정할 수 있는 설비/공정 조건. 값을 바꾸면 불량이 바뀐다(원인)
#   Response = 공정의 결과로 나타나는 측정값. 불량과 같이 움직이지만 조정 대상은 아니다
GROUP_CAUSE = "원인 (FDC)"
GROUP_MONITOR = "감시지표 (Response)"
# Vibration은 FDC도 Response도 아니다 — 값을 조정해서 고치는 게 아니라 설비를 정비해야
# 하는 열화 신호라, 26.08.06부터 원인 후보에서 빠지고 별도 알람 트랙으로 운영된다.
GROUP_EQUIPMENT = "설비 열화 (Equipment)"
# 관계DB에 불량과의 관계가 아직 확정되지 않은 나머지 변수들. 원인으로 지목하지는 않지만
# 놓치면 안 되니 같은 방식으로 감시만 한다(안전망).
GROUP_OTHER = "관계 미확정 (안전망)"

# Vibration은 26.08.06부터 원인 후보에서 빠지고 별도 알람 트랙으로 운영된다 —
# 값을 조정해서 고치는 인자가 아니라 설비 점검 대상이라 그룹을 따로 준다.
EQUIPMENT_FACTORS = {"Vibration"}

with open(HEATMAP_DATA, encoding="utf-8") as f:
    HEATMAP = json.load(f)

# 관계DB의 tier 표에는 있는데 agent_cause_factors.json에는 안 실린 두 컬럼을 가져온다.
# risk_ratio(24.67배)만 보여주면 "무엇의 몇 배인지" 알 수가 없다 — 실제 두 불량률
# (정상구간 0.7% → 위험구간 18.4%)을 같이 줘야 배수가 스스로 설명된다.
_TIER_TABLE = pd.read_csv(agent.REL_DB / "rel_20_tier_table.csv")
DEFECT_RATES = {
    (r["defect"], r["factor"]): {
        "rate_in_normal_pct": r["rate_in_normal_pct"],
        "rate_in_risky_pct": r["rate_in_risky_pct"],
        "threshold_raw": r["alert_threshold_raw"],
    }
    for _, r in _TIER_TABLE.iterrows()
}


def _clear_agent_chart_calls() -> None:
    """agent.get_trend_chart_data는 호출될 때마다 전역 리스트에 결과를 쌓는다(챗봇이
    나중에 꺼내 쓰려고). 뷰 빌더가 그 함수를 재사용하면 그 리스트가 무한히 자라므로
    쓰고 나서 비운다 — 챗봇 턴과 뷰 요청이 서로의 상태를 오염시키지 않게."""
    agent._chart_calls_this_turn.clear()


def _chart(machine_id: str, factor: str, days: int | None = None) -> dict | None:
    """agent의 시계열 조회를 그대로 쓴다. 관리한계/스펙 두 축, 짝지어진 defect 불량률,
    경보 시작일까지 이미 다 넣어주므로 화면 쪽 렌더러가 그대로 받아 그리면 된다."""
    try:
        raw = agent.get_trend_chart_data.func(machine_id, factor, days)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    finally:
        _clear_agent_chart_calls()
    # 조회 실패 시 agent는 JSON이 아니라 안내 문장을 돌려준다 — series 유무로 가른다.
    return data if isinstance(data, dict) and data.get("series") else None


# ---------------------------------------------------------------- 부트스트랩(선택기)

def machines_overview() -> list[dict]:
    """상단 장비 스트립 — 질문 전에도 항상 보이는 4대 상태. LLM을 안 거친다."""
    out = []
    for machine_id, snap in agent.MACHINES.items():
        worst = (snap.get("worst_defects") or [{}])[0]
        out.append({
            "machine_id": machine_id,
            "health_index": snap.get("health_index"),
            "worst_defect": worst.get("defect"),
            "worst_factor": worst.get("worst_factor"),
            "latest_date": snap.get("latest_date"),
        })
    return sorted(out, key=lambda m: (m["health_index"] is None, m["health_index"]))


# tier는 인자 레벨과 짝(인자×defect) 레벨이 다를 수 있다 — CLN_Flow는 인자 레벨이 T2지만
# Remain_Coat 짝으로는 T1이다. 사이드바 배지와 뷰 헤더가 서로 다른 값을 보여주면 안 되므로
# 둘 다 "쓸 수 있는 짝 중 가장 급한 것"으로 통일한다.
_TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "T4": 3, "M1": 4}


def _urgent_tier(meta: dict, usable_defects: list[str]) -> tuple[str | None, str | None]:
    per = meta.get("per_defect") or {}
    best = None
    for defect in usable_defects:
        pair = per.get(defect) or {}
        tier = pair.get("tier")
        if tier and (best is None or _TIER_RANK.get(tier, 9) < _TIER_RANK.get(best[0], 9)):
            best = (tier, pair.get("action_type", meta.get("action_type")))
    return best or (meta.get("tier"), meta.get("action_type"))


def variable_tree(machine_id: str) -> list[dict]:
    """사이드바 변수 목록. 그룹별로 묶고, 각 변수에 이 장비에서의 상태를 붙인다.

    alert_usable=False인 짝은 **목록에서 지우지 않고 사유를 달아 비활성으로 둔다.**
    Particle에 쓸 수 있는 원인 인자가 없다는 건 숨길 사실이 아니라 화면에 나와야 하는
    결과다(Goal5 README의 "가짜 100점보다 정직하다" 원칙).
    """
    rows = agent.LEVEL_TREND[agent.LEVEL_TREND["Machine_ID"] == machine_id]
    by_col = {r["column"]: r for _, r in rows.iterrows()}

    groups: dict[str, list[dict]] = {
        GROUP_CAUSE: [], GROUP_MONITOR: [], GROUP_EQUIPMENT: [], GROUP_OTHER: [],
    }

    for column in sorted(by_col):
        meta = agent.CAUSE_FACTORS.get(column, {})
        row = by_col[column]
        role = meta.get("role")
        if column in EQUIPMENT_FACTORS:
            group = GROUP_EQUIPMENT
        elif role == "감시지표(Response)":
            group = GROUP_MONITOR
        elif meta:
            group = GROUP_CAUSE
        else:
            group = GROUP_OTHER

        # 이 인자가 실제로 경보에 쓰이는 defect만 남긴다 — per_defect 플래그 존중.
        per = meta.get("per_defect") or {}
        usable, blocked = [], []
        for defect in meta.get("defects", []):
            ok = per.get(defect, {}).get("alert_usable", meta.get("alert_usable", True))
            (usable if ok else blocked).append(defect)

        tier, action_type = _urgent_tier(meta, usable)
        groups[group].append({
            "factor": column,
            "tier": tier,
            "action_type": action_type,
            "actionable": meta.get("actionable"),
            "defects": usable,
            "blocked_defects": blocked,
            # 점수를 목록에 바로 실어야 "추세 탭을 눌러봐야 점수를 안다"는 문제가 없어지고,
            # 낮은 순 정렬이 가능해진다. 01_level_trend는 원인/비원인 가릴 것 없이 전 컬럼에
            # health_index를 갖고 있어서 안전망 변수도 같은 자로 잰 점수가 나온다.
            "health_index": (float(row["health_index"])
                             if pd.notna(row.get("health_index")) else None),
            "early_warning_active": bool(row.get("early_warning_active")),
            "alert_active_days": (float(row["alert_active_days"])
                                  if pd.notna(row.get("alert_active_days")) else None),
            # (26.08.11) 경보 배지를 "경보 O/X"가 아니라 세기로 그리기 위해 같이 싣는다.
            # "full"은 Health Index가 추세 페널티를 최대폭까지 받은 경보 — 즉 점수가 이미
            # 통째로 반영한 것이라 강조해도 점수와 어긋나지 않는다. "early"는 그 미만.
            "alert_level": (row["alert_level"]
                            if pd.notna(row.get("alert_level")) else None),
            "margin_used_pct": (float(row["margin_used_pct"])
                                if pd.notna(row.get("margin_used_pct")) else None),
            "spec_status": row.get("spec_status"),
        })

    # 점수가 낮은(=급한) 순으로 정렬한다. Health Index는 여유 소진과 경보 지속일을 이미
    # 합쳐서 계산한 값이라, 이걸로 줄 세우면 "경보 먼저 + 심한 것 먼저"가 자연히 나온다
    # — 예전처럼 경보 여부와 여유를 따로 보는 2단 정렬이 필요 없다.
    def sort_key(item: dict) -> tuple:
        hi = item["health_index"]
        return (hi is None, hi if hi is not None else 0.0, item["factor"])

    out = []
    for name, items in groups.items():
        if not items:
            continue
        items.sort(key=sort_key)
        # 접힌 그룹 안의 경보는 안 보인다 — "그 외 37개"가 접혀 있으면 거기 뜬 경보를
        # 영영 못 본다. 그룹 헤더에 개수를 실어서 펼칠 이유를 준다.
        #
        # (26.08.11) 개수를 둘로 나눈다. 활성 경보 76건 중 65건이 "early"(점수를 거의
        # 안 깎는 경보)라, 전부 세면 거의 모든 그룹에 빨간 불이 켜져서 접힌 채로는
        # 어느 그룹을 펼쳐야 할지 알 수 없었다. 빨간 불은 full만 세고, 총 개수는
        # 툴팁으로 남긴다 — 끄는 게 아니라 무게를 다르게 준다.
        out.append({
            "group": name,
            "items": items,
            "alert_count": sum(1 for it in items if it["early_warning_active"]),
            "alert_count_full": sum(1 for it in items if it["alert_level"] == "full"),
        })
    return out


def bootstrap() -> dict:
    """화면이 처음 뜰 때 한 번 — 선택기를 채우는 데 필요한 전부."""
    machines = machines_overview()
    default_machine = machines[0]["machine_id"]  # 제일 나쁜 장비부터 보여준다
    return {
        "machines": machines,
        "defects": DEFECTS,
        "default_state": {
            "view": "trend",
            "machine": default_machine,
            "factor": machines[0]["worst_factor"],
        },
        "variables": {m["machine_id"]: variable_tree(m["machine_id"]) for m in machines},
        "generated_at": agent.DATA.get("generated_at"),
        "heatmap_axes": {"products": HEATMAP["products"], "recipes": HEATMAP["recipes"]},
    }


# ---------------------------------------------------------------- 뷰 1: 추세

def view_trend(machine_id: str, factor: str) -> dict:
    chart = _chart(machine_id, factor)
    if chart is None:
        return {"error": f"{machine_id} / {factor} 시계열을 찾을 수 없습니다."}

    # 카드에 실을 숫자는 health_index_data.json 쪽(원인 상세)에서 가져온다 — 여유 소진률,
    # 위험구간 진입률, tier/조치 긴급도는 시계열에 없다.
    # 한 인자가 여러 defect의 원인일 수 있다(예: Head_Temp). 아무거나 첫 번째를 집으면
    # 사이드바 배지(가장 급한 짝)와 헤더가 어긋나므로, 여기서도 가장 급한 짝을 고른다.
    detail, defect_name = None, None
    snap = agent.MACHINES.get(machine_id, {})
    matches = [(d, sig["causes"][factor]) for d, sig in (snap.get("defect_signals") or {}).items()
               if (sig.get("causes") or {}).get(factor)]
    if matches:
        per_all = (agent.CAUSE_FACTORS.get(factor, {}).get("per_defect") or {})
        defect_name, detail = min(
            matches,
            key=lambda m: _TIER_RANK.get((per_all.get(m[0]) or {}).get("tier"), 9),
        )

    meta = agent.CAUSE_FACTORS.get(factor, {})
    # tier/조치 긴급도는 **인자 레벨이 아니라 짝(인자×defect) 레벨**을 써야 한다.
    # CLN_Flow는 인자 레벨이 T2지만 Remain_Coat 짝으로는 T1(즉시조치)이다 — 한 인자가
    # 여러 defect의 원인이면 인자 레벨 값은 그중 하나일 뿐이라 화면에 그대로 쓰면 틀린다.
    pair = (meta.get("per_defect") or {}).get(defect_name, {}) if defect_name else {}
    rates = DEFECT_RATES.get((defect_name, factor), {}) if defect_name else {}

    def _num(v):
        return float(v) if v is not None and pd.notna(v) else None

    # (26.08.11) 헤더에 쓸 **하류 defect 전체 목록**. 위 defect_name은 health_index_data의
    # causes에서 오는데, 그건 alert_usable=True인 짝만 담고 있어 CLN_Flow가 Remain_Coat
    # 하나로만 보였다. 관계DB는 CLN_Flow에 Remain_Coat와 Particle을 둘 다 달아뒀고
    # (Particle은 tier T2 / alert_usable=False — 막힌 건 경계값이지 관계가 아니다),
    # 멘토 확정 시나리오도 "세정 실패 -> 둘 다 증가"다. 원인 변수 쪽에서 읽으면
    # "이 변수가 나빠지면 이 두 불량이 생길 수 있다"가 맞는 서술이다.
    # tier/진입률 등 숫자는 아래처럼 계속 짝 단위(defect_name)로만 쓴다 — 경계값을
    # 근거로 쓰는 자리에는 alert_usable=False인 짝을 절대 끼워넣지 않는다.
    # 관계표는 agent가 관계DB 세 출처를 한 번에 훑어 만든 단일 표다(agent.defect_relations).
    # 화면은 인자 이름으로 분기하지 않고 tier/is_cause만 보고 줄을 나눈다.
    relations = agent.defect_relations(factor)

    return {
        "view": "trend",
        "machine": machine_id,
        "factor": factor,
        "defect": defect_name,
        "related_defects": relations,
        "chart": chart,
        "detail": detail,
        "meta": {
            "tier": pair.get("tier", meta.get("tier")),
            "action_type": pair.get("action_type", meta.get("action_type")),
            "role": meta.get("role"),
            "actionable": meta.get("actionable"),
            "mechanism": meta.get("mechanism"),
            "normal_range": pair.get("normal_range", meta.get("normal_range")),
            "risky_range": pair.get("risky_range", meta.get("risky_range")),
            "risk_ratio": pair.get("risk_ratio", meta.get("risk_ratio")),
            # 배수만 주면 "무엇의 몇 배"인지 모른다 — 두 구간의 실제 불량률을 같이 준다.
            "rate_in_normal_pct": _num(rates.get("rate_in_normal_pct")),
            "rate_in_risky_pct": _num(rates.get("rate_in_risky_pct")),
            # **판정 기준은 이 숫자 하나다.** normal_range/risky_range는 기준이 아니라
            # 각 쪽에 떨어진 샷들이 실제로 놓인 범위(p5~p95)라서, 둘 사이에 빈 구간이
            # 생긴다(양쪽 꼬리 5%씩을 잘라냈기 때문). 화면에서 두 범위만 보여주면
            # 그 빈 구간이 "중립지대"처럼 읽히므로 경계선을 같이 그려야 한다.
            "threshold_raw": _num(rates.get("threshold_raw")),
        },
    }


# ---------------------------------------------------------------- 뷰 2: defect 발생

def view_defect(machine_id: str, defects: list[str] | None = None,
                days: int | None = None) -> dict:
    """장비의 실제 불량률 추이. Health Index(조짐)와 완전히 분리된 축이다 —
    "이미 터진 것"과 "터지기 전"을 한 그래프에 섞지 않기 위해 뷰를 따로 둔다.

    days=None이면 전체 기간(89일). 숫자면 최근 그만큼만 — 89일을 통째로 보면 최근에
    무슨 일이 있었는지가 뭉개진다."""
    defects = [d for d in (defects or DEFECTS) if d in agent.DEFECT_RATE_COLS]
    sub = agent.DAILY_TREND[agent.DAILY_TREND["Machine_ID"] == machine_id].sort_values("date")
    if sub.empty:
        return {"error": f"{machine_id}의 일별 불량률 데이터가 없습니다."}

    total_days = len(sub)
    if days:
        sub = sub.tail(days)

    dates = [str(d) for d in sub["date"]]
    series = []
    for defect in defects:
        col = agent.DEFECT_RATE_COLS[defect]
        values = [(float(v) * 100 if pd.notna(v) else None) for v in sub[col]]
        observed = [v for v in values if v is not None]
        # 이 defect에 쓸 수 있는 원인 인자가 있는지 — 없으면 화면에서 "감시 수단 없음"을
        # 명시해야 한다. Particle이 제일 흔한 불량인데 경보를 걸 인자가 없는 상태다.
        series.append({
            "defect": defect,
            "values": values,
            "mean_pct": round(sum(observed) / len(observed), 3) if observed else None,
            "max_pct": round(max(observed), 3) if observed else None,
            "usable_factors": agent.DEFECT_TO_FACTORS.get(defect, []),
        })

    return {"view": "defect", "machine": machine_id, "dates": dates, "series": series,
            "days": days, "total_days": total_days}


# ---------------------------------------------------------------- 뷰 3: 히트맵

def view_heatmap(machine_id: str, factor: str) -> dict:
    """Product×Recipe 6×9 격자. 셀 = 그 조합에서 이 변수가 경보 상태였던 샷의 비율(%).

    장비는 격자에 넣지 않고 선택으로 남긴다 — 4대를 다 넣으면 216칸이 되어 아무도 못 읽는다.
    """
    grid = (HEATMAP["cells"].get(machine_id) or {}).get(factor)
    if not grid:
        return {"error": f"{machine_id} / {factor} 조합의 경보 기록이 없습니다 (경보 0건)."}

    products, recipes = HEATMAP["products"], HEATMAP["recipes"]

    # 경보 로그에 없는 조합은 **결측이 아니라 0건**이다 — 분모(샷 수)는 216개 조합 전부에
    # 존재한다. 빈칸으로 두면 "데이터 없음"으로 읽혀서 DP01처럼 건강한 장비가 측정이
    # 안 된 것처럼 보인다. 샷이 실제로 있는 조합만 0으로 채우고, 샷 자체가 없으면 None.
    shots = HEATMAP["shots"]
    rows = [[(grid.get(f"{p}|{r}")
              if f"{p}|{r}" in grid
              else (0.0 if shots.get(f"{machine_id}|{p}|{r}") else None))
             for r in recipes] for p in products]
    flat = [v for row in rows for v in row if v is not None]

    # 색 눈금의 천장은 **이 변수의 4대 전체 최댓값**으로 잡는다. 장비별 최댓값으로
    # 정규화하면 어느 장비를 봐도 격자가 똑같이 새빨개져서 "DP04가 DP01보다 심하다"가
    # 색으로 안 보인다(DP04 CLN_Flow 35~48% vs DP01 0.2~6.5%인데 둘 다 만점 빨강).
    scale_max = max(
        (v for m in HEATMAP["cells"].values() for v in (m.get(factor) or {}).values()),
        default=0.0,
    )

    # 집중도 판정: 최고 셀이 평균의 2배 이상이면 특정 조합을 지목해도 된다. 아니면
    # "레시피 문제가 아니라 설비 전반"이라고 읽어야 한다 — 관계DB agent_rules와 같은 기준.
    mean = sum(flat) / len(flat) if flat else 0.0
    peak = max(flat) if flat else 0.0
    concentrated = bool(flat and peak >= mean * 2)
    hotspot = None
    if flat:
        for i, p in enumerate(products):
            for j, r in enumerate(recipes):
                if rows[i][j] == peak:
                    hotspot = {"product": p, "recipe": r, "value": peak}
                    break
            if hotspot:
                break

    return {
        "view": "heatmap", "machine": machine_id, "factor": factor,
        "products": products, "recipes": recipes, "rows": rows,
        "min": min(flat) if flat else 0.0, "max": peak,
        "scale_max": round(scale_max, 1),
        "mean": round(mean, 1), "concentrated": concentrated, "hotspot": hotspot,
        "unit": "경보 샷 비율 (%)",
    }


# ---------------------------------------------------------------- 뷰 4: 장비 비교

def view_compare(factor: str) -> dict:
    """같은 변수를 4대에 겹쳐 그린다. 기준선(정상값/관리한계)은 4대 공통이다 —
    baseline이 Product×Recipe 층에서 잡히고 Machine_ID를 안 쓰기 때문이고,
    그게 이 뷰의 요점이다(같은 자로 재서 어느 장비가 벗어났는가)."""
    charts = []
    for machine_id in sorted(agent.MACHINES):
        chart = _chart(machine_id, factor)
        if chart:
            charts.append(chart)
    if not charts:
        return {"error": f"{factor}의 장비별 시계열을 찾을 수 없습니다."}

    # 장비마다 창(기간)이 다를 수 있으므로 날짜 축을 합집합으로 만들고 없는 날은 null로
    # 둔다 — 0으로 이으면 없는 데이터를 있는 것처럼 그리게 된다.
    dates = sorted({p["date"] for c in charts for p in c["series"]})
    machines = []
    for chart in charts:
        by_date = {p["date"]: p["value"] for p in chart["series"]}
        machines.append({
            "machine_id": chart["machine_id"],
            "values": [by_date.get(d) for d in dates],
            "early_warning_active": chart.get("early_warning_active"),
            "alert_active_days": chart.get("alert_active_days"),
            "alert_level": chart.get("alert_level"),
            "spec_status": chart.get("spec_status"),
        })

    ref = charts[0]
    return {
        "view": "compare", "factor": factor, "dates": dates, "machines": machines,
        "baseline_median": ref["baseline_median"],
        "control_lsl": ref["control_lsl"], "control_usl": ref["control_usl"],
        "score_side": ref.get("score_side", "both"),
    }


# ---------------------------------------------------------------- 라우팅

def build(state: dict) -> dict:
    """뷰 상태 객체 하나를 받아 화면용 데이터로. 사이드바 클릭과 챗봇 답변이
    **똑같이 이 함수를 통과한다** — 두 입력이 만들 수 있는 화면이 같아야 하기 때문이다."""
    view = (state or {}).get("view")
    machine = (state or {}).get("machine")
    factor = (state or {}).get("factor")

    if view == "trend":
        return view_trend(machine, factor)
    if view == "defect":
        return view_defect(machine, state.get("defects"), state.get("days"))
    if view == "heatmap":
        return view_heatmap(machine, factor)
    if view == "compare":
        return view_compare(factor)
    return {"error": f"알 수 없는 뷰: {view!r}"}


def state_from_panels(panels: list | None) -> dict | None:
    """챗봇 답변에 딸려온 패널에서 뷰 상태를 뽑아낸다.

    Claude의 답변 문장을 파싱하지 않는다 — agent가 이미 도구 호출 결과로 결정론적인
    패널(장비/변수가 박힌)을 만들어두므로 거기서 읽는다. 즉 자연어는 **선택 UI의
    단축키**로만 작동하고, 화면이 갈 수 있는 곳은 여전히 이 4개 뷰뿐이다.
    """
    if not panels:
        return None
    first = panels[0]
    if first.get("compare"):
        return {"view": "compare", "factor": first["compare"].get("factor")}
    chart = first.get("chart")
    if chart and chart.get("machine_id") and chart.get("factor"):
        return {"view": "trend", "machine": chart["machine_id"], "factor": chart["factor"]}
    return None
