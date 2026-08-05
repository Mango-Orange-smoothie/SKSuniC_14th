"""db_09 — Target x Top Variables 요약본 (Wide 형태)

아키텍처 설계도의 Relationship DB 저장 형태:
    Target          Top Variables
    Kerf Width      Laser, Gas, Focus
    Kerf Depth      Cooling, Pressure

기존 db_01(Long, 63행)·db_02(엣지)·db_06(SHAP)·db_08(3방법 대조)에서 파생한 **뷰**다.
원본을 대체하지 않는다 — 상세 근거가 필요하면 db_01/db_02를 봐야 한다.

Target 두 종류를 모두 담는다:
  - Defect  : Chipping / Micro_Crack        -> 원인(FDC) + 감시지표(Response)
  - Response: Kerf_Width_Profile 등          -> 그 측정값을 만드는 FDC (설계도의 Kerf Width 행)

방향 표기: ↑ 높을수록 위험 / ↓ 낮을수록 위험 / ~ 비선형·방향 불명
신뢰도는 절대 생략하지 않는다 (근거 세탁 방지).
"""
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent
ARROW = {"up": "↑", "high_is_risky": "↑",
         "down": "↓", "low_is_risky": "↓",
         "either": "~", "nonlinear_or_none": "~", "not_applicable": "~", "unknown": "~"}

fac = pd.read_csv(OUT / "db_01_factors.csv", encoding="utf-8-sig")
edge = pd.read_csv(OUT / "db_02_relationships.csv", encoding="utf-8-sig")
shap = pd.read_csv(OUT / "db_06_shap_global.csv", encoding="utf-8-sig")
agree = pd.read_csv(OUT / "db_08_method_agreement.csv", encoding="utf-8-sig")
thr = pd.read_csv(OUT / "db_03_thresholds.csv", encoding="utf-8-sig")

CONFIRMED = ("confirmed", "shared_cause_with_Chipping", "shared_cause_with_Micro_Crack")
CANDIDATE = ("candidate_weak_signal", "candidate_needs_domain_review", "candidate_nonlinear_only")


def fmt(items):
    """[(name, arrow, score)] -> 'Name↑(1.98), Name2↓(1.18)'"""
    return ", ".join(f"{n}{a}({s:.3f})" if s is not None else f"{n}{a}" for n, a, s in items)


rows = []

# ============================================================ Defect 타깃
for target in ["Chipping", "Micro_Crack"]:
    f = fac[fac.target == target]
    sh = shap[(shap.target == target) & (shap.model == "A_cause_FDConly")]
    shp = dict(zip(sh.factor, sh.mean_abs_shap))
    shd = dict(zip(sh.factor, sh.shap_direction))
    auc = sh.model_roc_auc.iloc[0] if len(sh) else None
    nfeat = int(sh.n_features.iloc[0]) if len(sh) else None
    agree3 = sorted(set(agree[(agree.target == target)
                              & (agree.n_methods_in_top10 == 3)].factor))

    def pick(role, verdicts):
        sub = f[(f.role == role) & (f.verdict.isin(verdicts))].copy()
        # 원인은 SHAP 크기순, 감시지표는 효과크기순
        if role == "원인후보":
            sub["_s"] = sub.factor.map(shp).fillna(0)
            sub = sub.sort_values("_s", ascending=False)
            return [(r.factor, ARROW.get(shd.get(r.factor, r.direction_hypothesis), "~"),
                     shp.get(r.factor)) for r in sub.itertuples()]
        sub = sub.reindex(sub.delta_pure.abs().sort_values(ascending=False).index)
        return [(r.factor, "↑" if r.delta_pure > 0 else "↓", abs(r.delta_pure))
                for r in sub.itertuples()]

    causes_c = pick("원인후보", CONFIRMED)
    causes_w = pick("원인후보", CANDIDATE)
    mons_c = pick("감시지표", CONFIRMED)
    mons_w = pick("감시지표", CANDIDATE)

    cautions = sorted({c for c in f.caution.dropna().unique() if c})
    th = thr[thr.target == target].sort_values("risk_ratio", ascending=False).head(3)
    th_txt = " / ".join(f"{r.variable} z{r.threshold_z:+.2f} → {r.risk_ratio:.0f}배"
                        for r in th.itertuples())

    rows.append({
        "target": target,
        "target_type": "Defect",
        "top_causes_confirmed": fmt(causes_c),
        "top_causes_candidate": fmt(causes_w),
        "top_monitors_confirmed": fmt(mons_c),
        "top_monitors_candidate": fmt(mons_w),
        "n_methods_agree_all3": ", ".join(agree3),
        "model_performance": f"SHAP 원인모델 ROC-AUC {auc} (피처 {nfeat}개)",
        "top_thresholds": th_txt,
        "score_meaning": "원인=평균|SHAP| / 감시지표=Cliff's delta(pure 라벨)",
        "caution": " | ".join(cautions),
        "detail_ref": "db_01_factors.csv (근거·재현성), db_06(SHAP), db_08(3방법 대조)",
        "source_branch": "JHdaimma",
    })

# ============================================================ Response 타깃 (설계도의 Kerf Width 행)
drives = edge[edge.relation == "drives"]
for resp in sorted(drives.target.unique()):
    d = drives[drives.target == resp].sort_values("strength", ascending=False)
    items = [(r.source, ARROW.get(r.direction, "~"), r.strength) for r in d.itertuples()]
    r2 = d.method.iloc[0].split("R2=")[-1].rstrip(")") if "R2=" in d.method.iloc[0] else ""
    # 이 Response가 어떤 defect의 감시지표인지
    mon_for = sorted(set(edge[(edge.relation == "monitors") & (edge.source == resp)].target))
    rows.append({
        "target": resp,
        "target_type": "Response",
        "top_causes_confirmed": fmt(items),
        "top_causes_candidate": "",
        "top_monitors_confirmed": "",
        "top_monitors_candidate": "",
        "n_methods_agree_all3": "",
        "model_performance": f"FDC로 설명한 R² = {r2}",
        "top_thresholds": "",
        "score_meaning": "RandomForest permutation importance (이 측정값을 만드는 기여도)",
        "caution": ("이 측정값의 감시 대상: " + ", ".join(mon_for)) if mon_for else "",
        "detail_ref": "db_02_relationships.csv (relation=drives)",
        "source_branch": "JHdaimma",
    })

df = pd.DataFrame(rows)
df.to_csv(OUT / "db_09_target_top_variables.csv", index=False, encoding="utf-8-sig")

print(f"db_09_target_top_variables.csv 생성 — {len(df)}행 "
      f"(Defect {sum(df.target_type=='Defect')} + Response {sum(df.target_type=='Response')})\n")
for _, r in df.iterrows():
    print(f"[{r.target_type}] {r.target}")
    if r.top_causes_confirmed:
        print(f"   원인/드라이버 : {r.top_causes_confirmed}")
    if r.top_monitors_confirmed:
        print(f"   감시지표      : {r.top_monitors_confirmed}")
    if r.model_performance:
        print(f"   성능         : {r.model_performance}")
    print()
