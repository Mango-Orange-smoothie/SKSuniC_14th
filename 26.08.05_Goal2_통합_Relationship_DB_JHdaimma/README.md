# 팀 통합 Relationship DB — 4개 defect

작성 JHdaimma · 기준일 2026-08-05
재현 `python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_unified_relationship_db.py"`

각 담당자가 따로 낸 유효인자 판정을 **하나의 스키마**로 합쳤습니다.
AI Agent가 **원인(조치 가능) / 감시지표(관찰만) / 불량결과**를 구분해 답하기 위한 기반입니다.

---

## 출처 — 각 브랜치 최신 (2026-08-05)

| defect | 담당 | 출처 |
|---|---|---|
| Chipping | JHdaimma | `26.08.01_.../agent_db/db_01_factors.csv` |
| Micro_Crack | JHdaimma | 위와 동일 |
| **Particle** | **daeho** | `origin/daeho 26.08.05_.../out/04_particle_influence_factors_final.csv` |
| **Remain_Coat** | **전성재** | `origin/Jun .../07_remain_coat_unified_verdict.csv` + `origin/전성재 REM_COAT_유효인자_정리.md` 16절 |
| 4종 교차대조 | Jun | `origin/Jun 26.08.01_2229_.../07_*_unified_verdict.csv` |

---

## 설계 원칙 3가지

### ① 담당자 판정을 덮어쓰지 않는다

각 defect의 담당자가 그 defect의 권위입니다. Jun 통합본은 **같은 데이터를 다른 방법으로 본 대조군**입니다.
어긋나면 담당자 결론을 유지하되 `confidence`를 낮추고 `rel_03_disputes.csv`에 사유를 남깁니다.

| `cross_check` | 의미 | `confidence` |
|---|---|---|
| 일치 | 담당자·Jun 둘 다 같은 결론 | 높음(2개 방법론 일치) |
| 불일치 | 확정 여부가 갈림 | 중간(rel_03 참조) |
| 담당자_단독 | 대조본에 해당 행 없음 | 중간(대조본 없음) |

### ② 역할은 통계가 아니라 컬럼 계층이 정한다

| 계층 | 역할 | Agent 동작 |
|---|---|---|
| FDC | **원인(조치가능)** | SOP 생성 가능 |
| Response | **감시지표(관찰만)** | 경보만. **조치 지시 금지** |
| Response + 결과공변 검증됨 | **감시지표(결과공변·사후)** | 사후 탐지만. 예측 불가 |
| Defect | **불량결과** | — |

`actionable=True`인 인자에만 조치를 지시합니다.

### ③ 도메인 지지는 '확정' 근거일 때만 부여한다

작성자 추론은 지지가 아닙니다. (Micro_Crack/Vibration 오판정의 원인)

---

## 결과

| defect | 확정 원인 | 확정 감시지표 | 후보 | Agent가 조치 지시 가능? |
|---|---|---|---|---|
| **Chipping** | **5** | 7 | 5 | ✅ |
| **Micro_Crack** | **0** | 1 | 1 | ❌ **원인 없음으로 답해야 함** |
| **Particle** | **1** ⚠️ | 1 | 8 | ⚠️ 단서 필요 |
| **Remain_Coat** | **1** | 0 | 1 | ✅ 단, 사전예측 금지 |

### Chipping — 확정 원인 5개 (유일하게 조치 지시가 가능한 defect)

| 인자 | delta(pure) | 대조 |
|---|---|---|
| `Power_Efficiency` | −0.899 | 일치 |
| `Head_Temp` | +0.887 | 일치 |
| `Laser_Power` | −0.872 | 일치 |
| `Vibration` | +0.844 | 일치 |
| `Laser_Centering_Position` | +0.607 | ⚠️ 불일치 |

감시지표 7개: `Kerf_Width_Profile` `Bottom_Kerf` `Top_Kerf` `Laser_Cleaning_Demand` `Groove_Depth` `Package_Size_Asymmetry` `Surface_Roughness`

### Micro_Crack — 확정 원인 **0개**

이전 DB에 있던 `Vibration`·`Cooling_Flow`를 **강등했습니다.**

| 인자 | 강등 사유 |
|---|---|
| `Vibration` | 도메인 지지 철회 — 멘토의 *"진동은 설비 열화의 대표 신호"*를 작성자가 *"진동 → 미세균열"* 근거로 확대 해석. 단변량 통과도 broad 라벨에만 의존(broad +0.565 → pure **+0.124**). Jun 통합본도 `not_reproduced` |
| `Cooling_Flow` | pure 라벨에서 \|delta\| 0.018로 붕괴. 멘토 미확정 컬럼 |

> **표본 부족이 아니라 변수 누락입니다.** r1에서 15,372건을 확보했는데도 모델 AUC 0.578(동전던지기 0.5)입니다.
> **다이싱 단계를 나타내는 컬럼이 데이터에 없습니다.**

### Particle — ⚠️ 자동 점검에 걸렸습니다

daeho님이 `Vibration`을 확정 원인으로 판정했는데, **엄격 라벨에서 팀 기준에 못 미칩니다.**

```
Particle / Vibration     broad(넓은 라벨) +0.317   →   primary(엄격) +0.087
                                                       팀 기준 0.2 미달
```

**제가 Micro_Crack에서 저지른 것과 정확히 같은 패턴입니다.**
넓은 라벨에는 다른 defect가 섞여 있어서, 다른 defect의 신호를 빌려올 수 있습니다.

Jun 통합본도 같은 인자를 `Tier2d(관찰만)`로 봤습니다. **회의 안건으로 올립니다.**

### Remain_Coat — 확정 원인 1개 + 구조적 한계

| 인자 | 역할 |
|---|---|
| `CLN_Pressure` | 원인(조치가능) — 스트립별 **실시간 급락 알람** |
| `CLN_Flow` | 원인이지만 **DP04 한정** (Goal1 매개분석) |
| `Coating_Thickness` | **분류보류** — 측정 시점 미확인, 현업 확인 전까지 어느 분류에도 넣지 말 것 |

> **Remain_Coat에는 감시지표가 원리적으로 존재하지 않습니다.**
> 후보 39개 전수조사에서 "서서히 나빠지다 미리 잡히는" 인자가 하나도 없었습니다(전성재 검증9·11).
> **즉시성 현상**이라 사전 감시가 불가능합니다 → **Agent는 이 defect에 "며칠 뒤 발생" 예측을 하면 안 됩니다.**

---

## 교차대조 불일치 9건

### 판정 충돌 4건 — 팀 회의 안건

| defect / 인자 | 담당자 | Jun | 원인 |
|---|---|---|---|
| **Particle / `Vibration`** | daeho 확정 | Tier2d 관찰만 | **비교군 정의 차이.** daeho r1 비교군의 38.1%가 불량. r1 Vibration이 비교군에 따라 −0.024 ~ +0.289로 갈림 |
| Remain_Coat / `CLN_Pressure` | 전성재 확정 | Tier2c | 방향은 일치, 크기가 데이터셋 의존(원본 −0.529 vs r1 −0.136) |
| Chipping / `Laser_Centering_Position` | JHdaimma 확정 | Tier2d | 원본 Chipping이 4건뿐이라 재현성 판정 자체가 불안정 |
| Chipping / `Groove_Depth` | JHdaimma 확정 | Tier3 약한신호 | Jun 쪽 n_methods=1. `Laser_Power`와 정보 중복 여부 확인 필요 |

### 도메인 미확인 5건 — 멘토 질문 1개로 해소 가능

`Bottom_Kerf` `Top_Kerf` `Laser_Cleaning_Demand` `Package_Size_Asymmetry` `Surface_Roughness`

**통계 결과는 양쪽이 같습니다.** Jun 통합본이 판단을 보류한 이유는 이 컬럼들이
**팀 HealthIndex 원안 문서에 설명이 없어서**입니다. 멘토에게 *"이 컬럼이 무엇을 재는 값인가"*만 확인받으면 끝납니다.

---

## 파일

| 파일 | 내용 | 행 |
|---|---|---|
| `rel_00_metadata.json` | 출처·한계·Agent 규칙·멘토 질문 | — |
| `rel_01_factors.csv` | **통합 판정** (4 defect × 인자) | 143 |
| `rel_02_relationships.csv` | 관계 그래프 (causes / monitors / co_varies_with) | 31 |
| `rel_03_disputes.csv` | 교차대조 불일치 + 사유 | 9 |
| `rel_04_domain_knowledge.csv` | 도메인 지식 (확정/추정 등급 포함) | 82 |
| `rel_05_thresholds.csv` | 위험 경계값 | 16 |

### `rel_01_factors.csv` 주요 컬럼

| 컬럼 | 의미 |
|---|---|
| `role` | 원인(조치가능) / 감시지표(관찰만) / 감시지표(결과공변·사후) / 분류보류 |
| `final_status` | confirmed_cause / confirmed_monitor / candidate / needs_domain_review / rejected / insufficient |
| `actionable` | **True인 것에만 조치 지시 가능** |
| `confidence` | 높음(2개 방법론 일치) / 중간(…) |
| `cross_check` | 일치 / 불일치 / 등급차 / 담당자_단독 |
| `delta_pure` vs `delta_broad` | 엄격 라벨 vs 넓은 라벨 효과크기 — **둘이 크게 벌어지면 경고** |
| `caution` | 자동 점검 경고 |

---

## Agent가 지켜야 할 규칙 (`rel_00_metadata.json`)

1. `actionable=False`인 인자에 **조치를 지시하지 말 것.** 감시지표는 경보만.
2. `cross_check=불일치`는 **양쪽 주장을 모두 제시**하고 판단을 유보할 것.
3. **Remain_Coat에 "며칠 뒤 발생" 형태의 사전 예측을 하지 말 것** (감시지표 부재).
4. **`Surface_Roughness`를 원인으로 제시하지 말 것** (결과 공변, 선행신호 잔존율 7.5%).
5. **Micro_Crack의 확정 원인은 0건이다.** 없다고 답하고 다이싱 단계 컬럼 부재를 이유로 밝힐 것.
   억지로 후보를 제시하지 말 것.

---

## 알려진 한계

| 항목 | 내용 |
|---|---|
| Micro_Crack | 확정 원인 0건 — 변수 누락 문제(r1 단독 AUC 0.578) |
| SHAP | 판정에서 제외 — 4개 defect 과통과 24건 / 누락 1건 (`db_10_shap_false_positives.csv`) |
| **daeho Particle** | **`Focus`·`Cutting_Offset`을 포함해 실행됨.** 멘토 제외 지시 컬럼이므로 재실행 필요 |
| **pure 라벨 정의 불일치** | JHdaimma는 상대 defect만 제외, Jun/daeho는 전체 defect 제외 → **`delta_pure` 직접 비교 주의** |
| 조치 난이도표 | 없음 — 멘토 확인 필요 |

## 멘토 확인 요청

1. **Particle의 `Vibration`은 원인인가 관찰 대상인가?** (daeho 확정 vs Jun 관찰만)
2. `Surface_Roughness`는 실제 측정값인가, 형식상 컬럼인가?
3. `Vibration`을 축별/시점별로 세분화한 데이터가 있는가? (레이저/다이싱 단계 분리 목적)
4. `Coating_Thickness`는 가공 전 측정인가 후 측정인가?
5. `Bottom_Kerf` `Top_Kerf` `Laser_Cleaning_Demand` `Package_Size_Asymmetry`는 무엇을 재는 값인가?
6. 각 원인 인자의 조치 난이도·소요시간은?
