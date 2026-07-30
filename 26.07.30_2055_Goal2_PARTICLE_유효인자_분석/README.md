# Goal 2 — NG_Code: PARTICLE 유효인자 발굴

레이저 다이싱 공정의 Particle(이물) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney U + BH-FDR,
RandomForest permutation importance)을 **모두** 통과한 것만 "유효인자"로 확정한다.

BURN 분석(`../26.07.30_2001_Goal2_BURN_유효인자_분석/`)과 코드 구조·통계 기준은 동일하지만,
Particle의 물리 메커니즘(어블레이션 디브리 발생 vs 세정 능력)에 맞춰 도메인 가설은 처음부터
새로 세웠다. 도메인 지식/판단기준은 [`DOMAIN_KNOWLEDGE.md`](./DOMAIN_KNOWLEDGE.md) 참고.

## 실행 방법

```bash
python "26.07.30_2055_Goal2_PARTICLE_유효인자_분석/particle_influence_factors.py"
```

## 핵심 설계 결정

- **라벨 2종 병행**: `NG_Code=='PARTICLE'`(6,455건, 6.455%)을 주 라벨, `Particle==1`(7,792건,
  7.792%)을 보조 라벨로 검정. 둘의 차이(1,337건)는 전부 `NG_Code=='REM_COAT'`와 동시발생 —
  이물 오염과 코팅잔류가 물리적으로 같은 "세정 부족" 근본원인을 공유할 가능성을 시사.
- **Burn과 동일하게 OPCOND 층화 z-score + 팀 공용 도메인피처(`config.DOMAIN_FEATURES`) 포함**.
  특히 `Cleaning_Load_Ratio`(세정수요/세정능력)가 이번 분석의 핵심 가설을 이미 수식화하고
  있어 별도 신규 공학피처는 만들지 않았다(중복 재구현 방지).
- **"유효인자" 확정 기준은 Burn과 동일**: 서로 다른 방법론(단변량검정 vs 트리기반
  다변량중요도) 둘 다 합의 + 도메인 가설 있어야 `confirmed`.

## 산출물

| 파일 | 내용 |
|---|---|
| `00_particle_factors_summary.json` | 실행 메타데이터 |
| `01_particle_rate_by_stratum.csv` | Machine/Product/Recipe/OPCOND별 발생률 sanity check |
| `02_univariate_test_results.csv` | Mann-Whitney U + BH-FDR + Cliff's delta |
| `03_tree_importance.csv` | RandomForest permutation importance |
| `04_particle_influence_factors_final.csv` | **메인 산출물** |

## 결과 요약 (2026-07-30 실행 기준)

`confirmed` 2건: **Surface_Roughness**(effect size 0.72, p≈0으로 압도적 — 다만 이건
"원인"이 아니라 "particle이 표면에 남아 거칠기를 직접 높이는 결과 공변"일 가능성이 매우
높다, 해석 주의), **Vibration**(effect size 0.22, p≈1.5e-190 — 기계적 진동이 디브리를
비산/재부착시킨다는 가설과 정합적, 이쪽이 실질적 "원인 인자"에 더 가까움).

`CLN_Flow`, `Cleaning_Capacity`, `Beam_Diameter`는 단변량에서는 안 잡히고 트리
중요도(Broad 라벨)에서만 상위권으로 잡히는 `candidate_weak_signal` — 세정 능력이
단독보다 다른 변수와의 조합에서 작동할 가능성. Goal3(상호작용) 팀원에게 전달 권장.
`Cleaning_Load_Ratio`(핵심 가설 피처)는 이번 라운드에서는 `insufficient_evidence`로
나왔다 — Cleaning_Capacity/CLN_Flow가 개별적으로는 조합효과를 보이는데 그 둘을 나눈
비율 자체는 오히려 신호가 약해진 것으로, 비율 계산 방식(분모/분자 스케일)을
재검토할 여지가 있다.
