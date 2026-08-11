# JHdaimma님께 — 회의자료 각주 3곳이 병합과 동시에 뒤집혔습니다

**대상**: `26.08.05_Goal2_통합_Relationship_DB_JHdaimma/회의자료_라벨확장안_결정요청.md`
**급함**: 내일 회의에서 읽는 문서입니다.
**제가 안 고친 이유**: 진혁님 문서라 직접 손대는 것보다 알려드리는 게 맞다고 봤습니다.

---

## 무슨 일인가

`fd8122a`("회의자료 기준 시점 명시 — 김시우님 지적 반영")에서 각주를 이렇게 다셨습니다.

> `origin/main`은 아직 `CLN_Pressure`의 `watch_mode`가 `spike`라 **즉시조치가 3개**입니다
> (`554816b`의 `spike → level` 정정이 main에 없음). **병합되면 4개가 되고 이 문서가 그대로 맞습니다.**

지적을 반영해주신 건 감사합니다. 그런데 **각주를 넣은 `fd8122a`와 정정한 `554816b`가
PR #23으로 같이 병합**됐습니다. 즉 각주가 예고한 "병합되면"이 같은 순간에 이미
일어나서, 지금 main은 4개입니다.

직접 세어봤습니다 (`origin/main`의 `agent_cause_factors.json`):

```
T1 / 즉시조치      4건   Power_Efficiency · Laser_Power · Head_Temp · CLN_Pressure
T2 / 조건부조치    2건   CLN_Flow · Cooling_Flow
M1 / 감시(경보)    1건   Surface_Roughness
급락알람           0건
```

`rel_20_tier_table.csv`도 `Remain_Coat↔CLN_Pressure`가 `watch_mode=level` /
`action_type=즉시조치`로 들어와 있습니다.

## 고칠 곳 3군데

| 위치 | 현재 문구 | 문제 |
|---|---|---|
| 6~8행 (머리말) | "origin/main은 아직 … 즉시조치가 3개" | main은 4개 |
| 175~182행 (대가 2 절 대조표) | "**origin/main**(지금) \| spike \| 급락알람 \| 3개" | 세 칸 모두 틀림 |
| 239~240행 (결정표 각주) | "origin/main은 … 3개입니다" | main은 4개 |

**본문 숫자와 판단은 손댈 게 없습니다** — 각주가 없어야 맞는 상태입니다.
세 곳을 지우기만 하면 문서가 그대로 맞습니다. 남겨두면 내일 회의에서
읽는 사람이 3개로 오해합니다.

## 저희 쪽은 병합 영향 없음을 확인했습니다

새 DB로 직접 다시 돌렸습니다. 장비 점수가 소수점까지 그대로입니다.

```
DP01 91.9 / DP02 47.6 / DP03 50.8 / DP04 14.5
```

짝짓기도 3개 그대로입니다(`CLN_Pressure→Remain_Coat`, `CLN_Flow→Remain_Coat`,
`Surface_Roughness→Particle`). 세부는 이렇습니다.

- `repro_state` 3건이 `실패(데이터셋간 방향 불일치)` → `실패(도메인 방향과 불일치)`
  — 둘 다 "실패"로 시작해서 `build_health_index.py`의 `~startswith('실패')` 필터가
  동작이 완전히 같습니다. 진혁님이 `c6d1d18`에 적어두신 그대로였습니다.
- `watch_mode` spike → level — `pipeline/common.py`는 이 값을 **읽기만 하고 채택
  판정에는 안 씁니다**(`alert_usable` AND `repro_state`). 그래서 결과가 안 바뀝니다.
- `rel_30` 20열 → 22열 — 삭제된 `current_slope_per_day` / `trend_window_days`를
  읽는 코드가 저희 쪽에 하나도 없습니다.

## 저희가 같이 고친 것 (참고)

`health_index_data.json`이 새 DB로 재생성되지 않은 채 병합돼 있었습니다.
`build_health_index.py:1361`이 관계DB의 `cause_factors`를 산출물에 통째로 복사해서,
돌리기 전까지 `급락알람`이 사본에 남습니다. `n8n`이 이 파일을 하류로 내보내기 때문에
(`n8n/health_index_pipeline_workflow.json:21`) 같은 인자의 긴급도가 두 값으로
나가고 있었습니다. 저희 쪽에서 재생성해 맞췄습니다(`9b72cf1`).

**부탁**: 앞으로 `agent_cause_factors.json`을 고치시면 알려주세요. 저희가
`build_health_index.py`를 돌려야 사본이 따라옵니다. 자동으로는 안 됩니다.
