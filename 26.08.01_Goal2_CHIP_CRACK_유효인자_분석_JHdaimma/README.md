# Goal2 — Chipping / Micro_Crack 유효인자 분석

담당: **JHdaimma** · 기준일: 2026-08-01
데이터: 원본 `DP_HealthIndex_Dataset.csv` + **신규 `DP_HealthIndex_Dataset_r1.csv`** = 통합 200,000행

> 데이터 파일 2개는 용량(각 48MB) 때문에 커밋하지 않았습니다.
> 재실행하려면 저장소 루트 상위에 두 CSV를 두고 스크립트를 실행하세요.

---

## 왜 r1이 필요했나

| | 원본 | r1 | 
|---|---|---|
| Chipping | **4건** (0.004%) | **24,171건** (24.2%) |
| Micro_Crack | **41건** (0.041%) | **15,372건** (15.4%) |

Jun 브랜치가 "n=4는 패턴 탐지가 아니라 4개 사례 기록에 가깝다"고 남긴 그 문제가 r1으로 해소됐습니다.
`Lot_ID+Strip_ID` 키가 **8.6%만 중복**이라 독립 표본으로 보고 통합했습니다(`source_dataset` 컬럼으로 배치 구분).

---

## 폴더 구성

| 폴더/파일 | 내용 |
|---|---|
| **`SUMMARY.html`** | **한눈에 보기** — 결과 요약 페이지 (브라우저로 열어보세요) |
| **`agent_db/`** | **메인 산출물** — AI Agent(③ Relationship Analyzer)용 관계 DB 9종 |
| `analysis_v2_kimsiwoo_jun/` | 김시우 전처리 + Jun 방법론 재현 분석 및 검증 |
| `Goal2_Chipping_MicroCrack_도메인지식_정리.md` | 초기 도메인 지식 정리 |

`agent_db/README.md`에 DB 스키마와 사용법이 있습니다.

> `SUMMARY.html`은 GitHub 웹에서는 소스로만 보입니다.
> 다운로드해서 브라우저로 열거나, 저장소를 클론한 뒤 파일을 더블클릭하세요.

---

## ⚠️ 근거 표기 규약 — 확정 사실과 추론을 섞지 않았습니다

`agent_db/db_04_domain_knowledge.csv`의 `evidence_type` / `reliability` 컬럼으로 구분됩니다.

| evidence_type | 뜻 | 인용 가능? |
|---|---|---|
| `현업_확정` · `멘토_확정` · `팀문서` | 확인된 사실 | ✅ 근거로 인용 가능 |
| `데이터_실증` | 이 분석으로 검증 (수치 병기) | ✅ 수치와 함께 인용 |
| **`작성자_추론`** | 일반 공정 물리에서 도출한 해석 | ❌ **미검증 — "추정"으로만 표현** |
| `멘토_미확정` | 멘토가 시사했으나 확정 안 됨 | ❌ 결론 반영 금지 |

**분포**(총 77행): 팀문서 24 · 멘토_확정 15 · **작성자_추론 14** · 현업_확정 10 · 멘토_미확정 9 · 데이터_실증 3 · 기타 2

### 이 구분이 중요한 이유 — Micro_Crack 그루빙 제외 사례

| 근거 유형 | 내용 |
|---|---|
| `현업_확정` | "Micro_Crack은 레이저 그루빙 공정의 문제가 아니다" |
| `데이터_실증` | 그루빙 변수는 Chipping 동시발생 행에서만 신호가 나오고 제거 시 0으로 소멸 |
| **`작성자_추론`** | "레이저 HAZ는 scribe lane에 국한되고 블레이드가 제거하므로" ← **미검증** |

**추론이 틀려도 앞의 두 근거는 영향받지 않습니다.** 유효인자 판정·SHAP·위험선 결과는
추론 위에 서 있지 않으므로 재분석이 필요하지 않습니다.

---

## 방법론 (팀 규약 준수)

| 단계 | 방법 | 출처 |
|---|---|---|
| 전처리 | OPCOND 층 **OK-baseline** median/MAD 강건 z-score | 김시우 `pipeline/` (d39bbff) |
| 통계 ① | Mann-Whitney U + BH-FDR + Cliff's delta (≥0.2) | Jun Goal2 |
| 통계 ② | RandomForest(200, depth8, balanced) permutation importance | Jun Goal2 |
| **통계 ③** | **XGBoost + TreeSHAP** (모델 A/B 분리) | 아키텍처 ③ 원설계 |
| 위험선 | DecisionTree stump — **Jun이 표본 부족으로 포기했던 C유형** | Jun Goal2 |
| 비선형 | \|z편차\| 검정 (U자형 탐지) | 멘토 지시 |
| 오염검증 | primary / broad / **pure** 삼중 라벨 | 본인 확장 |

**미사용**: 전성재 브랜치 방법론(L1 로지스틱 / HistGradientBoosting / Machine 통제 다변량)

**세 방법은 서로를 대체하지 않고 병기합니다.** 김시우 `pipeline/README.md`의
"여러 방법에서 공통으로 상위권인 인자만 유효인자로 제출" 원칙에 따른 것이며,
대조 결과는 `agent_db/db_08_method_agreement.csv`에 있습니다.

### ⭐ SHAP 모델을 2개로 나눈 이유 (핵심 설계)

이 데이터는 다중공선성이 심합니다(`Laser_Power` ↔ `Kerf_Width_Profile` r=**-0.58**).
SHAP은 상관 높은 변수끼리 기여도를 나눠 갖기 때문에 **하나의 모델로 돌리면
하류 측정값이 상류 원인의 공을 가로챕니다.** 실제로 확인됐습니다(Chipping):

| 인자 | 모델 A(FDC만) | 모델 B(전체) | 변화 |
|---|---|---|---|
| `Head_Temp` | **1.979** | 0.150 | **1/13로 급락** |
| `Laser_Power` | **1.180** | 0.128 | **1/9로 급락** |
| `Kerf_Width_Profile` | (제외) | **6.142** | — |

한 모델로만 돌렸다면 **"Chipping 원인 = 절단 폭"**이라는 실행 불가능한 결론이 나왔을 것입니다.
→ **모델 A = 원인 규명 / 모델 B = 감시지표 선정**으로 분리했습니다.

---

## 핵심 결과

### Chipping — 원인 6개 / 감시지표 11개

```
Laser_Power ↓ / Power_Efficiency ↓ / Head_Temp ↑
        ↓
Kerf_Width_Profile 확대 · Groove_Depth 부족
        ↓
    Chipping
```

| 역할 | 인자 | 효과크기 |
|---|---|---|
| 원인 | `Power_Efficiency` | -0.899 |
| 원인 | `Head_Temp` | +0.887 |
| 원인 | `Laser_Power` | -0.872 |
| 원인 | `Vibration` | +0.844 |
| 원인 | `Laser_Centering_Position` | +0.607 |
| 감시 | `Kerf_Width_Profile` | +0.931 |
| 감시 | `Groove_Depth` | -0.750 |

**공정 해석(HBM DP)**: 레이저 출력·효율이 낮아 low-k가 덜 승화 → 홈이 얕고 좁음 →
블레이드가 잔류 low-k를 타격 → Chipping.

### Micro_Crack — 그루빙 계열 배제 후

```
Vibration ↑ ──drives(0.424)──> Surface_Roughness ↑ ──(0.492)──> Micro_Crack
```

| 역할 | 인자 | 판정 |
|---|---|---|
| 감시 | `Surface_Roughness` | **confirmed** (4개 장비 전부 재현) |
| 원인 | `Vibration` | `shared_cause` → **SHAP 추가 후 원인 1위** |
| 원인 | `Cooling_Flow` | `shared_cause_with_Chipping` |

### 3방법 합의 결과 (`db_08_method_agreement.csv`)

통계검정 · permutation importance · SHAP **세 방법 모두 top10**을 통과한 인자:

| 대상 | 인자 |
|---|---|
| **Chipping** | `Head_Temp`, `Laser_Power`, `Power_Efficiency`, `Laser_Cleaning_Demand`, `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf` |
| **Micro_Crack** | **`Vibration`**, `Surface_Roughness`, `CLN_Flow`, `Package_Size_Asymmetry` |

**SHAP 원인 모델(A) 순위**

| Chipping | \|SHAP\| | 방향 | | Micro_Crack | \|SHAP\| | 방향 |
|---|---|---|---|---|---|---|
| `Head_Temp` | **1.979** | 높으면 위험 | | `Vibration` | **0.255** | 높으면 위험 |
| `Laser_Power` | 1.180 | 낮으면 위험 | | `CLN_Time` | 0.133 | 낮으면 위험 |
| `Power_Efficiency` | 0.842 | 낮으면 위험 | | `CLN_Flow` | 0.125 | 낮으면 위험 |
| `Laser_Centering_Position` | 0.228 | 높으면 위험 | | | | |
| `Vibration` | 0.212 | 높으면 위험 | | | | |

모델 성능: Chipping ROC-AUC **0.965**(피처 23개) / Micro_Crack **0.803**(피처 14개)
(Micro_Crack이 낮은 이유는 **다이싱 단계를 직접 나타내는 컬럼이 없기 때문으로 추정**되나 확인된 바 아님 — 요청사항 4 참고)

> 💡 **`Vibration` 등급 상향 근거**: 단변량 delta 0.124로 기준(0.2) 미달이라
> `db_01`에서는 `shared_cause`로만 분류됐으나, **SHAP에서 Micro_Crack 원인 1위(0.255)**이고
> 3방법 모두 통과했습니다. 멘토가 언급한 실제 스크랩 사고 사례와도 일치합니다.

### 개별 건 설명 (`db_07_shap_local.csv`) — ⑤ Root Cause Analyzer 연결점

전역 중요도로는 못 하는 **"이 LOT은 왜?"**에 답합니다. 실제 예시:

| Lot_ID | 장비 | 예측위험 | 실제 | 기여인자 | SHAP | z-score |
|---|---|---|---|---|---|---|
| LOT003142 | DP02 | 0.979 | 불량✓ | `Head_Temp` | +0.872 | **+5.07** |
| | | | | `Power_Efficiency` | +0.858 | **-14.69** |
| | | | | `Laser_Power` | +0.446 | **-7.20** |

---

## 🔴 팀에 요청하는 사항

### 1. Jun 브랜치 CHIP 도메인 가설표 수정 필요

`Laser_Power`, `Power_Efficiency`가 `not_related_to_defect`("Burn 전용 메커니즘")로 분류돼 있는데,
**통계 1·2위이자 `Groove_Depth`(R²=0.606)·`Kerf_Width_Profile`(R²=0.954)의 직접 드라이버**입니다.

HBM DP 공정에서 레이저 출력은 **"low-k를 다 날렸는가"를 결정하는 핵심 변수**입니다.
n=4 시점의 판단이라 재검토가 필요합니다.

### 2. Jun 브랜치 CRACK 결론(`Frequency`) 재현 안 됨

| 데이터 | 표본 | `Frequency` 효과크기 |
|---|---|---|
| 원본만 | 41건 | **+0.783** |
| 통합 | 15,413건 | **+0.037** |

Jun 브랜치 README가 스스로 경고한 대로 소표본 착시였습니다.
`Frequency`는 멘토가 레이저 변수로 확정한 그루빙 제어인자라, 현업 도메인 지식
("Micro_Crack은 레이저 그루빙 문제가 아님")과도 배치됩니다.

### 3. 김시우 README 요구 교차검증 완료

`02b_process_parameter_correlation_pairs.csv` 대조를 수행했습니다
(Jun·전성재 브랜치 모두 "파일 미발견"으로 미수행 상태였음).
→ `analysis_v2_kimsiwoo_jun/07_crossvalidation_with_kimsiwoo_02b.csv`

`03_impact_factor_ranking.csv`는 Edge_Burn/Particle/Remain_Coat만 다뤄 CHIP/CRACK 대조 불가 —
김시우님께 재생성 요청 필요.

### 4. 멘토 확인 필요 4가지

| 항목 | 왜 필요한가 |
|---|---|
| `Surface_Roughness` 실제 측정값 여부 | **Micro_Crack의 유일한 confirmed** — 무효화 시 감시지표 소멸 |
| `Edge_Burn` 최종 제외 여부 | Jun BURN 분석 전체에 영향 |
| `Bottom_Kerf` 값 중복 여부 | Chipping confirmed 항목 |
| **`Vibration` 세분화 데이터 유무** | 현재는 **장비 레벨 단일 값**이라 레이저 단계 영향인지 다이싱 단계 영향인지 구분 불가. 축별·시점별 데이터가 있으면 Micro_Crack 규명이 크게 개선됨 |
| 다이싱 단계 파라미터 유무 | 다이싱 단계를 직접 나타내는 컬럼이 데이터에 없음 |

### 5. 멘토 지시 검증 결과 보고

| 지시 | 결과 |
|---|---|
| `Power_Efficiency` U자형 | ✅ 구간별 lift **0.01~6.97** — 단조 검정으론 못 잡는 패턴 확인 |
| `Head_Temp` 인과사슬 | ✅ `Kerf_Angle` 1위 드라이버(1.179), Kerf 3종 상위 — 가설대로 확인 |
| `Vibration` 열화 대표신호 | ✅ 두 결함 **공통 원인**으로 확인 (장비 레벨 진동 — 특정 단계 아님) |
| `Laser_Head_Remain_Time` 임계값성 | ❌ **lift 0.98~1.01, 신호 없음** — 합성 데이터에 수명 로직 미반영 추정 |
| `Package_Size_Asymmetry`(김시우 신규) | ✅ `Laser_Centering_Position` 하나로 **R²=0.847** — 피처 설계 타당 |

---

## ⚠️ 한계 (해석 시 주의)

1. **`Vibration`의 Micro_Crack 직접 효과는 약함** (pure delta 0.124, 기준 0.2 미달).
   트리 3위·3/4 장비 재현·SHAP 원인 1위(0.255)로 살아있어 `shared_cause`로 분류했으나
   **`confirmed`가 아님** — 보고 시 등급 구분 필요.
2. **`Process_Time`(Micro_Crack, candidate_weak_signal)은 신뢰하지 말 것.**
   delta -0.009인데 트리 순위만으로 통과. Micro_Crack 후보가 24개뿐이라 top-10 기준이 느슨함.
3. **r1은 DP02/DP03에 열화를 주입한 시나리오 데이터.** 실제 라인 재현 여부 별도 확인 필요.
4. `Cooling_Flow`/`Cooling_Water_Temp`는 멘토가 설비-컬럼 매핑 재확인 예정 — 해석 주의.

---

## 재실행

```bash
python "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/build_relationship_db.py"
```

김시우 `pipeline/` 규약이 바뀌면 스크립트 상단 config 블록을 동기화한 뒤 재실행하세요.
`pipeline/`, `data/` 폴더는 읽기만 했고 수정하지 않았습니다.
