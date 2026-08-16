
import os
import sys
import numpy as np
import pandas as pd
from scipy import stats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from pipeline import config
from pipeline.common import binomial_alert_count
from pipeline.mentor import SPEC  # 멘토 실측 LSL/TARGET/USL (26.08.05 수령, 10개 컬럼)

RAW_INPUT_FILES = [
    ("DP_HealthIndex_Dataset.csv", os.path.join(BASE_DIR, "data", "raw", "DP_HealthIndex_Dataset.csv")),
]
# r1(DP_HealthIndex_Dataset_r1.csv, 멘토 배포 파일)은 로컬에 있지만 여기 일부러 안 넣는다
# — r1은 C유형 threshold를 "학습"하는 데만 쓰는 별도 데이터셋이고(pipeline/config.py의
# BASELINE_C_DEFECT_MAP 주석 참고), 모니터링 대상 데이터에 섞으면 학습에 쓴 데이터로
# 다시 경보를 판정하는 셈이 된다. git에도 안 올린다(.gitignore).

CLASSIFICATION_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_column_classification.csv")
STRATUM_STD_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_stratum_baseline_stats_by_opcond.csv")
MACHINE_TREND_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_machine_column_trend.csv")
BASELINE_AB_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_AB.csv")
BASELINE_C_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_C.csv")
BASELINE_E_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_E.csv")
BASELINE_C_ENTRY_RATE_CSV = os.path.join(BASE_DIR, "analysis_outputs", "preprocessing", "00_baseline_C_entry_rate.csv")

OUTPUT_DIR = os.path.join(BASE_DIR, "analysis_outputs")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "trend_analysis_results.csv")
CROSS_VALIDATION_CSV = os.path.join(OUTPUT_DIR, "trend_cross_validation.csv")

GROUP_KEYS = ["Machine_ID", "Product_ID", "Recipe_ID"]
WINDOW = 10
# (26.08.06) Z_THRESHOLD(=2.0) 상수는 A/B/E 판정이 CUSUM으로, C 판정이 danger_rate로
# 바뀌면서 아무 데서도 안 쓰이게 돼 제거했다. 지금 판정 임계값은 CUSUM_K/CUSUM_H(A/B/E)와
# C_DANGER_RATE_MULTIPLE(C)이다.
# (26.08.17) VOLATILITY_RATIO_THRESHOLD(=1.5)와 변동성 확대 경보를 제거했다.
# 지우는 근거는 "CUSUM이 대신한다"가 아니다 — CUSUM은 z를 평소 std로 나눌 뿐이라
# 평균이 그대로면 E[z-K] = -K로 누적합이 계속 0으로 리셋된다. 원리적으로 순수 산포
# 증가는 못 잡는다. 지운 이유는 이 탐지기가 산포 증가를 잡고 있지 않았기 때문이다.
#
#   · 이 데이터에 산포 증가가 없다. 초반 30일 대비 후반 30일 std 비를 4대 x 35컬럼
#     140조합 전부 재보면 최대가 1.031배(DP02)고 1.2배를 넘는 조합이 0개다. 주입된
#     세 시나리오는 전부 평균을 미는 고장이지 산포를 키우는 고장이 아니다.
#   · 그런데 89일 중 86일, 4대 x 31컬럼 전부에서 울렸다(10,200행 = 경보행의 16.7%).
#   · 정상 장비를 못 가린다. DP01(시나리오 없음) 2,468행 vs DP04(고장) 2,446행 —
#     정상 장비가 더 많이 울렸다. 임계값을 S관리도 B4(n=10 -> 1.716)로 올려도
#     519 vs 545로 여전히 안 갈린다. 1.5가 문제가 아니라는 뜻이다.
#   · 원인은 10샷 표본 std의 추정 노이즈다. 산포가 안 변해도 s/sigma >= 1.5가
#     우연히 나올 확률이 1.643%(chi2(9))인데, 창이 1샷씩 밀리며 9개를 공유하므로
#     한 번 커지면 10행 유지된다. PERSIST_WINDOW=5 조건이 이걸 거르는 게 아니라
#     겹친 창에서 자동 충족돼 오히려 사건 하나를 다섯 번 세고 있었다.
#   · 아무도 안 읽었다. build_health_index / agent / views 어디도 이 컬럼을 안 본다.
#     점수·화면·챗봇에 안 들어가고 경보행 수만 부풀렸다.
#
# 산포가 커지는 고장을 감시하려면 겹치지 않는 부분군에 S관리도를 제대로 붙여야 한다
# (n=10이면 상한 B4=1.716). 지금 것은 그게 아니었으므로 되살릴 때도 그대로 되살리면
# 안 된다. std_slope도 이 판정에만 쓰이던 값이라 같이 뺀다.
KENDALL_P_THRESHOLD = 0.05  # 교차검증용 전역 추세 판정(Kendall tau) 유의수준
PERSIST_WINDOW = 5  # (26.08.05) 몇 행 연속으로 조건을 만족해야 "진짜 상태"로 볼지 —
# 노이즈로 임계값 근처를 오락가락하는 걸 "새로 진입"으로 계속 잡던 문제(Surface_Roughness
# 22,948건 중 21,426건이 진입 이벤트였음) 방지용. 1행짜리 순간 판정 대신 지속성 요구.

# (26.08.05 추가) Type C "접근" 판정은 "윈도우 안 위험구간 진입 샷 수"로 한다. rolling_mean
# 기반 risk_margin_z는 위험선까지 얼마나 남았는지를 "평균"으로 재는데, 평균은 개별 샷의
# 위험 진입을 지워버린다(CLN_Pressure 실측: 개별 샷 6.68%가 threshold 아래인데 rolling
# mean은 0.00%만 아래로 내려감 — 66,824배 차이). 반대로 rolling MIN(윈도우 내 최악값)을
# 쓰면 10개 중 1개만 넘어도 걸려서 오히려 개별 샷 확률의 절반(49.47%)까지 뛰어 과민해진다.
#
# (26.08.08) 판정선을 "평소의 2.0배"에서 "우연히 나올 확률 < C_DANGER_ALPHA"로 바꿨다.
# 고정 배수는 평소 진입률에 따라 엄격도가 8.7배까지 달라졌다 — 근거는 pipeline/common.py
# binomial_alert_count 주석 참고. 필요 샷 수는 (장비, 컬럼)마다 baseline에서 계산한다.

# (26.08.05 추가) A/B/E유형의 "지속적 편차" 판정을 CUSUM(누적합)으로 교체.
# 기존 방식(WINDOW=10 rolling mean + PERSIST_WINDOW=5 연속조건)은 구조적으로 최소
# WINDOW+PERSIST_WINDOW-1행(그룹당 하루 ~5샷이면 최소 3일)의 지연이 있고, 실측으로는
# CLN_Flow가 실제 하강 시작(2/16) 대비 첫 경고까지 6~7일 걸렸다(rolling mean이 전환
# 자체를 완전히 반영하기까지 추가 지연). CUSUM은 매 샷마다 target 대비 편차를 누적해서
# 작은 편차(CUSUM_K 미만)는 계속 무시하고 버리되, 그보다 큰 편차가 쌓이면 빠르게
# 경보 임계값(CUSUM_H)을 넘는다 — SPC(통계적 공정관리)에서 지속적 이동 감지에 쓰는
# 표준 방법. k=0.5, h=4는 교과서 관례값(약 1시그마 크기의 이동을 합리적인 오탐률로 잡음).
CUSUM_K = 0.7   # 허용 편차(시그마 단위) — 이보다 작은 편차는 누적 안 함(정상 노이즈)
CUSUM_H = 4.5   # 경보 임계값(시그마 단위) — 누적합이 이걸 넘으면 "지속적 이동" 확정
# (26.08.08) **멘토 확정 정답으로 재검증했다.** 위 26.08.05 튜닝은 "무엇이 진짜 고장인지"를
# 모르는 상태에서 오탐률만 보고 한 것이었는데, 멘토님이 주입 시나리오를 확정해주면서
# (DP02=Laser Aging / DP03=Cooling Failure / DP04=Cleaning Failure / **DP01=시나리오 없음**)
# 정상 장비를 기준으로 제대로 채점할 수 있게 됐다. 교과서값으로 되돌려 실측한 결과:
#
#   설정          DP01(정상) 14일↑ 지속경보   DP01 최장    판별
#   K0.7/H4.5     0개                      3.4일       DP01 0 vs DP02 6 / DP03 4 / DP04 1
#   K0.5/H4.0     8개                      87.6일      DP01 8 vs DP02 14 / DP03 14 / DP04 12
#
# 교과서값에서는 정상 장비가 89일 중 87.6일 경보 상태가 되고, 고장 장비와 구분이 안 된다
# (DP01 Health Index도 90.3 -> 68.8로 떨어진다). K=0.7/H=4.5를 유지한다 — 이제 근거가
# "오탐률이 낮아서"가 아니라 "정답이 있는 데이터에서 정상/고장을 가르기 때문"이다.
# (26.08.05) 파라미터를 실측으로 두 번 튜닝했다.
#   1차(K=0.5, H=4.0, OPCOND 공통 target): Laser_Power에서 DP02가 다른 장비보다 0.44시그마
#     낮게 89일 내내 고정 운영되는 걸 "지속 이동"으로 잘못 잡아 그 컬럼 알람율이 15.6%까지
#     치솟았다(정상적으론 거의 0%여야 함) — Coating_Uniformity는 거의 전체 행(96,484건)이
#     경보 상태가 됨.
#   2차 시도(그룹별 초반 30샷 평균을 기준점으로): 장비 간 차이 문제는 피했지만, 30개
#     표본만으로 추정한 기준점 자체가 우연히 실제 평균과 어긋나는 그룹이 나왔다(한
#     사례: 초반 30개 평균이 전체 평균보다 0.58시그마 낮게 나와서 그 뒤 447개 샷 내내
#     "위로 지속 이동"으로 오인, 알람율 93%). 표본이 작을수록 이 위험이 커진다.
#   최종: OPCOND 공통 target으로 되돌리고, K를 0.5->0.7, H를 4.0->4.5로 올려 "장비 간
#     자연스러운 0.4~0.6시그마 차이"에는 반응하지 않게 둔감화했다. 실측 검증(아래):
#       Laser_Power/Bottom_Kerf(추세 없는 안정 컬럼) 알람율 0.5%/1.0%대로 하락(20배+ 개선)
#       CLN_Flow(DP04, 실제 2/16~18 하강) 첫 경고 중앙값 2/22 18:06 — 기존 rolling+
#       persistence 방식(2/22~23)과 비슷한 속도를 유지하면서 오탐만 크게 줄였다.
#     SPC 이론상 "민감도(빠른 탐지)"와 "오탐률"은 같은 k/h로 동시에 최적화가 안 되는
#     근본적 트레이드오프라(작은 목표 이동폭 2k와 자연 변동폭이 겹치면 어느 한쪽을
#     포기해야 함), 이 데이터에서는 오탐 억제를 우선했다 — 지연을 더 줄이려면 목표
#     이동폭을 이 정도로 잡는 대신 오탐 증가를 감수해야 한다.


# (26.08.06 추가) 멘토 실측 스펙(pipeline/mentor.py) LSL/USL 위반 검사.
#
# 왜 CUSUM/threshold와 별개로 필요한가: 기존 판정은 전부 "정상군 baseline 대비 얼마나
# 벗어났나"(상대 기준)다. 멘토 스펙은 유일한 절대 기준이라, 같은 CUSUM 경보라도 "스펙
# 안에서 드리프트 중"인지 "이미 스펙 밖"인지는 완전히 다른 급함이다. 그래서 모든 출력
# 행에 spec_lsl/spec_usl/spec_status를 같이 실어서 소비자(Health Index/Agent)가 그 구분을
# 할 수 있게 한다.
#
# 알림은 왜 "샷 1개 위반"으로 안 내는가 — 실측으로 확인한 결과 이 데이터의 스펙 위반은
# 전부 **공정 이탈이 아니라 정상 분포의 꼬리**였다:
#   - 10개 중 8개 컬럼(Laser_Power/Power_Efficiency/Head_Temp/Kerf_Width_Profile 등)은
#     89일 100,000샷 내내 위반 0건 — 멘토 스펙이 자연 변동폭보다 넓다.
#   - Feed_Speed 1.27%(639건 하한/630건 상한 — 완벽히 대칭), Coating_Thickness 0.10%,
#     Frequency 0.01%. 장비별 위반율도 거의 동일(Feed_Speed 1.21/1.34/1.30/1.24%)이고
#     월별로도 평평(1.31/1.19/1.30%) — 특정 장비나 시점의 문제가 아니라는 뜻.
#   - 그룹 내 최대 연속 위반이 Feed_Speed 2샷, 나머지는 1샷.
# 즉 샷 단위로 알리면 1,366건이 전부 오탐이 된다. 반대로 "연속 r샷 위반"은 우연히는
# 사실상 안 생긴다 — 아래 required_run_length가 컬럼별 평소 위반율 p로부터 "p^r x 전체
# 샷수 < 0.01(즉 이 데이터 크기에서 우연히 한 번도 안 나올 수준)"이 되는 최소 r을 직접
# 구한다(Feed_Speed r=4, Coating_Thickness r=3, Frequency r=2, 위반 이력이 없는 컬럼 r=1).
# 임의 상수를 새로 만들지 않고 데이터가 r을 정하게 한 것이다.
#
# 평소 위반율은 (defect_zone_rate와 달리) **장비별이 아니라 컬럼 전체로** 잡는다 —
# 멘토 스펙은 절대 기준이라, 특정 장비가 원래 자주 위반한다고 해서 그 장비의 기준을
# 느슨하게 해주면 정작 제일 나쁜 장비가 자기 이력 뒤에 숨는다.
SPEC_RUN_EXPECTED_MAX = 0.01  # "우연히 이만큼도 안 나온다"고 볼 기대 발생 횟수 상한


def load_external_limit_rules() -> dict[str, dict]:
    """rel_28(설비 정비 대상 알람)의 상한 규칙을 읽는다 — 현재 Vibration 하나.

    (26.08.08) 왜 여기 있나 — Vibration은 "값을 조정해서 고치는 인자"가 아니라 설비 정비
    대상이라 관계DB의 원인 티어표에서 빠져 있다(rel_28.why_not_in_tier). 그래서 C유형
    threshold도, 원인 짝짓기도 안 걸리는데, 그렇다고 감시를 안 하면 DP02/DP03에서 40일씩
    올라가는 진동을 아무도 안 보게 된다. 관계DB가 이 컬럼만 별도 파일로 넘겨준 이유다
    (alarm_owner = "추세분석 담당(김시우)").

    상한 0.2111은 우리가 산출해서 관계DB에 넘긴 값이다 — 안정 구간(Mann-Kendall 추세
    발생 직전) x OK샷의 p99.9이고, 4대가 0.2089~0.2117로 수렴한다(동일 사양 장비이므로
    이게 맞는 그림). rel_28에 이전에 있던 upper_candidate_p99=0.2609는 합본 200k 기준이라
    감시 데이터 최댓값(0.2487)을 넘어 영원히 안 울렸다.

    판정은 rel_28.spec_breach_rule 그대로 — "그날 상한 초과 샷 수 >= binom.ppf(0.99, 그날
    샷수, 0.001)". 개별 샷 하나가 넘는 건 정상 꼬리라 무시하고, 하루치가 우연이라 보기
    어려울 만큼 몰릴 때만 경보한다. 멘토 스펙 검사(SPEC_RUN_EXPECTED_MAX)와 같은 사고방식.

    파일이 없거나 옛 스키마(upper_limit 열이 없음)면 빈 dict를 돌려주고 경고를 찍는다 —
    조용히 빠지면 "감시하고 있다"고 착각하게 된다.
    """
    path = config.RELATIONSHIP_DB_DIR / "rel_28_vibration_alarm.csv"
    if not path.exists():
        print("[관계DB] rel_28_vibration_alarm.csv 없음 — 설비 상한 알람을 건너뜁니다.")
        return {}
    t = pd.read_csv(path)
    if "upper_limit" not in t.columns:
        print("[관계DB] 경고: rel_28에 upper_limit 열이 없습니다(옛 스키마) — 상한 알람을 "
              "건너뜁니다. JHdaimma님 브랜치가 병합됐는지 확인 필요.")
        return {}
    rules: dict[str, dict] = {}
    for factor, g in t.groupby("factor"):
        limit = pd.to_numeric(g["upper_limit"], errors="coerce").dropna()
        if limit.empty:
            continue
        rules[str(factor)] = {
            "upper_limit": float(limit.iloc[0]),
            # 어느 불량과 연결되는지 + 근거 수준. "위험 증가"가 아니라 "관련 가능성"으로
            # 써야 한다 — 감시 데이터로는 둘 다 검증이 안 된다(JHdaimma 회신 ⑤).
            "defects": [
                {"defect": str(r.defect), "evidence_level": str(getattr(r, "evidence_level", ""))}
                for r in g.itertuples(index=False)
            ],
        }
    for f, r in rules.items():
        print(f"[관계DB] 설비 상한 알람: {f} > {r['upper_limit']} "
              f"(연결 불량 {', '.join(d['defect'] for d in r['defects'])})")
    return rules


def compute_external_limit_breach(df, rules) -> dict[tuple[str, object], bool]:
    """(장비, 날짜)별로 "그날 상한 초과가 우연이라 보기 어려운가"를 판정.

    rel_28.spec_breach_rule: 초과 샷 수 >= binom.ppf(0.99, 그날 샷수, 0.001)
    """
    out: dict[tuple[str, object], bool] = {}
    if not rules:
        return out
    day = df["DateTime"].dt.date
    for col, rule in rules.items():
        if col not in df.columns:
            continue
        over = df[col] > rule["upper_limit"]
        agg = pd.DataFrame({"m": df["Machine_ID"], "d": day, "over": over}) \
            .groupby(["m", "d"])["over"].agg(["sum", "size"])
        need = {n: int(stats.binom.ppf(0.99, n, 0.001)) for n in agg["size"].unique()}
        for (m, d), row in agg.iterrows():
            if row["sum"] >= max(need[row["size"]], 1):
                out[(col, m, d)] = True
    return out


def compute_spec_violation_rules(df, usable_columns):
    """컬럼별 (lsl, usl, 평소 위반율, 경보에 필요한 연속 위반 샷 수)를 미리 계산.

    SPEC은 10개지만 실제 검사 대상은 9개다 — Focus는 멘토가 "분석에 활용하지 않아도
    된다"고 명시적으로 제외한 변수라(mentor.MENTOR_EXCLUDED_VARS) 분석 대상 컬럼
    목록에서 이미 빠져 있다.
    """
    rules = {}
    n = len(df)
    usable = set(usable_columns)
    for col, s in SPEC.items():
        if col not in df.columns or col not in usable:
            continue
        values = df[col].to_numpy(dtype=float)
        out = (values < s["LSL"]) | (values > s["USL"])
        p = float(np.nanmean(out))
        run = 1
        while run < WINDOW and (p ** run) * n >= SPEC_RUN_EXPECTED_MAX:
            run += 1
        rules[col] = {"lsl": s["LSL"], "usl": s["USL"], "rate": p, "run": run}
    return rules


def compute_cusum(z_values):
    """target 기준 정규화된 z-score 시계열(샷 단위, 전체 길이)에 양방향 CUSUM 적용.

    s_pos: 위쪽으로 지속 이동 중이면 커짐(0 아래로는 안 내려감 — 정상/반대방향이면 리셋).
    s_neg: 아래쪽으로 지속 이동 중이면 작아짐(음수, 0 위로는 안 올라감).
    """
    n = len(z_values)
    s_pos = np.zeros(n)
    s_neg = np.zeros(n)
    prev_pos, prev_neg = 0.0, 0.0
    for i in range(n):
        prev_pos = max(0.0, prev_pos + z_values[i] - CUSUM_K)
        prev_neg = min(0.0, prev_neg + z_values[i] + CUSUM_K)
        s_pos[i] = prev_pos
        s_neg[i] = prev_neg
    return s_pos, s_neg

OUTPUT_COLUMNS = [
    "source_file", "DateTime", "Machine_ID", "Product_ID", "Recipe_ID",
    "column", "type", "matched_defect", "baseline", "threshold",
    # (26.08.06 추가) 멘토 실측 스펙 — SPEC에 없는 컬럼은 NaN/"" 이다. spec_status는
    # 그 행의 current_value(샷 값) 기준 "OUT_OF_SPEC"/"OK".
    "spec_lsl", "spec_usl", "spec_status",
    "current_value", "rolling_mean", "rolling_std",
    "difference", "slope", "normalized_deviation", "trend_direction",
    "spec_violation_warning", "external_limit_warning",
    "early_warning", "episode_id", "message",
]
# (26.08.05) Type C 컬럼은 "baseline"과 "threshold"가 서로 다른 개념인데 예전엔 threshold를
# baseline 자리에 그대로 넣어써서, normalized_deviation(추세/경고용 "정상에서 얼마나
# 벗어났는지")이 "위험선에서 얼마나 벗어났는지"로 계산되는 문제가 있었다(안전한 쪽으로
# 멀리 떨어져 있을 뿐인데도 큰 편차로 잡혀 CLN_Pressure 경고의 75%가 사실상 오탐이었음).
# 이제 baseline = 모든 유형 공통으로 "정상 기준값(target)"(Type C는 00_stratum_baseline_
# stats_by_opcond.csv의 Product×Recipe별 OK median, 나머지는 기존과 동일), threshold =
# Type C 전용 위험 경계값으로 분리한다. normalized_deviation/trend_direction은 baseline
# 기준으로(A/B/E와 동일 의미), entered/approaching 판정만 threshold 기준으로 따로 계산.


# ----------------------------------------------------------------------
# 1. 필수 입력 파일 존재 확인 (예외 처리)
# ----------------------------------------------------------------------
def check_required_files():
    required = [p for _, p in RAW_INPUT_FILES] + [
        CLASSIFICATION_CSV, STRATUM_STD_CSV, MACHINE_TREND_CSV, BASELINE_AB_CSV, BASELINE_C_CSV, BASELINE_E_CSV,
    ]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError("다음 필수 입력 파일을 찾을 수 없습니다:\n" + "\n".join(missing))


# ----------------------------------------------------------------------
# 2. 분석 대상 연속형 컬럼 결정 (00_column_classification.csv 기준)
#    - 식별자 / 범주형 / 결함결과 / 제외대상은 자연히 빠짐
#    - data_type == 'continuous' AND analysis_role == 'predictor' 인 것만 채택
# ----------------------------------------------------------------------
def load_analysis_columns():
    cls = pd.read_csv(CLASSIFICATION_CSV)
    mask = (cls["data_type"] == "continuous") & (cls["analysis_role"] == "predictor")
    cols = cls.loc[mask, "column"].tolist()
    return cols


# ----------------------------------------------------------------------
# 3. Baseline 파일 로드 (A/B/C/E)
# ----------------------------------------------------------------------
def load_baseline_maps():
    ab = pd.read_csv(BASELINE_AB_CSV)
    c = pd.read_csv(BASELINE_C_CSV)
    e = pd.read_csv(BASELINE_E_CSV)

    print(f"[Baseline] AB 파일 실제 컬럼: {list(ab.columns)}")
    print(f"[Baseline] C  파일 실제 컬럼: {list(c.columns)}")
    print(f"[Baseline] E  파일 실제 컬럼: {list(e.columns)}")

    column_type = {}      # column -> 'A' / 'B' / 'C' / 'E'
    direction_map = {}    # A유형: column -> 'up' / 'down'
    ab_value_map = {}     # (column, group_key) -> baseline_value  (A/B 공용, group_key='Product|Recipe')
    # (26.08.11) 값이 dict 하나가 아니라 **리스트**다. 한 컬럼이 두 defect의 원인이면
    # 경계값이 defect마다 따로 학습되므로 같은 (컬럼, 그룹)에 행이 둘 생긴다. 예전엔
    # dict 대입이라 나중 행이 앞 행을 조용히 덮어써서 한 defect가 통째로 사라졌다.
    c_map = {}             # (column, group_key) -> [{threshold, risky_direction, matched_defect}, ...]
    e_value_map = {}       # column -> baseline_value (이론상수)
    e_std_map = {}         # column -> reference_OK_std (E유형 fallback std)
    # (26.08.11) column -> reference_OK_mean (정상일 때 실제로 나오는 값).
    # 이론상수와 다를 수 있고, CUSUM은 이쪽을 target으로 써야 한다 — 아래 CUSUM 블록 주석 참고.
    e_ok_mean_map = {}

    for row in ab.itertuples(index=False):
        col = row.column
        column_type[col] = row.type  # 'A' or 'B'
        ab_value_map[(col, row.group_key)] = row.baseline_value
        if row.type == "A":
            direction_map[col] = row.bad_direction

    for row in c.itertuples(index=False):
        col = row.column
        column_type[col] = "C"
        c_map.setdefault((col, row.group_key), []).append({
            "threshold": row.threshold,
            "risky_direction": row.risky_direction,
            "matched_defect": row.matched_defect,
        })

    for row in e.itertuples(index=False):
        col = row.column
        column_type[col] = "E"
        e_value_map[col] = row.baseline_value
        e_std_map[col] = row.reference_OK_std
        e_ok_mean_map[col] = row.reference_OK_mean

    return (column_type, direction_map, ab_value_map, c_map,
            e_value_map, e_std_map, e_ok_mean_map)


# ----------------------------------------------------------------------
# 4. std fallback + Type C target 참조 테이블
#    analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv 재사용
#    (Product_ID x Recipe_ID x column 단위, OK 데이터 기준 std/median)
#    (26.08.05) median을 Type C 컬럼의 target으로도 쓴다 — Type C는 원래 "위험 threshold"만
#    있고 "정상일 때 이 값이어야 한다"는 target이 없었는데(threshold를 target 자리에 대신
#    써서 문제가 생겼음), 이 파일에 이미 Product×Recipe별 OK median이 있어서(Health Index
#    쪽 provisional_percentile 계산이 이미 같은 파일로 target을 쓰고 있음) 그대로 재사용한다.
# ----------------------------------------------------------------------
def load_stratum_reference_maps():
    strat = pd.read_csv(STRATUM_STD_CSV, usecols=["Product_ID", "Recipe_ID", "column", "std", "median"])
    fb_std, target_map = {}, {}
    for row in strat.itertuples(index=False):
        key = (row.Product_ID, row.Recipe_ID, row.column)
        fb_std[key] = row.std
        target_map[key] = row.median
    return fb_std, target_map


# ----------------------------------------------------------------------
# 5. Rolling 통계 계산 (그룹 내 한 컬럼, 시간순 정렬된 1D array)
# ----------------------------------------------------------------------
def compute_group_rolling(values):
    n = len(values)
    if n < WINDOW:
        return None
    windows = np.lib.stride_tricks.sliding_window_view(values, WINDOW)
    rolling_mean = windows.mean(axis=1)
    rolling_std = windows.std(axis=1, ddof=1)
    difference = windows[:, -1] - windows[:, 0]

    x = np.arange(WINDOW, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    slope = ((windows - rolling_mean.reshape(-1, 1)) * (x - x_mean)).sum(axis=1) / denom

    return rolling_mean, rolling_std, difference, slope


# ----------------------------------------------------------------------
# 5-1. 지속성 필터 — "1행짜리 순간 판정" 대신 "N행 연속 유지"를 요구
#      (26.08.05 추가) Type C(위험 threshold)의 entered_first가 임계값 근처 노이즈로
#      계속 새로 트리거되던 문제를 고친다.
#
#      (26.08.17) 이 필터는 겹치는 창 위에서는 지속성을 확인해주지 못한다 —
#      연속된 rolling 창은 WINDOW-1개 샷을 공유하므로 한 번 만족되면 자동으로
#      이어진다. 제거된 변동성 경보가 그 사례였다(위 상수 주석 참고). 여기 남은
#      C유형 진입/접근은 판정 대상이 rolling 통계가 아니라 개별 샷이라 해당 없다.
# ----------------------------------------------------------------------
def _sustained_state(condition: np.ndarray, persist_n: int) -> np.ndarray:
    """condition이 최근 persist_n행 연속 True인 시점부터를 True로 표시(그 구간 전체, 상태형)."""
    n = len(condition)
    if n < persist_n:
        return np.zeros(n, dtype=bool)
    windows = np.lib.stride_tricks.sliding_window_view(condition, persist_n)
    sustained = windows.all(axis=1)
    full = np.zeros(n, dtype=bool)
    full[persist_n - 1:] = sustained
    return full


def _sustained_first(condition: np.ndarray, persist_n: int) -> np.ndarray:
    """_sustained_state 중에서도 그 상태가 "막 시작된" 시점 1행만 True(이벤트형)."""
    full = _sustained_state(condition, persist_n)
    prev_full = np.concatenate(([False], full[:-1]))
    return full & ~prev_full


# ----------------------------------------------------------------------
# 5-3. Type C "접근" 판정용 정상 danger_rate — **장비×컬럼별로** "평소엔 위험구간에 샷이
#      얼마나 들어가는지". 그 장비 안 Product×Recipe 그룹별 비율의 median을 쓴다(특정
#      그룹이 튀어도 안 흔들리게).
#
#      (26.08.08) 이 값을 여기서 직접 계산하지 않고 step0 산출물을 읽는다. 예전엔
#      trend_analysis.py(경보)와 build_health_index.py(화면)가 각자 계산했는데 정의가
#      달랐다 — 여기는 그룹별 median, 저기는 일별 median. 같은 "평소 X%"가 화면과 경보에서
#      다른 수를 가리켰다. 더 중요한 건 둘 다 **89일 전체 × 전체 샷**으로 쟀다는 점인데,
#      불량 샷과 열화 기간이 baseline에 섞여 들어가 기준이 밀렸다(김시우님 지적).
#      step0의 compute_c_entry_rate_baseline이 안정 구간 × OK샷으로 다시 재서
#      00_baseline_C_entry_rate.csv에 저장한다 — 근거는 config.py의
#      C_BASELINE_MIN_STABLE_DAYS 주석 참고.
# ----------------------------------------------------------------------
def compute_c_type_baseline_rate(df, column_type, c_map):
    """00_baseline_C_entry_rate.csv에서 (장비, 컬럼, defect) -> 평소 진입률을 읽어온다.

    인자 df/c_map은 더 이상 계산에 쓰지 않지만(호출부 시그니처 유지), column_type은
    C유형만 남기는 필터로 계속 쓴다.

    (26.08.11) 키에 defect가 들어간다 — 한 컬럼이 두 defect의 원인이면 경계값이 둘이라
    "평소 얼마나 그 구간에 있었나"도 둘이다. 하나로 뭉치면 경보 판정 기준이 섞인다.
    """
    if not os.path.exists(BASELINE_C_ENTRY_RATE_CSV):
        raise FileNotFoundError(
            f"{BASELINE_C_ENTRY_RATE_CSV} 없음 — "
            "먼저 `python -m pipeline.step0_preprocessing`을 실행하세요."
        )
    table = pd.read_csv(BASELINE_C_ENTRY_RATE_CSV)
    c_columns = {col for col, t in column_type.items() if t == "C"}
    table = table.loc[table["column"].isin(c_columns)]
    # 그룹별 비율의 median이 아니라 풀링(전체 진입 샷 / 전체 OK샷)을 쓴다. median은 원래
    # "한 그룹이 튀어도 안 흔들리게" 고른 것이었는데, 희귀 사건에서 0으로 붕괴한다 —
    # DP04 CLN_Flow는 54개 그룹 중 49개가 진입 0건이라 median이 0.000%가 되고(실제
    # 15,604샷 중 5건 = 0.032%), 그러면 "평소 대비 몇 배"가 정의 불가라 이진 판정으로
    # 빠져 Health Index가 saturate했다. 나머지 11개 조합은 두 방식 차이가 0.8% 이내라
    # 잃는 게 없다.
    agg = table.groupby(["Machine_ID", "column", "matched_defect"])[
        ["n_in_zone", "n_ok_shots"]].sum()
    rate = agg["n_in_zone"] / agg["n_ok_shots"]
    return {(m, c, d): float(v) for (m, c, d), v in rate.items()}


# ----------------------------------------------------------------------
# 6. 파일 단위 처리
# ----------------------------------------------------------------------
def process_file(source_name, path, analysis_columns, column_type, direction_map,
                  ab_value_map, c_map, e_value_map, e_std_map, e_ok_mean_map,
                  fallback_std_map, stratum_target_map, state):
    df = pd.read_csv(path)
    n_input_rows = len(df)

    # 공통 분석 가능 컬럼만 사용 (두 파일 컬럼이 다를 경우 대비)
    usable_columns = [c for c in analysis_columns if c in df.columns]
    if len(usable_columns) != len(analysis_columns):
        skipped = set(analysis_columns) - set(usable_columns)
        print(f"[{source_name}] 경고: 원본에 없는 분석 대상 컬럼 {skipped} 은(는) 제외합니다.")

    df["source_file"] = source_name
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df = df.sort_values(GROUP_KEYS + ["DateTime"]).reset_index(drop=True)

    c_baseline_rate = compute_c_type_baseline_rate(df, column_type, c_map)
    spec_rules = compute_spec_violation_rules(df, usable_columns)
    # (26.08.08) 설비 정비 대상 상한 알람(rel_28) — 현재 Vibration. 원인 티어표에 없는
    # 컬럼이라 C유형/짝짓기로는 안 걸리지만 관계DB가 별도 파일로 넘겨준 감시 대상이다.
    ext_rules = load_external_limit_rules()
    ext_breach = compute_external_limit_breach(df, ext_rules)
    print(f"[{source_name}] 멘토 스펙 검사 대상 {len(spec_rules)}개 컬럼: "
          + ", ".join(f"{c}(평소위반 {r['rate']*100:.3f}%, 연속 {r['run']}샷이면 경보)"
                      for c, r in spec_rules.items()))

    total_out_rows = 0
    warning_count = 0
    warning_samples = []

    for group_vals, gdf in df.groupby(GROUP_KEYS, sort=False):
        machine_id, product_id, recipe_id = group_vals
        group_key = f"{product_id}|{recipe_id}"
        gdf = gdf.sort_values("DateTime")
        if len(gdf) < WINDOW:
            continue
        datetimes = gdf["DateTime"].to_numpy()[WINDOW - 1:]

        out_frames = []
        for col in usable_columns:
            # (26.08.11) 한 컬럼이 두 defect의 원인이면 defect마다 따로 돈다 —
            # 경계값도 경보 판정도 defect별로 다르기 때문이다. C유형이 아니거나
            # 짝이 하나면 [None] 한 번이라 예전과 완전히 같은 경로다.
            for c_variant in (c_map.get((col, group_key)) or [None]):
                values = gdf[col].to_numpy(dtype=float)
                result = compute_group_rolling(values)
                if result is None:
                    continue
                rolling_mean, rolling_std, difference, slope = result
                current_value = values[WINDOW - 1:]

                col_type = column_type.get(col)
                baseline = np.nan
                threshold = np.nan
                extra = {}
                if col_type in ("A", "B"):
                    baseline = ab_value_map.get((col, group_key), np.nan)
                elif col_type == "C":
                    # 위 for문이 이미 이 (컬럼, 그룹)의 defect 하나를 골라줬다.
                    if c_variant is not None:
                        threshold = c_variant["threshold"]
                        extra = c_variant
                    # target(정상 기준값)은 threshold와 별개 — Product×Recipe별 OK median.
                    baseline = stratum_target_map.get((product_id, recipe_id, col), np.nan)
                elif col_type == "E":
                    baseline = e_value_map.get(col, np.nan)

                baseline_arr = np.full(len(current_value), baseline, dtype=float)
                threshold_arr = np.full(len(current_value), threshold, dtype=float)

                # --- std 안전 대체 로직 ---
                eff_std = rolling_std.copy()
                need_fallback = np.isnan(eff_std) | (eff_std == 0)
                if need_fallback.any():
                    fb_val = np.nan
                    if col_type == "E":
                        fb_val = e_std_map.get(col, np.nan)
                    if fb_val is None or (isinstance(fb_val, float) and np.isnan(fb_val)) or fb_val == 0:
                        fb_val = fallback_std_map.get((product_id, recipe_id, col), np.nan)
                    eff_std = np.where(need_fallback, fb_val, eff_std)

                valid_baseline = ~np.isnan(baseline_arr)
                valid_std = (~np.isnan(eff_std)) & (eff_std != 0)
                calc_mask = valid_baseline & valid_std

                # 추세분석 목적: 순간값이 아니라 최근 10개 평균(rolling_mean)이 baseline에서
                # 얼마나 벗어났는지를 기준으로 정규화 편차를 계산한다.
                normalized_deviation = np.full(len(current_value), np.nan)
                normalized_deviation[calc_mask] = (
                    (rolling_mean[calc_mask] - baseline_arr[calc_mask]) / eff_std[calc_mask]
                )
                # std를 전혀 구할 수 없는 경우: 상대/절대 편차로 대체 표기(참고용, 조기경보 판정에는 미사용)
                rel_mask = valid_baseline & (~valid_std)
                nz_base = rel_mask & (baseline_arr != 0)
                z_base = rel_mask & (baseline_arr == 0)
                normalized_deviation[nz_base] = (
                    (rolling_mean[nz_base] - baseline_arr[nz_base]) / np.abs(baseline_arr[nz_base])
                )
                normalized_deviation[z_base] = rolling_mean[z_base] - baseline_arr[z_base]

                # 10개 단위 로컬 slope의 부호. 장기 drift 신호와는 스케일이 달라서(뒤
                # compute_reference_style_trend 참고) 이것만으로 추세를 주장하면 안 된다.
                # (26.08.06 수정) 예전엔 이 값을 그대로 trend_direction으로 내보냈는데, 저장되는
                # 행은 전부 early_warning=True인 행이고 그 경보를 실제로 띄운 건 CUSUM(A/B/E)
                # 이나 threshold 진입(C)이지 이 로컬 slope가 아니다. 그래서 "지속적인 하강이
                # 감지되었습니다" 메시지에 trend_direction="up"이 붙는 행이 절반 가까이 나왔고
                # (하강 경고 11,945행 중 5,383행), build_health_index -> agent.py가 그걸 그대로
                # 읽어서 엔지니어에게 반대 방향을 알려주고 있었다. 이제 경보가 뜬 행은 아래에서
                # 그 경보 자신의 방향으로 덮어쓴다(alert_direction).
                local_slope_direction = np.where(slope > 0, "up", np.where(slope < 0, "down", "flat"))
                trend_direction = local_slope_direction.copy()

                early_warning = np.zeros(len(current_value), dtype=bool)
                messages = np.array([""] * len(current_value), dtype=object)

                # --- 멘토 실측 스펙(LSL/USL) 위반 — A/B/C/E 유형 판정과 무관하게 공통 적용 ---
                # 상대 기준(baseline 대비 드리프트)만 보던 기존 판정에 절대 기준을 하나 더한다.
                # 판정 근거/연속 샷 수를 정한 이유는 compute_spec_violation_rules 주석 참고.
                rule = spec_rules.get(col)
                if rule is not None:
                    spec_lsl_arr = np.full(len(current_value), rule["lsl"], dtype=float)
                    spec_usl_arr = np.full(len(current_value), rule["usl"], dtype=float)
                    out_full = (values < rule["lsl"]) | (values > rule["usl"])
                    spec_status_arr = np.where(out_full[WINDOW - 1:], "OUT_OF_SPEC", "OK").astype(object)
                    # 전체 이력에 대해 "연속 run샷 위반"이 막 시작된 시점만 이벤트로 잡는다
                    # (상태형으로 두면 긴 이탈 구간 내내 매 샷 알림이 나감 — episode_id가 있긴
                    #  하지만 진입 시점이 알림의 단위여야 맞다. Type C entered_first와 동일 논리).
                    spec_violation = _sustained_first(out_full, rule["run"])[WINDOW - 1:]
                else:
                    spec_lsl_arr = np.full(len(current_value), np.nan)
                    spec_usl_arr = np.full(len(current_value), np.nan)
                    spec_status_arr = np.full(len(current_value), "", dtype=object)
                    spec_violation = np.zeros(len(current_value), dtype=bool)

                # --- CUSUM(누적합) — A/B/E유형의 "지속적 편차" 판정에 공통으로 쓴다 ---
                # rolling_mean 기반 WINDOW+PERSIST_WINDOW 방식보다 반응이 빠르다. target(OPCOND
                # 공통 baseline)과 안정적인 참조 std(rolling 아닌 스칼라)로 샷 단위 z-score를
                # 만들고 전체 이력에 누적합을 씌운다 — K/H 튜닝 배경은 위 CUSUM_K/H 주석 참고.
                ref_std_scalar = np.nan
                if col_type == "E":
                    ref_std_scalar = e_std_map.get(col, np.nan)
                if ref_std_scalar is None or (isinstance(ref_std_scalar, float) and np.isnan(ref_std_scalar)) or ref_std_scalar == 0:
                    ref_std_scalar = fallback_std_map.get((product_id, recipe_id, col), np.nan)
                cusum_pos = cusum_neg = None
                # (26.08.08) 유형 제한을 풀었다 — 예전엔 A/B/E만 CUSUM을 받고 C는 threshold
                # 판정만 받았는데, 그건 원리가 아니라 C 컬럼에 baseline을 안 만들어줬던 탓이다
                # (실제로는 stratum_target_map에 Product×Recipe OK median이 이미 있다).
                # 전 컬럼 측정 결과 no_trend 장비에서의 CUSUM 오경보율이 0.000~0.364%로
                # 35개 전부 C_DANGER_ALPHA(1%) 미만이라, 붙여서 해로운 컬럼이 없다.
                # 유형이 "어떤 경보를 받는지"를 정하지 않게 하는 것이 목적이다(김시우님 지적).
                #
                # (26.08.11) **E유형의 CUSUM target을 이론상수가 아니라 reference_OK_mean으로
                # 바꾼다.** CUSUM은 "지금 있어야 할 자리에서 밀려났나"를 재는 도구인데, E유형만
                # target이 이론값(Kerf_Angle=90, Package_Size=5)이라 정상 상태에서도 항상 얼마간
                # 벗어나 있었다. 그 고정 편차는 드리프트가 아닌데 CUSUM은 방향이 안 바뀌는
                # 편차를 계속 누적하므로, 영원히 끝나지 않는 드리프트로 읽힌다.
                #
                # 실측 — Kerf_Angle은 이론값 90 대비 정상 평균이 90.0329로 **+0.317σ 고정
                # 치우침**이 있다(00_baseline_E.csv). 그 결과:
                #   · 4대 경보행 457/462/662/654 — 시나리오 없는 정상 장비 DP01에도 똑같이 뜬다
                #     (진짜 시나리오 컬럼은 CLN_Flow 170배 / Laser_Power 45배로 갈린다)
                #   · 순수 잡음 시뮬레이션(추세 0)에서 치우침 0.317σ면 경보 샷 2.06%,
                #     장비당 514건 — 실측 457~662와 일치한다. 즉 신호가 안 들어 있다.
                #   · 치우침 0σ면 0.15%(장비당 39건)로 떨어진다. **0.317σ 하나로 오경보 14배.**
                # 0.317σ는 CUSUM_K(0.7)보다 작아 "감지"된 게 아니다 — 누적합이 0으로 되돌아가는
                # 힘이 약해져서 잡음이 H를 넘는 빈도가 올라간 것이다.
                #
                # 다른 E컬럼은 치우침이 0.001~0.036σ라 사실상 안 바뀐다. Kerf_Angle만 고쳐진다.
                # 이론값은 버리지 않고 baseline_arr(=출력의 baseline/difference/
                # normalized_deviation)에 그대로 남긴다 — "설계값에서 얼마나 비껴 있나"는
                # 여전히 볼 값이고, 다만 그건 매일 울릴 경보가 아니라 한 번 보고할 사실이다.
                cusum_target = baseline
                if col_type == "E":
                    ok_mean = e_ok_mean_map.get(col, np.nan)
                    if ok_mean is not None and not np.isnan(ok_mean):
                        cusum_target = ok_mean
                if not np.isnan(cusum_target) and ref_std_scalar and ref_std_scalar > 0:
                    z_full = (values - cusum_target) / ref_std_scalar
                    s_pos_full, s_neg_full = compute_cusum(z_full)
                    cusum_pos, cusum_neg = s_pos_full[WINDOW - 1:], s_neg_full[WINDOW - 1:]

                if col_type == "A":
                    bad_dir = direction_map.get(col)
                    if cusum_pos is not None:
                        ew = (cusum_pos > CUSUM_H) if bad_dir == "up" else (cusum_neg < -CUSUM_H)
                    else:
                        ew = np.zeros(len(current_value), dtype=bool)
                    early_warning |= ew
                    trend_direction[ew] = bad_dir  # 경보를 띄운 CUSUM의 방향 = A유형의 나쁜 방향
                    dir_word = "상승" if bad_dir == "up" else "하강"
                    for i in np.where(ew)[0]:
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                            f"정상 Baseline 대비 지속적인 {dir_word} 추세가 감지되었습니다."
                        )

                elif col_type == "B":
                    if cusum_pos is not None:
                        ew = (cusum_pos > CUSUM_H) | (cusum_neg < -CUSUM_H)
                    else:
                        ew = np.zeros(len(current_value), dtype=bool)
                    early_warning |= ew
                    for i in np.where(ew)[0]:
                        up_side = cusum_pos[i] > CUSUM_H
                        trend_direction[i] = "up" if up_side else "down"  # 경보를 띄운 CUSUM 쪽
                        side = "높은" if up_side else "낮은"
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                            f"정상 Baseline(최적값) 대비 {side} 방향으로 지속적으로 벌어지는 편차가 감지되었습니다."
                        )

                elif col_type == "C":
                    risky_direction = extra.get("risky_direction") if extra else None
                    valid_threshold = ~np.isnan(threshold_arr)
                    if risky_direction is not None and valid_threshold.any():
                        if risky_direction == "low_is_risky":
                            entered_raw = (current_value <= threshold_arr) & valid_threshold
                            slope_toward_risk = slope < 0
                            risky_side_raw = values < threshold
                        else:
                            entered_raw = (current_value >= threshold_arr) & valid_threshold
                            slope_toward_risk = slope > 0
                            risky_side_raw = values > threshold
                        # 위험영역에 "PERSIST_WINDOW행 연속" 머물렀을 때만, 그 시작 시점 1행만 경고.
                        # 예전엔 1행만 넘어도 진입으로 잡아서 임계값 근처 노이즈가 계속 "새로 진입"
                        # 취급됐음(Surface_Roughness 22,948건 중 21,426건이 이 케이스였음).
                        entered_first = _sustained_first(entered_raw, PERSIST_WINDOW)
                        # (26.08.05) 예전엔 rolling_mean 기준 risk_margin_z(정상 쪽 편차도 다 잡던
                        # 버그)를 썼다가, 그다음엔 "위험선까지 남은 여유가 Z_THRESHOLD std 미만"으로
                        # 고쳤는데, CLN_Pressure로 검증해보니 rolling MEAN 자체가 개별 샷 위험 진입을
                        # 지워버리는 문제가 있었다(개별 샷 6.68%가 threshold 아래인데 rolling mean은
                        # 356일 중 0번만 아래로 내려감 — 66,824배 차이). 반대로 rolling MIN을 쓰면
                        # 10개 중 1개만 넘어도 걸려 개별샷 확률의 절반(49.47%)까지 과민해진다.
                        # build_health_index.py의 defect_zone_rate(위험구간 진입 샷 비율)와 같은
                        # 방식으로 통일 — 이 WINDOW(10행) 안에서 위험구간에 들어간 샷의 비율이
                        # 평소(baseline_rate) 대비 C_DANGER_RATE_MULTIPLE배 이상이면 "접근 중".
                        windows_risky = np.lib.stride_tricks.sliding_window_view(risky_side_raw, WINDOW)
                        danger_count = windows_risky.sum(axis=1)
                        danger_rate = danger_count / WINDOW
                        base_rate = c_baseline_rate.get(
                            (machine_id, col, extra.get("matched_defect"))) or 0.0
                        # 평소 진입률에서 WINDOW개 중 몇 개 이상이면 "우연이라 보기 어려운가".
                        # base_rate=0이어도 이 식이 정의된다(k=1) — 예전의 별도 분기가 필요 없다.
                        need = binomial_alert_count(base_rate, WINDOW, config.C_DANGER_ALPHA)
                        rate_exceeded = danger_count >= need
                        approaching_raw = (
                            (~entered_raw) & slope_toward_risk & valid_threshold & rate_exceeded
                        )
                        # "접근중"도 상태형 메시지("지속적으로 접근하는 추세")라 진입과
                        # 같은 논리로 지속성 요구 — 순간적인 z 튐이 아니라 계속 접근할 때만.
                        approaching = _sustained_state(approaching_raw, PERSIST_WINDOW)
                        ew = entered_first | approaching
                        early_warning |= ew
                        # C유형 경보의 방향 = 위험 threshold 쪽으로 가는 방향(진입했든 접근 중이든).
                        trend_direction[ew] = "down" if risky_direction == "low_is_risky" else "up"
                        for i in np.where(entered_first)[0]:
                            messages[i] = (
                                f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                                f"위험 Threshold({threshold_arr[i]:.4f})에 진입했습니다."
                            )
                        # 경보 근거를 문구에 그대로 싣는다 — "몇 배"가 아니라 "평소라면 이만큼
                        # 나올 확률이 얼마나 낮은가"가 판정 근거이므로 그걸 읽히게 쓴다.
                        base_txt = (f"이 장비 평소 {base_rate*100:.2f}%" if base_rate
                                    else "이 장비는 평소 진입 이력 없음")
                        for i in np.where(approaching)[0]:
                            messages[i] = (
                                f"{machine_id} / {product_id} / {recipe_id}의 {col}은(는) "
                                f"최근 {WINDOW}개 샷 중 {int(danger_count[i])}개가 위험 Threshold"
                                f"({threshold_arr[i]:.4f}) 구간에 들어감"
                                f"({base_txt} — 우연이라면 {need}개 이상 나올 확률이 "
                                f"{config.C_DANGER_ALPHA*100:.0f}% 미만) — "
                                f"위험 방향으로 지속적으로 접근하는 추세가 감지되었습니다."
                            )

                    # (26.08.08) C유형에도 CUSUM 경로를 추가한다 — threshold 판정을 대체하는
                    # 게 아니라 더한다. threshold는 "위험구간에 샷이 들어갔나"(꼬리)를 보고
                    # CUSUM은 "평균 수준이 밀렸나"를 보므로 서로 다른 이상을 잡는다.
                    # 실측: CLN_Flow DP04는 CUSUM이 threshold보다 6~9일 빨랐고(2/22 vs 2/28)
                    # 나머지 3대에서는 0건이었다. 방향은 A유형과 같이 위험한 쪽만 본다 —
                    # 반대쪽은 이 컬럼에서 경보와 무관하다.
                    if cusum_pos is not None and risky_direction is not None:
                        ew_c = ((cusum_neg < -CUSUM_H) if risky_direction == "low_is_risky"
                                else (cusum_pos > CUSUM_H))
                        early_warning |= ew_c
                        trend_direction[ew_c] = "down" if risky_direction == "low_is_risky" else "up"
                        side = "낮은" if risky_direction == "low_is_risky" else "높은"
                        for i in np.where(ew_c)[0]:
                            if not messages[i]:
                                messages[i] = (
                                    f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                                    f"정상 Baseline 대비 {side} 방향으로 지속적으로 벌어지는 "
                                    f"편차가 감지되었습니다."
                                )

                elif col_type == "E":
                    if cusum_pos is not None:
                        ew = (cusum_pos > CUSUM_H) | (cusum_neg < -CUSUM_H)
                    else:
                        ew = np.zeros(len(current_value), dtype=bool)
                    early_warning |= ew
                    for i in np.where(ew)[0]:
                        trend_direction[i] = "up" if cusum_pos[i] > CUSUM_H else "down"
                        # (26.08.11) 문구도 target과 맞춘다 — 판정은 정상 수준(cusum_target)
                        # 대비인데 "이론 기준값 대비"라고 쓰면 근거를 잘못 읽게 된다.
                        # 이론값은 다를 때만 괄호로 같이 보여준다(Kerf_Angle 90 vs 90.0328).
                        theo = (f" (이론 기준값 {baseline_arr[i]:.4f})"
                                if not np.isnan(baseline_arr[i])
                                and abs(baseline_arr[i] - cusum_target) > 1e-9 else "")
                        messages[i] = (
                            f"{machine_id} / {product_id} / {recipe_id}의 {col}에서 "
                            f"정상 수준({cusum_target:.4f}){theo} 대비 지속적으로 벌어지는 "
                            f"편차가 감지되었습니다."
                        )
                # 그 외(Baseline 미매핑 컬럼): baseline/type 정보만 NONE으로 기록
                # 멘토 스펙 위반은 유형과 무관하게 공통 적용 — 다른 경보와 같은 행에서 동시에
                # 뜰 수 있으므로(예: CUSUM 드리프트 끝에 실제로 스펙을 벗어남) 메시지를 덧붙인다.
                # 이게 제일 급한 신호라 앞에 붙인다.
                for i in np.where(spec_violation)[0]:
                    smsg = (
                        f"{machine_id} / {product_id} / {recipe_id}의 {col}이(가) 멘토 실측 스펙"
                        f"(LSL {rule['lsl']} ~ USL {rule['usl']})을 {rule['run']}샷 연속으로 "
                        f"벗어났습니다(현재 {current_value[i]:.4f}). 평소 위반율 {rule['rate']*100:.3f}%"
                        f"로는 우연히 나올 수 없는 수준입니다."
                    )
                    messages[i] = f"{smsg} {messages[i]}".strip() if messages[i] else smsg
                # (26.08.08) 설비 상한 알람(rel_28) — 유형/짝짓기와 무관하게 공통 적용.
                # "그날 상한 초과 샷이 우연이라 보기 어려울 만큼 몰렸는가"를 (장비, 날짜)로
                # 판정해두고, 그날의 샷에 표시한다. 문구는 "위험 증가"가 아니라 "관련 가능성"
                # 이다 — 감시 데이터로는 연결 불량이 둘 다 검증되지 않는다(JHdaimma 회신 ⑤).
                ext_rule = ext_rules.get(col)
                external_limit_warning = np.zeros(len(current_value), dtype=bool)
                if ext_rule is not None:
                    days = gdf["DateTime"].dt.date.to_numpy()[WINDOW - 1:]
                    over = current_value > ext_rule["upper_limit"]
                    external_limit_warning = np.array(
                        [bool(ext_breach.get((col, machine_id, d))) for d in days]) & over
                    ev = " / ".join(f"{d['defect']} 관련 가능성" for d in ext_rule["defects"])
                    for i in np.where(external_limit_warning)[0]:
                        emsg = (
                            f"{machine_id}의 {col}이(가) 설비 상한({ext_rule['upper_limit']})을 "
                            f"넘었습니다(현재 {current_value[i]:.4f}). 그날 초과 샷이 우연으로 "
                            f"보기 어려운 수준입니다 — 설비 정비 점검 필요. {ev}."
                        )
                        messages[i] = f"{emsg} {messages[i]}".strip() if messages[i] else emsg

                early_warning = early_warning | spec_violation | external_limit_warning

                matched_defect_val = extra.get("matched_defect", "") if extra else ""
                matched_defect_arr = np.full(len(current_value), matched_defect_val, dtype=object)

                frame = pd.DataFrame({
                    "source_file": source_name,
                    "DateTime": datetimes,
                    "Machine_ID": machine_id,
                    "Product_ID": product_id,
                    "Recipe_ID": recipe_id,
                    "column": col,
                    "type": col_type if col_type else "NONE",
                    "matched_defect": matched_defect_arr,
                    "baseline": baseline_arr,
                    "threshold": threshold_arr,
                    "spec_lsl": spec_lsl_arr,
                    "spec_usl": spec_usl_arr,
                    "spec_status": spec_status_arr,
                    "current_value": current_value,
                    "rolling_mean": rolling_mean,
                    "rolling_std": rolling_std,
                    "difference": difference,
                    "slope": slope,
                    "normalized_deviation": normalized_deviation,
                    "trend_direction": trend_direction,
                    "spec_violation_warning": spec_violation,
                    "external_limit_warning": external_limit_warning,
                    "early_warning": early_warning,
                    # (26.08.05 추가) early_warning은 상태형이라 이상이 지속되는 동안 매 샷마다
                    # True로 계속 저장된다 — "몇 건"을 셀 때 샷 행 수를 세면 하나의 지속 사건이
                    # 수천 건처럼 부풀려 보인다(예: CLN_Flow는 10,476행이지만 실제 독립 사건은
                    # 97건뿐). episode_id는 이 그룹×컬럼 안에서 early_warning이 True로 "새로
                    # 시작된" 시점마다 1씩 증가하는 번호 — (Machine_ID,Product_ID,Recipe_ID,
                    # column,episode_id)로 묶으면 "사건 수"를 정확히 셀 수 있다.
                    "episode_id": np.cumsum(
                        early_warning & ~np.concatenate(([False], early_warning[:-1]))
                    ),
                    "message": messages,
                })
                out_frames.append(frame)

        if not out_frames:
            continue
        group_result = pd.concat(out_frames, ignore_index=True)[OUTPUT_COLUMNS]
        # 계산(Rolling/판정)은 전체 행에 대해 수행하되, 파일에는 early_warning=True인 행만 저장한다.
        ew_rows = group_result[group_result["early_warning"]]
        if len(ew_rows) > 0:
            ew_rows.to_csv(OUTPUT_CSV, mode="a", header=state["first_write"], index=False, encoding="utf-8-sig")
            state["first_write"] = False

        total_out_rows += len(ew_rows)
        warning_count += len(ew_rows)
        if len(warning_samples) < 10 and len(ew_rows) > 0:
            needed = 10 - len(warning_samples)
            warning_samples.extend(ew_rows.head(needed).to_dict("records"))

    return n_input_rows, total_out_rows, warning_count, warning_samples


# ----------------------------------------------------------------------
# 7. 기존 00_machine_column_trend.csv(일별 집계 + Kendall tau 기반)와의 교차검증
#
#    처음에는 본 스크립트가 이미 계산해 둔 10개 단위 로컬 rolling slope의
#    방향(up/down)을 그룹 전체에서 다수결로 집계해 비교했으나, 실제로 확인해보니
#    강한 장기 drift 컬럼(DP02 Vibration)과 no_trend 컬럼(DP01 Laser_Current)의
#    로컬 slope 비율 분포가 통계적으로 거의 동일했다(median 0.73 vs 0.71).
#    즉 10개 단위 로컬 rolling window는 90일치 장기 drift 신호를 애초에
#    분리해내지 못하는 스케일이라, 임계값을 조정해도 해결되지 않는 구조적
#    한계였다. 그래서 교차검증만큼은 조기경보 로직과 별개로, 참조 파일과
#    동일한 방법론(Machine_ID별 일별 평균 집계 -> Kendall tau)으로 다시 계산한다.
# ----------------------------------------------------------------------
def compute_reference_style_trend(path, columns):
    df = pd.read_csv(path, usecols=["DateTime", "Machine_ID"] + columns)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df["date"] = df["DateTime"].dt.date

    result = {}
    for machine_id, g in df.groupby("Machine_ID"):
        daily = g.groupby("date")[columns].mean().sort_index().reset_index(drop=True)
        day_idx = np.arange(len(daily))
        for col in columns:
            series = daily[col]
            if series.nunique() < 2 or len(series) < 3:
                result[(machine_id, col)] = "flat"
                continue
            tau, p_value = stats.kendalltau(day_idx, series)
            if pd.isna(tau) or pd.isna(p_value) or p_value >= KENDALL_P_THRESHOLD:
                result[(machine_id, col)] = "flat"
            else:
                result[(machine_id, col)] = "up" if tau > 0 else "down"
    return result


def cross_validate_machine_trend(reference_source_path, analysis_columns):
    ref = pd.read_csv(MACHINE_TREND_CSV)

    trend_class_direction_map = {
        "candidate_upward_drift": "up",
        "candidate_downward_drift": "down",
        "no_trend": "flat",
        "mixed": "flat",
        "not_applicable": None,
    }

    my_trend = compute_reference_style_trend(reference_source_path, analysis_columns)

    rows = []
    for row in ref.itertuples(index=False):
        key = (row.Machine_ID, row.column)
        my_direction = my_trend.get(key)
        if my_direction is None:
            continue
        ref_direction = trend_class_direction_map.get(row.trend_class)
        if ref_direction is None:
            continue
        rows.append({
            "Machine_ID": row.Machine_ID,
            "column": row.column,
            "my_direction": my_direction,
            "reference_trend_class": row.trend_class,
            "reference_direction": ref_direction,
            "agree": my_direction == ref_direction,
        })

    result = pd.DataFrame(rows)
    result.to_csv(CROSS_VALIDATION_CSV, index=False, encoding="utf-8-sig")

    print(f"\n===== 00_machine_column_trend.csv 교차검증 (일별 집계 + Kendall tau 방식) =====")
    if len(result) == 0:
        print("비교 가능한 항목이 없습니다.")
    else:
        n_agree = int(result["agree"].sum())
        n_total = len(result)
        print(f"비교 대상 {n_total}건 중 일치 {n_agree}건({n_agree / n_total * 100:.1f}%), 불일치 {n_total - n_agree}건")
    print(f"저장 파일: {CROSS_VALIDATION_CSV}")
    return result


def main():
    check_required_files()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(OUTPUT_CSV):
        os.remove(OUTPUT_CSV)  # 재실행 시 이전 결과 덮어쓰기 (원본/기존 산출물 아님, 본 스크립트의 출력 파일)

    analysis_columns = load_analysis_columns()
    print(f"[분석 대상 연속형 컬럼] 총 {len(analysis_columns)}개")
    print(analysis_columns)

    (column_type, direction_map, ab_value_map, c_map,
     e_value_map, e_std_map, e_ok_mean_map) = load_baseline_maps()
    fallback_std_map, stratum_target_map = load_stratum_reference_maps()

    mapped = [c for c in analysis_columns if c in column_type]
    unmapped = [c for c in analysis_columns if c not in column_type]
    print(f"[Baseline 매핑] 유형 매핑된 컬럼 {len(mapped)}개 / 매핑 안 된 컬럼 {len(unmapped)}개")
    print(f"  - 매핑 안 된 컬럼(참고용 rolling 통계만 계산, early_warning 미판정): {unmapped}")

    state = {"first_write": True}
    summary = {}

    for source_name, path in RAW_INPUT_FILES:
        print(f"\n===== 처리 시작: {source_name} =====")
        try:
            n_in, n_out, n_warn, samples = process_file(
                source_name, path, analysis_columns, column_type, direction_map,
                ab_value_map, c_map, e_value_map, e_std_map, e_ok_mean_map,
                fallback_std_map, stratum_target_map, state,
            )
        except Exception as exc:
            print(f"[오류] {source_name} 처리 중 예외 발생: {exc}", file=sys.stderr)
            raise
        summary[source_name] = {"n_input_rows": n_in, "n_output_rows": n_out, "n_early_warning": n_warn, "samples": samples}
        print(f"[{source_name}] 입력 행 수: {n_in}")
        print(f"[{source_name}] 결과 행 수: {n_out}")
        print(f"[{source_name}] early_warning 건수: {n_warn}")

    print("\n===== 전체 요약 =====")
    total_out = sum(v["n_output_rows"] for v in summary.values())
    total_warn = sum(v["n_early_warning"] for v in summary.values())
    print(f"결과 파일: {OUTPUT_CSV}")
    print(f"결과 전체 행 수: {total_out}")
    for source_name, v in summary.items():
        print(f"  - {source_name}: 입력 {v['n_input_rows']}행 -> 결과 {v['n_output_rows']}행, early_warning {v['n_early_warning']}건")
    print(f"early_warning 총합(샷 행 수): {total_warn}")

    # (26.08.05 추가) early_warning은 상태형이라 지속되는 동안 매 샷마다 카운트된다 —
    # "행 수"만 보면 하나의 긴 사건도 수천 건처럼 보인다. episode_id로 묶어 실제
    # 독립 사건 수를 따로 센다.
    if total_warn > 0 and os.path.exists(OUTPUT_CSV):
        ew = pd.read_csv(OUTPUT_CSV, usecols=["Machine_ID", "Product_ID", "Recipe_ID", "column", "episode_id"])
        total_episodes = len(ew.drop_duplicates(["Machine_ID", "Product_ID", "Recipe_ID", "column", "episode_id"]))
        print(f"early_warning 총합(독립 사건 수): {total_episodes}  "
              f"(행 수 대비 {total_episodes/total_warn*100:.1f}% — 나머지는 같은 사건이 지속된 것)")

    # (26.08.06 추가) 멘토 실측 스펙 기준 현황 — 경보 건수와 별개로, 저장된 경보 행 중
    # 실제로 스펙을 벗어나 있는 게 몇 건인지가 "얼마나 급한가"의 절대 기준이 된다.
    if total_warn > 0 and os.path.exists(OUTPUT_CSV):
        sp = pd.read_csv(OUTPUT_CSV, usecols=["column", "spec_status", "spec_violation_warning"])
        n_spec_alerts = int(sp["spec_violation_warning"].sum())
        checked = sp[sp["spec_status"].isin(["OK", "OUT_OF_SPEC"])]
        n_out = int((checked["spec_status"] == "OUT_OF_SPEC").sum())
        print(f"\n===== 멘토 실측 스펙(LSL/USL) 검사 =====")
        print(f"스펙 위반 경보(연속 위반): {n_spec_alerts}건")
        print(f"경보 행 중 스펙 검사 대상: {len(checked)}행, 그중 값이 스펙 밖: {n_out}행")
        if n_spec_alerts == 0:
            print("  -> 지속적 스펙 이탈은 없음. 이 데이터의 스펙 위반은 전부 정상 분포의 "
                  "꼬리(단발성)이며, 8개 컬럼은 89일 내내 위반 0건입니다 "
                  "— 멘토 스펙이 자연 변동폭보다 넓다는 뜻(상세 근거는 "
                  "compute_spec_violation_rules 주석).")

    if total_warn == 0:
        print("[점검] early_warning이 0건입니다. 임계값(CUSUM_H / C_DANGER_RATE_MULTIPLE) 또는 "
              "Baseline 매핑 로직을 점검해야 합니다.")

    cross_validate_machine_trend(RAW_INPUT_FILES[0][1], analysis_columns)

    for source_name, v in summary.items():
        print(f"\n===== {source_name} early_warning 샘플 (최대 10개) =====")
        if not v["samples"]:
            print("(해당 없음)")
        for s in v["samples"]:
            print(f"  [{s['DateTime']}] {s['message']}")

    return summary


if __name__ == "__main__":
    main()
