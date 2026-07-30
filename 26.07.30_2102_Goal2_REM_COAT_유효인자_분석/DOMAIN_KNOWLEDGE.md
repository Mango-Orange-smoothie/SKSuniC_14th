# Goal 2 (REM_COAT 유효인자) 도메인 지식 · 판단기준 · 논리 정리

`rem_coat_influence_factors.py`의 `DOMAIN_HYPOTHESIS` / `NOT_RELATED_TO_DEFECT` /
`TEAM_UNDETERMINED` 딕셔너리와 1:1로 대응한다. 방법론은 BURN/PARTICLE 분석과 동일 —
자세한 통계 기준/verdict 로직은
[BURN의 DOMAIN_KNOWLEDGE.md](../26.07.30_2001_Goal2_BURN_유효인자_분석/DOMAIN_KNOWLEDGE.md)
7~8절 참고.

## 1. 공정 배경

다이싱 전 웨이퍼 표면엔 보호용 코팅을 바른다. 다이싱 후 이 코팅을 세정 공정으로
씻어내는데, 다 씻기지 않고 남으면 **Remain_Coat** 불량이 된다. 이건 절단(레이저)
자체의 문제가 아니라 **후속 세정 공정의 문제**라는 게 이 분석의 핵심 전제다 —
그래서 Particle 분석과 달리 레이저/빔 서브시스템 대부분을 무관으로 분류했다.

## 2. 라벨 정의 논리

`is_remcoat_primary`(`NG_Code=='REM_COAT'`)와 `is_remcoat_broad`(`Remain_Coat==1`)가
**완전히 동일**하다(2,332건=2,332건, 다른 defect와 전혀 안 겹침). BURN/PARTICLE과 달리
"라벨 정의 차이" 문제 자체가 없는 깨끗한 단일원인 defect라, 도메인 가설이 맞다면
결과도 깔끔하게 나올 것으로 기대했다 — 실제로 그렇게 나왔다(4절).

## 3. 메커니즘별 도메인 가설 (`domain_status = defect_related`, 8개)

| 메커니즘 | 컬럼 | 방향 | 근거 |
|---|---|---|---|
| 세정 능력 | `CLN_Flow`, `CLN_Pressure`, `CLN_Time` | down | HealthIndex 설계서가 `CLN_Pressure`에 대해 "압력 부족 시 세정 불완전(Remain_Coat) 근거는 명확"이라고 명시 — 세 컬럼을 같은 계열로 묶음 |
| 코팅 도포 균일성 | `Coating_Flow` | either | 불균일 도포 시 일부 영역 과도포되어 제거 어려움 가능성 |
| 결과 공변 | `Surface_Roughness` | either | 코팅 잔류가 표면 거칠기를 바꿀 가능성, 원인 아닐 수 있음 |
| 헤드 노후 | `Laser_Head_Remain_Time` | down | 약한 가설 — 빔 품질 저하가 코팅 소작 효율에 간접 영향 가능성 |
| 팀 공용 피처 | `Cleaning_Capacity`(세정 능력 종합), `Cleaning_Load_Ratio`(수요/능력) | down / up | `Cleaning_Load_Ratio`의 분자(`Laser_Cleaning_Demand`)는 원래 Particle(디브리) 기준으로 설계된 개념이라 이 defect엔 다소 부정확할 수 있음을 명시하고 포함 |

## 4. 실제 통계 결과와의 대조

| 컬럼 | 가설 방향 | 관측 effect size(Primary) | 해석 |
|---|---|---|---|
| `CLN_Pressure` | down | **-0.543**, p≈0 | 가설과 정확히 일치, 두 방법 모두 강하게 합의 → `confirmed`. 이번 4개 defect 분석 중 가장 깔끔한 결과 |
| `Coating_Thickness`(도메인 지지 없음) | — | -0.279, p≈2.3e-116 | 통계는 강하지만 도메인 가설을 의도적으로 안 넣어서 `candidate_needs_domain_review`로 정확히 걸러짐 — 5절 데이터 누수 우려가 통계적으로도 시사됨(너무 깔끔하게 강한 신호는 동어반복 신호일 수 있음) |
| `Cleaning_Load_Ratio`, `Cleaning_Capacity`, `CLN_Flow` | up/down/down | 전부 방향 일치, effect size 0.15~0.19 | `candidate_weak_signal` — CLN_Pressure만큼 강하진 않지만 가설과 정합 |

## 5. Remain_Coat과 무관하다고 판단한 컬럼 (`not_related_to_defect`, 27개)

세 그룹:

- **정렬/센터링 계열**(9개, Particle과 동일 이유 — E유형/Chipping 메커니즘)
- **방열/체류시간 계열**(8개, Particle과 동일 이유 — Burn 전용 메커니즘)
- **절단(레이저) 서브시스템**(10개: `Laser_Power`, `Power_Efficiency`, `Focus`,
  `Beam_Diameter`, `Vibration`, `Groove_Depth`, `Kerf_Width_Profile`, `Top_Kerf`,
  `Bottom_Kerf`, `Laser_Cleaning_Demand`) — **이게 Particle 분석과 가장 다른 판단**.
  코팅 제거는 절단이 아니라 세정 공정의 일이라고 판단해서, Particle에서는
  `defect_related`였던 `Laser_Power`/`Groove_Depth`/`Laser_Cleaning_Demand` 등을
  여기선 무관으로 분류했다. `Laser_Power`가 통계적으로 약하게 유의(p=0.032)했지만
  effect size 0.034로 사실상 무신호라 이 판단을 반박하지 않는다(3절 표 참고).

## 6. 팀도 아직 결론 못 낸 컬럼, 특히 데이터 누수 우려 (`team_undetermined`, 4개)

`Laser_Current`, `Laser_Voltage`는 BURN/PARTICLE과 동일 이유(F유형).

`Coating_Thickness`, `Coating_Uniformity`는 **이 defect에서 유수 위험이 특히 크다**:
측정 시점이 세정 "후"라면 잔류 코팅량 자체와 사실상 같은 것을 두 번 재는 셈이라,
"원인"이 아니라 정의상 동어반복이 된다. 측정 시점을 확인하기 전까지 도메인 가설을
넣지 않기로 했고, 실제로 `Coating_Thickness`는 통계적으로 가장 강한 신호 중 하나로
나와서(4절) 이 우려가 근거 없는 게 아님을 데이터가 시사한다.

## 7. 통계적 판단기준 / verdict 로직

BURN/PARTICLE 분석과 완전히 동일. 자세한 내용은 BURN의 `DOMAIN_KNOWLEDGE.md` 참고.

## 8. 알려진 한계

- `Coating_Thickness`의 실제 측정 시점(가공 전/후)을 확인하기 전까지는
  `candidate_needs_domain_review` 상태를 유지해야 한다 — 확인되면 team_undetermined에서
  제외하거나, 반대로 "데이터 누수 확정"으로 명시적으로 배제해야 함.
- `Cleaning_Load_Ratio`의 분자(`Laser_Cleaning_Demand`)가 이 defect의 메커니즘과
  정확히 안 맞을 수 있다는 점은 3절에서 이미 명시함 — Remain_Coat 전용 비율 피처
  (예: `Coating_Flow / Cleaning_Capacity`)를 새로 만들어보는 것도 향후 검토 가치 있음.

## 출처

- `1주차/fdc_response_defect_parameter_discription.docx`
- `2주차/26.07.29_0242_HealthIndex_설계서_v2.docx`
- 데이터 자체 분석 결과 (`01_rem_coat_rate_by_stratum.csv`, `02_univariate_test_results.csv`,
  `03_tree_importance.csv`)
