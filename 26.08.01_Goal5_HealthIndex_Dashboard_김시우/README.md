# Goal5 — Health Index 계산 (v3, 김시우)

**대시보드는 없습니다.** 이 프로젝트 목표는 "데이터 분석해서 발표하는 것"이 아니라
"엔지니어를 대신해서 분석해주는 AI Agent"라서, 정적 HTML 대시보드는 만들지 않습니다.
이 폴더는 AI Agent(`26.08.01_Goal_AI_Agent_Prototype_김시우/`)가 읽는 데이터만 만듭니다.

## 실행

```bash
python 26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py
```

`health_index_data.json`이 생성되고, AI Agent(`agent.py`)가 이 파일을 바로 읽습니다.

## Health Index가 답하는 질문

**"다른 장비/변수 대비 몇 등인가"가 아니라 "스펙 아웃(임시 USL/LSL) 되기 전에 미리 알 수
있는가"입니다.** (v1은 근거 없는 가중치로 만든 단일 점수였고, v2는 정규분포/순위 기반
백분위로 만들었다가 "통계적으로 얼마나 특이한가"를 재는 거라 목적과 안 맞아서 폐기 —
자세한 시행착오는 커밋 로그 참고.)

## 계산 구조 (v3)

```
1) 스펙 경계까지 남은 여유 = 레벨
   boundary_z(컬럼별) = baseline(median)에서 임시 USL/LSL(정상군 p0.5~p99.5)까지의
     거리를 robust z-scale로 잰 것. OPCOND 층별로 계산 후 컬럼당 중앙값을 대표값으로.
   margin_used_pct = (지금 레벨 z ÷ boundary_z) × 100
     0% = baseline, 100% = 스펙 경계, 100% 넘으면 스펙아웃
   변수별 Health Index = 100 − clip(margin_used_pct, 0, 100)

2) 추세는 점수에 안 섞고 "예상 며칠 뒤 스펙아웃"으로 따로 제공
   margin_used_pct의 최근 14일 기울기(%/일) → 나빠지는 방향이면
   (100 − 지금 margin_used_pct) ÷ 기울기 = 예상 며칠 뒤 스펙아웃
   (이미 스펙아웃이거나 좋아지는 중이면 계산 안 함 — null)

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

## 데이터 출처 — 각자 확정한 유효인자를 그대로 가져옴

- Particle → `Vibration` (daeho, `26.07.31_2058_Goal2_PARTICLE_후속검증/` — 선행신호 검증까지 완료된 것)
- Remain_Coat → `CLN_Pressure` (전성재, `26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/` — Machine 통제 다변량 v2)
- Chipping → `Laser_Power`/`Power_Efficiency`/`Head_Temp`/`Laser_Centering_Position`/`Kerf_Width_Profile`/`Top_Kerf`/`Bottom_Kerf`/`Groove_Depth`
  (JHdaimma `26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/` 3방법 합의 + Jun confirmed 교차확인)
- Micro_Crack → `Vibration`/`Cooling_Flow` (JHdaimma, Chipping과 공유 원인)
- 전처리/추세검정/baseline/일별 집계 → `pipeline/`(김시우 Step0)

## 알려진 한계

- **boundary_z/USL/LSL은 컬럼당 대표값 하나(OPCOND 층별 중앙값)**입니다 — 장비/레시피마다
  실제 스펙 여유가 다를 수 있는 걸 다 못 담습니다.
- **margin_used_pct는 "일별 평균 z"를 "개별 샷 기준 p0.5~p99.5"랑 비교**하는 거라, 하루
  평균은 개별 샷보다 덜 극단적으로 나와서 실제보다 여유가 있어 보일 수 있습니다.
- **추세(기울기)는 통계적 유의성을 새로 검정한 게 아닙니다.** "최근 14일 방향/속도"를
  서술하는 용도일 뿐입니다. (실측 검증: 이 데이터셋에서 가장 확실한 89일 전체 drift조차
  30일 트레일링 윈도우로는 유의하지 않았음 — `pipeline/README.md` 참고.)
- **안전망(2단) 임계값 50%는 관례적 컷오프**입니다 — 최적화된 값 아님.
- Chipping/Micro_Crack은 JHdaimma의 r1(신규) 데이터로 교차검증됐지만, 이 계산 자체는
  원본 데이터(`data/raw/`)로만 함 — **팀 결정(26.08.01)**: r1은 표본 부족 보완용
  학습/검증 데이터로만 쓰고 원본과 합치지 않음(의도된 설계).
- SOP 제안은 전부 `DRAFT_UNVERIFIED` — 멘토/현장 확인 전까지 참고용.
- **확정 원인변수(단변량)로는 "조기" 경보가 사실상 어렵습니다.** `analyze_lead_time.py`로
  defect 발생 전 원인변수가 며칠 전부터 위험 신호를 보였는지 실측한 결과(26.08.05),
  대부분 전조 자체가 없거나(0~50%), 전조가 있어도 평균 리드타임이 **0.0일** — 위험
  상태가 defect 발생과 거의 동시에 나타나지 며칠 전부터 서서히 쌓이지 않습니다.
  단변량 확인 원인만으로는 예측할 시간적 여유가 이 데이터엔 거의 없다는 뜻 — 방법론/
  결과는 `05_lead_time_analysis.csv` 참고. JHdaimma의 다변량(SHAP/RandomForest) 모델
  같은 조합 신호를 봐야 진짜 조기경보가 가능할 가능성이 높음(다음 단계 후보).

## 산출물

| 파일 | 내용 |
|---|---|
| `01_level_trend_by_machine_column.csv` | 장비×전체 연속형변수별 레벨/추세/실제값 (원인/비원인 다 포함) |
| `02_health_index_by_defect.csv` | 장비×defect별 Health Index + 최악 원인변수 |
| `03_health_index_by_machine.csv` | 장비별 최종 Health Index + 최악 defect |
| `04_defect_occurrence_recent7d.csv` | 장비×defect별 최근 7일 실제 발생 여부 |
| `05_lead_time_analysis.csv` | 원인변수×defect별 조기경보 리드타임 실측(`analyze_lead_time.py` 산출물) |
| `health_index_data.json` | **AI Agent가 읽는 통합 데이터** |
