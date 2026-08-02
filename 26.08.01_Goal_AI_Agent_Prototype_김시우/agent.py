"""공정 품질 통합 관리 AI Agent — v2 (레벨/추세 분리 구조).

목적: "엔지니어를 대신해서 분석해주는 AI Agent"라는 프로젝트 본래 목표에 맞춰,
팀이 쌓은 지식(확정 유효인자별 레벨/추세, 실제 불량 발생 여부, 미확인 이상)을
Claude API가 실제로 조회해서 질문에 자연어로 답하는지 검증하는 버전이다.

v1과의 차이: 예전엔 Health Index라는 단일 점수(불량/안정성/추세 페널티를 임의
가중치로 합산)를 만들어서 보여줬는데, 그 가중치 자체가 근거 없는 값이었고
"과거 요약"에 가까웠다. v2는 점수를 하나로 뭉개지 않고, defect별 원인변수마다
레벨(지금 얼마나 벗어났나)과 추세(최근 며칠 방향/속도)를 그대로 노출한다 —
"레벨이 높고 추세도 나쁘니 급하다"는 종합 판단은 에이전트(이 모델)가 자연어로
하게 맡긴다. 확정 원인이 아닌 변수의 이상도 별도로 보여주고(안전망), 실제 불량
발생 여부는 레벨/추세와 완전히 분리된 필드로 준다 — "이미 터진 것"과 "터지기
전 조짐"을 섞지 않기 위함.

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
import sys
from pathlib import Path

import anthropic
from anthropic import beta_tool

HERE = Path(__file__).resolve().parent
HEALTH_INDEX_DATA = HERE.parent / "26.08.01_Goal5_HealthIndex_Dashboard_김시우" / "health_index_data.json"

with open(HEALTH_INDEX_DATA, encoding="utf-8") as f:
    DATA = json.load(f)

MACHINES = DATA["machines"]
CAUSE_FACTORS = DATA["cause_factors"]

# defect -> 그 defect의 원인으로 확정된 factor 목록 (역인덱스)
DEFECT_TO_FACTORS: dict[str, list[str]] = {}
for factor, meta in CAUSE_FACTORS.items():
    for defect in meta["defects"]:
        DEFECT_TO_FACTORS.setdefault(defect, []).append(factor)


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
    return json.dumps({"machine_id": machine_id, **snap}, ensure_ascii=False, indent=2)


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
엔지니어가 직접 데이터를 뒤지지 않아도, 오늘 뭘 먼저 봐야 하는지·원인·조치를 대신 조회해서 설명해주는 게 네 역할이다.

원칙:
1. 반드시 도구를 호출해서 실제 데이터를 확인한 뒤에 답하라. 데이터 없이 추측하지 마라.
2. 하나의 점수로 뭉개서 답하지 마라. get_machine_health가 주는 정보는 defect별로 "레벨"(지금 \
   baseline 대비 얼마나 벗어났는지, level_z)과 "추세"(recent_trend_slope_z_per_day — 최근 방향과 \
   속도)가 분리되어 있다. 어느 게 심각한지, 레벨은 낮아도 추세가 나쁘면 왜 주의해야 하는지 등을 \
   네가 직접 종합해서 설명하라 — 종합 판단 자체가 네 역할이다.
3. actual_occurred_recent_7d(최근 7일 실제 불량 발생 여부)는 레벨/추세와 다른 층위다. 실제로 \
   불량이 이미 났으면 그 사실을 가장 먼저, 명확하게 알려라 — "아직 조짐 단계"와 "이미 터짐"을 \
   절대 같은 어조로 말하지 마라.
4. unconfirmed_anomalies(미확인 이상)에 뭔가 있으면 반드시 언급하되, 확정 원인과는 다른 톤으로 \
   — "이건 아직 어느 defect와 연결되는지 검증되지 않았다"는 걸 매번 명시하고, SOP를 만들어내지 마라.
5. 유효인자는 팀이 통계적으로 검증한 "확정 원인"이지만, 상관관계이지 완전한 인과 증명은 아니다. \
   과도하게 확신하는 어조를 쓰지 말고, 근거(누가 어떤 방법으로 확인했는지)를 함께 설명하라.
6. SOP 제안은 전부 DRAFT_UNVERIFIED(미검증 초안)다 — 실제 조치처럼 단정적으로 말하지 말고, \
   "멘토/현장 확인 전까지는 참고용"이라는 점을 항상 명시하라.
7. 답변은 한국어로, 공정 엔지니어가 바로 이해할 수 있게 간결하고 구체적으로 하라. \
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
    q = " ".join(sys.argv[1:]) or "DP03 상태 어때? 오늘 제일 급한 게 뭐야?"
    print(f"질문: {q}\n")
    print(ask(q))
