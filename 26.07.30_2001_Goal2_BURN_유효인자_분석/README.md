# Goal 2 — NG_Code: BURN 유효인자 발굴

레이저 다이싱 공정의 Edge Burn(과열) 불량을 유발하는 FDC/Response 인자를
① 물리 메커니즘 기반 도메인 가설과 ② 통계적 교차검증(Mann-Whitney U + BH-FDR,
RandomForest permutation importance)을 **모두** 통과한 것만 "유효인자"로 확정한다.

`pipeline/`의 공용 전처리 산출물(OPCOND 층화 baseline)과 `pipeline/common.py`
헬퍼를 그대로 재사용했다. 원본 데이터/공용 pipeline 파일은 수정하지 않았다.

## 실행 방법

저장소 루트에서:

```bash
python "26.07.30_2001_Goal2_BURN_유효인자_분석/burn_influence_factors.py"
```

## 핵심 설계 결정

- **라벨 3종 병행**: `NG_Code=='BURN'`(엄격, 392건)을 주 라벨로 쓰되 `Edge_Burn==1`(broad,
  441건 — 다른 defect와 41건 동시발생)도 함께 검정해 라벨 정의 차이로 인한 왜곡을 확인한다.
- **OPCOND(Product×Recipe) 층화 z-score**로 정규화 후 검정 — Machine_ID별 BURN 발생률이
  0.33~0.47%로 균일함을 먼저 확인했으므로(`01_burn_rate_by_stratum.csv`), 특정 장비 쏠림이
  아니라 연속 공정변수 이상이 원인이라는 전제로 설계했다.
- **신규 공학 피처 `Thermal_Load_Ratio = Laser_Power × Frequency / Cooling_Flow`**:
  burn은 개별 변수가 아니라 "에너지 투입 vs 방열"의 비율(밸런스) 문제라는 도메인 가설을
  직접 검증하기 위해 추가.
- **"유효인자" 확정 기준**: 서로 다른 방법론(단변량검정 vs 트리기반 다변량중요도) **둘 다**
  합의해야 하고, 도메인 가설표에도 있어야 `confirmed`. 같은 방법이 Primary/Broad 두 라벨
  모두에서 뜨는 것은 "라벨 일관성"이라는 별개의 보강 신호로만 취급하고 방법 합의 수에는
  중복 반영하지 않는다 (`n_labels_univariate_flag` / `n_labels_tree_flag` 컬럼 참고).

## 산출물

| 파일 | 내용 |
|---|---|
| `00_burn_factors_summary.json` | 실행 메타데이터 (표본수, 임계값, verdict 분포, 최종 confirmed 목록) |
| `01_burn_rate_by_stratum.csv` | Machine/Product/Recipe/OPCOND별 BURN 발생률 (쏠림 sanity check) |
| `02_univariate_test_results.csv` | Mann-Whitney U + BH-FDR + Cliff's delta (라벨별 × 후보컬럼별) |
| `03_tree_importance.csv` | RandomForest permutation importance (라벨별 × 후보컬럼별) |
| `04_burn_influence_factors_final.csv` | **메인 산출물** — 도메인 가설 + 통계 교차검증 병합 최종표 |

## 현재 결과 요약 (2026-07-30 실행 기준)

`confirmed` 3건: **Frequency**(에너지 투입/펄스중첩, effect size 0.98·p≈4.5e-245로 압도적),
**Thermal_Load_Ratio**(에너지/방열 비율 공학피처, effect size 0.54), **Surface_Roughness**
(결과 공변 — 원인이라기보다 동일 근본원인의 동반증상일 가능성 높음, 해석 시 주의).

`Cooling_Flow`는 트리 중요도(다변량·상호작용)에서만 상위권으로 잡히고 단변량 검정에서는
안 잡힘 — burn이 Cooling_Flow 단독보다 Laser_Power/Frequency와의 **조합**에서 작동한다는
도메인 가설과 정합적인 패턴. `candidate_weak_signal`로 분류, Goal3(상호작용) 팀원에게
우선 전달할 후보로 남겨둠.

## 알려진 한계 / 다음 확인 사항

- README(`pipeline/README.md`)가 교차검증하라고 요구하는 `03_impact_factor_ranking.csv`,
  `full_correlation/02b_process_parameter_correlation_pairs.csv`가 저장소 어느 브랜치에도
  없어 이번 라운드에서는 교차검증하지 못했다. 파일 위치 확인 후 재검증 필요.
- `Top_Kerf`/`Bottom_Kerf`/`Surface_Roughness`처럼 "결과 공변" 성격의 Response 변수는
  burn의 원인이라기보다 같은 근본원인(과열)의 동반증상일 가능성이 있어, Health Index
  가중치나 SOP 매칭에 쓸 때는 "원인 인자"와 구분해서 다뤄야 한다.

## 추후 개인 검토 예정 (기록용)

이번 분석은 100,000행 전체를 행 단위로 쓰고 OPCOND(Product×Recipe)는 z-score 정규화
기준으로만 사용했다(그룹 집계 X). 확인 과정에서 **OPCOND 조합(54개)별 BURN 발생률이
0.10%~0.85%로 최대 약 8배 차이**나는 것을 발견했다(`01_burn_rate_by_stratum.csv`의
`Product_ID+Recipe_ID` 행 참고). 다만 조합당 BURN 건수가 2~16건뿐이라 이 차이가 통계적으로
유의한 신호인지 우연인지는 검정하지 않았다.

- 그룹(OPCOND) 단위 집계로 재분석하는 것이 원인인자 발굴에 더 나은지는 별도로 검토가
  필요하다고 판단했으나, 표본 부족(그룹당 BURN 2~16건)으로 이번 라운드에서는 보류했다.
  이 브랜치 작업자가 추후 개인적으로 카이제곱/Fisher 검정 등으로 이어서 확인할 예정.
  (결과가 유의하면 Goal1 담당자와도 공유 — "장비/레시피가 아니라 특정 Product×Recipe
  조합 자체가 burn 위험 요인일 수 있다"는 별개의 질문이라 Goal1 쪽에 더 가까움.)
