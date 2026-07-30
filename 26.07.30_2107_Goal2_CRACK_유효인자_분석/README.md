# Goal 2 — NG_Code: CRACK 유효인자 발굴

레이저 다이싱 공정의 Micro_Crack(미세균열) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney U + BH-FDR,
RandomForest permutation importance)을 **모두** 통과한 것만 "유효인자"로 확정한다.

> ⚠️ **극희귀 이벤트 경고**: Primary 라벨 34건, Broad 라벨 41건(전체의 0.03~0.04%)뿐이다.
> BURN(392건)보다도 10배 이상 희귀해서 통계 검정력이 훨씬 약하다. 이 폴더의 모든 결과는
> "확정된 원인"이 아니라 **"우선순위가 높은 가설"** 정도로 읽어야 한다.

BURN/PARTICLE/REM_COAT와 코드 구조·통계 기준은 동일하지만, 도메인 가설표는 팀 문서에
명시적 근거가 거의 없어 대부분 레이저 가공 일반 물리(열충격, 피로파괴)에 기반한
**작성자의 추론**이다. 상세 내용은 [`DOMAIN_KNOWLEDGE.md`](./DOMAIN_KNOWLEDGE.md) 참고.

## 실행 방법

```bash
python "26.07.30_2107_Goal2_CRACK_유효인자_분석/crack_influence_factors.py"
```

## 핵심 설계 결정

- **라벨**: `NG_Code=='CRACK'`(34건)과 `Micro_Crack==1`(41건). 차이 7건은 PARTICLE(5)/
  REM_COAT(1)/CHIP(1)과 동시발생 — 표본이 워낙 작아 이 겹침 자체도 우연일 가능성을
  배제 못 한다.
- **도메인 가설 대부분이 "제 추론"**: 팀 HealthIndex 설계서는 Chipping/Remain_Coat/Burn
  위주로 서술되어 있고 Crack에 대한 명시적 메커니즘 근거가 거의 없다. 그래서 이번
  가설표는 열충격·기계적 피로라는 레이저가공 일반 물리 원리에서 출발했다 —
  `DOMAIN_KNOWLEDGE.md`에 컬럼마다 "제 추론"임을 명시했다.
- **통계 기준(FDR, effect size, tree top-10)은 다른 defect와 동일하게 유지**했지만,
  표본이 극히 작아 p-value/effect size 추정 자체의 불확실성(표준오차)이 크다는 걸
  감안하고 읽을 것.

## 산출물

| 파일 | 내용 |
|---|---|
| `00_crack_factors_summary.json` | 실행 메타데이터 (통계 검정력 경고 포함) |
| `01_crack_rate_by_stratum.csv` | Machine/Product/Recipe/OPCOND별 발생률 sanity check |
| `02_univariate_test_results.csv` | Mann-Whitney U + BH-FDR + Cliff's delta |
| `03_tree_importance.csv` | RandomForest permutation importance |
| `04_crack_influence_factors_final.csv` | **메인 산출물** |

## 결과 요약 (2026-07-30 실행 기준, n=34 극소표본 주의)

`confirmed` 2건: **Frequency**(effect size 0.86, p≈2.2e-16 — BURN 분석에서도 1위였던
바로 그 변수. 펄스 중첩→열피로 축적이라는 메커니즘이 Burn과 Crack 모두에서 확인된
것으로, 두 defect가 부분적으로 같은 근본원인을 공유할 가능성을 시사), **Surface_Roughness**
(effect size 0.42 — 결과 공변 후보, 원인 아닐 수 있음).

**재검토 필요 — `Kerf_Width_Profile`**: `not_related_to_defect`로 분류했는데(절단 폭은
파단과 별개 메커니즘이라고 판단), 실제로는 effect size 0.25·트리 중요도도 상위권으로
나와 `candidate_needs_domain_review`가 됐다. n=34라 확실친 않지만, "그루브가 예상보다
넓게 파였다면 절단 팁에 응력이 더 집중됐을 수 있다"는 가설로 재해석할 여지가 있다 —
제 최초 판단(무관)이 틀렸을 수 있는 사례로 다음 라운드에 재검토할 것.
