# Goal 2 — PARTICLE 유효인자 후속 검증

Jun 브랜치의 [`26.07.30_2055_Goal2_PARTICLE_유효인자_분석`](../26.07.30_2055_Goal2_PARTICLE_유효인자_분석/)이
1차 스크리닝을 마치고 `confirmed` 2건(Surface_Roughness, Vibration)을 냈다.
그 README가 스스로 "더 봐야 한다"고 남긴 질문들을 데이터로 검증한 결과다.
**같은 스크리닝을 다시 돌린 것이 아니다.**

통계 규약(Mann-Whitney U + BH-FDR, Cliff's delta 임계값 0.2)은 1차 분석과 동일하게 유지해
숫자를 직접 비교할 수 있게 했다.

## 실행 방법

```bash
python "26.07.31_2058_Goal2_PARTICLE_후속검증/particle_followup_validation.py"
```

이 브랜치에는 `data/raw/`가 없으므로 원본 CSV 경로를 직접 지정한다:

```bash
python "26.07.31_2058_Goal2_PARTICLE_후속검증/particle_followup_validation.py" --data "원본CSV경로"
```

## 결론 요약

| 검증 | 질문 | 결과 |
|---|---|---|
| 1 | Surface_Roughness는 원인인가 결과인가 | **결과 공변 확정** — 원인 후보에서 제외 |
| 2 | particle 심각도(Die 수)를 좌우하는 인자가 있나 | **없음** — 전 인자 무신호 |
| 3 | Cleaning_Load_Ratio 비율 정의가 문제였나 | **아니오** — 정의 4종 전부 무신호 |
| 4 | PARTICLE과 REM_COAT가 근본원인을 공유하나 | **아니오** — 세정계는 REM_COAT 전용 |
| 5 | 결론이 층(OPCOND/GROUP) 선택에 민감한가 | **아니오** — 강건 |

**순효과: Jun의 `confirmed` 2건 중 1건(Surface_Roughness)은 원인 인자에서 내려가고,
`candidate_weak_signal` 중 세정계 2건(CLN_Flow, Cleaning_Capacity)은 기각된다.
Particle의 원인 후보로 남는 것은 Vibration 하나뿐이다.**

---

## 검증 1 — Surface_Roughness는 원인이 아니라 결과다

Jun의 판단("결과 공변일 가능성이 매우 높다, 해석 주의")이 데이터로 확인됐다.

**방법**: 어떤 인자가 원인이라면 그 인자가 나빠진 상태가 particle 발생보다 시간적으로
앞서야 한다. 설비별로 시간순 정렬한 뒤, 현재 스트립을 반드시 제외한(`shift(1)`) 직전
5/20/50개 스트립의 이동평균이 현재 스트립의 particle을 예측하는지 봤다.

| 인자 | 동시점 Cliff's delta | 선행(50) Cliff's delta | 신호 잔존율 |
|---|---|---|---|
| Surface_Roughness | 0.715 | 0.053 | **3~7%** |
| Vibration | 0.220 | 0.072 | 22~33% |

Surface_Roughness는 같은 스트립에서 잴 때만 압도적으로 갈리고, 직전 이력에는 사실상
아무것도 남지 않는다. **particle이 표면에 남아 거칠기를 높인 결과**로 해석하는 것이 맞다.

대조군으로 넣은 Vibration은 잔존율이 3~10배 높다. 방법 자체가 모든 신호를 지우는 게
아니라는 확인이자, 두 인자의 성격이 실제로 다르다는 증거다.

> 한계: 이것은 인과 증명이 아니라 "결과 공변 해석을 반증할 수 있는가"를 보는 검사다.
> 두 변수가 공통 원인을 공유해 함께 서서히 움직이면 선행 신호도 함께 나타날 수 있다.

## 검증 2 — particle 심각도를 좌우하는 인자는 없다

particle이 난 스트립 안에서 `Particle_Die`(불량 다이 수)와 각 인자의 관계를 봤다.

초기 계산에서는 CLN_Pressure(rho −0.165, 구간 단조성 −0.885)와 Surface_Roughness
(rho −0.162)가 강한 용량-반응을 보였다. **그러나 이는 전부 REM_COAT 오염이었다.**

`Particle==1`(7,792건)에는 REM_COAT 동시발생 1,337건이 섞여 있다. 이를 제외하고
다시 계산하면:

| 인자 | 전체 표본 rho | REM_COAT 제외 후 rho | 판정 |
|---|---|---|---|
| CLN_Pressure | −0.165 | **+0.008** | 소멸 |
| Surface_Roughness | −0.162 | **+0.006** | 소멸 |
| Vibration | −0.019 | +0.025 | 원래 무신호 |

발생 여부는 갈라도 심각도까지 좌우하는 인자는 확인되지 않았다.
Vibration은 Die 수와 무관하게 항상 z≈0.33으로 일정하게 높다 — "발생 스위치" 성격이다.

## 검증 3 — 비율 정의를 바꿔도 신호는 살아나지 않는다

Jun의 가설: 분자·분모는 개별 신호가 있는데 비율은 약하니 계산 방식 문제일 수 있다.
비율 정의 4종을 같은 검정에 태워 비교했다.

| 정의 | Cliff's delta | 판정 |
|---|---|---|
| 층내 순위차 `pct_rank(수요) − pct_rank(능력)` | −0.0117 | 미달 |
| `Demand_z − Capacity_z` | −0.0113 | 미달 |
| `Demand / Capacity` (현재 팀 공용 정의) | −0.0038 | 미달 |
| `log(Demand) − log(Capacity)` | −0.0038 | 미달 |

가장 나은 정의조차 효과크기 0.012로 임계값(0.2)의 6%에 불과하다.
**계산 방식 문제가 아니다.** 검증 4가 이유를 설명한다 — 세정 밸런스 자체가
particle과 무관하기 때문이다. `Cleaning_Load_Ratio` 재설계에 시간을 쓸 필요는 없다.

## 검증 4 — 세정계 인자는 REM_COAT 전용이다 (공통 근본원인 아님)

particle만 / 코팅잔류만 / 둘 다 / 정상, 네 그룹의 세정계 z 프로파일을 비교했다.

| 인자 | particle 단독 | REM_COAT 단독 | 둘 다 | 판정 |
|---|---|---|---|---|
| CLN_Pressure | **−0.002** | −0.536 | −0.548 | REM_COAT 전용 |
| Cleaning_Capacity | −0.004 | −0.192 | −0.193 | 미달 |
| Cleaning_Load_Ratio | +0.001 | +0.194 | +0.195 | 미달 |
| CLN_Flow | −0.005 | −0.124 | −0.163 | 미달 |

세정계 인자 전부 **particle 단독 그룹에서는 완전히 무신호**(|delta| < 0.005)이고,
REM_COAT가 걸린 그룹에서만 커진다. 공통 근본원인이 아니라 REM_COAT 쪽 인자다.

이것이 **Jun의 1차 분석에서 CLN_Pressure가 broad 라벨(`Particle==1`)에서만
p=7.5e-39로 잡히고 primary 라벨(`NG_Code=='PARTICLE'`)에서는 p=0.339였던 이유**다.
broad 라벨에 섞인 REM_COAT 1,337건이 만든 신호였다.

→ Jun 표의 `CLN_Pressure`, `CLN_Flow`, `Cleaning_Capacity` `candidate_weak_signal`은
particle 후보에서 내리는 것이 맞다. Goal 3(상호작용)으로 넘길 이유도 없다.

## 검증 5 — 결론은 층 선택에 강건하다

팀 내에 층 정의가 두 가지다. Jun은 OPCOND를 썼고, 기존
`analysis_outputs/03_impact_factor_ranking.csv`와 `pipeline/README.md`의 GROUP 설명은
Machine을 통제변수로 두는 쪽이다. 층이 갈리면 조치 주체(공정 파라미터 조정 vs 설비 정비)가
달라지므로 확인이 필요했다.

| 인자 | OPCOND | GROUP | 축소율 |
|---|---|---|---|
| Surface_Roughness | 0.7155 | 0.7136 | 0.3% |
| Vibration | 0.2195 | 0.2144 | **2.3%** |

40개 인자 전체에서 판정이 뒤집힌 것은 **하나도 없다**.

특히 Vibration은 장비를 통제해도 효과가 2.3%밖에 줄지 않는다. "일부 설비가 원래 진동이
크고 particle도 많다"는 설비 간 차이가 아니라, **같은 설비 안에서도 진동이 높을 때
particle이 늘어난다**는 뜻이다. 공정 인자로서 조치 대상이 될 수 있다.

---

## Particle 유효인자 현재 상태

| 인자 | 상태 | 근거 |
|---|---|---|
| **Vibration** | **유일한 원인 후보** | 효과크기 0.220, 층 무관 강건(축소 2.3%), 선행신호 잔존율 22~33% |
| Surface_Roughness | 결과 공변 — 원인 아님 | 선행신호 잔존율 3~7% |
| CLN_Pressure / CLN_Flow / Cleaning_Capacity | 기각 | particle 단독 그룹에서 무신호, REM_COAT 오염 |
| Cleaning_Load_Ratio | 기각 | 정의 4종 전부 무신호 |

## 남은 과제

1. **Vibration의 선행성이 아직 확정되지 않았다.** 선행 효과크기가 0.047~0.072로
   판정 기준(0.2)에 못 미쳐 `판단 보류`로 남았다. 잔존율은 Surface_Roughness의 3~10배라
   성격은 분명히 다르지만, "원인"이라고 단정하려면 근거가 더 필요하다.
   다음 단계 제안: 스트립 단위가 아닌 시간 윈도(시/일) 단위 집계, 또는 진동 급증 이벤트
   전후의 particle 발생률 비교.
2. **Beam_Diameter는 이번 검증 범위에 없었다.** Jun이 남긴 `candidate_weak_signal` 3건 중
   세정계 2건은 기각됐지만 Beam_Diameter는 별도 확인이 필요하다.
3. **Surface_Roughness의 활용처는 남아 있다.** 원인은 아니지만 particle 발생과 거의 동시에
   움직이므로(효과크기 0.715), Goal 4(이상탐지)나 Goal 5(Health Index)에서 **탐지 지표**로는
   가치가 있다. 조치 인자가 아니라 관측 지표로 넘기는 것을 권한다.
4. **REM_COAT 담당자에게 공유 필요.** 검증 4의 CLN_Pressure 효과크기 −0.536은 particle이
   아니라 REM_COAT 쪽에서 매우 강한 신호다.

## 산출물

| 파일 | 내용 |
|---|---|
| `00_followup_summary.json` | 실행 메타데이터 + 검증별 결론 |
| `01_surface_roughness_temporal.csv` | 검증1: 동시점 vs 선행(lag) 판별력 |
| `02_dose_response_particle_die.csv` | 검증2: Die 수 용량-반응 + REM_COAT 오염 검사 |
| `03_cleaning_load_ratio_variants.csv` | 검증3: 비율 정의 4종 비교 |
| `04_particle_remcoat_cooccurrence.csv` | 검증4: 동시발생 그룹별 세정계 프로파일 |
| `05_stratum_sensitivity.csv` | 검증5: OPCOND vs GROUP 효과크기 비교 |

원본 데이터와 `pipeline/` 공용 파일은 수정하지 않았다.
