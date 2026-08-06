# ⚠️ 1세대 — 사용하지 않습니다

여기 있는 파일은 **도메인 게이트를 적용하기 전(1세대)** 산출물입니다.
**이력 보관용이며, Agent나 분석에 쓰지 마세요.**

현재 쓰는 것은 상위 폴더의 **`rel_20_tier_table.csv`** 와 **`agent_cause_factors.json`** 입니다.

---

## 왜 안 쓰나

| | 1세대 (여기) | 2세대 (상위 폴더) |
|---|---|---|
| 후보 선정 | 담당자 판정 + Jun 교차대조 | **확정 도메인 11건만** |
| 티어 이름 | `C1~C3` / `M1~M3` / `P1~P2` | **`T1~T4` / `M1`** |
| 인과사슬 | 있음 | **없음** (멘토 지시: FDC-FDC 미연결) |
| Vibration | 원인 트랙에 포함 | **별도 알람 영역으로 분리** |
| 검정 가능성 | 없음 | **`testability` 반영** |

---

## 🔴 절대 실행하지 마세요

```
build_agent_payload.py
```

이 스크립트는 상위 폴더의 **`agent_cause_factors.json`을 같은 이름으로 덮어씁니다.**
실행하면 **1세대 판정으로 되돌아가고, main의 Agent가 옛 결론을 말하게 됩니다.**

`build_unified_relationship_db.py` · `build_full_db_extension.py` 도 마찬가지로 실행 금지입니다.

---

## 파일 목록

### 판정 (1세대)

| 파일 | 내용 |
|---|---|
| `rel_00_metadata.json` | 구 메타데이터 |
| `rel_01_factors.csv` | 담당자 판정 통합 143행 |
| `rel_02_relationships.csv` | 관계 그래프 |
| `rel_03_disputes.csv` | 교차대조 불일치 9건 |
| `rel_12_tiers.csv` | **구 티어표** (`rel_20`이 대체) |

### 근거 자료

| 파일 | 내용 | 비고 |
|---|---|---|
| `rel_04_domain_knowledge.csv` | 도메인 지식 82행 | ⚠️ **철회된 Vibration→Micro_Crack 항목이 남아 있음** |
| `rel_05_thresholds.csv` | 위험 경계값 | `rel_20`에 포함돼 중복 |
| `rel_08_binning.csv` | 구간별 불량률 |
| `rel_11_method_agreement.csv` | 3방법 순위 대조 |

### 판정 밖

| 파일 | 내용 |
|---|---|
| `rel_06_sop_draft.csv` | Jun님 08-02 SOP 초안 (멘토 SOP는 미수령) |
| `rel_07_health_index_link.csv` | Goal5 연결표 — 김시우님이 이미 반영 완료 |
| `rel_09_shap_global.csv` `rel_10_shap_local.csv` | SHAP — 판정에서 제외(오탐 24건) |
| `rel_13_vibration_entanglement.csv` | Vibration 얽힘 — 추세분석 담당으로 이관 |

### 구 스크립트

`build_unified_relationship_db.py` · `build_full_db_extension.py` · `build_agent_payload.py`

---

## 이관 시점

2026-08-06 · 커밋 참조
