# DP Health Index 분석 가이드

이 분석은 **원인을 단정하는 모델**이 아니라, 도메인 가설을 데이터로 점검하고 다음 검증 대상을 좁히는 과정입니다. 원본 Excel은 변경하지 않습니다.

## 실행 방법

터미널에서 아래 한 줄을 실행합니다.

```bash
python3 analysis_step_by_step.py
```

실행이 끝나면 `analysis_outputs` 폴더에 표(CSV)와 시각화용 집계 데이터(JSON)가 생성됩니다.

## 단계 1 — 데이터 키와 정상군 확인

`01_data_validation.csv`를 엽니다.

- 분석키는 `Lot_ID + Strip_ID`입니다.
- `Strip_ID`만으로는 다른 LOT에서 재사용되므로 행을 합치거나 제거하면 안 됩니다.
- 정상군은 `Yield = 100` **그리고** `NG_Code = OK`입니다.

## 단계 2 — 도메인 가설 변수 만들기

원본값 외에 아래 변수를 만듭니다.

- `Cooling_Thermal_Load`: 냉각수 온도는 높고 유량은 낮은 상태를 하나의 값으로 표현합니다.
- `Laser_Cleaning_Demand`: Laser Power와 Groove Depth가 클수록 세정 부담이 증가한다는 가설입니다.
- `Cleaning_Capacity`: Flow, Pressure, Time을 함께 반영한 세정 능력 후보입니다.
- `Cleaning_Load_Ratio`: 세정 부담 대비 세정 능력입니다. 높을수록 Particle/Remain Coat 위험이 높다는 가설을 확인합니다.

## 단계 3 — 상관 후보 선별

`02_correlation_screen.csv`를 봅니다.

상관계수 절대값이 큰 칼럼은 **후보**일 뿐 원인 확정이 아닙니다. 특히 전체 상관이 큰 경우에도 Product/Recipe가 다르면 생기는 가짜 상관일 수 있습니다.

## 단계 4 — 영향 인자 순위

`03_impact_factor_ranking.csv`에서 defect별 상위 인자를 확인합니다.

- `Particle`, `Remain_Coat`, `Micro_Crack`, `Chipping`을 각각 별도 모델로 봅니다
  (`Edge_Burn`은 26.08.01 멘토 최종 확인 결과 유효한 실패모드가 아니라 분석 대상에서
  제외됨 — `pipeline/config.py`의 `MENTOR_EXCLUDED_DEFECTS` 참고).
- `Micro_Crack`(41건)/`Chipping`(4건)은 이 스크립트의 층별(Machine×Product×Recipe) 비교
  방식으로는 표본 부족으로 결과가 안 나올 수 있습니다 — 실행 시 콘솔 경고를 확인하세요.
  이 두 defect는 행 단위 검정(Jun/윤진혁의 Goal2 CRACK/CHIP 분석 참고)이 더 적합합니다.
- `Machine_ID`, `Product_ID`, `Recipe_ID`를 함께 통제합니다.
- `absolute_effect`가 큰 칼럼부터 도메인 가설, 공정 로그, 현장 확인 대상으로 삼습니다.
- 이 표는 인과관계를 증명하지 않습니다. 상위 인자는 후속 검증 우선순위입니다.

## 단계 5 — 공식 SPEC이 없을 때의 경보 기준

`04_provisional_control_limits.csv`는 Product×Recipe별 정상군의 0.5~99.5 분위수를 제공합니다.

이는 공식 합불 SPEC이 아닌 **임시 통계 경보 기준**입니다. 값이 범위 안에 있어도 지속 상승·하락하면 열화 후보로 봅니다.

## 단계 6 — 설비 열화 추세와 품질 결과 연결

`05_machine_daily_trend.csv`를 봅니다.

예를 들어 특정 장비의 `Head_Temp_7d_ma`가 상승한 뒤 `Yield_7d_ma`가 하락하거나 `Chipping_rate`/`Micro_Crack_rate`가 상승하는지 확인합니다. 반드시 같은 Product/Recipe 조건으로 다시 나누어 재확인해야 합니다.

## 시각화 읽는 법

대화에 표시된 시각화에서 Normal과 NG response 분포의 겹침, 장비별 Head Temp와 Yield의 7일 이동평균을 확인합니다. 분포가 많이 겹치면 해당 response 하나만으로 NG를 판정하기 어렵습니다. 추세 변화는 같은 Product/Recipe 조건으로 다시 나누어 확인합니다.

## 다음 단계

상위 영향 인자와 실제 공정 조치가 연결되면 아래 순서로 SOP를 정합니다.

1. 경보 변수와 경보 수준 정의
2. 같은 Product/Recipe에서 재현성 확인
3. 작업자 확인 항목 및 조치 순서 정의
4. 조치 후 Particle/Remain Coat/Yield 개선 여부 확인
