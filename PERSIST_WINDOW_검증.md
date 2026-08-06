# PERSIST_WINDOW 검증 결과

## 배경

`trend_analysis.py`는 원래 조건을 만족하는 시점마다 즉시 경고를 냈다. 그런데 값이
위험선/변동성 임계값 근처에서 노이즈로 오락가락하면, 매번 "새로 진입했다"는 별개의
경고로 잡히는 문제가 있었다(예: Surface_Roughness 하나에서만 22,948건 중 21,426건이
이런 헛경보).

이를 해결하기 위해 **"최근 N행 연속으로 조건을 만족해야만 진짜 경고로 인정"**하는
지속성 필터(`PERSIST_WINDOW`)를 도입했다. C유형(entered/approaching)과 variability_warning에
적용된다.

## main 브랜치의 PERSIST_WINDOW=5 — 검증 결과 문제 발견

main 브랜치는 `PERSIST_WINDOW=5`를 썼다. 격리된 git worktree로 main을 직접 실행해
검증한 결과:

- 헛경보는 확실히 줄었다(Surface_Roughness 22,948건 → 718건, 약 97% 감소)
- 하지만 **실제 탐지력(Recall)도 같이 크게 희생됐다** — 같은 시점(same-row) 기준
  Precision/Recall을 Spec 방식과 비교했더니, Trend의 Recall이 20.8%까지 떨어져
  **Spec(90.1%)보다도 크게 낮아졌다.**
- 상한을 둔 lead time 재검증(24시간 이내)에서도 Trend는 실제 NG의 42.3%만
  사전탐지했고, 이는 Spec(98.7%)에 크게 못 미쳤다.

즉 `PERSIST_WINDOW=5`는 노이즈 억제에는 성공했지만 과도하게 엄격해서 실제 탐지력을
지나치게 깎아먹었다.

## lsyeon에서 PERSIST_WINDOW=3으로 재검증

같은 필터 로직(`_sustained_state`/`_sustained_first`)을 lsyeon의 `trend_analysis.py`에
적용하되, `PERSIST_WINDOW=3`으로 낮춰서 `Goal4_Performance_Validation`으로 재검증했다.

| 지표 | 필터 없음 | **PERSIST_WINDOW=3** | Spec(비교기준) |
|---|---|---|---|
| Precision | 0.320 | **0.424** | 0.473 |
| Recall | 0.940 | **0.738** | 0.857 |
| F1-score | 0.477 | **0.539** | 0.610 |
| False Alarm Rate | 0.682 | **0.342** | 0.326 |
| Detection Count | 146,673 | 86,839 | 90,353 |

**PERSIST_WINDOW=3이 5보다 훨씬 합리적인 균형점이다.** Precision과 False Alarm
Rate가 크게 개선되면서(Spec과 거의 비슷한 수준까지 근접) Recall은 적당히만
희생됐고, F1은 오히려 필터 없을 때보다 좋아졌다(0.477 → 0.539).

## 결론 / 채택한 값

`trend_analysis.py`의 `PERSIST_WINDOW = 3`으로 확정.

## 검증 방법 재현

```bash
python trend_analysis.py
python Goal4_Performance_Validation/performance_validation.py
```
`Goal4_Performance_Validation/results/performance_summary.csv`에서 Precision/Recall/F1/
False Alarm Rate 확인 가능.

## 참고 — "실제 defect 조기경보"와 "spec-out 조기경보"는 다른 질문

김시우 브랜치의 `26.08.01_Goal5_HealthIndex_Dashboard_김시우/README.md`에 정리된
`analyze_lead_time.py` 실측 결과에 따르면, **실제 defect 발생까지의 리드타임은
단변량/다변량 모델 모두 0.0일**이다(defect는 "서서히 쌓이다 터지는" 게 아니라
"그 순간 조건이 맞으면 바로 터지는" 방식으로 보임). 반면 **"Spec 경계를 넘는
순간"까지의 리드타임은 다르게 나타나며**, provisional 원인변수 11개 중 9개가
스펙아웃 며칠~몇 주 전부터 여유가 서서히 줄어드는 패턴을 보였다(예: Vibration
평균 25일 전).

즉 이 문서의 PERSIST_WINDOW 비교(Spec vs Trend, NG_Code 기준)는 "같은 조건에서
어느 방법이 더 잘 잡는지"를 비교하는 데는 유효하지만, 그 절대적인 리드타임
숫자를 "며칠 전에 defect를 예측했다"는 의미로 해석해서는 안 된다.
