# Goal 2 (BURN 유효인자) 도메인 지식 · 판단기준 · 논리 정리

`burn_influence_factors.py`에서 쓴 도메인 가설과 통계 판단기준을 코드 밖에서도 검토할 수
있도록 한 곳에 모았다. 코드의 `DOMAIN_HYPOTHESIS` / `NOT_RELATED_TO_BURN` /
`TEAM_UNDETERMINED` 딕셔너리와 1:1로 대응한다 — 코드를 고치면 이 문서도 같이 고칠 것.

## 1. 공정 배경

레이저 다이싱(그루빙) 공정에서 **Edge Burn**은 절단부에 열 에너지가 과도하게 축적되어
발생하는 열손상이다. 물리적으로는 다음 두 축의 밸런스 문제로 본다.

- **에너지 투입**: 레이저가 단위 시간·단위 길이당 얼마나 많은 에너지를 쏟아붓는가
- **방열/체류시간**: 그 에너지를 얼마나 빨리 빼내는가, 혹은 한 지점에 얼마나 오래 머무는가

투입이 방열을 앞지르면 국소적으로 열이 쌓이고, 그게 Edge Burn으로 나타난다는 것이
이번 분석 전체를 관통하는 가설이다. 신규 공학 피처 `Thermal_Load_Ratio`가 이 가설을
직접 수식화한 것이다.

## 2. 라벨 정의 논리

- **`is_burn_primary`** = `NG_Code=='BURN'` (392건, 0.39%) — 주 라벨
- **`is_burn_broad`** = `Edge_Burn==1` (441건) — 보조 라벨

둘이 완전히 겹치지 않는다: `Edge_Burn=1`인 441건 중 49건은 `NG_Code`가 BURN이 아니라
PARTICLE(38)/REM_COAT(7)/CRACK(4)로 기록되어 있다. 즉 "burn 현상 자체 발생"과 "burn이
주 불량코드로 채택된 것"은 다른 개념이다. 이 차이를 놓치지 않으려고 두 라벨을 병행 검정한다.

## 3. 왜 행 단위로 분석했는가 (OPCOND는 정규화 기준일 뿐)

BURN 발생률이 Machine_ID(0.33~0.47%)·Product_ID·Recipe_ID 전반에서 균일함을 먼저
확인했다 → 특정 장비/제품의 결함이 아니라 **연속 공정변수의 산발적 이상**이 원인이라는
전제를 세웠고, 이는 100,000행 전체를 개별 이벤트로 유지해야 검정력이 나오는 이유이기도
하다. `Product_ID×Recipe_ID`(OPCOND)는 그룹을 집계하는 데 쓴 게 아니라, 각 행의 원값을
"자기 그룹의 median/MAD 기준으로 얼마나 벗어났는가"로 정규화(z-score)하는 데만 썼다 —
그래야 "제품이 달라서 나는 차이"가 "burn 원인"으로 오인되지 않는다.

(참고: OPCOND 조합 54개별 BURN률이 0.10~0.85%로 최대 8배 차이나는 것도 확인했으나,
조합당 표본이 2~16건뿐이라 이번 분석에는 포함하지 않았다 — README의 "추후 개인 검토
예정" 항목.)

## 4. 메커니즘별 도메인 가설 (`domain_status = burn_related`, 25개)

| 메커니즘 | 컬럼 | 방향 가설 | 근거 |
|---|---|---|---|
| 에너지 투입 | `Laser_Power` | up | 물리적으로 자명(투입 에너지↑) |
| 에너지 투입(펄스 중첩) | `Frequency` | up | 펄스 주파수↑ → 인접 펄스 간 열 중첩 증가(레이저 가공 일반 원리) |
| 에너지 투입 | `Power_Efficiency` | either | 효율 이상(과다/과소 모두)이 실제 조사(照射) 에너지를 예측 밖으로 바꿀 수 있음 |
| 체류시간(열 축적) | `Feed_Speed` | down | 이동속도↓ → 단위 길이당 조사 시간↑ (레이저 가공 일반 원리) |
| 체류시간(열 축적) | `Process_Time`, `Alignment_Time` | up | 공정/정렬 시간↑ → 열 노출 시간↑ |
| 방열 능력 | `Cooling_Flow` | down | 냉각수 유량↓ → 방열 저하 |
| 방열 능력 | `Cooling_Water_Temp`, `Head_Temp` | up | 냉각수/헤드 온도↑ → 방열 여력 저하 |
| 빔 품질/집속 | `Focus`, `Beam_Diameter`, `Laser_Centering_Position` | either | 초점/빔 이탈 시 에너지 밀도 분포가 비정상화(과다 집중 또는 과다 분산 모두 가능) |
| 기계적 불안정 | `Vibration` | up | 진동↑ → 절단 경로 불안정 → 국소 hot spot |
| 이물/잔사(레이저 흡수) | `CLN_Flow`, `CLN_Pressure`, `CLN_Time` | down | 세정 부족 → 절단부 잔사 축적 → 잔사가 레이저 흡수해 국소 과열 |
| 이물/잔사(레이저 흡수) | `Coating_Flow` | down | 코팅 불균일 시 국소 흡수 편차 가능성(약한 가설) |
| 헤드 노후 | `Laser_Head_Remain_Time` | down | 헤드 수명 소진 → 빔 품질 저하 → burn 위험 증가 가능성 |
| 결과 공변(동반증상 후보) | `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf`, `Kerf_Angle`, `Groove_Depth`, `Surface_Roughness` | either/up | burn과 같은 근본원인(과열)의 부산물일 수 있음 — **원인이 아니라 증상일 가능성**을 항상 함께 표기 |
| 에너지투입/방열 비율(신규) | `Thermal_Load_Ratio` | up | `Laser_Power × Frequency / Cooling_Flow` — 1절의 밸런스 가설을 직접 수식화 |

### 4-1. 팀 HealthIndex 설계서와 방향 가설이 다른 경우 — 왜 다른가

팀의 `HealthIndex_설계서_v2`는 **모든 불량 유형을 아우르는 범용 분류**(A~G유형)이고,
여기 표는 **BURN 하나에 한정된 방향 가설**이라 목적이 다르다. 아래는 실제로 다르게
분류한 케이스와 실제 통계 결과 대조:

| 컬럼 | 팀 설계서 분류 | 이 분석의 가설 | 실제 관측 결과 |
|---|---|---|---|
| `Frequency` | F유형(불확실형) — "레이저 쏘는 속도 조절이라는 설명뿐, 적정구간 근거 없음" | 에너지 투입(up) — 펄스 중첩 원리로 burn에 한정해 방향 특정 | **effect size 0.98, p≈4.5e-245로 confirmed** — burn 한정 가설이 팀 설계서가 못 잡은 부분을 메운 사례 |
| `Feed_Speed` | F유형(불확실형) | 체류시간(down) | 관측 방향은 오히려 +0.033(반대 부호)이지만 effect size가 사실상 0 — 데이터가 가설을 반박한 게 아니라 애초에 신호가 없다는 뜻(`insufficient_evidence`) |
| `Laser_Power` | B유형(U자형) — "파워 너무 높아도 낮아도 문제" | up(burn 한정 단순화) | effect size 0.006로 거의 무신호. U자형이면 방향을 하나로 고정한 단변량 검정 자체가 안 맞을 수 있음(6절 한계 참고) |

## 5. Burn과 무관하다고 판단한 컬럼 (`domain_status = not_related_to_burn`, 7개)

근거: `HealthIndex_설계서_v2`의 **E유형(대칭성/정렬형)** 분류. 알려진 실패모드가
정렬/센터링 불량 → **Chipping** 계열이지, Burn의 메커니즘인 열 축적과는 물리적
연결고리가 없다고 판단했다.

| 컬럼 | 설계서 근거 |
|---|---|
| `Cutting_X_Index`, `Cutting_Y_Index` | "X/Y Cutting Offset — 목표 절단선 대비 편차" |
| `Cutting_Offset` | "목표 절단선 대비 오차" |
| `Package_Size_1~4` | "센터링이 틀어지면 좌우 다이 패키지 사이즈 균형이 깨짐" |

통계 결과도 이 판단을 뒷받침한다 — 7개 전부 effect size 0.02 이하로 사실상 무신호.

## 6. 팀도 아직 결론 못 낸 컬럼 (`domain_status = team_undetermined`, 4개)

근거: `HealthIndex_설계서_v2`가 자체적으로 F유형(불확실형)/G유형(미해결형)으로
분류해둔 것 — 멘토링 자료로도 실패모드를 특정 못 한 항목이라, 이 분석에서 억지로
burn 가설을 붙이지 않았다.

| 컬럼 | 설계서 근거 |
|---|---|
| `Laser_Current`, `Laser_Voltage` | F유형 — "전기적 제어수치라는 설명뿐, 실패모드 근거 없음" |
| `Coating_Thickness`, `Coating_Uniformity` | G유형 — "가공 전/후 어느 시점 값인지 데이터상 확인 안 됨(Remain_Coat과 지표 중복·데이터 누수 위험 있음)" |

## 7. 통계적 판단기준

| 항목 | 값/방법 | 이유 |
|---|---|---|
| 정규화 | OPCOND(Product×Recipe) 층화 median/MAD z-score | Product/Recipe 간 목표값 차이를 제거하고 순수 이상치만 비교 |
| 단변량 검정 | Mann-Whitney U (burn군 vs 나머지) | 정규분포 가정 불필요, 이상치에 강건 |
| 다중비교 보정 | Benjamini-Hochberg FDR, α=0.05 | 후보 컬럼 36개를 개별 검정하면 우연한 유의 결과가 다수 섞임 |
| 효과크기 | Cliff's delta, \|δ\|≥0.2만 인정 | 표본 10만 개라 사소한 차이도 p<0.05로 나오는 문제를 방지 |
| 다변량 | RandomForest(class_weight=balanced) + permutation importance(scoring=average_precision) | 희귀 이벤트(0.39%)에서 정확도는 무의미, 단일변수로 안 잡히는 조합효과 포착 |
| 트리 지지 기준 | permutation importance 상위 10위 이내 & 양수 | 상위권만 "지지"로 인정 |

## 8. "유효인자" 확정 로직 (verdict)

```
n_methods_agree = (단변량검정이 Primary 또는 Broad 라벨 중 하나라도 유의+효과크기 통과) 
                + (트리중요도가 Primary 또는 Broad 라벨 중 하나라도 상위권)
                # 최대 2 — "서로 다른 방법론 2개"만 센다.
                # 같은 방법이 두 라벨 모두에서 뜨는 건 "라벨 일관성"이라는 별개 신호로만
                # n_labels_univariate_flag / n_labels_tree_flag 컬럼에 남기고 여기엔 안 더한다.

confirmed                     : n_methods_agree>=2 AND 도메인 가설 있음(burn_related)
candidate_needs_domain_review : n_methods_agree>=2 AND 도메인 가설 없음  ← 통계는 강한데 물리적 설명을 못 찾은 경우, 재검토 대상
candidate_weak_signal         : n_methods_agree==1 AND 도메인 가설 있음
insufficient_evidence         : 그 외
```

## 9. 알려진 한계 (다음 라운드에서 보완할 것)

- **U자형("either") 가설과 Mann-Whitney의 한계**: `Focus`, `Beam_Diameter`,
  `Laser_Centering_Position`, `Power_Efficiency`, `Laser_Power` 등은 "너무 높아도 낮아도
  나쁘다"는 U자형 가설인데, 지금 쓴 Mann-Whitney U는 **부호 있는 z-score의 순위 이동**을
  보는 검정이라 양방향 이탈이 서로 상쇄되어 실제 신호가 있어도 안 잡힐 수 있다. 다음
  라운드에서는 `|z|`(절대편차) 기준 검정을 U자형 가설 컬럼에 추가로 돌려봐야 한다.
- OPCOND 조합(54개)별 BURN률 최대 8배 차이는 이번 라운드에서 검정하지 않고 기록만 해둠
  (README "추후 개인 검토 예정" 참고).
- `pipeline/README.md`가 요구하는 `03_impact_factor_ranking.csv`,
  `02b_process_parameter_correlation_pairs.csv`가 저장소에 없어 팀 기존 산출물과의
  교차검증은 아직 못 했음.

## 출처

- `1주차/fdc_response_defect_parameter_discription.docx` — 컬럼별 정의
- `2주차/26.07.29_0242_HealthIndex_설계서_v2.docx` — A~G 유형 분류, 회의록/멘토링 근거
- 데이터 자체 분석 결과 (`01_burn_rate_by_stratum.csv`, `02_univariate_test_results.csv`,
  `03_tree_importance.csv`)
