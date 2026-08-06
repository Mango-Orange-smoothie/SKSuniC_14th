# Trend Analysis — 팀 공유 문서

## 1. 개요
장비 센서 값을 계속 관찰하다가 "지속적으로 나빠지는 추세"를 조기에 탐지하는 모듈이다. 실제 불량이 나기 전, Spec을 아직 안 벗어난 시점에도 경고를 낼 수 있는 게 핵심 목적이다.

## 2. 파일 위치
- 코드: `trend_analysis.py` (프로젝트 루트)
- 실제 Spec(LSL/TARGET/USL): `spec.py`
- 결과: `analysis_outputs/trend_analysis_results.csv` (전체, 용량 문제로 GitHub 미반영)
- 유형별 결과(GitHub 반영됨): `analysis_outputs/trend_early_warning_{A,B,C,E,S}.csv`
- 교차검증 결과: `analysis_outputs/trend_cross_validation.csv`
- 성능 검증: `Goal4_Performance_Validation/` (Spec vs Trend 비교, ROC/PR curve, 임계값 보정 실험)
- 실행: `python trend_analysis.py` (다른 팀원 파일 수정 없이 읽기 전용으로 동작)

## 3. 입력 의존성
- `HealthIndex_Dataset.csv`, `DP_HealthIndex_Dataset_r1.csv` (원본 데이터 2종)
- `analysis_outputs/preprocessing/00_column_classification.csv` (분석 대상 변수 목록)
- `26.07.29 Baseline 관련 작업/` 아래 Baseline_AB/C/E 3개 (정상 기준값)
- `analysis_outputs/preprocessing/00_stratum_baseline_stats_by_opcond.csv` (표준편차 대체용)
- `analysis_outputs/preprocessing/00_machine_column_trend.csv` (자체 교차검증용)
- `spec.py` (실제 Spec 10개 변수)

## 4. 판정 유형 (5가지)

| 유형 | 대상 | 판단 방식 |
|---|---|---|
| **S (실제 Spec)** | Laser_Power, Power_Efficiency, Laser_Centering_Position, Frequency, Feed_Speed, Head_Temp, Focus, Kerf_Width_Profile, Coating_Thickness, Coating_Uniformity (10개) | LSL/USL 이탈, 또는 아직 Spec 이내지만 한계선에 지속 접근, 또는 TARGET에서 지속 이탈 |
| **A (단조 열화형)** | Vibration 등 7개 | 초기 안정구간(OK) 대비 한 방향으로 지속 이탈 |
| **B (최적값형)** | Laser_Power 등 4개(스펙 있는 4개는 S로 이동) | 정상 중앙값에서 양방향 어디로든 지속 이탈 |
| **C (위험선형)** | CLN_Pressure, Surface_Roughness | 위험 Threshold 진입 또는 그 방향으로 지속 접근 |
| **E (이론상수형)** | Kerf_Angle 등 8개 | 물리적으로 정해진 값에서 지속 이탈 |

**S유형은 실제 공식 Spec이 확보된 변수에 한해 기존 A/B/E 분류를 대체한다** (데이터 기반 추정치보다 실측 Spec이 더 신뢰할 수 있는 기준이므로). 이전엔 기준이 아예 없어 판정 불가였던 Frequency/Feed_Speed/Coating_Thickness/Coating_Uniformity 4개도 이번에 처음 탐지 대상에 포함됐다.

## 5. 지속성 필터 (중요)
C유형(entered/approaching)과 S유형(entered/approaching), 변동성 경고는 **"최근 `PERSIST_WINDOW`행 연속 조건 만족"일 때만** 진짜 경고로 인정한다. 노이즈로 위험선 근처를 오락가락하는 것까지 매번 "새로 진입"으로 잡던 문제(Surface_Roughness 한 변수에서만 헛경보 다수 발생)를 막기 위함이다.

**`PERSIST_WINDOW = 3`으로 설정했다.** main 브랜치는 5를 쓰는데, 검증해보니 5는 노이즈는 잘 줄이지만 실제 탐지력(Recall)까지 과하게 깎아서(같은 시점 기준 Recall이 Spec보다도 낮아짐, F1=0.14) 3으로 낮춰 재검증했다. 3에서는 Precision/False Alarm Rate가 크게 개선되면서도(FAR 0.682→0.342) Recall은 적당히만 떨어져(0.940→0.738) F1이 오히려 좋아졌다(0.477→0.539).

## 6. 검증 상태
- 기존 산출물(`00_machine_column_trend.csv`, 일별 통계+Kendall tau 기반)과 교차검증: **140건 중 140건 일치 (100%)**
- 재실행 시 결과 완전히 재현됨

## 7. Spec vs Trend 성능 비교 (Goal4_Performance_Validation)

| 지표 | Spec | Trend (PERSIST_WINDOW=3) |
|---|---|---|
| Precision | 0.473 | 0.424 |
| Recall | 0.857 | 0.738 |
| F1-score | 0.610 | 0.539 |
| False Alarm Rate | 0.326 | 0.342 |

Trend가 Spec보다 아직 F1은 낮지만(더 많은 변수를 넓게 감시하는 대가), 격차는 지속성 필터 도입 전(F1 0.477)보다 크게 좁혀졌다.

## 8. 알려진 한계
- **원본 데이터 1개만 반영**된 main과 달리, 이 버전은 원본 2개(HealthIndex_Dataset.csv, DP_HealthIndex_Dataset_r1.csv)를 모두 처리한다. r1 반영 여부는 팀 결정에 따라 다를 수 있음.
- CLN_Pressure/Surface_Roughness(C유형)의 위험선 자체가 원본 데이터에서 OK/NG를 깔끔히 못 가르는 근본적 한계가 있음(최고 상관 변수도 r=0.28 수준) — 코드 문제가 아니라 데이터 자체의 한계.
- **"defect 발생"까지의 조기경보(리드타임)는 이 데이터 특성상 원천적으로 어렵다** — 단변량/다변량 모델 모두 defect 발생 자체는 리드타임이 거의 0에 가까움(그 순간 조건이 맞으면 바로 발생, 서서히 쌓이지 않음). 반면 **"Spec 경계를 넘는 순간"까지의 리드타임은 존재**하는 것으로 보인다(일부 변수는 며칠~몇 주 전부터 여유가 서서히 줄어듦) — 다만 표본이 작아 정성적 결론 수준.
- A유형 일부 컬럼(Alignment_Time, Process_Time, Cooling_Water_Temp 등)의 "악화 방향(up/down)" 가정이 실제 열화 방향과 맞는지 재검증이 필요함.

## 9. 활용 시 주의사항
- 다른 defect 원인분석/Health Index와 결합할 때는 `Machine_ID`+`Product_ID`+`Recipe_ID`+`DateTime`+`column` 기준으로 join
- C/S유형 결과는 `matched_defect` 컬럼으로 어떤 결함과 연결되는지 확인 가능(C유형만 해당)
- 결과 CSV엔 `early_warning=True`인 행만 저장되어 있음(용량 문제로 전체 행은 저장 안 함)
- `early_warning=True`가 많이 뜨는 게 "정확도가 높다"는 뜻은 아님 — 참고 신호로 활용 권장
