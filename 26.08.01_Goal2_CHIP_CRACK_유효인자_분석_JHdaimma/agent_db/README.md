# Relationship DB — Chipping / Micro_Crack

담당: JHdaimma · 대상: 전체 아키텍처의 **③ Relationship Analyzer** 산출물
용도: **⑤ Root Cause Analyzer**와 **⑦ GPT AI Agent**가 참조하는 관계 지식베이스

---

## 이 DB가 답하는 질문

| 질문 | 참조 파일 |
|---|---|
| "Chipping의 원인이 뭐야?" | `db_01_factors.csv` (role=원인후보) |
| "뭘 모니터링해야 해?" | `db_01_factors.csv` (role=감시지표) |
| "이 변수가 왜 문제야?" | `db_01_factors.csv` (domain_mechanism) + `db_04` |
| "어느 값부터 위험해?" | `db_03_thresholds.csv` |
| "A가 나빠지면 뭐가 따라 나빠져?" | `db_02_relationships.csv` (그래프 탐색) |
| "이 공정 단계가 뭐 하는 거야?" | `db_04_domain_knowledge.csv` |
| "구간별로 위험도가 어떻게 달라져?" | `db_05_binning.csv` |
| "이 결론 믿어도 돼?" | `db_00_metadata.json` (limitations) |
| **"이 LOT은 왜 불량이 났어?"** | **`db_07_shap_local.csv`** (개별 건 SHAP 분해) |
| "여러 방법이 같은 답을 내나?" | `db_08_method_agreement.csv` |

---

## 파일 구조

### `db_01_factors.csv` — 유효인자 판정표 (메인)

**행 = (target, factor) 조합.** target은 `Chipping` / `Micro_Crack`.

| 컬럼 그룹 | 컬럼 | 설명 |
|---|---|---|
| **분류** | `layer` | `FDC`(직접 조절 가능한 손잡이) / `Response`(측정 결과, 조절 불가) |
| | `role` | **`원인후보`**(조치 대상) / **`감시지표`**(모니터링용) |
| | `process_stage` | 공정 단계. 근거 없으면 `unassigned` — 김시우 `subsystem`이 기준 |
| | `is_laser_grooving` | 레이저 그루빙 계열 여부 |
| **판정** | `verdict` | 아래 표 참조 |
| | `n_methods_agree` | 통과한 통계 방법 수 (0~2) |
| **도메인** | `domain_status` | `defect_related` / `not_related_to_defect` / `team_undetermined` |
| | `domain_mechanism` | **왜** 이 변수가 불량과 연결되는지 (Agent가 설명에 사용) |
| | `direction_hypothesis` | `up` / `down` / `either` |
| | `domain_source` | 근거 출처 (팀설계서 / 멘토 / 현업 / 공정지식) |
| **통계** | `delta_primary/broad/pure` | 라벨별 Cliff's delta (효과크기) |
| | `delta_nonlinear_abs_pure` | \|편차\| 기준 (U자형 탐지, 멘토 지시) |
| | `tree_imp_*`, `tree_rank_*` | RandomForest permutation importance |
| **재현성** | `delta_original_dataset` / `delta_r1_dataset` | 데이터셋별 효과크기 |
| | `n_machines_effect_ge_02` | 4대 중 몇 대에서 재현되나 |
| **주의** | `caution` | 멘토 재확인 대기 / 매핑 미확정 등 |

#### verdict 값의 뜻

| verdict | 의미 | Agent 사용법 |
|---|---|---|
| **`confirmed`** | 도메인 지지 + 통계 2개 방법 모두 통과 | **자신 있게 보고** |
| `candidate_needs_domain_review` | 통계는 강한데 **도메인 설명이 없음** | "통계상 유력하나 검토 필요"로 보고 |
| `candidate_weak_signal` | 도메인 지지 + 통계 1개만 | 참고 수준 |
| `candidate_nonlinear_only` | 단조 검정은 실패, **U자형에서만** 잡힘 | 적정구간 이탈 관점으로 해석 |
| **`shared_cause_with_*`** | 두 결함을 **모두 유발하는 공통 원인** (pure에서 다변량 신호 유지) | 공통 원인으로 보고 |
| **`contaminated_by_*`** | 다른 결함 동시발생 때문에 생긴 **가짜 신호** | **보고하면 안 됨** |
| `insufficient_evidence` | 근거 부족 | 무시 |

### `db_02_relationships.csv` — 관계 엣지 (그래프)

**FDC → Response → Defect** 3층 그래프의 간선입니다. NetworkX로 바로 로드 가능합니다.

| relation | 의미 | 예 |
|---|---|---|
| `drives` | FDC가 Response를 만든다 | `Laser_Power` → `Kerf_Width_Profile` |
| `monitors` | Response가 Defect를 예고한다 | `Kerf_Width_Profile` → `Chipping` |
| `causes` | FDC가 Defect를 유발한다 | `Vibration` → `Micro_Crack` |
| `co_occurs` | 두 결함이 함께 발생 | `Chipping` ↔ `Micro_Crack` |

**Root Cause 추적 방법**: Defect에서 역방향으로 타고 올라가면 조치 가능한 FDC가 나옵니다.
```
Micro_Crack ←(monitors) Surface_Roughness ←(drives) Vibration
                                                      ↑ 여기가 조치 지점
```

### `db_03_thresholds.csv` — 위험선

Jun님의 **C유형 방식**(결정트리 스텀프)으로 구한 경계값입니다.

| 컬럼 | 설명 |
|---|---|
| `threshold_z` | z-score 기준 경계 (조건 무관하게 사용 가능) |
| `threshold_raw_approx` | 원단위 환산값 (참고용) |
| `risky_direction` | `low_is_risky` / `high_is_risky` |
| `defect_rate_below/above` | 경계 아래/위 불량률(%) |
| `risk_ratio` | 위험 구간이 안전 구간의 몇 배인가 |

> ⚠️ 이건 **공식 SPEC이 아니라 데이터 기반 통계 경보선**입니다.

### `db_04_domain_knowledge.csv` — 공정 도메인 지식

| kind | 내용 |
|---|---|
| `defect_mechanism` | Chipping/Micro_Crack이 **왜, 어느 단계에서** 생기는가 |
| `process_stage` | HBM DP 4단계 설명 |
| `column_stage_mapping` | 컬럼 → 공정 단계 매핑 (+확신도) |
| `mentor_feedback` | 멘토 지시사항 (확정 / 재확인 대기) |

#### ⚠️ `evidence_type` — 확정 사실과 추론을 절대 섞지 않습니다

**Agent는 이 컬럼을 반드시 확인해야 합니다.** 추론을 확정 사실처럼 보고하면 안 됩니다.

| evidence_type | reliability | 뜻 | Agent 사용법 |
|---|---|---|---|
| **`현업_확정`** | 확정 | 현업/담당자가 명시적으로 확인해준 사실 | 근거로 인용 가능 |
| **`멘토_확정`** | 확정 | 멘토 피드백으로 확정된 사항 | 근거로 인용 가능 |
| **`팀문서`** | 확정 | HealthIndex 설계서·회의록 명시 내용 | 근거로 인용 가능 |
| **`데이터_실증`** | 검증됨 | 이 분석의 데이터로 직접 검증 (수치 병기) | 수치와 함께 인용 |
| **`작성자_추론`** | **미검증(추론)** | 일반 공정 물리에서 도출한 해석 | **"추정"으로만 표현. 사실로 인용 금지** |
| `멘토_미확정` | 재확인 대기 | 멘토가 시사했으나 확정 안 됨 | 결론에 반영 금지 |

**현재 분포**(총 77행): 팀문서 24 · 멘토_확정 15 · **작성자_추론 14** · 현업_확정 10 · 멘토_미확정 9 · 데이터_실증 3 · 기타 2

#### 이 구분이 왜 중요한가 — 실제 사례

`Micro_Crack`의 그루빙 제외 결정은 세 개의 서로 다른 근거로 기록돼 있습니다:

| 근거 | 내용 |
|---|---|
| `현업_확정` | "Micro_Crack은 레이저 그루빙 공정의 문제가 아니다" |
| `데이터_실증` | 그루빙 변수는 Chipping 동시발생 행에서만 신호가 나오고 제거 시 0으로 소멸 |
| **`작성자_추론`** | "레이저 HAZ는 scribe lane에 국한되고 블레이드가 제거하므로" ← **미검증** |

**추론이 틀려도 앞의 두 근거는 영향받지 않습니다.** 그래서 분석 결과(유효인자·SHAP·위험선)를
다시 돌릴 필요가 없습니다 — 결과는 추론 위에 서 있지 않기 때문입니다.

### `db_05_binning.csv` — 구간별 불량률

멘토 지시("임계값성 패턴은 선형 상관으로 안 잡힘")에 따른 구간화 분석.

`lift_vs_overall`이 **1보다 크면 그 구간이 평균보다 위험**합니다.

### `db_06_shap_global.csv` — SHAP 전역 중요도 (XGBoost + TreeSHAP)

기존 방법(통계검정 + permutation importance)을 **대체하지 않고 3번째 방법으로 병기**합니다.

#### ⭐ 모델을 2개로 나눈 이유 (가장 중요한 설계)

이 데이터는 다중공선성이 심합니다 (`Laser_Power` ↔ `Kerf_Width_Profile` r = **-0.58**).
SHAP은 상관 높은 변수끼리 기여도를 나눠 갖기 때문에, **하나의 모델로 돌리면
하류 측정값이 상류 원인의 공을 가로챕니다.**

| 모델 | 피처 | 답하는 질문 |
|---|---|---|
| **`A_cause_FDConly`** | **FDC만** (Response 제외) | "어느 손잡이를 돌려야 하나?" → **원인** |
| `B_monitor_full` | FDC + Response 전체 | "뭘 모니터링해야 하나?" → **감시지표** |

**실제로 이 함정이 확인됐습니다** (Chipping):

| 인자 | 모델 A \|SHAP\| | 모델 B \|SHAP\| | 변화 |
|---|---|---|---|
| `Head_Temp` | **1.979** | 0.150 | **1/13로 급락** |
| `Laser_Power` | **1.180** | 0.128 | **1/9로 급락** |
| `Kerf_Width_Profile` | (제외) | **6.142** | — |

한 모델로만 돌렸다면 **"Chipping 원인 = 절단 폭"**이라는 실행 불가능한 결론이 나왔을 것입니다.

| 컬럼 | 설명 |
|---|---|
| `model` | `A_cause_FDConly` / `B_monitor_full` — **반드시 구분해서 읽을 것** |
| `mean_abs_shap` | 평균 절대 SHAP = 전역 중요도 |
| `mean_signed_shap` | 평균 부호 SHAP = 전반적 방향 |
| `shap_direction` | `high_is_risky` / `low_is_risky` / `nonlinear_or_none` |
| `model_roc_auc`, `model_pr_auc` | 해당 모델 성능 |

### `db_07_shap_local.csv` — 개별 건 설명 ⭐

**⑤ Root Cause Analyzer를 가능하게 하는 파일.** 전역 중요도로는 답할 수 없는
**"이 LOT은 왜?"**에 답합니다.

실제 예시 (Chipping 위험 1위 케이스):

| Lot_ID | 장비 | 예측위험 | 실제 | 기여인자 | SHAP | z-score | 원단위 |
|---|---|---|---|---|---|---|---|
| LOT003142 | DP02 | 0.979 | 불량✓ | `Head_Temp` | +0.872 | **+5.07** | 43.717 |
| | | | | `Power_Efficiency` | +0.858 | **-14.69** | 92.559 |
| | | | | `Laser_Power` | +0.446 | **-7.20** | 17.869 |

→ Agent는 이렇게 답할 수 있습니다:
> "LOT003142(DP02)는 위험도 0.979입니다. **헤드 온도가 정상 대비 5.1칸 높고**,
> **파워 효율이 14.7칸 낮으며**, 레이저 출력도 7.2칸 낮습니다.
> low-k가 충분히 승화되지 못해 블레이드가 잔류물을 타격했을 가능성이 높습니다."

| 컬럼 | 설명 |
|---|---|
| `case_rank` | 예측 위험도 상위 순번 (1~5) |
| `Lot_ID`, `Strip_ID`, `Machine_ID` | 추적 키 |
| `predicted_risk` | 모델 예측 확률 |
| `actual_defect` | 실제 불량 여부 (검증용) |
| `contrib_rank`, `factor`, `shap_value` | 기여도 순위와 값 |
| `factor_zscore`, `factor_raw` | 그 인자의 실제 값 (조건 대비 / 원단위) |
| `interpretation` | `위험을 높임` / `위험을 낮춤` |

### `db_08_method_agreement.csv` — 3방법 순위 대조

김시우 `pipeline/README.md`가 Goal2에 요구한
**"여러 방법에서 공통으로 상위권인 인자만 유효인자로 제출"** 원칙의 근거 자료입니다.

| 방법 | 컬럼 |
|---|---|
| ① 통계 검정 (Cliff's delta) | `rank_statistic` |
| ② RandomForest permutation | `rank_permutation` |
| ③ XGBoost SHAP | `rank_shap` |

`agreement` = `3방법 모두 상위` / `2방법 상위` / `1방법만 상위` / `모두 하위`

**3방법 모두 top10 통과 항목:**

| 대상 | 인자 |
|---|---|
| Chipping | `Head_Temp`, `Laser_Power`, `Power_Efficiency`, `Laser_Cleaning_Demand`, `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf` |
| Micro_Crack | **`Vibration`**, `Surface_Roughness`, `CLN_Flow`, `Package_Size_Asymmetry` |

> 💡 `Vibration`은 단변량 검정에서 delta 0.124로 기준(0.2) 미달이라
> `db_01`에서 `shared_cause`로만 분류됐지만, **SHAP에서 Micro_Crack 원인 1위(0.255)**이고
> 3방법 모두 통과했습니다. **`db_08`을 함께 보면 등급이 올라갑니다.**

### `db_00_metadata.json` — 실행 정보 및 한계

**Agent는 보고 전에 반드시 `known_limitations`를 확인해야 합니다.**
`shap_layer` 키에 XGBoost/SHAP 설정이 별도로 기록돼 있습니다.

---

## 방법론 요약

| 단계 | 방법 | 출처 |
|---|---|---|
| 전처리 | OPCOND 층 OK-baseline median/MAD 강건 z-score | 김시우 `pipeline/` (d39bbff) |
| 통계 ① | Mann-Whitney U + BH-FDR + Cliff's delta (≥0.2) | Jun Goal2 |
| 통계 ② | RandomForest permutation importance (top-10) | Jun Goal2 |
| 비선형 | \|z편차\| 기준 검정 (U자형 탐지) | 멘토 지시 |
| 위험선 | DecisionTree stump (depth=1) | Jun C유형 |
| 오염검증 | primary / broad / **pure** 삼중 라벨 대조 | 본인 확장 |
| 통계 ③ | **XGBoost + TreeSHAP** (모델 A/B 분리) | 본인 아키텍처 ③ 설계 |

**미사용**: 전성재 브랜치 방법론(L1 로지스틱 / HistGradientBoosting / Machine 통제 다변량)

> **SHAP 구현 참고**: `shap 0.49` ↔ `xgboost 3.2` 버전 비호환(base_score 파싱 오류)이 있어
> **XGBoost 내장 TreeSHAP**(`booster.predict(pred_contribs=True)`)을 사용했습니다.
> `shap.TreeExplainer`와 **동일한 알고리즘·동일한 값**입니다(둘 다 근사가 아닌 정확해).

---

## 핵심 설계 결정 3가지

### 1. Response는 "원인"이 아니라 "감시지표"
절단 폭이나 표면 거칠기는 **조절할 수 있는 값이 아닙니다.** 레이저·블레이드 설정의 결과죠.
그래서 `role` 컬럼으로 명확히 구분했습니다 — Agent가 "이걸 조치하세요"라고 잘못 안내하지 않도록.

### 2. `pure` 라벨로 오염 제거
Micro_Crack의 **57.7%가 Chipping과 동시발생**합니다. 그냥 분석하면 Chipping 원인이 섞여 들어와요.
`Chipping==0`인 행만 쓴 `pure` 라벨을 만들어, broad에서만 보이고 pure에서 사라지는 신호는
**`contaminated_by_*`로 판정**했습니다.

### 3. 현업 도메인 제약을 코드에 명시
**"Micro_Crack은 레이저 그루빙 문제가 아니다"** — 이 지식에 따라 그루빙 단계 컬럼을
Micro_Crack 후보에서 제외했습니다. (`is_laser_grooving` 컬럼으로 추적 가능)

물리적 근거: 레이저 HAZ는 scribe lane 안에 국한되고, **그 자리는 블레이드가 지나가며 제거**됩니다.
미세균열은 블레이드 절삭 응력·진동에 의한 **기계적 파괴**입니다.

---

## 데이터

| | 원본 | r1 (멘토 신규) |
|---|---|---|
| 행 수 | 100,000 | 100,000 |
| Chipping | 4건 | 24,171건 |
| Micro_Crack | 41건 | 15,372건 |

**통합 근거**: `Lot_ID+Strip_ID` 키가 8.6%만 겹침 → 독립 표본
**원본만으로는 분석 불가** (Chipping 4건). r1이 있어야 통계가 성립합니다.

---

## 재생성

```bash
python agent_db/build_relationship_db.py
```

김시우님 `pipeline/` 규약이 바뀌면 스크립트 상단 config 블록을 동기화한 뒤 재실행하세요.
