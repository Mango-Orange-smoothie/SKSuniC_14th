"""Health Index 재설계 v3 — "오늘 뭐부터 봐야 하는가"를 위한 우선순위 신호 계산.

배경: 이전 버전(v1)은 불량페널티+안정성페널티+추세페널티를 가중치(3/8/5)로 더해
하나의 점수로 뭉갰다. 근거 없는 가중치 문제도 있었지만, 더 근본적으로는 목적과
안 맞았다 — 이 프로젝트는 "과거를 요약한 리포트"가 아니라 "엔지니어에게 뭘 보라고
알려주는 AI Agent"가 목표다. 하나의 점수로 뭉개면 에이전트가 "왜 급한지" 설명을
못 한다.

v2 구조 — 엔지니어가 "오늘 뭐부터 볼지" 정할 수 있는 숫자(0~100, 100이 건강)를 만들되,
임의 가중치 없이 만든다.

**Health Index가 답하는 질문은 "다른 장비/변수 대비 몇 등인가"가 아니라 "스펙 아웃(임시
USL/LSL) 되기 전에 미리 알 수 있는가"다.** (처음에 정규분포/순위 기반 백분위로 만들었다가,
그건 "통계적으로 얼마나 특이한가"를 재는 거라 목적과 안 맞아서 폐기하고 이 방식으로
다시 짰다.)

  1. **레벨 = 스펙 경계까지 남은 여유를 다 쓴 정도(margin_used_pct, 0~100+)**
       mentor_spec 컬럼(10개): 멘토 실측 LSL/TARGET/USL과 raw 값을 직접 비교.
       provisional_percentile 컬럼(나머지 ~24개): 스펙 경계 z(boundary_z)는
         **daily_mean_z 자기 자신의 분포**(p0.5~p99.5, compute_daily_boundary_z)로 잰 것.
         margin_used_pct = (지금 레벨 z ÷ boundary_z) × 100
         0% = baseline 그대로, 100% = 스펙 경계 도달, 100% 넘으면 이미 스펙아웃.
       변수별 Health Index = margin_to_health(margin_used_pct) — 0~100 안에 들어오되
         아래쪽 10점은 "이미 스펙아웃" 전용 구간이라 스펙아웃끼리도 순위가 갈린다
         (margin 0%→100점, 100%(경계)→10점, 그 위는 0점으로 점근. ALARM_BAND 참고).
       (26.08.05: 예전엔 boundary_z를 raw 샷 노이즈 분포로 재고 daily_mean_z와 비교해서
        granularity가 안 맞았다 — 일평균은 샷 평균이라 분산이 훨씬 작아 그 경계에 거의
        못 미쳤고, "스펙아웃이 원래 잘 안 생긴다"는 결론으로 이어졌었다. daily_mean_z
        자기 분포로 경계를 다시 재서 고침.)
  2. **추세는 두 가지를 별도 정보로 계속 제공하면서, 그중 (b)만 점수에도 작게 반영한다.**
       (a) margin_used_pct의 최근 14일 기울기(%/일)로 뽑은 정량적 "예상 며칠 뒤
           스펙아웃"(margin_trend_pct_per_day/estimated_days_to_control_limit) — 이 스크립트가
           직접 추정. 이건 여전히 점수에 안 섞고 별도 필드로만 준다(리드타임 추정치라
           "점수"로 만들 단위가 없음).
       (b) trend_analysis.py(이승연 원안, WINDOW=10 롤링 + PERSIST_WINDOW=5 지속성
           필터, Kendall tau로 교차검증됨)가 판정한 "지금 공식적으로 경보가 켜져
           있는가"(trend_direction/early_warning_active/trend_message,
           load_trend_warning_status) — 팀이 따로 검증한 판정 로직을 그대로 신뢰.
       (26.08.05: 원래 (b)가 없어서 Health Index가 (a)만으로 자체적으로 "추세"를
        다 떠맡고 있었다 — 원래 설계 의도("전처리에서 변동성 확인 → 추세분석에서
        방향 판단 → 그 결과로 위험을 알려줌")와 다르게, 추세분석 스크립트의 산출물이
        Health Index에 전혀 연결이 안 된 채 따로 돌고 있었다. 여기서 연결.)
       (26.08.06: (b)를 "따로 보여주기만" 했더니, margin은 안 닳았는데 CUSUM은 이미
        지속적 이상을 확정한 변수가 점수만 보면 100점(완전 건강)으로 나오는 사각지대가
        생겼다(예: 막 CUSUM 경보가 뜬 DP01 Head_Temp). "Health Index는 장비 상태를
        보라고 만든 것"이라는 목적에 안 맞아서, early_warning_active가 true인 변수는
        레벨 점수(중 ALARM_BAND 위 몫)에
        (1 - TREND_PENALTY_MAX_CUT × max(maturity, urgency)) 배율을 곱한다.
          maturity = alert_since부터 지속된 일수 ÷ RECENT_WINDOW_DAYS (0~1) — 증거가 쌓였나
          urgency  = RECENT_WINDOW_DAYS ÷ estimated_days_to_control_limit (0~1) — 곧 터지나
                     (개선 중이거나 기울기가 0 이하라 est_days가 없으면 0)
        (26.08.08까지는 maturity 하나만 썼는데, 그러면 "방금 뜬 급한 경보"가 거의 안 깎여
        순위가 뒤집혔다 — DP03 CLN_Pressure(17.8일 뒤 도달, 경보 0.1일째)가 66.3점으로
        Head_Temp(41.8일째지만 개선 중)의 53.6점보다 건강하게 나왔다. 두 축의 순위상관은
        0.077로 사실상 무관해서 어느 쪽으로도 대체가 안 되므로 둘 중 큰 쪽을 쓴다.)
        막 뜬 경보는 거의 안 깎이고, RECENT_WINDOW_DAYS 이상 지속된 "성숙한" 경보라야
        최대폭(TREND_PENALTY_MAX_CUT)을 다 받는다 — 자세한 근거는 TREND_PENALTY_MAX_CUT
        정의부 주석 참고. v1의 "근거 없는 가중치로 여러 페널티를 섞는" 방식으로 돌아가지
        않도록, (a)는 여전히 안 섞고 (b) 하나만, 그것도 "레벨 70%+추세 30%" 식 평균이
        아니라 레벨에 곱하는 배율로만 반영한다 — 평균이면 "추세 미확인=100점"이 되어
        margin은 이미 위험한데 CUSUM만 안 켜진 컬럼의 점수가 오히려 올라가는 문제가
        생기기 때문.)
       레벨(z)과 추세(z/일)는 단위가 달라 그냥 더하면 한쪽이 묻히는 문제가 있어서,
       여전히 "점수 하나로 억지로 합치기"는 하지 않는다 — 레벨은 "지금 얼마나 급한가",
       추세는 "언제쯤/왜 더 급해지는가"에 각자 답하되, (b)가 확정한 이상만큼은 레벨
       점수에도 최소한의 흔적을 남긴다.
  3. defect별 Health Index = 그 defect 원인변수들 중 최솟값(제일 나쁜 게 전체를 끌어내림)
     장비별 Health Index   = 그 장비 defect들 중 최솟값
  4. 확정 원인이 아닌 나머지 변수도 같은 레벨/추세 계산을 적용한다(안전망) — 단 defect
     연결/SOP는 안 붙이고 "미확인 이상"으로만 표시한다. Step0가 이미 전체 연속형
     변수에 대해 baseline/일별 시계열을 계산해둬서 추가 비용이 거의 없다.
  5. 실제 불량 발생 여부(최근 7일 defect rate)는 레벨/추세와 별개 필드로 분리한다
     — "이미 터진 것"과 "터지기 전 조짐"은 다른 층위의 정보라서 섞으면 안 된다.

알려진 한계: provisional_percentile 컬럼의 boundary_z는 컬럼당 대표값 하나(4개 장비
풀링한 p0.5~p99.5)라서, 장비/레시피마다 실제 스펙 여유가 다를 수 있는 걸 다 못 담는다.
또한 정의상 "daily_mean_z의 상위/하위 0.5%"를 경계로 삼으므로, 89일치 데이터에서
장비 전체를 통틀어도 경계를 넘는 사례가 매우 드물게(변수당 1~2건) 나온다 — 표본이
작아서 리드타임 숫자(예상 며칠 뒤 스펙아웃) 자체의 통계적 신뢰도는 낮고, "점진적으로
쌓이는 패턴이 있는지 없는지"를 보는 용도로 쓸 것.

이 스크립트는 정적 HTML 대시보드를 만들지 않는다(v1의 build_dashboard_html.py는
삭제됨) — 산출물은 AI Agent(agent.py)가 직접 읽는 health_index_data.json 하나뿐이다.

입력 의존성: pipeline/step0_preprocessing.py(Step0)의 baseline/일별 시계열 산출물이
꼭 있어야 한다(없으면 실행 자체가 안 됨). trend_analysis.py(analysis_outputs/
trend_analysis_results.csv)는 있으면 읽어서 trend_direction/early_warning_active/
trend_message를 채우고, 없으면 그 필드들만 비운 채(None/False) 나머지는 그대로
계산한다(load_trend_warning_status가 조용히 빈 dict 반환) — 필수는 아니지만 최신
경보 판정을 반영하려면 먼저 돌려둘 것:
  python pipeline/step0_preprocessing.py
  python trend_analysis.py
  python "26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py"

산출물 (이 폴더 안):
  health_index_data.json   AI Agent가 읽는 데이터 (레벨/추세/실제발생/미확인이상)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config
from pipeline.common import binomial_alert_count
from pipeline.mentor import SPEC

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 팀이 각 defect별로 확정한 "원인(cause)" FDC/response 변수.
# (26.08.05) 예전엔 여기 하드코딩돼 있었으나, 팀 통합 검증(JHdaimma 26.08.05_Goal2_통합_
# Relationship_DB)으로 교체한다. agent.py도 같은 파일을 쓰므로 두 스크립트가 이제 같은
# 원인 판정을 공유한다. direction: "up"=높을수록 위험, "down"=낮을수록 위험,
# "either"=양방향 다 위험(U자형 등).
# (26.08.06) 1세대(담당자 판정+Jun 대조본+SHAP, 11개 후보 중 확정 6개 — Vibration/
# Laser_Centering_Position 포함)에서 2세대(T1~T4 통계 티어 체계, 확정 도메인 11건 검정)로
# 갱신됨에 따라 구성이 Power_Efficiency/Laser_Power/Head_Temp/CLN_Pressure/CLN_Flow/
# Cooling_Flow로 바뀌었다 — Vibration/Laser_Centering_Position은 빠지고 CLN_Flow가
# 새로 들어옴(risk_ratio 24.67, 우리 쪽 결정트리 스캔의 24.8배와 독립적으로 일치).
# 1세대 산출물(rel_00~13)은 26.08.05_Goal2_통합_Relationship_DB_JHdaimma/_history/로
# 이관됨 — 옛 rel_07_health_index_link.csv 등 경로는 더 이상 유효하지 않음.
# ---------------------------------------------------------------------------
REL_DB = REPO_ROOT / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma"
with open(REL_DB / "agent_cause_factors.json", encoding="utf-8") as f:
    _REL_DB_JSON = json.load(f)

# (26.08.08) 예전엔 cause_factors 하나만 읽었다. 이 파일에는 최상위 키가 12개 있고
# 그중 monitor_factors를 안 읽어서 Particle 감시가 통째로 빠져 있었다(JHdaimma님 회신).
#
#   cause_factors    역할=원인(FDC),      actionable=true   -> "이걸 조정하세요"
#   monitor_factors  역할=감시지표(Response), actionable=false  -> "이게 나빠지고 있습니다"
#
# 둘 다 defect 건강도 산출에는 쓰되, 조치 지시는 actionable=true 인 것만 해야 한다
# (관계DB agent_rules 6번: "role이 감시지표인 인자에 조치를 지시하지 말 것. 경보만.").
CAUSE_FACTORS = _REL_DB_JSON["cause_factors"]
MONITOR_FACTORS = _REL_DB_JSON.get("monitor_factors", {})
HEALTH_FACTORS = {**CAUSE_FACTORS, **MONITOR_FACTORS}
CAUSE_COLS = set(HEALTH_FACTORS)
# 확정 원인이 0건인 defect의 사유(agent가 "왜 원인을 못 말하는지" 답할 수 있게).
DEFECTS_WITHOUT_CAUSE = _REL_DB_JSON.get("defects_without_confirmed_cause", {})


def _usable_defects(meta: dict) -> list[str]:
    """한 인자가 "경보에 쓸 수 있는" defect 목록.

    (26.08.08) 예전엔 meta["defects"]를 그대로 썼는데, 관계DB는 인자 레벨
    alert_usable 말고 per_defect[defect].alert_usable을 따로 들고 있고 둘이 다를 수
    있다. 실제로 CLN_Flow는 인자 레벨 True인데 per_defect["Particle"]는 False다
    (risk_ratio 0.80 — 위험구간 불량률이 정상구간보다 오히려 낮다는 뜻이라 DB가
    "이 경계값으로 경보를 걸면 안 됨"이라고 적어놨다). 그걸 무시한 결과 Particle
    건강도가 CLN_Flow 건강도의 복사본이 돼서, DP03의 Particle이 6.8%->10.2%로
    늘어나는 동안 건강도는 100.0을 유지했다(김시우님 지적).
    """
    per = meta.get("per_defect") or {}
    return [d for d in meta.get("defects", [])
            if per.get(d, {}).get("alert_usable", meta.get("alert_usable", True))]


def _load_verified_pairs() -> set[tuple[str, str]] | None:
    """장비 대표 점수에 넣을 수 있는 (인자, 불량) 짝 — **인과가 반박되지 않은** 것.

    (26.08.08 개정) 처음엔 `repro_state == "통과"`만 채택했는데 **너무 좁았다.**
    멘토님이 확정 시나리오를 주셔서 확인됐다:

        DP02 = Laser Aging   -> Power_Efficiency 감소 -> Kerf 증가 -> Chipping 증가
        DP03 = Cooling Failure -> Head_Temp 증가 -> Micro_Crack / Chipping 증가
        DP04 = Cleaning Failure -> CLN_Flow 감소 -> Remain_Coat / Particle 증가

    관계DB의 domain_direction이 이 문장과 글자 그대로 같고 전부 domain_evidence=
    "멘토 확정"이다. 즉 Chipping 짝은 "검증 안 된 관계"가 아니라 **확정된 관계인데
    이 데이터셋에 라벨이 안 실린 것**이다(감시 데이터 Chipping 4건, Laser_Paim 0건 —
    원인 드리프트만 심고 불량 라벨은 R1에 몰아넣은 것으로 보인다).

    그래서 repro_state를 3값으로 갈라 쓴다 — JHdaimma님이 두 값을 구분한 이유가 이거다:

        "통과"                     -> 채택 (감시 데이터에서 재현됨)
        "판정불가(원본 표본부족)"    -> **채택** (표본이 없어 못 잰 것이지 반박된 게 아님)
        "실패(데이터셋간 방향 불일치)" -> 제외 (데이터가 반대 방향을 가리킴)

    표본이 없어서 못 잰 것을 실패로 처리하면 강한 인자가 부당하게 강등된다. 반대로
    방향이 뒤집힌 것(Micro_Crack 짝 2개)은 도메인이 멘토 확정이어도 이 경계값으로는
    경보를 걸 수 없다.
    "최근에 터졌는가"는 기준이 아니다. 관계가 확정된 짝이라면 7일 무발생이어도 대표로
    올려야 맞다 — 그게 예측이다. 반대로 아무리 자주 터져도 방향이 반박됐으면 점수로
    확신을 가장하면 안 된다.

    (아래는 이 함수를 처음 만들 때의 기록 — 기준이 왜 한 번 좁았다가 넓어졌는지)
    장비 대표 점수에 Chipping 9.7(Laser_Power 경보선 초과)이 잡혀서, 매일 실제로 나는
    Particle(8.68%)을 제치고 DP02의 대표가 됐다. 감시 데이터로는 그 인과를 검정할
    방법이 없어서(Chipping 4건, 6-1 스캔에 행조차 안 생김) 일단 제외했는데, 멘토님
    시나리오를 받고 보니 **관계가 없는 게 아니라 이 데이터셋에 라벨이 안 실린 것**
    이었다. "검증 불가"와 "반박됨"을 구분해야 한다.

    판정은 우리가 다시 하지 않고 관계DB의 repro_state를 그대로 읽는다 — C유형 짝짓기
    (common.load_defect_pairing_from_db)가 쓰는 것과 같은 단일 출처다. 파일이 없거나
    스키마가 바뀌면 None을 돌려주고, 호출부는 "전부 채택"으로 폴백한다(조용히 빠지는
    것보다 예전 동작이 낫다 — 대신 경고를 찍는다).
    """
    path = REL_DB / "rel_20_tier_table.csv"
    if not path.exists():
        return None
    try:
        t = pd.read_csv(path, usecols=["factor", "defect", "repro_state"])
    except (ValueError, KeyError):
        return None
    # "실패(...)"로 시작하는 것만 제외 — 통과/판정불가는 채택.
    ok = ~t["repro_state"].astype(str).str.strip().str.startswith("실패")
    return set(zip(t.loc[ok, "factor"], t.loc[ok, "defect"]))


VERIFIED_PAIRS = _load_verified_pairs()
if VERIFIED_PAIRS is None:
    print("[관계DB] 경고: rel_20_tier_table.csv를 못 읽어 repro_state를 확인할 수 없습니다 "
          "— 모든 짝을 채택합니다(장비 점수가 과대평가될 수 있음).")


def _scored_defects(meta: dict, factor: str) -> list[str]:
    """대표 점수(장비 순위)에 넣을 defect — 경보용(_usable_defects)의 부분집합."""
    usable = _usable_defects(meta)
    if VERIFIED_PAIRS is None:
        return usable
    return [d for d in usable if (factor, d) in VERIFIED_PAIRS]


_dropped = [(f, d) for f, meta in HEALTH_FACTORS.items()
            for d in meta.get("defects", []) if d not in _usable_defects(meta)]
if _dropped:
    print("[관계DB] per_defect.alert_usable=False 라 Health Index 원인에서 제외: "
          + ", ".join(f"{f}↔{d}" for f, d in _dropped))
_orphans = [d for d in ("Particle", "Remain_Coat", "Micro_Crack", "Chipping")
            if not any(d in _usable_defects(m) for m in HEALTH_FACTORS.values())]
if _orphans:
    print(f"[관계DB] 경고: 쓸 수 있는 원인 인자가 하나도 없는 defect {_orphans} — "
          "이 defect는 Health Index가 감시하지 못한다(가짜 100점을 내지 않도록 제외됨).")

DEFECT_RATE_COLS = {
    "Particle": "Particle_rate",
    "Remain_Coat": "Remain_Coat_rate",
    "Micro_Crack": "Micro_Crack_rate",
    "Chipping": "Chipping_rate",
}

# 미확인 이상(안전망) 판정 임계값 — 경보선까지 남은 여유를 이 % 이상 썼으면 표시.
# 확정 원인이 아니라서 보수적으로(절반 이상 썼을 때만) 잡는다. 최적화된 값은 아니다.
ANOMALY_MARGIN_THRESHOLD_PCT = 50.0
# (26.08.08) margin 하나로만 거르던 걸 "또는 성숙한 지속 경보"로 넓힌다.
#
# 왜 — 관계DB에 짝(어느 변수가 어느 불량의 원인인가)이 없는 변수는 defect 건강도에
# 안 들어가므로 이 안전망이 유일한 출구인데, 조건이 margin뿐이라 **"값은 아직 여유
# 있는데 추세가 확실히 이상한"** 것이 통째로 빠졌다. 추세 페널티를 만든 이유와 정확히
# 같은 사각지대인데 안전망에는 그 논리가 없었다. 실측: 확정 원인이 아닌데 경보가 켜진
# 컬럼 59건 중 **55건이 아무 데도 안 나왔다** — DP03 Kerf_Angle은 37일째 경보인데
# margin 18.7%라 빠졌다.
#
# 짝짓기의 단일 출처는 관계DB지만, **짝을 몰라도 "이 변수 추세가 이상하다"는 말은 할 수
# 있어야 한다.** 원인 지목(어느 불량인지)과 이상 보고(추세가 이상함)는 다른 주장이다.
#
# 기준일은 RECENT_WINDOW_DAYS(14일)를 그대로 쓴다 — 새로 고른 상수가 아니고, 추세
# 페널티의 성숙도 기준이자 §4-4에서 정상 장비와 고장 장비를 완벽히 가른 선이다
# (docs/판정근거_정리.md: DP01 0개 vs DP02 6 / DP03 4 / DP04 1).
# 레벨/추세 계산에 쓰는 최근 구간 길이(일). 통계적 유의성을 새로 검정하는 게 아니라
# "최근 방향/속도"를 서술하는 용도라서 짧아도 된다 — 다만 지난 검증(DP02 Laser_Power
# 사례)에서 확인했듯 이 값 자체로 "유의미한 추세 확정"을 주장하지는 않는다.
RECENT_WINDOW_DAYS = 14
RECENT_DEFECT_WINDOW_DAYS = 7
ANOMALY_SUSTAINED_ALERT_DAYS = RECENT_WINDOW_DAYS
# margin 100%가 걸리는 선 — Shewhart 관리한계(3σ). 교과서 상수이고 σ만 있으면 전 컬럼에
# 똑같이 적용된다. 근거는 compute_level_and_trend의 margin 계산부 주석 참고.
CONTROL_LIMIT_SIGMA = 3.0

TREND_ANALYSIS_CSV = REPO_ROOT / "analysis_outputs" / "trend_analysis_results.csv"
# early_warning이 언제 마지막으로 켜졌는지가 최신 데이터로부터 이만큼(일) 이내면
# "지금도 활성 상태"로 본다. trend_analysis.py의 early_warning은 상태형(조건이 유지되는
# 동안 계속 True)이라 마지막 발생일이 최신 데이터와 가까우면 지금도 켜져 있다는 뜻이다.
TREND_WARNING_ACTIVE_WITHIN_DAYS = 1
# (machine, column) 단위로 보여줄 Product x Recipe 핫스팟 개수.
RECIPE_HOTSPOT_TOP_N = 3
# top1 조합의 경고 건수가 "조합당 평균"의 이 배수 이상이면 "특정 조합에 몰림"으로 본다.
# 미만이면(예: CLN_Flow처럼 전 조합에 고르게 퍼진 경우) 레시피 문제가 아니라 설비/공정
# 전반의 문제라는 뜻이라 agent가 그렇게 말해야 한다.
RECIPE_HOTSPOT_CONCENTRATION_RATIO = 2.0

# (26.08.06 추가, 08.06 개정) Health Index는 원래 margin_used_pct(스펙 경계까지 남은
# 여유)로만 점수를 매겨서, trend_analysis.py가 CUSUM/threshold로 통계적으로 확정한
# "지속적 이상 추세"(early_warning_active)가 켜져 있어도 margin이 아직 안 닳았으면
# 점수가 100에 가깝게 나왔다(예: DP01 Head_Temp가 방금 CUSUM 경보가 떴는데도 100.0으로
# 표시됨) — "장비 상태를 보여준다"는 목적에 안 맞는 사각지대였다.
#
# 처음엔 "켜져 있으면 -15점" 고정폭으로 최소 반영했는데, 실제로 보니 레벨이 여전히
# 점수를 거의 다 좌우했다(100점짜리가 85점까지밖에 안 내려감 — "레벨 비중이 너무 크다"는
# 피드백). 그렇다고 "레벨 70% + 추세 30%"처럼 두 값을 평균내는 것도 안 된다 — 추세가
# 아직 "미확인"(false)일 뿐인데 그걸 "건강함(100)"으로 취급해 평균에 넣으면, margin을
# 91% 써서 이미 스펙아웃 직전인데 CUSUM만 아직 안 켜진 컬럼(예: DP03 Process_Time,
# level=8.8)의 점수가 8.8×0.7+100×0.3=36.2로 오히려 올라가 버린다.
#
# 그래서 "레벨에 비율(%)을 곱해서 깎는" 방식을 쓰되, 그 비율 자체를 alert_active_days
# (이 경보가 며칠째 지속 중인지, load_trend_warning_status가 계산)로 0에서
# TREND_PENALTY_MAX_CUT까지 선형으로 키운다 — 막 뜬 지 몇 시간 안 된 경보(대부분이
# 이 경우: 활성 경보 75건의 중앙값이 0.5일)는 아직 증거가 얕으니 레벨을 거의 안 건드리고,
# RECENT_WINDOW_DAYS(14일, 위 상수 재사용) 이상 지속된 "성숙한" 경보라야 최대폭을
# 다 받는다. 이건 이 프로젝트 전체에서 반복된 원칙과 같다 — PERSIST_WINDOW/episode_id/
# CUSUM 누적합 모두 "순간 튐"보다 "계속 유지되는 신호"를 신뢰하는 방향으로 만들어졌다.
#
# 값 선정 근거 (26.08.09 cfe4acd에서 0.5 -> 0.45로 확정).
#
# 처음엔 ANOMALY_MARGIN_THRESHOLD_PCT(50)에 맞춰 0.5로 잡았다 — "레벨이 100점이어도
# 성숙한 추세 경보 하나로 팀의 기존 기준선(50점)까지 끌어내린다"는 뜻이었다. 그런데
# 멘토 정답으로 재검증하면서 바꿨다:
#
#   0.0~1.0 어느 값을 써도 장비 순위는 안 바뀐다(전부 DP04 < DP02 < DP03 < DP01).
#   그래서 순위로는 고를 수 없고, 대신 "정답에서 정상으로 확정된 DP01의 대표 점수를
#   건드리지 않는 최대값"을 쓴다 — 0.30~0.45는 DP01 90.70으로 동일하고, 0.50부터
#   90.30으로 깎이기 시작한다.
#
# 즉 지금 값은 "정상 장비를 정상으로 유지하는 선에서 추세를 최대한 반영"이 근거다.
# 0.45에서 레벨 100점짜리의 하한은 50점이 아니라 ALARM_BAND + 90×0.55 = **59.5점**이다
# (예전 주석이 0.5 기준의 "50점"을 그대로 두고 있어 코드와 어긋났다 — 26.08.11 정정).
TREND_PENALTY_MAX_CUT = 0.45

# (26.08.06 개정 2) Health Index를 다시 0~100 안에 가두되, "이미 스펙아웃"끼리의 우선순위는
# 살린다. 직전 버전은 margin_used_pct 상한 clip을 아예 없애서 health가 음수(-191 등)까지
# 내려가게 했었다 — 우선순위는 살았지만 "점수"라고 부를 수 없는 값이 됐다.
#
# 대신 0~100 스케일의 **아래쪽 ALARM_BAND점을 "이미 스펙아웃" 전용 구간으로 예약**한다.
#   margin 0~100%  -> health 100 -> ALARM_BAND  (선형, 스펙 안)
#   margin 100%+   -> health ALARM_BAND * (100/margin)  (0으로 점근, 스펙 밖)
# 경계(margin=100%)에서 두 식이 정확히 만나고, 전 구간에서 단조 감소한다. 즉
# **"10점 미만 = 이미 스펙아웃, 0에 가까울수록 몇 배로 벗어난 것"**으로 읽으면 된다.
#
# 10으로 잡은 근거: 이 구간을 넓게 잡을수록 정작 매일 쓰는 "스펙 안" 영역이 눌린다
# (예약 20점이면 margin 50%가 60점으로 나옴 — 원래 뜻인 "여유 절반 남음"과 어긋남).
# 실제 데이터 140개 장비×컬럼 중 margin이 100%를 넘는 건 3건(2%)뿐이라, 2%에 스케일을
# 많이 떼어줄 이유가 없다. 10점이면 스펙 안 영역은 health = 100 - 0.9×margin이 되어
# 원래의 "100 - margin"과 최대 10점(경계에서만)밖에 안 어긋나고, n8n 위험장비 기준
# 30점의 의미도 거의 그대로 유지된다(margin 70% 초과 -> 77.8% 초과). 표시 스케일을
# 어떻게 쪼갤지의 문제일 뿐이라 물리적 근거가 필요한 상수는 아니며, 왜곡을 최소화하는
# 쪽으로 고른 값이다. 왜곡 없는 원본 수치가 필요하면 margin_used_pct를 그대로 쓸 것.
ALARM_BAND = 10.0


def margin_to_health(margin_used_pct: float) -> float:
    """margin_used_pct(0~무한대)를 0~100 Health Index로 단조 변환. 위 ALARM_BAND 주석 참고."""
    m = max(margin_used_pct, 0.0)
    if m <= 100:
        return ALARM_BAND + (100 - ALARM_BAND) * (1 - m / 100)
    return ALARM_BAND * 100 / m


def load_step0_outputs():
    opcond_baseline = pd.read_csv(config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv")
    daily_series = pd.read_csv(config.PREPROCESSING_DIR / "00_machine_daily_series.csv")
    daily_series["date"] = pd.to_datetime(daily_series["date"])
    return opcond_baseline, daily_series


def load_trend_warning_status() -> dict[tuple[str, str], dict]:
    """trend_analysis.py(이승연 원안, 김시우 지속성 필터 수정)의 산출물을 장비×컬럼별 최신 상태로 요약.

    trend_analysis_results.csv는 early_warning=True인 행만 저장된 이벤트 로그다
    (Machine_ID x Product_ID x Recipe_ID x column x DateTime, 샷 단위). Health Index는
    OPCOND로 안 나누고 장비×컬럼 단위로 보므로, 같은 (Machine_ID, column)의 모든 OPCOND
    조합을 합쳐서 "가장 최근에 경보가 켜졌던 시점"을 찾는다. 그 시점이 데이터 전체의
    최신 시점과 가깝다면(TREND_WARNING_ACTIVE_WITHIN_DAYS 이내) 지금도 경보가 켜져
    있다는 뜻이다(early_warning은 지속성 필터를 거친 상태형 플래그라 순간 노이즈가 아님).

    Health Index의 "레벨(margin_used_pct)"과 별개 축인 "추세"를 여기서 가져온다 —
    margin 기울기(OLS)로 직접 추정하지 않고, 팀이 따로 검증한 trend_analysis.py의
    판정(WINDOW=10 롤링 + PERSIST_WINDOW=5 지속성 필터, Kendall tau 교차검증됨)을
    그대로 신뢰해서 쓴다. (26.08.05: 원래는 Health Index가 자체적으로 14일 선형회귀
    기울기만으로 추세를 다시 계산해서, trend_analysis.py와 완전히 분리된 채 돌고
    있었다 — 원래 설계 의도(전처리→추세분석→Health Index가 그 결과를 읽어 씀)와
    안 맞아서 여기서 연결.)

    (26.08.05 추가) trend_message는 이 (machine, column)의 "가장 최근 경고 1건"의
    메시지를 그대로 인용하는데, 그 메시지가 특정 Product_ID/Recipe_ID를 콕 집어
    말해도(예: "DP01 / PKG_A / RCP_2의 Vibration...") 정작 margin_used_pct/current_value는
    그 machine의 전체 Product/Recipe를 뭉친 값이라 서로 근거 층위가 어긋났었다.
    trend_analysis_results.csv가 이미 Product_ID/Recipe_ID를 갖고 있으므로(샷 단위
    원본 grain), 여기서 (machine, column) 안에서 Product×Recipe 조합별 경고 건수를
    같이 집계해 recipe_hotspots로 반환한다 — "어느 설비가 문제인가"(machine, column
    자체가 이미 답함)뿐 아니라 "어느 제품/레시피 조합이 문제인가"까지 agent가 답할 수
    있게 하기 위함. top1이 조합당 평균 경고 건수의 RECIPE_HOTSPOT_CONCENTRATION_RATIO배
    이상이면 "특정 조합에 몰림"(recipe_hotspot_concentrated=True), 아니면 전 조합에
    고르게 퍼진 것이라 레시피 문제가 아니라 설비/공정 전반의 문제로 봐야 한다.
    """
    if not TREND_ANALYSIS_CSV.exists():
        return {}
    tr = pd.read_csv(
        TREND_ANALYSIS_CSV,
        usecols=["DateTime", "Machine_ID", "Product_ID", "Recipe_ID", "column",
                 "trend_direction", "message", "episode_id"],
    )
    tr["DateTime"] = pd.to_datetime(tr["DateTime"])
    dataset_latest = tr["DateTime"].max()

    status: dict[tuple[str, str], dict] = {}
    for (machine, col), g in tr.groupby(["Machine_ID", "column"]):
        latest_row = g.loc[g["DateTime"].idxmax()]
        days_since = (dataset_latest - latest_row["DateTime"]) / pd.Timedelta(days=1)

        # (26.08.06) "언제부터 이 이상이 시작됐는지". 알림을 매 행마다 새로 보내면 40일
        # 지속되는 문제도 40번 나가므로(엔지니어 알림 피로), n8n 등 실제 알림 트리거는
        # early_warning 행이 아니라 이 alert_since가 바뀔 때만 새 알림으로 취급해야 한다.
        #
        # (26.08.08 개정) 예전엔 "가장 최근 행이 속한 episode"(같은 Product×Recipe 안에서
        # 끊기지 않은 구간)의 시작을 썼는데, 그러면 상태가 유지되지 않고 계속 리셋됐다 —
        # 경보는 Product×Recipe 그룹별로 판정되는데 서로 다른 그룹의 샷이 시간축에서
        # 뒤섞이므로 한 그룹의 경보는 자연히 끊긴다. 실측: 128개 (장비,컬럼) 조합 중
        # 54개가 "1일 미만"으로 표시됐는데 전부 실제로는 30일 넘게 경보 상태였다
        # (DP03 Surface_Roughness는 224개 episode로 쪼개져 "0.1일째"). 엔지니어가 보는
        # 건 "이 장비의 이 변수가 언제부터 이상한가"이지 레시피별 조각이 아니다(김시우님 지적).
        #
        # 그래서 (장비, 컬럼) 단위로, 경보 간격이 TREND_WARNING_ACTIVE_WITHIN_DAYS 이내면
        # 같은 상태가 이어진 것으로 보고 이어붙인다. 이 상수는 바로 위 early_warning_active
        # 판정이 이미 "마지막 경보가 이만큼 이내면 지금도 켜져 있다"는 뜻으로 쓰는 값이라
        # 새 튜닝값을 만들지 않는다.
        times = g["DateTime"].sort_values()
        gap_breaks = times.diff() > pd.Timedelta(days=TREND_WARNING_ACTIVE_WITHIN_DAYS)
        run_id = gap_breaks.cumsum()
        current_run = run_id == run_id.iloc[-1]
        alert_since = times[current_run].min()
        alert_active_days = (dataset_latest - alert_since) / pd.Timedelta(days=1)

        # (26.08.11) 방향은 **현재 경보 구간의 우세 방향**을 쓴다. 예전엔 가장 최근 1행의
        # trend_direction을 그대로 썼는데, 노이즈성 컬럼은 방향이 행마다 뒤집혀서 마지막
        # 하나가 대표성이 없었다 — DP03 Kerf_Angle은 경보 662건 중 630건(95%)이 "up"인데
        # 마지막 행이 "down"이라 화면·에이전트 답변에 계속 "down"으로 나갔다.
        # 구간은 alert_since를 잡을 때 쓴 것과 같은 창(current_run)이라 새 기준이 아니다.
        # 얼마나 한쪽으로 쏠렸는지(share)도 같이 내보내서, 0.5에 가까우면 "방향이 섞여
        # 있다 = 추세라고 부르기 어렵다"를 소비자가 판단할 수 있게 한다.
        run_dirs = g.loc[current_run[current_run].index, "trend_direction"].dropna()
        if len(run_dirs):
            counts = run_dirs.value_counts()
            trend_direction = str(counts.index[0])
            trend_direction_share = round(float(counts.iloc[0] / counts.sum()), 3)
        else:
            trend_direction, trend_direction_share = None, None

        combo_counts = g.groupby(["Product_ID", "Recipe_ID"]).size().sort_values(ascending=False)
        n_combos_affected = int(combo_counts.size)
        avg_per_combo = float(combo_counts.mean())
        top1_count = int(combo_counts.iloc[0])
        recipe_hotspots = [
            {"product_id": p, "recipe_id": r, "warning_count": int(c)}
            for (p, r), c in combo_counts.head(RECIPE_HOTSPOT_TOP_N).items()
        ]

        status[(machine, col)] = {
            "trend_direction": trend_direction,
            "trend_direction_share": trend_direction_share,
            "early_warning_active": bool(days_since <= TREND_WARNING_ACTIVE_WITHIN_DAYS),
            "trend_message": latest_row["message"],
            "days_since_last_warning": round(float(days_since), 1),
            "alert_since": alert_since.strftime("%Y-%m-%d") if bool(days_since <= TREND_WARNING_ACTIVE_WITHIN_DAYS) else None,
            "alert_active_days": round(float(alert_active_days), 1) if bool(days_since <= TREND_WARNING_ACTIVE_WITHIN_DAYS) else None,
            "recipe_hotspots": recipe_hotspots,
            "n_product_recipe_combos_affected": n_combos_affected,
            "recipe_hotspot_concentrated": bool(top1_count >= RECIPE_HOTSPOT_CONCENTRATION_RATIO * avg_per_combo),
        }
    return status


def direction_of(column: str) -> str:
    """관계DB에 있으면 확정된 방향, 없으면 방향 모르니 either(양방향 이상 취급)."""
    meta = HEALTH_FACTORS.get(column)
    return meta["direction"] if meta else "either"


def compute_spec_values(opcond_baseline: pd.DataFrame) -> dict[str, dict]:
    """컬럼별 baseline(median)과 robust_z_scale(원래 단위)을 대표값 하나로 정리.

    lsl/usl은 여기서 안 정한다 — provisional 컬럼의 실제 경계(lsl/usl 표시값)는
    margin 계산에 실제로 쓰는 boundary_z(compute_daily_boundary_z)에 맞춰
    compute_level_and_trend에서 baseline ± boundary_z*scale로 다시 구성한다
    (그래야 표시되는 lsl/usl과 margin_used_pct가 서로 어긋나지 않는다 — 26.08.05
    granularity mismatch 버그의 재발 방지).
    """
    spec: dict[str, dict] = {}
    for col, g in opcond_baseline.groupby("column"):
        scale = g["robust_z_scale"].where(g["robust_z_scale"].abs() > 1e-9)
        spec[col] = {
            "baseline_median": float(g["median"].median()),
            "robust_z_scale": float(scale.median()) if scale.notna().any() else None,
        }
    return spec


def compute_boundary_z(opcond_baseline: pd.DataFrame) -> dict[str, float]:
    """컬럼별 "baseline에서 임시 스펙 경계(p0.5~p99.5)까지 몇 z 떨어져 있는지" — RAW 샷 기준.

    OPCOND 층마다 살짝 다를 수 있어서, 층별로 계산한 뒤 중앙값을 컬럼의 대표값으로 쓴다.
    direction에 따라 어느 쪽 경계를 볼지 결정 — either는 둘 중 가까운 쪽(더 보수적인 쪽)을 쓴다.

    주의: 이건 개별 샷(raw) 단위 노이즈 분포로 그은 경계라서, 개별 샷 z-score와
    비교할 때만 맞다(예: analyze_lead_time.py — defect는 개별 샷 단위 사건이라 raw가
    맞는 granularity). **일평균(daily_mean_z)과 비교하려면 이 경계를 쓰면 안 된다** —
    일평균은 여러 샷을 평균내서 분산이 훨씬 작아 이 경계에 거의 못 미치고, 그 결과
    "스펙아웃 사례 자체가 없다"는 잘못된 결론(및 리드타임 0일 오판)으로 이어졌다
    (26.08.05 발견). 일평균 기준 경계는 compute_daily_boundary_z를 쓸 것.
    """
    boundary_z: dict[str, float] = {}
    for col, g in opcond_baseline.groupby("column"):
        direction = direction_of(col)
        scale = g["robust_z_scale"].where(g["robust_z_scale"].abs() > 1e-9)
        up_z = (g["p99_5"] - g["median"]) / scale
        down_z = (g["median"] - g["p0_5"]) / scale
        if direction == "up":
            candidate = up_z
        elif direction == "down":
            candidate = down_z
        else:
            candidate = pd.concat([up_z, down_z], axis=1).min(axis=1)
        candidate = candidate[candidate > 0].dropna()
        if len(candidate):
            boundary_z[col] = float(candidate.median())
    return boundary_z


def compute_daily_boundary_z(daily_series: pd.DataFrame, min_days: int = 30) -> dict[str, dict[str, float]]:
    """컬럼별 "일평균 자기 자신의 분포"로 스펙 경계(z)를 위/아래 양쪽 다 재계산 — DAILY 기준.

    compute_boundary_z(raw 샷 p0.5~p99.5)를 daily_mean_z에 그대로 적용했더니 자와
    저울이 다른 걸 섞어 쓴 셈이 돼서(일평균은 샷 평균이라 분산이 훨씬 작음) 스펙아웃이
    사실상 감지가 안 됐다(26.08.05 발견, 상세 배경은 compute_boundary_z 참고). 여기서는
    daily_mean_z 자신의 p0.5~p99.5로 경계를 그어서, 재는 값과 경계가 같은 granularity를
    쓰게 만든다. Machine_ID 4대를 풀링해서 계산한다(장비 1대당 89일치뿐이라 p0.5/p99.5
    같은 꼬리 분위수는 표본이 부족함).

    {col: {"up": ..., "down": ...}} 형태로 위/아래 둘 다 반환한다 — direction="either"인
    컬럼(확정 원인 중 U자형이거나, 방향을 아직 모르는 안전망 컬럼)을 예전처럼
    min(|p0.5|,|p99.5|) 하나로 뭉개면, 분포가 한쪽으로 치우친 컬럼(예: CLN_Flow — 거의
    항상 baseline보다 낮고 위로는 거의 안 벗어남)에서 "넓은 쪽으로 벗어난 값"을 "좁은 쪽"
    경계로 잘못 나눠서 margin이 1000%가 넘게 튀는 문제가 있었다(26.08.05 발견). 이제
    compute_level_and_trend에서 현재 값이 어느 쪽으로 벗어났는지 보고 그 방향의 경계를
    쓴다 — mentor_spec 컬럼(_real_spec_margin_pct)이 이미 하던 방식과 통일.
    """
    boundary_z: dict[str, dict[str, float]] = {}
    for col, g in daily_series.groupby("column"):
        z = g["daily_mean_z"].dropna()
        if len(z) < min_days:
            continue
        p0_5, p99_5 = np.percentile(z, [0.5, 99.5])
        entry = {}
        if p99_5 > 0:
            entry["up"] = float(p99_5)
        if p0_5 < 0:
            entry["down"] = float(-p0_5)
        if entry:
            boundary_z[col] = entry
    return boundary_z


# C유형 health 스케일: "위험구간에 들어간 샷 비율"이 어디까지 가면 margin 100%(=스펙아웃
# 취급)로 볼지.
#
# (26.08.08 개정) 예전엔 "평소의 2.0배"라는 고정 배수였는데 두 가지가 문제였다:
#   (1) 평소 비율이 낮은 컬럼일수록 쉽게 넘어서, 컬럼마다 엄격도가 달랐다.
#   (2) 평소 비율이 0에 가까우면 비율 자체가 폭주했다 — DP04 CLN_Flow는 평소 0.032%
#       (안정구간 15,604샷 중 5건)라 margin이 23,412%로 찍혔고, 안정구간 진입이 2건이었다면
#       58,500%가 나왔을 값이다. 분모가 작아서 숫자가 불안정하다.
# 이제 경계를 "그날 샷 수에서 이만큼 진입할 확률이 C_DANGER_ALPHA 미만이 되는 지점"으로
# 잡는다. 분모가 작아도 안정적이고(위 사례에서 5건이든 2건이든 경계가 거의 같다),
# 평소 비율이 0이어도 정의된다. trend_analysis.py의 경보 판정과 같은 기준이다.


def load_daily_defect_zone_rate() -> pd.DataFrame:
    """Step0가 집계한 "날짜×장비별 위험구간 샷 비율"을 로드(없으면 빈 DataFrame)."""
    path = config.PREPROCESSING_DIR / "00_machine_daily_defect_zone_rate.csv"
    if not path.exists():
        return pd.DataFrame()
    z = pd.read_csv(path)
    z["date"] = pd.to_datetime(z["date"])
    return z


def load_target_override_map() -> dict[str, float]:
    """config.TARGET_RECOMPUTE_FROM_DATA(현재 Kerf_Width_Profile)의 재계산된 target을 로드.

    (26.08.05 추가) opcond_baseline(00_stratum_baseline_stats_by_opcond.csv)의 median은
    _apply_mentor_target_override가 SPEC 있는 컬럼을 전부 멘토 TARGET으로 덮어써버려서,
    "실측 OK median"을 다시 구하려면 그 override를 안 거치는 다른 소스가 필요하다.
    compute_baseline_type_b(step0_preprocessing.py)가 TARGET_RECOMPUTE_FROM_DATA 컬럼은
    이미 원본 OK median으로 00_baseline_AB.csv에 저장해두므로 그걸 그대로 읽는다.
    """
    path = config.PREPROCESSING_DIR / "00_baseline_AB.csv"
    if not path.exists() or not config.TARGET_RECOMPUTE_FROM_DATA:
        return {}
    ab = pd.read_csv(path)
    result = {}
    for col in config.TARGET_RECOMPUTE_FROM_DATA:
        sub = ab[ab["column"] == col]
        if len(sub):
            result[col] = float(sub["baseline_value"].mean())
    return result


def load_defect_threshold_map() -> dict[str, dict]:
    """C유형(CLN_Pressure/Surface_Roughness)의 "불량률이 급변하는 경계값"을 컬럼별 대표값으로 로드.

    (26.08.05 추가) 이 두 컬럼은 멘토 SPEC(pipeline/mentor.py)에 없어서 그동안
    provisional_percentile(정상군 일평균 p0.5~p99.5)로 경계를 대체하고 있었는데, 그 값이
    실제 불량 발생 지점과 크게 어긋난다는 걸 확인했다 — CLN_Pressure의 임시 LSL은
    target에서 0.16σ(= 하루 ~270샷 평균의 표준오차 폭 그 자체, 즉 "일평균이 평소 얼마나
    흔들리나"를 잰 값)인데, 실제 Remain_Coat가 터지기 시작하는 지점은 target에서 1.60σ
    떨어진 296.90이다(9.8배 차이). 반면 Step0가 결정트리 스텀프로 학습한 이 threshold는
    10만 행 검증에서 경계 아래위로 불량률이 약 20배 점프하는 게 확인됐다
    (CLN_Pressure 20.6% -> 2.4%, Surface_Roughness 1.2% -> 20.8%).

    그래서 이 2개 컬럼만큼은 임시 percentile보다 이 threshold가 훨씬 나은 기준이라
    따로 쓴다(spec_source="defect_zone_rate"). 우선순위는 mentor_spec > defect_zone_rate
    > provisional_percentile.

    단, threshold 자체를 일평균과 직접 비교하지는 않는다 — threshold는 샷 단위 경계라
    일평균은 356일 내내 거기 못 닿는다. 실제 margin은 compute_daily_defect_zone_rate가
    센 "그날 위험구간에 들어간 샷 비율"로 계산한다(compute_level_and_trend 참고).

    Product_ID x Recipe_ID 54개 그룹별로 학습된 값이라 컬럼 대표값은 median을 쓴다
    (compute_spec_values가 baseline_median을 뽑는 방식과 동일 — level_trend는 OPCOND가
    아니라 장비x컬럼 단위라 그룹별 값을 그대로는 못 씀).
    """
    path = config.PREPROCESSING_DIR / "00_baseline_C.csv"
    if not path.exists():
        return {}
    c = pd.read_csv(path)
    result: dict[str, dict] = {}
    for col, g in c.groupby("column"):
        directions = g["risky_direction"].unique()
        if len(directions) != 1:
            # 그룹마다 위험 방향이 갈리면 대표값 하나로 못 줄임 — 임시 percentile로 폴백.
            print(f"[경고] {col}: risky_direction이 그룹별로 불일치({directions}) — defect_threshold 미적용")
            continue
        result[col] = {
            "threshold": float(g["threshold"].median()),
            "risky_direction": str(directions[0]),
            "matched_defect": str(g["matched_defect"].iloc[0]),
        }
    return result


def load_cusum_alert_lines() -> dict[str, dict[str, float | None]]:
    """A/B/E유형 컬럼의 "CUSUM 경보선"(무시선)을 원래 단위로 환산해서 컬럼별로 돌려준다.

    (26.08.06 추가) 왜 필요한가 — 지금 차트가 그리는 기준선은 LSL/USL/baseline 셋인데,
    **그중 실제로 경보를 결정하는 선은 하나도 없다.** 멘토 스펙 LSL/USL은 이 공정의 자연
    변동폭보다 훨씬 넓어서(9개 컬럼 중 7개가 89일 내내 위반 0건) 데이터에서 수십 시그마
    떨어져 있고, 정작 경보를 내는 건 trend_analysis.py의 CUSUM이다. 그래서 화면에서는
    실제 등락이 직선처럼 뭉개져 보이고(DP02 Laser_Power 30일치가 세로 220px 중 2.3px),
    "왜 경보가 떴는지"를 그래프로 설명할 수가 없었다(김시우님 지적).

    CUSUM은 매 샷 (z - K)를 누적하므로, 공정 평균이 baseline에서 K시그마 이내에 머무는
    한 누적합이 안 쌓여 **아무리 오래 있어도 경보가 안 뜬다**. 반대로 K시그마를 넘어선
    수준으로 지속되면 결국 경보가 뜬다. 즉 baseline ± CUSUM_K x std가 "이 선을 넘은
    상태가 지속되면 경보"라는 실질적 판정 경계다.

    주의: 이건 **지속되는 평균 수준**에 대한 선이지 샷/일평균 하나가 넘었다고 즉시
    경보가 뜨는 선이 아니다. 얼마나 빨리 뜨는지는 넘어선 폭에 달렸다(CUSUM_H / (편차 - K)
    샷 — 0.8시그마면 45샷, 2시그마면 3샷). 화면에 쓸 땐 "이 아래로 계속 있으면 경보"로
    읽어야 한다.

    trend_analysis.py와 같은 입력(00_baseline_AB/E + OPCOND별 std)과 같은 상수(CUSUM_K)를
    쓴다 — 상수를 여기 다시 적으면 튜닝값이 어긋날 수 있어서 직접 import한다. Product x
    Recipe 그룹별로 조금씩 다르므로 컬럼 대표값은 median을 쓴다(lsl/usl 표시값이 이미
    같은 방식). C유형은 CUSUM으로 판정하지 않으므로 제외한다.
    """
    from trend_analysis import CUSUM_K  # 튜닝된 K를 단일 출처로 공유(중복 정의 방지)

    ab_path = config.PREPROCESSING_DIR / "00_baseline_AB.csv"
    e_path = config.PREPROCESSING_DIR / "00_baseline_E.csv"
    std_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
    if not ab_path.exists() or not std_path.exists():
        return {}
    strat = pd.read_csv(std_path, usecols=["column", "std"])
    std_map = strat.groupby("column")["std"].median().to_dict()

    result: dict[str, dict[str, float | None]] = {}

    def _add(col: str, baseline: float, bad_direction: str | None):
        std = std_map.get(col)
        if not std or not np.isfinite(std) or std <= 0 or not np.isfinite(baseline):
            return
        lower = baseline - CUSUM_K * std
        upper = baseline + CUSUM_K * std
        # A유형은 나쁜 방향이 하나뿐이라 반대쪽 선은 경보와 무관 — 그리면 오해를 부른다.
        result[col] = {
            "lower": round(float(lower), 4) if bad_direction in (None, "down") else None,
            "upper": round(float(upper), 4) if bad_direction in (None, "up") else None,
        }

    ab = pd.read_csv(ab_path)
    for col, g in ab.groupby("column"):
        col_type = str(g["type"].iloc[0])
        bad_dir = g["bad_direction"].iloc[0] if "bad_direction" in g else None
        bad_dir = str(bad_dir) if col_type == "A" and pd.notna(bad_dir) else None
        _add(str(col), float(g["baseline_value"].median()), bad_dir)

    if e_path.exists():
        e = pd.read_csv(e_path)
        for col, g in e.groupby("column"):
            _add(str(col), float(g["baseline_value"].median()), None)  # E유형은 양방향

    return result


def _real_spec_margin_pct(raw_values: pd.Series, direction: str, lsl: float, target: float, usl: float) -> pd.Series:
    """멘토 실측 스펙(pipeline/mentor.py) 기준 margin_used_pct. 0=TARGET, 100=USL/LSL 도달.

    OPCOND 층별 정규화를 안 거치고 raw 값을 그대로 스펙과 비교한다 — 멘토가 준 스펙은
    Product/Recipe에 상관없는 절대 물리적 기준이라, 상대적 z-score가 아니라 실측값
    자체를 써야 맞다.
    """
    above = raw_values >= target
    margin = pd.Series(np.nan, index=raw_values.index, dtype=float)
    if usl > target:
        margin[above] = (raw_values[above] - target) / (usl - target) * 100
    if target > lsl:
        margin[~above] = (target - raw_values[~above]) / (target - lsl) * 100
    if direction == "up":
        margin[~above] = 0.0  # 위로만 위험한 변수는 target 아래로 벗어나도 여유 소진 아님
    elif direction == "down":
        margin[above] = 0.0
    return margin


def compute_level_and_trend(
    daily_series: pd.DataFrame, boundary_z: dict[str, float], spec_values: dict[str, dict],
    trend_status: dict[tuple[str, str], dict] | None = None,
    defect_threshold_map: dict[str, dict] | None = None,
    zone_rate_df: pd.DataFrame | None = None,
    target_override_map: dict[str, float] | None = None,
    cusum_lines: dict[str, dict[str, float | None]] | None = None,
    stratum_std_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    """장비×컬럼별로 "경보선까지 남은 여유"(레벨)와 "그 여유가 줄어드는 속도"(추세)를 계산한다.

    (26.08.08 개정) 기준선을 **전 컬럼 하나로 통일**했다 — CUSUM 경보선
    (target ± CUSUM_K x σ). 예전엔 컬럼마다 멘토 스펙(50~100σ) / 임시 백분위 경계 /
    이항 경보선을 각각 100%로 삼았는데, 경계가 σ 단위로 1000배까지 흩어져 있어서
    "경계까지 몇 %"끼리 비교가 안 됐다. 자세한 근거는 아래 margin 계산부 주석 참고.

      margin 100% = "이 수준이 지속되면 CUSUM 경보가 뜬다"

    멘토 스펙과 위험구간 진입률은 점수에서 빠지고 각각 spec_status / defect_zone_rate_pct
    로 따로 실린다 — 관리한계(경보선)와 스펙은 다른 축이라 한 점수에 섞지 않는다(Shewhart).
    실제 원래 단위 값(current_value/lsl/usl)도 같이 붙여서 "29.3% 사용"이 아니라 실제
    수치로 보여줄 수 있게 한다. 스펙이 있는 컬럼은 lsl/usl에 진짜 스펙을, 없는 컬럼은
    점수를 내는 경보선을 그대로 실어서 화면과 점수의 근거가 어긋나지 않게 한다.

    추세는 두 가지를 같이 담는다: margin_used_pct의 최근 14일 기울기로 뽑은 정량적
    "예상 며칠 뒤 스펙아웃"(margin_trend_pct_per_day/estimated_days_to_control_limit)과,
    trend_analysis.py(load_trend_warning_status)가 판정한 "지금 공식적으로 경보가
    켜져 있는가"(trend_direction/early_warning_active/trend_message) — 전자는 이
    스크립트가 직접 추정한 속도, 후자는 팀이 따로 검증한 판정 로직의 결과다.
    """
    trend_status = trend_status or {}
    defect_threshold_map = defect_threshold_map or {}
    target_override_map = target_override_map or {}
    cusum_lines = cusum_lines or {}
    stratum_std_map = stratum_std_map or {}
    from trend_analysis import CUSUM_K  # 튜닝된 K를 단일 출처로 공유(중복 정의 방지)

    # (machine, column) -> date별 위험구간 비율 Series / (machine, column) -> 그 장비의 정상 기준 비율
    zone_lookup: dict[tuple[str, str], pd.Series] = {}
    zone_shots: dict[tuple[str, str], pd.Series] = {}  # 그날 샷 수 — 이항 경계 계산에 필요
    zone_base_rate: dict[tuple[str, str], float] = {}
    # (26.08.06) "평소"는 그 장비 자신의 이력 기준이어야 맞다 — 4대 풀링 median을 쓰던 때는
    # CLN_Flow처럼 위험구간 진입이 DP04만의 일인 컬럼에서 나머지 3대의 "항상 0%"가 평소
    # 비율을 짓눌러(0.48%) DP04의 정상적 편차(7.53%)조차 1469%짜리 폭주로 보이게 만들었다.
    #
    # (26.08.08) 여기서 직접 median을 잡지 않고 step0 산출물을 읽는다. 예전엔 이 파일이
    # 일별 진입률의 median을, trend_analysis.py는 그룹별 진입률의 median을 썼다 — 같은
    # "평소 X%"가 화면과 경보에서 다른 수였다. 게다가 둘 다 89일 전체 × 전체 샷이라
    # 불량 샷과 열화 기간이 baseline에 섞였다(김시우님 지적). 이제 안정 구간 × OK샷으로
    # 잰 단일 출처를 양쪽이 같이 읽는다(config.py C_BASELINE_MIN_STABLE_DAYS 주석 참고).
    # zone_lookup(날짜별 실제 진입률)은 계속 일별 집계 파일에서 온다 — 이건 "지금 값"이라
    # baseline과 달리 전 구간이 필요하다.
    if zone_rate_df is not None and len(zone_rate_df):
        for (m, c), zg in zone_rate_df.groupby(["Machine_ID", "column"]):
            zg = zg.set_index("date").sort_index()
            zone_lookup[(m, c)] = zg["defect_zone_rate"]
            zone_shots[(m, c)] = zg["n_shots"]
    # 그룹별 비율의 median이 아니라 풀링(전체 진입 샷 / 전체 OK샷) — 근거는
    # trend_analysis.py compute_c_type_baseline_rate 주석 참고(희귀 사건에서 median이
    # 0으로 붕괴해 DP04 CLN_Flow의 크기 정보가 사라졌다).
    entry_path = config.PREPROCESSING_DIR / "00_baseline_C_entry_rate.csv"
    if entry_path.exists():
        entry = pd.read_csv(entry_path)
        agg = entry.groupby(["Machine_ID", "column"])[["n_in_zone", "n_ok_shots"]].sum()
        for (m, c), v in (agg["n_in_zone"] / agg["n_ok_shots"]).items():
            zone_base_rate[(m, c)] = float(v)

    rows = []
    for (machine, col), g in daily_series.groupby(["Machine_ID", "column"]):
        g = g.sort_values("date")
        direction = direction_of(col)
        real_spec = SPEC.get(col)
        defect_thr = defect_threshold_map.get(col)
        zone_rate_now = None

        # -------------------------------------------------------------------
        # (26.08.08 개정) margin의 기준선을 **모든 컬럼에서 하나로 통일**한다.
        #
        # 예전엔 컬럼마다 다른 경계를 100%로 삼았는데, 그 경계들이 목표값에서 떨어진
        # 거리가 σ 단위로 1000배까지 차이났다:
        #
        #   CUSUM 경보선   0.7σ        (전 컬럼)
        #   이항 경보선    일별 진입률의 ~2.3σ — n이 커서 절대폭이 6.4%p까지 좁아짐
        #   멘토 LSL/USL   50~100σ     (10개 컬럼)
        #
        # "경계까지 몇 %"는 경계가 0.7σ와 100σ에 흩어져 있으면 원리적으로 비교가
        # 안 된다. 실측 결과가 정확히 그랬다 — 멘토 스펙 컬럼 40개는 margin이 최대
        # 8.6%에 갇히고(스펙이 자연 변동폭의 50~100배라 아무리 나빠져도 한 자릿수),
        # 진입률 컬럼 12개는 2426%까지 치솟아, min()으로 고르면 **장비 4대 전부
        # 진입률 컬럼이 주범**으로 나왔다. DP02 Laser_Power는 56일째 CUSUM 경보에
        # 경보선까지 넘긴 상태인데 margin 8.6%라 3순위였다.
        #
        # 진입률 분모가 특히 나쁜 이유: 여유폭(경보선 - 평소)이 6.4%p / 0.7%p다.
        # 하루 280샷이라 비율이 정밀하게 측정되고, 정밀하면 작은 변화도 통계적으로
        # 확실해져서 경보선이 평소값 바로 옆에 붙는다. 즉 **탐지가 쉬울수록 margin이
        # 커진다** — 심각도 척도로 쓰면 안 되는 성질이다(정밀한 체온계로 재면
        # 36.5->36.8도 "확실한 상승"이지만 265% 아픈 게 아니다).
        #
        # 그래서 기준선을 σ 하나로 통일한다: **CUSUM 경보선(target ± CUSUM_K x σ)**.
        # 이미 전 컬럼에 CUSUM을 걸고 있으므로(커밋 1947b31) 이건 "실제로 경보를
        # 내는 선"이고, 화면에도 이미 cusum_alert_lower/upper로 그리고 있다.
        #   margin 100% = "이 수준이 지속되면 CUSUM 경보가 뜬다"
        # 멘토 스펙과 진입률은 점수에서 빠지고 각각 spec_status / defect_zone_rate_pct
        # 로 **따로** 표시된다 — Shewhart 원칙대로 관리한계와 스펙을 한 축에 안 섞는다.
        # -------------------------------------------------------------------
        spec_source = "control_limit_3sigma"
        if real_spec is not None:
            # 표시용 LSL/USL은 진짜 스펙이 있으면 그걸 쓴다(사람이 읽는 절대 기준).
            lsl_disp, usl_disp = real_spec["LSL"], real_spec["USL"]
            # TARGET(정상 기준값)은 멘토 값을 쓰되, TARGET_RECOMPUTE_FROM_DATA에 있는
            # 컬럼은 실측 OK median으로 바꾼다 — load_target_override_map docstring 참고
            # (멘토 TARGET과 스펙폭의 12% 어긋남, 89일 내내 안 줄어드는 정적 오프셋이라
            # 반복 오탐의 원인이었음).
            baseline_disp = target_override_map.get(col, real_spec["TARGET"])
            spec_source = ("mentor_spec_recomputed_target" if col in target_override_map
                           else "mentor_spec") + "+control_limit_3sigma"
        elif spec_values.get(col):
            baseline_disp = spec_values[col]["baseline_median"]
            lsl_disp = usl_disp = np.nan
        else:
            continue

        # (26.08.08 개정 2) margin 100%를 **Shewhart 관리한계(목표값 ± 3σ)**에 건다.
        #
        # 직전 버전은 CUSUM 경보선(0.7σ)에 걸었는데, 0.7σ는 **탐지 문턱**이지 심각도가
        # 아니다. 그래서 경보가 확정된 컬럼은 무엇이든 margin 100%를 넘어 10점 이하로
        # 떨어졌다 — DP02 Laser_Power는 목표값에서 0.72σ, 멘토 스펙 여유는 8.6%밖에
        # 안 썼는데 9.7점이었다(김시우님 지적). 이 데이터의 실제 열화가 0.5~2.7σ라
        # 0.7σ 기준선으로는 전부 바닥을 친다.
        #
        # 이건 내가 이항 경보선을 두고 "탐지 문턱을 심각도 자로 쓰면 안 된다"고 지적한
        # 것과 같은 잘못이었다 — 척도를 통일하면서 같은 성질을 전 컬럼에 옮겼다.
        #
        # 3σ를 쓰는 이유: Shewhart 관리한계가 SPC에서 "공정이 관리 이탈"의 표준선이고,
        # 교과서 상수라 우리가 고른 값이 아니며, σ만 있으면 전 컬럼에 똑같이 적용된다.
        # 그 결과 **"10점 미만 = 관리한계 초과"**로 읽는 법에 의미가 생긴다(예전엔
        # "탐지됐다"일 뿐이었다).
        #
        # 역할 분담도 깔끔해진다 — margin은 "얼마나 벗어났나"(심각도), 추세 페널티는
        # "확정된 이상인가, 얼마나 오래/급한가"(확신도). CUSUM 경보 정보는 페널티가
        # 이미 나르고 있으므로 margin이 다시 나를 필요가 없다.
        # cusum_alert_lower/upper는 화면에 계속 그린다 — "왜 경보가 떴는지"를 보여주는
        # 선이라 점수 기준선과 별개로 쓸모가 있다.
        # (26.08.10) **관리한계는 A/B/C/E 전 유형에 양쪽 다 만든다. 점수는 위험한 쪽만
        # 센다.** 예전엔 편측 컬럼의 안전한 쪽 선을 아예 안 만들었는데, 그러면 엔지니어가
        # 화면에서 정상 변동폭(±3σ)이 얼마인지를 볼 수 없다 — Shewhart 관리도는 원래 양쪽을
        # 다 그리고, 한쪽 이탈만 조치 대상인 것과 "선을 안 그리는 것"은 다른 얘기다.
        #
        # 그래서 두 쌍으로 분리한다:
        #   ctrl_lo/ctrl_up   = 정상값 ± 3σ. 항상 양쪽. **표시 전용**
        #   score_lo/score_up = 위험한 쪽만. **margin/점수 전용**
        # 섞으면 CLN_Flow(유량 감소가 위험)가 유량이 올라갔다고 점수를 잃는다 — 세정이
        # 더 잘 되고 있는데 경보가 뜨는 셈이라 명백히 틀린다.
        sd = stratum_std_map.get(col)
        ctrl_lo = ctrl_up = None
        if sd and np.isfinite(sd) and sd > 0 and np.isfinite(baseline_disp):
            ctrl_up = baseline_disp + CONTROL_LIMIT_SIGMA * sd
            ctrl_lo = baseline_disp - CONTROL_LIMIT_SIGMA * sd
        if ctrl_lo is None and ctrl_up is None:
            continue

        # 점수를 내는 쪽. direction_of가 관계DB의 방향을 이미 반영한다.
        score_up = ctrl_up if direction != "down" else None
        score_lo = ctrl_lo if direction != "up" else None

        vals = g["daily_mean"]
        above = vals >= baseline_disp
        margin_pct = pd.Series(0.0, index=g.index, dtype=float)
        if score_up is not None and score_up != baseline_disp:
            margin_pct[above] = (vals[above] - baseline_disp) / (score_up - baseline_disp) * 100
        if score_lo is not None and score_lo != baseline_disp:
            margin_pct[~above] = (baseline_disp - vals[~above]) / (baseline_disp - score_lo) * 100
        margin_pct = margin_pct.clip(lower=0.0)
        margin_pct[vals.isna()] = np.nan

        if real_spec is None:
            # 진짜 스펙이 없는 컬럼은 표시 경계도 점수를 내는 선과 같게 둔다 — 예전엔
            # 임시 백분위 경계(provisional_percentile)를 보여줬는데, 그 선은 점수 계산에
            # 쓰이지도 않으면서 "스펙처럼" 읽혔다.
            # 표시용이므로 양쪽 관리한계를 그대로 쓴다(ctrl_*). 예전엔 baseline_disp로
            # 채웠는데 "정상값 == 한계선"이 되어 화면에 정상값 자리에 빨간 한계선이
            # 그려졌다(DP01 Surface_Roughness: baseline 0.5832 = lsl 0.5832).
            lsl_disp = ctrl_lo if ctrl_lo is not None else np.nan
            usl_disp = ctrl_up if ctrl_up is not None else np.nan

        # 진입률은 점수에서 빠지지만 화면/agent 문구의 근거라 계속 계산한다.
        if defect_thr is not None and (machine, col) in zone_lookup:
            zone_rate_now = zone_lookup[(machine, col)].reindex(g["date"].values).values

        # (26.08.08) spec_status를 margin이 아니라 **진짜 멘토 스펙 위반**으로 판정한다.
        # 예전엔 margin>=100을 SPEC_OUT으로 표시했는데, margin의 100% 지점이 컬럼마다
        # 스펙이 아니었다(임시 백분위 경계, 이항 경보선). 그래서 화면에 "스펙아웃" 4건이
        # 떴지만 그중 스펙이 있는 컬럼은 0건이었다 — 멘토 스펙 기준 실제 위반은 89일
        # 17,203행 검사 중 34행(0.2%)뿐이고 지속 위반 경보는 0건이다.
        spec_violating = (
            ((vals < real_spec["LSL"]) | (vals > real_spec["USL"]))
            if real_spec is not None else pd.Series(False, index=g.index)
        )

        valid = margin_pct.dropna()
        if valid.empty:
            continue
        latest_idx = valid.index[-1]
        latest_pos = g.index.get_loc(latest_idx)  # zone_rate_now(위치 기반 배열) 조회용
        latest_date = g.loc[latest_idx, "date"]
        # (26.08.08) "현재 상태"를 마지막 하루가 아니라 최근 RECENT_DEFECT_WINDOW_DAYS일의
        # 중앙값으로 잡는다. 예전엔 valid.iloc[-1](하루치)을 썼는데, 이 신호의 일별 변동이
        # 그 자체로 크다 — CLN_Pressure 진입률은 4대 모두 89일 평균 6.76~7.11%에 표준편차
        # 1.30~1.67%p로, 하루 사이 4%p씩 튄다. 그래서 3/30 하루의 1.1%p 차이(DP01 7.41%
        # vs DP02 6.29%, 표준편차보다도 작은 노이즈)만으로 Remain_Coat 건강도가 57.9 대
        # 83.1로 25점 갈렸고, 추세 페널티를 0으로 놔도 드리프트 17개인 DP02가 4개인
        # DP01보다 좋게 나왔다(김시우님 지적). 7일 중앙값으로 재면 DP01 6.59% /
        # DP02 6.57%로 차이가 사라지고 89일 평균과도 맞는다.
        # 창 길이는 이미 "최근"의 의미로 쓰는 RECENT_DEFECT_WINDOW_DAYS를 재사용한다.
        # median을 쓰는 것도 이 파이프라인이 baseline/threshold에서 쓰는 방식과 같다.
        window = valid.iloc[-RECENT_DEFECT_WINDOW_DAYS:]
        current_margin_pct = float(window.median())
        value_window = g.loc[window.index, "daily_mean"].dropna()
        current_value = float(value_window.median()) if len(value_window) else float(
            g.loc[latest_idx, "daily_mean"])
        # 예전엔 margin_used_pct를 100%에서 clip해서, 경계를 살짝 넘은 것(margin 105%)과
        # 몇 배로 폭주한 것(margin 291%)이 똑같이 "HI 0.0"으로 뭉개졌다 — worst_factors/
        # worst_defects/장비 순위에서 뭐가 더 급한지 구분이 안 됐다(김시우님 피드백).
        # 지금은 0~100은 유지하면서 아래쪽 ALARM_BAND점을 경보선 초과 전용 구간으로 써서
        # 그 안에서도 순위가 갈리게 한다 — ALARM_BAND 주석 참고.
        health_index_var = margin_to_health(current_margin_pct)
        # 경보선을 넘었는가(점수 밴드/추세 페널티 게이트). 스펙 위반과는 다른 축이다.
        alarm_exceeded = current_margin_pct >= 100
        # 스펙 위반은 최근 창에서 한 번이라도 LSL/USL 밖으로 나갔는가로 따로 판정한다.
        spec_out = bool(spec_violating.loc[window.index].any())

        recent = valid.iloc[-RECENT_WINDOW_DAYS:]
        margin_slope, est_days = None, None
        if len(recent) >= 3 and recent.nunique() > 1:
            x = np.arange(len(recent))
            lr = scipy_stats.linregress(x, recent.values)
            margin_slope = float(lr.slope)  # %/일 (양수=여유가 줄어드는 중)
            if not alarm_exceeded and margin_slope > 1e-9:
                remaining = 100 - current_margin_pct
                projected = remaining / margin_slope
                est_days = round(projected, 1) if projected <= 365 else None  # 1년 넘게 남으면 "임박 아님" 취급
            # 이미 경보선을 넘었으면 "며칠 뒤"는 의미 없으므로 est_days는 None으로 둔다.

        ta_status = trend_status.get((machine, col), {})

        # (26.08.11) 경보의 **세기**. 아래 페널티 배율에 쓰는 값을 그대로 내보낸다 —
        # 화면과 agent가 early_warning_active(boolean)만 읽어서 "10,513행 39.6일째"와
        # "31행 0.2일째"를 똑같은 `경보` 배지로 그리고 있었다(docs/점검_원인변수_경보기준.md).
        # 활성 경보 76건 중 63건이 세기 0.5 미만이고 그 63건의 HI가 전부 96 이상이라,
        # 사실상 "HI 99인데 빨간 경보"가 화면의 기본 상태였다.
        #
        # 새 기준을 만들지 않고 **점수가 이미 쓰고 있는 값**을 그대로 표시로 보낸다.
        # 그래야 배지와 점수가 서로 다른 말을 할 수 없다 — 배지가 빨간데 HI가 99인
        # 지금 상태가 정확히 그 어긋남이었다. 경보가 없으면 None.
        alert_strength, alert_level = None, None
        if ta_status.get("early_warning_active"):
            maturity = min(1.0, (ta_status.get("alert_active_days") or 0.0) / RECENT_WINDOW_DAYS)
            urgency = min(1.0, RECENT_WINDOW_DAYS / est_days) if est_days else 0.0
            alert_strength = round(max(maturity, urgency), 3)
            # "full" = 페널티를 최대폭(TREND_PENALTY_MAX_CUT)까지 다 받은 경보. 즉 점수가
            # 이미 이 경보를 통째로 반영했다는 뜻이라, 여기서만 강조 표시를 쓴다.
            alert_level = "full" if alert_strength >= 1.0 else "early"

        # 추세 페널티는 "스펙 안" 구간(ALARM_BAND 위)에서만, 그 구간 안에서만 깎는다.
        #  - 이미 SPEC_OUT이면 안 깎는다: margin 자체가 이미 심각하다고 말하고 있어서 추세가
        #    추가로 알려줄 정보가 없다(이 페널티의 존재 목적 자체가 "margin은 멀쩡해 보이는데
        #    추세가 나쁜" 사각지대를 잡는 것이었음).
        #  - 스펙 안이면 ALARM_BAND 위에 남은 몫(excess)만 깎는다. 점수 전체에 배율을
        #    곱하면 스펙 안인 변수가 스펙아웃 전용 구간(0~10) 안으로 내려가 "10점 미만 =
        #    이미 스펙아웃"이라는 읽는 법이 깨진다.
        if alert_strength is not None and not alarm_exceeded:
            # (26.08.08) 예전엔 성숙도(경보 지속일)만 썼다. 그러면 "방금 뜬 급한 경보"가
            # 거의 안 깎여서 순위가 뒤집힌다 — DP03에서 CLN_Pressure(17.8일 뒤 스펙아웃,
            # 경보 0.1일째)가 66.3점으로, Head_Temp(41.8일째지만 기울기 -0.02로 오히려
            # 개선 중, margin 3.2%)의 53.6점보다 건강하게 나왔다.
            #
            # 그렇다고 기울기로 **대체**하면 반대쪽을 잃는다 — 실측상 지속일과 기울기의
            # 순위상관은 0.077로 사실상 무관하고, 활성 경보 75건 중 30건(40%)은 기울기가
            # 음수다. DP02 Laser_Power(56일 지속, 기울기 0.066)처럼 확정된 느린 열화는
            # 기울기로는 안 잡힌다.
            #
            # 두 축은 각각 독립적으로 "이건 문제다"라고 말할 수 있다:
            #   성숙도 = 증거가 쌓였나   (14일이면 완성)
            #   긴급도 = 곧 터지나       (14일 안에 스펙아웃이면 최대)
            # 그래서 둘 중 큰 쪽을 쓴다 — 둘 다 약할 때만 안 깎는다. 두 축 모두 기준을
            # RECENT_WINDOW_DAYS 하나로 쓰므로 새로 고른 상수가 없다. est_days는 이미
            # 계산해서 화면에 보여주던 값이고(remaining/slope), 기울기가 0 이하면 None이라
            # "개선 중"이 자동으로 긴급도 0이 된다.
            # (26.08.11) max(maturity, urgency) 자체는 바로 위에서 alert_strength로 미리
            # 계산해둔다 — 같은 값을 화면·agent에도 내보내야 배지와 점수가 어긋나지 않는다.
            excess = health_index_var - ALARM_BAND
            health_index_var = ALARM_BAND + excess * (
                1 - TREND_PENALTY_MAX_CUT * alert_strength)

        rows.append({
            "Machine_ID": machine,
            "column": col,
            "direction": direction,
            "latest_date": str(latest_date.date()),
            "current_value": round(current_value, 4),
            "baseline_median": round(baseline_disp, 4),
            "lsl": round(lsl_disp, 4),
            "usl": round(usl_disp, 4),
            "spec_source": spec_source,
            "spec_status": "SPEC_OUT" if spec_out else "OK",
            # 실제로 경보를 결정하는 선(있으면). lsl/usl과 달리 데이터 바로 근처에 있어서
            # 그래프에 그리면 "왜 경보가 떴는지"가 눈에 보인다 — load_cusum_alert_lines 참고.
            "cusum_alert_lower": (cusum_lines.get(col) or {}).get("lower"),
            "cusum_alert_upper": (cusum_lines.get(col) or {}).get("upper"),
            # (26.08.08) margin/health를 실제로 결정하는 선 = 관리한계(목표값 ± 3σ).
            # lsl/usl은 멘토 스펙이 있으면 그걸 보여주는데(사람이 읽는 절대 기준),
            # 그러면 화면의 한계값과 margin의 기준이 어긋난다 — 예: DP02 Laser_Power는
            # 현재 18.44 / 스펙 하한 17.80이라 여유가 많아 보이는데 margin은 24%다
            # (관리한계 18.25 기준). 두 선을 다 실어서 어느 쪽 기준인지 보이게 한다.
            #
            # (26.08.10) control_lsl/usl은 **전 유형 양쪽 다** 채운다 — 정상 변동폭(±3σ)이
            # 얼마인지는 편측 컬럼에서도 봐야 하는 정보다. 다만 점수를 내는 건 위험한
            # 쪽뿐이라, 어느 쪽이 점수 기준인지는 아래 score_side로 따로 알려준다.
            # 이걸 안 실으면 화면이 CLN_Flow의 위쪽 선을 보고 "여기 넘으면 위험"이라고
            # 오해할 수 있다(유량이 늘어나는 건 위험이 아니다).
            "control_lsl": round(ctrl_lo, 4) if ctrl_lo is not None else None,
            "control_usl": round(ctrl_up, 4) if ctrl_up is not None else None,
            "score_side": ("both" if score_lo is not None and score_up is not None
                           else "upper" if score_up is not None
                           else "lower" if score_lo is not None else "none"),
            # defect_zone_rate 컬럼 전용: margin/health가 "값이 경계에서 얼마나 떨어졌나"가
            # 아니라 "위험구간 샷 비율이 평소 대비 얼마나 늘었나"에서 나온다는 걸 알 수 있게
            # 실제 비율을 그대로 같이 싣는다(다른 컬럼은 None).
            # margin과 같은 창(최근 RECENT_DEFECT_WINDOW_DAYS일 중앙값)으로 낸다 —
            # 화면에 보이는 진입률과 점수의 근거가 어긋나면 안 된다.
            "defect_zone_rate_pct": (
                round(float(np.nanmedian(zone_rate_now[
                    [g.index.get_loc(i) for i in window.index]])) * 100, 2)
                if zone_rate_now is not None
                and np.isfinite(np.nanmedian(zone_rate_now[
                    [g.index.get_loc(i) for i in window.index]])) else None
            ),
            "defect_zone_baseline_pct": (
                # spec_source 문자열이 아니라 "이 컬럼에 zone 근거가 실제로 있었는가"로 판정.
                # 스펙+zone을 둘 다 가진 컬럼이 생기면서 문자열 비교로는 안 걸린다.
                round(zone_base_rate.get((machine, col), 0.0) * 100, 2) if zone_rate_now is not None else None
            ),
            "margin_used_pct": round(current_margin_pct, 1),
            "health_index": round(health_index_var, 1),
            "margin_trend_pct_per_day": round(margin_slope, 3) if margin_slope is not None else None,
            "estimated_days_to_control_limit": est_days,
            "trend_direction": ta_status.get("trend_direction"),
            # 1.0에 가까울수록 한 방향으로 확실히 쏠린 것, 0.5에 가까우면 방향이 섞여
            # 있어서 "추세"라고 부르기 어렵다 — 소비자가 구분할 수 있게 같이 낸다.
            "trend_direction_share": ta_status.get("trend_direction_share"),
            "early_warning_active": ta_status.get("early_warning_active", False),
            "trend_message": ta_status.get("trend_message"),
            "alert_since": ta_status.get("alert_since"),
            "alert_active_days": ta_status.get("alert_active_days"),
            # 경보의 세기(0~1)와 그 세기가 최대인지 여부. early_warning_active가 "켜졌나"만
            # 말한다면 이 둘은 "얼마나 큰 경보인가"를 말한다 — 점수가 쓰는 값과 같다.
            "alert_strength": alert_strength,
            "alert_level": alert_level,
            "recipe_hotspots": ta_status.get("recipe_hotspots", []),
            "n_product_recipe_combos_affected": ta_status.get("n_product_recipe_combos_affected"),
            "recipe_hotspot_concentrated": ta_status.get("recipe_hotspot_concentrated", False),
            "is_cause_factor": col in CAUSE_COLS,
        })
    return pd.DataFrame(rows)


TOP_N = 3  # 순위 표시 개수 — "제일 나쁜 것 하나"만 보여주지 말고 상위 N개를 보여달라는 피드백 반영


def aggregate_health_index(level_trend: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """변수별 Health Index를 defect별 -> 장비별로 집계한다 (둘 다 '최솟값' 규칙).

    평균이 아니라 최솟값을 쓰는 이유: 여러 원인변수 중 하나라도 심각하게 나쁘면
    그 defect 전체가 위험해야 한다 — "약한 고리가 전체를 결정한다"는 원칙이라
    가중치처럼 임의로 정할 여지가 없다. 대표값(최솟값)과 별개로, 상위 TOP_N개
    순위(worst_factors/worst_defects)도 같이 담아서 "제일 나쁜 것 하나"만 보여주지
    않고 여러 개를 순서대로 볼 수 있게 한다.
    """
    cause_rows = level_trend[level_trend["is_cause_factor"]]

    defect_rows = []
    for (machine, defect), _ in [
        ((m, d), None) for m in cause_rows["Machine_ID"].unique() for d in DEFECT_RATE_COLS
    ]:
        factor_names = [f for f, meta in HEALTH_FACTORS.items() if defect in _usable_defects(meta)]
        sub = cause_rows[(cause_rows["Machine_ID"] == machine) & (cause_rows["column"].isin(factor_names))]
        if sub.empty:
            continue
        ranked = sub.sort_values("health_index").head(TOP_N)
        worst = ranked.iloc[0]
        defect_rows.append({
            "Machine_ID": machine,
            "defect": defect,
            "health_index": worst["health_index"],
            "worst_factor": worst["column"],
            # 이 defect의 원인 중 방향이 반박되지 않은 게 하나라도 있는가 —
            # 없으면 건강도는 계속 내되 장비 대표 점수에서는 뺀다(_load_verified_pairs 참고).
            "scored": any(defect in _scored_defects(meta, f)
                          for f, meta in HEALTH_FACTORS.items()),
            "worst_factors": [
                {"factor": r["column"], "health_index": r["health_index"], "spec_status": r["spec_status"]}
                for _, r in ranked.iterrows()
            ],
        })
    defect_index = pd.DataFrame(defect_rows)

    unscored = defect_index.loc[~defect_index["scored"], "defect"].unique()
    if len(unscored):
        print(f"[관계DB] 장비 대표 점수에서 제외(repro_state=실패, 방향 불일치): {sorted(unscored)} "
              "— 건강도는 계속 산출되고 경보로 나갑니다.")

    machine_rows = []
    for machine, g in defect_index[defect_index["scored"]].groupby("Machine_ID"):
        ranked = g.sort_values("health_index").head(TOP_N)
        worst = ranked.iloc[0]
        machine_rows.append({
            "Machine_ID": machine,
            "health_index": worst["health_index"],
            "worst_defect": worst["defect"],
            "worst_defects": [
                {"defect": r["defect"], "health_index": r["health_index"], "worst_factor": r["worst_factor"]}
                for _, r in ranked.iterrows()
            ],
        })
    machine_index = pd.DataFrame(machine_rows)

    return defect_index, machine_index


def load_defect_occurrence() -> pd.DataFrame:
    """05_machine_daily_trend.csv(Step0 산출물)로 최근 실제 발생 여부 판정.

    (26.08.07) 이 파일은 원래 analysis_step_by_step.py가 만들었는데, 그 스크립트는 8/1
    이후 정지된 초기 탐색용이라 실행 순서 안내에 없었다 — 원본이 바뀌면 이 파일만 낡은
    채 남아 "최근 7일"을 옛날 데이터로 판정할 위험이 있어서 step0로 옮겼다. 이제
    step0_preprocessing만 돌리면 같이 갱신된다.
    """
    trend = pd.read_csv(REPO_ROOT / "analysis_outputs" / "05_machine_daily_trend.csv")
    trend["date"] = pd.to_datetime(trend["date"])
    cutoff = trend["date"].max() - pd.Timedelta(days=RECENT_DEFECT_WINDOW_DAYS)
    recent = trend[trend["date"] > cutoff]

    rows = []
    for machine, g in recent.groupby("Machine_ID"):
        for defect, rate_col in DEFECT_RATE_COLS.items():
            occurred = bool((g[rate_col] > 0).any())
            count_days = int((g[rate_col] > 0).sum())
            rows.append({
                "Machine_ID": machine,
                "defect": defect,
                "actual_occurred_recent_7d": occurred,
                "occurred_days_recent_7d": count_days,
            })
    return pd.DataFrame(rows)


def _none_if_nan(value):
    """DataFrame에 섞여 들어간 None이 NaN으로 바뀌는 걸 JSON 출력 직전에 되돌린다."""
    return None if pd.isna(value) else value


def build_machine_snapshot(
    level_trend: pd.DataFrame, occurrence: pd.DataFrame,
    defect_index: pd.DataFrame, machine_index: pd.DataFrame,
) -> dict:
    """장비별로 Health Index(장비/defect/변수 3단계) + 실제발생 여부 + 미확인 이상을 묶는다."""
    machines: dict[str, dict] = {}

    for machine, g in level_trend.groupby("Machine_ID"):
        cause_rows = g[g["is_cause_factor"]]
        other_rows = g[~g["is_cause_factor"]]

        # defect별로 원인변수 묶기
        defect_signals: dict[str, dict] = {}
        for defect in DEFECT_RATE_COLS:
            factor_names = [f for f, meta in HEALTH_FACTORS.items() if defect in _usable_defects(meta)]
            factor_rows = cause_rows[cause_rows["column"].isin(factor_names)]
            if factor_rows.empty:
                continue
            causes = {}
            for _, row in factor_rows.iterrows():
                meta = HEALTH_FACTORS[row["column"]]
                causes[row["column"]] = {
                    "current_value": row["current_value"],
                    "baseline_median": row["baseline_median"],
                    # 편측 컬럼은 없는 쪽이 NaN이다 — JSON에 NaN을 그대로 실으면 브라우저
                    # JSON.parse가 죽으므로 반드시 None으로 바꿔서 내보낸다.
                    "lsl": _none_if_nan(row["lsl"]),
                    "usl": _none_if_nan(row["usl"]),
                    # 점수를 실제로 내는 선. lsl/usl은 멘토 스펙이 있으면 그걸 보여주므로
                    # margin과 기준이 다를 수 있다(compute_level_and_trend 주석 참고).
                    "control_lsl": _none_if_nan(row["control_lsl"]),
                    "control_usl": _none_if_nan(row["control_usl"]),
                    # 관리한계는 양쪽 다 있지만 점수를 내는 건 이쪽뿐이다(upper/lower/both).
                    "score_side": row["score_side"],
                    # SYSTEM_PROMPT가 3곳에서 참조하는데 payload에 없었다 —
                    # "레벨은 아직 여유 있는데 추세 때문에 점수가 깎였다"를 agent가
                    # 설명하려면 health_index와 margin을 둘 다 봐야 한다.
                    "margin_used_pct": _none_if_nan(row["margin_used_pct"]),
                    "spec_source": row["spec_source"],
                    "spec_status": row["spec_status"],
                    "health_index": row["health_index"],
                    "defect_zone_rate_pct": _none_if_nan(row["defect_zone_rate_pct"]),
                    "defect_zone_baseline_pct": _none_if_nan(row["defect_zone_baseline_pct"]),
                    "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                    "estimated_days_to_control_limit": _none_if_nan(row["estimated_days_to_control_limit"]),
                    "trend_direction": _none_if_nan(row["trend_direction"]),
                    "early_warning_active": bool(row["early_warning_active"]),
                    "trend_message": _none_if_nan(row["trend_message"]),
                    "alert_since": _none_if_nan(row["alert_since"]),
                    "alert_active_days": _none_if_nan(row["alert_active_days"]),
                    "alert_strength": _none_if_nan(row["alert_strength"]),
                    "alert_level": _none_if_nan(row["alert_level"]),
                    "recipe_hotspots": row["recipe_hotspots"],
                    "n_product_recipe_combos_affected": _none_if_nan(row["n_product_recipe_combos_affected"]),
                    "recipe_hotspot_concentrated": bool(row["recipe_hotspot_concentrated"]),
                    "direction": meta["direction"],
                    "mechanism": meta["mechanism"],
                    "source": meta["owner"],
                    # (26.08.08) 조치 가능 여부 — 관계DB agent_rules 6번 "role이 감시지표인
                    # 인자에 조치를 지시하지 말 것. 경보만." 을 agent가 지킬 수 있게 싣는다.
                    # Surface_Roughness는 결과 지표라 조정 대상이 아니다.
                    "role": meta.get("role", "원인(FDC)"),
                    "actionable": bool(meta.get("actionable", True)),
                }
            occ = occurrence[(occurrence["Machine_ID"] == machine) & (occurrence["defect"] == defect)]
            d_idx = defect_index[(defect_index["Machine_ID"] == machine) & (defect_index["defect"] == defect)]
            # scored=False면 건강도는 있지만 장비 대표 점수에는 안 들어간다 —
            # 감시 데이터에서 인과가 검증 안 된 짝이라(_load_verified_pairs 참고).
            # agent가 "왜 점수에 없는데 경보가 뜨는지" 답할 수 있게 사유를 같이 싣는다.
            scored = bool(d_idx["scored"].iloc[0]) if len(d_idx) else False
            defect_signals[defect] = {
                "health_index": float(d_idx["health_index"].iloc[0]) if len(d_idx) else None,
                "counts_toward_machine_score": scored,
                "not_scored_reason": None if scored else (
                    "데이터가 도메인 기대와 반대 방향을 가리킴"
                    "(관계DB repro_state=실패) — 경보로만 사용, 장비 점수 제외"),
                "worst_factors": d_idx["worst_factors"].iloc[0] if len(d_idx) else [],
                "actual_occurred_recent_7d": bool(occ["actual_occurred_recent_7d"].iloc[0]) if len(occ) else False,
                "occurred_days_recent_7d": int(occ["occurred_days_recent_7d"].iloc[0]) if len(occ) else 0,
                "causes": causes,
            }

        # 미확인 이상(안전망): 확정 원인이 아닌 변수 중 (a) 경보선까지 여유를 많이 썼거나
        # (b) 성숙한 지속 경보가 켜져 있는 것. (b)가 없으면 "값은 여유 있는데 추세가
        # 확실히 이상한" 것이 통째로 빠진다 — ANOMALY_SUSTAINED_ALERT_DAYS 주석 참고.
        anomalies = []
        sustained = (other_rows["early_warning_active"].fillna(False).astype(bool)
                     & (other_rows["alert_active_days"].fillna(0) >= ANOMALY_SUSTAINED_ALERT_DAYS))
        flagged = other_rows[(other_rows["margin_used_pct"] >= ANOMALY_MARGIN_THRESHOLD_PCT) | sustained]
        # margin이 큰 순이 아니라 "경보가 오래 지속된 순 -> margin 큰 순"으로 정렬한다.
        # 지속일이 곧 증거의 강도라, 값만 크고 방금 뜬 것보다 먼저 봐야 한다.
        for _, row in flagged.sort_values(
                ["alert_active_days", "margin_used_pct"], ascending=False, na_position="last").iterrows():
            anomalies.append({
                "column": row["column"],
                "current_value": row["current_value"],
                "baseline_median": row["baseline_median"],
                "lsl": _none_if_nan(row["lsl"]),
                "usl": _none_if_nan(row["usl"]),
                "control_lsl": _none_if_nan(row["control_lsl"]),
                "control_usl": _none_if_nan(row["control_usl"]),
                "score_side": row["score_side"],
                "spec_source": row["spec_source"],
                "spec_status": row["spec_status"],
                "defect_zone_rate_pct": _none_if_nan(row["defect_zone_rate_pct"]),
                "defect_zone_baseline_pct": _none_if_nan(row["defect_zone_baseline_pct"]),
                "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                "estimated_days_to_control_limit": _none_if_nan(row["estimated_days_to_control_limit"]),
                "trend_direction": _none_if_nan(row["trend_direction"]),
                "early_warning_active": bool(row["early_warning_active"]),
                "trend_message": _none_if_nan(row["trend_message"]),
                "alert_since": _none_if_nan(row["alert_since"]),
                "alert_active_days": _none_if_nan(row["alert_active_days"]),
                "alert_strength": _none_if_nan(row["alert_strength"]),
                "alert_level": _none_if_nan(row["alert_level"]),
                "recipe_hotspots": row["recipe_hotspots"],
                "n_product_recipe_combos_affected": _none_if_nan(row["n_product_recipe_combos_affected"]),
                "recipe_hotspot_concentrated": bool(row["recipe_hotspot_concentrated"]),
                "note": "확정 원인 아님 — 어느 defect와 연결되는지 검증 안 됨, 모니터링 참고용",
            })

        m_idx = machine_index[machine_index["Machine_ID"] == machine]
        machines[machine] = {
            "health_index": float(m_idx["health_index"].iloc[0]) if len(m_idx) else None,
            "worst_defects": m_idx["worst_defects"].iloc[0] if len(m_idx) else [],
            "latest_date": g["latest_date"].max(),
            "defect_signals": defect_signals,
            "unconfirmed_anomalies": anomalies,
        }
    return machines


def main() -> None:
    opcond_baseline, daily_series_raw = load_step0_outputs()

    boundary_z = compute_daily_boundary_z(daily_series_raw)
    spec_values = compute_spec_values(opcond_baseline)
    trend_status = load_trend_warning_status()
    defect_threshold_map = load_defect_threshold_map()
    zone_rate_df = load_daily_defect_zone_rate()
    target_override_map = load_target_override_map()
    cusum_lines = load_cusum_alert_lines()
    # C유형은 load_cusum_alert_lines가 아직 안 다루므로(A/B/E만), 경보선을 그 안에서
    # 만들 수 있게 층별 std를 같이 넘긴다 — 같은 파일, 같은 CUSUM_K를 쓴다.
    stratum_std_map = (pd.read_csv(config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv",
                                   usecols=["column", "std"])
                       .groupby("column")["std"].median().to_dict())

    level_trend = compute_level_and_trend(
        daily_series_raw, boundary_z, spec_values, trend_status, defect_threshold_map, zone_rate_df,
        target_override_map, cusum_lines, stratum_std_map,
    )
    level_trend.to_csv(OUT_DIR / "01_level_trend_by_machine_column.csv", index=False, encoding="utf-8-sig")

    defect_index, machine_index = aggregate_health_index(level_trend)
    defect_index.to_csv(OUT_DIR / "02_health_index_by_defect.csv", index=False, encoding="utf-8-sig")
    machine_index.to_csv(OUT_DIR / "03_health_index_by_machine.csv", index=False, encoding="utf-8-sig")

    occurrence = load_defect_occurrence()
    occurrence.to_csv(OUT_DIR / "04_defect_occurrence_recent7d.csv", index=False, encoding="utf-8-sig")

    machines = build_machine_snapshot(level_trend, occurrence, defect_index, machine_index)

    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "recent_window_days": RECENT_WINDOW_DAYS,
        "anomaly_margin_threshold_pct": ANOMALY_MARGIN_THRESHOLD_PCT,
        "cause_factors": CAUSE_FACTORS,
        "machines": machines,
    }
    with open(OUT_DIR / "health_index_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"완료: {len(machines)}개 장비 스냅샷 생성")
    ranked = sorted(machines.items(), key=lambda kv: (kv[1]["health_index"] is None, kv[1]["health_index"]))
    for machine, snap in ranked:
        n_anomalies = len(snap["unconfirmed_anomalies"])
        top3 = ", ".join(f"{d['defect']}({d['health_index']})" for d in snap["worst_defects"])
        print(f"  {machine}: Health Index {snap['health_index']} (순위: {top3}), 미확인 이상 {n_anomalies}건")


if __name__ == "__main__":
    main()
