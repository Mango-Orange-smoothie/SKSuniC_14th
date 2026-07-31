# Goal2 — REM_COAT(코팅 잔류) 유효인자 정리

담당: 전성재 (branch: `전성재`)
정리 기준일: 2026-07-31
원자료 출처: branch `Jun` — `pipeline/`(Step0 전처리, 작성 Mango-Orange-smoothie/김시우) 및
`26.07.30_2102_Goal2_REM_COAT_유효인자_분석/`(REM_COAT 유효인자 발굴, 작성 Mango-Orange-smoothie)

> 이 문서는 새 분석이 아니라, `Jun` 브랜치에 이미 있는 두 산출물(전처리 · REM_COAT 유효인자
> 발굴)을 내 브랜치(`전성재`)에서 참고하기 쉽게 정리한 요약본이다. 원본 코드/데이터는
> `Jun` 브랜치에 있으며 여기서는 옮기거나 수정하지 않았다.

---

## 1. 전처리 기반 (Step0, `pipeline/step0_preprocessing.py`)

- 원본: `data/raw/DP_HealthIndex_Dataset.csv` (100,000행), 절대 수정하지 않음
- 정상군(OK) 정의: `Yield == 100 AND NG_Code == 'OK'` → 90,783건
- 층(strata) 정의
  - `OPCOND = [Product_ID, Recipe_ID]` — Machine 무관 baseline용 (Remain_Coat처럼 장비 비교가
    필요한 분석에 사용)
  - `GROUP = [Machine_ID, Product_ID, Recipe_ID]` — Machine을 통제변수로 둘 때 사용
- REM_COAT 분석이 그대로 재사용한 Step0 산출물
  - `00_column_classification.csv` → 68개 원본 컬럼의 subsystem/타입/변동성/추세 분류.
    `Remain_Coat`, `Remain_Coat_Die`는 `defect_binary`/`defect_count`로 분류되어 있고
    변동성 등급은 `variable`(둘 다 rate_cv / index_of_dispersion 기준)
  - `00_stratum_baseline_stats_by_opcond.csv` — OPCOND 층 median/MAD baseline (z-score 정규화 근거)
  - `00_preprocessing_summary.json` — 정합성 검증 결과(Fail_Die vs (100-Yield) Spearman ≈ 0.9999)

## 2. REM_COAT 유효인자 발굴 방법론 (`rem_coat_influence_factors.py`)

Remain_Coat(코팅 잔류)를 유발하는 FDC/Response 인자를 아래 **두 조건을 모두 통과**해야만
"유효인자"로 확정하는 방식:

1. **물리 메커니즘 기반 도메인 가설** — 세정 공정(CLN_*)이 보호 코팅을 다 씻어내지
   못하는 것이 사실상 유일하게 알려진 메커니즘이라는 전제로, 절단(레이저) 계열 변수
   대부분은 1차적으로 "무관"으로 분류
2. **통계적 교차검증**
   - Mann-Whitney U + Benjamini-Hochberg FDR 보정 + Cliff's delta(효과크기, 기준 ≥0.2)
   - RandomForest permutation importance
   - 두 라벨(primary/broad, is_remcoat 정의 방식 차이) 기준으로 각각 계산 후 일치 여부 확인

후보 컬럼 39개 전체를 이 기준으로 스캔했고, `pipeline/`의 OPCOND 층화 baseline과
`pipeline/common.py` 헬퍼를 그대로 재사용(재구현하지 않음).

## 3. 발생률 sanity check (`01_rem_coat_rate_by_stratum.csv`)

| 층 | 값 | Remain_Coat 발생률 |
|---|---|---|
| Machine_ID | DP01 | 2.06% |
| Machine_ID | DP02 | 1.94% |
| Machine_ID | DP03 | 1.86% |
| Machine_ID | **DP04** | **3.45%** ← 다른 장비 대비 뚜렷하게 높음 |
| Product_ID | PKG_A~F | 2.25~2.43% (제품 간 큰 차이 없음) |

→ **장비(Machine_ID) 간 차이가 제품/레시피 간 차이보다 훨씬 크다.** DP04가 다른 3대보다
Remain_Coat 발생률이 약 1.6~1.8배 높음 — 장비 개별 세정계 상태(압력/유량 등) 점검 우선순위.

## 4. 최종 유효인자 판정 (`04_rem_coat_influence_factors_final.csv`)

| 판정 | 컬럼 | 서브시스템 | 메커니즘 가설 | 방향 |
|---|---|---|---|---|
| **confirmed** | `CLN_Pressure` | fdc_cleaning | 세정 압력 부족 → 코팅 미제거 | 낮을수록 불량↑ |
| candidate_weak_signal | `Cleaning_Load_Ratio` | engineered(팀 공용) | 세정 부담 대비 세정 능력 | 높을수록 불량↑ |
| candidate_weak_signal | `Cleaning_Capacity` | engineered(팀 공용) | CLN_Flow×Pressure×Time 종합 | 낮을수록 불량↑ |
| candidate_weak_signal | `CLN_Flow` | fdc_cleaning | 세정 유량 부족 → 코팅 미제거 | 낮을수록 불량↑ |
| candidate_needs_domain_review | `Coating_Thickness` | response | ⚠ 측정 시점(가공 전/후) 불확실 — 세정 후 측정이면 잔류 코팅량과 동어반복(데이터 누수 위험) | 확인 전까지 후보 제외 |
| insufficient_evidence | 나머지 35개 | — | 절단/열/정렬 계열 등 세정 메커니즘과 무관하거나 근거 부족 | — |

- **핵심 결론**: 세정계(Cleaning subsystem, `CLN_*`) 4개 변수 중 `CLN_Pressure`만 두 통계
  방법 모두에서 유의(FDR-p ≈ 0, Cliff's delta ≈ -0.54)했고 도메인 가설과도 일치 → 가장
  신뢰도 높은 유효인자
- `CLN_Flow`, `Cleaning_Capacity`, `Cleaning_Load_Ratio`는 방향은 같은 계열(세정능력)이지만
  한 가지 방법에서만 유의해 "약한 신호"로 보류
- `Coating_Thickness`는 상관은 강하지만(Cliff's delta -0.28) 원인이 아니라 결과일 수 있어
  **측정 시점 확인 전까지 후보에서 제외**해야 함 — Goal2/Goal3로 넘어가기 전에 반드시
  현업에 확인 필요한 항목

## 5. 독립 검증 (전성재, `verify_rem_coat_factors.py`)

Jun 브랜치의 판정을 그대로 믿지 않고, 원본 데이터셋으로 **직접 새 코드를 작성**해서
재현되는지 확인했다. `pipeline/config.py`/`pipeline/common.py`(공용 KEY/GROUP/OPCOND/NORMAL
정의)만 재사용하고, REM_COAT 분석 코드는 보지 않고 별도로 작성했다.

방법: 후보 39개 컬럼(FDC+response+도메인피처+Maintenance_Count)에 대해
① Mann-Whitney U + BH-FDR 보정 + rank-biserial correlation(=Cliff's delta) 효과크기,
② RandomForest permutation importance(average_precision 기준) — 두 방법 모두를 통과한
컬럼만 "확정"으로 판정. n=100,000이면 사소한 차이도 p<0.05가 나오므로 효과크기
(|rank-biserial| ≥ 0.2)를 별도 기준으로 강제했다.

| 컬럼 | rank-biserial 효과크기 | FDR-p | tree top10 | 두 방법 모두 통과 |
|---|---|---|---|---|
| **CLN_Pressure** | **-0.543** | ≈0 | ✅ | ✅ **확정** |
| Coating_Thickness | -0.279 | ≈0 | ✅ | ✅ **확정** (단, 아래 주의사항 참고) |
| Cleaning_Load_Ratio | 0.195 | ≈0 | ❌ | 미달 (효과크기 0.2 기준 근소 미달) |
| Cleaning_Capacity | -0.193 | ≈0 | ❌ | 미달 |
| CLN_Flow | -0.145 | ≈0 | ✅ | 미달 (univariate 효과크기 부족) |
| 나머지 34개 | 대부분 \|효과\| < 0.03 | 대부분 미보정 유의 | ❌ | — |

**결론: Jun 브랜치 판정과 사실상 일치.**
- `CLN_Pressure`가 39개 후보 중 압도적으로 가장 큰 효과크기 → 독립적으로도 "확정 유효인자"로 재현됨
- 세정계 나머지 3개(`Cleaning_Load_Ratio`/`Cleaning_Capacity`/`CLN_Flow`)는 방향은 맞지만
  효과크기가 작아 "약한 신호"라는 Jun의 판정과 동일한 결론
- **차이점 1개**: 내 기준으로는 `Coating_Thickness`도 통계적으로는 두 방법 모두 통과(확정
  기준 충족). Jun 쪽도 같은 효과크기(-0.28)를 확인했지만 "세정 후 측정이면 잔류 코팅량과
  동어반복일 수 있다"는 도메인 판단으로 후보에서 뺐음 — **통계적으로는 내 검증도 이 판단에
  반박하지 않는다.** 오히려 왜 그 컬럼이 통계적으로 강한지(측정 시점 문제일 수 있음)를
  뒷받침하는 근거가 됨. 즉 이 항목을 다시 후보에 넣자는 게 아니라, "통계만 보면 강해 보이는
  변수도 도메인 검토로 걸러야 한다"는 Jun의 경고가 맞았다는 걸 재확인한 것.

산출물: `verify_00_summary.json`, `verify_01_univariate_mannwhitney.csv`,
`verify_02_tree_permutation_importance.csv`, `verify_03_cross_validated_factors.csv`

## 6. 다음에 확인할 것 (전성재 담당 관점)

1. `Coating_Thickness` 측정 시점(가공 전/후)을 현업/멘토에게 확인 — 데이터 누수 여부 판가름
2. DP04 장비의 `CLN_Pressure`/`CLN_Flow` 실측값이 다른 3대와 어떻게 다른지 장비별로 재확인
   (`00_stratum_baseline_stats_by_machine_opcond.csv` 활용 가능)
3. `03_impact_factor_ranking.csv`, `full_correlation/02b_process_parameter_correlation_pairs.csv`
   (Machine 통제 GROUP 기준 결과)와 교차검증 — 이 문서 작성 시점엔 로컬에 해당 파일이 없어
   대조하지 못함, Goal2 최종 제출 전 반드시 재확인
4. Goal3(상호작용) 진행 시 `CLN_Pressure`를 확정 유효인자로 우선 투입
