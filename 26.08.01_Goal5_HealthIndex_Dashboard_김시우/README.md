# Goal5 — Health Index 계산 (v3, 김시우)

**대시보드는 없습니다.** 이 프로젝트 목표는 "데이터 분석해서 발표하는 것"이 아니라
"엔지니어를 대신해서 분석해주는 AI Agent"라서, 정적 HTML 대시보드는 만들지 않습니다.
이 폴더는 AI Agent(`26.08.01_Goal_AI_Agent_Prototype_김시우/`)가 읽는 데이터만 만듭니다.

## 실행

Step0(전처리/baseline)와 `trend_analysis.py`(추세판정/조기경보)를 먼저 돌려야 합니다 —
이 스크립트는 그 둘의 산출물을 읽어서 레벨+추세를 종합합니다.

```bash
python pipeline/step0_preprocessing.py
python trend_analysis.py
python 26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py
```

(`trend_analysis.py` 산출물이 없어도 실행은 되지만, 그 경우 추세 쪽 필드
`trend_direction`/`early_warning_active`/`trend_message`는 비어서 나갑니다.)

`health_index_data.json`이 생성되고, AI Agent(`agent.py`)가 이 파일을 바로 읽습니다.

## Health Index가 답하는 질문

**"다른 장비/변수 대비 몇 등인가"가 아니라 "스펙 아웃(임시 USL/LSL) 되기 전에 미리 알 수
있는가"입니다.** (v1은 근거 없는 가중치로 만든 단일 점수였고, v2는 정규분포/순위 기반
백분위로 만들었다가 "통계적으로 얼마나 특이한가"를 재는 거라 목적과 안 맞아서 폐기 —
자세한 시행착오는 커밋 로그 참고.)

## 계산 구조 (v3)

```
1) 관리한계까지 남은 여유 = 레벨   (26.08.08 개정)
   margin_used_pct = (현재값 − 정상값) / (관리한계 − 정상값) × 100
     관리한계 = 정상값 ± 3σ  (Shewhart, CONTROL_LIMIT_SIGMA)
     0% = 정상값, 100% = 관리한계 도달
   변수별 Health Index = margin_used_pct를 0~100 점수로 단조 변환 (margin_to_health)
     margin 0%    -> 100점
     margin 100%  ->  10점  (관리한계)
     margin 100%+ -> 10 x (100/margin), 0으로 점근
     즉 **10점 미만 = 관리한계(3σ) 초과**입니다. **"스펙아웃"이 아닙니다** —
     89일 동안 멘토 스펙 위반 지속 경보는 0건이고, 스펙아웃은 spec_status로 따로
     표시합니다(현재 전 장비 OK).

   기준선을 전 컬럼 하나로 통일한 이유와, 왜 CUSUM 경보선(0.7σ)이 아니라 3σ인지는
   docs/발표_왜_이_식인가.md 및 compute_level_and_trend의 margin 계산부 주석 참고.
   요약: 0.7σ는 탐지 문턱이라 경보가 확정된 컬럼이 무엇이든 10점 이하로 떨어졌다
   (DP02 Laser_Power가 목표값에서 0.72σ인데 9.7점). 탐지는 CUSUM이 이미 한다.

   화면에는 두 선을 다 싣습니다:
     control_lsl / control_usl  점수를 내는 선 (관리한계)
     lsl / usl                  멘토 실측 스펙 (10개 변수만, 표시용 절대 기준)

2) 추세는 점수에 안 섞고, 두 가지를 같이 제공 (26.08.05부터)
   (a) margin_used_pct의 최근 14일 기울기(%/일) → 나빠지는 방향이면
       (100 − 지금 margin_used_pct) ÷ 기울기 = 예상 며칠 뒤 **관리한계 도달**
       (필드명 estimated_days_to_spec_out은 옛 이름이 남은 것 — 스펙아웃이 아니다)
       (이미 관리한계를 넘었거나 좋아지는 중이면 계산 안 함 — null)
   (b) trend_analysis.py(이승연 원안, WINDOW=10 롤링 + 지속성 필터, Kendall tau
       교차검증됨)가 판정한 "지금 공식적으로 경보가 켜져 있는가"
       → trend_direction("up"/"down"/"flat") / early_warning_active(bool) /
       trend_message(사람이 읽는 설명)
   (a)는 이 스크립트가 margin만 보고 직접 추정한 속도, (b)는 팀이 따로 만들고
   검증한 추세분석 스크립트의 판정을 그대로 가져온 것 — 원래 "전처리 → 추세분석 →
   Health Index가 그 결과를 읽어 씀" 구조를 이렇게 연결했습니다.

3) defect별 Health Index = 그 defect 원인변수들 중 최솟값(최악이 전체를 끌어내림)
   장비별 Health Index   = 그 장비 defect들 중 최솟값
   -> 순위 상위 3개(worst_factors/worst_defects)까지 같이 제공, 1등만 안 보여줌

4) 확정 원인이 아닌 나머지 변수(~24개)도 같은 계산 적용(안전망) — defect 연결/SOP는
   안 붙이고, 여유를 50% 이상 썼을 때만 "미확인 이상"으로 표시

5) 실제 불량 발생 여부(최근 7일 defect rate > 0)는 레벨/추세와 완전히 분리된 필드
   -> "이미 터진 것"과 "터지기 전 조짐"을 안 섞기 위함
```

## 출력에 실제 값이 그대로 들어감

"29.3% 사용" 같은 추상적 숫자 대신, 실제 값(`current_value`/`baseline_median`/`lsl`/`usl`)을
그대로 줍니다. 스펙아웃이면 `spec_status: "SPEC_OUT"`만 표시하고(퍼센트 안 보여줌),
아직 스펙 안이고 나빠지는 중이면 `estimated_days_to_spec_out`(예상 며칠 뒤)을 줍니다.

## 데이터 출처 — 원인 인자는 Goal2 관계DB에서 읽음

원인 판정은 `26.08.05_Goal2_통합_Relationship_DB_JHdaimma/agent_cause_factors.json`
하나에서 온다(agent.py도 같은 파일을 쓴다). 1세대 개별 산출물(daeho/전성재/JHdaimma의
defect별 분석)은 이 통합 DB로 흡수됐다.

**(26.08.08) `per_defect[defect].alert_usable`를 존중한다.** 관계DB는 인자 레벨
`alert_usable`과 defect별 플래그를 따로 들고 있고 둘이 다를 수 있다. 예전엔 인자 레벨
`defects` 목록만 읽어서, DB가 "이 짝으로는 경보를 걸면 안 됨"이라고 적어둔 연결까지
썼다 — 자세한 경위는 아래 "알려진 한계" 참고.

현재 감시되는 defect (실행할 때마다 콘솔에 출력됨):

| defect | 쓸 수 있는 원인 인자 |
|---|---|
| Remain_Coat | `CLN_Pressure`, `CLN_Flow` |
| Chipping | `Power_Efficiency`, `Laser_Power`, `Head_Temp`, `Cooling_Flow` |
| **Particle** | **없음** — 유일한 후보 `CLN_Flow`가 `alert_usable=False`(risk_ratio 0.80) |
| **Micro_Crack** | **없음** — 관계DB의 원인(FDC) 목록에 연결된 인자가 없음 |

- 전처리/baseline/일별 집계 → `pipeline/`(김시우 Step0)
- 추세판정/조기경보(early_warning) → `trend_analysis.py`(이승연 원안, 김시우가 지속성
  필터 추가 + 경로/입력 수정, 저장소 루트) — Health Index가 이 결과를 그대로 읽어 씀

## 알려진 한계

- **(26.08.08 현재) Particle과 Micro_Crack을 감시하지 못합니다.** Particle은 감시
  데이터에서 가장 흔한 불량인데(6,455건, 6.46%) 쓸 수 있는 원인 인자가 없습니다.
  경위: 유일한 후보였던 `CLN_Flow`는 관계DB `per_defect["Particle"].alert_usable=False`
  (risk_ratio 0.80 — 위험구간 불량률이 정상구간보다 **낮다**는 뜻)입니다. 예전엔 이 플래그를
  안 읽어서 Particle 건강도가 CLN_Flow 건강도의 복사본이었고, DP03의 Particle이
  6.8%→10.2%로 늘어나는 동안 건강도는 100.0을 유지했습니다. 지금은 그 연결을 끊고
  **"감시 수단 없음"을 실행 시 경고로 출력**합니다 — 가짜 100점보다 정직합니다.
  실제로 가장 강한 관계는 `Surface_Roughness`↔Particle(risk_ratio 378.38, DB 전체 최강)인데
  `role = 감시지표(Response)`라 원인(FDC) 목록에 없습니다. **Health Index에 결과 지표를
  넣을지는 Goal2 담당자와 협의 필요.**
- **boundary_z/USL/LSL은 컬럼당 대표값 하나(장비 4대 풀링)**입니다 — 장비/레시피마다
  실제 스펙 여유가 다를 수 있는 걸 다 못 담습니다.
- **(26.08.08 발견 및 수정) "현재 상태"를 마지막 하루로 읽던 문제.** 이 신호는 일별 변동이
  그 자체로 큽니다 — CLN_Pressure 진입률은 4대 모두 89일 평균 6.76~7.11%에 표준편차
  1.30~1.67%p로, 하루 사이 4%p씩 튑니다. 그런데 마지막 하루의 1.1%p 차이(표준편차보다도
  작은 노이즈)만으로 Remain_Coat 건강도가 57.9 대 83.1로 25점 갈렸고, 그 결과 드리프트
  17개인 DP02가 4개인 DP01보다 좋게 나왔습니다. **수정: `current_margin_pct` /
  `current_value` / `defect_zone_rate_pct`를 최근 `RECENT_DEFECT_WINDOW_DAYS`(7)일
  중앙값으로.** 수정 후 장비 순위가 드리프트 수·경보 지속일과 일치합니다
  (DP01 78.8 / DP03 53.6 / DP02 51.1 / DP04 0.4).
- **(26.08.08 발견 및 수정) 경보 지속 상태가 계속 리셋되던 문제.** `alert_since`를
  "최신 행이 속한 episode(같은 Product×Recipe 안에서 끊기지 않은 구간)의 시작"으로
  잡았는데, 경보는 Product×Recipe별로 판정되고 서로 다른 그룹의 샷이 시간축에서 뒤섞이므로
  한 그룹의 경보는 자연히 끊깁니다. 128개 (장비,컬럼) 조합 중 54개가 "1일 미만"으로
  표시됐는데 전부 실제로는 30일 넘게 경보 상태였습니다(DP03 Surface_Roughness는 224개
  episode로 쪼개져 "0.1일째"). **수정: (장비, 컬럼) 단위로 경보 간격이
  `TREND_WARNING_ACTIVE_WITHIN_DAYS` 이내면 같은 상태로 이어붙임.** "1일 미만" 54→28건.
- **(26.08.05 발견 및 수정) margin_used_pct가 "일별 평균 z"를 "개별 샷 기준 p0.5~p99.5"랑
  비교하던 버그가 있었습니다.** 하루 평균은 개별 샷보다 훨씬 덜 극단적으로 나오는데
  (여러 샷을 평균내면 노이즈가 상쇄됨), 경계선은 개별 샷 노이즈 분포로 그어놔서
  실제로는 거의 도달 못 하는 경계와 비교하고 있었습니다 — 그 결과 "스펙아웃 자체가
  안 생긴다"는 잘못된 인상을 줬습니다. **수정: provisional 컬럼의 boundary_z를
  `daily_mean_z` 자기 자신의 분포(p0.5~p99.5)로 다시 재계산**(`compute_daily_boundary_z`)
  — 재는 값과 경계가 같은 granularity를 쓰도록 통일했습니다. 단, 정의상 "일평균의
  상위/하위 0.5%"를 경계로 삼다 보니 89일치 데이터에서는 컬럼당 스펙아웃 사례가 1~2건
  정도로 적습니다 — `estimated_days_to_spec_out` 숫자 자체의 통계적 신뢰도는 낮고,
  "점진적으로 쌓이는 패턴이 있는지" 정성적으로 보는 용도로 쓸 것.
- **(26.08.05 발견 및 수정) direction="either" 컬럼의 margin이 분포가 한쪽으로 치우친
  경우 터무니없이 커지는 버그가 있었습니다.** `|z|`를 위/아래 중 더 좁은 쪽 경계
  하나로만 나눴는데, CLN_Flow처럼 거의 항상 baseline보다 낮고 위로는 거의 안 벗어나는
  컬럼은 "넓은 쪽(아래)"으로 벗어난 값이 "좁은 쪽(위)" 경계에 걸려 margin이 1443%까지
  나온 사례가 있었습니다. **수정: `compute_daily_boundary_z`가 위/아래 경계를 따로
  반환**하고, margin 계산 시 지금 값이 어느 쪽으로 벗어났는지 보고 그 방향의 경계를
  씁니다(멘토 스펙 컬럼이 이미 하던 방식과 통일). 수정 후 provisional 컬럼 margin
  분포: 평균 55.8→35.4, 표준편차 147.8→27.2, 최댓값 1443.7%→113.8%.
- **(26.08.05 발견 및 수정) `Groove_Depth`(Chipping 확정 원인)가 trend_analysis.py의
  A/B/C/E 어디에도 분류가 안 돼서, 방향성 조기경보(early_warning)가 전혀 안 나오고
  있었습니다**(변동성 확대 경보만 가능). `pipeline/config.py`의 `BASELINE_A_DIRECTION`에
  추가해서 고침 — 자세한 내용은 `pipeline/README.md` 참고.
- **추세(기울기)는 통계적 유의성을 새로 검정한 게 아닙니다.** "최근 14일 방향/속도"를
  서술하는 용도일 뿐입니다. (실측 검증: 이 데이터셋에서 가장 확실한 89일 전체 drift조차
  30일 트레일링 윈도우로는 유의하지 않았음 — `pipeline/README.md` 참고.)
- **안전망(2단) 임계값 50%는 관례적 컷오프**입니다 — 최적화된 값 아님.
- Chipping/Micro_Crack은 JHdaimma의 r1(신규) 데이터로 교차검증됐지만, 이 계산 자체는
  원본 데이터(`data/raw/`)로만 함 — **팀 결정(26.08.01)**: r1은 표본 부족 보완용
  학습/검증 데이터로만 쓰고 원본과 합치지 않음(의도된 설계).
- SOP 제안은 전부 `DRAFT_UNVERIFIED` — 멘토/현장 확인 전까지 참고용.
- **"defect(불량) 발생"과 "spec-out(변수가 스펙 경계를 넘는 것)"은 리드타임이 다른
  질문입니다** — 아래 두 항목은 서로 다른 이벤트를 잰 것이니 섞어서 읽지 말 것.

- **확정 원인변수(단변량)로 "defect 발생"까지의 조기경보는 사실상 어렵습니다.**
  `analyze_lead_time.py`로 defect 발생 전 원인변수가 며칠 전부터 위험 신호를 보였는지
  실측한 결과(26.08.05, raw 샷 단위), 대부분 전조 자체가 없거나(0~50%), 전조가 있어도
  평균 리드타임이 **0.0일** — 위험 상태가 defect 발생과 거의 동시에 나타나지 며칠 전부터
  서서히 쌓이지 않습니다. defect는 개별 샷 단위 사건이라 raw 샷 기준으로 재는 게 맞고,
  이 결과는 유효합니다 — 방법론/결과는 `05_lead_time_analysis.csv` 참고.
- **(26.08.05 후속검증) 다변량(JHdaimma XGBoost 모델, `26.08.01_Goal_AI_Agent_Prototype_김시우/
  train_defect_models.py`로 재현)도 defect 리드타임 0.0일로 동일합니다.** 그 순간 위험도를
  훨씬 정확히 잡아내긴 함(Chipping 전조 탐지율 75%, Micro_Crack 39% — 단변량은
  거의 0%였음) — 하지만 "며칠 전에 미리 아는" 건 방법론과 무관하게 안 됨. defect라는
  사건 자체는 "서서히 쌓이다 터지는" 게 아니라 "그 순간 조건이 맞으면 바로 터지는"
  방식으로 보임.
- **(26.08.05 재검증, 위 결론 일부 정정) "spec-out(변수가 스펙 경계를 넘는 순간)"까지의
  리드타임은 얘기가 다릅니다.** 처음엔 위 defect 결과와 똑같이 raw 샷 boundary_z를
  일평균에 그대로 적용해서 "spec-out 자체가 없다"고 오판했는데(위 한계 항목 참고),
  boundary_z를 daily_mean_z 자기 분포로 재계산해서 다시 재보니 — provisional 11개
  원인변수 중 **9개가 스펙아웃 며칠~몇 주 전부터 여유(margin)가 서서히 줄어드는
  패턴**을 보였습니다(예: Vibration 평균 25일 전, Power_Efficiency 48.5일 전 —
  CLN_Pressure/Cooling_Flow 2개만 즉시형). 단, 컬럼당 스펙아웃 사례가 89일 데이터에서
  1~2건뿐이라 표본이 매우 작습니다 — "점진적 패턴이 존재한다"는 정성적 결론까지만
  신뢰할 것, 리드타임 숫자를 확정치로 쓰지 말 것.
  **결론: "spec out 되기 전에 위험을 미리 알려준다"는 원래 목표는 여전히 유효합니다**
  (레벨 1단계 margin_used_pct/estimated_days_to_spec_out으로 이미 반영). "defect 발생을
  N일 전에 정확히 찍어서 예측"하는 건 안 되지만, 그건 이 시스템이 원래 약속한 것도
  아닙니다 — Health Index는 처음부터 "다른 장비 대비 몇 등"이 아니라 "스펙 경계까지
  남은 여유"를 보여주는 설계였고, 그 여유가 다변량 모델의 순간 탐지력(위 문단)과
  결합하면 "서서히 다가오는 위험 + 그 순간 정확한 원인 설명"을 함께 줄 수 있습니다.

## 산출물

| 파일 | 내용 |
|---|---|
| `01_level_trend_by_machine_column.csv` | 장비×전체 연속형변수별 레벨/추세/실제값 (원인/비원인 다 포함, trend_direction/early_warning_active/trend_message 포함) |
| `02_health_index_by_defect.csv` | 장비×defect별 Health Index + 최악 원인변수 |
| `03_health_index_by_machine.csv` | 장비별 최종 Health Index + 최악 defect |
| `04_defect_occurrence_recent7d.csv` | 장비×defect별 최근 7일 실제 발생 여부 |
| `05_lead_time_analysis.csv` | 원인변수×defect별 조기경보 리드타임 실측(`analyze_lead_time.py` 산출물) |
| `health_index_data.json` | **AI Agent가 읽는 통합 데이터** |

입력(이 폴더 밖, 저장소 루트 기준): `pipeline/`(Step0 baseline/일별 시계열),
`analysis_outputs/trend_analysis_results.csv`(`trend_analysis.py` 산출물, 추세판정).
