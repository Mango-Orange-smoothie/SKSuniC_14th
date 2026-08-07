"""멘토가 제공한 입력 — 우리가 정한 값이 아니라 밖에서 받은 사실.

여기 있는 것은 튜닝 대상이 아니다. 팀이 분석해서 도출한 값(config.py)이나 데이터에서
학습한 값(00_baseline_C.csv)과 성격이 완전히 달라서, 섞여 있으면 "이건 우리가 정한
거니까 바꿔도 되나?"를 매번 헷갈리게 된다. 바꾸려면 멘토 확인이 필요하다.

(26.08.07) 원래 SPEC만 pipeline/spec.py에 있고 나머지 멘토 피드백은 config.py에
섞여 있었다. 출처가 같은 것끼리 모은다 — spec.py는 이 파일로 흡수됐다.

담긴 것:
  SPEC                        멘토 실측 LSL/TARGET/USL (26.08.05 수령, 10개 컬럼)
  MENTOR_EXCLUDED_VARS        분석에 안 써도 된다고 지정한 변수
  MENTOR_DOMAIN_NOTES         제외가 아니라 "참고"로 준 도메인 지식
  MENTOR_EXCLUDED_DEFECTS     유효한 실패모드가 아님이 확정돼 제외된 defect
  MENTOR_PENDING_REVIEW       아직 확정 아니고 "재확인 예정"으로 남은 항목
"""

# 멘토 피드백(26.07.31): 데이터 제공 시 "분석에 활용하지 않아도 되는 변수"로 명시적으로
# 지정됨. FDC/response 값이라 원본 데이터프레임에는 남기되, 피처셋에서는 제외한다.
# 주의: Focus는 Jun의 BURN 분석(Goal2)에서 이미 도메인 후보로 포함돼 있었으므로
# 이 변경 이후 재실행이 필요할 수 있다 — Jun에게 공유할 것.
MENTOR_EXCLUDED_VARS = ["Focus", "Cutting_Offset"]
MENTOR_EXCLUDED_VARS_NOTE = "멘토가 데이터 제공 시 분석에 활용하지 않아도 된다고 명시적으로 지정한 변수 (26.07.31 피드백)."

# 멘토 피드백(26.07.31) — 제외가 아니라 "참고" 성격의 도메인 지식. 통계 분석 시
# 단순 선형/단조 상관만 보지 말고 임계값 효과 가능성을 염두에 둘 것.
MENTOR_DOMAIN_NOTES = {
    "Frequency": "멘토 피드백: 레이저 변수로 확인됨 (fdc_laser로 재분류).",
    "Laser_Head_Remain_Time": (
        "멘토 피드백: 헤드 내 11개 스팟, 스팟당 기준수명 약 2000시간(가상데이터라 그대로 "
        "적용 안 될 수 있음). 잔여시간이 적게 남거나 특정 시점(교체/오버 시점)을 지날 때 "
        "불량이 발생하는 임계값성 패턴이 있을 수 있음 — 선형 상관보다 구간별/임계값 "
        "기반 분석(예: 잔여시간 구간화 후 불량률 비교)을 함께 검토할 것."
    ),
    "Power_Efficiency": (
        "멘토 피드백: 비선형(U자형/최적구간) 특성 — 효율이 높아져도 낮아져도 불량과 "
        "연관될 수 있음. 단순 선형/단조 상관(Mann-Whitney 등)으로만 해석하지 말 것, "
        "|편차| 기준 검정이나 구간화 분석을 함께 검토할 것."
    ),
    "Vibration": (
        "멘토 피드백: 설비 열화(degradation)의 대표 신호. 실제 사고 사례(노후 장비 Y축 "
        "이동 시 진동으로 빔 라인 어긋남 → 대량 스크랩)가 있었음 — Health Index(Goal5) "
        "핵심 후보 변수로 우선 고려할 것."
    ),
    "Kerf_Width_Profile": (
        "멘토 피드백: '7㎛ 지점' 기준으로 정의된 값이지만, 이 합성 데이터에서는 생성 시 "
        "정확히 7㎛로 고정되지 않고 임의 baseline을 썼을 수 있음 — 7㎛를 물리 상수로 "
        "하드코딩하지 말고, baseline을 데이터 분포(정상군 median 등)에서 역산해서 쓸 것 "
        "(Step0의 OK-baseline 방식이 이미 이 원칙을 따름). "
        "메커니즘(팀 도메인지식, 26.08.02): 가공폭이 넓거나 좁거나 양방향 모두 위험 "
        "(direction=either) — 패키지 크기 불균형이나 가공영역 이탈로 이어짐. Chipping "
        "원인으로 Jun/JHdaimma 양쪽에서 통계적으로 확정됨(JHdaimma는 통계검정·permutation "
        "importance·SHAP 3방법 모두 top10 합의)."
    ),
    "Top_Kerf": (
        "멘토 피드백: Kerf_Width_Profile과 동일한 '7㎛ 기준점 아님' 주의사항 적용. "
        "Chipping 원인으로 JHdaimma가 3방법 합의로 확정(direction=either, Kerf_Width_Profile과 "
        "동일 메커니즘 상속)."
    ),
    "Groove_Depth": (
        "멘토 피드백: 기준 깊이(7㎛) 대비 편차값이지만, 이 데이터에서 7㎛가 실제 물리 "
        "상수가 아닐 수 있음 — Kerf_Width_Profile과 동일 주의사항, baseline은 데이터로 역산. "
        "메커니즘(팀 도메인지식, 26.08.02): 너무 깊게 깎인 건 문제 안 되고 **덜 깎였을 때만 "
        "위험**(direction=down이 위험, either 아님) — Kerf_Width_Profile과 방향 성격이 다름. "
        "Chipping 원인으로 Jun이 통계검정 confirmed(가공깊이 부족 -> Low-k 불완전 승화 -> "
        "Blade가 잔류물 타격), CAUSE_FACTORS에 반영됨. "
        "(정정: JHdaimma 모델에서 Laser_Power의 결과값(R²=0.606)으로 나온 건 JHdaimma가 "
        "Chipping 예측 후보에서 애초에 제외하고 별도 회귀로만 다룬 것뿐 — Jun의 confirmed "
        "결과를 반박하는 근거가 아니었음. 처음에 이걸 잘못 해석해서 CAUSE_FACTORS에서 뺐다가 "
        "재정정함.)"
    ),
    "Kerf_Angle": (
        "팀 자체 검증(26.08.02): Top_Kerf/Bottom_Kerf/Groove_Depth 어느 조합과도 상관/회귀/"
        "RandomForest 전부 관계 없음(R² 0.5~0.6% 수준). Jun의 5개 defect 통계검정에서도 "
        "전부 insufficient_evidence/not_related_to_defect. JHdaimma 모델에서도 원인이 아니라 "
        "Head_Temp가 만드는 결과값(R²=0.664)으로만 등장. **원인 후보에서 배제하고 "
        "독립적으로 생성된 변수로 결론** — 더 이상 인과분석 대상으로 우선순위 두지 않음."
    ),
    "Bottom_Kerf": (
        "Jun 도메인 지식(26.08.02, 멘토 미확정): Top_Kerf=절단 상단 폭, Bottom_Kerf=완전히 "
        "깎인 하단 폭, Kerf_Width_Profile=7㎛ 지점 폭, Kerf_Angle=절단면 기울기(경계값), "
        "Groove_Depth=실제 깎인 깊이 — 5개가 같은 절단면을 위치별로 잰 값이라는 해석. "
        "**단, 이 데이터로 검증한 결과 그 기하학적 순서 관계는 성립하지 않음**: "
        "Top_Kerf > Bottom_Kerf 비율이 49.3%(위가 항상 넓어야 하면 거의 100%여야 함), "
        "Kerf_Width_Profile이 Top~Bottom 사이 값인 비율도 28.5%뿐. 5개 컬럼 평균이 다들 "
        "50.09~50.10으로 비슷해서 같은 물리량을 재는 것처럼 보이지만, 서로 독립적으로 "
        "생성된 값에 가까움(가상데이터 한계 — Kerf_Width_Profile 노트의 '7㎛ 비고정' 문제와 "
        "같은 맥락). 인과분석 시 Jun의 개념적 해석은 참고하되, 5개를 기하학적으로 서로 "
        "치환 가능한 중복값처럼 다루지 말 것 — 각각 독립 후보 변수로 취급."
    ),
    "Package_Size_1": "멘토 피드백: 4방향(동서남북) 중 하나, 방향 특정 불필요. 센터링 이상 시 비대칭 패턴 발생 — Package_Size_Asymmetry(팀 공용 피처) 참고.",
    "Package_Size_2": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Package_Size_3": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Package_Size_4": "멘토 피드백: Package_Size_1과 동일 — 센터링 이상 시 비대칭 패턴, Package_Size_Asymmetry 참고.",
    "Head_Temp": (
        "멘토 피드백: Head_Temp -> 크리스탈 스팟 온도 변화 -> 굴절률 변화 -> "
        "Laser_Centering_Position 변화 -> Chipping/Kerf 불균일로 이어지는 인과사슬 가설. "
        "Cooling_Flow/Cooling_Water_Temp/Laser_Centering_Position과 함께 묶어 다변량 분석 권장."
    ),
    "Laser_Centering_Position": "멘토 피드백: Head_Temp 인과사슬의 종착점 — 레이저 품질 이상의 핵심 원인 중 하나로 반복 언급됨.",
}

# 멘토 피드백(26.08.01) — 재확인 결과 최종 확정: Edge_Burn/Edge_Burn_Die는 유효한 실패모드가
# 아니므로 defect 분석 대상에서 제외. Jun의 Goal2 BURN 분석(confirmed factors: Frequency,
# Thermal_Load_Ratio, Top_Kerf, Kerf_Width_Profile, Surface_Roughness)은 이 라벨 자체를 쓴
# 것이므로 전체가 무효화됨 — Jun에게 최우선으로 공유하고 BURN 분석 폴더 처리 방향(삭제 vs
# "제외된 defect였음" 아카이브) 논의 필요.
MENTOR_EXCLUDED_DEFECTS = ["Edge_Burn", "Edge_Burn_Die"]
MENTOR_EXCLUDED_DEFECTS_NOTE = (
    "멘토 확인 결과 유효한 실패모드가 아님이 확정되어 defect 분석 대상에서 제외 (26.08.01). "
    "Jun의 Goal2 BURN 분석 전체가 이 라벨 기반이라 재검토 필요."
)

# 멘토 피드백(26.07.31) — 아직 최종 확정이 아니라 "재확인 예정"으로 남은 항목.
# 함부로 제외하지 않고 include_in_downstream_default=True로 유지하되, 강한 경고를 남긴다.
MENTOR_PENDING_REVIEW = {
    "Bottom_Kerf": (
        "멘토가 다른 kerf 컬럼과 값 중복 여부, 순수 샘플링 값인지 재확인 예정이라고 했음 "
        "— 결과 해석 시 주의. 팀 자체 검증(26.08.02): 상관계수로는 완전 중복 아님(0.63대, "
        "OPCOND 층화 재검증해도 동일), 값 자체 100% 일치하는 행도 없음 — '중복 저장'은 "
        "가능성 낮음. 단 Jun의 도메인 해석(Top/Bottom/Profile이 절단면 위치별 값)이 기대하는 "
        "기하학적 순서 관계도 데이터에서 안 성립함(MENTOR_DOMAIN_NOTES 참고) — 멘토 최종 "
        "확인 전까지는 '중복도 아니고 깔끔한 기하학적 유도값도 아닌, 독립적인 후보 변수'로 취급."
    ),
    "Surface_Roughness": (
        "멘토가 drop 여부를 확정하지 않음('필요상 넣어놓은 컬럼'이라고만 언급) — Jun의 "
        "BURN/PARTICLE/CRACK confirmed 목록에 이미 등장하므로 최종 확정 전까지 결과 해석 시 주의."
    ),
    "Cooling_Flow": "멘토가 '컬럼을 다시 봐야겠다'며 설비-컬럼 매핑 재확인을 예고함 — 정확한 매핑 확정 전까지 결과 해석 시 주의.",
    "Cooling_Water_Temp": "멘토가 '컬럼을 다시 봐야겠다'며 설비-컬럼 매핑 재확인을 예고함 — 정확한 매핑 확정 전까지 결과 해석 시 주의.",
}


SPEC = {
    "Laser_Power": {"LSL": 17.8, "TARGET": 18.5, "USL": 19.2},
    "Power_Efficiency": {"LSL": 92, "TARGET": 95, "USL": 98},
    "Laser_Centering_Position": {"LSL": -3, "TARGET": 0, "USL": 3},
    "Frequency": {"LSL": 98, "TARGET": 100, "USL": 102},
    "Feed_Speed": {"LSL": 248, "TARGET": 250, "USL": 252},
    "Head_Temp": {"LSL": 38, "TARGET": 42, "USL": 47},
    "Focus": {"LSL": -4, "TARGET": 0, "USL": 4},
    "Kerf_Width_Profile": {"LSL": 49.2, "TARGET": 50, "USL": 50.8},  # 멘토 원본 키: Kerf_Profile
    "Coating_Thickness": {"LSL": 9.5, "TARGET": 10, "USL": 10.5},
    "Coating_Uniformity": {"LSL": 97, "TARGET": 99, "USL": 100},
}
