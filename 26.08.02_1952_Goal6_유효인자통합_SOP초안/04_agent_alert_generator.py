"""SOP 기반 Agent 알림 문구 생성기.

`02_SOP_초안.csv` + Goal2 통합방법론의 `05_{defect}_thresholds.csv`(위험선)를 읽어서,
실시간(또는 배치) 값이 들어오면 **tier(action_type)마다 다른 어조**로 알림 문구를 만든다.

핵심 설계: Tier1(즉시조치)은 "이렇게 하세요"까지 말하고, Tier2d(관찰만)는 절대
숫자로 "이렇게 하라"고 말하지 않는다 — 확신이 낮은 신호를 확신 있는 것처럼
포장하지 않기 위해서다 (00_설계기록.md 4절 참고).

두 가지 진입점:
  generate_alert(defect, factor, z, raw_value=None)
      이미 z-score를 알고 있을 때 — 문구 1개 생성 (위험 아니면 None)
  evaluate_row(row: dict)
      Product_ID/Recipe_ID/센서 원본값이 있는 실제 한 스트립 딕셔너리를 받아서,
      pipeline의 OPCOND baseline으로 z-score를 직접 계산해 SOP에 등록된 모든
      인자를 한 번에 평가하고, 위험한 것들의 알림 문구 리스트를 반환한다.

실행 (저장소 루트에서, 데모):
    python "26.08.02_1952_Goal6_유효인자통합_SOP초안/04_agent_alert_generator.py"
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SOP_DIR = Path(__file__).resolve().parent
GOAL2_DIR = REPO_ROOT / "26.08.01_2229_Goal2_통합_전체방법론_4개defect"
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402

SOP = pd.read_csv(SOP_DIR / "02_SOP_초안.csv", encoding="utf-8-sig")

_THRESHOLD_FILES = {
    "Chipping": "05_chipping_thresholds.csv",
    "Remain_Coat": "05_remain_coat_thresholds.csv",
    "Particle": "05_particle_thresholds.csv",
    "Micro_Crack": "05_micro_crack_thresholds.csv",
}
THRESHOLDS = {
    defect: pd.read_csv(GOAL2_DIR / fname, encoding="utf-8-sig")
    for defect, fname in _THRESHOLD_FILES.items()
}

# ---------------------------------------------------------------------------
# tier(action_type)별 문구 템플릿 — 02_SOP_초안.csv의 action_type 값과 정확히 일치해야 한다.
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, str] = {
    "즉시조치": (
        "🔴 [{defect} 위험 신호 — 즉시 점검 요망]\n"
        "인자: {inspection_target}\n"
        "현재 z = {z:+.2f} (기준: {normal_range})\n"
        "→ {warning_signal}\n\n"
        "권장 조치: {recommended_action}\n"
        "근거: {evidence_methods} | 재현성: {reproducibility}\n"
        "*(DRAFT_UNVERIFIED — 잠정 SOP, 최종 조치는 담당자 판단)*"
    ),
    "조건부조치(실시간 알람형)": (
        "🟡 [{defect} 주의 신호 — 조건부 알람]\n"
        "인자: {inspection_target}\n"
        "현재 z = {z:+.2f} (기준: {normal_range})\n\n"
        "권장 조치: {recommended_action}\n"
        "⚠️ 주의: {confidence_note}\n"
        "근거: {evidence_methods} | 재현성: {reproducibility}\n"
        "*(DRAFT_UNVERIFIED)*"
    ),
    "관찰만(조치 보류)": (
        "⚪ [참고 — 조치 지시 아님] {defect} 관련 {inspection_target} 추이 이상\n"
        "현재 z = {z:+.2f}\n\n"
        "📌 이 인자는 수치 기반 조치를 권고하지 않습니다.\n"
        "사유: {confidence_note}\n"
        "권장: {recommended_action}\n"
        "근거: {evidence_methods} | 재현성: {reproducibility}\n"
        "*(DRAFT_UNVERIFIED — 조치 임계값 미확정)*"
    ),
    "감시(조치대상아님)": (
        "ℹ️ [참고 정보] {defect} 발생 시 함께 관찰되는 지표\n"
        "인자: {inspection_target}\n"
        "현재 z = {z:+.2f}\n"
        "→ {warning_signal}\n\n"
        "이 지표는 원인이 아니라 결과입니다 — {confidence_note}\n"
        "조치 대상 아님. {recommended_action}"
    ),
}


def _is_risky(defect: str, factor: str, z: float) -> bool:
    """05_thresholds.csv의 위험 방향으로 z가 넘어갔는지 판정. 위험선이 없는 인자는
    호출자가 이미 위험하다고 판단해 넘긴 것으로 보고 True."""
    th = THRESHOLDS.get(defect)
    if th is None:
        return True
    trow = th[th["column"] == factor]
    if trow.empty:
        return True
    t = trow.iloc[0]
    if t["risky_direction"] == "high_is_risky":
        return z > t["threshold_z"]
    return z < t["threshold_z"]


def generate_alert(defect: str, factor: str, z: float, raw_value: float | None = None) -> str | None:
    """defect/factor/z-score로 알림 문구 하나를 만든다. 위험 범위가 아니면 None."""
    sop_row = SOP[(SOP["defect"] == defect) & (SOP["factor"] == factor)]
    if sop_row.empty:
        return None
    sop_row = sop_row.iloc[0]

    if not _is_risky(defect, factor, z):
        return None

    template = TEMPLATES.get(sop_row["action_type"])
    if template is None:
        template = TEMPLATES["관찰만(조치 보류)"]  # 모르는 action_type이면 보수적으로 처리

    msg = template.format(
        defect=defect,
        inspection_target=sop_row["inspection_target"],
        z=z,
        normal_range=sop_row["normal_range"],
        warning_signal=sop_row["warning_signal"],
        recommended_action=sop_row["recommended_action"],
        evidence_methods=sop_row["evidence_methods"],
        reproducibility=sop_row["reproducibility"],
        confidence_note=sop_row["confidence_note"],
    )
    if raw_value is not None:
        msg = f"실측값: {raw_value}\n" + msg
    return msg


def evaluate_row(row: dict) -> list[str]:
    """실제 운영 중인 한 스트립의 원본 데이터(Product_ID/Recipe_ID + 센서 원본값)를 받아서
    SOP에 등록된 모든 인자에 대해 OPCOND baseline 기준 z-score를 계산하고, 위험한
    인자들의 알림 문구를 전부 반환한다.

    row 예시: {"Product_ID": "PKG_A", "Recipe_ID": "RCP_1", "Head_Temp": 42.3,
               "Vibration": 0.081, "CLN_Pressure": 2.1, ...}
    """
    baseline = pd.read_csv(
        config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv", encoding="utf-8-sig"
    )
    alerts = []
    for _, sop_row in SOP.iterrows():
        defect, factor = sop_row["defect"], sop_row["factor"]
        if factor not in row:
            continue
        b = baseline[
            (baseline["column"] == factor)
            & (baseline["Product_ID"] == row.get("Product_ID"))
            & (baseline["Recipe_ID"] == row.get("Recipe_ID"))
        ]
        if b.empty:
            continue
        median, scale = b.iloc[0]["median"], b.iloc[0]["robust_z_scale"]
        if abs(scale) < 1e-9:
            continue
        z = (row[factor] - median) / scale
        msg = generate_alert(defect, factor, z, raw_value=row[factor])
        if msg:
            alerts.append(msg)
    return alerts


# ---------------------------------------------------------------------------
# 데모 — 세 가지 tier를 각각 대표하는 예시를 실제로 생성해본다.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    demo_cases = [
        ("Chipping", "Head_Temp", 2.8, 42.3),        # Tier1 즉시조치
        ("Remain_Coat", "CLN_Pressure", -1.7, 2.1),  # Tier2c 조건부조치
        ("Particle", "Vibration", 0.9, 0.081),        # Tier2d 관찰만
        ("Chipping", "Kerf_Width_Profile", 3.6, 8.1), # Tier1 감시지표
        ("Chipping", "Head_Temp", 0.5, 38.0),         # 정상범위 -> 알림 없음 확인용
    ]
    for defect, factor, z, raw in demo_cases:
        print("=" * 70)
        print(f"[입력] defect={defect}, factor={factor}, z={z:+.2f}, raw={raw}")
        msg = generate_alert(defect, factor, z, raw_value=raw)
        print(msg if msg else "(정상 범위 — 알림 없음)")
    print("=" * 70)
