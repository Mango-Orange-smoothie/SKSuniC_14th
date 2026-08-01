"""공정 품질 통합 관리 AI Agent — 최소 동작 버전 (월요일 데모용 프로토타입).

목적: "엔지니어를 대신해서 분석해주는 AI Agent"라는 프로젝트 본래 목표에 맞춰,
지금까지 팀이 쌓은 지식(Health Index/경보/확정 유효인자)을 Claude API가 실제로
조회해서 질문에 자연어로 답하는지 검증하는 최소 버전이다.

아직 윤진혁님의 관계DB가 완성되기 전이라, 지금 있는 데이터로만 동작한다:
  - Health Index/경보: 26.08.01_Goal5_HealthIndex_Dashboard_김시우/dashboard_data.json
  - 확정 유효인자: 같은 파일의 cause_factors (daeho=Particle, 전성재=Remain_Coat,
    JHdaimma=Chipping/Micro_Crack 결과를 이미 통합해둔 것)
관계DB가 커지면 get_defect_causes/get_sop_for_factor 두 함수만 그걸 읽도록
바꾸면 된다 — 에이전트 구조 자체는 안 바뀐다.

실행 전 준비:
  1. pip install anthropic   (이미 설치됨)
  2. 터미널에서: export ANTHROPIC_API_KEY="본인 키"
  3. python3 agent.py "DP03 상태 어때?"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic
from anthropic import beta_tool

HERE = Path(__file__).resolve().parent
DASHBOARD_DATA = HERE.parent / "26.08.01_Goal5_HealthIndex_Dashboard_김시우" / "dashboard_data.json"

with open(DASHBOARD_DATA, encoding="utf-8") as f:
    DATA = json.load(f)

HI_SERIES = DATA["health_index_series"]
ALERTS = DATA["alerts"]
CAUSE_FACTORS = DATA["cause_factors"]

# defect -> 그 defect의 원인으로 확정된 factor 목록 (역인덱스)
DEFECT_TO_FACTORS: dict[str, list[str]] = {}
for factor, meta in CAUSE_FACTORS.items():
    for defect in meta["defects"]:
        DEFECT_TO_FACTORS.setdefault(defect, []).append(factor)


@beta_tool
def get_machine_health(machine_id: str) -> str:
    """특정 장비의 최신 Health Index, 최근 추세, 활성 경보를 조회한다.

    Args:
        machine_id: 장비 ID, 예: "DP01", "DP02", "DP03", "DP04".
    """
    machine_id = machine_id.upper().strip()
    rows = [r for r in HI_SERIES if r["Machine_ID"] == machine_id]
    if not rows:
        return f"'{machine_id}'에 대한 데이터를 찾을 수 없음. 유효한 장비 ID: DP01~DP04."

    rows_sorted = sorted(rows, key=lambda r: r["date"])
    latest = rows_sorted[-1]
    last_30 = rows_sorted[-30:]
    hi_values = [r["health_index"] for r in last_30]

    machine_alerts = [a for a in ALERTS if a["Machine_ID"] == machine_id]

    result = {
        "machine_id": machine_id,
        "latest_date": latest["date"],
        "latest_health_index": latest["health_index"],
        "defect_penalty": round(latest["defect_penalty"], 2),
        "stability_penalty": round(latest["stability_penalty"], 2),
        "trend_penalty": round(latest["trend_penalty"], 2),
        "last_30day_min": round(min(hi_values), 1),
        "last_30day_max": round(max(hi_values), 1),
        "active_alerts_count": len(machine_alerts),
        "active_alerts": machine_alerts[:5],
    }
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
    """특정 원인 변수(유효인자)에 대한 점검/조치 SOP 초안을 조회한다. 전부 미검증 초안이다.

    Args:
        factor_name: 원인 변수 이름, 예: "Vibration", "CLN_Pressure".
    """
    meta = CAUSE_FACTORS.get(factor_name)
    if not meta:
        known = ", ".join(sorted(CAUSE_FACTORS.keys()))
        return f"'{factor_name}'는 확정 유효인자가 아님. 조회 가능한 인자: {known}"
    return json.dumps({
        "factor": factor_name,
        "check": f"{factor_name} 실측값을 baseline(정상군 기준) 대비 확인",
        "action": f"{factor_name} 이상 원인(설비 점검/재보정) 조치 후 관련 defect 불량률 72시간 재확인",
        "status": "DRAFT_UNVERIFIED — 멘토/현장 SOP 확인 전까지 참고용",
    }, ensure_ascii=False, indent=2)


SYSTEM_PROMPT = """\
너는 SK하이닉스 HBM 다이싱 공정의 "공정 품질 통합 관리 AI Agent"다. \
엔지니어가 직접 데이터를 뒤지지 않아도, 장비 상태·불량 원인·조치를 대신 조회해서 설명해주는 게 네 역할이다.

원칙:
1. 반드시 도구를 호출해서 실제 데이터를 확인한 뒤에 답하라. 데이터 없이 추측하지 마라.
2. 유효인자는 팀이 통계적으로 검증한 "확정 원인"이지만, 상관관계이지 완전한 인과 증명은 아니다. \
   과도하게 확신하는 어조를 쓰지 말고, 근거(누가 어떤 방법으로 확인했는지)를 함께 설명하라.
3. SOP 제안은 전부 DRAFT_UNVERIFIED(미검증 초안)다 — 실제 조치처럼 단정적으로 말하지 말고, \
   "멘토/현장 확인 전까지는 참고용"이라는 점을 항상 명시하라.
4. Health Index는 잠정 가중치로 만든 러프 지표라는 것도 필요시 밝혀라.
5. 답변은 한국어로, 공정 엔지니어가 바로 이해할 수 있게 간결하고 구체적으로 하라. \
   숫자를 인용할 때는 실제 조회한 값을 그대로 써라.
"""


def ask(question: str) -> str:
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[get_machine_health, get_defect_causes, get_sop_for_factor],
        messages=[{"role": "user", "content": question}],
    )
    final_text = ""
    for message in runner:
        for block in message.content:
            if block.type == "text":
                final_text = block.text
    return final_text


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "DP03 상태 어때? 문제 있으면 원인이랑 조치도 알려줘."
    print(f"질문: {q}\n")
    print(ask(q))
