# Goal2 — Particle 유효인자 분석 (진혁님 방법론 이식)

담당: 박대호 · 기준일: 2026-08-05
데이터: 원본 `DP_HealthIndex_Dataset.csv` + `DP_HealthIndex_Dataset_r1.csv` = **통합 200,000행**
방법: **진혁님(JHdaimma) `chip_crack_factors_v2.py` 방법론을 그대로 이식**

> 진혁님이 CHIP/CRACK에 쓴 판정 방법을 Particle에 처음 적용한 결과입니다.
> 통계 로직은 한 줄도 바꾸지 않았고, Particle 도메인 가설표만 승준님
> `26.07.30_2055_.../DOMAIN_KNOWLEDGE.md`에서 옮겨 채웠습니다.

---

## 세 줄 요약

1. **진혁님 방법 그대로 돌리면 Particle의 `confirmed`는 `Surface_Roughness`와 `Vibration` 2건입니다.**
   승준님 통합본이 `Vibration`을 **Tier2d(관찰만, 수치 지시 금지)** 로 강등시킨 것과 정면으로 어긋납니다.
2. **그 차이는 전부 "비교군을 무엇으로 잡느냐" 하나에서 나옵니다.** r1에서 `Vibration` 효과크기가
   비교군에 따라 **−0.034에서 +0.289까지** 갈립니다. 승준님 숫자(−0.0341)를 소수점까지 재현했고,
   `keep` 마스크만 씌우면 +0.168로 부호가 뒤집힙니다.
3. **단, 이 결과를 그대로 팀에 내면 안 됩니다.** 진혁님 방법에는 **시간선행성 검사가 없어서**
   `Surface_Roughness`(결과 공변)를 `Vibration`과 같은 등급으로 올립니다. 이미 기각한 결론이
   방법론 때문에 되살아난 것이라, 4절을 반드시 같이 읽어야 합니다.

---

## 0. 이식 정합성 검증 — 통과

Particle 결과를 믿기 전에, 같은 스크립트를 **CHIP으로 돌려 진혁님 공개 산출물과 대조**했습니다.

`08_reproducibility_chip.csv` — 진혁님 브랜치 값 vs 이번 실행값:

| 인자 | 진혁님 원본/r1/통합 | 이번 실행 | |
|---|---|---|---|
| `Kerf_Width_Profile` | 0.9998 / 0.9600 / 0.9825 | 0.9998 / 0.9600 / 0.9825 | ✅ |
| `Laser_Power` | −0.9792 / −0.9071 / −0.9229 | −0.9792 / −0.9071 / −0.9229 | ✅ |
| `Power_Efficiency` | −0.4454 / −0.9246 / −0.9506 | −0.4454 / −0.9246 / −0.9506 | ✅ |
| `Focus` | −0.1815 / 0.8721 / 0.9372 | −0.1815 / 0.8721 / 0.9372 | ✅ |
| `Vibration` | 0.3447 / 0.8694 / 0.9022 | 0.3447 / 0.8694 / 0.9022 | ✅ |

**소수점 4자리까지 전부 일치합니다.**

승준님 방법 G도 같이 재현됐습니다 — `09_reproducibility_by_dataset.csv`의
Chipping `Vibration` r1 **+0.7091** ↔ 이번 실행 B변형 **+0.7091**.

정합성 증거가 하나 더 있습니다. CHIP 실행에서 `Laser_Power`(트리 2위)와
`Power_Efficiency`(트리 1위)가 `confirmed`가 아니라 **`candidate_needs_domain_review`** 로
떨어지는데, 이는 진혁님이 README "팀에 요청하는 사항 1"에서 지적한
*"승준님 CHIP 도메인 가설표에 이 둘이 `not_related`(Burn 전용)로 분류돼 있다"* 는 문제가
그대로 재현된 것입니다.

> 참고: 진혁님 README 본문의 요약 효과크기(`Power_Efficiency` −0.899 등)는 이번 실행값
> (−0.951)과 조금 다릅니다. 그 표는 pure 라벨 기준이고 `chip_crack_factors_v2.py` 본체는
> primary/broad 라벨만 쓰기 때문입니다. 스크립트가 실제로 저장하는 산출물끼리는 위처럼
> 완전히 일치합니다.

---

## 1. 판정 결과 (`04_particle_influence_factors_final.csv`)

인자 40개 → `confirmed` 2 / `candidate_weak_signal` 8 / `insufficient_evidence` 30

### confirmed 2건

| 인자 | delta(primary) | delta(broad) | 트리 순위 | 방법 합의 |
|---|---|---|---|---|
| `Surface_Roughness` | **+0.618** | +0.551 | 1위 | 2/2 |
| `Vibration` | +0.087 | **+0.317** | 3위 | 2/2 |

### candidate_weak_signal 8건

| 인자 | delta(primary) | delta(broad) | 비고 |
|---|---|---|---|
| `CLN_Flow` | −0.008 | −0.146 | 트리 2위 |
| `Kerf_Width_Profile` | −0.069 | +0.123 | |
| `Top_Kerf` | −0.062 | +0.128 | |
| `Bottom_Kerf` | −0.059 | +0.130 | |
| `Focus` | −0.074 | +0.112 | |
| `Cleaning_Load_Ratio` | +0.036 | +0.068 | |
| `CLN_Pressure` | +0.013 | −0.063 | |
| `Cleaning_Capacity` | +0.007 | −0.143 | |

---

## 2. 핵심 산출물 — 비교군 4종 대조 (`10_comparison_group_contrast_particle.csv`)

팀 안에서 같은 `Vibration`을 두고 숫자가 안 맞는 이유가 이 표 하나로 정리됩니다.

### `Vibration` — Cliff's delta

| 비교군 정의 | 원본 | **r1** | 통합 |
|---|---|---|---|
| **A. 진혁님** — 불량군 `NG_Code=='PARTICLE'` vs **나머지 전부** | +0.2195 | **−0.0240** | +0.0865 |
| **B. 승준님 방법 G** — pure vs ~pure | +0.2192 | **−0.0341** | +0.0773 |
| **C. `keep` 보정** — 다른 defect 있는 행 제외 | +0.2191 | **+0.1684** | +0.1935 |
| **D. 대호님 규약** — vs `NG_Code=='OK'`만 | +0.2202 | **+0.2892** | +0.2510 |

**원본에서는 넷이 소수점 셋째 자리까지 같습니다(+0.219~+0.220). r1에서만 갈립니다.**

이유는 비교군 크기에 그대로 찍혀 있습니다. r1 비교군 행 수:

| 비교군 | r1 행 수 | 그중 불량 |
|---|---|---|
| A(나머지 전부) | 95,159 | **36,269건 (38.1%)** |
| D(OK만) | 58,890 | 0건 |

**r1 비교군의 38.1%가 불량입니다.** 그 불량들(대부분 CHIP)이 진동이 높은 행이라, "정상 대비
진동이 높다"를 재려는데 비교 상대가 이미 진동 높은 불량군인 셈이 됩니다. 원본은 오염이
2.5%뿐이라 티가 안 났습니다.

> 이건 대호님 Goal3(`26.08.02_2250_Goal3_Vibration_얽힘구조`)에서 이미 낸 결론인데,
> **이번엔 진혁님 방법론 위에서 독립적으로 재현됐습니다.** 승준님 방법 G의 −0.0341을
> 소수점까지 그대로 뽑았고, `keep` 마스크만 적용하면 +0.1684가 됩니다.

### 세정계 — 라벨에 따라 완전히 갈립니다 (해석 보류)

| 인자 | A(진혁) | B(승준) | C(keep) | D(OK만) | broad 라벨 |
|---|---|---|---|---|---|
| `CLN_Flow` | −0.008 | −0.005 | −0.005 | −0.026 | **−0.146** |
| `CLN_Pressure` | +0.013 | +0.012 | +0.008 | −0.000 | −0.063 |
| `Cleaning_Capacity` | +0.007 | +0.010 | +0.005 | −0.017 | **−0.143** |

**primary/pure 라벨에서는 어느 비교군을 써도 전부 무신호(|delta| < 0.03)인데,
broad 라벨(`Particle==1`)에서만 −0.14대가 나옵니다.**

이 차이가 "REM_COAT 동시발생이 만든 착시"인지, 아니면 "두 불량이 공통 원인을 공유한다는
증거"인지는 **이 분석만으로는 판단하지 않습니다.** 설비(Machine) 축을 검토해야 갈리는
문제인데 이번 방법론에는 Machine 축이 없습니다(4절 ③). 별도로 확인 중이며,
팀 상의 후 정리할 예정입니다.

---

## 3. 재현성 (`08_reproducibility_particle.csv`)

진혁님 `supplement_crossvalidation.py` 방식(broad 라벨 vs ~broad) 그대로.

| 인자 | 원본 | r1 | 통합 |
|---|---|---|---|
| `Surface_Roughness` | +0.610 | +0.490 | +0.551 |
| `Vibration` | +0.194 | **+0.331** | +0.317 |
| `CLN_Flow` | −0.030 | −0.206 | −0.146 |
| `Cleaning_Capacity` | −0.034 | −0.194 | −0.143 |

**진혁님 방식(broad 라벨)으로 재면 `Vibration`은 r1에서 오히려 강해집니다(+0.331).**
승준님 방법 G가 같은 데이터에서 −0.034를 낸 것과 대비됩니다. 진혁님 브랜치
`08_reproducibility_crack.csv`의 Micro_Crack(+0.4533 vs 승준님 −0.0922)과 **같은 구조의 불일치**입니다.

`09_baseline_sensitivity_particle.csv`: baseline 선택(통합 OK 기준 vs 전체 행 기준)으로
판정이 바뀐 인자 **0건** — 강건합니다.

---

## 4. ⚠️ 이 결과를 그대로 쓰면 안 되는 세 가지

### ① `Surface_Roughness`가 `confirmed`로 올라온 건 방법론의 빈칸 때문입니다

`Surface_Roughness`는 delta +0.618로 1위지만, 대호님 후속검증(검증1)에서
**선행신호 잔존율 7.5%로 결과 공변이 확정된 인자**입니다. particle이 표면에 남아 거칠어진
결과이지 원인이 아닙니다.

진혁님 방법(통계검정 + RandomForest)에는 **시간선행성 검사가 없습니다.** 두 방법 다
"같은 행에서 같이 나타나는가"만 묻기 때문에 원인과 결과를 구분할 수 없고, 그래서
가장 강한 결과 공변 인자가 자동으로 1위 `confirmed`가 됩니다.

승준님 통합본에는 이 검사가 방법 F로 들어 있고(대호님 원안), 거기서는
`Surface_Roughness`가 `monitor_only`로 내려갑니다. **진혁님 방법을 쓰려면 방법 F를
반드시 얹어야 합니다.**

### ② `Vibration`이 `confirmed`가 된 근거는 오염된 라벨입니다

`Vibration`의 방법 합의 2건 중 통계검정은 **broad 라벨에서만 통과**했습니다.

| | primary(`NG_Code=='PARTICLE'`) | broad(`Particle==1`) |
|---|---|---|
| delta | +0.087 (기준 0.2 **미달**) | +0.317 (통과) |

broad 라벨에는 CHIP·REM_COAT 동시발생이 섞여 있어 그 자체로 오염돼 있습니다.
**결론(`Vibration`은 Particle 인자)은 맞지만, 맞은 이유가 틀렸습니다.**

비교군을 대호님 규약으로 바꾸면 primary 라벨만으로도 통합 delta **+0.2510** 으로
기준을 통과합니다(2절 D행). 즉 `Vibration`은 오염된 라벨의 도움 없이도 서는 인자인데,
진혁님의 `~label` 비교군이 primary 라벨 쪽 신호를 +0.087로 깎아내린 상태입니다.

### ③ 설비(Machine) 축이 방법론에 없습니다

진혁님 방법론은 층을 OPCOND(`Product_ID × Recipe_ID`)로만 잡고 **설비 4대를 pool합니다.**
전성재님의 Machine 통제 다변량은 진혁님이 명시적으로 미사용으로 뒀고, 이 이식본도 그대로
물려받았습니다. 따라서 **특정 설비에만 나타나는 현상은 나머지 3대에 희석돼 이 판정표에
나타나지 않습니다.**

pure/primary 라벨도 같은 방향의 제약이 있습니다. 이 라벨들은 "다른 불량이 같이 난 행"을
오염으로 보고 제거하므로, **여러 불량을 동시에 일으키는 공통 원인은 구조적으로 찾지
못합니다.** 2절 세정계 표에서 primary/pure와 broad가 갈리는 것이 그 지점입니다.

설비 축과 동시발생 그룹을 따로 검토 중이며, 결과는 팀 상의 후 별도로 정리합니다.

---

## 5. 라벨 등가식 점검 (`00_summary_particle.json`)

대호님 원본 분석은 `NG_Code=='PARTICLE'` == pure 라벨을 `assert`로 고정했는데,
통합 데이터에서는 성립하지 않아 건수 기록으로 대체했습니다.

| 데이터 | primary | pure | 불일치 |
|---|---|---|---|
| 원본 | 6,455 | 6,450 | **5건** |
| r1 | 4,841 | 4,022 | **819건** |

※ 여기서 pure는 다른 3개 defect가 **전부** 0인 행입니다. `Particle==1 & Remain_Coat==0`
정의로 세면 숫자가 달라집니다 — 둘 다 맞고, 정의가 다릅니다.
**원본에서도 5건 불일치가 있어 `assert`는 원본에서조차 다시 걸면 안 됩니다.**

---

## 6. 다음에 할 것

1. **진혁님께** — `08_reproducibility_particle.csv`의 `Vibration` r1 **+0.331**과 승준님 방법 G의
   **−0.034**. 진혁님 CRACK에서 나온 +0.4533 vs −0.0922와 같은 원인입니다(2절).
2. **승준님께** — `unified_full_methodology.py:253`(방법 G)와 `:299`(방법 A)에 `keep` 마스크가
   빠져 있습니다. 같은 파일 `:498`에 이미 정의돼 있고 방법 B/C/D/E에는 넘어갑니다.
   Particle/Micro_Crack의 Tier2d 강등과 SOP "조치 보류"가 여기에 걸려 있습니다.
3. **방법론 보완** — 진혁님 방법에 시간선행성(방법 F)을 얹기 전까지 이 판정표의
   `Surface_Roughness` 등급은 쓰지 말 것.
4. **설비 축 검토** — Machine을 층 또는 통제변수로 넣고 재실행할 필요가 있는지 판단
   (전성재님 Machine 통제 다변량이 이미 그 형태). 2절 세정계 표와 4절 ③ 참고.

---

## 실행

이 폴더 안에서:

```bash
py -3 particle_factors_jh.py
```

CHIP 대조 실행(이식 정합성 확인용):

```bash
py -3 particle_factors_jh.py --target CHIP
```

데이터 CSV 2개(`DP_HealthIndex_Dataset.csv`, `_r1.csv`)는 용량 때문에 커밋하지 않았습니다.
기본적으로 이 폴더의 상위에서 찾고, `--data <폴더>` 또는 환경변수 `DP_DATA_DIR`로 지정할 수
있습니다. Windows에서 `python`이 Store 스텁으로 잡히면 `py -3`을 쓰십시오.

## 산출물

| 파일 | 내용 |
|---|---|
| `out/04_particle_influence_factors_final.csv` | **메인 판정표 — 인자 40개** |
| `out/10_comparison_group_contrast_particle.csv` | **비교군 4종 × 데이터셋 3종 대조** |
| `out/08_reproducibility_particle.csv` | 원본/r1 재현성 |
| `out/02_particle_univariate_test_results.csv` | 방법 1 (MWU + BH-FDR + Cliff's delta) |
| `out/03_particle_tree_importance.csv` | 방법 2 (RF permutation importance) |
| `out/09_baseline_sensitivity_particle.csv` | baseline 민감도 |
| `out/01_particle_rate_by_stratum.csv` | 발생률 sanity check |
| `out/00_stratum_baseline_by_opcond_combined.csv` | OK-baseline median/MAD |
| `out/00_summary_particle.json` | 실행 메타데이터 + 라벨 점검 |
| `out/*_chip.*`, `out/04_chip_*`, `out/08_reproducibility_chip.csv` | **이식 정합성 검증용 CHIP 실행분** (0절) |
| `out/run_log_particle.txt`, `out/run_log_chip_verify.txt` | 실행 로그 |
