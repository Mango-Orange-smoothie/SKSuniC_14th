# Goal 2 — Particle / Remain_Coat / Chipping / Micro_Crack 통합 전체방법론

담당: Jun · 기준일: 2026-08-01 (재현성 반영 최종판)

> "모두 동일한 신뢰성"을 목표로 시작했는데, 실행 결과는 그 반대 — **defect마다,
> 인자마다 신뢰도가 다르다는 걸 데이터로 재확인**하는 방향으로 끝났다. 재현성 검증을
> tier 로직에 정식으로 반영해서, 신뢰도 차이가 판정표에 그대로 드러나게 만들었다.

## 무엇을 했나

팀 3명이 각자 다른 방법을 보강했던 것(박대호=시간선행성, 전성재=Machine통제 다변량+시간선행성,
JHdaimma=XGBoost+TreeSHAP+위험선)을 **7개 방법론 전부, 4개 defect 전부에 동일하게** 적용했다.

| 방법 | 내용 |
|---|---|
| A | Mann-Whitney U + BH-FDR + Cliff's delta (+ \|z\| 비선형) |
| B | RandomForest permutation importance |
| C | L1(Lasso) 로지스틱 + HistGradientBoosting (Machine 통제) — 전성재 원안 |
| D | XGBoost + TreeSHAP, 모델 A(FDC전용)/B(전체) 분리 — JHdaimma 원안 |
| E | DecisionTree stump 위험선 — JHdaimma 원안 |
| F | 시간 선행성(lag 5/20/50 스트립) — 박대호 원안, 전성재 확장 |
| **G** | **원본/r1 데이터셋 재현성** — 이번 작업 중 새로 필요하다고 밝혀져서 추가 |

데이터: 원본(100,000행) + r1(100,000행) 통합 200,000행. **모든 4개 defect에 pure
라벨(다른 3개 defect 동시발생 배제)을 적용** — 박대호님의 원본 단독 분석과 달리,
통합 데이터에서는 4개 defect가 서로 상당히 동시발생한다(예: Particle&Remain_Coat 5,793건).

## 방법 G — 왜 필요했나

4개 방법(A~D)만으로 나온 1차 결과에서 `Vibration`이 Particle/Chipping/Micro_Crack
3개 defect의 공통 원인처럼 보였다. 그런데 원본/r1을 나눠서 다시 보니:

| defect | 컬럼 | 원본 delta | r1 delta | 판정 |
|---|---|---|---|---|
| Chipping | Groove_Depth, Head_Temp, Kerf_Width_Profile, Laser_Power, Power_Efficiency, Vibration | 전부 \|delta\|≥0.2 | 전부 \|delta\|≥0.2, 동일방향 | ✅ reproduced |
| Chipping | Laser_Centering_Position | -0.024 | 0.515 | ⚠️ r1에서만 (not_reproduced) |
| **Particle** | **Vibration** | **0.219** | **-0.034** | 🔴 원본에서만, r1은 부호까지 반대 (not_reproduced) |
| **Remain_Coat** | **CLN_Pressure** | **-0.529** | **-0.136** | 🟡 방향은 같으나 r1에서 기준(0.2) 미달 (direction_only) |
| **Micro_Crack** | **Vibration** | **0.087** | **-0.092** | 🔴 양쪽 다 약하고 부호도 반대 (not_reproduced) |

**해석**: r1은 "DP02/DP03에 열화를 주입한 시나리오"로 알려져 있는데, 그 시나리오가
Chipping 메커니즘과는 잘 들어맞지만 Particle/Micro_Crack의 Vibration 메커니즘은
반영하지 않은 것으로 보인다. 박대호님/JHdaimma님이 틀렸다는 뜻이 아니라 — 각자
**원본 데이터만으로 낸 결론**이 r1까지 포함한 통합 데이터에서는 그대로 일반화되지
않는다는 뜻이다.

## Tier 체계 (재현성을 1차 게이트로 반영)

재현성을 통계적 방법 개수나 시간선행성보다 **먼저** 거른다 — 같은 배치 안에서의
시간선행성보다, 서로 다른 배치(원본 vs r1)에서도 안 흔들리는지가 더 근본적인
일반화 질문이라고 판단했다.

| tier | 조건 |
|---|---|
| **Tier1_실행준비완료** | 도메인지지 + 통계 2개↑ 방법 통과 + **원본·r1 양쪽 재현** + 시간선행신호 유지 |
| Tier2_통계확정_인과방향검증필요 | 위 조건 + 재현됨, 단 시간선행성만 판단보류 |
| Tier2b_통계강함_결과공변의심 | 위 조건 + 재현됨, 단 시간선행신호 소멸(결과공변 의심) |
| **Tier2c_방향일치_크기데이터셋의존** | 재현성이 direction_only(방향은 같으나 한쪽 데이터셋에서 기준 미달) |
| **Tier2d_데이터셋특정적_재현안됨** | 재현성이 not_reproduced(부호 반대 또는 한쪽만 신호) — **가장 주의 필요** |
| Tier3_약한신호 | 도메인지지 + 통계 1개 방법만 통과 |
| candidate_needs_domain_review | 통계는 강하나 도메인 지지 없음 |
| monitor_only / rejected / excluded_domain | 팀 도메인 판단(각자 후속검증 결론)을 그대로 반영 |

## 최종 판정 결과 (`07_{defect}_unified_verdict.csv`)

| defect | Tier1 | Tier2c(방향유지, 크기 데이터셋의존) | Tier2d(데이터셋특정적, 재현 안 됨) | monitor_only |
|---|---|---|---|---|
| Particle | — | — | **Vibration** | Surface_Roughness |
| Remain_Coat | — | **CLN_Pressure** | — | — |
| **Chipping** | **Laser_Power, Power_Efficiency, Head_Temp, Vibration, Kerf_Width_Profile** | — | Laser_Centering_Position | — |
| Micro_Crack | — | — | **Vibration** | Surface_Roughness |

**결론**: 이번 4개 defect 중 **Chipping만 진짜로 "실행준비완료" 등급**이다. 나머지는
전부 어떤 형태로든 "데이터셋에 따라 흔들린다"는 단서가 붙는다 — Remain_Coat는
그나마 방향은 유지되고(전성재님의 "즉시성 현상" 해석과 일치), Particle/Micro_Crack의
`Vibration`은 재현조차 안 된다.

## 교차 defect 공통 인자 (`08_cross_defect_vibration.csv`)

| 컬럼 | 재현된 원인(Tier1/2/2b) 개수 | 데이터셋특정적(Tier2d) 개수 |
|---|---|---|
| Vibration | 1 (Chipping만) | 2 (Particle, Micro_Crack) |

**"Vibration이 3개 불량의 공통 원인"이라는 최초 헤드라인은 데이터로 반박됐다.**
Vibration이 재현 가능한 원인으로 확인된 건 Chipping 하나뿐이다. Particle과
Micro_Crack에서 Vibration이 원인이라는 주장은 이번 기준으로는 데이터셋 의존적
신호라 실행(SOP 조치)의 근거로 쓰면 안 된다.

## 실행 방법

```bash
python "26.08.01_2128_Goal2_통합_전체방법론_4개defect/unified_full_methodology.py"
```

`reproducibility_check.py`는 방법 G가 본 스크립트에 흡수되면서 더 이상 필요 없다
(구버전 결과 `09_reproducibility_by_dataset.csv`는 이력 참고용으로 남겨둠, 각
defect별 `09_{defect}_reproducibility.csv`가 최신·전체 후보 컬럼 버전).

이 브랜치에는 `data/raw/`가 없다 — `DP_HealthIndex_Dataset.csv`/`_r1.csv`를 저장소
루트의 **상위 폴더**에 둬야 한다(용량 때문에 git 커밋 안 함).

## 산출물

| 파일 | 내용 |
|---|---|
| `00_summary.json` | 실행 메타데이터 (defect별 tier1/tier2/tier2d 목록 포함) |
| `01~06_{defect}_*.csv` | 방법 A~F 각각의 defect별 상세 결과 |
| `07_{defect}_unified_verdict.csv` | **7개 방법 통합 최종 판정표 (메인 산출물)** |
| `08_cross_defect_vibration.csv` | 교차 defect 공통 인자 (재현 여부 구분) |
| `09_{defect}_reproducibility.csv` | 방법 G 상세 (전 후보 컬럼 × 원본/r1) |
| `09_reproducibility_by_dataset.csv` | (구버전, Tier1~2b 후보만 대상 — 이력용) |

## 다음에 필요한 것

1. **박대호님/JHdaimma님께 공유하고 확인받을 것** — 각자의 `Vibration` 결론이 원본
   단독 분석이었다는 걸 이 결과가 뒷받침한다. r1을 어떻게 다룰지(제외/가중치 낮춤/
   전용 시나리오로 별도 취급) 논의 필요.
2. **r1이 "모든 defect에 균등 적용 가능한 시나리오"인지 멘토/현업 확인** — Chipping
   전용으로 설계된 것이라면, Particle/Remain_Coat/Micro_Crack은 원본 단독 결과를
   우선하는 게 맞을 수 있음.
3. Chipping의 `Laser_Centering_Position`도 재현 실패라 Tier1에서 빠졌다 —
   JHdaimma님의 SHAP 결과에는 포함돼 있었을 가능성이 있어 대조 확인 권장.
