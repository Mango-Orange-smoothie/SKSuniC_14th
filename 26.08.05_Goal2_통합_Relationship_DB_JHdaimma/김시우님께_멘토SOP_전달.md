# 김시우님께 — 멘토 SOP 3건 전달 · `get_sop_for_factor` 반영 요청

작성 JHdaimma · 2026-08-12
관련 `agent.py:210 get_sop_for_factor` · `agent_cause_factors.json` 의 `agent_rules`

> **한 줄: 멘토님 SOP를 받았습니다. `sop_status="SOP 미수령"`을 이제 채울 수 있습니다.**
>
> `agent.py`가 김시우님 파일이라 제가 직접 고치지 않았습니다.
> **문구와 설계만 넘깁니다.** 브랜치가 main보다 23커밋 앞서 계셔서 충돌도 피하고 싶었습니다.

---

# 1. 멘토 SOP 원문 (2026-08-11 수령)

가공하지 않은 원문입니다. 다듬은 버전은 3절에 있습니다.

### ① Power_Efficiency & Laser_Power

> head 단 laser 출력과 가공점의 laser 출력의 정도 차이를 효율로 나타내주는 것인데,
> 사이에 있는 광로(mirror)의 particle이나, laser 과다 노출에 의한 열화가 발생되어
> 효율이 떨어진다. **광로의 mirror별 power 점검 진행이 필요하다.**

### ② Head_Temp

> head를 식히기 위해서 subcomponent module인 chiller를 이용하여 water를 공급해
> 항온을 유지한다. chiller에서 나오는 물의 온도 또는 water flow가 비정상적인 경우
> head temp 열화를 일으키고, 높아진 head temp에 의해 laser beam의 shape/centering
> 등이 틀어진다. 이로 인해 laser grooving 공정이 정상적으로 Metal line을 날리지 못하고
> 날아가지 않은 metal 패턴에 singulation blade가 닿으면 chipping이 발생된다.
> **chiller를 점검하고 laser beam별 profile 점검이 필요하다.**

### ③ CLN_Pressure / CLN_Flow

> fab 공급단의 di water 압과 유량이 열화되면 세정력에 문제가 생기고, 제거되지 않는
> coating액으로 인한 불량이 발생된다. 이를 점검하기 위해서는 **di water hook up단
> 체결 상태를 점검 및 fab 공급단의 변화를 모니터링한다.**

---

# 2. 핵심 — SOP는 **인자 단위가 아니라 계통 단위**입니다

멘토님이 인자 8개가 아니라 **3그룹**으로 주셨습니다.

| 계통 | 인자 | 점검 |
|---|---|---|
| **레이저 광로** | `Power_Efficiency` · `Laser_Power` | 미러별 출력 |
| **칠러** | `Head_Temp` · `Cooling_Flow` · `Cooling_Water_Temp` | 칠러 + 빔 프로파일 |
| **세정** | `CLN_Pressure` · `CLN_Flow` | DI water 체결부 + 팹 공급단 |

**인자마다 따로 지시하면 같은 작업을 여러 번 시키게 됩니다.**
예를 들어 DP03은 `Head_Temp`·`Cooling_Flow` 둘 다 걸리는데 **칠러 점검은 한 번**입니다.

## 칠러 계통이 3개인 근거 — 진혁님 확인 + 데이터

멘토님께 여쭤보니 **칠러는 냉각수를 내보내는 장치**라고 하셨습니다.
그래서 `Cooling_Flow`·`Cooling_Water_Temp`가 ② SOP의 "chiller에서 나오는 물"입니다.

**데이터로도 유량 쪽은 확인됩니다.**

```
Cooling_Flow       vs Head_Temp   상관 −0.422 (합본) · −0.527 (r1)
Cooling_Water_Temp vs Head_Temp   상관 −0.000
```

| 냉각 유량 | 헤드 온도 |
|---|---|
| 9.837 | **42.349** |
| 9.927 | 42.099 |
| 9.985 | 42.063 |
| 10.041 | 42.044 |
| 10.120 | **42.028** |

**유량이 낮을수록 헤드 온도가 오릅니다. 멘토님 인과사슬 그대로입니다.**

> 이게 `Cooling_Flow`의 RF 순열중요도가 39/39(꼴찌)인 이유이기도 합니다 —
> `Head_Temp`를 통해서만 작용하는 중간 다리라, `Head_Temp`가 모델에 있으면
> 추가 정보를 못 줍니다. **관계가 없어서가 아니라 가려져서입니다.**

> ⚠️ `Cooling_Water_Temp`는 상관 −0.000이고 89일 변동 폭이 약 1℃입니다.
> **데이터로는 확인이 안 되지만 멘토 확정 도메인이라 계통에 유지**했습니다
> (T4 판단보류는 그대로).

---

# 3. 다듬은 문구

## 레이저 광로 — `Power_Efficiency` · `Laser_Power`

```
조치    광로(mirror)별 출력 점검

왜      헤드에서 나온 출력과 가공점 출력의 차이가 '효율'입니다.
        그 사이 광로 거울에 파티클이 끼거나 레이저 과다 노출로 거울이 열화되면
        효율이 떨어집니다.

순서    거울을 하나씩 짚어가며 출력을 재서 어느 구간에서 떨어지는지 확인
```

## 칠러 — `Head_Temp` · `Cooling_Flow` · `Cooling_Water_Temp`

```
조치    ① 칠러(chiller) 점검
        ② 레이저 빔 프로파일 점검

왜      헤드는 칠러가 보내는 냉각수로 온도를 유지합니다.
        칠러 물의 온도나 유량이 흐트러지면 헤드 온도가 오르고,
        레이저 빔의 모양과 중심이 틀어집니다.
        그루빙이 메탈 라인을 다 못 날리고, 남은 메탈에 절단 블레이드가 닿으면
        모서리가 깨집니다.

순서    칠러 먼저(원인) → 빔 프로파일(결과 확인)
```

## 세정 — `CLN_Pressure` · `CLN_Flow`

```
조치    ① DI water 체결부(hook up) 상태 점검
        ② fab 공급단 변화 모니터링

왜      팹에서 오는 DI water 의 압력과 유량이 떨어지면 세정력이 약해지고,
        씻기지 않은 코팅액이 남습니다.

순서    체결부 먼저(설비 쪽) → 공급단(팹 쪽)
```

---

# 4. 반영 제안 — `get_sop_for_factor` 한 함수

`agent.py:81`에 적어두신 대로 **에이전트 구조는 안 건드립니다.**

> *"관계DB가 커지면 get_defect_causes / get_sop_for_factor만 그걸 읽도록 바꾸면 되고
> 에이전트 구조 자체는 안 바뀐다."*

## ① 상수 추가

```python
# 멘토 SOP (2026-08-11 수령) — 인자가 아니라 '계통' 단위.
# 같은 계통은 점검이 하나라, 인자마다 따로 지시하면 같은 작업을 여러 번 시키게 된다.
MENTOR_SOP = {
    "세정": {
        "factors": ["CLN_Pressure", "CLN_Flow"],
        "actions": ["DI water 체결부(hook up) 상태 점검", "fab 공급단 변화 모니터링"],
        "order":   "체결부 먼저(설비 쪽) → 공급단(팹 쪽)",
        "why":     "팹에서 오는 DI water 압력·유량이 떨어지면 세정력이 약해지고 "
                   "씻기지 않은 코팅액이 남는다.",
    },
    "레이저 광로": {
        "factors": ["Power_Efficiency", "Laser_Power"],
        "actions": ["광로(mirror)별 출력 점검"],
        "order":   "거울을 하나씩 짚어가며 출력을 재서 어느 구간에서 떨어지는지 확인",
        "why":     "헤드 출력과 가공점 출력의 차이가 효율이다. 사이 광로 거울에 파티클이 "
                   "끼거나 레이저 과다 노출로 열화되면 효율이 떨어진다.",
    },
    "칠러": {
        "factors": ["Head_Temp", "Cooling_Flow", "Cooling_Water_Temp"],
        "actions": ["칠러(chiller) 점검", "레이저 빔 프로파일 점검"],
        "order":   "칠러 먼저(원인) → 빔 프로파일(결과 확인)",
        "why":     "헤드는 칠러 냉각수로 항온을 유지한다. 물 온도나 유량이 흐트러지면 "
                   "헤드 온도가 오르고 빔 shape·centering이 틀어진다. 그루빙이 metal line을 "
                   "다 못 날리고, 남은 metal에 singulation blade가 닿으면 chipping이 난다.",
    },
}
SOP_GROUP = {f: g for g, v in MENTOR_SOP.items() for f in v["factors"]}
```

## ② 반환값에 키 추가 (기존 키는 그대로)

```python
g = SOP_GROUP.get(factor_name)
if g:
    payload.update({
        "sop_status":      "수령 (2026-08-11 멘토 제공)",
        "sop_group":       g,
        "sop_shared_with": MENTOR_SOP[g]["factors"],
        "sop_actions":     MENTOR_SOP[g]["actions"],
        "sop_order":       MENTOR_SOP[g]["order"],
        "sop_why":         MENTOR_SOP[g]["why"],
    })
# SOP 없는 인자(Surface_Roughness)는 기존 반환값 그대로
```

**키가 늘어나기만 해서 호출부(`_format_action_line` 등)는 안 깨집니다.**

## ③ `SYSTEM_PROMPT` 규칙 3줄

```
- SOP는 계통 단위다. 같은 계통 인자가 여러 개 걸려도 점검은 한 번만 지시할 것.
- sop_shared_with 의 인자 중 **경보 중인 것만** 이름을 부를 것.
  경보가 없는 인자는 원인 목록에는 두되 조치 지시에서는 뺄 것.
- tier가 T2면 조치를 단독으로 지시하지 말 것. 같은 계통 T1이 있으면 그쪽에 묶고,
  없으면 "먼저 확인할 것"을 제시한 뒤 조건에 따라 갈라서 답할 것.
```

## ④ `agent_rules` 한 줄 교체 — **이건 제가 하겠습니다**

```
전   "SOP는 아직 수령하지 않았다. 조치 문구를 지어내지 말 것."
후   "SOP는 계통 단위로 수령했다(레이저 광로·칠러·세정).
      Surface_Roughness는 아직 미수령이므로 그 인자만 문구를 지어내지 말 것."
```

`agent_cause_factors.json`은 제 산출물이라 `build_integrated_db.py`에서 고쳐 올리겠습니다.
**말씀 주시면 그때 맞춰 넣겠습니다.**

---

# 5. 출력 시안 — 실제 main 숫자로 렌더링해봤습니다

## DP03 · Chipping

```
  원인 4개 — 급한 순
    🔴 지금 조치   Head_Temp          42.160 (평소 42.000)   HI 50.8   T1  41.8일째
    🟡 관찰       Laser_Power        18.475 (평소 18.500)   HI 78.0   T1   5.0일째
    🟡 관찰       Power_Efficiency   94.962 (평소 95.000)   HI 88.3   T1   1.6일째
       관찰       Cooling_Flow        9.992 (평소  9.999)   HI 97.8   T2  경보 없음

  ▶ 칠러 계통  (Head_Temp)
       1. 칠러(chiller) 점검
       2. 레이저 빔 프로파일 점검
       ...
  ▶ 레이저 광로 계통  (Power_Efficiency · Laser_Power)
       1. 광로(mirror)별 출력 점검
       ...
```

**`Cooling_Flow`는 원인 목록에 있지만 경보가 없어서 조치 지시에서는 빠집니다.**

## DP02 · Chipping

```
    🔴 지금 조치   Laser_Power        18.440   HI 47.6   T1  56.0일째
    🔴 지금 조치   Power_Efficiency   94.892   HI 48.0   T1  59.5일째
       관찰       Head_Temp          42.022   HI 97.9   T1  경보 없음
       관찰       Cooling_Flow       10.000   HI 100.0  T2  경보 없음

  ▶ 레이저 광로 계통  (Power_Efficiency · Laser_Power)
```

**칠러 계통은 경보가 하나도 없어서 블록 자체가 안 나옵니다.**

## DP04 · Remain_Coat

```
    🔴 지금 조치   CLN_Flow            9.769 (평소  9.992)   HI 14.5   T1  39.6일째
    🟡 관찰       CLN_Pressure      299.907 (평소 300.036)   HI 80.5   T1   6.2일째

  ▶ 세정 계통  (CLN_Pressure · CLN_Flow)
```

> 이 숫자들은 `01_level_trend_by_machine_column.csv`(현재 main)에서 읽었습니다.
> **'다'안 반영 후 재생성하시면 달라질 수 있습니다.** 시안 확인용으로만 봐주십시오.

---

# 6. 아직 SOP가 없는 인자

| 인자 | 티어 | 상태 |
|---|---|---|
| **`Surface_Roughness`** | M1 감시지표 | ❌ **미수령** |

**감시지표라 "조치"가 성립하지 않습니다.** *"거칠기를 낮추십시오"* 는 지시가 될 수 없어서,
멘토님께는 **"경보가 뜨면 무엇을 점검합니까"** 로 여쭤뒀습니다 (`멘토님_SOP_요청.md` 6번).

**받을 때까지 이 인자만 기존 반환값(`SOP 미수령`)을 유지해주십시오.**

---

# 7. 요약

| | 무엇 | 누가 |
|---|---|---|
| ① | `MENTOR_SOP` 상수 + `get_sop_for_factor` 반환값 | **김시우님** |
| ② | `SYSTEM_PROMPT` 규칙 3줄 | **김시우님** |
| ③ | `agent_rules` 한 줄 교체 | **JHdaimma** (말씀 주시면) |
| ④ | `Surface_Roughness` SOP | 멘토 대기 |

**`build_health_index.py` · `trend_analysis.py` · `pipeline/` · 관계DB 산출물은 전부 안 건드립니다.**

문구나 계통 묶기에 이견 있으시면 말씀해주십시오. 멘토님 원문은 1절에 그대로 뒀습니다.
