# 팀 통합 Relationship DB — 4개 defect

작성 JHdaimma · 기준일 2026-08-05

재현 — **순서대로** 실행 (저장소 루트에서):
```bash
python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_tier_table.py"
python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/check_injected_scenarios.py"
python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/compare_spec_vs_data_threshold.py"
python "26.08.05_Goal2_통합_Relationship_DB_JHdaimma/build_integrated_db.py"
```

---

## 🔒 절대 바꾸면 안 되는 것

main의 `26.08.01_Goal_AI_Agent_Prototype_김시우/agent.py`가 이 파일을 읽습니다.

```python
REL_DB = HERE.parent / "26.08.05_Goal2_통합_Relationship_DB_JHdaimma"
with open(REL_DB / "agent_cause_factors.json") as f:
    CAUSE_FACTORS = json.load(f)["cause_factors"]
```

| 고정 | 값 |
|---|---|
| 폴더명 | `26.08.05_Goal2_통합_Relationship_DB_JHdaimma` |
| 파일명 | `agent_cause_factors.json` |
| 최상위 키 | `cause_factors` |
| 하위 키 | `defects` · `owner` · `direction` · `mechanism` |

**하나라도 바꾸면 main의 Agent가 즉시 깨집니다.**

## 🔗 추세분석 담당(김시우님)과의 인터페이스

| 파일 | 내가 채움 | 추세팀이 채움 |
|---|---|---|
| `rel_30_trend_interface.csv` | 목표선(`target_threshold_raw`), 방향, 정상/위험 범위, 위험비 | `current_slope_per_day`, `days_to_threshold`, `trend_status` |
| `rel_28_vibration_alarm.csv` | 상하한 후보(p99/p99.9), defect 연결, 분포 | `trend_window_days`, `trend_slope_threshold`, `spec_breach_rule` |

> **`threshold_source_dataset`을 꼭 보셔야 합니다.**
> `r1 주도`면 **정상 운전에서는 그 선에 도달하지 않을 수 있습니다.**

> **방침: 걸러내지 않습니다.** 확신이 낮은 것도 `status`/`confidence`/`caution`을 달아 전부 싣습니다.
> Agent가 무엇을 말하면 안 되는지는 **필드로 판단**하게 합니다.

---

## 📁 파일 구성

### Agent가 읽는 것

| 파일 | |
|---|---|
| **`agent_cause_factors.json`** | 🔒 **경로·이름 고정** — main의 `agent.py`가 읽음 |

### 산출물

| 파일 | 내용 |
|---|---|
| **`rel_20_tier_table.csv`** | **티어표 11행 × 56열** ← 중심 |
| `rel_28_vibration_alarm.csv` | **Vibration 별도 알람 영역** (티어표 밖) |
| `rel_29_ng_code_summary.csv` | NG_Code 요약 (20만행) |
| `rel_30_trend_interface.csv` | **추세팀 인터페이스** |
| `rel_26_scenario_injection_check.csv` | 검정 가능성 (39행) |
| `rel_27_spec_vs_data_threshold.csv` | 규격 간극 (3행) |
| `rel_14` · `rel_15` | 냉각·레이저노후 경향 (근거) |

### 문서

`TIER_기준.md` (판정 기준) · `결정_대기_사항.md` (미결 16건) · `규격과_실제불량_간극.md`

### 📦 `_history/` — 1세대, **사용 안 함**

도메인 게이트 적용 **이전** 산출물 17개를 이력으로 보관합니다.
`rel_00`~`rel_13` + 구 스크립트 3개.

> 🔴 **`_history/build_agent_payload.py`는 절대 실행하지 마세요.**
> 상위 폴더의 `agent_cause_factors.json`을 **1세대 내용으로 덮어씁니다.**

자세한 내용은 [_history/README.md](_history/README.md) 참조.

### 현재 티어 분포 (`rel_20`) — 확정 도메인 11건

| 티어 | 건수 | 인자 |
|---|---|---|
| **T1 즉시조치** | **5** | Chipping `Power_Efficiency` `Laser_Power` `Head_Temp` · Remain_Coat `CLN_Flow` `CLN_Pressure`(급락알람) |
| T2 조건부조치 | 2 | Chipping `Cooling_Flow` · Particle `CLN_Flow` |
| T3 감시 | 1 | Micro_Crack `Cooling_Flow` |
| T4 판단보류 | 2 | Micro_Crack `Cooling_Water_Temp` · Particle `CLN_Pressure` — 둘 다 도메인과 데이터 방향 반대 |
| M1 감시지표 | 1 | Particle `Surface_Roughness` |

> 🔧 **`CLN_Pressure` 방향 정정** (2026-08-06): `증가 → Particle 증가` → **`증가 → Particle 감소`**.
> 이로써 Remain_Coat와 **같은 방향**이 되어 **트레이드오프가 해소**됐습니다 (압력을 올리면 둘 다 개선).
> 대신 실측 `delta +0.012`가 도메인 기대(음수)와 반대라 **T3 → T4**로 내려갔습니다.

> 🔔 **`Vibration`은 티어표에서 제외했습니다** (2026-08-06).
> 유효인자(원인) 트랙이 아니라 **별도 알람 트랙(`rel_28_vibration_alarm.csv`)**으로 운영합니다 —
> 추세 상승과 상하한 급이탈만 감시해 알람을 주고 **조치 지시는 하지 않습니다.**

### `rel_28` — Vibration 별도 영역

| | |
|---|---|
| 공식 스펙 | **없음** (멘토 `spec.py` 10개 변수에 미포함) → 상하한을 데이터에서 제시 |
| 상한 후보 | p99 **0.2609** · p99.9 **0.2841** (원본 p99 0.2066 / r1 p99 0.2687) |
| Chipping | p99 초과 구간 불량률 **30.05%** (전체 6.23%, **4.82배**) ✅ |
| **Micro_Crack** | p99 초과 구간 불량률 **0.95%** (전체 2.46%, **0.39배**) ⚠️ **상한 초과가 예측 못 함** |
| 추세 기준 | **빈칸** — 추세분석 담당이 채움 |

> ⚠️ **상한 알람은 Chipping에만 연결하고, Micro_Crack에는 붙이면 안 됩니다.**
> `Vibration` 상한을 넘은 구간의 Micro_Crack 발생률이 오히려 **평균보다 낮습니다.**
> Micro_Crack 쪽은 **추세**로만 봐야 할 가능성이 큽니다.

### `rel_29` — NG_Code 요약 (20만행)

| 구분 | NG_Code | 건수 | 비율 |
|---|---|---|---|
| OK | `OK` | 149,673 | **74.837%** |
| Chipping | `CHIP` | 24,175 | 12.088% |
| Particle | `PARTICLE` | 11,296 | 5.648% |
| Remain_Coat | `REM_COAT` | 9,266 | 4.633% |
| Micro_Crack | `CRACK` | 4,921 | 2.460% |
| (기타) | `BURN` | 608 | 0.304% |
| (기타) | `LASER` | 61 | 0.030% |
| **합계** | | **200,000** | 100% |

**SOP 칸은 비어 있습니다** — `sop_status = "SOP 미수령 — 멘토 제공 대기"`

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

## 티어표 (`rel_12_tiers.csv`)

**원인 트랙과 감시지표 트랙을 절대 한 줄로 세우지 않습니다.**
섞으면 `Groove_Depth`(측정값)가 상위 티어에 올라가고 Agent가 "조치하라"고 말하게 됩니다.

### 원인 트랙 — 조치 지시 가능

| Tier | 의미 | 인자 |
|---|---|---|
| **C1** | 실행 준비 완료 (2개 방법론 일치 + 재현) | Chipping `Power_Efficiency` `Head_Temp` `Laser_Power` `Vibration` |
| **C3** | 관찰 (대조 불일치 + 재현 안 됨) | Chipping `Laser_Centering_Position` · **Particle `Vibration`** ⚠️ · Remain_Coat `CLN_Pressure` |

### 감시지표 트랙 — 경보 전용

| Tier | 의미 | 인자 |
|---|---|---|
| **M1** | 경보 가능 | Chipping `Kerf_Width_Profile` |
| **M2** | 경보 가능하나 단서 필요 | `Bottom_Kerf` `Top_Kerf` `Laser_Cleaning_Demand` `Groove_Depth` `Package_Size_Asymmetry` |
| **M3** | 결과 공변 — 사후 탐지만 | `Surface_Roughness` ×3 defect |

### 후보 — 원인이라고 답하면 안 됨
**P1** 15건 (한쪽 방법만 통과) · **P2** 13건 (도메인 근거 미확인)

---

## 🔧 김시우님 Goal5 반영 필요 (`rel_07_health_index_link.csv`)

현재 `health_index_data.json`의 `cause_factors` 11개 중 **6건을 고쳐야 합니다.**

| 조치 | 건수 | 대상 |
|---|---|---|
| **삭제** | 2 | Micro_Crack `Vibration` `Cooling_Flow` — **Agent가 지금 원인이라고 답하고 있음** |
| **역할 변경** | 4 | Chipping `Kerf_Width_Profile` `Top_Kerf` `Bottom_Kerf` `Groove_Depth` → **감시지표. SOP 대상 제외** |
| 유지 | 6 | Chipping 4개 + Particle `Vibration` + Remain_Coat `CLN_Pressure` |
| 추가 | 6 | Chipping `Vibration` 외 감시지표 5개 |

### 낡은 SOP 4건 (`rel_06_sop_draft.csv`)

| defect / 인자 | 경고 |
|---|---|
| Micro_Crack `Vibration` | **판정 강등 — 사용 중지 권고** |
| Chipping `Kerf_Width_Profile` | 역할 변경 — 조치 SOP → 경보 문구 |
| Micro_Crack `Surface_Roughness` | 위와 같음 |
| Particle `Surface_Roughness` | 위와 같음 |

---

## 파일

### 판정 (`build_unified_relationship_db.py`)

| 파일 | 내용 | 행 |
|---|---|---|
| `rel_00_metadata.json` | 출처·한계·Agent 규칙·멘토 질문 | — |
| `rel_01_factors.csv` | **통합 판정** (4 defect × 인자) | 143 |
| `rel_02_relationships.csv` | 관계 그래프 (causes / monitors / co_varies_with) | 31 |
| `rel_03_disputes.csv` | 교차대조 불일치 + 사유 | 9 |
| `rel_04_domain_knowledge.csv` | 도메인 지식 (확정/추정 등급 포함) | 82 |

### Agent 출력용 (`build_full_db_extension.py`)

| 파일 | 내용 | 행 |
|---|---|---|
| `rel_05_thresholds.csv` | **위험 경계값 — 4개 defect 전부.** `usable_for_alert` 플래그 | 156 |
| `rel_06_sop_draft.csv` | **SOP 초안** (Jun Goal6) + 낡음 경고 | 10 |
| `rel_07_health_index_link.csv` | **Goal5 연결표** + 필요 조치 | 18 |
| `rel_08_binning.csv` | 구간별 불량률 — "이 값이면 몇 %" | 110 |
| `rel_09_shap_global.csv` | SHAP 전역 — **설명 전용** | 100 |
| `rel_10_shap_local.csv` | SHAP 개별 건 — "이 LOT은 왜 위험한가" | 50 |
| `rel_11_method_agreement.csv` | 3방법 순위 대조 | 100 |
| `rel_12_tiers.csv` | **티어표** — 원인/감시 트랙 분리 | 44 |
| `rel_13_vibration_entanglement.csv` | daeho Goal3 — Vibration 얽힘 구조 | 6 |

### Agent 입력 (`build_agent_payload.py`)

| 파일 | 내용 |
|---|---|
| `agent_cause_factors.json` | **위 전부를 하나로 묶은 Agent 입력.** `cause_factors` 6 / `monitor_factors` 7 / `thresholds` 30 / `sop_draft` 10 / `health_index_actions` 18 / `disputes` 9 / `agent_rules` 5 / `tier_legend` |

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
