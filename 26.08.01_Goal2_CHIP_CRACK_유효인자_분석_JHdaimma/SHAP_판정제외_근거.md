# XGBoost+SHAP을 유효인자 판정에서 제외한 근거

작성: JHdaimma · 기준일: 2026-08-03
검증 대상: **4개 defect 전체** (Chipping / Micro_Crack / Particle / Remain_Coat)
재현: `agent_db/verify_shap_false_positives.py` → `agent_db/db_10_shap_false_positives.csv`

---

## 요약

> **SHAP은 4개 defect 전부에서 오탐 24건을 만들었고, 누락은 1건뿐이었다.**
> 판정에 쓰면 무관한 인자가 확정으로 올라간다. **개별 건 설명 전용으로 써야 한다.**

---

## 검증 방법

각 defect마다 이렇게 셌습니다.

| 구분 | 정의 |
|---|---|
| **SHAP만 통과** | SHAP top10에는 들었는데 **통계검정·RandomForest는 둘 다 탈락**시킨 인자 |
| **SHAP만 누락** | 통계검정·RandomForest는 둘 다 통과인데 **SHAP만 탈락**시킨 인자 |

두 방향을 같이 세면 **SHAP이 어느 쪽으로 치우치는지** 알 수 있습니다.

---

## 결과

| defect | 후보 | **SHAP만 통과** | SHAP만 누락 | 출처 |
|---|---|---|---|---|
| **Chipping** | 23 | **5** | 0 | JHdaimma |
| **Micro_Crack** | 14 | **6** | 0 | JHdaimma |
| **Particle** | 39 | **7** | 1 | Jun 통합본 |
| **Remain_Coat** | 39 | **6** | 0 | Jun 통합본 |
| **합계** | | **24** | **1** | |

### SHAP만 통과시킨 인자 목록

| defect | 인자 |
|---|---|
| Chipping | `CLN_Flow`, `Coating_Flow`, `Cooling_Flow`, `Feed_Speed`, `Frequency` |
| Micro_Crack | `CLN_Time`, `Coating_Flow`, `Cooling_Thermal_Load`, `Cooling_Water_Temp`, `Cutting_X_Index`, `Cutting_Y_Index` |
| Particle | `CLN_Pressure`, `Cleaning_Capacity`, `Coating_Flow`, `Frequency`, `Head_Temp`, `Laser_Centering_Position`, `Laser_Voltage` |
| Remain_Coat | `Coating_Flow`, `Cutting_X_Index`, `Cutting_Y_Index`, `Feed_Speed`, `Laser_Centering_Position`, `Laser_Power` |

---

## 왜 이런 일이 생기나

**SHAP은 항상 순위를 매깁니다. 후보가 전부 무관해도 반드시 누군가는 상위권이 됩니다.**

Chipping SHAP 원인모델(FDC 23개) 순위를 보면 명확합니다.

| 순위 | 인자 | \|SHAP\| | 판정 |
|---|---|---|---|
| 1 | `Head_Temp` | **1.9790** | ✅ 진짜 |
| 2 | `Laser_Power` | 1.1804 | ✅ |
| 3 | `Power_Efficiency` | 0.8422 | ✅ |
| 4 | `Laser_Centering_Position` | 0.2276 | ✅ |
| 5 | `Vibration` | 0.2119 | ✅ |
| **6** | **`CLN_Flow`** | **0.1225** | ❌ 세정 계열 |
| **7** | **`Frequency`** | **0.1076** | ❌ |
| **8** | **`Cooling_Flow`** | **0.0989** | ❌ 방열 계열 |
| **9** | **`Coating_Flow`** | **0.0936** | ❌ 코팅 계열 |
| **10** | **`Feed_Speed`** | **0.0890** | ❌ |

**6~10위는 1위의 1/16 ~ 1/22 수준**인데, `top-10`이라는 기준을 쓰면 **전부 통과**합니다.

세정·냉각·코팅은 **Chipping(기계적 파손)과 물리적으로 무관**합니다
(Jun CHIP DOMAIN_KNOWLEDGE.md에서 `not_related_to_defect`로 분류).

### Remain_Coat가 가장 극적입니다

> **Remain_Coat = 세정 공정 문제** (팀 문서 명시)

그런데 SHAP이 통과시킨 6개에 **세정 계열이 하나도 없습니다.**
전부 레이저·정렬 계열이고, 정작 진짜 원인인 `CLN_Pressure`는 **통계검정·RandomForest가 잡았습니다.**

---

## 🔑 Chipping은 왜 사고가 안 났나

**SHAP은 Chipping에서도 똑같이 5건을 오탐했습니다.** 최종 목록에 안 들어간 건
**SHAP이 정확해서가 아니라 도메인 게이트가 막았기 때문**입니다.

| | Chipping | Micro_Crack |
|---|---|---|
| SHAP 오탐 | 5개 | 6개 |
| **도메인 게이트** | ✅ 세정·냉각이 **"무관"으로 분류돼 차단** | ❌ **`Vibration`에 도메인 지지를 잘못 부여** |
| 최종 목록 진입 | **없음** | **`Vibration` 진입** |

`Vibration`만 게이트를 통과한 이유는, 작성자가 멘토의 *"진동은 설비 열화의 대표 신호"*를
**"진동 → 미세균열"의 근거로 확대 해석**했기 때문입니다.

> **도메인 게이트가 SHAP 오탐을 막는 방어선인데, 그 문에 작성자가 구멍을 냈습니다.**

---

## 결론 — SHAP의 역할 배치

| 용도 | 사용 | 이유 |
|---|---|---|
| **유효인자 판정** | ❌ **제외** | 오탐 24건. 순위를 항상 매기므로 무관한 인자도 상위권이 됨 |
| **개별 건 설명** (`db_07`) | ✅ **필수** | "이 LOT은 왜 위험한가"에 답할 수 있는 **유일한 방법** |
| **3방법 대조** (`db_08`) | ✅ 참고 | 다른 방법과 어긋나면 그 자체가 검토 신호 |

**현재 `db_01` 판정 로직은 통계검정 + RandomForest 2개만 사용합니다.** 이 문서가 그 근거입니다.

---

## 함께 지켜야 할 것

SHAP을 빼도 **판정 기준 자체에 남은 문제**가 있습니다.

| 문제 | 내용 | 조치 |
|---|---|---|
| **top-N 기준이 후보 수에 반비례** | Micro_Crack은 후보 14개인데 top-10 = **상위 71%** | **후보 수 비례**(예: 상위 25%) + **중요도 최소값** 병행 |
| **모델 성능 미반영** | Micro_Crack 모델 AUC **0.578**(동전던지기 0.5 수준)인데 순위는 매겨짐 | 모델 성능이 낮으면 **순위 신뢰도 하향** |
| **도메인 게이트가 방어선** | 게이트가 뚫리면 오탐이 그대로 통과 | **도메인 지지는 확정 근거일 때만 부여** (`작성자_추론`은 지지 아님) |

---

## 발표용 한 문단

> "SHAP은 4개 결함 모두에서 **오탐 24건**을 만들었습니다. 누락은 1건뿐이었고요.
> Remain_Coat는 세정 공정 문제인데, **SHAP이 뽑은 6개에 세정 계열이 하나도 없었습니다.**
>
> SHAP은 **항상 순위를 매기기 때문**입니다. 후보가 전부 무관해도 누군가는 상위권이 됩니다.
>
> 그래서 저희는 **SHAP을 판정에서 빼고 개별 건 설명에만** 씁니다.
> 이건 SHAP을 **안 써봐서가 아니라, 써보고 내린 결정**입니다."

---

## 재현

```bash
python "26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/agent_db/verify_shap_false_positives.py"
```

Particle/Remain_Coat는 Jun 브랜치의 통합본을 `git show`로 읽으므로 **원격 접근이 필요**합니다.
