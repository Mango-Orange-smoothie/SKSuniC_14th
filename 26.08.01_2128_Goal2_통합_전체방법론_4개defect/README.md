# Goal 2 — Particle / Remain_Coat / Chipping / Micro_Crack 통합 전체방법론

담당: Jun · 기준일: 2026-08-01

> ⚠️ **이 문서는 "모두 동일한 신뢰성"을 목표로 시작했지만, 실행 결과 그 반대 — 즉
> **defect마다 신뢰도가 다르다는 것을 데이터로 재확인**하는 결과가 나왔습니다.
> 특히 박대호님(Particle→Vibration)과 JHdaimma님(Micro_Crack→Vibration)의 핵심
> 결론이 원본/r1 데이터셋 간 재현이 안 됩니다. 아래 "가장 중요한 발견"을 먼저 읽어주세요.

## 무엇을 했나

팀 3명이 각자 다른 방법을 보강했던 것(박대호=시간선행성, 전성재=Machine통제 다변량+시간선행성,
JHdaimma=XGBoost+TreeSHAP+위험선)을 **6개 방법론 전부, 4개 defect 전부에 동일하게** 적용했다.

| 방법 | 내용 |
|---|---|
| A | Mann-Whitney U + BH-FDR + Cliff's delta (+ \|z\| 비선형) |
| B | RandomForest permutation importance |
| C | L1(Lasso) 로지스틱 + HistGradientBoosting (Machine 통제) — 전성재 원안 |
| D | XGBoost + TreeSHAP, 모델 A(FDC전용)/B(전체) 분리 — JHdaimma 원안 |
| E | DecisionTree stump 위험선 — JHdaimma 원안 |
| F | 시간 선행성(lag 5/20/50 스트립) — 박대호 원안, 전성재 확장 |

데이터: 원본(100,000행) + r1(100,000행) 통합 200,000행. **모든 4개 defect에 pure
라벨(다른 3개 defect 동시발생 배제)을 적용** — 통합 후 재확인한 결과 박대호님의
원본 단독 분석과 달리 4개 defect가 서로 상당히 동시발생하기 때문(예:
Particle&Remain_Coat 5,793건).

## 가장 중요한 발견 — 원본/r1 재현성 (`09_reproducibility_by_dataset.csv`)

통합 데이터의 효과크기가 낮게 나온 인자들이 있어서, 원본과 r1을 나눠 따로
Cliff's delta를 계산해봤다. 결과:

| defect | 컬럼 | 원본 delta | r1 delta | 판정 |
|---|---|---|---|---|
| **Chipping** | Groove_Depth | -0.797 | -0.652 | ✅ 양쪽 재현 |
| **Chipping** | Head_Temp | 0.214 | 0.753 | ✅ 양쪽 재현 |
| **Chipping** | Kerf_Width_Profile | 1.000 | 0.813 | ✅ 양쪽 재현 |
| **Chipping** | Laser_Power | -0.978 | -0.765 | ✅ 양쪽 재현 |
| **Chipping** | Power_Efficiency | -0.347 | -0.779 | ✅ 양쪽 재현 |
| **Chipping** | Vibration | 0.337 | 0.709 | ✅ 양쪽 재현 |
| Chipping | Laser_Centering_Position | -0.024 | 0.515 | ⚠️ r1에서만 |
| **Particle** | **Vibration** | **0.219** | **-0.034** | 🔴 **원본에서만 — r1은 사실상 무신호(부호도 반대)** |
| **Remain_Coat** | **CLN_Pressure** | **-0.529** | **-0.136** | 🟡 방향은 같으나 r1에서 기준(0.2) 미달 |
| **Micro_Crack** | **Vibration** | **0.087** | **-0.092** | 🔴 **양쪽 다 약하고 부호도 반대** |

### 해석

- **Chipping은 압도적으로 견고하다.** 6개 인자 전부 원본·r1 양쪽에서 같은 방향, 기준 이상
  효과크기로 재현됐다 — r1이 애초에 "DP02/DP03에 열화를 주입한 시나리오"로 알려져 있는데,
  그 시나리오가 Chipping 메커니즘과 잘 들어맞는 것으로 보인다.
- **박대호님의 `Vibration`(Particle) 핵심 결론은 원본 데이터에서만 성립한다.** 원본에서는
  0.219로 박대호님 결과(0.220)와 거의 정확히 일치하지만, r1에서는 -0.034로 사실상
  무신호다. **r1의 Particle 생성 시나리오가 Vibration 메커니즘을 반영하지 않았을
  가능성**이 높다 — 박대호님이 틀렸다는 뜻이 아니라, r1이 모든 defect에 똑같이
  적용 가능한 시나리오가 아닐 수 있다는 뜻이다.
- **JHdaimma님의 `Vibration`(Micro_Crack) 결론은 재검토가 필요하다.** 원본 0.087,
  r1 -0.092로 둘 다 약하고 부호까지 반대다. JHdaimma님 README의 SHAP 결과(원인모델
  1위, 0.255)는 원본+r1 **통합** 데이터로 학습한 것이라 이 약한 신호를 못 볼 수 있다 —
  다중공선성 방어(모델 분리)는 있지만 데이터셋 간 재현성 검증은 없었던 부분.

**결론**: "6개 방법론을 다 적용했다"가 "신뢰도가 같아졌다"를 보장하지 않는다.
오히려 **재현성 검증 자체가 7번째 방법론으로 꼭 필요하다는 게 이번 작업으로 증명됐다.**

## 통합 판정 결과 (`07_{defect}_unified_verdict.csv`)

Tier는 `n_methods_agree`(A~E 중 몇 개 통과, 최대4) + 도메인 지지 + 방법F(시간선행성)를
결합해 정했다. **위 재현성 표는 아직 tier 계산에 반영되지 않았다** — 반영 여부를
사용자와 상의해야 해서 일단 별도 파일로만 남겨뒀다.

| defect | Tier1(실행준비완료) | Tier2(통계확정, 인과방향 검증필요) | Tier2b(통계강함, 결과공변의심) | monitor_only |
|---|---|---|---|---|
| Particle | — | **Vibration** (⚠️ 재현성표 참고) | — | Surface_Roughness |
| Remain_Coat | — | — | **CLN_Pressure** (⚠️ 방향은 재현, 크기는 r1에서 약화) | — |
| Chipping | **Laser_Power, Power_Efficiency, Head_Temp, Laser_Centering_Position, Vibration, Kerf_Width_Profile** | — | — | — |
| Micro_Crack | — | **Vibration** (⚠️ 재현성표 참고) | — | Surface_Roughness |

`Chipping`은 왜 전부 Tier1인데 나머지는 아닌지: Chipping만 원본/r1 양쪽에서 대부분
그대로 재현됐고, 다른 defect는 재현성 문제가 있거나(Particle/Micro_Crack) 시간선행성
검사 방식과 원인의 성질이 안 맞아서(Remain_Coat — 전성재님이 이미 지적한 "즉시성
현상이라 추세형 검사에 안 걸림") Tier1 기준을 못 채웠다.

## 교차 defect 공통 인자 (`08_cross_defect_vibration.csv`)

`Vibration`이 3개 defect(Particle/Chipping/Micro_Crack)에서 원인 후보로 나왔지만,
**신뢰도는 defect마다 전혀 다르다** — Chipping은 원본/r1 양쪽 재현 + 시간선행성 확인까지
된 강한 신호, Particle/Micro_Crack은 원본에서만 또는 양쪽 다 약한 신호다. "Vibration
하나가 세 불량의 공통 원인"이라고 단순화해서 보고하면 안 된다.

## 실행 방법

```bash
python "26.08.01_2128_Goal2_통합_전체방법론_4개defect/unified_full_methodology.py"
python "26.08.01_2128_Goal2_통합_전체방법론_4개defect/reproducibility_check.py"
```

이 브랜치에는 `data/raw/`가 없다 — `DP_HealthIndex_Dataset.csv`/`_r1.csv`를 저장소
루트의 **상위 폴더**에 둬야 한다(용량 때문에 git 커밋 안 함).

## 산출물

| 파일 | 내용 |
|---|---|
| `00_summary.json` | 실행 메타데이터 |
| `01~06_{defect}_*.csv` | 방법 A~F 각각의 defect별 상세 결과 |
| `07_{defect}_unified_verdict.csv` | 6개 방법 통합 최종 판정표 |
| `08_cross_defect_vibration.csv` | 교차 defect 공통 인자 |
| **`09_reproducibility_by_dataset.csv`** | **원본/r1 재현성 — 가장 중요한 발견** |

## 다음 결정이 필요한 것

1. **재현성표를 tier 로직에 반영할지** — 반영하면 Particle의 Vibration/Micro_Crack의
   Vibration은 강등되고, Remain_Coat의 CLN_Pressure는 방향유지로 유지될 가능성이 큼.
2. **박대호님/JHdaimma님께 이 재현성 결과를 공유하고 확인받을 것** — 특히 각자의
   결론이 r1 없이(원본 단독) 도출된 것이었는지, r1까지 반영한 것이었는지 재확인 필요.
3. r1이 "모든 defect에 균등하게 적용 가능한 시나리오"인지, 아니면 "Chipping/Crack
   전용으로 설계된 시나리오"인지 멘토/현업에 확인 필요 — 이게 확인되면 Particle/
   Remain_Coat는 원본 단독 결과를 우선하는 게 맞을 수도 있음.
