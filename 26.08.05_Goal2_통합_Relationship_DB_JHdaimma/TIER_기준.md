# 유효인자 티어 판정 기준

작성 JHdaimma · 2026-08-05 · 멘토 방향성 반영
산출물 `rel_20_tier_table.csv` · 재현 `build_tier_table.py`

> 멘토 요구: **"티어 나누는 기준을 엄격·근거·가시성 있게 정할 것"**
> 이 문서가 그 기준이고, `rel_20_tier_table.csv`의 모든 행에 **왜 그 티어인지(`tier_reason`)**가 함께 실립니다.

---

## 0. 후보 선정 — 확정 도메인 지식 13건만

**추정 도메인 지식은 쓰지 않습니다.** 멘토·현업이 확정한 관계만 후보로 올립니다.

| defect | 인자 | 방향 | 감시방식 |
|---|---|---|---|
| Particle | `Surface_Roughness` | 증가 → 증가 | level |
| Particle | `CLN_Flow` | 감소 → 증가 | level |
| Particle | `CLN_Pressure` | 증가 → 증가 | level |
| Remain_Coat | `CLN_Pressure` | **감소** → 증가 | **spike**(순간 급락) |
| Remain_Coat | `CLN_Flow` | 감소 → 증가 | level |
| Micro_Crack | `Cooling_Flow` | 감소 → 증가 | level |
| Micro_Crack | `Cooling_Water_Temp` | 증가 → 증가 | level |
| Chipping | `Power_Efficiency` | 감소 → 증가 | level |
| Chipping | `Laser_Power` | 감소 → 증가 | level |
| Chipping | `Head_Temp` | 증가 → 증가 | level |
| Chipping | `Cooling_Flow` | 감소 → 증가 | level |
| Chipping | `Vibration` | 증가 → 증가 | **trend**(추세·틀어짐) |
| Micro_Crack | `Vibration` | 증가 → 증가 | **trend** |

### FDC-FDC를 엮지 않습니다

멘토 지시에 따라 **인과사슬을 만들지 않습니다.**

```
❌ Cooling_Flow ↓ → Head_Temp ↑ → 센터링 이탈 → Chipping
✅ Cooling_Flow ↓ → Chipping        (1:1)
✅ Head_Temp   ↑ → Chipping        (1:1)
```

각 인자는 **defect에만 직접 연결**됩니다. 인자끼리는 연결하지 않습니다.

> ⚠️ `CLN_Pressure`는 **defect마다 방향이 반대**입니다.
> Particle은 **증가**할 때, Remain_Coat는 **감소**할 때 늘어납니다.
> 한쪽을 고치면 다른 쪽이 나빠지므로 **조치 시 반대편 영향을 반드시 병기**해야 합니다.

---

## 1. 검정 4종 — 각각의 통과 기준

모든 판정은 **pure 라벨**로 합니다.

> **pure 라벨** = 나머지 3개 defect가 동시 발생한 행을 **비교군·불량군 양쪽에서 제외**
> 다른 불량의 신호를 빌려오는 것을 막기 위함입니다.

기준선은 **OPCOND(`Product_ID` × `Recipe_ID`) 층별 정상군 median**, 산포는 **MAD × 1.4826**(강건 z-score)입니다.

### ① 방향 일치 — 가장 먼저 보는 관문

도메인이 말한 방향과 데이터의 부호가 같은가.

```
기대 "감소 → 증가"  →  Cliff's delta 가 음수여야 함
기대 "증가 → 증가"  →  Cliff's delta 가 양수여야 함
```

**어긋나면 다른 검정 결과와 무관하게 T4(판단보류)** 입니다.

### ② 통계검정

| 항목 | 내용 |
|---|---|
| 방법 | **Mann-Whitney U 양측검정** → **Cliff's delta**로 환산 |
| 다중비교 보정 | **BH-FDR** (39개 컬럼 전체를 함께 보정) |
| 통과 기준 | **`p_FDR < 0.05`** AND **`|delta| ≥ 0.2`** |

> **`0.2`의 근거**: Cliff's delta 해석 관례에서 **0.15 미만은 "무시할 수준(negligible)"** 입니다.
> 0.2는 그 구간을 막 벗어난 지점으로, **"최소한 이 정도는 넘어야 실무에서 의미가 있다"**는 선입니다.
> 물리 상수가 아니라 **합의된 기준**이며, 이 값을 바꾸면 결과가 바뀝니다(민감도는 아래 §4).

### ③ RandomForest

| 항목 | 내용 |
|---|---|
| 모델 | RandomForest (트리 200, 최대깊이 8, `class_weight=balanced`) |
| 중요도 | **순열 중요도** — 검증셋에서 한 컬럼씩 무작위 셔플 **10회**, 성능 하락폭 평균 |
| 채점 지표 | **PR-AUC**(`average_precision`) |
| 통과 기준 | **상위 25% 이내** AND **중요도 > 0** |

> **왜 PR-AUC인가**: 불량이 소수(수 %)인 불균형 데이터라 정확도·ROC-AUC는 부풀려집니다.
> 실제로 Chipping 모델은 ROC-AUC 0.965 / PR-AUC 0.571로 크게 다릅니다.
>
> **왜 고정 top-10이 아니라 상위 25%인가**: 후보 수가 defect마다 달라
> 같은 "top-10"이라도 엄격함이 다릅니다. 비율로 고정해 **잣대를 통일**했습니다.

### ④ 재현성

원본 데이터와 r1 데이터에서 **각각 따로 계산**해, 부호가 **둘 다 도메인 기대 방향**과 같아야 통과입니다.
장비별(DP01~04)로도 계산해 `|delta| ≥ 0.2`인 장비 수를 함께 싣습니다.

---

## 2. 티어 배정 규칙

### 원인 트랙 (FDC — 조치 가능)

| 티어 | 조건 | 액션 타입 |
|---|---|---|
| **T1** | 방향일치 + **통계검정 통과** + **RF 통과** + **재현성 통과** | **즉시조치** |
| **T2** | 방향일치 + 통계·RF 모두 통과했으나 **재현 실패**<br>또는 방향일치 + **2개 중 1개만** 통과 | **조건부조치** |
| **T3** | 방향일치하나 **통계·RF 모두 미달** | **감시** |
| **T4** | **방향 반대** | **판단보류** |

### 감시지표 트랙 (Response — 경보 전용)

| 티어 | 조건 | 액션 타입 |
|---|---|---|
| **M1** | 방향일치 + 통계·RF 모두 통과 + 재현 | 감시(경보) |
| **M2** | 방향일치 + 2개 중 1개 이상 통과 | 감시(경보·단서필요) |
| **M3** | 방향일치하나 둘 다 미달 | 감시(사후탐지) |

> **두 트랙을 절대 한 줄로 세우지 않습니다.**
> 섞으면 측정값(Response)이 상위 티어에 올라가고, Agent가 **"측정값을 조치하십시오"**라는
> 실행 불가능한 지시를 내립니다.

### 감시 방식에 따른 액션 타입 덮어쓰기

| 감시방식 | 대상 | 액션 타입 |
|---|---|---|
| `trend` | `Vibration` | **추세알람(정비)** — 값 조정이 아니라 설비 정비 |
| `spike` | `Remain_Coat`의 `CLN_Pressure` | **급락알람** — 추세가 아니라 순간 급락 |
| `level` | 그 외 | 티어 기본 액션 |

> `Vibration`은 **"낮추라"고 지시할 수 없습니다.** 추세를 보고 정비 시점을 알리는 인자입니다.
> `CLN_Pressure`(Remain_Coat)는 **추세가 아니라 그 스트립 순간의 급락**이 문제입니다.
> **같은 알람 로직으로는 둘 다 못 잡습니다.**

---

## 3. 가시성 — 표에 함께 싣는 근거

멘토 요구(*"무슨 근거로 그 숫자가 나온건지"*)에 따라, `rel_20_tier_table.csv`는
**판정 결과뿐 아니라 그 숫자가 나온 조건을 전부** 함께 싣습니다.

| 열 | 내용 |
|---|---|
| `cliffs_delta` / `p_fdr` | 통계검정 결과값 |
| `n_defect` / `n_normal` | **그 숫자를 낸 표본 수** |
| `stat_method` | Mann-Whitney U → Cliff's delta, BH-FDR 보정 |
| `stat_criterion` | `p_FDR < 0.05 AND |delta| >= 0.2` |
| `rf_importance` / `rf_importance_std` | 순열 중요도 평균 · 표준편차(10회 반복) |
| `rf_rank` | `순위/후보수` — 몇 개 중 몇 등인지 |
| `rf_criterion` / `rf_method` | 통과선과 계산 방법 |
| `delta_original` / `delta_r1` | 데이터셋별로 따로 계산한 값 |
| `n_machines_pass` | `|delta| ≥ 0.2`인 장비 수 |
| `comparison_group` | **비교군 정의** (pure 라벨) |
| `baseline` | **기준선 정의** (OPCOND 층별 median, MAD×1.4826) |
| `tier_reason` | **이 행이 왜 그 티어인지 한 문장** |

---

## 4. 경보 임계값 — 어떤 값을 넘으면 울리는가

멘토 요구(*"어떤 값의 범위나 차이를 보여주면 좋다"*)에 따라 **실제 단위**로 싣습니다.

| 열 | 내용 |
|---|---|
| `alert_threshold_z` / `alert_threshold_raw` | 경계값 (z 및 **실제 단위**) |
| `normal_range_raw` | **정상 구간의 실제 값 범위** (5~95 백분위) |
| `risky_range_raw` | **위험 구간의 실제 값 범위** |
| `rate_in_normal_pct` / `rate_in_risky_pct` | 두 구간의 **불량률** |
| `risk_ratio` | 위험구간이 정상구간의 **몇 배**인가 |
| `n_in_normal` / `n_in_risky` | 각 구간 표본 수 |
| `threshold_method` | DecisionTree stump(깊이 1)로 분할점 탐색 |

경계값은 **사람이 정한 게 아니라 데이터에서 찾은 값**입니다.
깊이 1짜리 결정트리가 "여기서 자르면 불량/정상이 가장 잘 갈린다"는 지점을 찾습니다.

---

## 5. SOP 칸

**현재 SOP를 받지 못해 비워둡니다.**

| 열 | 값 |
|---|---|
| `sop_action` | *(빈칸)* |
| `sop_check` | *(빈칸)* |
| `sop_status` | `SOP 미수령 — 멘토 제공 대기` |

`action_type`(즉시조치/조건부조치/감시/추세알람/급락알람)은 **이미 채워져 있으므로**,
SOP 문구만 받으면 그 자리에 넣으면 됩니다.

---

## 6. 알려진 한계

| 항목 | 내용 |
|---|---|
| `0.2` 기준선 | 관례이며 물리 상수가 아님. 이 값에 결론이 바뀌는 인자가 있음 |
| 원본 데이터 | Chipping 4건 / Micro_Crack 41건뿐이라 원본 단독 재현성 판정이 불안정 |
| r1 데이터 | DP02/DP03에 열화를 **주입한 시나리오** — 실제 라인 재현 여부 미확인 |
| `CLN_Pressure` | Particle과 Remain_Coat에 **반대 방향** — 조치 시 트레이드오프 발생 |
| 냉각 계열 | 두 컬럼 모두 변동 폭이 매우 좁아(수온 약 1℃), **실제 냉각 실패 사건이 데이터에 없을 가능성** |
