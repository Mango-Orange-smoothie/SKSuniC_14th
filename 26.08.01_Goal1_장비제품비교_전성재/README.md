# Goal 1 — 장비(Machine_ID) 비교 (전성재)

## 세 줄 요약

1. **DP04만 Remain_Coat 발생률이 1.48배 높은 이유는 CLN_Pressure가 아니라 CLN_Flow(세정 유량)입니다.** DP04의 CLN_Flow는 다른 3대보다 만성적으로 낮습니다.
2. 매개분석으로 확인: DP04라는 "장비 효과"는 CLN_Flow 하나로 **103% 설명**됩니다 — DP04라서 위험한 게 아니라 DP04의 CLN_Flow가 낮아서 위험한 것입니다.
3. r1(불량률 높인 새 데이터)에서 이 패턴이 **더 심하게 재현**됩니다(DP04 발생률 11배, CLN_Flow z-score -1.29).

바쁘시면 위 세 줄만 보셔도 됩니다.

---

## 배경

Goal2 REM_COAT 분석(`26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/`)에서 "DP04만 Remain_Coat
발생률이 다른 3대보다 1.6~1.8배 높다"를 발견했다. 이걸 REM_COAT 하나가 아니라 defect
6종 전체, 공정변수 40개 전체로 확장해서 DP04가 REM_COAT만 유독 심한 건지, 전반적으로
다른 장비인지 확인했다.

방법론은 `pipeline/README.md`의 Goal1 방법을 그대로 따른다: OPCOND(Product×Recipe)를
고정한 채(=OPCOND 층별 강건 z-score로 정규화) Machine_ID 그룹을 비모수 검정으로 비교
— OPCOND를 고정해야 "제품이 달라서 나는 차이"와 "장비가 달라서 나는 차이"가 안 섞인다.

## 1단계 — defect 6종 x 장비 4대 (`machine_comparison.py`)

카이제곱 검정(FDR 보정) 결과, 장비 간 차이가 유의한 defect는 **Remain_Coat, Particle
두 개뿐**이었다(Chipping/Edge_Burn/Laser_Paim/Micro_Crack은 장비 무관).

| defect | 특이 장비 | 발생률(전체 평균 대비) |
|---|---|---|
| Remain_Coat | **DP04** | 1.48배 |
| Particle | DP03/DP02 | 각 1.05배/1.02배 (DP04는 평균 수준) |

## 2단계 — 공정변수 40개 x 장비 4대 Kruskal-Wallis

40개 중 12개가 장비 간 유의한 차이를 보였다. **1위는 CLN_Pressure가 아니라 CLN_Flow**
(효과크기 0.113, 2위와 3배 이상 차이) — DP04의 CLN_Flow median z = -0.91 (다른 3대는
+0.13~0.14). 반대로 **CLN_Pressure는 장비 간 차이가 사실상 없다**(효과크기 ≈0, p=0.96,
40개 중 꼴찌권) — 9번 검증(선행신호 검사)에서 낸 "CLN_Pressure는 장비 무관하게 어디서나
순간적으로 튀는 즉시성 현상"이라는 해석과 정확히 일치한다.

## 3단계 — 심화검증 (`machine_mediation_analysis.py`)

**① DP04 vs 개별 장비 3대**: DP04는 DP01/DP02/DP03 각각과 개별적으로 CLN_Flow가 유의하게
낮다(Cliff's delta -0.45 전후, p≈0 x3) — 특정 장비 하나랑만 다른 게 아니라 나머지 전부보다
낮다.

**② 매개분석**: Remain_Coat를 Machine 더미만으로 설명하는 모델과, 거기에 CLN_Flow(+CLN_Pressure)를
추가한 모델을 비교했다.

| | DP04의 초과위험(오즈비) |
|---|---|
| CLN_Flow 보정 전 | 1.70배 |
| CLN_Flow 보정 후 | 0.98배 (사실상 소멸) |
| **초과위험 감소율** | **103%** |

CLN_Flow 하나로 "DP04 효과"가 통계적으로 완전히 사라진다 — 교과서적인 매개효과 패턴.

**③ r1 재현**: 불량률을 3배 높인 새 데이터에서도 동일 패턴이 더 뚜렷하게 재현된다.

| | DP01~03 | DP04 |
|---|---|---|
| Remain_Coat 발생률 | ~2.1% | **23.4%** (11배) |
| CLN_Flow median z | +0.10 | **-1.29** |
| CLN_Pressure median z | -0.02~0.00 | -0.02 (여전히 차이 없음) |

## 결론 및 실무 제안

- **DP04의 REM_COAT 과다 발생 원인은 CLN_Flow(세정 유량) 만성 저하**이며, 통계적으로
  DP04 효과를 100% 이상 설명한다.
- **DP04 개별 설비 점검(노즐 막힘/펌프 노후 등)이 최우선 실무 조치**로 제시할 수 있는
  수준의 근거.
- **미해결 질문**: DP04의 CLN_Flow가 왜 만성적으로 낮은지는 데이터만으로는 알 수 없다
  — 정비팀/현업 확인 필요.

## 산출물

| 파일 | 내용 |
|---|---|
| `01_defect_rate_by_machine.csv` | defect 6종 x 장비 4대 발생률 + 카이제곱 검정 |
| `02_continuous_kruskal_by_machine.csv` | 공정변수 40개 x 장비 Kruskal-Wallis |
| `03_top_variable_machine_medians.csv` | 유의 변수들의 장비별 median z |
| `04_step1_dp04_pairwise_cln_flow.csv` | DP04 vs 개별 장비 pairwise 비교 |
| `05_step2_mediation_result.json` | 매개분석 결과 |
| `06_step3_r1_replication.json` | r1 재현 결과 |
| `00_summary.json`, `00b_deep_verification_summary.json` | 실행 메타데이터 |

## 실행 방법

```bash
python "26.08.01_Goal1_장비제품비교_전성재/machine_comparison.py"
python "26.08.01_Goal1_장비제품비교_전성재/machine_mediation_analysis.py"
```

`pipeline/config.py`, `pipeline/common.py`만 재사용, 원본 데이터/공용 pipeline 파일은
수정하지 않았다.
