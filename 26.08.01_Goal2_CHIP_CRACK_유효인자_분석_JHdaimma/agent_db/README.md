# Relationship DB — Chipping / Micro_Crack

담당: JHdaimma · 대상: 전체 아키텍처의 **③ Relationship Analyzer** 산출물
용도: **⑤ Root Cause Analyzer**와 **⑦ GPT AI Agent**가 참조하는 관계 지식베이스

---

## 이 DB가 답하는 질문

| 질문 | 참조 파일 |
|---|---|
| "Chipping의 원인이 뭐야?" | `db_01_factors.csv` (role=원인후보) |
| "뭘 모니터링해야 해?" | `db_01_factors.csv` (role=감시지표) |
| "이 변수가 왜 문제야?" | `db_01_factors.csv` (domain_mechanism) + `db_04` |
| "어느 값부터 위험해?" | `db_03_thresholds.csv` |
| "A가 나빠지면 뭐가 따라 나빠져?" | `db_02_relationships.csv` (그래프 탐색) |
| "이 공정 단계가 뭐 하는 거야?" | `db_04_domain_knowledge.csv` |
| "구간별로 위험도가 어떻게 달라져?" | `db_05_binning.csv` |
| "이 결론 믿어도 돼?" | `db_00_metadata.json` (limitations) |

---

## 파일 구조

### `db_01_factors.csv` — 유효인자 판정표 (메인)

**행 = (target, factor) 조합.** target은 `Chipping` / `Micro_Crack`.

| 컬럼 그룹 | 컬럼 | 설명 |
|---|---|---|
| **분류** | `layer` | `FDC`(손잡이) / `Response`(측정결과) / `Engineered`(파생) |
| | `role` | **`원인후보`**(조치 대상) / **`감시지표`**(모니터링용) |
| | `process_stage` | HBM DP 공정 단계 (`2_laser_grooving` 등) |
| | `is_laser_grooving` | 레이저 그루빙 계열 여부 |
| **판정** | `verdict` | 아래 표 참조 |
| | `n_methods_agree` | 통과한 통계 방법 수 (0~2) |
| **도메인** | `domain_status` | `defect_related` / `not_related_to_defect` / `team_undetermined` |
| | `domain_mechanism` | **왜** 이 변수가 불량과 연결되는지 (Agent가 설명에 사용) |
| | `direction_hypothesis` | `up` / `down` / `either` |
| | `domain_source` | 근거 출처 (팀설계서 / 멘토 / 현업 / 공정지식) |
| **통계** | `delta_primary/broad/pure` | 라벨별 Cliff's delta (효과크기) |
| | `delta_nonlinear_abs_pure` | \|편차\| 기준 (U자형 탐지, 멘토 지시) |
| | `tree_imp_*`, `tree_rank_*` | RandomForest permutation importance |
| **재현성** | `delta_original_dataset` / `delta_r1_dataset` | 데이터셋별 효과크기 |
| | `n_machines_effect_ge_02` | 4대 중 몇 대에서 재현되나 |
| **주의** | `caution` | 멘토 재확인 대기 / 매핑 미확정 등 |

#### verdict 값의 뜻

| verdict | 의미 | Agent 사용법 |
|---|---|---|
| **`confirmed`** | 도메인 지지 + 통계 2개 방법 모두 통과 | **자신 있게 보고** |
| `candidate_needs_domain_review` | 통계는 강한데 **도메인 설명이 없음** | "통계상 유력하나 검토 필요"로 보고 |
| `candidate_weak_signal` | 도메인 지지 + 통계 1개만 | 참고 수준 |
| `candidate_nonlinear_only` | 단조 검정은 실패, **U자형에서만** 잡힘 | 적정구간 이탈 관점으로 해석 |
| **`contaminated_by_*`** | 다른 결함 동시발생 때문에 생긴 **가짜 신호** | **보고하면 안 됨** |
| `insufficient_evidence` | 근거 부족 | 무시 |

### `db_02_relationships.csv` — 관계 엣지 (그래프)

**FDC → Response → Defect** 3층 그래프의 간선입니다. NetworkX로 바로 로드 가능합니다.

| relation | 의미 | 예 |
|---|---|---|
| `drives` | FDC가 Response를 만든다 | `Laser_Power` → `Kerf_Width_Profile` |
| `monitors` | Response가 Defect를 예고한다 | `Kerf_Width_Profile` → `Chipping` |
| `causes` | FDC가 Defect를 유발한다 | `Vibration` → `Micro_Crack` |
| `co_occurs` | 두 결함이 함께 발생 | `Chipping` ↔ `Micro_Crack` |

**Root Cause 추적 방법**: Defect에서 역방향으로 타고 올라가면 조치 가능한 FDC가 나옵니다.
```
Micro_Crack ←(monitors) Surface_Roughness ←(drives) Vibration
                                                      ↑ 여기가 조치 지점
```

### `db_03_thresholds.csv` — 위험선

Jun님의 **C유형 방식**(결정트리 스텀프)으로 구한 경계값입니다.

| 컬럼 | 설명 |
|---|---|
| `threshold_z` | z-score 기준 경계 (조건 무관하게 사용 가능) |
| `threshold_raw_approx` | 원단위 환산값 (참고용) |
| `risky_direction` | `low_is_risky` / `high_is_risky` |
| `defect_rate_below/above` | 경계 아래/위 불량률(%) |
| `risk_ratio` | 위험 구간이 안전 구간의 몇 배인가 |

> ⚠️ 이건 **공식 SPEC이 아니라 데이터 기반 통계 경보선**입니다.

### `db_04_domain_knowledge.csv` — 공정 도메인 지식

| kind | 내용 |
|---|---|
| `defect_mechanism` | Chipping/Micro_Crack이 **왜, 어느 단계에서** 생기는가 |
| `process_stage` | HBM DP 4단계 설명 |
| `column_stage_mapping` | 컬럼 68개 → 공정 단계 매핑 (+확신도) |
| `mentor_feedback` | 멘토 지시사항 (확정 / 재확인 대기) |

### `db_05_binning.csv` — 구간별 불량률

멘토 지시("임계값성 패턴은 선형 상관으로 안 잡힘")에 따른 구간화 분석.

`lift_vs_overall`이 **1보다 크면 그 구간이 평균보다 위험**합니다.

### `db_00_metadata.json` — 실행 정보 및 한계

**Agent는 보고 전에 반드시 `known_limitations`를 확인해야 합니다.**

---

## 방법론 요약

| 단계 | 방법 | 출처 |
|---|---|---|
| 전처리 | OPCOND 층 OK-baseline median/MAD 강건 z-score | 김시우 `pipeline/` (d39bbff) |
| 통계 ① | Mann-Whitney U + BH-FDR + Cliff's delta (≥0.2) | Jun Goal2 |
| 통계 ② | RandomForest permutation importance (top-10) | Jun Goal2 |
| 비선형 | \|z편차\| 기준 검정 (U자형 탐지) | 멘토 지시 |
| 위험선 | DecisionTree stump (depth=1) | Jun C유형 |
| 오염검증 | primary / broad / **pure** 삼중 라벨 대조 | 본인 확장 |

**미사용**: 전성재 브랜치 방법론(L1 로지스틱 / HistGradientBoosting / Machine 통제 다변량)

---

## 핵심 설계 결정 3가지

### 1. Response는 "원인"이 아니라 "감시지표"
절단 폭이나 표면 거칠기는 **조절할 수 있는 값이 아닙니다.** 레이저·블레이드 설정의 결과죠.
그래서 `role` 컬럼으로 명확히 구분했습니다 — Agent가 "이걸 조치하세요"라고 잘못 안내하지 않도록.

### 2. `pure` 라벨로 오염 제거
Micro_Crack의 **57.7%가 Chipping과 동시발생**합니다. 그냥 분석하면 Chipping 원인이 섞여 들어와요.
`Chipping==0`인 행만 쓴 `pure` 라벨을 만들어, broad에서만 보이고 pure에서 사라지는 신호는
**`contaminated_by_*`로 판정**했습니다.

### 3. 현업 도메인 제약을 코드에 명시
**"Micro_Crack은 레이저 그루빙 문제가 아니다"** — 이 지식에 따라 그루빙 단계 컬럼을
Micro_Crack 후보에서 제외했습니다. (`is_laser_grooving` 컬럼으로 추적 가능)

물리적 근거: 레이저 HAZ는 scribe lane 안에 국한되고, **그 자리는 블레이드가 지나가며 제거**됩니다.
미세균열은 블레이드 절삭 응력·진동에 의한 **기계적 파괴**입니다.

---

## 데이터

| | 원본 | r1 (멘토 신규) |
|---|---|---|
| 행 수 | 100,000 | 100,000 |
| Chipping | 4건 | 24,171건 |
| Micro_Crack | 41건 | 15,372건 |

**통합 근거**: `Lot_ID+Strip_ID` 키가 8.6%만 겹침 → 독립 표본
**원본만으로는 분석 불가** (Chipping 4건). r1이 있어야 통계가 성립합니다.

---

## 재생성

```bash
python agent_db/build_relationship_db.py
```

김시우님 `pipeline/` 규약이 바뀌면 스크립트 상단 config 블록을 동기화한 뒤 재실행하세요.
