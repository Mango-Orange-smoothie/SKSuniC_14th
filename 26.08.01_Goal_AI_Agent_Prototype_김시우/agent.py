"""공정 품질 통합 관리 AI Agent — v3 (스펙 경계까지 남은 여유 기반 Health Index).

목적: "엔지니어를 대신해서 분석해주는 AI Agent"라는 프로젝트 본래 목표에 맞춰,
팀이 쌓은 지식(defect별 Health Index/실제 불량 발생 여부/미확인 이상)을 Claude API가
실제로 조회해서 질문에 자연어로 답하는지 검증하는 버전이다.

Health Index(0~100, 100이 건강)가 답하는 질문은 "다른 장비/변수 대비 몇 등인가"가
아니라 "스펙 아웃(임시 USL/LSL) 되기 전에 미리 알 수 있는가"다. 변수별로 baseline에서
스펙 경계까지 남은 여유를 다 쓴 정도로 점수를 매기고(margin 기반, 가중치 없음),
defect/장비 단위로는 "여러 원인 중 제일 나쁜 것"을 그대로 대표값으로 쓴다(평균 아님).
(26.08.06) margin만으로는 "추세는 나쁜데 아직 값은 안 벗어난" 사각지대가 있어서
(예: 방금 CUSUM 경보가 뜬 변수가 margin만 보면 100점으로 표시됨), early_warning_active가
true인 변수는 레벨 점수에 (1 - 0.5×maturity) 배율을 곱한다(단 이미 SPEC_OUT이면 안 깎음)
— maturity는 이 경보가
alert_since부터 며칠째 지속 중인지를 14일 기준으로 0~1로 정규화한 값. 막 뜬 경보는
거의 안 깎이고 14일 이상 지속된 "성숙한" 경보라야 최대 50%까지 깎인다 — 그래서
health_index 자체가 이미 추세(그것도 얼마나 오래 확인된 추세인지)를 어느 정도 반영한
값이다(margin과 완전히 같은 게 아님). 그 위에 "이 속도면 예상 며칠 뒤 관리한계 도달"이라는
정량 추정치(estimated_days_to_control_limit)를 별도로 더 준다. 자세한 계산 로직은
build_health_index.py 상단 docstring 참고.

get_machine_health가 반환하는 구조 핵심:
  - health_index: 장비/defect/원인변수 3단계 모두 있음. **0~100이고 낮을수록 급하다.**
    (26.08.08 의미 변경) 아래쪽 10점은 **"Shewhart 관리한계(정상값 ± 3시그마) 초과"**
    전용 구간이다 — **"스펙아웃"이 아니다.** 100점은 정상값에 정확히 있다는 뜻.
    스펙 위반은 spec_status로만 판단하라(현재 전 장비 OK).
  - worst_defects / worst_factors: 나쁜 순서로 정렬된 목록 (1개만 보지 말 것).
    worst_defects에는 **장비 점수에 반영되는 defect만** 들어간다 — 감시 데이터에서
    원인 관계가 재현 검증 안 된 defect(현재 Chipping)는 defect_signals에는 있지만
    worst_defects에서 빠진다. counts_toward_machine_score / not_scored_reason 참고.
  - current_value / lsl / usl / spec_status: 추상적 %가 아니라 실제 값 — spec_status가
    "SPEC_OUT"이면 이미 스펙을 벗어난 것, "OK"면 아직 스펙 안
  - control_lsl / control_usl: **점수를 내는 선** — Shewhart 관리한계(정상값 ± 3시그마).
    margin_used_pct 100%가 여기다. 편측 변수(위험 방향이 하나)는 반대쪽이 null이다.
  - lsl / usl: 멘토 실측 스펙(10개 변수만). **점수 기준이 아니라 사람이 읽는 절대
    기준이다.** 둘이 크게 다를 수 있으니 섞어 말하면 안 된다 — 예: DP02 Laser_Power는
    현재 18.44 / 스펙 하한 17.80이라 여유가 많아 보이지만 관리한계 18.25 기준으로는
    24%를 쓴 상태다.
  - spec_source: 표시용 lsl/usl이 어디서 왔는지. "mentor_spec"으로 시작하면 멘토 스펙이
    있는 변수(40개), "control_limit_3sigma"면 스펙이 없어 관리한계만 있는 변수다.
    **진짜 스펙 위반은 spec_status가 "SPEC_OUT"일 때뿐이고, 현재 전 장비 OK다.**
  - defect_zone_rate_pct / defect_zone_baseline_pct: C유형 5개(CLN_Pressure/
    Surface_Roughness/CLN_Flow/Laser_Power/Coating_Thickness)에만 값이 있고 나머지는 null. **점수 근거가 아니라 참고
    지표다** — 하루 280샷이라 비율이 정밀하게 측정돼서 작은 변화도 큰 숫자로 보이므로,
    심각도를 이 값으로 말하면 과장된다. 예: 7.53%(평소 6.13%)면 "평소보다 위험구간 진입이 늘었다"는 뜻.
    평소 비율은 **그 장비 자신의 이력** 기준이다(CLN_Flow처럼 특정 장비에서만 일어나는
    현상을 4대 평균과 비교하면 왜곡되기 때문) — "다른 장비 대비"로 설명하면 안 됨.
  - estimated_days_to_control_limit: margin 기울기로 추정한 **관리한계 도달 예상일**
    (26.08.11에 estimated_days_to_spec_out에서 개명 — 8/8에 기준선이 3σ 관리한계로
    바뀌면서 의미가 달라졌는데 이름만 남아 있었고, 이 프롬프트가 그 이름을 보고
    "스펙아웃"이라고 답하게 만들고 있었다). 나빠지는 중일 때만 값이
    있고, 안정적이거나 좋아지는 중이거나 이미 관리한계를 넘었으면 null. 표본이 작아 숫자 자체보다 "며칠 단위/몇 주 단위" 정도의
    감으로만 말할 것.
  - trend_direction / early_warning_active / trend_message: estimated_days_to_control_limit과
    다른 스크립트(trend_analysis.py, 김시우 팀원 작성)가 WINDOW=10 롤링+지속성 필터로
    따로 검증해서 내린 판정. early_warning_active가 true면 "지금 공식적으로 추세
    경보가 켜져 있다"는 뜻이고, 이미 health_index 점수 자체에 alert_active_days
    비례 배율로 반영돼 있다(위 문단 참고, 막 뜬 경보면 거의 안 깎임) — 그래도
    margin_used_pct(레벨)이 아직 낮은데 health_index가 상대적으로 높게 나오면
    "레벨(값 자체)은 아직 여유 있지만 추세분석 쪽에서 지속적인 이상이 잡혀서 점수에
    반영됐다"고 근거를 같이 설명할 것. trend_message에 사람이
    읽는 설명이 이미 들어있으니 그대로 인용해도 됨.
    단, trend_message는 최근 경고 "1건"의 예시일 뿐이라 특정 Product/Recipe를 언급해도
    그게 대표 원인이라는 뜻은 아님 — 어느 조합이 문제인지는 recipe_hotspots를 봐야 함.
  - alert_since / alert_active_days: early_warning_active가 true일 때만 값이 있음 —
    지금 켜져 있는 경보가 "언제부터" 이어지고 있는지(며칠째인지). "추세 경보가 켜져
    있다"고만 말하지 말고 반드시 이 날짜/일수를 같이 언급할 것(예: "2/13부터 23일째
    지속 중"). 매일 새로 알림이 뜨는 게 아니라 이 시작일 기준 하나의 사건이 계속되고
    있다는 뜻이므로, 어제도 오늘도 물어봤다고 "새로 발생했다"고 말하면 안 됨.
  - recipe_hotspots / n_product_recipe_combos_affected / recipe_hotspot_concentrated:
    "어느 설비가 문제인지"는 machine_id 자체가 답이지만, "어느 제품/레시피 조합이
    문제인지"는 이 필드가 답한다(전체 54개 Product×Recipe 조합 중 경고가 집중된 순위,
    build_health_index.py의 load_trend_warning_status가 trend_analysis_results.csv에서
    직접 집계). recipe_hotspot_concentrated가 true면 top1 조합이 조합당 평균의 2배 이상
    — 특정 Product/Recipe 조합을 점검 대상으로 콕 집어 말해도 된다. false면 거의 모든
    조합(n_product_recipe_combos_affected로 몇 개인지 확인)에 고르게 퍼진 것이니
    "특정 레시피 문제가 아니라 설비/공정 전반의 문제"라고 말할 것 — recipe_hotspots에
    숫자가 있어도 그걸 "이 레시피가 원인"이라고 단정하면 안 됨.
  - actual_occurred_recent_7d: Health Index와 완전히 별개 — 이미 터진 불량 여부

데이터 출처: 26.08.01_Goal5_HealthIndex_Dashboard_김시우/health_index_data.json
(같은 폴더의 build_health_index.py가 생성. 관계DB가 커지면 get_defect_causes/
get_sop_for_factor만 그걸 읽도록 바꾸면 되고 에이전트 구조 자체는 안 바뀐다.)

실행 전 준비:
  1. pip install anthropic   (이미 설치됨)
  2. 터미널에서: export ANTHROPIC_API_KEY="본인 키"
  3. python3 agent.py "DP03 상태 어때?"
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import anthropic
import pandas as pd
from anthropic import beta_tool

HERE = Path(__file__).resolve().parent
GOAL5_DIR = HERE.parent / "26.08.01_Goal5_HealthIndex_Dashboard_김시우"
REL_DB = HERE.parent / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma"
HEALTH_INDEX_DATA = GOAL5_DIR / "health_index_data.json"
LEVEL_TREND_CSV = GOAL5_DIR / "01_level_trend_by_machine_column.csv"
DAILY_SERIES_CSV = HERE.parent / "analysis_outputs" / "preprocessing" / "00_machine_daily_series.csv"
DAILY_TREND_CSV = HERE.parent / "analysis_outputs" / "05_machine_daily_trend.csv"

with open(HEALTH_INDEX_DATA, encoding="utf-8") as f:
    DATA = json.load(f)

MACHINES = DATA["machines"]
# 26.08.06 관계DB(JHdaimma) 2세대 판정(T1~T4 티어)으로 교체.
# (26.08.08) 이 파일에는 최상위 키가 12개 있는데 cause_factors 하나만 읽고 있었다.
# build_health_index.py는 같은 날 고쳤는데 여기를 빠뜨려서, get_defect_causes("Particle")이
# CLN_Flow를 돌려주고 있었다 — DB가 per_defect["Particle"].alert_usable=False로 막아둔
# 바로 그 짝이고(risk_ratio 0.80), 진짜 감시 인자인 Surface_Roughness는 monitor_factors에
# 있어서 아예 안 보였다. 두 키를 합치고 per_defect 플래그를 존중한다.
with open(REL_DB / "agent_cause_factors.json", encoding="utf-8") as f:
    _REL_DB_JSON = json.load(f)
CAUSE_FACTORS = {**_REL_DB_JSON["cause_factors"], **_REL_DB_JSON.get("monitor_factors", {})}
DEFECTS_WITHOUT_CAUSE = _REL_DB_JSON.get("defects_without_confirmed_cause", {})
LEVEL_TREND = pd.read_csv(LEVEL_TREND_CSV)
DAILY_SERIES = pd.read_csv(DAILY_SERIES_CSV)
DAILY_TREND = pd.read_csv(DAILY_TREND_CSV)  # 전체 89일 기준 defect rate — 실제 발생 날짜 조회용

DEFECT_RATE_COLS = {
    "Particle": "Particle_rate",
    "Remain_Coat": "Remain_Coat_rate",
    "Micro_Crack": "Micro_Crack_rate",
    "Chipping": "Chipping_rate",
}

# defect -> 그 defect의 원인으로 확정된 factor 목록 (역인덱스).
# per_defect[defect].alert_usable=False인 짝은 제외한다 — 인자 레벨 플래그만 보면
# CLN_Flow↔Particle처럼 DB가 "이 경계값으로 경보를 걸면 안 됨"이라고 적어둔 짝이 통과한다.
DEFECT_TO_FACTORS: dict[str, list[str]] = {}
for factor, meta in CAUSE_FACTORS.items():
    per = meta.get("per_defect") or {}
    for defect in meta["defects"]:
        if per.get(defect, {}).get("alert_usable", meta.get("alert_usable", True)):
            DEFECT_TO_FACTORS.setdefault(defect, []).append(factor)

# factor -> 그래프에 같이 그릴 defect **목록**. (26.08.10) 원인 변수의 추세만 보여주면
# "그래서 불량이 실제로 늘었냐"에 답이 안 된다 — 원인이 꺾인 시점과 불량률이 올라간
# 시점을 한 화면에 겹쳐야 선후관계가 보인다.
#
# (26.08.11) 예전엔 dict[str, str]이라 인자당 defect 하나만 남았고, DEFECT_TO_FACTORS를
# 뒤집어 만드느라 alert_usable=False인 짝이 통째로 빠졌다. 그 결과 CLN_Flow가
# "원인 → Remain_Coat"로만 나왔다. 두 가지가 문제였다:
#
#   1. 한 원인이 두 불량을 일으키는 경우를 화면이 표현하지 못한다. 멘토 확정 시나리오가
#      정확히 그것이다 — "DP04 = Cleaning Failure -> CLN_Flow 감소 -> Remain_Coat /
#      Particle 증가". 절반만 보여주고 있었다.
#   2. alert_usable=False를 "관계 없음"으로 읽었는데, DB가 막은 건 **경계값**이다.
#      CLN_Flow↔Particle은 tier=T2(조건부조치)로 관계가 인정돼 있고, 붙은 경고는
#      "위험구간 불량률이 정상구간보다 낮음 — 이 경계값으로 경보를 걸면 안 됨"이다
#      (risk_ratio 0.80). 즉 "9.722를 넘었으니 파티클 경보"라고 말하지 말라는 것이지
#      "CLN_Flow가 나빠져도 파티클과 무관하다"가 아니다.
#
# 그래서 여기서는 meta["defects"]를 그대로 싣되, 경보/경계값 용도인 DEFECT_TO_FACTORS는
# 위에서 계속 alert_usable로 걸러진 채로 둔다. 점수(Health Index)도 안 건드린다 —
# defect 건강도는 build_health_index.py가 _usable_defects로 따로 판단한다.
#
# 이 목록은 "이 변수가 나빠지면 어떤 불량이 생길 수 있는가"를 이름으로 말하는 데만 쓴다.
FACTOR_TO_DEFECTS: dict[str, list[str]] = {
    factor: list(meta.get("defects") or [])
    for factor, meta in CAUSE_FACTORS.items()
}


def paired_defects(factor: str) -> list[str]:
    """이 인자의 하류 defect 목록 — 불량률을 그래프에 겹쳐 그릴 대상."""
    return [d for d in FACTOR_TO_DEFECTS.get(factor, []) if d in DEFECT_RATE_COLS]


def alert_usable_pair(factor: str, defect: str) -> bool:
    """이 (인자, defect) 짝의 **경계값으로 경보를 걸어도 되는가**.

    이름을 부르는 것(paired_defects)과 경보를 거는 것은 다른 권한이다 — 위 주석 참고.
    """
    meta = CAUSE_FACTORS.get(factor) or {}
    per = meta.get("per_defect") or {}
    return bool(per.get(defect, {}).get("alert_usable", meta.get("alert_usable", True)))

# get_trend_chart_data가 이번 턴에 만든 차트 데이터를 전부 담아둔다(리스트 — "Vibration을
# 4개 장비 다 보여줘"처럼 한 턴에 여러 번 호출될 수 있다). tool_runner는 최종 텍스트만
# 돌려주기 때문에, 그래프용 원시 데이터는 별도로 꺼내 화면에 넘겨야 한다.
# 주의: 프로토타입이라 전역 변수로 처리 — 동시에 여러 요청이 들어오면(멀티유저) 꼬일 수
# 있다. 데모용 단일 사용자 흐름 전제.
_chart_calls_this_turn: list = []

# get_machine_health가 이번 턴에 조회한 장비 스냅샷을 전부(장비ID별로) 담아둔다 — 대시보드
# 1/2번 패널을 Claude의 답변 문장을 파싱하지 않고 이 원본 JSON에서 직접, 결정론적으로 만들기
# 위함이다. "몇 등이야"처럼 배경 계산으로 여러 장비를 조회할 수도 있어서 딕셔너리로 전부
# 쌓아두고, 실제 패널을 무엇으로 채울지는 질문 문장에 실제로 언급된 장비 개수로 판단한다
# (아래 _build_panels 참고) — 마지막 호출만 남기면 "DP01 vs DP04"처럼 여러 장비를 비교하는
# 질문에서 마지막 장비 것으로 덮어써지는 문제가 있었다.
_machine_snapshots_this_turn: dict = {}


@beta_tool
def get_machine_health(machine_id: str) -> str:
    """특정 장비의 defect별 원인변수 레벨/추세, 실제 불량 발생 여부, 미확인 이상을 조회한다.

    Args:
        machine_id: 장비 ID, 예: "DP01", "DP02", "DP03", "DP04".
    """
    machine_id = machine_id.upper().strip()
    snap = MACHINES.get(machine_id)
    if not snap:
        return f"'{machine_id}'에 대한 데이터를 찾을 수 없음. 유효한 장비 ID: {', '.join(MACHINES.keys())}."
    result = {"machine_id": machine_id, **snap}
    _machine_snapshots_this_turn[machine_id] = result
    return json.dumps(result, ensure_ascii=False, indent=2)


@beta_tool
def get_defect_causes(defect_name: str) -> str:
    """특정 defect(불량)의 팀이 확정한 원인 변수(유효인자)와 메커니즘을 조회한다.

    Args:
        defect_name: 불량 이름, 예: "Particle", "Remain_Coat", "Chipping", "Micro_Crack".
    """
    factors = DEFECT_TO_FACTORS.get(defect_name)
    if not factors:
        known = ", ".join(sorted(DEFECT_TO_FACTORS.keys()))
        return f"'{defect_name}'에 대한 확정 유효인자가 없음. 조회 가능한 defect: {known}"

    details = []
    for f in factors:
        meta = CAUSE_FACTORS[f]
        details.append({
            "factor": f,
            "direction": meta["direction"],
            "mechanism": meta["mechanism"],
            "source": meta["owner"],
        })
    return json.dumps({"defect": defect_name, "confirmed_causes": details}, ensure_ascii=False, indent=2)


@beta_tool
def get_sop_for_factor(factor_name: str) -> str:
    """특정 원인 변수(유효인자)의 조치 긴급도(tier/action_type)와 위험 구간을 조회한다.

    (26.08.06) 관계DB agent_rules에 "SOP는 아직 수령하지 않았다. 조치 문구를 지어내지 말 것"이
    명시돼 있다 — agent_cause_factors.json의 sop.status가 "SOP 미수령"이기 때문이다. 그래서
    이 도구는 구체적인 점검/조치 "문구"를 만들어내지 않는다. 대신 이미 검정으로 확정된 것만
    준다: tier(T1/T2)와 action_type(즉시조치/조건부조치/급락알람 등 — 이건 SOP 문구가 아니라
    통계 검정 결과로 정해진 긴급도 분류라 지어낸 게 아님), 그리고 실제 위험/정상 구간 값.

    Args:
        factor_name: 원인 변수 이름, 예: "Head_Temp", "CLN_Pressure".
    """
    meta = CAUSE_FACTORS.get(factor_name)
    if not meta:
        known = ", ".join(sorted(CAUSE_FACTORS.keys()))
        return f"'{factor_name}'는 확정 유효인자가 아님. 조회 가능한 인자: {known}"
    return json.dumps({
        "factor": factor_name,
        "tier": meta.get("tier"),
        "action_type": meta.get("action_type"),
        "normal_range": meta.get("normal_range"),
        "risky_range": meta.get("risky_range"),
        "risk_ratio": meta.get("risk_ratio"),
        "sop_status": "SOP 미수령 — 멘토 제공 대기",
        "note": "구체적인 점검·조치 문구는 아직 없음. action_type(긴급도)과 위험구간만 전달하고, "
                "세부 조치 방법을 지어내지 말 것.",
    }, ensure_ascii=False, indent=2)


DEFAULT_CHART_DAYS = 30  # 경보가 없는(= 볼 사건이 없는) 변수의 기본 창. 최근 한 달.

# (26.08.10) 경보가 있으면 **경보 시작 시점이 창 안에 들어오도록** 창을 자동으로 넓힌다.
# 최근 30일 고정이면 정작 값이 꺾인 순간이 잘려나간다 — DP02 Laser_Power는 2/2,
# DP03 Head_Temp는 2/17, DP04 CLN_Flow는 2/19에 경보가 시작되는데 화면은 3/1부터였다.
# 그래서 "이미 나빠진 뒤의 평평한 구간"만 보이고, 정작 조기탐지를 그림으로 증명할 수가
# 없었다. 경보 시작 **전**의 정상 구간도 이만큼 같이 보여줘야 "꺾였다"가 눈에 보인다.
PRE_ALERT_CONTEXT_DAYS = 14


@beta_tool
def get_defect_occurrence_dates(machine_id: str, defect_name: str) -> str:
    """특정 장비에서 특정 defect가 실제로 발생한 날짜를 전체 기간(89일) 기준으로 조회한다.

    "언제 불량 났었어?", "불량 난 구간 보여줘"처럼 실제 발생 시점을 알아야 할 때 먼저
    이 도구로 날짜를 찾고, 그 다음 get_trend_chart_data를 center_date와 함께 호출해서
    그 주변 그래프를 보여준다. Particle/Remain_Coat처럼 거의 매일 발생하는 defect는
    날짜가 아주 많이 나올 수 있다 — Chipping/Micro_Crack처럼 희귀한 defect에 특히 유용.

    Args:
        machine_id: 장비 ID.
        defect_name: 불량 이름 (Particle/Remain_Coat/Micro_Crack/Chipping).
    """
    machine_id = machine_id.upper().strip()
    rate_col = DEFECT_RATE_COLS.get(defect_name)
    if not rate_col:
        return f"'{defect_name}'는 알 수 없는 defect. 가능한 값: {', '.join(DEFECT_RATE_COLS.keys())}"

    sub = DAILY_TREND[(DAILY_TREND["Machine_ID"] == machine_id) & (DAILY_TREND[rate_col] > 0)]
    if sub.empty:
        return f"{machine_id}에서 {defect_name}가 전체 기간 중 발생한 적 없음."
    dates = sorted(sub["date"].tolist())
    return json.dumps({
        "machine_id": machine_id,
        "defect": defect_name,
        "occurrence_dates": dates,
        "occurrence_count": len(dates),
    }, ensure_ascii=False)


@beta_tool
def get_trend_chart_data(
    machine_id: str, factor: str, days: int | None = None, center_date: str | None = None,
) -> str:
    """특정 장비×변수의 추세를 그래프로 보여달라는 요청일 때 시계열 데이터를 조회한다.

    사용자가 "그래프로 보여줘", "추세 그려줘"처럼 시각적으로 보고 싶어할 때만 호출한다.
    반환값에는 baseline/LSL/USL 기준선과 날짜별 실측값이 들어있어, 화면에서 바로
    선그래프로 그릴 수 있다. factor는 CAUSE_FACTORS(현재 6개)뿐 아니라 전체 연속형
    변수 아무거나 가능하다(안전망 대상 포함).

    Args:
        machine_id: 장비 ID, 예: "DP01", "DP02", "DP03", "DP04".
        factor: 변수 이름, 예: "Head_Temp", "Laser_Power", "CLN_Flow".
        days: 최근 며칠치를 보여줄지. **비워두는 게 기본이고 권장값이다** — 비우면
            경보가 있는 변수는 경보 시작 14일 전부터 지금까지를 자동으로 잡아준다
            (값이 꺾인 순간이 화면에 들어와야 추세가 보인다). 경보가 없으면 최근 30일.
            사용자가 "최근 일주일만", "전체 기간 다"처럼 명시적으로 요청할 때만
            지정한다(예: 7, 89). center_date를 쓸 때는 이 값이 그 날짜 앞뒤로 며칠씩
            볼지를 뜻한다(예: days=7이면 앞뒤 3일씩 총 7일 근방).
        center_date: "YYYY-MM-DD" 형식. "불량 난 구간 보여줘"처럼 특정 시점 주변을
            보고 싶을 때 지정 — get_defect_occurrence_dates로 먼저 날짜를 찾은 뒤 여기
            넘기면 된다. 지정 안 하면(기본) 오늘 기준 최근 days일을 보여준다.
    """
    machine_id = machine_id.upper().strip()
    spec_row = LEVEL_TREND[(LEVEL_TREND["Machine_ID"] == machine_id) & (LEVEL_TREND["column"] == factor)]
    if spec_row.empty:
        known = ", ".join(sorted(LEVEL_TREND["column"].unique()))
        return f"'{machine_id}'/'{factor}' 조합을 찾을 수 없음. 조회 가능한 변수: {known}"

    series = DAILY_SERIES[(DAILY_SERIES["Machine_ID"] == machine_id) & (DAILY_SERIES["column"] == factor)]
    series = series.sort_values("date")
    spec = spec_row.iloc[0]

    # days를 안 받았으면(기본) 경보 시작 시점이 창 안에 들어오게 자동으로 잡는다.
    # 호출자가 명시적으로 준 값은 그대로 존중한다 — "최근 일주일만" 같은 요청이 있다.
    auto_days = days is None
    if auto_days:
        days = DEFAULT_CHART_DAYS
        alert_since = spec["alert_since"]
        if pd.notna(alert_since) and len(series):
            # span은 두 날짜의 "간격"이라 경보일 당일이 안 세어진다(2/19~3/30 = 39일이지만
            # 행 수는 40개). +1을 빼먹으면 경보 전 구간이 14일이 아니라 13일이 된다.
            span = (pd.to_datetime(series["date"].iloc[-1]) - pd.Timestamp(alert_since)).days
            days = max(days, span + 1 + PRE_ALERT_CONTEXT_DAYS)

    if center_date:
        center = pd.Timestamp(center_date)
        half = max(days, 2) // 2
        dates = pd.to_datetime(series["date"])
        series = series[(dates >= center - pd.Timedelta(days=half)) & (dates <= center + pd.Timedelta(days=half))]
    else:
        series = series.tail(max(days, 2))

    result = {
        "machine_id": machine_id,
        "factor": factor,
        "baseline_median": float(spec["baseline_median"]),
        # 편측 컬럼(증가만 나쁘거나 감소만 나쁜 변수)은 반대쪽 한계가 없다 — None으로
        # 내보내야 화면이 "정상값 자리에 한계선"을 그리지 않는다(26.08.10).
        "lsl": float(spec["lsl"]) if pd.notna(spec["lsl"]) else None,
        "usl": float(spec["usl"]) if pd.notna(spec["usl"]) else None,
        # (26.08.10) **점수를 실제로 내는 선**. lsl/usl은 멘토 스펙이 있으면 스펙을 담고
        # 있어서 그래프에 그리면 화면과 점수의 기준이 어긋난다 — DP03 Head_Temp는
        # 스펙 38~47 한복판(42.16)에 있어 그래프상 안전해 보이지만, 관리상한은 42.9156이라
        # HI가 50.8이다. 진짜 경계선이 안 그려지면 "그래프는 멀쩡한데 왜 50점이냐"에
        # 답할 수가 없다. 두 선을 다 실어서 화면에서 구분해 그린다.
        "control_lsl": float(spec["control_lsl"]) if pd.notna(spec["control_lsl"]) else None,
        "control_usl": float(spec["control_usl"]) if pd.notna(spec["control_usl"]) else None,
        # (26.08.10) 관리한계는 양쪽 다 그리되, 점수를 내는 건 위험한 쪽뿐이다.
        # 어느 쪽인지 안 알려주면 화면이 CLN_Flow의 위쪽 선을 "넘으면 위험"으로
        # 오해한다 — 유량이 늘어나는 건 위험이 아니다. upper/lower/both.
        "score_side": spec["score_side"] if pd.notna(spec["score_side"]) else "both",
        # (26.08.06 추가) 실제로 경보를 결정하는 선. lsl/usl은 이 공정의 자연 변동폭보다
        # 훨씬 넓어서 데이터에서 수십 시그마 떨어져 있고(멘토 스펙 9개 중 7개가 89일 내내
        # 위반 0건), 경보를 내는 건 CUSUM이다. 화면에서 y축을 lsl~usl에 맞추면 실제 등락이
        # 직선으로 뭉개지므로, 데이터 근처에 있는 이 선을 대신 기준으로 쓸 것.
        # 값이 없을 수도 있다(C유형/방향이 한쪽뿐인 A유형의 반대쪽).
        "cusum_alert_lower": float(spec["cusum_alert_lower"]) if pd.notna(spec["cusum_alert_lower"]) else None,
        "cusum_alert_upper": float(spec["cusum_alert_upper"]) if pd.notna(spec["cusum_alert_upper"]) else None,
        "spec_source": spec["spec_source"],
        "spec_status": spec["spec_status"],
        "trend_direction": spec["trend_direction"] if pd.notna(spec["trend_direction"]) else None,
        "early_warning_active": bool(spec["early_warning_active"]),
        "trend_message": spec["trend_message"] if pd.notna(spec["trend_message"]) else None,
        "alert_since": spec["alert_since"] if pd.notna(spec["alert_since"]) else None,
        "alert_active_days": float(spec["alert_active_days"]) if pd.notna(spec["alert_active_days"]) else None,
        "series": [
            {"date": d, "value": v}
            for d, v in zip(series["date"], series["daily_mean"])
        ],
    }

    # (26.08.10) 이 인자가 원인인 defect의 실제 불량률을 같은 날짜 축으로 붙인다.
    # 원인 변수만 보여주면 "그래서 불량이 실제로 늘었냐"에 답이 안 된다 — 원인이 꺾인
    # 시점과 불량률이 올라간 시점이 한 화면에 겹쳐야 선후관계가 보인다.
    # 스케일이 완전히 다르므로(유량 9.99 vs 불량률 0.0x) 화면에서 별도 축으로 그린다.
    #
    # (26.08.11) 하류 defect가 여러 개면 **전부** 겹쳐 그린다. 예전엔 하나만 그려서
    # CLN_Flow 그래프에 Remain_Coat만 나왔는데, 세정 실패는 Remain_Coat와 Particle을
    # 같이 올린다(멘토 확정). 둘을 같은 날짜 축에 겹쳐야 "한 원인이 두 불량을 민다"가
    # 눈으로 보인다 — 이건 경계값을 쓰는 주장이 아니라 실측 불량률을 나란히 놓는 것이다.
    dates = [str(d) for d in series["date"]]
    sub = DAILY_TREND[DAILY_TREND["Machine_ID"] == machine_id]
    defects_out = []
    for d_name in paired_defects(factor):
        rate_col = DEFECT_RATE_COLS.get(d_name)
        if not rate_col or rate_col not in DAILY_TREND.columns:
            continue
        rate_by_date = dict(zip(sub["date"].astype(str), sub[rate_col]))
        pairs = [(dt, rate_by_date.get(dt)) for dt in dates]
        if not any(v is not None and pd.notna(v) for _, v in pairs):
            continue
        defects_out.append({
            "defect": d_name,
            # 경계값 경보를 걸 수 있는 짝인지 — 화면이 선을 그릴지 판단하는 데 쓴다.
            # False라도 실측 불량률은 그린다(관계는 tier로 인정돼 있고, 막힌 건 경계값뿐).
            "alert_usable": alert_usable_pair(factor, d_name),
            "series": [
                {"date": dt, "value": (float(v) if v is not None and pd.notna(v) else None)}
                for dt, v in pairs
            ],
        })
    if defects_out:
        result["defects"] = defects_out
        # 하위호환: 기존 소비자가 읽던 단수 키를 첫 번째(경보 가능한 짝 우선)로 유지한다.
        primary = next((x for x in defects_out if x["alert_usable"]), defects_out[0])
        result["defect"] = primary["defect"]
        result["defect_series"] = primary["series"]

    _chart_calls_this_turn.append(result)
    return json.dumps({**result, "series_length": len(result["series"])}, ensure_ascii=False)


SYSTEM_PROMPT = """\
너는 SK하이닉스 HBM 다이싱 공정의 "공정 품질 통합 관리 AI Agent"다. \
엔지니어가 직접 데이터를 뒤지지 않아도, 오늘 뭘 먼저 봐야 하는지·원인·조치를 대신 조회해서 알려주는 게 \
네 역할이다. **답변은 엔지니어가 3초 안에 훑을 수 있는 간결한 구조여야 한다 — 설명 문단을 늘어놓지 말고 \
아래 출력 형식을 그대로 따라라.**

원칙:
1. 반드시 도구를 호출해서 실제 데이터를 확인한 뒤에 답하라. 데이터 없이 추측하지 마라.
2. 장비 상태를 물으면(get_machine_health 호출 후) 아래 형식을 그대로 따르고, 값이 채워지는 \
   부분만 실제 데이터로 바꿔라. defect 순서는 worst_defects(나쁜 순서) 그대로.
   **화면 렌더러는 마크다운 중 딱 5가지만 지원한다: `### 헤더`, `**볼드**`, `` `코드` ``(숫자·값에 \
   써서 칩처럼 보이게), `- 목록`, `| 표 |`. 이탤릭·인용구·중첩목록 등 그 외 문법은 화면에 그대로 \
   글자로 노출되니 절대 쓰지 마라.**

--- 출력 형식 ---
### {장비ID} 종합 상태 (기준일 `{latest_date}`)

### {actual_occurred_recent_7d가 true면 "🔴" / false이고 early_warning_active가 true면 "🟡" / \
그 외 "⚪"} {N}순위 - {defect} (HI `{health_index}`)
- **발생**: {actual_occurred_recent_7d가 true면 "최근 7일 내내(7/7)" 또는 "{occurred_days_recent_7d}/7일" \
| false면 "없음(조짐 단계)"}
- **원인**: `{worst_factors[0]의 factor}` — 현재 `{current_value}` / \
  {direction이 up이면 "관리상한" down이면 "관리하한"} `{control_usl 또는 control_lsl}` \
  {멘토 스펙이 있으면(spec_source가 mentor_spec으로 시작) 뒤에 "(멘토 스펙 `{usl 또는 lsl}`)"를 붙여라}
  **점수는 전부 Shewhart 관리한계(정상값 ± 3σ) 기준이다.** lsl/usl(멘토 스펙)이 아니라 \
  control_lsl/control_usl을 인용하라 — 둘이 크게 다르다(DP02 Laser_Power는 현재 18.44 / \
  스펙 하한 17.80이라 여유가 많아 보이지만 관리한계 18.25 기준으로는 24%를 쓴 상태다). \
  margin_used_pct 100%는 "스펙아웃"이 아니라 "관리한계 도달"이니 스펙아웃이라고 쓰지 마라 — \
  진짜 스펙 위반은 spec_status가 SPEC_OUT일 때뿐이고 현재 전 장비 OK다.
  defect_zone_rate_pct가 null이 아니면(C유형) 위 한 줄 뒤에 \
  ", 위험구간 진입 `{defect_zone_rate_pct}`% (평소 `{defect_zone_baseline_pct}`%)"를 덧붙여라 \
  — 이건 점수 근거가 아니라 참고 지표다.
   공통: {trend_direction이 up이면 "상승" down이면 "하강" 아니면 생략}추세{estimated_days_to_control_limit이 \
null이 아닐 때만 ", 관리한계 도달 예상 `{N}일`"을 붙여라 — null이면 이 구절을 통째로 빼고, 숫자를 \
절대 지어내지 마라}{early_warning_active가 true면 반드시 ", `{alert_since}`부터 `{alert_active_days}일`째 \
경보 지속"을 붙여라 — 매일 새로 뜬 게 아니라 하나의 사건이 이어지고 있다는 뜻이니 날짜를 빼면 안 된다}
- **메커니즘**: {mechanism을 화살표(→) 형식 한 줄로 압축}
- **조치**: get_sop_for_factor 호출 후 `{action_type}`(tier `{tier}`) `[SOP 미수령]` — \
위험구간 `{risky_range}` 참고. **구체적 점검·조치 문구는 아직 없으니 지어내지 말고, \
tier/action_type과 위험구간 숫자만 전달하라.**

(worst_defects 중 상위 1~2개만 위 `###` 헤더+4개 불릿 블록으로 쓰고, 그 아래 순위부터는 \
헤더 없이 불릿 한 줄로: `- **{N순위}** {defect} (HI {값}) [발생/미발생] — {worst_factor} {한 줄 사유}`)

defect_signals 중 counts_toward_machine_score가 false인데 원인 인자에 early_warning_active가 \
있으면, 순위 목록 **아래에 따로** 이렇게 쓴다(순위에 섞지 마라 — 장비 점수에 안 들어간 항목이다):
### 예방 정비 대상 (장비 점수 미반영)
- `{factor}` {alert_active_days}일째 경보 — {defect} 위험. {not_scored_reason}

이 구분이 중요한 이유: 감시 데이터에 그 불량이 너무 적어 "이 인자가 그 불량을 일으킨다"를 \
여기서 검증할 수 없다는 뜻이다. 관계 자체는 도메인으로 확정돼 있으니 **버리지 말고 경보로 \
전달하되, 장비 순위를 매기는 근거로는 쓰지 마라.**

unconfirmed_anomalies가 있으면 마지막에 표로:
| 인자 | 상태 |
|---|---|
| `{factor1}` | {SPEC_OUT 또는 "N일 뒤 관리한계 도달"} |

맨 끝에 한 줄만(헤더·볼드 없이 평문으로):
※ 원인은 통계적 상관관계로 확정된 것이며 완전한 인과관계 증명은 아닙니다. 구체적 SOP 문구는 아직 \
멘토로부터 받지 못한 상태입니다(action_type/tier만 확정됨).
--- 형식 끝 ---

3. defect에 확정 원인이 없으면(get_defect_causes가 "없음"이라 답하면) 원인/메커니즘/SOP 3줄 대신 \
   "원인: 확정 원인 없음 ({이유를 한 줄로})"로 대체하라.
4. 원인이 여러 개인 defect는 worst_factors[0](가장 나쁜 것) 하나만 위 형식에 쓰고, 나머지는 \
   사용자가 더 물어보면 그때 알려줘라 — 처음부터 다 나열하지 마라.
5. spec_status가 "SPEC_OUT"이면 상한/하한 대신 그냥 "SPEC_OUT"이라고만 써라. 퍼센트(%)는 절대 쓰지 마라 \
   (단, defect_zone_rate 컬럼의 defect_zone_rate_pct/defect_zone_baseline_pct는 이 규칙의 예외 — \
   그 자체가 판정 근거라 반드시 %로 표시).
5-1. health_index는 0~100이고 낮을수록 급하다. **아래쪽 10점은 "이미 스펙 밖" 전용 구간이라, \
   10점 미만이면 이미 SPEC_OUT이고 0에 가까울수록 스펙을 몇 배로 벗어난 것**이다(예: HI 3.4 = \
   경계를 3배 가까이 넘음). 10점 이상이면 아직 스펙 안이다. HI가 한 자릿수인데 "조금 낮다" 같이 \
   말하지 마라 — 그건 이미 스펙을 벗어났다는 뜻이다.
6. **장비 간 순위 비교("몇 등이야?", "다른 장비랑 비교하면?")는 사용자가 명시적으로 물어봤을 때만 \
   계산하라.** 그 전까지는 절대 "N개 장비 중 M등" 같은 문구를 먼저 붙이지 마라 — 매번 계산하면 \
   장비 4대를 다 조회해야 해서 응답이 느려진다. 명시적으로 물으면 get_machine_health를 4대 다 \
   불러서 순위를 계산해 알려줘라.
7. 사용자가 그래프/추세를 시각적으로 보여달라고 하면 get_trend_chart_data를 호출하라. 이 도구를 \
   부르면 화면 패널에 자동으로 선그래프가 그려지니, 텍스트로 수치를 다시 나열하지 말고 "그래프로 \
   보여드렸습니다"처럼 짧게 언급하고 핵심 해석만 한 줄 덧붙여라. **한 인자를 여러 장비(또는 \
   "전체 4대")에서 비교해서 보여달라고 하면, 장비마다 get_trend_chart_data를 한 번씩 따로 \
   호출해서 전부 조회하라** — 화면은 조회한 개수만큼 그래프를 나란히 보여준다(1개면 1개, \
   4개면 4분할). 개수를 미리 정하지 말고 사용자가 보고 싶어하는 만큼만 정확히 호출하라.
8. "불량 난 구간 보여줘"처럼 특정 시점 주변을 보고 싶어하면, 먼저 get_defect_occurrence_dates로 \
   실제 발생 날짜를 찾고, 그 날짜를 get_trend_chart_data의 center_date로 넘겨라. 발생일이 매우 \
   많으면(Particle/Remain_Coat) 가장 최근 날짜 하나를 골라 쓰거나 사용자에게 물어봐라.
9. "어느 제품/레시피가 문제야?"처럼 물으면(get_machine_health 결과의 causes 안에 있는) \
   recipe_hotspots를 확인해서 표로 답하라: `| 조합 | 경고건수 |` 형식. \
   recipe_hotspot_concentrated가 true면 top1 조합(product_id×recipe_id)을 "우선 점검 대상"이라고 \
   콕 집어 말하고, false면 n_product_recipe_combos_affected(예: "54개 중 54개")를 근거로 \
   "특정 레시피 문제가 아니라 설비 자체 문제"라고 명확히 말하라 — 숫자만 보고 특정 레시피를 \
   원인으로 단정하지 마라.
10. **점수 기준선은 전 변수 하나다 — Shewhart 관리한계(control_lsl/control_usl).** \
    멘토 스펙(lsl/usl)은 10개 변수에만 있고 **점수 기준이 아니다.** 둘을 섞어 말하지 마라. \
    관리한계는 "이 선을 넘으면 SPC 기준 공정 이탈", 멘토 스펙은 "이 선을 넘으면 불량품"이라 \
    뜻이 다르다. 멘토 스펙이 있으면 절대 기준으로 괄호에 같이 보여주되, "몇 % 왔는가"는 \
    항상 관리한계 기준이다.
11. 한국어로 답하되, 위 출력 형식을 벗어난 부가 설명 문단을 붙이지 마라. 사용자가 형식에 없는 걸 \
    추가로 물으면(예: SOP 상세 설명, 왜 이런 판정인지) 그 부분만 짧게 답하고 전체 형식은 유지하라.
12. **Vibration은 (26.08.06부터) 원인 후보 표에서 완전히 빠졌다** — 값을 조정해서 고칠 수 있는 \
    인자가 아니라 설비 정비 대상이라, 추세분석팀이 별도 알람 트랙으로 관리하기로 했기 때문이다. \
    Vibration은 get_defect_causes/get_sop_for_factor에 안 걸리고, get_machine_health의 \
    unconfirmed_anomalies에서만 조회된다. Vibration 관련 질문에는 "Chipping/Micro_Crack의 \
    설비 열화 알람(값 조정이 아니라 설비 점검 대상)"이라고 설명하고, "확정 원인 아님"이라는 \
    문구는 다른 미확인 이상과 똑같이 붙이지 마라 — 이건 검증 실패가 아니라 애초에 다른 트랙으로 \
    분류된 것이다.
"""


# \b(단어 경계)는 안 쓴다 — "DP01이랑"처럼 장비ID 바로 뒤에 한국어 조사가 붙으면(공백 없이)
# 파이썬 정규식의 \b가 한글도 "단어 문자"로 취급해서 경계로 인식하지 못해 매칭이 깨진다.
# 대신 앞뒤에 다른 영숫자만 없으면 되도록 lookaround로 직접 제한한다.
_MACHINE_ID_RE = re.compile(r"(?<![A-Za-z0-9_])DP0[1-4](?![0-9])", re.IGNORECASE)


def _format_cause_value_line(c: dict) -> str:
    """"원인" 줄의 값 부분 하나를 만든다.

    (26.08.08) 점수를 내는 선이 **관리한계(정상값 ± 3σ)**로 통일됐다. 예전엔 lsl/usl을
    보여줬는데, 그건 멘토 스펙이 있으면 스펙을 담고 있어서 화면 숫자와 margin의 기준이
    어긋났다 — DP02 Laser_Power는 현재 18.44 / 스펙 하한 17.80이라 여유가 많아 보이지만
    관리한계 18.25 기준으로는 24%를 쓴 상태다. control_lsl/usl(점수를 내는 선)을 쓰고,
    멘토 스펙이 따로 있으면 괄호로 덧붙여 둘 다 보이게 한다.
    """
    if c.get("defect_zone_rate_pct") is not None:
        # C유형 참고 지표. "평소"는 4대 평균이 아니라 그 장비 자신의 이력이다
        # (CLN_Flow처럼 특정 장비에서만 일어나는 현상 때문) — 화면에도 그렇게 써야
        # 엔지니어가 "다른 장비 대비"로 오해하지 않는다.
        zone_txt = (f", 위험구간 진입 `{c['defect_zone_rate_pct']}%` "
                    f"(이 장비 평소 `{c.get('defect_zone_baseline_pct')}%`)")
    else:
        zone_txt = ""
    up = c.get("direction") == "up"
    bound_label = "관리상한" if up else "관리하한"
    bound_val = c.get("control_usl") if up else c.get("control_lsl")
    if bound_val is None:  # 편측인데 그 방향 선이 없으면 반대쪽이라도 보여준다
        bound_val = c.get("control_lsl") if up else c.get("control_usl")
        bound_label = "관리하한" if up else "관리상한"
    value_part = f"현재 `{c.get('current_value')}` / {bound_label} `{bound_val}`"
    # 멘토 스펙이 있으면 절대 기준으로 같이 보여준다(점수 기준은 아니라는 걸 문구로 구분).
    spec_val = c.get("usl") if up else c.get("lsl")
    if str(c.get("spec_source", "")).startswith("mentor_spec") and spec_val is not None:
        value_part += f" (멘토 스펙 `{spec_val}`)"
    trend_word = {"up": "상승", "down": "하강"}.get(c.get("trend_direction"), "")
    trend_txt = f", {trend_word}추세" if trend_word else ""
    reach = c.get("estimated_days_to_control_limit")
    reach_txt = f", 관리한계 도달 예상 `{reach}일`" if reach is not None else ""
    alert_txt = ""
    if c.get("early_warning_active") and c.get("alert_since"):
        alert_txt = f", `{c['alert_since']}`부터 `{c.get('alert_active_days')}일`째 경보 지속"
    return f"{value_part}{zone_txt}{trend_txt}{reach_txt}{alert_txt}"


def _format_action_line(factor: str) -> str:
    """"조치" 줄 — SOP 문구를 지어내지 않고, 검정으로 확정된 tier/action_type/위험구간만
    전달한다(agent_rules: "SOP는 아직 수령하지 않았다. 조치 문구를 지어내지 말 것")."""
    try:
        sop = json.loads(get_sop_for_factor.func(factor))
        return (f"`{sop.get('action_type')}`(tier `{sop.get('tier')}`) `[SOP 미수령]` "
                f"— 위험구간 `{sop.get('risky_range')}`")
    except (json.JSONDecodeError, KeyError, TypeError):
        return "확정 조치 유형 없음(감시지표 또는 원인 미확정) `[SOP 미수령]`"


def _defect_rate_context(machine_id: str, defect: str) -> str:
    """"이 장비의 불량률이 4대 중 어느 위치인가"를 한 구절로 만든다.

    (26.08.10) "발생: 최근 7일 내내(7/7)"만 보면 심각해 보이는데, Particle은 이 공정에서
    4대 전부 매일 나는 상시 불량이다(89일 평균 6.96~8.16%). DP01은 그중 **제일 낮은데도**
    화면상 제일 위험해 보였다. 비교 기준 없이 발생 사실만 쓰면 오해를 만든다.
    """
    rate_col = DEFECT_RATE_COLS.get(defect)
    if not rate_col or rate_col not in DAILY_TREND.columns:
        return ""
    per_machine = DAILY_TREND.groupby("Machine_ID")[rate_col].mean()
    if machine_id not in per_machine.index or not len(per_machine):
        return ""

    # 상시 불량(Particle/Remain_Coat)과 희귀 불량(Chipping/Micro_Crack)은 다르게 말해야
    # 한다. Chipping은 89일 10만 샷에 4건이라 평균이 0.00%로 찍혀서, 비율로 비교하면
    # "4대 평균 0.00%, 이 장비 0.00%"라는 무의미한 문장이 된다. 그런 불량은 비율이
    # 아니라 **건수**가 정보다.
    RARE_RATE_PCT = 0.5
    n = len(per_machine)
    if per_machine.mean() * 100 < RARE_RATE_PCT:
        if "samples" not in DAILY_TREND.columns:
            return ""
        cnt = (DAILY_TREND[rate_col] * DAILY_TREND["samples"]).groupby(
            DAILY_TREND["Machine_ID"]).sum().round()
        return (f"희귀 불량 — 89일 동안 {n}대 합쳐 `{int(cnt.sum())}건`, "
                f"이 장비 `{int(cnt.get(machine_id, 0))}건`")

    mine, avg = per_machine[machine_id] * 100, per_machine.mean() * 100
    rank = int((per_machine > per_machine[machine_id]).sum()) + 1  # 1등 = 가장 나쁨
    where = "최고" if rank == 1 else ("최저" if rank == n else f"{rank}위")
    return f"이 공정 상시 발생(4대 평균 `{avg:.2f}%`), 이 장비 `{mine:.2f}%`로 {n}대 중 {where}"


def _panel_from(snapshot: dict, defect: str, factor: str, rank: int) -> dict | None:
    """장비 스냅샷 하나에서 defect/factor 하나를 골라 패널 하나(제목/그래프/설명)를 만든다.
    Claude 답변 문장을 파싱하지 않고 원본 JSON에서 직접, 결정론적으로 구성한다 — Claude의
    문구가 매번 달라져도 패널 내용은 항상 실제 데이터와 정확히 일치한다."""
    machine_id = snapshot["machine_id"]
    sig = snapshot.get("defect_signals", {}).get(defect, {})
    c = sig.get("causes", {}).get(factor)
    if c is None:
        return None  # 이 인자는 원인 상세 정보가 없음(안전망 항목 등) — 패널에서 생략

    occurred = sig.get("actual_occurred_recent_7d", False)
    hi = sig.get("health_index")

    # (26.08.10) 아이콘을 "최근 7일에 한 번이라도 났는가"가 아니라 **점수**로 정한다.
    #
    # 예전 규칙(occurred면 무조건 빨강)은 Particle처럼 매일 나는 불량에서 4대가 전부
    # 항상 7/7이라 무조건 빨강이 됐다 — DP01은 HI 91.9로 제일 건강한데 화면은
    # "🔴 DP01 Particle"이었다(김시우님 지적). 반대로 Chipping은 89일에 4건뿐이라
    # 실제로 나빠도 하얗게 떴다. 발생 빈도는 그 불량의 성질이지 심각도가 아니다.
    if hi is None:
        icon = "⚪"
    elif hi < 50:
        icon = "🔴"
    elif hi < 80:
        icon = "🟡"
    else:
        icon = "🟢"

    # 발생 줄도 마찬가지다. "7/7"은 상시 발생 불량에서 정보가 없다 — 4대 평균과
    # 비교해야 "많은 건지"를 알 수 있다. rate가 있으면 그 비교를 같이 실어준다.
    occ_txt = ("최근 7일 내내(7/7)" if sig.get("occurred_days_recent_7d") == 7
               else (f"{sig.get('occurred_days_recent_7d', 0)}/7일" if occurred
                     else "없음(조짐 단계)"))
    ctx = _defect_rate_context(machine_id, defect)
    if ctx:
        occ_txt += f" · {ctx}"
    title = f"{icon} {machine_id} · {rank}순위 - {defect} (HI `{hi}`)"
    # (26.08.08) 관계DB agent_rules 6번 "role이 감시지표인 인자에 조치를 지시하지 말 것.
    # 경보만." — Surface_Roughness처럼 actionable=false인 인자를 "원인"이라 부르면 틀린
    # 말이다(표면조도는 결과지 조정 대상이 아님). 라벨 자체를 바꿔서 오해를 막는다.
    if c.get("actionable", True):
        cause_label = "원인"
        extra = ""
    else:
        cause_label = "감시지표"
        # JHdaimma님 회신: 결과 공변이라 사후 탐지에는 유효하지만 예측에는 못 쓴다
        # (선행신호 잔존율 7.5%). 그 단서를 문구에 남긴다.
        extra = "\n- **주의**: 확정 원인 미확인 — 결과 지표로 감시 중(사후 탐지용, 예측 불가)"
    explanation_md = (
        f"- **발생**: {occ_txt}\n"
        f"- **{cause_label}**: `{factor}` {_format_cause_value_line(c)}\n"
        f"- **메커니즘**: {c.get('mechanism', '-')}\n"
        f"- **조치**: {_format_action_line(factor)}"
        f"{extra}"
    )
    try:
        chart = json.loads(get_trend_chart_data.func(machine_id, factor))
    except (json.JSONDecodeError, KeyError, TypeError):
        chart = None
    return {"title": title, "explanation_md": explanation_md, "chart": chart}


MAX_PANELS = 4  # 화면 대시보드가 감당할 수 있는 최대 분할 수


# Vibration은 26.08.06부터 원인 후보 표에서 빠지고 별도 알람 트랙(추세분석 담당)으로 운영된다
# — get_defect_causes/get_sop_for_factor로는 절대 안 걸리므로, 명시적 그래프 요청(_panel_from_chart)
# 경로에서만 만날 수 있다. 값 조정이 아니라 설비 정비 대상이라는 걸 패널에서도 명시해야 한다.
_VIBRATION_NOTE = ("설비 열화 알람 전용(Chipping/Micro_Crack 연관) — 값을 조정해서 고치는 "
                    "인자가 아니라 설비 점검 대상. \"확정 원인 아님\"이 아니라 애초에 별도 트랙")


def _panel_from_chart(chart: dict) -> dict:
    """get_trend_chart_data 결과 하나로 패널을 만든다 — 사용자가 특정 인자를 콕 집어
    그래프를 요청한 경우용. get_machine_health를 안 거쳐도 되므로, 확정 원인이면
    CAUSE_FACTORS에서 메커니즘을 덧붙이고, 조치는 SOP 문구를 지어내지 않고 tier/action_type만
    붙인다(get_sop_for_factor와 동일 원칙)."""
    factor, machine_id = chart["factor"], chart["machine_id"]
    series = chart.get("series") or []
    latest = series[-1]["value"] if series else None
    trend_word = {"up": "상승", "down": "하강"}.get(chart.get("trend_direction"), "")
    alert_txt = ""
    if chart.get("early_warning_active") and chart.get("alert_since"):
        alert_txt = f", `{chart['alert_since']}`부터 `{chart.get('alert_active_days')}일`째 경보 지속"

    # 편측 컬럼은 한쪽 한계만 존재한다 — 없는 쪽을 "~"로 이어 쓰면 없는 선을 있는 것처럼
    # 말하게 된다(26.08.10). 있는 쪽만 이름을 붙여서 말한다.
    # 점수를 내는 선(control_*)을 먼저 말한다. 멘토 스펙(lsl/usl)은 다른 축이라
    # 괄호로 덧붙이기만 한다 — 둘을 "~"로 섞으면 어느 쪽이 점수 기준인지 사라진다.
    lo, hi_ = chart.get("control_lsl"), chart.get("control_usl")
    side = chart.get("score_side", "both")
    if lo is None and hi_ is None:
        bound_txt = "관리한계 없음"
    elif side == "upper":
        bound_txt = f"관리한계 `{lo}` ~ `{hi_}` (점수는 **상한** 기준 — 증가만 위험한 변수)"
    elif side == "lower":
        bound_txt = f"관리한계 `{lo}` ~ `{hi_}` (점수는 **하한** 기준 — 감소만 위험한 변수)"
    else:
        bound_txt = f"관리한계 `{lo}` ~ `{hi_}`"
    if str(chart.get("spec_source", "")).startswith("mentor_spec"):
        bound_txt += f" · 멘토 스펙 `{chart.get('lsl')}` ~ `{chart.get('usl')}`(점수 기준 아님)"

    lines = [
        f"- **현재값**: `{latest}` (정상값 `{chart.get('baseline_median')}`), " + bound_txt
        + (f", {trend_word}추세" if trend_word else "") + alert_txt
    ]

    # 겹쳐 그린 불량률을 문장으로도 한 줄 남긴다 — 그래프를 캡처해서 붙일 때
    # 숫자가 같이 가야 한다. 경보 전/후를 나눠서 실제로 늘었는지를 보여준다.
    ds = chart.get("defect_series") or []
    since = chart.get("alert_since")
    if ds and chart.get("defect"):
        vals = [(p["date"], p["value"]) for p in ds if p.get("value") is not None]
        if vals:
            before = [v for d, v in vals if since and d < since]
            after = [v for d, v in vals if since and d >= since]
            if before and after:
                b, a = sum(before) / len(before), sum(after) / len(after)
                move = "증가" if a > b else "감소"
                lines.append(
                    f"- **실제 불량**: `{chart['defect']}` 발생률 경보 전 `{b * 100:.2f}%` "
                    f"→ 경보 후 `{a * 100:.2f}%` ({move})")
            else:
                cur = vals[-1][1]
                lines.append(f"- **실제 불량**: `{chart['defect']}` 최근 발생률 `{cur * 100:.2f}%`")
    if chart.get("trend_message"):
        lines.append(f"- **추세 메시지**: {chart['trend_message']}")

    if factor == "Vibration":
        lines.append(f"- **참고**: {_VIBRATION_NOTE}")
    else:
        meta = CAUSE_FACTORS.get(factor)
        if meta:
            lines.append(f"- **메커니즘**: {meta.get('mechanism', '-')}")
            lines.append(f"- **조치**: {_format_action_line(factor)}")

    return {"title": f"📈 {machine_id} · {factor}", "explanation_md": "\n".join(lines), "chart": chart}


def _panel_from_compare(charts: list[dict]) -> dict:
    """같은 변수를 여러 장비에서 조회했을 때 **한 그래프에 겹쳐서** 비교 패널을 만든다.

    (26.08.10) 예전엔 장비마다 패널을 따로 그려서, "이 변수에서 어느 장비가 제일 나쁜가"를
    보려면 4개의 작은 그래프를 눈으로 옮겨다니며 비교해야 했다. y축 범위도 패널마다 달라서
    실제로는 비교가 안 됐다.

    기준선(정상값/관리한계)은 장비별로 같다 — OPCOND(Product x Recipe) 층에서 잡고
    Machine_ID를 안 쓰기 때문이다. 그래서 한 세트만 그리면 되고, 그게 오히려 이 그래프의
    요점이다: **같은 자로 재서 어느 장비가 벗어났는가.**

    각 장비의 자동 창(경보 시작 14일 전~)이 서로 다르므로 날짜 합집합으로 축을 맞추고,
    없는 날은 None으로 둔다(화면에서 선을 끊는다).
    """
    factor = charts[0]["factor"]
    base = max(charts, key=lambda c: len(c.get("series") or []))  # 창이 가장 넓은 것을 기준선 출처로

    # 장비마다 자동 창이 다르다(자기 경보 시작 기준). 그대로 합치면 한 장비만 긴 선이고
    # 나머지는 25일씩 비어서 비교가 안 된다 — **가장 넓은 창으로 통일해서 원본을 다시
    # 읽는다.** 비교 그래프의 전제가 "같은 구간을 같은 자로 본다"이므로 여기서 타협하면
    # 그래프 자체가 거짓말이 된다.
    all_dates = sorted({p["date"] for c in charts for p in (c.get("series") or [])})
    lo_date, hi_date = all_dates[0], all_dates[-1]

    machines = []
    for c in sorted(charts, key=lambda c: c["machine_id"]):
        mid = c["machine_id"]
        sub = DAILY_SERIES[(DAILY_SERIES["Machine_ID"] == mid)
                           & (DAILY_SERIES["column"] == factor)]
        sub = sub[(sub["date"].astype(str) >= lo_date) & (sub["date"].astype(str) <= hi_date)]
        by_date = dict(zip(sub["date"].astype(str), sub["daily_mean"]))
        values = [(float(by_date[d]) if d in by_date and pd.notna(by_date[d]) else None)
                  for d in all_dates]
        present = [v for v in values if v is not None]
        machines.append({
            "machine_id": mid,
            "values": values,
            "current_value": present[-1] if present else None,
            "alert_since": c.get("alert_since"),
            "alert_active_days": c.get("alert_active_days"),
            "early_warning_active": c.get("early_warning_active"),
        })

    compare = {
        "factor": factor,
        "dates": all_dates,
        "machines": machines,
        "baseline_median": base.get("baseline_median"),
        "control_lsl": base.get("control_lsl"),
        "control_usl": base.get("control_usl"),
        "score_side": base.get("score_side", "both"),
        "lsl": base.get("lsl"),
        "usl": base.get("usl"),
        "spec_source": base.get("spec_source"),
    }

    # 설명은 "정상값에서 위험한 방향으로 얼마나 벗어났나" 순으로 세운다. 단순 대소가
    # 아니라 방향을 봐야 한다 — CLN_Flow는 낮을수록 나쁘고 Head_Temp는 높을수록 나쁘다.
    side, b = compare["score_side"], compare["baseline_median"]
    def deviation(m):
        v = m["current_value"]
        if v is None or b is None:
            return -1.0
        if side == "lower":
            return b - v
        if side == "upper":
            return v - b
        return abs(v - b)

    ranked = sorted(machines, key=deviation, reverse=True)
    worst = ranked[0]
    dir_word = {"lower": "낮을수록", "upper": "높을수록"}.get(side, "정상값에서 멀수록")
    lines = [
        f"- **기준**: 정상값 `{b}`, 관리한계 `{compare['control_lsl']}` ~ `{compare['control_usl']}` "
        f"— 4대 공통({dir_word} 나쁨). 기준선은 Product×Recipe 층에서 잡아 장비를 안 쓰므로 "
        f"**같은 자로 4대를 잰 것**이다.",
        # %.4g는 9.9996을 "10"으로 뭉갠다 — 비교 그래프에서 자릿수가 죽으면 순위가
        # 사라지므로 정상값과 같은 소수 자릿수(최소 4자리)로 맞춘다.
        "- **현재값**: " + " · ".join(
            f"`{m['machine_id']}` {m['current_value']:.4f}" + ("⚠️" if m.get("early_warning_active") else "")
            for m in ranked if m["current_value"] is not None),
    ]
    if deviation(worst) > 0:
        alert_txt = (f", `{worst['alert_since']}`부터 `{worst['alert_active_days']}일`째 경보"
                     if worst.get("early_warning_active") and worst.get("alert_since") else "")
        lines.append(f"- **가장 벗어난 장비**: `{worst['machine_id']}`{alert_txt}")

    meta = CAUSE_FACTORS.get(factor)
    if factor == "Vibration":
        lines.append(f"- **참고**: {_VIBRATION_NOTE}")
    elif meta:
        lines.append(f"- **메커니즘**: {meta.get('mechanism', '-')}")

    return {
        "title": f"📊 {factor} · 장비 비교 ({len(machines)}대)",
        "explanation_md": "\n".join(lines),
        "compare": compare,
    }


def _build_panels(snapshots: dict, chart_calls: list, question: str) -> list[dict] | None:
    """이번 턴에 실제로 조회된 내용으로 대시보드 패널을 만든다. 패널 개수는 항상
    고정(2개)이 아니라 실제로 조회한 개수를 그대로 따른다(최대 MAX_PANELS) — 그래프 1개를
    조회했으면 1개, "전체 4대 비교"처럼 4개를 조회했으면 4개를 4분할로 보여준다.

    우선순위: 사용자가 특정 인자 그래프를 명시적으로 요청했으면(get_trend_chart_data 호출)
    그 결과가 최우선이다. 아니면 get_machine_health 기반 1·2순위 로직으로 판단한다
    (장비 몇 개가 질문에 언급됐는지로 "무엇을 비교하려는 질문인가"를 판단 — 도구 호출
    횟수로 판단하면 "몇 등이야?" 같은 배경조회에 오염된다)."""
    if chart_calls:
        # 같은 변수를 여러 장비에서 조회했으면 쪼개지 말고 한 그래프에 겹친다 —
        # "Vibration 전체 장비 비교" 같은 질문에서 작은 그래프 4개를 눈으로 옮겨다니며
        # 비교하는 건 비교가 아니다(y축 범위도 패널마다 달라진다).
        by_factor: dict[str, list] = {}
        for c in chart_calls:
            by_factor.setdefault(c["factor"], []).append(c)
        panels = []
        for factor, group in by_factor.items():
            uniq = list({c["machine_id"]: c for c in group}.values())
            panels.append(_panel_from_compare(uniq) if len(uniq) >= 2
                          else _panel_from_chart(uniq[0]))
        return panels[:MAX_PANELS] or None

    mentioned = list(dict.fromkeys(m.upper() for m in _MACHINE_ID_RE.findall(question)))

    # (26.08.10) "4대 전부", "장비 전체", "제일 급한 장비 어디야?"처럼 장비 ID를 하나도
    # 안 부르는 질문은 패널이 0개였다 — Claude는 4대를 다 조회해서 답하는데 화면은 빈
    # 상태로 남았다. 조회한 장비가 2대 이상이면 전부 보여주는 게 맞다.
    #
    # 명시적으로 부른 장비가 있으면 그쪽이 우선이다("DP03 몇 등이야?"는 배경으로 4대를
    # 다 조회하지만 사용자가 물은 건 DP03 하나다). 다만 "전부/전체/모든/4대"처럼 범위를
    # 넓히는 말이 같이 있으면 조회된 전부로 확장한다 — "DP01부터 DP04까지 전부"가
    # DP01/DP04 두 개만 나오던 문제.
    _ALL_MARKERS = ("전부", "전체", "모든", "4대", "네 대", "다 ", "모두")
    wants_all = any(k in question for k in _ALL_MARKERS)
    if len(snapshots) >= 2 and (not mentioned or wants_all):
        # 나쁜 순서로 세운다 — "어디부터 봐야 되냐"가 이 질문의 요지다.
        mentioned = [mid for mid, _ in sorted(
            snapshots.items(), key=lambda kv: kv[1].get("health_index", 100))]

    if len(mentioned) >= 2:
        picks = []  # (snapshot, defect, factor, rank)
        for mid in mentioned[:MAX_PANELS]:
            snap = snapshots.get(mid)
            wd_list = (snap or {}).get("worst_defects") or []
            if snap and wd_list:
                picks.append((snap, wd_list[0]["defect"], wd_list[0]["worst_factor"], 1))
    else:
        target = snapshots.get(mentioned[0]) if mentioned else (
            next(iter(snapshots.values())) if len(snapshots) == 1 else None)
        if target is None:
            return None
        wd_list = (target.get("worst_defects") or [])[:2]
        picks = [(target, wd["defect"], wd["worst_factor"], i + 1) for i, wd in enumerate(wd_list)]

    panels = [p for p in (_panel_from(*pick) for pick in picks) if p is not None]
    return panels or None


def ask(question: str) -> dict:
    _chart_calls_this_turn.clear()
    _machine_snapshots_this_turn.clear()
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5",
        max_tokens=3000,  # 원인/메커니즘/조치를 defect마다 반복 + recipe_hotspots 표까지
        # 붙다 보니 2000으로 가끔 빠듯했다(26.08.06 티어체계 확장 이후 답변이 길어짐).
        system=SYSTEM_PROMPT,
        tools=[
            get_machine_health, get_defect_causes, get_sop_for_factor,
            get_trend_chart_data, get_defect_occurrence_dates,
        ],
        messages=[{"role": "user", "content": question}],
    )
    final_text = ""
    for message in runner:
        for block in message.content:
            # 빈 문자열 블록이면 덮어쓰지 않는다 — 도구만 호출하고 텍스트가 없는
            # 메시지가 마지막에 끼면(또는 빈 텍스트 블록이면) final_text가 이미 받아둔
            # 진짜 답변을 지워버려서 화면에 빈 말풍선만 뜨는 문제가 있었다.
            if block.type == "text" and block.text:
                final_text = block.text
    panels = (_build_panels(_machine_snapshots_this_turn, _chart_calls_this_turn, question)
              if (_machine_snapshots_this_turn or _chart_calls_this_turn) else None)
    return {"answer": final_text, "panels": panels}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "DP03 상태 어때? 오늘 제일 급한 게 뭐야?"
    print(f"질문: {q}\n")
    result = ask(q)
    print(result["answer"])
    if result["panels"]:
        print(f"\n[대시보드 패널 {len(result['panels'])}개 생성됨: "
              f"{[p['title'] for p in result['panels']]}]")
