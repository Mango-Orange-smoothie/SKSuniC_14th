# Goal5 — Health Index + 경보 + SOP 대시보드 (러프 v0, 김시우)

월요일 멘토 미팅용 "대충이라도" 만든 초안입니다. 정교한 최종 버전이 아니라, 지금까지 팀이
각자 확정한 결과를 한 화면에서 볼 수 있게 처음으로 이어 붙인 것입니다.

## 실행

```bash
python 26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_health_index.py   # Health Index/경보/SOP 계산
python 26.08.01_Goal5_HealthIndex_Dashboard_김시우/build_dashboard_html.py # dashboard.html 생성
```

`dashboard.html`을 더블클릭해서 브라우저로 열면 됩니다 (서버 불필요).

## 데이터 출처 — 각자 확정한 유효인자를 그대로 가져옴

- Particle → `Vibration` (daeho, `26.07.31_2058_Goal2_PARTICLE_후속검증/` — 선행신호 검증까지 완료된 것)
- Remain_Coat → `CLN_Pressure` (전성재, `26.07.31_Goal2_REM_COAT_유효인자_분석_전성재/` — Machine 통제 다변량 v2)
- Chipping/Micro_Crack → `Laser_Power`/`Power_Efficiency`/`Head_Temp`/`Laser_Centering_Position`/`Vibration`/`Cooling_Flow` (JHdaimma, `26.08.01_Goal2_CHIP_CRACK_유효인자_분석_JHdaimma/` — SHAP 모델A 원인후보)
- 전처리/추세검정/baseline → `pipeline/`(김시우 Step0)

## Health Index 산식 (전부 잠정치 — 팀 논의로 조정 필요)

```
Health Index = 100 − 불량페널티 − 안정성페널티 − 추세페널티
  불량페널티   = (100 − Yield_7d_ma) × 3, 최대 45
  안정성페널티 = 원인변수 7개의 OPCOND 층화 z-score 평균(|z|, 위험방향) × 8, 최대 30
  추세페널티   = 그 장비에서 나쁜 방향으로 추세(candidate_*_drift)인 원인변수 개수 × 5, 최대 20
```

가중치(3, 8, 5)와 상한선은 근거 있는 최적화 값이 아니라 "일단 돌아가는" 잠정치입니다.

## 알려진 한계 (다음 라운드에서 보완할 것)

- 가중치 미검증 — Health Index가 실제 불량 발생을 얼마나 잘 예측하는지 검증 안 함
- Chipping/Micro_Crack은 JHdaimma의 r1(신규) 데이터 기반 분석인데, 이 대시보드는 원본
  데이터(`data/raw/`)로만 계산 — **팀 결정(26.08.01)**: r1은 표본 부족(원본 기준 극희귀
  defect) 보완용 학습/검증 데이터로만 쓰고 `data/raw/`와 합치지 않음. 따라서 이건 "나중에
  재계산할 한계"가 아니라 **의도된 설계** — Health Index는 계속 원본 데이터 기준으로 유지.
- 경보 임계값(HI<80)과 z-score 임계값(2.0)은 실제 분포를 보고 잡은 눈대중 값
- SOP 제안은 전부 `DRAFT_UNVERIFIED` — 멘토/현장 확인 전까지 참고용

## 산출물

| 파일 | 내용 |
|---|---|
| `01_health_index_by_machine_date.csv` | 장비×날짜별 Health Index (356행, 90일×4대) |
| `02_active_alerts.csv` | 최근 7일 경보 목록 (14건) |
| `03_sop_suggestions.csv` | 경보에 등장한 원인변수별 SOP 초안 (6건) |
| `dashboard_data.json` | 대시보드가 읽는 통합 데이터 |
| `dashboard.html` | **대시보드 본체** — 더블클릭으로 바로 열람 |
| `dashboard_artifact.html` | 위와 동일 내용, Claude Artifact 게시용 (wrapper 태그만 제거) |
