# JHdaimma님께 — 협의 요청 4건

- 2026-08-08 / 김시우 (추세분석·Health Index)
- 관련: `26.08.05_Goal2_통합_Relationship_DB_JHdaimma/`

---

## 먼저, DB 쪽 판정이 맞았던 건 확인했습니다

우리(Health Index) 쪽에 버그가 있어서 DB 판정을 무시하고 있었습니다. **`per_defect[defect].alert_usable`를 안 읽고 인자 레벨 `defects` 목록만 읽고 있었습니다.**

그래서 `CLN_Flow ↔ Particle`(`alert_usable=False`, risk_ratio 0.80)을 원인으로 쓰고 있었고, Particle 건강도가 CLN_Flow 건강도의 복사본이 돼 있었습니다. 결과:

| 장비 | Particle 실제 발생률 (첫30일 → 최근7일) | 표시된 건강도 |
|---|---|---|
| DP03 | 6.77% → **10.21%** (+50%) | **100.0** |
| DP04 | 6.79% → **10.24%** (+51%) | 0.4 |

**수정 완료**(커밋 `844b88e`). 이제 `per_defect` 플래그를 우선 적용하고, 제외된 짝을 실행할 때마다 출력합니다. **DB 데이터는 정확했고 저희가 안 읽은 문제였습니다.**

그리고 저희 독립 검정도 DB 판정과 같은 답을 냈습니다. Remain_Coat 후보 17개 중 진짜 원인(CLN_Flow)을 통제하고 재검정하니 15개가 분리력의 22~55%를 잃었고(교란), `CLN_Pressure`만 4.28 → 30.18로 오히려 강해졌습니다 — DB의 T1 배정과 일치합니다.

---

## 요청 1 (가장 급함) — Surface_Roughness ↔ Particle을 Health Index에 넣을 수 있나요

### 상황

위 수정 후 **Particle에 쓸 수 있는 원인 인자가 0개**가 됐습니다. Particle은 감시 데이터에서 **가장 흔한 불량**입니다(6,455건, 6.46%). 지금은 감시 대상에서 빠지고 경고만 출력합니다.

`rel_20_tier_table.csv`를 훑어보니 Particle 관련 행이 셋인데:

| 인자 | tier | repro_state | alert_usable | risk_ratio | JSON 수록 |
|---|---|---|---|---|---|
| CLN_Flow | T2 | 통과 | **False** | 0.80 | ○ (플래그로 걸림) |
| CLN_Pressure | T4 | 실패(방향 불일치) | False | 0.88 | ✕ |
| **Surface_Roughness** | **M1** | **통과** | **True** | **378.38** | **✕** |

**Surface_Roughness가 DB 전체에서 risk_ratio가 가장 높고 재현성도 통과인데,** `agent_cause_factors.json`에는 없습니다. 수록 규칙이 `역할=원인(FDC)` AND `tier T1/T2`인 것으로 보이고, 이건 `역할=감시지표(Response)` / `M1`이라 규칙상 빠진 것으로 이해했습니다.

### 질문

**Health Index가 "결과 지표"도 봐야 할까요?**

- **넣으면**: Particle 건강도가 DP01 45.8 / DP02 5.3 / DP03 3.8 / DP04 7.6이 되어 실제 발생률과 맞아떨어집니다.
- **문제**: agent가 "원인은 Surface_Roughness입니다"라고 말하면 **틀린 말**입니다. 표면조도는 결과지 조정 가능한 인자가 아닙니다.

저희 쪽 생각은 **역할을 구분해서 둘 다 쓰는 것**입니다:

```
원인(FDC)       → "이걸 조정하세요"     (조치 대상)
감시지표(Response) → "이게 나빠지고 있습니다"  (상태 표시)
```

이렇게 하면 Particle 건강도는 나오되 조치 문구는 "원인 미확인, 표면조도로 감시 중"이 됩니다.

### 필요한 것

`agent_cause_factors.json`에 `Surface_Roughness`를 추가하되 **`role`을 구분 가능하게** 넣어주실 수 있을까요. 지금도 `role` 필드가 있으니 값만 `감시지표(Response)`로 들어오면 저희가 코드에서 갈라 쓰겠습니다.

아니면 **의도적으로 뺀 것이라면 그 이유를 알려주세요** — 그러면 저희는 "Particle 감시 불가"를 한계로 명시하고 갑니다.

---

## 요청 2 — Micro_Crack도 확인 부탁드립니다

같은 상황입니다. `agent_cause_factors.json`에 Micro_Crack 연결이 없어서 감시가 안 됩니다.

`rel_20`에 두 행이 있는데 둘 다 `repro_state = 실패(데이터셋간 방향 불일치)`입니다:

| 인자 | tier | alert_usable |
|---|---|---|
| Cooling_Flow | T3 | True |
| Cooling_Water_Temp | T4 | False |

**재현 실패라 뺀 것이 맞다고 이해**하고 있습니다. 맞는지만 확인 부탁드립니다. (Micro_Crack은 감시 데이터에 34건뿐이라 저희도 검증이 어렵습니다.)

---

## 요청 3 — rel_28 Vibration 기준값 회신

별도 문서 `rel_28_Vibration_기준값_회신.md`로 정리했습니다. 요약만 옮기면:

### ① 제시된 상한을 쓸 수 없습니다

`upper_candidate_p99 = 0.2609`는 **합본 200k(원본+R1) 기준**입니다(`defect_rate_overall_pct = 6.234`가 합본 pure Chipping 비율과 정확히 일치하는 것으로 확인). 그런데 **감시 데이터의 Vibration 최댓값이 0.2487**이라 이 선은 영원히 안 울립니다.

같은 파일의 `upper_original_p99 = 0.2066`은 감시 데이터 기준이지만 89일 전체로 계산해 열화 구간이 섞여 있습니다.

### ② 제안 상한: 0.2111

안정 구간(Mann-Kendall로 추세 발생 직전까지) × OK샷의 p99.9입니다. **4대가 0.2089~0.2117로 수렴**합니다(동일 사양 장비이므로 이게 맞는 그림). 89일 전체로 재면 장비별로 벌어집니다.

적용 결과: 상승 중인 DP02·DP03에서 각각 19일·43일 경보, 추세 없는 DP01에서 1일(89일 중). **기존 CUSUM 추세 경보보다 DP02는 11일, DP03은 5일 빠릅니다.**

### ③ 채울 수 없는 필드 2개

| 필드 | 회신 |
|---|---|
| `spec_breach_rule` | 상한 0.2111, 일별 초과 샷 수 ≥ `binom.ppf(0.99, 그날 샷수, 0.001)` |
| `trend_window_days` | **해당 없음** — 저희 구현은 고정 창이 아니라 CUSUM 누적(`K=0.7σ`, `H=4.5σ`) |
| `trend_slope_threshold` | **미사용** — 기울기 임계값이 아니라 Mann-Kendall `p<0.05`로 판정 |

스키마가 가정한 파라미터 형태와 저희 구현이 다릅니다. **필드를 "해당 없음"으로 남길지, 스키마를 CUSUM 파라미터에 맞게 바꿀지** 정해주시면 따르겠습니다.

### ④ 짝짓기 확인

`defect = Chipping`(lift 4.82)인데 **감시 데이터의 pure Chipping이 3건**뿐이라, `rel_20`의 `repro_state` 논리대로면 재현 검증이 불가능합니다. `domain_evidence = 멘토 확정`이니 도메인 근거로 진행하는 것이 맞는지 확인 부탁드립니다.

---

## 요청 4 — 새 후보 2쌍을 tier 체계로 검정해주실 수 있나요

### 배경

저희 전처리 6-1 단계(`scan_type_c_candidates`)가 **전 컬럼 × 전 defect**에 결정트리 stump를 돌려 "불량률이 뛰는 경계"를 찾고, 순열검정으로 노이즈 천장을 만들어 대조합니다. 원래 C유형 배정이 데이터와 맞는지 자체 검증하려고 만든 것입니다.

여기에 저희 경보 채택 기준(**추세 없는 장비에서의 오경보율 < 1%**, 판정 1회당)을 그대로 적용했더니, **관계DB에 없는 두 쌍이 통과**했습니다.

| 인자 ↔ 불량 | 신호/노이즈 | no_trend 경보율 | drift 경보율 |
|---|---|---|---|
| **Vibration ↔ Remain_Coat** | 1.65배 | 0.809% | **2.025%** (2.5배 구분) |
| **Coating_Thickness ↔ Remain_Coat** | 2.69배 | 0.002% | — (드리프트 장비 없음) |

*(참고 — 이미 채택된 것들: CLN_Pressure 0.000%, CLN_Flow 0.010%, Surface_Roughness 0.177%)*

### DB가 기각한 게 아니라 평가 대상이 아니었던 것으로 보입니다

`rel_20_tier_table.csv`의 Remain_Coat 행은 **CLN_Pressure(T1)와 CLN_Flow(T1) 둘뿐**입니다. Vibration은 `rel_28`에서 다루시지만 거기선 Chipping·Micro_Crack 짝만 보셨고, Remain_Coat 짝은 이번에 처음 나온 것입니다.

### 저희가 임의로 넣지 않는 이유

stump 검정 하나로 원인 관계를 확정하는 건 팀이 써온 방식(Mann-Whitney + Cliff's delta + RandomForest + 재현성 4중 검정)과 맞지 않습니다. **짝짓기는 관계DB를 단일 출처로 삼기로 했으니**, 저희가 후보만 올리고 판정은 요청드리는 게 맞다고 봅니다.

### 참고로, 탈락한 18쌍은 두 방법이 같은 답을 냅니다

Remain_Coat 후보 중 나머지(Kerf_Width_Profile, Focus, Bottom_Kerf, Head_Temp, Top_Kerf, Power_Efficiency, Laser_Power, Package_Size 계열 등)는:

- **교란 검정**: 진짜 원인 CLN_Flow를 통제하니 분리력 22~55% 상실
- **오경보율 기준**: 1.5~4.3%로 기준(1%) 초과

두 독립 방법이 같은 컬럼들을 걸러냈습니다. **이건 저희 쪽에서 판단이 선 부분이라 검정 요청 대상이 아닙니다.**

### 필요한 것

위 2쌍이 tier 체계를 통과하는지, 통과한다면 tier·방향·`alert_usable`을 `agent_cause_factors.json`에 넣어주시면 저희가 바로 반영합니다.

**단서**: `Coating_Thickness`는 오경보율이 0.002%로 매우 낮지만, 이 컬럼에 드리프트 판정된 장비가 없어서 **정탐(진짜 열화를 잡는지)이 검증되지 않았습니다.** 오경보가 없다는 것만 확인된 상태입니다.

---

## 참고 — 저희가 DB에서 새로 읽기 시작한 것들

파이프라인이 이제 `rel_30_trend_interface.csv`와 `rel_20_tier_table.csv`를 직접 읽습니다(예전엔 짝짓기를 코드에 손으로 적어뒀습니다). 채택 조건은 **`alert_usable=True` AND `repro_state=통과`**이고, 무엇이 왜 제외됐는지 실행할 때마다 출력합니다.

`threshold_source_dataset = "r1 주도(원본 기여 미미)"` 경고도 실측으로 확인했습니다 — 해당 인자들(Power_Efficiency/Laser_Power/Head_Temp/Cooling_Flow)은 감시 데이터에서 경계 진입 경보가 **0건**입니다. 주석에 적어두신 그대로였습니다. 이 인자들은 CUSUM 추세 경보로만 감시하고 있습니다.

**DB 스키마가 바뀌면 알려주세요.** 컬럼 존재를 검증하고 없으면 폴백하도록 만들어뒀지만, 조용히 폴백되면 저희가 옛날 값을 쓰게 됩니다.
