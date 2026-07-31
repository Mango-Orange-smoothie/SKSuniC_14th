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
| **`agent_db/`** | **메인 산출물** — AI Agent(③ Relationship Analyzer)용 관계 DB 6종 |
| `analysis_v2_kimsiwoo_jun/` | 김시우 전처리 + Jun 방법론 재현 분석 및 검증 |
| `Goal2_Chipping_MicroCrack_도메인지식_정리.md` | 초기 도메인 지식 정리 |

`agent_db/README.md`에 DB 스키마와 사용법이 있습니다.

---

## 방법론 (팀 규약 준수)

| 단계 | 방법 | 출처 |
|---|---|---|
| 전처리 | OPCOND 층 **OK-baseline** median/MAD 강건 z-score | 김시우 `pipeline/` (d39bbff) |
| 통계 ① | Mann-Whitney U + BH-FDR + Cliff's delta (≥0.2) | Jun Goal2 |
| 통계 ② | RandomForest(200, depth8, balanced) permutation importance | Jun Goal2 |
| 위험선 | DecisionTree stump — **Jun이 표본 부족으로 포기했던 C유형** | Jun Goal2 |
| 비선형 | \|z편차\| 검정 (U자형 탐지) | 멘토 지시 |
| 오염검증 | primary / broad / **pure** 삼중 라벨 | 본인 확장 |

**미사용**: 전성재 브랜치 방법론(L1 로지스틱 / HistGradientBoosting / Machine 통제 다변량)

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
| 원인 | `Vibration` | `shared_cause_with_Chipping` |
| 원인 | `Cooling_Flow` | `shared_cause_with_Chipping` |

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
| **블레이드 파라미터 추가 제공 가능 여부** | Chipping/Micro_Crack 둘 다 블레이드 단계 불량인데 **블레이드 정보가 데이터에 전혀 없음**. `Vibration`이 유일한 프록시 |

### 5. 멘토 지시 검증 결과 보고

| 지시 | 결과 |
|---|---|
| `Power_Efficiency` U자형 | ✅ 구간별 lift **0.01~6.97** — 단조 검정으론 못 잡는 패턴 확인 |
| `Head_Temp` 인과사슬 | ✅ `Kerf_Angle` 1위 드라이버(1.179), Kerf 3종 상위 — 가설대로 확인 |
| `Vibration` 열화 대표신호 | ✅ 두 결함 **공통 원인**으로 확인 |
| `Laser_Head_Remain_Time` 임계값성 | ❌ **lift 0.98~1.01, 신호 없음** — 합성 데이터에 수명 로직 미반영 추정 |
| `Package_Size_Asymmetry`(김시우 신규) | ✅ `Laser_Centering_Position` 하나로 **R²=0.847** — 피처 설계 타당 |

---

## ⚠️ 한계 (해석 시 주의)

1. **`Vibration`의 Micro_Crack 직접 효과는 약함** (pure delta 0.124, 기준 0.2 미달).
   트리 3위·3/4 장비 재현·`Surface_Roughness` 경로로는 살아있어 `shared_cause`로 분류했으나
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
