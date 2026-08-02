# Goal5 — 원인변수 레벨/추세 계산 (v2, 김시우)

**v2에서 대시보드를 없앴습니다.** 이 프로젝트 목표는 "데이터 분석해서 발표하는 것"이 아니라
"엔지니어를 대신해서 분석해주는 AI Agent"라서, 정적 HTML 대시보드(`dashboard.html`,
`build_dashboard_html.py`)는 삭제했습니다. 이 폴더는 이제 AI Agent(`26.08.01_Goal_AI_Agent_Prototype_김시우/`)가
읽는 데이터만 만듭니다.

## 실행

```bash
python 26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py
```

`health_index_data.json`이 생성되고, AI Agent(`agent.py`)가 이 파일을 바로 읽습니다.

## v1 → v2, 뭐가 왜 바뀌었나

v1은 "Health Index"라는 단일 점수(불량페널티+안정성페널티+추세페널티를 가중치 3/8/5로
합산)를 만들어서 대시보드에 그렸습니다. 근본적으로 두 가지 문제가 있었습니다:

1. **가중치(3, 8, 5)에 근거가 없었습니다** — 그냥 "일단 돌아가는" 값이었습니다.
2. **목적과 안 맞았습니다** — 하나의 점수로 뭉개면 "왜 급한지"를 설명할 수 없습니다.
   이 프로젝트가 만들려는 건 리포트가 아니라, 엔지니어에게 "뭘 봐야 하는지" 알려주는
   AI Agent입니다.

그래서 v2는 점수를 하나로 합치지 않습니다. defect별 원인변수마다 **레벨**(지금 baseline
대비 얼마나 벗어났는지)과 **추세**(최근 며칠간 방향/속도)를 따로따로 계산해서 그대로
내보내고, "레벨이 높고 추세도 나쁘니 급하다" 같은 종합 판단은 AI Agent(LLM)가 질문에
답할 때 직접 하게 맡깁니다 — 가중치를 하드코딩하는 대신, 판단 자체를 에이전트한테
넘긴 것입니다.

## 데이터 출처 — 각자 확정한 유효인자를 그대로 가져옴

- Particle → `Vibration` (daeho, `26.07.31_2058_Goal2_PARTICLE_후속검증/` — 선행신호 검증까지 완료된 것)
- Remain_Coat → `CLN_Pressure` (전성재, `26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/` — Machine 통제 다변량 v2)
- Chipping → `Laser_Power`/`Power_Efficiency`/`Head_Temp`/`Laser_Centering_Position`/`Kerf_Width_Profile`/`Top_Kerf`/`Bottom_Kerf`/`Groove_Depth`
  (JHdaimma `26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/` 3방법 합의 + Jun confirmed 교차확인)
- Micro_Crack → `Vibration`/`Cooling_Flow` (JHdaimma, Chipping과 공유 원인)
- 전처리/추세검정/baseline/일별 집계 → `pipeline/`(김시우 Step0)

## 계산 구조 (v2)

```
1) defect별 확정 원인변수(CAUSE_FACTORS, 11개)의 레벨/추세
   레벨 = 00_machine_daily_series.csv의 가장 최근 날짜 daily_mean_z (방향 보정)
   추세 = 최근 14일 daily_mean_z의 선형회귀 기울기 (방향 보정, z/일 단위)
   -> defect_signals에 담김, SOP까지 연결

2) 확정 원인이 아닌 나머지 변수(~30개)도 같은 방식으로 레벨/추세 계산 (안전망)
   -> |레벨| ≥ 2.0인 것만 unconfirmed_anomalies에 담김, SOP 없음, "검증 안 됨" 명시

3) 실제 불량 발생 여부(최근 7일 defect rate > 0)는 레벨/추세와 완전히 분리된 필드
   -> "이미 터진 것"과 "터지기 전 조짐"을 안 섞기 위함
```

## 알려진 한계

- **추세(기울기)는 통계적 유의성을 새로 검정한 게 아닙니다.** "최근 14일 방향/속도"를
  서술하는 용도일 뿐, "이게 통계적으로 확실한 추세다"라고 주장하지 않습니다. (실측
  검증: 이 데이터셋에서 가장 확실한 89일 전체 drift조차 30일 트레일링 윈도우로는
  유의하지 않았음 — `pipeline/README.md` 참고. 14일 기울기는 그보다 더 짧은
  "최근 동향" 참고치로만 쓸 것.)
- **안전망(2단) 임계값 |z|≥2.0은 관례적 컷오프**입니다 — 최적화된 값 아님.
- Chipping/Micro_Crack은 JHdaimma의 r1(신규) 데이터로 교차검증됐지만, 이 계산 자체는
  원본 데이터(`data/raw/`)로만 함 — **팀 결정(26.08.01)**: r1은 표본 부족 보완용
  학습/검증 데이터로만 쓰고 원본과 합치지 않음(의도된 설계).
- SOP 제안은 전부 `DRAFT_UNVERIFIED` — 멘토/현장 확인 전까지 참고용.

## 산출물

| 파일 | 내용 |
|---|---|
| `01_level_trend_by_machine_column.csv` | 장비×전체 연속형변수별 레벨/추세 (원인/비원인 다 포함) |
| `02_defect_occurrence_recent7d.csv` | 장비×defect별 최근 7일 실제 발생 여부 |
| `health_index_data.json` | **AI Agent가 읽는 통합 데이터** |
