# JHdaimma님께 — 부탁드릴 것 1건: `build_tier_table.py`를 이진 라벨로 한 번 더 돌려주세요

- 2026-08-11 / 김시우 (추세분석 · Health Index)
- 관련: `26.08.05_Goal2_통합_Relationship_DB_JHdaimma/결정_대기_사항.md` (A-1 · C-3 · C-4 · D-1)
- 재현: `python3 docs/check_label_delta.py` · `python3 docs/check_label_grid.py`

> **한 줄: `pure` 라벨이 "한 인자가 두 불량을 일으키는" 짝만 골라서 깎고 있고,
> 라벨을 이진으로 바꾸면 님 결정_대기_사항의 판정 2건이 바뀝니다.**

---

## 0. 부탁드리는 것은 딱 하나입니다

`build_tier_table.py:90~94`의 라벨 정의를 이진으로 바꿔서 **한 번 더 돌려주시고,
두 결과를 비교해 주십시오.** 제안 코드는 §5에 적었습니다.

DB를 이진으로 **바꿔달라는 게 아닙니다.** 어느 쪽을 정본으로 할지는 님 판단이고,
저는 그 판단에 쓸 숫자를 재서 가져온 것입니다.

---

## 1. 먼저 — 제 재계산이 님 표를 그대로 재현합니다

새 전처리를 만들지 않았습니다. `build_relationship_db.py`를 exec해서 **님이 쓰시는
층별 기준선·강건 z-score·피처 목록·정상군 정의를 그대로** 썼습니다
(`build_tier_table.py`와 같은 수법입니다).

`pure` 라벨로 다시 계산한 Cliff's delta가 `rel_20_tier_table.csv`와 **11행 전부
소수점 4자리까지 일치**합니다.

```
불량 ↔ 인자                                DB      pure
Particle ↔ CLN_Flow                    -0.0052  -0.0052
Remain_Coat ↔ CLN_Pressure             -0.2466  -0.2466
Chipping ↔ Power_Efficiency            -0.8789  -0.8789
...                                    (11/11 일치)
```

**이게 맞아야 아래 숫자를 믿으실 수 있어서 먼저 적습니다.**

## 2. 왜 라벨을 의심하게 됐나 — 모양이 너무 규칙적입니다

티어표에서 **defect를 2개 가진 인자가 셋**인데, 셋 다 두 번째만 강등돼 있습니다.

| 인자 | 첫 번째 불량 | 두 번째 불량 |
|---|---|---|
| CLN_Flow | Remain_Coat **T1** | Particle **T2** (`alert_usable=False`) |
| CLN_Pressure | Remain_Coat **T1** | Particle **T4 판단보류** |
| Cooling_Flow | Chipping **T2** | Micro_Crack **T3 감시만** |

`pure`는 다른 불량이 같이 난 행을 양쪽에서 뺍니다. 그런데 **한 원인이 두 불량을 동시에
일으키면, 그 관계를 증명하는 행이 정확히 "같이 난 행"입니다.** 즉 증거만 골라서
지워집니다. 실측으로 위험구간 안의 해당 불량 샷 중 다른 불량 동반 비율이

```
CLN_Flow     ↔ Particle     88%      <- pure가 버리는 몫
Cooling_Flow ↔ Micro_Crack  85%
CLN_Pressure ↔ Particle     77%
반면 확정 T1 짝들            48~69%
```

버리는 몫이 큰 순서와 강등된 순서가 같습니다.

## 3. 라벨을 바꾸면 통계검정 판정 2건이 바뀝니다

`python3 docs/check_label_delta.py` (통과 기준은 님 코드 그대로 `p_fdr < 0.05 AND |delta| >= 0.2`)

| 불량 ↔ 인자 | pure delta | 이진 delta | 판정 |
|---|---|---|---|
| **Micro_Crack ↔ Cooling_Flow** | −0.0232 | **−0.2775** | 미달 → **통과** ⬅ |
| **Particle ↔ CLN_Pressure** | +0.0117 | **−0.0633** | 방향X → **방향O** ⬅ |
| Particle ↔ CLN_Flow | −0.0052 | −0.1460 | 미달 → 미달 (28배 커짐, p 0.46 → 3.7e-266) |
| Micro_Crack ↔ Cooling_Water_Temp | −0.0125 | −0.0059 | 방향X → 방향X (**안 바뀜**) |
| Chipping 3짝 · Remain_Coat 2짝 · Surface_Roughness | — | — | 전부 통과 유지(오히려 강해짐) |

경계값 축(`risk_ratio` / `alert_usable`)도 같은 방향입니다 — `docs/check_label_grid.py`,
r1 기준:

```
CLN_Flow     ↔ Particle     0.80 -> 3.31   (역전 해소)
Cooling_Flow ↔ Micro_Crack  1.35 -> 1.78
CLN_Pressure ↔ Particle     0.88 -> 1.29   (역전 해소)
Cooling_Water_Temp ↔ Micro_Crack  0.93 -> 0.97   (여전히 역전)
```

## 4. 결정_대기_사항.md 항목별로

### A-1 `Particle / CLN_Flow` T2 → T3 — **재실행 뒤로 미뤄주시길 부탁드립니다**

님이 강등 근거로 적으신 두 가지가 이렇게 됩니다.

| 근거 | pure | 이진 |
|---|---|---|
| "delta −0.005 — 사실상 0" | −0.0052 (p_fdr 0.46) | **−0.1460 (p_fdr 3.7e-266)** |
| "경보 방향 역전 0.8배" | 0.80배 | **3.31배 (역전 해소)** |

**|delta| 0.2 기준에는 이진으로도 여전히 미달입니다** — 이건 분명히 적어둡니다.
다만 "사실상 0"과 "0.146"은 다르고, 역전은 사라집니다. 지금 티어 규칙대로면
`dir_ok=True, stat_pass=False, rf_pass=True → n_pass=1 → T2`라 **규칙상으로는 T2가
유지**됩니다. 강등하실 거면 규칙을 넘어서는 판단인데, 그 판단의 근거 두 개 중
하나(역전)가 라벨을 바꾸면 없어집니다.

### C-4 `Micro_Crack` 확정 원인 0건 — **이진 라벨이면 Cooling_Flow가 통계검정을 통과합니다**

지금 T3인 이유가 "통계검정·RF 모두 미달"(`stat_pass=False, rf_pass=False → n_pass=0`)인데,
이진으로는 delta −0.2775로 **통계검정을 통과합니다.** 그러면 RF 결과와 무관하게
`n_pass >= 1`이 되어 **규칙상 T3가 아니라 최소 T2**입니다(RF까지 통과하고 재현성이
받쳐주면 T1). RF와 재현성은 제가 안 돌렸습니다 — §6.

Micro_Crack은 지금 Health Index가 **감시 자체를 못 하는** 불량이라(쓸 수 있는 원인이
0개라 가짜 100점을 막으려고 제외 중입니다), 이 한 건이 풀리면 그 구멍이 메워집니다.

### D-1 `CLN_Pressure` 방향 어긋남 — **이진 라벨이면 방향이 맞습니다**

> *"정정 후 데이터와 방향이 어긋납니다. Particle의 실측 delta는 +0.012(양수)로 도메인
> 기대(음수)와 반대입니다."*

이진 라벨로는 **−0.0633으로 음수**입니다. 도메인 정정(압력 ↑ → Particle ↓)과 방향이
맞습니다. 크기는 여전히 작지만, T4의 배정 사유였던 `not dir_ok`가 해소됩니다.

### C-3 `Micro_Crack / Cooling_Water_Temp` — **님 판단이 맞습니다. 그대로 두십시오**

이 짝만 라벨을 바꿔도 **안 바뀝니다**(0.93 → 0.97, 여전히 역전 / delta 방향도 그대로 X).
티어표에서 defect가 하나뿐인 인자라 애초에 `pure`가 깎을 게 없었습니다.

**T4 판단보류는 이 짝에 대해 옳은 판정이고, 멘토께 여쭤보시려는 질문
("이 데이터셋에 실제 Cooling Failure 사건이 포함돼 있습니까?")도 그대로 유효합니다.**
라벨 문제로 설명되지 않는다는 게 오히려 그 질문을 더 필요하게 만듭니다.

### 덤 — `Surface_Roughness / Particle`의 risk_ratio 378배

`pure`로 재면 정상구간 분모가 0에 가까워서 **2621배**까지 튑니다(r1 기준). 이진으로는
6.90배라는 읽을 수 있는 수가 나옵니다. 이 짝은 이진 쪽이 더 정확한 게 아니라 **말이
되는** 쪽입니다. `agent_cause_factors.json`에 넣을지 논의할 때 참고하실 수 있습니다.

## 5. 고치실 곳은 한 군데입니다

`build_tier_table.py:90~94`. 라벨을 만드는 곳이 여기 하나고, 아래쪽은 전부
`df[f"__pure_{d}"]`를 읽기만 합니다(108·122·142·174·183·189행).

```python
# 지금
for d in DEFECTS:
    others = [x for x in DEFECTS if x != d]
    df[f"__pure_{d}"] = ((df[d] == 1) & (df[others].sum(axis=1) == 0)).astype(int)
LABEL_DEF = "pure 라벨 — 나머지 3개 defect가 동시 발생한 행을 비교군·불량군 양쪽에서 제외"

# 제안 — 라벨을 상수로 빼서 두 번 돌리고 비교
LABEL_MODE = "pure"        # "pure" | "binary"
for d in DEFECTS:
    others = [x for x in DEFECTS if x != d]
    df[f"__y_{d}"] = (((df[d] == 1) & (df[others].sum(axis=1) == 0)) if LABEL_MODE == "pure"
                      else (df[d] == 1)).astype(int)
LABEL_DEF = {"pure": "pure 라벨 — 나머지 3개 defect가 동시 발생한 행을 비교군·불량군 양쪽에서 제외",
             "binary": "이진 라벨 — 해당 defect 컬럼이 1인 행을 전부 불량으로 셈"}[LABEL_MODE]
```

`__pure_` → `__y_` 이름만 같이 바꾸시면 됩니다. `LABEL_DEF`가 `comparison_group`
칸으로 나가니 산출물에 어느 라벨로 만든 표인지 자동으로 남습니다.

## 6. 제가 확인하지 못한 것 — 그래서 재실행이 필요합니다

- **RandomForest 순열중요도를 안 돌렸습니다.** `rf_pass`가 어떻게 바뀔지 모릅니다.
- **재현성(두 데이터셋 방향 일치)을 안 봤습니다.** `repro_state`도 모릅니다.
- 따라서 **최종 tier를 예측하면 안 됩니다.** 제가 잰 건 통계검정 축과 경계값 축 둘뿐입니다.
- 라벨을 바꾸면 `n_defect` 자체가 커져서(예: Chipping pure 12,468 → 이진 24,175)
  RF 학습 조건도 달라집니다. 제가 밖에서 추정할 수 있는 부분이 아닙니다.

## 7. 저희 쪽은 코드 변경이 없습니다

짝짓기 단일 출처가 관계DB라 하드코딩된 짝이 없습니다. DB가 바뀌면:

- `CLN_Flow ↔ Particle`의 `alert_usable`이 True가 되면 화면의 `(위험구간 기준 없음)`
  꼬리표가 저절로 사라집니다
- `CLN_Pressure`가 Particle을, `Cooling_Flow`가 Micro_Crack을 하류 defect로 갖게 되면
  화면·에이전트가 자동으로 둘 다 이름을 부릅니다 — **인자당 defect를 여러 개 읽는 건
  `e38f213`에서 이미 고쳐뒀습니다.** 지금 DB에 2개짜리가 CLN_Flow 하나뿐이라
  거기서만 보이는 것뿐입니다
- Micro_Crack이 감시 대상으로 복귀합니다(지금은 쓸 수 있는 원인이 0개라 제외 중)

**바뀌면 저희가 재생성하고 장비 점수 변화를 보고드리겠습니다.**

## 8. 관련 문서

| 문서 | 내용 |
|---|---|
| `docs/검증_라벨정의가_가린_짝_전수조사.md` | 11개 짝 경계값 축 전수조사 |
| `docs/검증_CLNFlow_Particle_경계가_사라진_이유.md` | CLN_Flow↔Particle 한 짝을 샷 단위로 |
| `docs/check_label_delta.py` | §3 표 재현 (통계검정 축) |
| `docs/check_label_grid.py` | §3 아래 배수 재현 (경계값 축) |
