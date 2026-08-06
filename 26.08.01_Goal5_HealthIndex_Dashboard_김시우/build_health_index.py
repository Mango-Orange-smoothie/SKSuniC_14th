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
       변수별 Health Index = 100 − clip(margin_used_pct, 0, 100)
       (26.08.05: 예전엔 boundary_z를 raw 샷 노이즈 분포로 재고 daily_mean_z와 비교해서
        granularity가 안 맞았다 — 일평균은 샷 평균이라 분산이 훨씬 작아 그 경계에 거의
        못 미쳤고, "스펙아웃이 원래 잘 안 생긴다"는 결론으로 이어졌었다. daily_mean_z
        자기 분포로 경계를 다시 재서 고침.)
  2. **추세는 두 가지를 별도 정보로 계속 제공하면서, 그중 (b)만 점수에도 작게 반영한다.**
       (a) margin_used_pct의 최근 14일 기울기(%/일)로 뽑은 정량적 "예상 며칠 뒤
           스펙아웃"(margin_trend_pct_per_day/estimated_days_to_spec_out) — 이 스크립트가
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
        레벨 점수에 (1 - TREND_PENALTY_MAX_CUT × maturity) 배율을 곱한다 — maturity는
        alert_since부터 지속된 일수를 RECENT_WINDOW_DAYS로 나눈 값(0~1). 막 뜬 경보는
        거의 안 깎이고, RECENT_WINDOW_DAYS 이상 지속된 "성숙한" 경보라야 최대폭
        (TREND_PENALTY_MAX_CUT)을 다 받는다 — 자세한 근거는 TREND_PENALTY_MAX_CUT
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
from pipeline.spec import SPEC

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
    CAUSE_FACTORS = json.load(f)["cause_factors"]
CAUSE_COLS = set(CAUSE_FACTORS.keys())

DEFECT_RATE_COLS = {
    "Particle": "Particle_rate",
    "Remain_Coat": "Remain_Coat_rate",
    "Micro_Crack": "Micro_Crack_rate",
    "Chipping": "Chipping_rate",
}

# 미확인 이상(안전망) 판정 임계값 — 스펙 경계까지 남은 여유를 이 % 이상 썼으면 표시.
# 확정 원인이 아니라서 보수적으로(절반 이상 썼을 때만) 잡는다. 최적화된 값은 아니다.
ANOMALY_MARGIN_THRESHOLD_PCT = 50.0
# 레벨/추세 계산에 쓰는 최근 구간 길이(일). 통계적 유의성을 새로 검정하는 게 아니라
# "최근 방향/속도"를 서술하는 용도라서 짧아도 된다 — 다만 지난 검증(DP02 Laser_Power
# 사례)에서 확인했듯 이 값 자체로 "유의미한 추세 확정"을 주장하지는 않는다.
RECENT_WINDOW_DAYS = 14
RECENT_DEFECT_WINDOW_DAYS = 7

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
# TREND_PENALTY_MAX_CUT=0.5로 잡은 근거: 이미 있는 ANOMALY_MARGIN_THRESHOLD_PCT(50) —
# "margin만으로도 이 정도면 눈여겨봐야 한다"는 팀의 기존 기준선 — 과 맞춘 것이다.
# 즉 레벨이 100(margin 전혀 안 씀)이어도 성숙한 추세 경보 하나만으로 그 기존 기준선
# (50점)까지는 끌어내릴 수 있게 했다. 실제 데이터(75건의 활성 경보)로 검증한 결과
# 30점(n8n 위험장비 기준)을 새로 넘는 경우는 1건뿐이었다 — 대부분이 아직 신선한
# 경보라 이 정도 상한으로는 위험장비 알림이 쏟아지지 않는다.
TREND_PENALTY_MAX_CUT = 0.5


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

        # (26.08.06 추가) "언제부터 이 이상이 시작됐는지"는 가장 최근 경고 행이 속한
        # episode(같은 Product×Recipe 안에서 early_warning이 끊기지 않고 이어진 구간)의
        # 첫 행 시각이다. 여기서 알림을 매 행(=매일)마다 새로 보내면 40일 넘게 지속되는
        # 문제도 40번 알림이 나가버리므로(엔지니어 알림 피로), n8n 등 실제 알림 트리거는
        # early_warning 행 자체가 아니라 이 episode 시작 시점(alert_since)이 바뀔 때만
        # 새 알림으로 취급해야 한다.
        same_episode = g[
            (g["Product_ID"] == latest_row["Product_ID"])
            & (g["Recipe_ID"] == latest_row["Recipe_ID"])
            & (g["episode_id"] == latest_row["episode_id"])
        ]
        alert_since = same_episode["DateTime"].min()
        alert_active_days = (dataset_latest - alert_since) / pd.Timedelta(days=1)

        combo_counts = g.groupby(["Product_ID", "Recipe_ID"]).size().sort_values(ascending=False)
        n_combos_affected = int(combo_counts.size)
        avg_per_combo = float(combo_counts.mean())
        top1_count = int(combo_counts.iloc[0])
        recipe_hotspots = [
            {"product_id": p, "recipe_id": r, "warning_count": int(c)}
            for (p, r), c in combo_counts.head(RECIPE_HOTSPOT_TOP_N).items()
        ]

        status[(machine, col)] = {
            "trend_direction": latest_row["trend_direction"],
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
    """CAUSE_FACTORS에 있으면 확정된 방향, 없으면 방향 모르니 either(양방향 이상 취급)."""
    meta = CAUSE_FACTORS.get(column)
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


# C유형 health 스케일: "위험구간에 들어간 샷 비율"이 정상 기준의 몇 배가 되면 health 0(스펙아웃
# 취급)으로 볼지. 2.0 = 평소의 2배로 늘면 최악. 임의로 정한 관례값이며 최적화된 값이 아니다 —
# 다만 "절대 안 울리는" 기존 상태(일평균은 356일 내내 경계를 한 번도 안 넘음)보다는 낫다.
# 실제 조치 기준으로 쓰기 전에 멘토/현장 확인 필요.
DEFECT_ZONE_SPECOUT_MULTIPLE = 2.0


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

    (26.08.05 추가) 이 두 컬럼은 멘토 SPEC(pipeline/spec.py)에 없어서 그동안
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


def _real_spec_margin_pct(raw_values: pd.Series, direction: str, lsl: float, target: float, usl: float) -> pd.Series:
    """멘토 실측 스펙(pipeline/spec.py) 기준 margin_used_pct. 0=TARGET, 100=USL/LSL 도달.

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
) -> pd.DataFrame:
    """장비×컬럼별로 "스펙 경계까지 남은 여유"(레벨)와 "그 여유가 줄어드는 속도"(추세)를 계산한다.

    두 가지 기준 소스를 컬럼별로 섞어 쓴다:
      - SPEC(pipeline/spec.py)에 있는 10개 컬럼: 멘토가 준 진짜 LSL/TARGET/USL을 raw 값과
        직접 비교(spec_source="mentor_spec") — 신뢰도 높음.
      - 나머지 컬럼: daily_mean_z(OPCOND baseline 대비 일별 정규화 잔차)와 boundary_z(여기
        쓰는 boundary_z는 daily_mean_z 자기 자신의 분포로 잰 경계 — compute_daily_boundary_z.
        raw 샷 분포로 잰 경계를 쓰면 안 됨, 26.08.05 granularity mismatch 버그 참고)로
        계산(spec_source="provisional_percentile") — 진짜 스펙이 아니라 정상군 분포로
        대체한 임시값이니 참고용으로만 쓸 것.
    실제 원래 단위 값(current_value/lsl/usl)도 같이 붙여서 "29.3% 사용"이 아니라 실제
    수치로 보여줄 수 있게 한다. provisional 컬럼의 lsl/usl 표시값은 margin 계산에 실제
    쓰는 boundary_z와 같은 기준(baseline ± boundary_z*scale)으로 역산해서, 화면에 보이는
    한계값과 margin_used_pct가 서로 어긋나지 않게 한다.

    추세는 두 가지를 같이 담는다: margin_used_pct의 최근 14일 기울기로 뽑은 정량적
    "예상 며칠 뒤 스펙아웃"(margin_trend_pct_per_day/estimated_days_to_spec_out)과,
    trend_analysis.py(load_trend_warning_status)가 판정한 "지금 공식적으로 경보가
    켜져 있는가"(trend_direction/early_warning_active/trend_message) — 전자는 이
    스크립트가 직접 추정한 속도, 후자는 팀이 따로 검증한 판정 로직의 결과다.
    """
    trend_status = trend_status or {}
    defect_threshold_map = defect_threshold_map or {}
    target_override_map = target_override_map or {}

    # (machine, column) -> date별 위험구간 비율 Series / (machine, column) -> 그 장비의 정상 기준 비율
    zone_lookup: dict[tuple[str, str], pd.Series] = {}
    zone_base_rate: dict[tuple[str, str], float] = {}
    # (26.08.06 개정) 원래는 "정상 기준"을 4대 장비 풀링 median으로 잡았다 — 특정 장비가
    # 일시적으로 나빠진 구간이 있어도 기준 자체가 끌려가지 않게 하려는 의도였다. 그런데
    # CLN_Flow처럼 애초에 "이 위험구간에 들어가는 게 특정 장비(DP04)만의 일"인 컬럼에선
    # 이 가정이 틀렸다 — DP01~03을 풀링에 같이 넣으면 걔들의 "항상 0%"가 평소 비율을
    # 인위적으로 짓눌러서(0.48%), DP04가 원래도 가끔 겪는 정상적 편차(7.53%)조차 비율로
    # 따지면 1469%짜리 폭주로 보이게 만들었다(김시우님 지적). "평소"는 그 장비 자신의
    # 이력 기준이어야 맞다 — 다른 장비를 섞을 이유가 없다. 그래서 이제 장비별로 따로
    # 잡는다. (CLN_Pressure/Surface_Roughness는 애초에 4대가 서로 비슷한 비율이라
    # 이 변경으로 값이 거의 안 바뀐다 — 확인됨.)
    if zone_rate_df is not None and len(zone_rate_df):
        for (m, c), zg in zone_rate_df.groupby(["Machine_ID", "column"]):
            series = zg.set_index("date")["defect_zone_rate"].sort_index()
            zone_lookup[(m, c)] = series
            base = series.median()
            if not base:
                base = series.mean()  # median도 0이면(절반 넘는 날이 0%) mean으로 대체
            zone_base_rate[(m, c)] = float(base) if base else 0.0

    rows = []
    for (machine, col), g in daily_series.groupby(["Machine_ID", "column"]):
        g = g.sort_values("date")
        direction = direction_of(col)
        real_spec = SPEC.get(col)
        defect_thr = defect_threshold_map.get(col)
        zone_rate_now = None

        if real_spec is not None:
            spec_source = "mentor_spec" if col not in target_override_map else "mentor_spec_recomputed_target"
            lsl_disp, usl_disp = real_spec["LSL"], real_spec["USL"]
            # LSL/USL(위험 경계)은 멘토 값을 그대로 신뢰하되, TARGET_RECOMPUTE_FROM_DATA에
            # 있는 컬럼(Kerf_Width_Profile)은 target(정상 기준값)만 실측 OK median으로 바꾼다
            # — load_target_override_map docstring 참고(멘토 TARGET과 스펙폭의 12% 어긋남,
            # 89일 내내 안 줄어드는 정적 오프셋이라 반복 오탐의 원인이었음).
            baseline_disp = target_override_map.get(col, real_spec["TARGET"])
            margin_pct = _real_spec_margin_pct(g["daily_mean"], direction, lsl_disp, baseline_disp, usl_disp)
            margin_pct.index = g.index
        elif defect_thr is not None and spec_values.get(col) and (machine, col) in zone_lookup:
            # C유형: 임시 percentile도, 일평균 대 threshold 비교도 아니고,
            # "그날 샷 중 몇 %가 불량 위험구간에 들어갔나"로 잰다.
            # (일평균은 356일 내내 threshold를 한 번도 안 넘어서 경보 자체가 불가능했음 —
            #  compute_daily_defect_zone_rate docstring 참고.)
            spec_source = "defect_zone_rate"
            baseline_disp = spec_values[col]["baseline_median"]
            thr = defect_thr["threshold"]
            risky_direction = defect_thr["risky_direction"]
            if risky_direction == "low_is_risky":
                lsl_disp, usl_disp = thr, baseline_disp
            else:
                lsl_disp, usl_disp = baseline_disp, thr

            zr = zone_lookup[(machine, col)].reindex(g["date"].values)
            base_rate = zone_base_rate.get((machine, col), 0.0)
            if base_rate and base_rate > 0:
                span = base_rate * (DEFECT_ZONE_SPECOUT_MULTIPLE - 1.0)
                margin_pct = ((zr.values - base_rate) / span * 100).clip(min=0.0)
            else:
                # 이 장비는 이 위험구간에 들어간 적이 사실상 없다(평소 비율=0) — "평소 대비
                # 몇 배"라는 비율 자체가 정의 안 됨. 조금이라도 들어간 날은 경계(100%,
                # health=0)로, 안 들어간 날은 정상(0%)으로 본다.
                margin_pct = np.where(zr.values > 0, 100.0, 0.0)
            margin_pct = pd.Series(margin_pct, index=g.index, dtype=float)
            zone_rate_now = zr.values
        else:
            b = boundary_z.get(col)
            spec = spec_values.get(col)
            if not b or not spec or not spec.get("robust_z_scale"):
                continue
            up_b, down_b = b.get("up"), b.get("down")
            if direction == "up" and not up_b:
                continue
            if direction == "down" and not down_b:
                continue
            if direction == "either" and not up_b and not down_b:
                continue
            spec_source = "provisional_percentile"
            baseline_disp = spec["baseline_median"]
            scale = spec["robust_z_scale"]
            # either인데 한쪽 경계가 없으면(분포가 한쪽으로만 벗어난 경우) 반대쪽 크기를
            # 그대로 대칭 fallback으로 씀 — lsl/usl을 아예 안 보여줄 순 없어서.
            up_disp = up_b if up_b else down_b
            down_disp = down_b if down_b else up_b
            lsl_disp = baseline_disp - down_disp * scale if direction != "up" else baseline_disp
            usl_disp = baseline_disp + up_disp * scale if direction != "down" else baseline_disp

            z = g["daily_mean_z"]
            margin_pct = pd.Series(np.nan, index=z.index, dtype=float)
            if direction == "up":
                margin_pct[z >= 0] = (z[z >= 0] / up_b) * 100
                margin_pct[z < 0] = 0.0
            elif direction == "down":
                margin_pct[z <= 0] = (-z[z <= 0] / down_b) * 100
                margin_pct[z > 0] = 0.0
            else:
                # either: 지금 어느 쪽으로 벗어났는지 보고 그 방향의 경계로 나눈다 —
                # 예전처럼 |z|를 min(up,down) 경계 하나로 재면, 분포가 한쪽으로 치우친
                # 컬럼(예: CLN_Flow)에서 "넓은 쪽" 값이 "좁은 쪽" 경계에 걸려 margin이
                # 1000%+ 로 튀는 문제가 있었다(26.08.05 발견). up_b/down_b 중 없는 쪽은
                # 위 up_disp/down_disp와 같은 방식으로 대칭 fallback.
                eff_up_b = up_b if up_b else down_b
                eff_down_b = down_b if down_b else up_b
                above = z >= 0
                margin_pct[above] = (z[above] / eff_up_b) * 100
                margin_pct[~above] = (-z[~above] / eff_down_b) * 100

        valid = margin_pct.dropna()
        if valid.empty:
            continue
        current_margin_pct = float(valid.iloc[-1])
        latest_idx = valid.index[-1]
        latest_pos = g.index.get_loc(latest_idx)  # zone_rate_now(위치 기반 배열) 조회용
        latest_date = g.loc[latest_idx, "date"]
        current_value = float(g.loc[latest_idx, "daily_mean"])
        # (26.08.06) 예전엔 margin_used_pct를 100%에서 clip해서 health_index가 0 밑으로
        # 못 내려갔다 — 그러다 보니 경계를 살짝 넘은 것(예: margin 105%)과 몇 배로 폭주한
        # 것(예: DP04 CLN_Flow margin 1465%)이 똑같이 "HI 0.0"으로 보여서, worst_factors/
        # worst_defects/장비 순위(TOP_N)에서 뭐가 진짜 더 급한지 구분이 안 됐다(김시우님
        # 피드백). 위쪽 clip을 없애 margin이 클수록 health_index가 계속 더 음수로 내려가게
        # 한다 — "100이 건강"은 그대로고, 0 밑은 "경계를 몇 배 넘었는지"를 그대로 보여주는
        # 값이 된다. 0~100 사이 동작(margin<=100인 대다수)은 전혀 안 바뀐다.
        health_index_var = 100 - max(current_margin_pct, 0.0)
        spec_out = current_margin_pct >= 100

        recent = valid.iloc[-RECENT_WINDOW_DAYS:]
        margin_slope, est_days = None, None
        if len(recent) >= 3 and recent.nunique() > 1:
            x = np.arange(len(recent))
            lr = scipy_stats.linregress(x, recent.values)
            margin_slope = float(lr.slope)  # %/일 (양수=여유가 줄어드는 중)
            if not spec_out and margin_slope > 1e-9:
                remaining = 100 - current_margin_pct
                projected = remaining / margin_slope
                est_days = round(projected, 1) if projected <= 365 else None  # 1년 넘게 남으면 "임박 아님" 취급
            # 이미 스펙아웃이면 "며칠 뒤"는 의미 없으므로 est_days는 None으로 둔다 (spec_status로 대체)

        ta_status = trend_status.get((machine, col), {})
        # health_index_var > 0일 때만 곱셈 페널티를 적용한다 — 이미 0 밑(margin이 100%를
        # 넘어 SPEC_OUT 수준)이면 음수에 (1-cut)을 곱하는 순간 0 쪽으로 끌려가(더 나빠져야
        # 할 값이 오히려 좋아 보이게 됨) 방향이 뒤집힌다. margin 자체가 이미 심각하다고
        # 말하고 있는 상태라 추세 페널티가 추가로 알려줄 정보도 없다(그 존재 목적 자체가
        # "margin은 멀쩡해 보이는데 추세가 나쁜" 사각지대를 잡는 것이었음).
        if ta_status.get("early_warning_active") and health_index_var > 0:
            maturity = min(1.0, (ta_status.get("alert_active_days") or 0.0) / RECENT_WINDOW_DAYS)
            health_index_var = health_index_var * (1 - TREND_PENALTY_MAX_CUT * maturity)

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
            # defect_zone_rate 컬럼 전용: margin/health가 "값이 경계에서 얼마나 떨어졌나"가
            # 아니라 "위험구간 샷 비율이 평소 대비 얼마나 늘었나"에서 나온다는 걸 알 수 있게
            # 실제 비율을 그대로 같이 싣는다(다른 컬럼은 None).
            "defect_zone_rate_pct": (
                round(float(zone_rate_now[latest_pos]) * 100, 2)
                if zone_rate_now is not None and not pd.isna(zone_rate_now[latest_pos]) else None
            ),
            "defect_zone_baseline_pct": (
                round(zone_base_rate.get((machine, col), 0.0) * 100, 2) if spec_source == "defect_zone_rate" else None
            ),
            "margin_used_pct": round(current_margin_pct, 1),
            "health_index": round(health_index_var, 1),
            "margin_trend_pct_per_day": round(margin_slope, 3) if margin_slope is not None else None,
            "estimated_days_to_spec_out": est_days,
            "trend_direction": ta_status.get("trend_direction"),
            "early_warning_active": ta_status.get("early_warning_active", False),
            "trend_message": ta_status.get("trend_message"),
            "alert_since": ta_status.get("alert_since"),
            "alert_active_days": ta_status.get("alert_active_days"),
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
        factor_names = [f for f, meta in CAUSE_FACTORS.items() if defect in meta["defects"]]
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
            "worst_factors": [
                {"factor": r["column"], "health_index": r["health_index"], "spec_status": r["spec_status"]}
                for _, r in ranked.iterrows()
            ],
        })
    defect_index = pd.DataFrame(defect_rows)

    machine_rows = []
    for machine, g in defect_index.groupby("Machine_ID"):
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
    """05_machine_daily_trend.csv(analysis_step_by_step.py 산출물)로 최근 실제 발생 여부 판정."""
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
            factor_names = [f for f, meta in CAUSE_FACTORS.items() if defect in meta["defects"]]
            factor_rows = cause_rows[cause_rows["column"].isin(factor_names)]
            if factor_rows.empty:
                continue
            causes = {}
            for _, row in factor_rows.iterrows():
                meta = CAUSE_FACTORS[row["column"]]
                causes[row["column"]] = {
                    "current_value": row["current_value"],
                    "baseline_median": row["baseline_median"],
                    "lsl": row["lsl"],
                    "usl": row["usl"],
                    "spec_source": row["spec_source"],
                    "spec_status": row["spec_status"],
                    "health_index": row["health_index"],
                    "defect_zone_rate_pct": _none_if_nan(row["defect_zone_rate_pct"]),
                    "defect_zone_baseline_pct": _none_if_nan(row["defect_zone_baseline_pct"]),
                    "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                    "estimated_days_to_spec_out": _none_if_nan(row["estimated_days_to_spec_out"]),
                    "trend_direction": _none_if_nan(row["trend_direction"]),
                    "early_warning_active": bool(row["early_warning_active"]),
                    "trend_message": _none_if_nan(row["trend_message"]),
                    "alert_since": _none_if_nan(row["alert_since"]),
                    "alert_active_days": _none_if_nan(row["alert_active_days"]),
                    "recipe_hotspots": row["recipe_hotspots"],
                    "n_product_recipe_combos_affected": _none_if_nan(row["n_product_recipe_combos_affected"]),
                    "recipe_hotspot_concentrated": bool(row["recipe_hotspot_concentrated"]),
                    "direction": meta["direction"],
                    "mechanism": meta["mechanism"],
                    "source": meta["owner"],
                }
            occ = occurrence[(occurrence["Machine_ID"] == machine) & (occurrence["defect"] == defect)]
            d_idx = defect_index[(defect_index["Machine_ID"] == machine) & (defect_index["defect"] == defect)]
            defect_signals[defect] = {
                "health_index": float(d_idx["health_index"].iloc[0]) if len(d_idx) else None,
                "worst_factors": d_idx["worst_factors"].iloc[0] if len(d_idx) else [],
                "actual_occurred_recent_7d": bool(occ["actual_occurred_recent_7d"].iloc[0]) if len(occ) else False,
                "occurred_days_recent_7d": int(occ["occurred_days_recent_7d"].iloc[0]) if len(occ) else 0,
                "causes": causes,
            }

        # 미확인 이상(안전망): 확정 원인 아닌 변수 중 스펙 여유를 많이 쓴 것만
        anomalies = []
        flagged = other_rows[other_rows["margin_used_pct"] >= ANOMALY_MARGIN_THRESHOLD_PCT]
        for _, row in flagged.sort_values("margin_used_pct", ascending=False).iterrows():
            anomalies.append({
                "column": row["column"],
                "current_value": row["current_value"],
                "baseline_median": row["baseline_median"],
                "lsl": row["lsl"],
                "usl": row["usl"],
                "spec_source": row["spec_source"],
                "spec_status": row["spec_status"],
                "defect_zone_rate_pct": _none_if_nan(row["defect_zone_rate_pct"]),
                "defect_zone_baseline_pct": _none_if_nan(row["defect_zone_baseline_pct"]),
                "margin_trend_pct_per_day": _none_if_nan(row["margin_trend_pct_per_day"]),
                "estimated_days_to_spec_out": _none_if_nan(row["estimated_days_to_spec_out"]),
                "trend_direction": _none_if_nan(row["trend_direction"]),
                "early_warning_active": bool(row["early_warning_active"]),
                "trend_message": _none_if_nan(row["trend_message"]),
                "alert_since": _none_if_nan(row["alert_since"]),
                "alert_active_days": _none_if_nan(row["alert_active_days"]),
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

    level_trend = compute_level_and_trend(
        daily_series_raw, boundary_z, spec_values, trend_status, defect_threshold_map, zone_rate_df,
        target_override_map,
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
