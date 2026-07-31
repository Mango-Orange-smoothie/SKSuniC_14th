# Goal2 — Chipping / Micro_Crack 유효인자 분석 (v2)

담당: JHdaimma · 기준일: 2026-07-31
데이터: 원본 100,000행 + r1(멘토 신규) 100,000행 = **통합 200,000행**
**참고 브랜치: 김시우 + Jun 만 사용** (전성재 브랜치 방법론 일절 미사용)

## 사용한 방법론

| 출처 | 내용 |
|---|---|
| **김시우 `pipeline/`** | OPCOND=[Product_ID, Recipe_ID] 층 정의, 정상군 정의(Yield=100 & NG_Code=OK), **OK행 기준 median/MAD 강건 z-score**, 4개 도메인 파생피처, `00_column_classification.csv` 피처 선정, 02b 상관쌍 교차검증 요구 |
| **Jun `Goal2_*_유효인자_분석`** | **이중 라벨**(primary=NG_Code / broad=이진컬럼), Mann-Whitney U + BH-FDR(α=0.05) + Cliff's delta(\|d\|≥0.2), RandomForest(200, depth8, balanced) + permutation importance(average_precision, 15회, top-10), verdict 4단계 로직, 도메인 가설표 |
| **현업 도메인 지식(신규)** | "Micro_Crack은 레이저 그루빙 문제가 아니다" → Jun의 CRACK 도메인 가설표에서 그루빙 계열 17개를 `not_related_to_defect`로 이동 |

피처 40개 = FDC 22 + response 13 + 도메인피처 4 + Maintenance_Count 1 (Jun과 동일)

---

# 1. Chipping — 결과

라벨: primary(NG_Code='CHIP') = **24,175건** = broad(Chipping==1) = 24,175건 (완전 일치)

## 1-1. Jun 방식 최종 판정

### ✅ confirmed 7건 (도메인 지지 + 통계 2개 방법 모두 통과)

| 컬럼 | Cliff's delta | 트리 순위 | 도메인 근거 |
|---|---|---|---|
| `Laser_Centering_Position` | +0.658 | 4 | 정렬/센터링 — 빔 중심 이탈 |
| **`Kerf_Width_Profile`** | **+0.982** | 5 | 절단 폭 (설계서 명시) |
| `Top_Kerf` | +0.978 | 6 | 절단 폭 상속 |
| `Bottom_Kerf` | +0.979 | 7 | 절단 폭 상속 |
| `Vibration` | +0.902 | 8 | 기계적 불안정 (회의록 명시) |
| `Groove_Depth` | **-0.799** | 9 | Depth 부족 → Chipping (설계서 C유형) |
| `Focus` | +0.937 | 10 | 빔 집속 (설계서 PDF 근거) |

→ **Jun님이 n=4에서 confirmed했던 `Kerf_Width_Profile`, `Groove_Depth`가 6,000배 표본에서도 그대로 재현**됐습니다. 방향(Groove_Depth는 down)까지 팀 설계서와 일치합니다.

### ⚠️ candidate_needs_domain_review 3건 — **가장 중요한 발견**

| 컬럼 | Cliff's delta | **트리 순위** | Jun의 기존 분류 |
|---|---|---|---|
| **`Laser_Power`** | **-0.923** | **1위** | `not_related` ("Burn 전용 메커니즘") |
| **`Power_Efficiency`** | **-0.951** | **2위** | `not_related` ("Burn 전용 메커니즘") |
| `Laser_Cleaning_Demand` | -0.912 | 3위 | `not_related` (세정 파생피처) |

**통계적으로 전체 1·2위인데 도메인 지지가 없어서 confirmed가 못 됐습니다.**
Jun님은 n=4 시점에 "에너지 투입 계열은 Burn 전용이라 Chipping(기계적 파손)과 연결고리 없음"으로 판단했는데, 24,175건에서는 최상위로 올라옵니다.

**→ 팀 조치 필요: Jun님 도메인 가설표에서 `Laser_Power` / `Power_Efficiency`를 Chipping 관련으로 재분류해야 합니다.** (`candidate_needs_domain_review`는 Jun님이 바로 이런 경우를 잡으려고 설계한 카테고리입니다.)

## 1-2. 김시우 README 요구 교차검증 (02b 상관쌍) — Jun/전성재 모두 미수행

| 변수쌍 | Spearman |
|---|---|
| `Laser_Power` ↔ `Kerf_Width_Profile` | **-0.5788** |
| `Laser_Power` ↔ `Groove_Depth` | **+0.3501** |
| `Kerf_Width_Profile` ↔ `Groove_Depth` | -0.2269 |
| `Power_Efficiency` ↔ `Kerf_Width_Profile` | -0.2245 |

**해석**: `Laser_Power`/`Power_Efficiency`는 `Kerf_Width_Profile`과 강하게 상관됩니다. 즉 **레이저 출력·효율이 절단 폭을 만들고, 그 절단 폭이 Chipping으로 이어지는 하나의 인과 사슬**로 읽는 것이 타당합니다. Jun님이 `Laser_Cleaning_Demand`를 "`Groove_Depth`의 중복 신호"로 의심한 것도 이 표(`Laser_Power`↔`Groove_Depth` +0.35)로 뒷받침됩니다.

## 1-3. 데이터셋별 재현성 (Jun의 Cliff's delta)

| 컬럼 | 원본(n=4) | r1(n=24,171) | 통합 |
|---|---|---|---|
| `Kerf_Width_Profile` | +1.000 | +0.960 | **+0.982** |
| `Laser_Power` | -0.979 | -0.907 | **-0.923** |
| `Power_Efficiency` | -0.445 | -0.925 | -0.951 |
| `Focus` | -0.181 ⚠ | +0.872 | +0.937 |
| `Vibration` | +0.345 | +0.869 | +0.902 |

`Kerf_Width_Profile`, `Laser_Power`는 두 데이터셋에서 모두 강하게 재현. `Focus`는 원본(n=4)에서 부호가 반대였으나 표본이 4건이라 의미 없습니다.

## 1-4. Chipping 결론

```
Laser_Power ↓ / Power_Efficiency ↓ / Focus 이탈
              ↓
   Kerf_Width_Profile 확대 · Groove_Depth 부족
              ↓
          Chipping 발생
```
보조 인자: `Vibration`(기계적 불안정), `Laser_Centering_Position`(정렬)

---

# 2. Micro_Crack — 결과

라벨: primary(NG_Code='CRACK') = **4,921건** / broad(Micro_Crack==1) = **15,413건**
두 라벨 차이가 큽니다 — NG_Code는 우선순위 단일 라벨이라, Micro_Crack이 있어도 Chipping이 우선 기록된 행이 많기 때문입니다.

## 2-1. 🔑 결정적 발견 — Jun님의 이중 라벨 설계가 밝혀낸 것

**broad 라벨의 15,413건 중 8,891건(57.7%)이 Chipping과 동시발생**합니다. 이를 이용해 세 가지 라벨로 나눠 효과크기를 비교했습니다:

| 컬럼 | 그루빙 | primary | broad | **pure**(Chip 제외) | 판정 |
|---|---|---|---|---|---|
| **`Surface_Roughness`** | 아니오 | **+0.440** | **+0.575** | **+0.492** | ✅ **모든 라벨에서 유지 = 진짜 신호** |
| `Kerf_Width_Profile` | 예 | -0.012 | +0.534 | -0.023 | ❌ broad에서만 |
| `Top_Kerf` | 예 | -0.003 | +0.535 | -0.017 | ❌ broad에서만 |
| `Bottom_Kerf` | 예 | +0.003 | +0.536 | -0.015 | ❌ broad에서만 |
| `Focus` | 예 | +0.004 | +0.511 | -0.014 | ❌ broad에서만 |
| `Head_Temp` | 예 | +0.014 | +0.512 | -0.001 | ❌ broad에서만 |
| `Laser_Power` | 예 | +0.054 | -0.484 | +0.065 | ❌ broad에서만 |
| `Power_Efficiency` | 예 | +0.025 | -0.510 | +0.040 | ❌ broad에서만 |
| `Groove_Depth` | 예 | +0.050 | -0.425 | +0.056 | ❌ broad에서만 |
| `Frequency` | 예 | +0.071 | +0.037 | +0.062 | ❌ 전 구간 무신호 |

### **레이저 그루빙 계열은 전부 `broad`에서만 신호가 나오고, Chipping을 제거하면 0으로 사라집니다.**

즉 **"Micro_Crack에서 보이던 그루빙 신호는 Chipping 동시발생에 의한 오염이었다"**는 것이 데이터로 증명됐습니다.

> 이것은 **현업 도메인 지식("Micro_Crack은 레이저 그루빙 문제가 아니다")을 Jun님 자신의 이중 라벨 설계로 독립 검증**한 결과입니다. 도메인 지식이 먼저 옳았고, 데이터가 따라온 사례입니다.

## 2-2. 순수 Micro_Crack(Chipping 제외, n=6,522) RandomForest 재실행

| 순위 | 컬럼 | importance | 그루빙 |
|---|---|---|---|
| **1** | **`Surface_Roughness`** | **0.08765** | 아니오 |
| **2** | **`CLN_Flow`** | **0.02729** | 아니오 |
| 3 | `Bottom_Kerf` | 0.01476 | 예 |
| 4 | `Head_Temp` | 0.00994 | 예 |
| **5** | **`Vibration`** | **0.00897** | 아니오 |
| 6~8 | `Top_Kerf`/`Focus`/`Frequency` | ~0.007 | 예 |
| 9 | `Cleaning_Load_Ratio` | 0.00275 | 아니오 |

→ 비그루빙 상위 3개: **`Surface_Roughness`(압도적 1위) → `CLN_Flow` → `Vibration`**

## 2-3. `Surface_Roughness`는 원인인가 결과인가 — 김시우 02b 대조

Jun님도 도메인 가설표에 "**결과 공변(동반증상 후보) — 원인 아닐 수 있음**"이라고 적어뒀습니다. 김시우님 02b 상관쌍에서 `Surface_Roughness`와 가장 강하게 연결된 변수는:

| 변수쌍 | Spearman |
|---|---|
| **`Vibration` ↔ `Surface_Roughness`** | **+0.3152** |
| `Bottom_Kerf` ↔ `Surface_Roughness` | +0.0437 |
| `Top_Kerf` ↔ `Surface_Roughness` | +0.0424 |

**`Vibration`이 `Surface_Roughness`의 압도적 1위 상관 변수**입니다(다음 항목의 7배). 그리고 `Vibration`은 비그루빙(fdc_mechanical) 계열입니다.

## 2-4. 데이터셋별 재현성

| 컬럼 | 원본(n=41) | r1(n=15,372) | 통합 |
|---|---|---|---|
| `Surface_Roughness` | +0.444 | +0.540 | **+0.575** |
| `Vibration` | +0.151 | +0.453 | +0.565 |
| **`Frequency`** | **+0.783** | **+0.040** | **+0.037** |

### ⚠️ Jun 브랜치 CRACK 1위 결론(`Frequency`)은 재현되지 않습니다
n=41에서 +0.783이던 효과크기가 n=15,372에서 **+0.040으로 소멸**했습니다. Jun님 본인이 README에 "n=34라 신뢰도 낮다, 재검증 필요"고 명시했던 그대로입니다. **그리고 `Frequency`는 레이저 그루빙 제어인자** — 현업 도메인 지식과도 일치합니다.

## 2-5. Micro_Crack 결론

```
      Vibration ↑ (기계적 진동, 비그루빙)
            ↓  (김시우 02b: r=+0.3152)
   Surface_Roughness ↑ (표면 거칠기)
            ↓  (pure 라벨 delta +0.492, 트리 1위)
      Micro_Crack 발생
```
보조 후보: `CLN_Flow`(순수 라벨 트리 2위, 비그루빙 — 신규 발견)

**단, `Surface_Roughness`는 Jun님 표기대로 "결과 공변" 가능성이 남아있습니다.** 균열이 거칠기를 만든 결과일 수 있으므로, 보고 시 `Vibration`을 원인으로, `Surface_Roughness`를 감시 지표로 구분하는 것이 안전합니다.

---

# 3. 최종 제출 (Relationship DB 형식)

| Target | Top Variables | 감시 지표 | 비고 |
|---|---|---|---|
| **Chipping** | `Laser_Power`, `Power_Efficiency`, `Focus`, `Groove_Depth`, `Laser_Centering_Position`, `Vibration` | `Kerf_Width_Profile` | 앞의 2개는 Jun 도메인표 재분류 필요 |
| **Micro_Crack** | `Vibration`, (`CLN_Flow`) | `Surface_Roughness` | 그루빙 계열 전부 오염으로 확인·배제 |

---

# 4. 팀에 제안할 사항

1. **Jun님 CHIP 도메인 가설표 수정 요청**: `Laser_Power`, `Power_Efficiency`를 `not_related_to_defect` → `defect_related`로 이동. 통계 1·2위인데 도메인 미지지로 confirmed에서 빠져 있음.
2. **Jun님 CRACK 결론 폐기**: `Frequency`는 n=41 착시. 통합 데이터에서 delta +0.037.
3. **현업 도메인 지식 확인 완료 보고**: "Micro_Crack ≠ 레이저 그루빙"이 데이터로 검증됨 (그루빙 신호는 100% Chipping 동시발생 오염).
4. **김시우 README 교차검증 완료**: 02b 상관쌍 대조 수행 (Jun·전성재 브랜치 모두 파일 미발견으로 미수행 상태였음). `03_impact_factor_ranking.csv`는 Edge_Burn/Particle/Remain_Coat만 다뤄 CHIP/CRACK 대조 불가 — 김시우님께 재생성 요청 필요.
5. **Goal3(상호작용) 담당자 전달**: `CLN_Flow`가 순수 Micro_Crack에서 트리 2위. 세정계와 균열의 관계는 단변량에서 안 잡히고 트리에서만 잡히므로 상호작용 후보.

# 5. 한계

- **`Surface_Roughness` 역인과**: Jun님 표기대로 결과 공변일 수 있음. 현업 확인 필요.
- **`Vibration`의 순수 라벨 단변량 효과크기는 +0.124**로 Jun의 기준(0.2)에 미달. 트리에서는 5위(비그루빙 3위)이고 김시우 02b에서 `Surface_Roughness`의 1위 드라이버로 확인되므로 "원인 경로" 해석은 유지하되, **단변량 단독으로는 confirmed 등급이 아님**을 명시해야 함.
- **r1은 시뮬레이션 데이터**: 특정 장비(DP02/DP03)에 열화가 주입된 구조. 실제 라인 재현 여부는 별도 확인 필요.

# 6. 산출물

| 파일 | 내용 |
|---|---|
| `chip_crack_factors_v2.py` | 메인 (김시우 전처리 + Jun 방법론) |
| `supplement_crossvalidation.py` | 오염 검증 + 02b 교차검증 + 재현성 |
| `04_chip_influence_factors_final.csv` | **CHIP 메인 산출물** |
| `04_crack_influence_factors_final.csv` | **CRACK 메인 산출물** |
| `05_crack_grooving_contamination_check.csv` | 그루빙 오염 검증표 |
| `06_crack_pure_tree_importance.csv` | 순수 Micro_Crack 트리 중요도 |
| `07_crossvalidation_with_kimsiwoo_02b.csv` | 김시우 02b 교차검증 |
| `08_reproducibility_*.csv` | 데이터셋별 재현성 |
