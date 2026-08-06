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
true인 변수는 레벨 점수에 (1 - 0.5×maturity) 배율을 곱한다 — maturity는 이 경보가
alert_since부터 며칠째 지속 중인지를 14일 기준으로 0~1로 정규화한 값. 막 뜬 경보는
거의 안 깎이고 14일 이상 지속된 "성숙한" 경보라야 최대 50%까지 깎인다 — 그래서
health_index 자체가 이미 추세(그것도 얼마나 오래 확인된 추세인지)를 어느 정도 반영한
값이다(margin과 완전히 같은 게 아님). 그 위에 "이 속도면 예상 며칠 뒤 스펙아웃"이라는
정량 추정치(estimated_days_to_spec_out)를 별도로 더 준다. 자세한 계산 로직은
build_health_index.py 상단 docstring 참고.

get_machine_health가 반환하는 구조 핵심:
  - health_index: 장비/defect/원인변수 3단계 모두 있음 (낮을수록 급함)
  - worst_defects / worst_factors: 나쁜 순서로 최대 3개 정렬된 목록 (1개만 보지 말 것)
  - current_value / lsl / usl / spec_status: 추상적 %가 아니라 실제 값 — spec_status가
    "SPEC_OUT"이면 이미 스펙을 벗어난 것, "OK"면 아직 스펙 안
  - spec_source: 세 가지가 있고 신뢰도가 다르다.
      "mentor_spec"(멘토가 26.08.05 직접 준 진짜 스펙, 10개 변수만)이면 신뢰도 높음.
      "provisional_percentile"(정상군 분포 기반 임시 대체값, 대부분의 변수)이면 진짜
        스펙이 아니라는 걸 반드시 같이 언급할 것.
      "defect_zone_rate"(CLN_Pressure/Surface_Roughness 2개만) — 이 둘은 성격이 달라서
        health/margin이 "값이 스펙에서 얼마나 벗어났나"가 아니라 "그날 샷 중 몇 %가
        불량 급증 구간에 들어갔나"에서 나온다. defect_zone_rate_pct(현재 비율)와
        defect_zone_baseline_pct(평소 비율)를 같이 인용해서 설명할 것.
    셋을 같은 확신으로 말하면 안 됨.
  - defect_zone_rate_pct / defect_zone_baseline_pct: 위 "defect_zone_rate" 컬럼에만 값이
    있고 나머지는 null. 예: 7.53%(평소 6.13%)면 "평소보다 위험구간 진입이 늘었다"는 뜻.
  - estimated_days_to_spec_out: margin 기울기로 이 스크립트가 직접 추정한 정량적
    "예상 며칠 뒤" — 나빠지는 중일 때만 값이 있고, 안정적이거나 좋아지는 중이거나
    이미 SPEC_OUT이면 null. 표본이 작아 숫자 자체보다 "며칠 단위/몇 주 단위" 정도의
    감으로만 말할 것.
  - trend_direction / early_warning_active / trend_message: estimated_days_to_spec_out과
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
# 26.08.05 관계DB(JHdaimma) 최신 판정으로 교체 — Micro_Crack Vibration/Cooling_Flow 강등 등
# 반영. 기존 키(defects/owner/direction/mechanism)는 그대로라 아래 코드는 수정 불필요.
with open(REL_DB / "agent_cause_factors.json", encoding="utf-8") as f:
    CAUSE_FACTORS = json.load(f)["cause_factors"]
LEVEL_TREND = pd.read_csv(LEVEL_TREND_CSV)
DAILY_SERIES = pd.read_csv(DAILY_SERIES_CSV)
DAILY_TREND = pd.read_csv(DAILY_TREND_CSV)  # 전체 89일 기준 defect rate — 실제 발생 날짜 조회용

DEFECT_RATE_COLS = {
    "Particle": "Particle_rate",
    "Remain_Coat": "Remain_Coat_rate",
    "Micro_Crack": "Micro_Crack_rate",
    "Chipping": "Chipping_rate",
}

# defect -> 그 defect의 원인으로 확정된 factor 목록 (역인덱스)
DEFECT_TO_FACTORS: dict[str, list[str]] = {}
for factor, meta in CAUSE_FACTORS.items():
    for defect in meta["defects"]:
        DEFECT_TO_FACTORS.setdefault(defect, []).append(factor)

# get_trend_chart_data가 마지막으로 만든 차트 데이터를 담아둔다. tool_runner는 최종
# 텍스트만 돌려주기 때문에, 그래프용 원시 데이터는 별도로 꺼내 chat.html에 넘겨야 한다.
# 주의: 프로토타입이라 전역 변수 하나로 처리 — 동시에 여러 요청이 들어오면(멀티유저) 꼬일
# 수 있다. 데모용 단일 사용자 흐름 전제.
_last_chart_data: dict = {"value": None}


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


DEFAULT_CHART_DAYS = 30  # 3개월(전체 89일) 다 보여주면 최근 동향이 묻힘 — 관례적 기본값


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
    machine_id: str, factor: str, days: int = DEFAULT_CHART_DAYS, center_date: str | None = None,
) -> str:
    """특정 장비×변수의 추세를 그래프로 보여달라는 요청일 때 시계열 데이터를 조회한다.

    사용자가 "그래프로 보여줘", "추세 그려줘"처럼 시각적으로 보고 싶어할 때만 호출한다.
    반환값에는 baseline/LSL/USL 기준선과 날짜별 실측값이 들어있어, 화면에서 바로
    선그래프로 그릴 수 있다. factor는 CAUSE_FACTORS 11개뿐 아니라 전체 연속형 변수
    아무거나 가능하다(안전망 대상 포함).

    Args:
        machine_id: 장비 ID, 예: "DP01", "DP02", "DP03", "DP04".
        factor: 변수 이름, 예: "Vibration", "Laser_Power", "CLN_Flow".
        days: 최근 며칠치를 보여줄지. 기본 30일(최근 한 달) — 전체 기간(89일)을 다
            보여주면 최근 동향이 묻힌다. 사용자가 "최근 일주일만", "전체 기간 다"처럼
            요청하면 그에 맞게 조정(예: 7, 89). center_date를 쓸 때는 이 값이 그 날짜
            앞뒤로 며칠씩 볼지를 뜻한다(예: days=7이면 앞뒤 3일씩 총 7일 근방).
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
    if center_date:
        center = pd.Timestamp(center_date)
        half = max(days, 2) // 2
        dates = pd.to_datetime(series["date"])
        series = series[(dates >= center - pd.Timedelta(days=half)) & (dates <= center + pd.Timedelta(days=half))]
    else:
        series = series.tail(max(days, 2))

    spec = spec_row.iloc[0]
    result = {
        "machine_id": machine_id,
        "factor": factor,
        "baseline_median": float(spec["baseline_median"]),
        "lsl": float(spec["lsl"]),
        "usl": float(spec["usl"]),
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
    _last_chart_data["value"] = result
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
- **원인**: `{worst_factors[0]의 factor}` — spec_source에 따라 다르게 쓸 것(규칙 10 참고):
    - mentor_spec/provisional_percentile: 현재 `{current_value}` / {direction이 up이면 "상한" \
      down이면 "하한"} `{usl 또는 lsl}` [{mentor_spec이면 "스펙기준" provisional_percentile이면 "임시기준"}]
    - defect_zone_rate(CLN_Pressure/Surface_Roughness): current_value/usl/lsl 대신 \
      `{defect_zone_rate_pct}`% (평소 `{defect_zone_baseline_pct}`%) [불량검증기준]으로 쓸 것 \
      — 이 둘은 health가 current_value와 직접 연결되지 않으므로 섞어 쓰면 틀린다.
   공통: {trend_direction이 up이면 "상승" down이면 "하강" 아니면 생략}추세{estimated_days_to_spec_out이 \
null이 아닐 때만 ", 스펙아웃 예상 `{N}일`"을 붙여라 — null이면 이 구절을 통째로 빼고, 숫자를 \
절대 지어내지 마라}
- **메커니즘**: {mechanism을 화살표(→) 형식 한 줄로 압축}
- **SOP**: {get_sop_for_factor의 action을 한 줄로 압축} `[미검증초안]`

(worst_defects 중 상위 1~2개만 위 `###` 헤더+4개 불릿 블록으로 쓰고, 그 아래 순위부터는 \
헤더 없이 불릿 한 줄로: `- **{N순위}** {defect} (HI {값}) [발생/미발생] — {worst_factor} {한 줄 사유}`)

unconfirmed_anomalies가 있으면 마지막에 표로:
| 인자 | 상태 |
|---|---|
| `{factor1}` | {SPEC_OUT 또는 "N일 뒤 스펙아웃"} |

맨 끝에 한 줄만(헤더·볼드 없이 평문으로):
※ 원인은 통계적 상관관계로 확정된 것이며 완전한 인과관계 증명은 아닙니다. SOP는 전부 DRAFT_UNVERIFIED입니다.
--- 형식 끝 ---

3. defect에 확정 원인이 없으면(get_defect_causes가 "없음"이라 답하면) 원인/메커니즘/SOP 3줄 대신 \
   "원인: 확정 원인 없음 ({이유를 한 줄로})"로 대체하라.
4. 원인이 여러 개인 defect는 worst_factors[0](가장 나쁜 것) 하나만 위 형식에 쓰고, 나머지는 \
   사용자가 더 물어보면 그때 알려줘라 — 처음부터 다 나열하지 마라.
5. spec_status가 "SPEC_OUT"이면 상한/하한 대신 그냥 "SPEC_OUT"이라고만 써라. 퍼센트(%)는 절대 쓰지 마라 \
   (단, defect_zone_rate 컬럼의 defect_zone_rate_pct/defect_zone_baseline_pct는 이 규칙의 예외 — \
   그 자체가 판정 근거라 반드시 %로 표시).
6. **장비 간 순위 비교("몇 등이야?", "다른 장비랑 비교하면?")는 사용자가 명시적으로 물어봤을 때만 \
   계산하라.** 그 전까지는 절대 "N개 장비 중 M등" 같은 문구를 먼저 붙이지 마라 — 매번 계산하면 \
   장비 4대를 다 조회해야 해서 응답이 느려진다. 명시적으로 물으면 get_machine_health를 4대 다 \
   불러서 순위를 계산해 알려줘라.
7. 사용자가 그래프/추세를 시각적으로 보여달라고 하면 get_trend_chart_data를 호출하라. 이 도구를 \
   부르면 화면에 자동으로 선그래프가 그려지니, 텍스트로 수치를 다시 나열하지 말고 "그래프로 \
   보여드렸습니다"처럼 짧게 언급하고 핵심 해석만 한 줄 덧붙여라.
8. "불량 난 구간 보여줘"처럼 특정 시점 주변을 보고 싶어하면, 먼저 get_defect_occurrence_dates로 \
   실제 발생 날짜를 찾고, 그 날짜를 get_trend_chart_data의 center_date로 넘겨라. 발생일이 매우 \
   많으면(Particle/Remain_Coat) 가장 최근 날짜 하나를 골라 쓰거나 사용자에게 물어봐라.
9. "어느 제품/레시피가 문제야?"처럼 물으면(get_machine_health 결과의 causes 안에 있는) \
   recipe_hotspots를 확인해서 표로 답하라: `| 조합 | 경고건수 |` 형식. \
   recipe_hotspot_concentrated가 true면 top1 조합(product_id×recipe_id)을 "우선 점검 대상"이라고 \
   콕 집어 말하고, false면 n_product_recipe_combos_affected(예: "54개 중 54개")를 근거로 \
   "특정 레시피 문제가 아니라 설비 자체 문제"라고 명확히 말하라 — 숫자만 보고 특정 레시피를 \
   원인으로 단정하지 마라.
10. spec_source를 반드시 확인하고 다르게 말하라(위 출력 형식의 "원인" 줄에도 이미 반영됨). \
    "mentor_spec"(Laser_Power/Power_Efficiency/Laser_Centering_Position/Frequency/Feed_Speed/ \
    Head_Temp/Kerf_Width_Profile/Coating_Thickness/Coating_Uniformity 등 10개 변수만 해당)은 \
    멘토가 준 진짜 스펙이라 "스펙기준"이라고 확실하게 말해도 된다. "provisional_percentile"( \
    나머지 대부분)은 정상군 분포로 대체한 임시값일 뿐이니 "임시기준"이라고만 표시하고 "스펙"이라는 \
    단어를 쓰지 마라. "defect_zone_rate"(CLN_Pressure/Surface_Roughness)는 실제 불량 발생 \
    데이터로 검증된 경계라 "불량검증기준"이라고 말할 수 있지만 멘토 스펙은 아니다. 셋을 같은 \
    확신으로 말하면 안 된다.
11. 한국어로 답하되, 위 출력 형식을 벗어난 부가 설명 문단을 붙이지 마라. 사용자가 형식에 없는 걸 \
    추가로 물으면(예: SOP 상세 설명, 왜 이런 판정인지) 그 부분만 짧게 답하고 전체 형식은 유지하라.
"""


def ask(question: str) -> dict:
    _last_chart_data["value"] = None
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5",
        max_tokens=2000,
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
            if block.type == "text":
                final_text = block.text
    return {"answer": final_text, "chart_data": _last_chart_data["value"]}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "DP03 상태 어때? 오늘 제일 급한 게 뭐야?"
    print(f"질문: {q}\n")
    result = ask(q)
    print(result["answer"])
    if result["chart_data"]:
        print(f"\n[그래프 데이터 있음: {result['chart_data']['machine_id']}/{result['chart_data']['factor']}, "
              f"{len(result['chart_data']['series'])}개 포인트]")
