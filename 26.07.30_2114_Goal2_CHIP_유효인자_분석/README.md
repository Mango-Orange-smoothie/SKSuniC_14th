# Goal 2 — NG_Code: CHIP 유효인자 발굴

레이저 다이싱 공정의 Chipping(모서리 파손) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney U + BH-FDR,
RandomForest permutation importance)을 **모두** 통과한 것만 "유효인자"로 확정한다.

> ⚠️ **이번 4개 defect 분석 중 가장 희귀한 이벤트**: `NG_Code=='CHIP'`와 `Chipping==1`이
> 완전히 동일한 **정확히 4건**(전체의 0.004%)뿐이다. train/test 분할하면 test셋에 양성
> 표본이 1개만 남는다 — 이건 "패턴 탐지"가 아니라 사실상 "4개 개별 사례를 기록한 것"에
> 가깝다. 아래 결과는 절대 "확정된 원인"으로 읽지 말고, CHIP 사례가 더 쌓였을 때(또는
> 실제 라인 데이터에서) 재검증해야 할 극도로 잠정적인 순위로만 취급할 것.

BURN/PARTICLE/REM_COAT/CRACK과 코드 구조·통계 기준은 동일하다. 다만 Chipping은 팀
HealthIndex 설계서에 **이번 4개 defect 중 가장 명시적인 근거가 많은** defect라
(`Groove_Depth`, `Beam_Diameter`, `Vibration`, `Focus` 전부 회의록·PDF 직접 인용),
도메인 가설표의 "제 추론" 비중이 가장 낮다. 상세 내용은
[`DOMAIN_KNOWLEDGE.md`](./DOMAIN_KNOWLEDGE.md) 참고.

## 실행 방법

```bash
python "26.07.30_2114_Goal2_CHIP_유효인자_분석/chip_influence_factors.py"
```

## 핵심 설계 결정

- **정렬/센터링 계열을 이번엔 `defect_related`로 포함**: BURN/PARTICLE/REM_COAT에서는
  `Cutting_X/Y_Index`, `Package_Size_1~4` 등을 "Chipping 메커니즘이라 무관"이라고
  적어 제외했었다. CHIP 분석에서는 그 Chipping이 바로 이 defect이므로, 이번엔
  이 컬럼들을 도메인 가설에 포함시켰다 — 다른 3개 분석과 대조해서 읽으면 논리적
  일관성이 보인다.
- **극소표본 대응**: 통계 기준(FDR, effect size, tree top-10)은 다른 defect와
  동일하게 유지했지만, n=4에서는 Cliff's delta가 ±1.0 근처로 쉽게 튀는 등 추정치
  자체의 불확실성이 매우 크다는 점을 결과 해석에 반드시 반영해야 한다.

## 산출물

| 파일 | 내용 |
|---|---|
| `00_chip_factors_summary.json` | 실행 메타데이터 (통계 검정력 경고 포함) |
| `01_chip_rate_by_stratum.csv` | Machine/Product/Recipe/OPCOND별 발생률 sanity check |
| `02_univariate_test_results.csv` | Mann-Whitney U + BH-FDR + Cliff's delta |
| `03_tree_importance.csv` | RandomForest permutation importance |
| `04_chip_influence_factors_final.csv` | **메인 산출물** |

## 결과 요약 (2026-07-30 실행 기준, n=4 극소표본 — 참고용으로만 읽을 것)

`confirmed` 2건: **`Kerf_Width_Profile`**(effect size ≈1.00), **`Groove_Depth`**
(effect size ≈-0.83, 방향도 가설과 일치 — Depth 부족→Chipping). 둘 다 팀 HealthIndex
설계서가 명시적으로 근거를 남긴 바로 그 메커니즘이라 **표본이 4개뿐인데도 팀 문서와
정확히 들어맞은 건 고무적**이다. 다만 n=4에서 나온 "confirmed"라는 라벨을 다른
defect의 confirmed와 같은 신뢰도로 취급하면 안 된다.

**참고 — `Laser_Cleaning_Demand`**(`candidate_needs_domain_review`, effect size -0.98):
이건 `Laser_Power × Groove_Depth`로 정의된 파생 피처라, `Groove_Depth`의 강한 신호가
그대로 묻어 들어온 것일 가능성이 높다(독립적인 새 발견이 아니라 상관에 의한 중복
신호로 보는 게 타당) — 의도적으로 무관 처리를 유지했다.
