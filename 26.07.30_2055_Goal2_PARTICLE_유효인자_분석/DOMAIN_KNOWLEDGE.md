# Goal 2 (PARTICLE 유효인자) 도메인 지식 · 판단기준 · 논리 정리

`particle_influence_factors.py`의 `DOMAIN_HYPOTHESIS` / `NOT_RELATED_TO_DEFECT` /
`TEAM_UNDETERMINED` 딕셔너리와 1:1로 대응한다. 구조는 BURN 분석의
[`../26.07.30_2001_Goal2_BURN_유효인자_분석/DOMAIN_KNOWLEDGE.md`](../26.07.30_2001_Goal2_BURN_유효인자_분석/DOMAIN_KNOWLEDGE.md)와
동일하지만, 내용은 Particle 물리 메커니즘에 맞춰 처음부터 다시 세웠다.

## 1. 공정 배경

레이저 다이싱은 재질을 어블레이션(레이저로 태워 제거)하는 공정이라, 제거된 재질은
반드시 어딘가로 가야 한다. 세정(cleaning) 공정이 이 디브리를 제대로 씻어내지 못하면
웨이퍼 표면에 남아 **Particle(이물)** 불량으로 기록된다. 즉 핵심 가설은
**"디브리 발생량 vs 세정 능력"의 밸런스 문제** — Burn의 "에너지투입 vs 방열"과 구조는
같지만 물리적 실체(물질 vs 열)는 다르다.

## 2. 라벨 정의 논리

- `is_particle_primary` = `NG_Code=='PARTICLE'` (6,455건, 6.455%)
- `is_particle_broad` = `Particle==1` (7,792건, 7.792%)

두 라벨의 차이 1,337건은 **전부** `NG_Code=='REM_COAT'`와 겹친다(BURN/CHIP/CRACK과는
전혀 안 겹침). 이물 오염과 코팅잔류가 "세정 부족"이라는 같은 근본원인을 공유할 가능성이
데이터에 이미 나타나 있다 — REM_COAT 분석과 결과를 대조해볼 가치가 있다.

## 3. 메커니즘별 도메인 가설 (`domain_status = defect_related`, 18개)

| 메커니즘 | 컬럼 | 방향 | 근거 |
|---|---|---|---|
| 에너지 투입(어블레이션량) | `Laser_Power` | up | 에너지↑ → 제거되는 재질량↑ → 디브리 소스 |
| 에너지 변환 이상 | `Power_Efficiency` | either | 효율 이상 → 비정상 어블레이션 가능성 |
| 빔 품질/집속 | `Focus`, `Beam_Diameter` | either | 빔 이상 시 비정상 어블레이션(스패터) 증가 가능성 |
| 세정 능력 | `CLN_Flow`, `CLN_Pressure`, `CLN_Time` | down | 세정 부족 → 디브리 잔류 (Burn에선 "이물이 열을 흡수"라는 2차 가설이었지만, 여기선 **1차 메커니즘**) |
| 코팅 이슈 | `Coating_Flow` | down | 코팅 불균일 → 박리가 particle 소스가 될 가능성(약한 가설) |
| 헤드 노후 | `Laser_Head_Remain_Time` | down | 빔 품질 저하 → 스패터 증가 가능성 |
| 기계적 진동 | `Vibration` | up | 진동 → 디브리 비산/재부착 — **통계로 강하게 확인됨(4절)** |
| 가공 제거량 | `Groove_Depth`, `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf` | up | 더 넓고 깊게 깎을수록 디브리 발생량 증가 |
| 결과 공변 | `Surface_Roughness` | up | particle이 표면에 남아 거칠기 직접 상승 — **원인 아니라 증상, 통계로 압도적 확인(4절)** |
| 팀 공용 피처 | `Laser_Cleaning_Demand`(디브리 발생 수요), `Cleaning_Capacity`(세정 능력), `Cleaning_Load_Ratio`(수요/능력 — 핵심 밸런스 가설) | up / down / up | `config.DOMAIN_FEATURES` 재사용 |
| 정비 이력 프록시 | `Maintenance_Count` | either | 김시우님 preprocessing decision_note가 Goal2 확인 가치 있다고 명시, 방향 상충 가능성 있어 미특정. 실제 신호 없음(effect size -0.01) |

## 4. 실제 통계 결과와의 대조

| 컬럼 | 가설 방향 | 관측 effect size(Primary) | 해석 |
|---|---|---|---|
| `Surface_Roughness` | up | **0.715**, p≈0 | 압도적으로 확인됨. 다만 "원인"이 아니라 "particle이 남아서 거칠어짐"이라는 **결과 공변**일 가능성이 훨씬 높음 — Health Index/SOP에 쓸 때 원인 인자와 반드시 구분 |
| `Vibration` | up | **0.220**, p≈1.5e-190 | 확인됨. 방향도 가설과 일치 — 이쪽이 실질적 원인 인자에 더 가까움 |
| `CLN_Flow`, `Cleaning_Capacity`, `Beam_Diameter` | down/either | 단변량은 무신호, 트리(Broad)에서만 상위권 | 세정 능력이 단독보다 다른 변수와 **조합**될 때 작동한다는 가설과 정합 |
| `Cleaning_Load_Ratio` | up(핵심 가설) | 무신호(`insufficient_evidence`) | 예상과 다름 — Cleaning_Capacity/CLN_Flow는 개별적으로 조합효과가 있는데 비율로 나누니 오히려 신호가 죽음. 비율 정의(분자/분모 스케일) 재검토 필요 |

## 5. Particle과 무관하다고 판단한 컬럼 (`not_related_to_defect`, 17개)

두 그룹으로 나뉜다:

- **정렬/센터링 계열**(`Laser_Centering_Position`, `Cutting_X_Index`, `Cutting_Y_Index`,
  `Cutting_Offset`, `Kerf_Angle`, `Package_Size_1~4`) — HealthIndex 설계서 E유형,
  알려진 실패모드는 Chipping이며 디브리 발생과 무관.
- **방열/체류시간 계열**(`Head_Temp`, `Cooling_Flow`, `Cooling_Water_Temp`,
  `Cooling_Thermal_Load`, `Frequency`, `Alignment_Time`, `Process_Time`, `Feed_Speed`) —
  BURN 분석에서 확립된 열 축적 메커니즘 전용. Particle은 물질(디브리) 문제이지 열
  문제가 아니므로 무관으로 분류.

## 6. 팀도 아직 결론 못 낸 컬럼 (`team_undetermined`, 4개)

`Laser_Current`, `Laser_Voltage`(F유형), `Coating_Thickness`, `Coating_Uniformity`(G유형)
— BURN 분석과 동일한 이유(데이터 자체의 속성 문제, 측정 시점 불확실)로 defect 종류와
무관하게 동일하게 유지했다. `Coating_Thickness`/`Coating_Uniformity`는 "코팅 박리가
particle 소스"라는 그럴듯한 가설을 세울 수도 있었지만, 측정 시점(가공 전/후) 자체가
불확실한 상태에서 가설을 얹는 건 억지라고 판단해 보류했다.

## 7. 통계적 판단기준 / verdict 로직

BURN 분석과 완전히 동일 (Mann-Whitney+BH-FDR+Cliff's delta≥0.2, RandomForest
permutation importance top-10, "서로 다른 방법론 2개 합의 + 도메인 가설"이 `confirmed`
조건). 자세한 로직은 BURN의 `DOMAIN_KNOWLEDGE.md` 7~8절 참고.

## 8. 알려진 한계

- U자형("either") 가설(`Focus`, `Beam_Diameter`, `Power_Efficiency`)에 대한
  Mann-Whitney의 한계는 BURN과 동일하게 적용됨(9절 참고 — 절대편차 기준 검정 추가 필요).
- `Surface_Roughness`처럼 강한 신호가 "원인"이 아니라 "결과"일 수 있다는 점은
  particle에서 특히 더 뚜렷하다 — Health Index 가중치에 넣을 때는 반드시 원인/결과를
  구분해서 다뤄야 함.
- `Cleaning_Load_Ratio`가 구성요소(CLN_Flow, Cleaning_Capacity)보다 신호가 약해진
  현상은 재검토가 필요한 미해결 이슈로 남겨둠.

## 출처

- `1주차/fdc_response_defect_parameter_discription.docx`
- `2주차/26.07.29_0242_HealthIndex_설계서_v2.docx`
- 데이터 자체 분석 결과 (`01_particle_rate_by_stratum.csv`, `02_univariate_test_results.csv`,
  `03_tree_importance.csv`)
