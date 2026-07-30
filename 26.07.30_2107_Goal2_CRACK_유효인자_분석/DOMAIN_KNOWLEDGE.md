# Goal 2 (CRACK 유효인자) 도메인 지식 · 판단기준 · 논리 정리

`crack_influence_factors.py`의 `DOMAIN_HYPOTHESIS` / `NOT_RELATED_TO_DEFECT` /
`TEAM_UNDETERMINED` 딕셔너리와 1:1로 대응한다. 방법론은 BURN/PARTICLE/REM_COAT와 동일 —
자세한 통계 기준/verdict 로직은
[BURN의 DOMAIN_KNOWLEDGE.md](../26.07.30_2001_Goal2_BURN_유효인자_분석/DOMAIN_KNOWLEDGE.md)
7~8절 참고. 이 문서는 **표본이 34건뿐이라는 특수성**을 계속 강조한다.

## 1. 공정 배경과 이번 defect의 특수성

Micro_Crack(미세균열)은 재료의 파단강도를 넘어서는 스트레스가 가해질 때 생긴다.
열충격(급격한 온도변화)과 기계적 피로(반복 응력) 두 축이 핵심 후보 메커니즘이다.

**중요**: 팀 HealthIndex 설계서는 Crack에 대한 명시적 서술이 거의 없다 — 회의록/멘토링
근거가 주로 Chipping("나이프자국형 대형불량"), Remain_Coat(세정), Burn(파워/방열) 위주로
남아있고, Crack 전용 메커니즘은 문서화되지 않았다. 그래서 아래 도메인 가설 대부분은
레이저가공 일반 물리 원리에서 출발한 **작성자의 추론**이며, 각 항목에 이를 명시한다.

## 2. 라벨 정의 논리

- `is_crack_primary` = `NG_Code=='CRACK'` (34건, 0.034%)
- `is_crack_broad` = `Micro_Crack==1` (41건, 0.041%)

차이 7건은 PARTICLE(5)/REM_COAT(1)/CHIP(1)과 동시발생. 표본이 워낙 작아 이 겹침
패턴 자체의 신뢰도도 낮다는 걸 감안해야 한다.

## 3. 메커니즘별 도메인 가설 (`domain_status = defect_related`, 17개, 전부 "제 추론")

| 메커니즘 | 컬럼 | 방향 |
|---|---|---|
| 에너지 투입(열충격) | `Laser_Power`, `Power_Efficiency` | up / either |
| 방열 능력(열충격) | `Head_Temp`, `Cooling_Flow`, `Cooling_Water_Temp`, `Cooling_Thermal_Load`(팀 피처) | up / down / up / up |
| 빔 품질(응력 집중) | `Focus`, `Beam_Diameter`, `Laser_Centering_Position` | either |
| 기계적 스트레스 | `Vibration`(진동 피로), `Feed_Speed`(기계적·열적 스트레스가 상충) | up / either |
| 열피로 | `Frequency`(펄스 반복 피로) — **통계로 강하게 확인됨(4절)** | up |
| 누적 노출 | `Process_Time`, `Alignment_Time` | up |
| 응력 집중(구조) | `Groove_Depth`(그루브가 깊을수록 절단 팁에 응력 집중 가능성) | up |
| 헤드 노후 | `Laser_Head_Remain_Time` | down |
| 결과 공변 | `Surface_Roughness` — **통계로 확인됨(4절)** | up |

이 표의 방향 가설은 전부 열충격/기계적 피로라는 **일반 물리 원리**에서 도출한 것이지,
회의록·멘토링에서 Crack에 대해 직접 확인된 서술이 아니다.

## 4. 실제 통계 결과와의 대조 (n=34, 극도로 조심스럽게 읽을 것)

| 컬럼 | 가설 방향 | 관측 effect size(Primary) | 해석 |
|---|---|---|---|
| `Frequency` | up | **0.856**, p≈2.2e-16 | BURN 분석 1위 변수와 동일. 펄스중첩→열축적이 Burn뿐 아니라 Crack에도 걸린다는 건, 두 defect가 부분적으로 같은 근본원인(열)을 공유할 가능성을 시사 — Health Index 설계 시 참고할 만함 |
| `Surface_Roughness` | up | **0.417**, p≈5.0e-4 | 확인됨. 결과 공변 후보 |
| `Kerf_Width_Profile`(도메인 지지 없음) | — | 0.252, p≈0.054(경계) | **재검토 필요**. 절단 폭은 파단과 별개 메커니즘이라고 판단해 무관 처리했는데, 두 방법 모두 상위권으로 나옴. "그루브가 예상보다 넓으면 절단 팁 응력이 커진다"는 가설로 재해석 가능 — 제 최초 판단이 틀렸을 수 있는 사례 |

## 5. Crack과 무관하다고 판단한 컬럼 (`not_related_to_defect`, 18개)

- **정렬/센터링 계열**(8개: `Cutting_X/Y_Index`, `Cutting_Offset`, `Kerf_Angle`,
  `Package_Size_1~4`) — 위치 정확도 문제, 파단 스트레스와 무관
- **절단 폭 계열**(3개: `Kerf_Width_Profile`, `Top_Kerf`, `Bottom_Kerf`) — **4절에서
  이 판단에 대한 반증(candidate_needs_domain_review)이 나왔으니 다음 라운드에 재검토**
- **세정/코팅 계열**(7개: `CLN_Flow`, `CLN_Pressure`, `CLN_Time`, `Coating_Flow`,
  `Cleaning_Capacity`, `Cleaning_Load_Ratio`, `Laser_Cleaning_Demand`) — Particle/
  Remain_Coat 전용 메커니즘, 파단과 무관

## 6. 팀도 아직 결론 못 낸 컬럼 (`team_undetermined`, 4개)

`Laser_Current`, `Laser_Voltage`, `Coating_Thickness`, `Coating_Uniformity` — 다른
defect 분석과 동일한 이유(데이터 자체의 속성 문제).

## 7. 통계적 판단기준 / verdict 로직

BURN/PARTICLE/REM_COAT와 완전히 동일. 자세한 내용은 BURN의 `DOMAIN_KNOWLEDGE.md` 참고.

## 8. 알려진 한계 (이 defect에서 특히 중요)

- **표본 34건**은 Mann-Whitney/RandomForest 모두에게 매우 작은 숫자다. FDR 보정,
  train/test 분할(20%면 test에 positive가 6~7개뿐), permutation importance 추정치
  모두 표준오차가 크다. 이 폴더의 `confirmed`는 다른 defect의 `confirmed`보다
  신뢰도가 명백히 낮다 — 팀에 보고할 때 반드시 표본 크기를 함께 명시할 것.
- 팀 문서에 Crack 전용 메커니즘 서술이 없어 도메인 가설표 전체가 "제 추론" 기반이다.
  멘토링에서 Crack 관련 실제 실패모드를 확인하면 이 표를 전면 재검토해야 한다.
- `Kerf_Width_Profile`의 무관 판단이 통계로 반박된 사례는 재검토 대상으로 명시적으로
  남겨둔다(4절).

## 출처

- `1주차/fdc_response_defect_parameter_discription.docx`
- `2주차/26.07.29_0242_HealthIndex_설계서_v2.docx` (Crack 관련 명시적 서술은 거의 없음)
- 데이터 자체 분석 결과 (`01_crack_rate_by_stratum.csv`, `02_univariate_test_results.csv`,
  `03_tree_importance.csv`)
