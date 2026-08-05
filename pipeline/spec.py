"""멘토가 직접 제공한 공식 스펙(USL/LSL/TARGET). 26.08.05 수령.

지금까지 build_health_index.py의 "임시 USL/LSL"(정상군 p0.5~p99.5로 대체한 값, 실제
defect 발생과 거의 안 겹친다는 걸 검증으로 확인함)은 진짜 스펙이 없어서 쓴 대체값이었다.
여기 10개 변수는 멘토가 준 진짜 스펙이라 임시값 대신 이걸 우선 써야 한다.

컬럼명 매핑 주의: 멘토가 준 원본 키는 "Kerf_Profile"인데, 데이터셋 실제 컬럼명은
Kerf_Width_Profile이다(TARGET=50이 실측 median 50.0949와 거의 일치해서 같은 변수로 확인).
아래 딕셔너리 키는 데이터셋 컬럼명 기준으로 통일했다.

Focus/Frequency/Feed_Speed는 확정 원인(CAUSE_FACTORS) 목록엔 없는 변수다 — Focus는 멘토가
"분석에 활용하지 않아도 된다"고 명시적으로 제외한 변수(config.py MENTOR_EXCLUDED_VARS)라서
스펙은 있어도 Health Index 계산에선 안 쓴다.
"""

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
