# pipeline/ — Step 0 전처리 & 다운스트림(Goal 1~6) 활용 가이드

이 폴더는 6개 목표(① 장비/제품 비교, ② 유효인자 발굴, ③ 상호작용, ④ 이상치/열화 탐지,
⑤ Health Index, ⑥ SOP 초안)를 분업할 때 **모두가 공통으로 딛고 설 전처리 결과물**을 만든다.
원본 `DP_HealthIndex_Dataset.csv`나 기존 `analysis_step_by_step.py` /
`full_correlation_analysis.py`는 건드리지 않는다 — 이 파이프라인은 그 위에 추가되는 것이다.

## 환경 설정

저장소 루트(`suni c 14조/`)에서 실행:

```bash
pip install -r requirements.txt
```

## 실행 방법

저장소 루트에서 실행 (반드시 `pipeline.` 모듈 형태로 — `python pipeline/step0_preprocessing.py`처럼
직접 실행하면 `from pipeline import config` import가 깨진다):

```bash
python3 -m pipeline.step0_preprocessing
```

`analysis_outputs/preprocessing/`에 아래 10개 파일이 생성된다 (10만행 기준 약 8초 소요).

| 파일 | 내용 |
|---|---|
| `00_column_classification.csv` | 68개 원본 컬럼 전체의 분류(서브시스템/타입/역할/변동성/추세/제외여부) |
| `00_machine_daily_series.csv` | (장비, 연속형 컬럼, 날짜)별 OPCOND 정규화 일별 집계 시계열 — **추세/조기경보 분석 공용 입력(아래 설명)** |
| `00_machine_column_trend.csv` | (장비, 연속형 컬럼)별 89일 전체 추세검정 요약 (Mann-Kendall tau/p, OLS 기울기/p) |
| `00_missing_sensor_fault_flags.csv` | 결측/물리적으로 불가능한 0값/flatline(센서 고착) 플래그 |
| `00_stratum_baseline_stats_by_opcond.csv` | Product×Recipe grain OK-baseline (mean/std/median/MAD/분위수) |
| `00_stratum_baseline_stats_by_machine_opcond.csv` | Machine×Product×Recipe grain OK-baseline |
| `00_baseline_AB.csv` | A(단조 drift형)/B(U자형·최적구간형) 컬럼 Baseline (Jun `26.07.29 Baseline 관련 작업/` 이식, 아래 설명) |
| `00_baseline_C.csv` | C(편측 위험 threshold형) 컬럼의 결정트리 기반 위험 경계값 (Jun 이식) |
| `00_baseline_E.csv` | E(대칭성/정렬형) 컬럼의 이론 상수 Baseline (Jun 이식) |
| `00_preprocessing_summary.json` | 행 수/키/정상군 assert 결과 + 다운스트림 기본 포함 컬럼 목록 |

### `00_baseline_AB.csv` / `00_baseline_C.csv` / `00_baseline_E.csv` — Jun의 baseline 이식 (26.08.04)

원래 Jun 브랜치 `26.07.29 Baseline 관련 작업/`에 독립 스크립트(`compute_baseline_AB.py` 등)로
따로 있던 A/B/C/E 열화 패턴 유형별 baseline을 Step0로 흡수했다. 그룹핑은 Jun의 원본 결정을
그대로 따라 `Product_ID x Recipe_ID`(Machine_ID 배제, 이유는 `config.py` 주석 참고)다.

- **A(단조 drift형, 9개)**: 그룹별 OK median(SPEC에 있는 컬럼은 멘토 TARGET 우선,
  `compute_baseline_type_a` 참고) + `bad_direction`(up/down).
  (26.08.05 정정: 이 문서에 "초기 25개 표본 평균"으로 적혀 있었는데, 그 방식은 초기값이
  가장 깨끗한 시점에 편향되는 문제가 있어(Vibration/Head_Temp 같은 열화형 변수에서 OK
  median보다 0.44~0.93 표준편차 낮게 나옴) 진작 B와 같은 OK median 방식으로 바꿨었다 —
  문서만 안 따라와서 정정. 같은 날 Groove_Depth도 여기 추가됨: Chipping 확정 원인인데
  A/B/C/E 어디에도 분류가 안 돼서 trend_analysis.py가 방향성 조기경보를 못 내고
  있었음(변동성 경보만 가능했음) — 단일방향 편차형이라 A유형이 맞아서 추가.)
- **B(U자형/최적구간형, 8개)**: 그룹별 OK median. CLN_Time은 원래 C 후보였으나 위험 방향이
  그룹마다 불일치해(54그룹 중 29/25로 갈림) B로 재분류됨.
- **C(편측 위험 threshold형)**: `CLN_Pressure→Remain_Coat`, `Surface_Roughness→Particle` 두 쌍만
  대상. OK 데이터만으로는 위험선을 추정할 수 없어(정상 범위 내부 분포만으로는 어디부터 위험한지
  모름) **OK+NG 전체 데이터**로 `DecisionTreeClassifier(max_depth=1)` 스텀프를 그룹별로 학습해
  경계값(threshold)과 위험 방향(risky_direction)을 추정한다. NG 표본이 10개 미만인 그룹은 skip.
  Groove_Depth는 매칭 defect(Chipping)가 전체 4건뿐이라 이 산출물에서는 계속 제외(위 A유형
  참고 — 표본 부족 문제가 없는 A유형으로 대신 편입함).
- **E(대칭성/정렬형, 9개)**: 그룹핑 없이 공정 설계상 이론 상수(대부분 0, Kerf_Angle=90,
  Package_Size_1~4=5)를 baseline으로 고정. 참고용으로 실측 OK mean/std도 같이 기록.

**주의(OK 정의 차이)**: 위 3개 파일의 A/B/E는 Jun 원본 값을 그대로 재현하기 위해
`df_normal`(`is_normal` = Yield==100 & NG_Code=='OK')이 아니라 Jun이 썼던
`NG_Code=='OK'`만으로 별도 필터링한다 — Step0의 다른 산출물(`00_stratum_baseline_stats_*` 등)
보다 느슨한 정의라는 점에 유의. C는 애초에 OK/NG 구분 없이 전체 df를 사용한다.

### `00_machine_daily_series.csv` — 왜 추가했는지 (26.08.02)

추세/조기경보 분석에서 원본 행(샷) 단위로 직접 rolling window를 돌리면, 이 데이터셋은
Machine×Product×Recipe로 쪼갤 때 하루 평균 샷 수가 **5개 안팎**이라 "10개 윈도우"가
실제로는 1~2일치밖에 안 된다. 실측 검증 결과, 이 데이터셋에서 가장 확실한 장기 drift
(`DP02 Laser_Power`, 89일 전체 Kendall tau=-0.74, p≈2×10⁻²⁴)조차 **최근 30일만 잘라
보면 통계적으로 안 잡힌다**(p=0.32) — 45일은 돼야 다시 유의해진다(p=0.014). 즉 일별
집계 없이 짧은 샷 단위 윈도우로 장기 drift를 잡으려는 접근은 이 데이터 특성상
구조적으로 어렵다.

그래서 Step0에서 **미리 날짜 단위로 집계·정규화한 시계열**을 공용 산출물로 내보낸다.
`compute_machine_daily_series()`가 `00_machine_column_trend.csv`(89일 전체 1회 검정)를
만들 때 내부적으로 쓰던 일별 z-잔차 시계열을 그대로 노출한 것 — 새로 계산한 게 아니라
기존에 버려지던 중간 결과를 저장한 것뿐이다. 컬럼: `Machine_ID`, `column`, `date`,
`n_shots`(그날 표본 수), `daily_mean`(원값 일평균), `daily_mean_z`(OPCOND 정규화
z-잔차 일평균).

**권장 사용법**: 추세/조기경보 분석(rolling window, 조기경보 임계값 등)은 이 파일의
`daily_mean_z`를 입력으로 rolling을 돌릴 것 — 원본 행에서 직접 rolling하지 말 것.
날짜 단위로 이미 노이즈가 눌려 있어 같은 윈도우 크기로도 더 안정적인 신호를 준다.
(이 파일 생성 자체는 전처리 담당 소관, 그 위에 얹는 rolling/조기경보 판정 로직은
추세분석 담당 소관 — 역할 분리.)

## 공통 로드 패턴

Goal 모듈을 새로 만들 때는 아래처럼 `pipeline.config`/`pipeline.common`을 import해서 쓴다.
KEY/GROUP/OPCOND/NORMAL 정의를 각자 다시 만들지 말 것 — 층(stratum) 정의가 모듈마다
미묘하게 어긋나는 사고를 방지하기 위한 것이다.

```python
from pipeline import config
from pipeline.common import load_dataset, save_table, zscore_transform, compute_stratum_baseline_stats

df = load_dataset()  # DateTime 파싱 + is_normal 컬럼 + 4개 도메인 피처 자동 포함
classification = pd.read_csv("analysis_outputs/preprocessing/00_column_classification.csv")
feature_cols = classification.loc[classification.include_in_downstream_default, "column"].tolist()
```

## 핵심 개념 두 가지

- **`GROUP = [Machine_ID, Product_ID, Recipe_ID]`** (기존 `analysis_step_by_step.py`와 동일):
  Machine을 "통제/공변량"으로 두고 defect 영향도 등을 볼 때 사용. 예: 기존
  `analysis_outputs/03_impact_factor_ranking.csv`가 이 방식.
- **`OPCOND = [Product_ID, Recipe_ID]`** (신규, 멘토 피드백 반영 — Strip_ID/Lot_ID는
  운전조건이 아니므로 무시): Machine을 "비교 대상"으로 두거나(Goal1), Machine-무관
  baseline이 필요할 때(Goal4/5 정규화) 사용.

두 grain의 baseline 파일이 모두 존재하는 이유가 이것이다 — 질문 성격에 맞는 쪽을 골라 쓴다.

## 멘토 피드백 반영 (26.07.31)

- **분석 제외 변수 추가**: `Focus`, `Cutting_Offset`은 멘토가 "분석에 활용하지 않아도 된다"고
  명시적으로 지정한 변수. `00_column_classification.csv`에서 `analysis_role=mentor_excluded`,
  `include_in_downstream_default=False`로 반영됨. **주의**: Jun의 BURN 분석(Goal2)은 이 변경
  이전에 실행되어 `Focus`를 도메인 후보로 이미 포함하고 있음 — 재실행 여부 판단 필요.
- **`Frequency` 재분류**: `fdc_motion` → `fdc_laser`로 이동 (멘토가 레이저 변수로 확인). 후보
  컬럼 목록 자체(FDC_COLS)는 안 바뀌므로 기존 분석 결과에 영향 없음, 분류만 정정됨.
- **`Laser_Head_Remain_Time` 참고사항**: 잔여시간이 적거나 특정 시점(교체/오버 시점)을 지날 때
  불량이 나는 **임계값성 패턴**이 있을 수 있다는 멘토 코멘트. 단순 선형 상관(Mann-Whitney 등)만
  보지 말고, 잔여시간을 구간화(binning)해서 구간별 불량률을 비교하는 방법도 함께 검토할 것 —
  `00_column_classification.csv`의 해당 행 `decision_note`에도 남겨둠.

## 멘토 피드백 2차 반영 (`FDC_전처리_멘토링_정리.md` 기준, 26.07.31)

- **재확인 대기 중인 컬럼 4개** (`mentor_pending_review=True`, 제외하지 않고 경고만 추가):
  `Bottom_Kerf`(다른 kerf 컬럼과 값 중복 가능성), `Surface_Roughness`(drop 여부 미확정 — Jun의
  BURN/PARTICLE/CRACK confirmed 목록에 이미 등장하므로 주의), `Cooling_Flow`/`Cooling_Water_Temp`
  (설비-컬럼 매핑 재확인 예정).
- **`Power_Efficiency`**: 비선형(U자형/최적구간) 특성 — 단순 선형 상관만으로 판단 금지.
- **`Vibration`**: 설비 열화의 대표 신호(실제 대형 스크랩 사고 사례 있음) — **Health Index(Goal5)
  핵심 후보 변수**로 우선 고려할 것.
- **`Kerf_Width_Profile`/`Top_Kerf`/`Groove_Depth`**: "7㎛ 기준점"이 이 합성 데이터에서는 실제
  물리 상수가 아닐 수 있음 — 하드코딩 금지, baseline은 데이터 분포에서 역산 (Step0의 OK-baseline
  방식이 이미 이 원칙을 따르고 있음).
- **`Package_Size_1~4`**: 센터링 이상 시 비대칭 패턴이 생긴다는 도메인 힌트를 신규 팀 공용
  피처 **`Package_Size_Asymmetry`**(4개 값의 행별 표준편차)로 수식화해서 `config.DOMAIN_FEATURES`
  에 추가함 (어느 번호가 어느 방향인지 몰라도 계산 가능).
- **`Head_Temp`/`Cooling_Flow`/`Cooling_Water_Temp`/`Laser_Centering_Position`**: 멘토가 설명한
  인과사슬(Head_Temp→크리스탈 스팟 온도→굴절률→센터링 변화→Chipping/Kerf 불균일) 가설 —
  Goal3(상호작용) 담당자는 이 4개를 묶어서 다변량으로 분석하는 것을 우선 고려할 것.

## 멘토 피드백 3차 반영 — `Edge_Burn` 최종 제외 확정 (26.08.01)

- **`Edge_Burn`, `Edge_Burn_Die`를 defect 분석 대상에서 최종 제외했다.** 멘토 재확인 결과
  유효한 실패모드가 아님이 확정됨. `00_column_classification.csv`에서
  `analysis_role=mentor_excluded_defect`, `is_mentor_excluded_defect=True`,
  `include_in_downstream_default=False`로 반영됨.
- **⚠️ 팀 전체 영향— 반드시 확인할 것**: Jun의 Goal2 BURN 분석
  (`26.07.30_2001_Goal2_BURN_유효인자_분석/`)은 `NG_Code=='BURN'`/`Edge_Burn==1`을 라벨로
  써서 만든 것이라 **이번 제외 결정으로 전체가 무효화된다.** confirmed factors였던
  `Frequency`, `Thermal_Load_Ratio`, `Top_Kerf`, `Kerf_Width_Profile`, `Surface_Roughness`는
  더 이상 "BURN 유효인자"로 제출하면 안 됨.
- **팀 결정(26.08.01)**: BURN 관련 폴더/코드는 삭제하지 않고 **그대로 두되 더 이상 사용하지
  않는다** (아카이브 취급, 별도 정리 작업 불필요).
- 원본 데이터의 `Edge_Burn`/`Edge_Burn_Die` 값 자체는 지우지 않았다(추적성 보존) — 분석
  피처셋에서만 빠진다.

## r1(신규) 데이터셋 정책 (26.08.01)

멘토가 준 `DP_HealthIndex_Dataset_r1.csv`(정상군 58.9%, 원본 대비 불량률 대폭 상향, `LASER`
신규 NG_Code 포함)는 **`data/raw/`의 원본 데이터와 합치지 않는다.** 원본 기준 극희귀
defect(예: Chipping 4건, Micro_Crack 41건)의 표본 부족을 보완하는 **학습/검증 전용
데이터**로만 쓴다 — JHdaimma가 Chip/Crack confirmed factor를 원본·r1 양쪽에서 재현되는지
교차검증하는 데 이미 이렇게 쓰고 있다(`analysis_v2_kimsiwoo_jun/` 폴더 참고).

- `pipeline/`(Step0), `analysis_step_by_step.py`, 이 대시보드(`26.08.01_Goal5_...`)를 포함한
  **팀 공용 산출물은 계속 원본 데이터 기준으로만 유지**한다.
- r1을 쓰는 개인 분석은 결과에 "r1 기준"임을 명시하고, 원본 기준 결과와 나란히 놓고
  "재현되는지"만 확인하는 용도로 한정할 것 — r1 결과 단독으로 팀 공식 유효인자를 바꾸지 않는다.
- r1 원본 파일은 용량 때문에 git에 커밋하지 않는다(JHdaimma README와 동일 방침).

## 추가 피처 엔지니어링 도구 (26.08.02)

단순 선형 상관/z-score만으로는 U자형 비선형, 임계값 반응, 누적 열화(drift) 관계를
못 잡는 경우가 많다는 도메인 지적을 반영해 `pipeline/common.py`에 3개 함수를 추가했다.
어떤 컬럼에 적용할지는 도메인 판단이 필요해 강제 적용하지 않고, Goal 담당자가 필요할
때 갖다 쓰는 도구로 남겨둔다.

- **`add_spec_deviation_features(df, baseline_long, stratum_keys, columns)`** — 공식
  SPEC이 없는 데이터셋이라 OK군의 층별 0.5~99.5 분위수(`compute_stratum_baseline_stats`가
  이미 계산해둔 `p0_5`/`p99_5`)를 임시 USL/LSL로 삼아 `max(0, X-USL) + max(0, LSL-X)`
  이탈량 피처를 만든다. `Power_Efficiency`처럼 "높아도 낮아도 위험"한 either 방향
  변수는 부호 있는 z-score로는 상쇄되어 사라지므로, 이 방식이 필요하다.
- **`add_ratio_features(df, {새_컬럼명: (분자, 분모)})`** — 두 변수의 비율/상호작용
  피처(0나눔 방지 포함). 예: `Bottom_Kerf`/`Top_Kerf`로 절단면 기울기 경향 포착.
- **`add_rolling_trend_features(df, group_col, time_col, columns, window=5)`** —
  장비별 시간순 rolling mean/std + 직전값 대비 delta. `Cooling_Water_Temp`,
  `Laser_Head_Remain_Time`처럼 단발성 수치는 정상이어도 서서히 누적되며 불량으로
  이어지는 경우를 잡기 위함. `00_machine_column_trend.csv`의 전체기간 1회 검정과
  달리 날짜별로 값이 실제로 움직인다.

세 함수 다 실제 데이터로 동작 검증 완료(스펙이탈 발생률 ~1%, ratio에 inf/NaN 없음,
rolling이 행 순서/개수 보존).

### `add_spec_deviation_features`의 "임시 USL/LSL"이 정확히 뭔지

이 데이터셋엔 공식 설비 스펙(USL/LSL) 컬럼이 없다. 그래서 실제 스펙 대신 아래 방식으로
**대체값**을 만들어 썼다 — 팀 전체가 이 값의 의미를 정확히 알고 써야 해서 상세히 남긴다.

**정의**: 정상군(OK, `Yield=100` & `NG_Code='OK'`)의 분포에서, Product×Recipe(`OPCOND`)
층별로 하위 0.5%/상위 0.5% 지점을 각각 임시 LSL/USL로 쓴다.

```
LSL(임시 하한) = 그 OPCOND 층에서 OK행들의 값 중 하위 0.5% 지점
USL(임시 상한) = 그 OPCOND 층에서 OK행들의 값 중 상위 0.5% 지점
spec_exceedance = max(0, X - USL) + max(0, LSL - X)   (범위 안이면 0)
```

**왜 이렇게 했나**: "정상적으로 나온 값들이 실제로 어디까지 퍼져 있었는지" 그 범위를
스펙처럼 빌려 쓰자는 논리다. OK군의 99%가 이 구간 안에 있었으니, 벗어난 값(위+아래
합쳐 1%)은 "정상 범위를 벗어난 이례적인 값"으로 볼 수 있다. Product×Recipe별로 따로
계산하는 이유는 레시피마다 정상 범위 자체가 다르기 때문 — 전체를 뭉치면 왜곡된다.

**새로 만든 게 아니라 재사용한 것**: `04_provisional_control_limits.csv`(김시우,
`Coating_Uniformity`/`Surface_Roughness` 2개 컬럼에만 좁게 적용)와 같은 철학을,
Step0의 `compute_stratum_baseline_stats()`가 이미 전체 FDC/response 컬럼에 대해
층별 `p0_5`/`p99_5`로 일반화해서 `00_stratum_baseline_stats_by_opcond.csv`에
계산해둔 상태였다. `add_spec_deviation_features()`는 그 기존 결과를 그대로 갖다 써서
이탈량만 계산하는 얇은 함수다 — 새로 통계를 돌리지 않는다.

**한계 (반드시 알고 쓸 것)**:
- **진짜 공정 스펙이 아니다.** "정상적으로 나온 값의 범위"일 뿐, 설비 제조사나 공정
  엔지니어가 정한 물리적 한계치가 아니다. 정상 범위 안에 있어도 실제 설비 스펙상으론
  위험한 값일 수 있고, 반대로 스펙상 괜찮은데 이 기준으로 "이탈"로 잡힐 수도 있다.
- **0.5%라는 컷오프도 임의값이다.** 통계적으로 최적화한 게 아니라
  `04_provisional_control_limits.csv`에서 쓰던 값을 관례적으로 재사용했다.
- 그래서 함수/컬럼명에 `USL`/`LSL`을 직접 쓰지 않고 `spec_exceedance`라고만 이름
  붙였다 — 실제 스펙과 혼동하지 않도록 하기 위함.
- **멘토가 실제 USL/LSL을 제공하면**: `add_spec_deviation_features`에 넘기는
  `baseline_long` 인자만 그 값 기준으로 바꾸면 되고, 함수 구조 자체는 그대로 쓸 수 있다.

## Goal별 활용법

- **Goal 1 (장비/제품 비교)**: `00_stratum_baseline_stats_by_machine_opcond.csv`의
  z-score(median/MAD 기반, `common.zscore_transform`으로 재현 가능)로 OPCOND를 고정한 채
  Machine_ID 그룹을 비모수 검정(Kruskal-Wallis 등)으로 비교. OPCOND를 고정해야
  "제품이 달라서 나는 차이"와 "장비가 달라서 나는 차이"가 섞이지 않는다.
- **Goal 2 (유효인자 발굴)**: `00_column_classification.csv`의
  `include_in_downstream_default=True` 컬럼을 피처 후보로 사용하고,
  `degradation_trend_class`가 `candidate_upward_drift`/`candidate_downward_drift`인 컬럼을
  우선순위 후보로 삼는다. **반드시 기존 `analysis_outputs/03_impact_factor_ranking.csv` 및
  `analysis_outputs/full_correlation/02b_process_parameter_correlation_pairs.csv`와
  교차검증** — 여러 방법에서 공통으로 상위권인 인자만 "유효인자"로 멘토에게 제출한다
  (`ANALYSIS_GUIDE.md`가 이미 경고했듯 상관/중요도 하나만으로는 가짜상관 위험이 있다).
  **주의**: `03_impact_factor_ranking.csv`(`analysis_step_by_step.py` 산출물, 26.08.01
  Edge_Burn 제외 반영 재작성됨)는 Particle/Remain_Coat/Micro_Crack/Chipping 4개 defect를
  다루도록 갱신됐다. 단 **Micro_Crack/Chipping은 층별(Machine×Product×Recipe) 표본 부족
  으로 실제 결과 행이 없다**(스크립트 실행 시 콘솔 경고 참고, 최대 층당 2건/1건뿐) —
  이 두 defect는 이 파일로 교차검증할 수 없고, Jun/윤진혁의 행 단위 검정(Goal2 CRACK/CHIP
  분석)을 참고할 것. **Particle/Remain_Coat 행만 실질적으로 교차검증에 쓸 수 있다.**
  Laser_Paim은 이 데이터셋에서 발생 건수가 0건이라 애초에 대상이 아니다.
- **Goal 3 (상호작용)**: Goal 2가 확정한 유효인자 목록을 받아서 실행 (Goal 2 이후 순서).
  `00_stratum_baseline_stats_by_opcond.csv`의 정규화 스케일 위에서 인자쌍 상호작용 분석.
- **Goal 4 (이상치/열화 탐지)**: 먼저 `00_missing_sensor_fault_flags.csv`로 결측/센서고장
  의심 행을 제외. `degradation_trend_class`를 "spec-out은 아니지만 추세 이상"으로 보고하는
  데 직접 사용 가능하고, `00_machine_column_trend.csv`의 원본 p-value로 세부 근거를 댈 수
  있다. **주의**: 4개 장비 × 40개 연속형 컬럼 = 160개 가설을 개별 alpha=0.05로 검정했으므로
  다중비교 보정 없이는 우연히 유의한 결과가 다수 섞여 있다. Goal4에서 최종 확정할 때는
  `statsmodels.stats.multitest.multipletests`로 보정하거나, 같은 장비·컬럼의 추세가
  여러 주 연속으로 재현되는지 확인해서 걸러낼 것. 기존 `analysis_outputs/04_provisional_control_limits.csv`와
  교차표를 만들면 "spec-out만 잡던 기존 방식보다 얼마나 더 잡아내는지" 정량적으로 보여줄 수 있다.
- **Goal 5 (Health Index)**: Goal 1(안정성)/Goal 4(열화추세)의 결과와 defect율을 0~100
  스케일로 통일해 가중합. 가중치는 잠정치로 문서화하고 Spearman(HI, Yield) 부호로 자체 검증.
- **Goal 6 (SOP 초안)**: Goal 2 유효인자 + Goal 4 이상탐지 결과를 결합해 "점검→조치" 템플릿
  생성. 실제 SOP는 멘토가 유효인자 확인 후 제공하므로 이번 산출물은 전부
  `DRAFT_UNVERIFIED`로 표시한다.

## 알아두어야 할 설계 판단

- **결측/이상값 처리는 flag-only.** 이 데이터셋은 결측치가 0건, flatline(센서 고착) 의심도
  0건으로 확인되어 자동 보간 로직은 만들지 않았다. 필요해지면
  `00_missing_sensor_fault_flags.csv`의 `suggested_handling` 컬럼을 확장해서 쓸 것.
- **변동성 지표는 컬럼 타입마다 다르다** (`dispersion_method` 컬럼 참고): 연속형은
  CV(또는 signed 컬럼은 range-normalized std), 이진 defect는 층별 발생률의 CV, count는
  index of dispersion(var/mean). defect 관련 컬럼은 정상군(OK)에서 항상 0이므로
  **전체 데이터**로 계산했다 — OK-only로 계산하면 전부 0이 되어 무의미해진다.
- **미문서화 컬럼(PLC/Network/LED/Room_Noise/Door/Fan/Vision/Factory_Power)은 1차
  제외.** 공정 물리량이 아닌 설비 IT/환경 텔레메트리로 추정된다. 단
  `Maintenance_Count`는 정비이력 프록시로 볼 수 있어 제외하지 않고 남겨뒀다
  (`00_column_classification.csv`의 `decision_note` 참고).
- **die 단위 x,y 좌표가 데이터에 없다.** 공간(DBSCAN) 클러스터링은 이번 범위에서 완전히
  제외했다. 좌표가 추가되면 그때 Goal4에 별도 모듈로 확장할 것.
