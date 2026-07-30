# Goal 2 (CHIP 유효인자) 도메인 지식 · 판단기준 · 논리 정리

`chip_influence_factors.py`의 `DOMAIN_HYPOTHESIS` / `NOT_RELATED_TO_DEFECT` /
`TEAM_UNDETERMINED` 딕셔너리와 1:1로 대응한다. 방법론은 BURN/PARTICLE/REM_COAT/CRACK과
동일 — 자세한 통계 기준/verdict 로직은
[BURN의 DOMAIN_KNOWLEDGE.md](../26.07.30_2001_Goal2_BURN_유효인자_분석/DOMAIN_KNOWLEDGE.md)
7~8절 참고. 이 문서는 **표본이 4건뿐이라는 극단적 제약**을 계속 강조한다.

## 1. 공정 배경과 이번 defect의 특수성

Chipping(모서리 파손)은 절단 경계에서 재질이 매끈하게 제거되지 못하고 깨져나가는
현상이다. 이번 4개 defect(Burn/Particle/Remain_Coat/Crack) 중 **팀 HealthIndex
설계서에 가장 명시적인 근거가 많이 남아있는** defect다:

- `Groove_Depth`: "Depth 부족 시 Low-k가 완전히 승화되지 못해 Blade 진입 시 Chipping 발생" (명시적)
- `Beam_Diameter`: "협소해지면 Width 감소로 Chipping 증가, 과다해지면 Width 증가로 Die 영역 침범·손상" (명시적)
- `Vibration`: "장비 노후화로 스테이지 축 이동 시 설비가 흔들려 나이프 자국 형태로 잘려 나가는 대형 불량 원인" (회의록 명시)
- `Focus`: "헤드 온도가 변하면 광원 스팟의 온도와 레이저 굴절률이 변해 센터링 불량, Chipping, Depth/Width 이상 발생" (PDF 근거)

**단, 표본은 정확히 4건**(0.004%) — 이번 4개 분석 중 가장 희귀하다.

## 2. 라벨 정의 논리

`is_chip_primary`(`NG_Code=='CHIP'`)와 `is_chip_broad`(`Chipping==1`)가 **완전히
동일**하다(4건=4건, REM_COAT와 마찬가지로 다른 defect와 안 겹치는 깨끗한 단일원인).
다만 절대적인 건수가 너무 적어 이 "깨끗함" 자체도 우연일 가능성을 배제 못 한다.

## 3. 메커니즘별 도메인 가설 (`domain_status = defect_related`, 19개)

| 메커니즘 | 컬럼 | 방향 | 근거 |
|---|---|---|---|
| 가공 깊이 | `Groove_Depth` | down | HealthIndex 설계서 C유형 명시 — **통계로 확인됨(4절)** |
| 빔 품질/절단 폭 | `Beam_Diameter`, `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf` | either | HealthIndex 설계서 B유형 명시 — `Kerf_Width_Profile` **통계로 확인됨(4절)** |
| 기계적 불안정 | `Vibration` | up | HealthIndex 설계서 회의록 명시 |
| 빔 집속 | `Focus` | either | HealthIndex 설계서 PDF 근거 명시 |
| 방열(간접) | `Head_Temp` | up | Focus 메커니즘의 상류 원인으로 간접 연결(PDF 근거에서 헤드온도→굴절률→Focus 언급) |
| 정렬/센터링 | `Cutting_X_Index`, `Cutting_Y_Index`, `Cutting_Offset`, `Laser_Centering_Position`, `Kerf_Angle` | either | E유형 — **다른 3개 defect 분석에서는 "Chipping 메커니즘이라 무관"으로 제외했던 바로 그 컬럼들을 여기서는 포함** |
| 정렬 동반지표 | `Package_Size_1~4` | either | 센터링 불량의 동반지표 |
| 헤드 노후 | `Laser_Head_Remain_Time` | down | 제 추론 |
| 결과 공변 | `Surface_Roughness` | up | 모서리 파손 부위가 거칠기를 높일 가능성, 원인 아닐 수 있음 |
| 정비 이력 프록시 | `Maintenance_Count` | either | 김시우님 preprocessing decision_note가 Goal2 확인 가치 있다고 명시, 실제 신호 없음(effect size 0.16) |

## 4. 실제 통계 결과와의 대조 (n=4, 극도로 조심스럽게 읽을 것)

| 컬럼 | 가설 방향 | 관측 effect size(Primary) | 해석 |
|---|---|---|---|
| `Kerf_Width_Profile` | either | **0.9998** | 사실상 극단값 — 팀 문서 근거(Beam_Diameter 상속 메커니즘)와 방향은 맞지만, n=4에서 effect size가 ±1 근처로 튀는 건 자연스러운 현상이라 크기 자체에 과도한 의미를 부여하면 안 됨 |
| `Groove_Depth` | down | **-0.834** | 가설과 정확히 일치, 팀 문서의 명시적 근거와 부합 |
| `Laser_Cleaning_Demand`(도메인 지지 없음) | — | -0.984 | `Laser_Power×Groove_Depth` 파생 피처라 `Groove_Depth`의 신호가 그대로 묻어온 것으로 추정 — 독립적 발견이 아니라 상관에 의한 중복 신호 |

## 5. Chipping과 무관하다고 판단한 컬럼 (`not_related_to_defect`, 16개)

- **에너지투입/체류시간/방열 계열**(9개: `Laser_Power`, `Power_Efficiency`, `Feed_Speed`,
  `Frequency`, `Alignment_Time`, `Process_Time`, `Cooling_Flow`, `Cooling_Water_Temp`,
  `Cooling_Thermal_Load`) — Burn 전용 메커니즘(열 축적)이라 Chipping(기계적 파손)과는
  별개로 판단
- **세정/코팅 계열**(7개: `CLN_Flow`, `CLN_Pressure`, `CLN_Time`, `Coating_Flow`,
  `Cleaning_Capacity`, `Cleaning_Load_Ratio`, `Laser_Cleaning_Demand`) — Particle/
  Remain_Coat 전용 메커니즘

## 6. 팀도 아직 결론 못 낸 컬럼 (`team_undetermined`, 4개)

`Laser_Current`, `Laser_Voltage`, `Coating_Thickness`, `Coating_Uniformity` — 다른
defect 분석과 동일한 이유.

## 7. 통계적 판단기준 / verdict 로직

BURN/PARTICLE/REM_COAT/CRACK과 완전히 동일. 자세한 내용은 BURN의
`DOMAIN_KNOWLEDGE.md` 참고.

## 8. 알려진 한계 (이 defect에서 가장 심각함)

- **표본 4건**은 사실상 통계적 일반화가 불가능한 수준이다. Mann-Whitney U 검정,
  FDR 보정, RandomForest train/test 분할(test셋에 양성 1개) 전부 이론적으로는
  계산되지만, "패턴을 탐지했다"기보다 "4개 사례가 어떻게 생겼는지 기록했다"에
  가깝다고 보는 게 정확하다.
- 그럼에도 불구하고 confirmed 2건(`Kerf_Width_Profile`, `Groove_Depth`)이 팀
  HealthIndex 설계서의 명시적 Chipping 메커니즘과 정확히 일치한 건 우연 이상의
  의미가 있을 수 있다 — 다만 이건 "통계적 확정"이 아니라 "기존에 알려진 메커니즘이
  이 4개 사례에서도 재현됐다"는 정성적 확인 정도로만 취급해야 한다.
- CHIP 사례가 더 쌓이거나(다음 데이터 배치), 실제 라인 데이터를 확보하면 반드시
  재검증할 것.

## 출처

- `1주차/fdc_response_defect_parameter_discription.docx`
- `2주차/26.07.29_0242_HealthIndex_설계서_v2.docx` (Chipping 관련 명시적 서술이 가장 많음)
- 데이터 자체 분석 결과 (`01_chip_rate_by_stratum.csv`, `02_univariate_test_results.csv`,
  `03_tree_importance.csv`)
