# Goal 2 — NG_Code: REM_COAT 유효인자 발굴

레이저 다이싱 공정의 Remain_Coat(코팅 잔류) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney U + BH-FDR,
RandomForest permutation importance)을 **모두** 통과한 것만 "유효인자"로 확정한다.

BURN/PARTICLE 분석과 코드 구조·통계 기준은 동일하지만, 도메인 가설은 Remain_Coat
물리 메커니즘(세정 공정이 보호 코팅을 다 씻어내지 못함)에 맞춰 새로 세웠다. 도메인
지식/판단기준은 [`DOMAIN_KNOWLEDGE.md`](./DOMAIN_KNOWLEDGE.md) 참고.

## 실행 방법

```bash
python "26.07.30_2102_Goal2_REM_COAT_유효인자_분석/rem_coat_influence_factors.py"
```

## 핵심 설계 결정

- **라벨 2종이지만 사실상 동일**: `NG_Code=='REM_COAT'`와 `Remain_Coat==1`이 **완전히
  일치**한다(둘 다 2,332건). Burn/Particle과 달리 이 defect는 다른 불량과 전혀 겹치지
  않는 "깨끗한" 단일원인 불량이다 — 그만큼 원인 규명이 더 명확하게 나올 것으로 기대했고,
  실제로 그렇게 나왔다(아래 결과 요약).
- **레이저(절단) 관련 변수 대부분을 의도적으로 무관 처리**: 코팅 제거는 절단 자체가
  아니라 후속 "세정" 공정의 일이라고 판단해 `Laser_Power`/`Focus`/`Beam_Diameter`/
  `Groove_Depth`/`Kerf_*` 등을 전부 `not_related_to_defect`로 분류했다. Particle
  분석과 정반대 판단이라 두 결과를 대조하는 재미가 있다.
- **`Coating_Thickness`/`Coating_Uniformity`는 데이터 누수 위험 때문에 도메인 지지
  없이 유지**: 세정 "후" 측정값이라면 잔류 코팅량과 사실상 동어반복이 될 수 있어서다.

## 산출물

| 파일 | 내용 |
|---|---|
| `00_rem_coat_factors_summary.json` | 실행 메타데이터 |
| `01_rem_coat_rate_by_stratum.csv` | Machine/Product/Recipe/OPCOND별 발생률 sanity check |
| `02_univariate_test_results.csv` | Mann-Whitney U + BH-FDR + Cliff's delta |
| `03_tree_importance.csv` | RandomForest permutation importance |
| `04_rem_coat_influence_factors_final.csv` | **메인 산출물** |

## 결과 요약 (2026-07-30 실행 기준)

`confirmed` 1건: **`CLN_Pressure`**(effect size -0.54, p≈0 — 두 방법 모두 강하게 합의).
방향도 가설과 정확히 일치(압력 낮을수록 remain coat 증가) — 팀 HealthIndex 설계서가
이미 "압력 부족 시 세정 불완전(Remain_Coat) 근거는 명확"이라고 적어둔 것과 데이터가
그대로 들어맞은, 이번 4개 defect 분석 중 가장 깔끔한 결과다.

**주목할 사례 — `candidate_needs_domain_review`**: `Coating_Thickness`가 effect size
-0.28, p≈2.3e-116로 통계적으로는 매우 강하게 나왔다. 하지만 도메인 가설표에서 "세정
후 측정값이면 잔류 코팅량과 동어반복이라 데이터 누수 위험"이라고 판단해 일부러 지지를
안 넣었더니, verdict 로직이 정확히 `candidate_needs_domain_review`(통계는 강한데 도메인
설명이 없음)로 걸러냈다 — 검증 카테고리가 설계 의도대로 작동한 사례. 이 컬럼의 측정
시점(가공 전/후)을 먼저 확인하기 전엔 "원인 인자"로 보고하면 안 된다.

`Cleaning_Load_Ratio`, `Cleaning_Capacity`, `CLN_Flow`는 `candidate_weak_signal` —
CLN_Pressure만큼 강하지 않지만 방향은 전부 가설과 일치.
