# Goal 2 — Chipping / Micro_Crack 유효인자 발굴: 도메인 지식 정리 (초안)

> 목적: 데이터 분석(SHAP 등)에 들어가기 전에, 공정 도메인 관점에서 Chipping과
> Micro_Crack의 발생 메커니즘과 관련 컬럼 가설을 먼저 정리한다. Jun 브랜치의 기존
> CHIP/CRACK 분석(`DOMAIN_KNOWLEDGE.md`, Mann-Whitney + RandomForest 기반)을 1차
> 자료로 흡수하고, 본인의 SHAP 기반 Relationship Analyzer 작업의 출발점으로 삼는다.

## 0. 두 defect의 근거 수준 차이 (가장 먼저 짚어야 할 점)

| | Chipping | Micro_Crack |
|---|---|---|
| 팀 HealthIndex 설계서 근거 | **명시적** — 회의록/PDF에 메커니즘 서술 다수 | **거의 없음** — Crack 전용 서술이 문서화 안 됨 |
| 표본 수 | 4건 (0.004%) | 34~41건 (0.03~0.04%) |
| 가설의 성격 | 팀 문서 인용 위주 | 레이저가공 일반 물리(열충격/피로파괴) 기반 **작성자 추론** |
| 통계 검증(Jun, n 극소) | confirmed 2건 (Kerf_Width_Profile, Groove_Depth) | confirmed 2건 (Frequency, Surface_Roughness) |

→ Chipping은 "팀이 이미 아는 메커니즘을 통계로 재확인"하는 성격이 강하고, Crack은
"가설 자체를 데이터로 처음 검증"하는 성격이 강함. SHAP 분석 결과를 해석할 때 이
차이를 신뢰도 판단에 반영해야 함.

## 1. Chipping (모서리 파손) — 메커니즘

절단 경계에서 재질이 매끈하게 제거되지 못하고 깨져나가는 **기계적 파손** 현상.

| 메커니즘 | 관련 컬럼 | 방향 가설 | 근거 수준 |
|---|---|---|---|
| 가공 깊이 부족 | `Groove_Depth` | 부족할수록 Chipping↑ (down) | 명시적 (Low-k 미승화 → Blade 진입 시 파손) |
| 빔 폭/절단 폭 이상 | `Beam_Diameter`, `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf` | 협소→Width 감소, 과다→Die 영역 침범 (either) | 명시적 |
| 기계적 불안정(진동) | `Vibration` | 진동↑ → 나이프자국형 대형불량 (up) | 명시적 (회의록) |
| 빔 집속 이상 | `Focus` | 헤드온도 변화 → 굴절률 변화 → 센터링/Depth·Width 이상 (either) | 명시적 (PDF) |
| 방열(Focus의 상류 원인) | `Head_Temp` | up | 간접 근거 |
| 정렬/센터링 (이 defect에서만 포함) | `Cutting_X/Y_Index`, `Cutting_Offset`, `Laser_Centering_Position`, `Kerf_Angle`, `Package_Size_1~4` | either | 명시적 — 다른 defect(Burn 등)에서는 무관 처리되지만 Chipping엔 직결 |
| 헤드 노후(추론) | `Laser_Head_Remain_Time` | down | 추론 |

**무관 판단**: 에너지투입/체류시간/방열 계열(Laser_Power, Frequency, Feed_Speed 등, Burn 전용 메커니즘), 세정/코팅 계열(Particle/Remain_Coat 전용) — Jun 분석에서 무관 처리.

## 2. Micro_Crack (미세균열) — 메커니즘

재료의 파단강도를 넘는 스트레스가 가해질 때 발생. **열충격**과 **기계적 피로** 두 축이 핵심 후보.

| 메커니즘 | 관련 컬럼 | 방향 가설 | 근거 수준 |
|---|---|---|---|
| 열충격(에너지 투입) | `Laser_Power`, `Power_Efficiency` | up/either | 추론 |
| 열충격(방열 능력) | `Head_Temp`, `Cooling_Flow`, `Cooling_Water_Temp`, `Cooling_Thermal_Load` | up/down/up/up | 추론 |
| 열피로(펄스 반복) | `Frequency` | up | 추론이지만 **통계로 강하게 확인됨** (effect size 0.86, Burn 1위 변수와 동일 → Burn과 근본원인 공유 가능성) |
| 응력 집중(빔 품질) | `Focus`, `Beam_Diameter`, `Laser_Centering_Position` | either | 추론 |
| 기계적 스트레스 | `Vibration`, `Feed_Speed` | up/either | 추론 |
| 누적 노출 | `Process_Time`, `Alignment_Time` | up | 추론 |
| 구조적 응력 집중 | `Groove_Depth` | up (그루브 깊을수록 절단 팁 응력 집중) | 추론 |
| 결과 공변 | `Surface_Roughness` | up | **통계로 확인됨** (effect size 0.42) — 원인이 아니라 결과일 가능성도 있음 |
| 재검토 대상 | `Kerf_Width_Profile` | — | 원래 무관 판단했으나 effect size 0.25로 경계선 → 재검토 필요 |

**무관 판단**: 정렬/센터링 계열(위치 정확도 문제, 파단 스트레스와 무관), 세정/코팅 계열 — 단, `Kerf_Width_Profile`은 위 표처럼 재검토 여지 있음.

## 3. 두 defect의 겹치는 지점 (교차 확인 포인트)

- **Frequency**: Chipping 분석에서는 직접 언급 없지만, Crack과 **Burn** 모두에서 confirmed → 열 축적 메커니즘이 Crack/Burn에 공통 작용할 가능성. SHAP 분석 시 Chipping에도 유의미하게 나오는지 대조 필요.
- **Groove_Depth**: Chipping(confirmed, 부족 시 파손)과 Crack(추론, 과다 시 응력집중)에서 **방향이 반대로 가설됨** — 흥미로운 검증 포인트. SHAP으로 방향성까지 확인 가치 있음.
- **Vibration**: 두 defect 모두 "기계적 불안정 → 파손/균열" 메커니즘으로 겹침.
- **Kerf_Width_Profile**: Chipping엔 confirmed, Crack엔 재검토 대상 — 같은 변수가 다른 결함에 다르게 작용하는지 SHAP으로 비교.

## 4. 한계 및 다음 확인 사항

- 두 defect 모두 **표본이 극소수**(4건, 34~41건)라 통계적 결론의 신뢰도가 낮음. SHAP도 마찬가지로 소표본 불안정성에 취약하므로, 결과는 "확정 원인"이 아닌 "우선순위 후보"로 취급.
- Crack은 팀 설계서에 명시적 근거가 없으므로, **팀 멘토링/회의에서 Crack 실패모드를 확인하면 이 표를 전면 재검토**해야 함.
- 원본 설계 문서(`1주차/fdc_response_defect_parameter_discription.docx`, `2주차/HealthIndex_설계서_v2.docx`)는 저장소에 커밋되어 있지 않음 — 팀원(Jun 등)에게 직접 공유 요청 필요.

## 5. 팀 방향성 정렬 메모

- 방법론은 Jun의 통계 검증(Mann-Whitney+RF)과 **본인의 SHAP 분석을 상호 대조**하는 방식으로 진행 (완전 대체가 아님).
- 산출물은 전체 아키텍처의 `Target → Top Variables` Relationship DB 포맷에 맞춰 CHIP/CRACK 각각 정리.
- Jun의 `confirmed`/`candidate_needs_domain_review`/`not_related` 라벨 체계를 그대로 참고해, SHAP 상위 변수와의 일치/불일치를 명시적으로 표기할 것.
