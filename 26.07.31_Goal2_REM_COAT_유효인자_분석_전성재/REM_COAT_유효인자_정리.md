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

## 6. 2차 검증 — Machine 통제 다변량 방법 (전성재, `verify_v2_multivariate_controlled.py`)

5번 검증(=Jun 방식을 다르게 재구현한 것)은 Jun과 **사실상 같은 종류의 방법**(불량군 vs
정상군 단순 비교)이라 같은 답이 나온 게 당연했다. **여기서부터가 진짜 다른 방법이다.**

**문제의식**: `01_rem_coat_rate_by_stratum.csv`에서 DP04만 불량률이 1.6~1.8배 높다는 걸
확인했다. `CLN_Pressure`, `CLN_Flow`, `Cleaning_Capacity`, `Cleaning_Load_Ratio`는 계산식
자체가 서로 얽혀있다(`Cleaning_Capacity = CLN_Flow × CLN_Pressure × CLN_Time`). 이런 상황에서
"불량군과 정상군의 값이 다르다"는 단변량 비교만으로는 ①장비 차이 때문에 생긴 착시인지,
②서로 얽힌 변수 중 진짜 원인이 뭔지 구분할 수 없다.

**방법**:
1. OPCOND(Product×Recipe) 층별 강건 z-score로 정규화(`pipeline.common.zscore_transform`
   재사용) — 같은 제품/레시피 조건끼리만 비교
2. **Machine_ID를 더미변수로 넣은 L1(Lasso) 로지스틱 회귀** — "같은 장비 안에서도 이
   변수가 불량과 관련 있는가"를 직접 검정. L1이 서로 얽힌 변수 중 독자적 설명력이 없는
   변수의 계수를 자동으로 0으로 만들어줌
3. **HistGradientBoostingClassifier + permutation importance(ROC-AUC)** — 1차 검증의
   RandomForest와는 다른 트리 계열, 다른 채점 기준으로 교차검증
4. 두 방법 모두 통과한 컬럼만 "확정"

**원본 데이터 결과**:

| 컬럼 | 로지스틱 계수 | 오즈비(1 stratum-SD당) | 확정 |
|---|---|---|---|
| **CLN_Pressure** | -0.420 | 0.657 (odds 34%↓) | ✅ |
| Coating_Thickness | -0.174 | 0.840 (odds 16%↓) | ✅ (누수 우려 여전) |
| CLN_Flow | -0.069 | — | ❌ L1이 계수 0으로 만듦 |
| Cleaning_Capacity, Cleaning_Load_Ratio, CLN_Time 등 | 0 | — | ❌ |

→ `CLN_Pressure`가 Machine 통제 후에도 살아남았고, 오즈비 기준으로 오히려 더 뚜렷해졌다.
`CLN_Flow`/`Cleaning_Capacity`/`Cleaning_Load_Ratio`가 5번 검증에서 "약한 신호"로 나온 건
"CLN_Pressure가 이미 설명하는 것 이상의 독자적 정보가 없다"는 뜻이었다는 게 이걸로 밝혀짐.

산출물: `verify_v2_00_summary.json`, `verify_v2_04_machine_controlled_factors.csv`

## 7. 새 데이터(r1, 불량률 높인 버전) 재검증

멘토님이 불량률을 높여서 새로 준 데이터(`DP_HealthIndex_Dataset_r1.csv`)로 **전처리
코드(`pipeline/`)는 한 줄도 안 바꾸고, 입력 파일과 `EXPECTED_ROW_COUNT`/`EXPECTED_NORMAL_COUNT`
상수만 교체**해서 Step0부터 5번·6번과 동일한 코드로 재실행했다.

- 원본: 100,000행, 정상군 90,783건(90.8%), Remain_Coat 2.33%
- r1: 100,000행, 정상군 58,890건(58.9%), Remain_Coat **7.44%** (약 3.2배↑), NG_Code에
  `LASER`라는 새 유형도 등장

### 결과 비교 — 방법 A(단순 비교) vs 방법 B(Machine 통제 다변량)

| | 방법 A (5번, 단순 비교) | 방법 B (6번, Machine 통제) |
|---|---|---|
| 원본 데이터 결론 | CLN_Pressure 확정 (효과 -0.543) | CLN_Pressure 확정 (오즈비 0.657) |
| r1 데이터 결론 | **CLN_Flow가 1위(-0.69), CLN_Pressure는 탈락(-0.17, 기준 미달)** | **CLN_Pressure 여전히 확정, 오즈비 0.444(원본보다 더 강함)** |
| 데이터가 바뀌어도 결론이 일관되는가 | ❌ 아니오 — 1등이 통째로 바뀜 | ✅ 예 — CLN_Pressure 순위 유지 |

r1에서 방법 B가 추가로 확정한 것: `Cleaning_Load_Ratio`(오즈비 0.304, 방법 B 기준 가장 강함),
`CLN_Flow`(오즈비 0.827), `Coating_Thickness`(누수 우려 동일), `CLN_Time`(오즈비 2.03 —
**방향이 도메인 가설과 반대라 다중공선성에 의한 부호 역전으로 의심, 원인으로 보고하면
안 됨**, `Coating_Thickness`와 같은 급의 "현업 확인 필요" 항목). 방법 A에서 새로 튀어나왔던
`Kerf_Width_Profile`/`Top_Kerf`/`Bottom_Kerf`/`Head_Temp`/`Focus`(절단·열 계열, 세정 메커니즘과
무관)는 방법 B에서 전부 탈락 — Machine/상관변수 통제로 걸러진 착시로 판단.

산출물: `r1_higher_defect_rate/preprocessing/`(Step0 재실행), `r1_higher_defect_rate/verify_0*`
(방법 A), `r1_higher_defect_rate/verify_v2_*`(방법 B)

### 방법 A와 B, 뭐가 맞는가 — 근거

**방법 B(Machine 통제 다변량)가 맞다.** 근거 세 가지:

1. **구조적 문제 회피**: `CLN_Pressure`/`CLN_Flow`/`Cleaning_Capacity`/`Cleaning_Load_Ratio`는
   계산식 자체가 얽혀있는 변수다(`Cleaning_Capacity = CLN_Flow × CLN_Pressure × CLN_Time`).
   방법 A(단변량)는 이렇게 얽힌 변수들을 각각 따로 검정하기 때문에, 진짜 원인이 아니어도
   "얽혀있다는 이유만으로" 유의하게 나올 수 있다 — 통계학적으로 잘 알려진 한계다. 방법 B는
   전부 같은 모델에 넣고 서로의 효과를 통제하기 때문에 이 문제를 원천적으로 피한다.
2. **재현성/안정성**: 진짜 원인이라면 불량률이 달라져도(데이터가 바뀌어도) 같은 결론이
   나와야 한다. 방법 A는 원본→r1로 데이터가 바뀌자 1위가 통째로 바뀌었다(불안정). 방법 B는
   원본과 r1 모두에서 `CLN_Pressure`가 유지됐다(안정적) — 안정적인 결론일수록 신뢰도가 높다.
3. **Confounding 통제**: DP04만 불량률이 유독 높다는 걸 이미 알고 있는데, 방법 A는 이걸
   전혀 고려하지 않는다. 방법 B는 Machine_ID를 통제 변수로 넣어서 "장비 차이로 설명되는
   부분"과 "변수 자체의 효과"를 분리한다.

r1에서 방법 A만 봤다면 "CLN_Flow가 진짜 원인이고 CLN_Pressure는 아니다"로 잘못 결론 내릴
뻔했다. 방법 B 덕분에 데이터가 바뀌어도 흔들리지 않는 결론(CLN_Pressure)을 확인했다.

## 8. 다음에 확인할 것 (전성재 담당 관점)

1. `Coating_Thickness` 측정 시점(가공 전/후)을 현업/멘토에게 확인 — 데이터 누수 여부 판가름
2. DP04 장비의 `CLN_Pressure`/`CLN_Flow` 실측값이 다른 3대와 어떻게 다른지 장비별로 재확인
   (`00_stratum_baseline_stats_by_machine_opcond.csv` 활용 가능)
3. `03_impact_factor_ranking.csv`, `full_correlation/02b_process_parameter_correlation_pairs.csv`
   (Machine 통제 GROUP 기준 결과)와 교차검증 — 이 문서 작성 시점엔 로컬에 해당 파일이 없어
   대조하지 못함, Goal2 최종 제출 전 반드시 재확인
4. Goal3(상호작용) 진행 시 `CLN_Pressure`를 확정 유효인자로 우선 투입
5. `CLN_Time`(r1에서 방향이 반대로 나옴)도 `Coating_Thickness`처럼 현업 확인 전까지 원인으로
   보고하지 말 것 — 다중공선성에 의한 부호 역전 가능성
6. 보고/회의 자료에는 반드시 **방법 B(Machine 통제) 결과를 기준**으로 삼을 것 — 방법
   A(단순 비교)만 보고하면 데이터에 따라 결론이 흔들릴 수 있음(7번 참고)
