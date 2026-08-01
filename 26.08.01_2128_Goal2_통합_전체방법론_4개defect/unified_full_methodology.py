"""Goal 2 — Particle / Remain_Coat / Chipping / Micro_Crack 통합 전체방법론.

팀 3명(박대호=Particle, 전성재=Remain_Coat, JHdaimma=Chipping·Micro_Crack)이 각자
서로 다른 방법을 보강해서 검증했다. 이 스크립트는 **6개 방법론 전부를 4개 defect
모두에 동일하게** 적용해서, 어느 defect의 결론이든 같은 급의 신뢰도를 갖게 만든다.

  방법 A  Mann-Whitney U + BH-FDR + Cliff's delta (+ |z| 비선형)   [팀 전체 공통 기반]
  방법 B  RandomForest permutation importance                     [팀 전체 공통 기반]
  방법 C  L1(Lasso) 로지스틱 + HistGradientBoosting (Machine 통제) [전성재 원안]
  방법 D  XGBoost + TreeSHAP, 모델 A(FDC전용)/B(전체)로 분리        [JHdaimma 원안]
  방법 E  DecisionTree stump 위험선                                [JHdaimma 원안]
  방법 F  시간 선행성(lag window 5/20/50 스트립)                    [박대호 원안, 전성재 확장]

BURN(Edge_Burn)은 멘토 최종 확인으로 Goal2 대상에서 제외됨 — 이 4개 defect만 다룬다.
Focus/Cutting_Offset은 멘토 지시로 후보에서 제외.

데이터: 원본(100,000행) + r1(100,000행) 통합 = 200,000행. 통합 후 co-occurrence를
재확인한 결과 박대호 원안(원본 단독)과 달리 **4개 defect 전부 서로 유의미하게
동시발생**한다(예: Particle&Remain_Coat 5,793건) — 그래서 이번엔 4개 전부에 pure
라벨(다른 3개 defect 동시발생 배제)을 적용한다.

산출물 (이 폴더 안):
  00_summary.json                        실행 메타데이터 + defect별 최종 confirmed 목록
  01_{defect}_univariate.csv             방법 A
  02_{defect}_rf_importance.csv          방법 B
  03_{defect}_machine_controlled.csv     방법 C (L1 로지스틱 + HGB)
  04_{defect}_shap.csv                   방법 D (모델 A/B SHAP)
  05_{defect}_thresholds.csv             방법 E (위험선)
  06_{defect}_temporal_precedence.csv    방법 F (선행성)
  07_{defect}_unified_verdict.csv        **6개 방법 통합 최종 판정표**
  08_cross_defect_vibration.csv          Vibration 교차 defect 비교 (헤드라인 발견)
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy import stats as scipy_stats
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PARENT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402
from pipeline.common import compute_stratum_baseline_stats, zscore_transform  # noqa: E402

OUT = Path(__file__).resolve().parent
RNG = 42

OPCOND = config.OPCOND
EFFECT_SIZE_MIN = 0.2
FDR_ALPHA = config.TREND_ALPHA
TREE_TOP_N = 10
LAG_WINDOWS = [5, 20, 50]
RETENTION_LOW = 0.15

# 멘토 지시(26.07.31): Focus/Cutting_Offset 제외. Frequency는 이미 fdc_laser로 포함됨.
CANDIDATE_COLS = [c for c in (config.FDC_COLS + config.RESPONSES)
                  if c not in ("Focus", "Cutting_Offset")]
TEAM_DOMAIN_FEATURES = config.DOMAIN_FEATURES
ALL_FEATURE_COLS = CANDIDATE_COLS + TEAM_DOMAIN_FEATURES + ["Maintenance_Count"]

DEFECTS = {
    "Particle": {"ng": "PARTICLE", "bin": "Particle"},
    "Remain_Coat": {"ng": "REM_COAT", "bin": "Remain_Coat"},
    "Chipping": {"ng": "CHIP", "bin": "Chipping"},
    "Micro_Crack": {"ng": "CRACK", "bin": "Micro_Crack"},
}
ALL_DEFECT_BIN_COLS = [v["bin"] for v in DEFECTS.values()]

# layer 판정 (JHdaimma 원안과 동일 원칙) — FDC=직접 조절 가능, Response=측정결과
FDC_SET = set(config.FDC_COLS)
RESPONSE_SET = set(config.RESPONSES)
DERIVED_LAYER = {
    "Cooling_Thermal_Load": "FDC",
    "Cleaning_Capacity": "FDC",
    "Laser_Cleaning_Demand": "Response",
    "Cleaning_Load_Ratio": "Response",
}


def layer_of(col: str) -> str:
    if col in DERIVED_LAYER:
        return DERIVED_LAYER[col]
    if col in RESPONSE_SET:
        return "Response"
    if col in FDC_SET:
        return "FDC"
    return "Other"


# =============================================================================
# 도메인 가설 — 각 담당자가 이미 확정한 결론을 그대로 재사용한다 (재도출하지 않음)
# =============================================================================

# 박대호 최종 결론(06_particle_influence_factors_FINAL.csv 요약)
PARTICLE_DOMAIN = {
    "Vibration": ("기계적 진동 — 디브리 비산/재부착. 박대호 선행신호검증 통과(잔존율 33.5%)", "up"),
}
PARTICLE_MONITOR_ONLY = {
    "Surface_Roughness": "박대호 검증: 선행신호 소멸(잔존율 7.5%) — 결과 공변, 원인 아님. 감시지표로만 사용",
}
PARTICLE_REJECTED = {
    "CLN_Pressure": "박대호 검증4: particle 단독 그룹에서 무신호(delta -0.002) — REM_COAT 오염이었음",
    "CLN_Flow": "박대호 검증4: REM_COAT 오염",
    "Cleaning_Capacity": "박대호 검증4: REM_COAT 오염",
    "Cleaning_Load_Ratio": "박대호 검증3: 비율 정의 4종 전부 무신호",
}

# 전성재 최종 결론(04_rem_coat_influence_factors_final.csv + 검증9 요약)
REMCOAT_DOMAIN = {
    "CLN_Pressure": (
        "세정 압력 — 그 스트립 세정 순간의 즉시적 압력 하락(전성재 검증9: 추세형 아님, "
        "선행신호 소멸 4.1% but 동시점 신호는 5개 독립방법이 뒷받침). SOP는 추세감시가 "
        "아니라 스트립별 실시간 급락 알람으로 설계할 것", "down",
    ),
}
REMCOAT_REJECTED = {
    "Coating_Thickness": "전성재 검증: 세정 후 측정이면 잔류 코팅량과 동어반복(데이터 누수 위험) — 측정시점 확인 전까지 제외. 선행신호도 소멸(0.7%)로 결과공변 해석과 일치",
    "CLN_Time": "전성재 검증9: 동시점부터 무신호(p=0.60) — 원인 후보에서 완전 제외",
    "CLN_Flow": "전성재 검증6: Machine 통제 다변량(L1)에서 계수 0 — CLN_Pressure가 이미 설명하는 것 이상의 독자정보 없음",
    "Cleaning_Capacity": "전성재 검증6: L1에서 계수 0",
    "Cleaning_Load_Ratio": "전성재 검증6: L1에서 계수 0",
}

# JHdaimma 최종 결론(db_01_factors.csv 요약, Chipping/Micro_Crack 공용 딕셔너리에서 발췌)
CHIP_DOMAIN = {
    "Head_Temp": ("헤드온도->크리스탈 스팟온도->굴절률->센터링 변화->Chipping/Kerf 불균일 (멘토 인과사슬 확정)", "up"),
    "Laser_Power": ("출력 부족 -> low-k 불완전 승화 -> 잔류물에 블레이드 충돌 (JHdaimma 데이터 반증: Jun 원안의 Burn전용 분류는 오분류였음)", "down"),
    "Power_Efficiency": ("실제 조사 에너지 이상 -> 승화 불완전 (멘토: U자형 비선형 주의)", "either"),
    "Vibration": ("장비 노후로 스테이지 축 이동 시 진동 -> 나이프 자국형 대형 불량 (팀설계서 회의록 + 멘토 사고사례)", "up"),
    "Laser_Centering_Position": ("Head_Temp 인과사슬 종착점 — 빔 중심 이탈로 비대칭 절단", "either"),
    "Groove_Depth": ("깊이 부족 시 low-k 미승화 -> 블레이드가 잔류 low-k 직접 타격", "down"),
    "Kerf_Width_Profile": ("레이저 홈 폭 < 블레이드 폭이면 블레이드가 안 파인 low-k 가장자리 침범", "either"),
}
CHIP_MONITOR_ONLY = {
    "Kerf_Width_Profile": "JHdaimma: 감시지표(Response layer) — Laser_Power/Head_Temp의 결과값",
    "Groove_Depth": "JHdaimma: 감시지표(Response layer)",
}

CRACK_DOMAIN = {
    "Vibration": ("장비/스테이지 진동. 멘토가 설비 열화 대표신호로 지목, 실제 스크랩 사고 사례. JHdaimma SHAP 원인모델 1위", "up"),
}
CRACK_MONITOR_ONLY = {
    "Surface_Roughness": "JHdaimma: Vibration의 압도적 드라이버(perm.imp 0.424)라 균열과 공통원인을 공유하는 동반지표",
}
# 현업 확정: Micro_Crack은 레이저 그루빙 문제가 아님 -> 그루빙 계열 컬럼 제외
CRACK_GROOVING_EXCLUDED = [
    "Laser_Power", "Power_Efficiency", "Laser_Current", "Laser_Voltage",
    "Beam_Diameter", "Laser_Centering_Position", "Frequency", "Feed_Speed",
    "Head_Temp", "Laser_Head_Remain_Time", "Groove_Depth", "Kerf_Width_Profile",
    "Top_Kerf", "Bottom_Kerf", "Kerf_Angle", "Laser_Cleaning_Demand",
]

DEFECT_DOMAIN = {
    "Particle": {"domain": PARTICLE_DOMAIN, "monitor_only": PARTICLE_MONITOR_ONLY,
                 "rejected": PARTICLE_REJECTED, "excluded_mechanism": []},
    "Remain_Coat": {"domain": REMCOAT_DOMAIN, "monitor_only": {},
                     "rejected": REMCOAT_REJECTED, "excluded_mechanism": []},
    "Chipping": {"domain": CHIP_DOMAIN, "monitor_only": CHIP_MONITOR_ONLY,
                 "rejected": {}, "excluded_mechanism": []},
    "Micro_Crack": {"domain": CRACK_DOMAIN, "monitor_only": CRACK_MONITOR_ONLY,
                     "rejected": {}, "excluded_mechanism": CRACK_GROOVING_EXCLUDED},
}


def domain_info(defect: str, column: str) -> tuple[str, str, bool, str]:
    spec = DEFECT_DOMAIN[defect]
    if column in spec["excluded_mechanism"]:
        return "[현업확정] Micro_Crack은 레이저 그루빙 문제가 아님 — 그루빙 계열 제외", "not_applicable", False, "not_related_to_defect"
    if column in spec["domain"]:
        mech, direction = spec["domain"][column]
        return mech, direction, True, "defect_related"
    if column in spec["rejected"]:
        return spec["rejected"][column], "not_applicable", False, "rejected_by_followup"
    if column in spec["monitor_only"]:
        return spec["monitor_only"][column], "not_applicable", False, "monitor_only_not_cause"
    return "미분류 — 팀 원안에 없던 컬럼, 이번 통합 스캔에서 새로 확인 필요", "unknown", False, "unclassified"


# =============================================================================
# 0단계: 데이터 로드 (원본 + r1 통합) + baseline/z-score
# =============================================================================
print("[0] 데이터 로드 (원본 + r1 통합)")
o = pd.read_csv(DATA_PARENT / "DP_HealthIndex_Dataset.csv", encoding="utf-8-sig")
r = pd.read_csv(DATA_PARENT / "DP_HealthIndex_Dataset_r1.csv", encoding="utf-8-sig")
o["source_dataset"] = "original"
r["source_dataset"] = "r1"
df = pd.concat([o, r], ignore_index=True)
df["DateTime"] = pd.to_datetime(df["DateTime"], format="mixed")  # r1은 초(:00)가 추가로 붙어 원본과 포맷이 다름
df["is_normal"] = (df["Yield"] == 100) & (df["NG_Code"] == "OK")
df = config.add_domain_features(df)
print(f"    통합 {len(df):,}행 (original {len(o):,} + r1 {len(r):,}) | 정상군 {df.is_normal.sum():,}")

baseline_path = config.PREPROCESSING_DIR / "00_stratum_baseline_stats_by_opcond.csv"
baseline_orig = pd.read_csv(baseline_path)  # 원본 전용이라 재계산 필요 (r1 포함 안 됨)
baseline = compute_stratum_baseline_stats(df[df["is_normal"]], OPCOND, ALL_FEATURE_COLS)
df = zscore_transform(df, baseline, OPCOND, ALL_FEATURE_COLS)
for c in ALL_FEATURE_COLS:
    df[f"{c}_absz"] = df[f"{c}_z"].abs()

mach_dummies = pd.get_dummies(df["Machine_ID"], prefix="MACH", drop_first=True).astype(float)
ds_dummies = pd.get_dummies(df["source_dataset"], prefix="DS", drop_first=True).astype(float)

summary = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "n_rows": int(len(df)), "n_normal": int(df.is_normal.sum()),
           "n_features": len(ALL_FEATURE_COLS), "defects": {}}
all_unified = {}


def cliffs(a, b) -> tuple[float, float]:
    a = pd.Series(a).dropna(); b = pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    u, p = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    return (2 * u) / (len(a) * len(b)) - 1, p


# =============================================================================
# 방법 A — Mann-Whitney U + BH-FDR + Cliff's delta (+ |z| 비선형)
# =============================================================================
def method_a_univariate(feats, labels):
    rows = []
    for lab_name, mask in labels.items():
        for c in feats:
            d, p = cliffs(df.loc[mask, f"{c}_z"], df.loc[~mask, f"{c}_z"])
            dn, pn = cliffs(df.loc[mask, f"{c}_absz"], df.loc[~mask, f"{c}_absz"])
            rows.append({"label": lab_name, "column": c, "delta": d, "p": p,
                        "delta_abs": dn, "p_abs": pn})
    t = pd.DataFrame(rows)
    t["p_fdr"] = np.nan; t["p_fdr_abs"] = np.nan
    for lab_name, idx in t.groupby("label").groups.items():
        t.loc[idx, "p_fdr"] = multipletests(t.loc[idx, "p"].fillna(1), alpha=FDR_ALPHA, method="fdr_bh")[1]
        t.loc[idx, "p_fdr_abs"] = multipletests(t.loc[idx, "p_abs"].fillna(1), alpha=FDR_ALPHA, method="fdr_bh")[1]
    t["univariate_flag"] = (t.p_fdr < FDR_ALPHA) & (t.delta.abs() >= EFFECT_SIZE_MIN)
    t["nonlinear_flag"] = (t.p_fdr_abs < FDR_ALPHA) & (t.delta_abs.abs() >= EFFECT_SIZE_MIN)
    return t


# =============================================================================
# 방법 B — RandomForest permutation importance (pure 라벨)
# =============================================================================
def method_b_randomforest(feats, y, keep):
    fz = [f"{c}_z" for c in feats]
    dd = df.loc[keep, fz + []].copy()
    dd["_y"] = y[keep]
    tr, te = train_test_split(dd, test_size=0.2, random_state=RNG, stratify=dd["_y"])
    m = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced",
                               random_state=RNG, n_jobs=-1).fit(tr[fz], tr["_y"])
    tes = te.sample(n=min(20000, len(te)), random_state=RNG)
    pi = permutation_importance(m, tes[fz], tes["_y"], scoring="average_precision",
                                n_repeats=10, random_state=RNG, n_jobs=-1)
    t = pd.DataFrame({"column": feats, "rf_importance": pi.importances_mean})
    t["rf_rank"] = t.rf_importance.rank(ascending=False, method="min").astype(int)
    t["rf_flag"] = (t.rf_rank <= TREE_TOP_N) & (t.rf_importance > 0)
    return t


# =============================================================================
# 방법 C — L1(Lasso) 로지스틱 + HistGradientBoosting (Machine 통제, pure 라벨)
# =============================================================================
def method_c_machine_controlled(feats, y, keep):
    fz = [f"{c}_z" for c in feats]
    X = pd.concat([df.loc[keep, fz], mach_dummies.loc[keep], ds_dummies.loc[keep]], axis=1)
    yy = y[keep]
    Xtr, Xte, ytr, yte = train_test_split(X, yy, test_size=0.25, random_state=RNG, stratify=yy)

    l1 = LogisticRegression(penalty="l1", solver="liblinear", C=0.5,
                            class_weight="balanced", random_state=RNG, max_iter=2000)
    l1.fit(Xtr, ytr)
    coefs = pd.Series(l1.coef_[0], index=X.columns)
    l1_auc = roc_auc_score(yte, l1.predict_proba(Xte)[:, 1])

    hgb = HistGradientBoostingClassifier(max_depth=6, random_state=RNG,
                                         class_weight="balanced").fit(Xtr, ytr)
    hgb_auc = roc_auc_score(yte, hgb.predict_proba(Xte)[:, 1])
    Xte_s = Xte.sample(n=min(15000, len(Xte)), random_state=RNG)
    pi = permutation_importance(hgb, Xte_s, yte.loc[Xte_s.index], scoring="roc_auc",
                                n_repeats=8, random_state=RNG, n_jobs=-1)
    hgb_imp = pd.Series(pi.importances_mean, index=X.columns)

    rows = []
    for c in feats:
        zc = f"{c}_z"
        rows.append({
            "column": c, "l1_coef": round(float(coefs.get(zc, 0.0)), 5),
            "l1_odds_ratio": round(float(np.exp(coefs.get(zc, 0.0))), 4),
            "l1_nonzero": bool(abs(coefs.get(zc, 0.0)) > 1e-9),
            "hgb_importance": round(float(hgb_imp.get(zc, 0.0)), 6),
        })
    t = pd.DataFrame(rows)
    t["hgb_rank"] = t.hgb_importance.rank(ascending=False, method="min").astype(int)
    t["hgb_flag"] = (t.hgb_rank <= TREE_TOP_N) & (t.hgb_importance > 0)
    t["machine_controlled_flag"] = t.l1_nonzero & t.hgb_flag
    meta = {"l1_auc": round(float(l1_auc), 4), "hgb_auc": round(float(hgb_auc), 4)}
    return t, meta


# =============================================================================
# 방법 D — XGBoost + TreeSHAP, 모델 A(FDC전용,원인)/B(전체,감시) 분리 (pure 라벨)
# =============================================================================
def method_d_shap(feats, y, keep):
    fdc_only = [c for c in feats if layer_of(c) == "FDC"]
    models = {"A_cause_FDConly": fdc_only, "B_monitor_full": feats}
    all_rows = []
    meta = {}
    for mname, mfeats in models.items():
        if len(mfeats) < 2:
            continue
        fz = [f"{c}_z" for c in mfeats]
        X = pd.concat([df.loc[keep, fz], mach_dummies.loc[keep], ds_dummies.loc[keep]], axis=1)
        yy = y[keep]
        Xtr, Xte, ytr, yte = train_test_split(X, yy, test_size=0.25, random_state=RNG, stratify=yy)
        spw = float((ytr == 0).sum() / max((ytr == 1).sum(), 1))
        clf = xgb.XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.08,
                                subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                                scale_pos_weight=spw, eval_metric="aucpr",
                                random_state=RNG, n_jobs=-1, tree_method="hist")
        clf.fit(Xtr, ytr)
        proba = clf.predict_proba(Xte)[:, 1]
        auc = roc_auc_score(yte, proba); ap = average_precision_score(yte, proba)
        sub = Xte.sample(n=min(20000, len(Xte)), random_state=RNG)
        dm = xgb.DMatrix(sub, feature_names=list(sub.columns))
        contribs = clf.get_booster().predict(dm, pred_contribs=True)
        sv = np.asarray(contribs)[:, :-1]
        mean_abs = np.abs(sv).mean(axis=0)
        dir_corr = [float(np.corrcoef(sub.iloc[:, j].values, sv[:, j])[0, 1])
                   if np.std(sub.iloc[:, j].values) > 1e-12 else np.nan
                   for j in range(sub.shape[1])]
        tab = pd.DataFrame({"feature_col": sub.columns, "mean_abs_shap": mean_abs,
                            "value_shap_corr": dir_corr})
        ctrl_cols = list(mach_dummies.columns) + list(ds_dummies.columns)
        tab = tab[~tab.feature_col.isin(ctrl_cols)].copy()
        tab["column"] = tab.feature_col.str.replace("_z$", "", regex=True)
        tab["model"] = mname
        tab["shap_rank"] = tab.mean_abs_shap.rank(ascending=False, method="min").astype(int)
        tab["shap_direction"] = np.select(
            [tab.value_shap_corr > 0.05, tab.value_shap_corr < -0.05],
            ["high_is_risky", "low_is_risky"], default="nonlinear_or_none")
        all_rows.append(tab[["model", "column", "mean_abs_shap", "shap_rank", "shap_direction"]])
        meta[mname] = {"roc_auc": round(float(auc), 4), "pr_auc": round(float(ap), 4),
                       "n_features": len(mfeats)}
    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(), meta


# =============================================================================
# 방법 E — DecisionTree stump 위험선 (pure 라벨)
# =============================================================================
def method_e_thresholds(feats, y, keep):
    rows = []
    yk = y[keep]
    if yk.sum() < 30:
        return pd.DataFrame(rows)
    for c in feats:
        X = df.loc[keep, [f"{c}_z"]].fillna(0).values
        t = DecisionTreeClassifier(max_depth=1, min_samples_leaf=200, random_state=0).fit(X, yk)
        if t.tree_.feature[0] == -2:
            continue
        thr = float(t.tree_.threshold[0])
        below = yk[X[:, 0] < thr]; above = yk[X[:, 0] >= thr]
        if len(below) < 50 or len(above) < 50:
            continue
        rb, ra = below.mean(), above.mean()
        risky = "low_is_risky" if rb > ra else "high_is_risky"
        rows.append({
            "column": c, "threshold_z": round(thr, 4), "risky_direction": risky,
            "defect_rate_below_pct": round(float(rb) * 100, 3),
            "defect_rate_above_pct": round(float(ra) * 100, 3),
            "risk_ratio": round(float(max(rb, ra) / max(min(rb, ra), 1e-9)), 2),
            "n_below": int((X[:, 0] < thr).sum()), "n_above": int((X[:, 0] >= thr).sum()),
        })
    return pd.DataFrame(rows).sort_values("risk_ratio", ascending=False)


# =============================================================================
# 방법 F — 시간 선행성 (lag window 5/20/50 스트립, source_dataset별 독립 정렬)
# =============================================================================
def method_f_temporal(feats, labels):
    ordered = df.sort_values(["source_dataset", "Machine_ID", "DateTime"]).copy()
    rows = []
    for c in feats:
        zcol = f"{c}_z"
        # lag 컬럼은 라벨과 무관하므로 (컬럼,윈도우)당 한 번만 계산해서 재사용한다.
        lag_cache = {}
        for w in LAG_WINDOWS:
            lag_cache[w] = ordered.groupby(["source_dataset", "Machine_ID"])[zcol].transform(
                lambda s, ww=w: s.shift(1).rolling(ww, min_periods=max(3, ww // 2)).mean())
        for lab_name, mask in labels.items():
            mask_o = mask.reindex(ordered.index)
            d_now, p_now = cliffs(ordered.loc[mask_o, zcol], ordered.loc[~mask_o, zcol])
            for w in LAG_WINDOWS:
                lag = lag_cache[w]
                d_lag, p_lag = cliffs(lag[mask_o], lag[~mask_o])
                retention = abs(d_lag) / abs(d_now) if pd.notna(d_now) and abs(d_now) > 1e-9 else np.nan
                rows.append({"column": c, "label": lab_name, "lag_window": w,
                            "delta_concurrent": d_now, "delta_lagged": d_lag,
                            "p_lagged": p_lag, "signal_retention_ratio": retention})
    t = pd.DataFrame(rows)
    t["p_lagged_fdr"] = np.nan
    for (lab_name, w), idx in t.groupby(["label", "lag_window"]).groups.items():
        t.loc[idx, "p_lagged_fdr"] = multipletests(t.loc[idx, "p_lagged"].fillna(1), alpha=FDR_ALPHA, method="fdr_bh")[1]
    t["lagged_significant"] = (t.p_lagged_fdr < FDR_ALPHA) & (t.delta_lagged.abs() >= EFFECT_SIZE_MIN)

    def interpret(row):
        if pd.isna(row.delta_lagged):
            return "판정불가"
        if row.lagged_significant:
            return "선행신호 유지 - 상류 원인 가능성"
        if pd.notna(row.signal_retention_ratio) and row.signal_retention_ratio < RETENTION_LOW:
            return "선행신호 소멸 - 결과 공변 해석 지지"
        return "선행신호 약함 - 판단 보류"
    t["interpretation"] = t.apply(interpret, axis=1)
    return t


# =============================================================================
# 메인 루프 — 4개 defect 각각에 방법 A~F 전부 적용
# =============================================================================
for dname, spec in DEFECTS.items():
    print(f"\n{'='*78}\n### DEFECT: {dname}\n{'='*78}")
    others = [b for b in ALL_DEFECT_BIN_COLS if b != spec["bin"]]

    primary = (df["NG_Code"] == spec["ng"])
    broad = (df[spec["bin"]] == 1)
    pure = broad & (df[others] == 0).all(axis=1)
    # pure 라벨 학습용 keep 마스크: "이 defect는 없는데 다른 defect가 있는" 오염행 제외
    keep = ~(~broad & (df[others] == 1).any(axis=1))
    labels = {"primary": primary, "broad": broad, "pure": pure}
    print(f"  primary={primary.sum():,}  broad={broad.sum():,}  pure={pure.sum():,}  "
          f"(다른 defect 동시발생 배제 {broad.sum() - pure.sum():,}건) keep={keep.sum():,}")

    if dname == "Micro_Crack":
        feats = [c for c in ALL_FEATURE_COLS if c not in CRACK_GROOVING_EXCLUDED]
        print(f"  [현업확정] 그루빙 계열 {len(ALL_FEATURE_COLS) - len(feats)}개 제외 -> 후보 {len(feats)}개")
    else:
        feats = ALL_FEATURE_COLS

    y_pure = pure.astype(int)

    print("  [A] Mann-Whitney U + BH-FDR + Cliff's delta (+|z| 비선형)")
    t_a = method_a_univariate(feats, labels)
    t_a.to_csv(OUT / f"01_{dname.lower()}_univariate.csv", index=False, encoding="utf-8-sig")

    print("  [B] RandomForest permutation importance (pure)")
    t_b = method_b_randomforest(feats, y_pure, keep)
    t_b.to_csv(OUT / f"02_{dname.lower()}_rf_importance.csv", index=False, encoding="utf-8-sig")

    print("  [C] L1 로지스틱 + HistGradientBoosting (Machine 통제, pure)")
    t_c, meta_c = method_c_machine_controlled(feats, y_pure, keep)
    t_c.to_csv(OUT / f"03_{dname.lower()}_machine_controlled.csv", index=False, encoding="utf-8-sig")
    print(f"      L1 AUC={meta_c['l1_auc']}  HGB AUC={meta_c['hgb_auc']}")

    print("  [D] XGBoost + TreeSHAP 모델 A(FDC전용)/B(전체) (pure)")
    t_d, meta_d = method_d_shap(feats, y_pure, keep)
    t_d.to_csv(OUT / f"04_{dname.lower()}_shap.csv", index=False, encoding="utf-8-sig")
    for mn, mm in meta_d.items():
        print(f"      [{mn}] AUC={mm['roc_auc']} PR-AUC={mm['pr_auc']} 피처{mm['n_features']}개")

    print("  [E] DecisionTree stump 위험선 (pure)")
    t_e = method_e_thresholds(feats, y_pure, keep)
    t_e.to_csv(OUT / f"05_{dname.lower()}_thresholds.csv", index=False, encoding="utf-8-sig")

    # 방법 F는 팀 관행대로 이미 신호가 있는 후보만 (전수조사 아님) — A/B/C/D 중 하나라도
    # 걸린 컬럼 + 도메인 가설표에 있는 컬럼만 추린다.
    uni_pure_flag = set(t_a.loc[(t_a.label == "pure") & (t_a.univariate_flag), "column"])
    rf_flag_cols = set(t_b.loc[t_b.rf_flag, "column"])
    mc_flag_cols = set(t_c.loc[t_c.machine_controlled_flag, "column"])
    shap_flag_cols = set(t_d.loc[(t_d.model == "A_cause_FDConly") & (t_d.shap_rank <= TREE_TOP_N), "column"]) if len(t_d) else set()
    domain_cols = set(DEFECT_DOMAIN[dname]["domain"].keys()) | set(DEFECT_DOMAIN[dname]["monitor_only"].keys())
    temporal_targets = sorted((uni_pure_flag | rf_flag_cols | mc_flag_cols | shap_flag_cols | domain_cols) & set(feats))
    print(f"  [F] 시간 선행성(lag 5/20/50) — 대상 {len(temporal_targets)}개: {temporal_targets}")
    t_f = method_f_temporal(temporal_targets, labels) if temporal_targets else pd.DataFrame()
    if len(t_f):
        t_f.to_csv(OUT / f"06_{dname.lower()}_temporal_precedence.csv", index=False, encoding="utf-8-sig")

    # ---------------- 통합 판정 (6개 방법 -> tier) ----------------
    rows = []
    for c in feats:
        mech, direction, has_support, dstatus = domain_info(dname, c)
        a_pure = t_a[(t_a.label == "pure") & (t_a.column == c)]
        b_row = t_b[t_b.column == c]
        c_row = t_c[t_c.column == c]
        d_rows = t_d[t_d.column == c] if len(t_d) else pd.DataFrame()

        delta_pure = float(a_pure.delta.iloc[0]) if len(a_pure) else np.nan
        p_fdr_pure = float(a_pure.p_fdr.iloc[0]) if len(a_pure) else np.nan
        uni_flag = bool(a_pure.univariate_flag.iloc[0]) if len(a_pure) else False
        nonlin_flag = bool(a_pure.nonlinear_flag.iloc[0]) if len(a_pure) else False
        rf_flag = bool(b_row.rf_flag.iloc[0]) if len(b_row) else False
        mc_flag = bool(c_row.machine_controlled_flag.iloc[0]) if len(c_row) else False
        shap_A = d_rows[d_rows.model == "A_cause_FDConly"]
        shap_flag = bool((shap_A.shap_rank <= TREE_TOP_N).iloc[0]) if len(shap_A) else False
        shap_abs = float(shap_A.mean_abs_shap.iloc[0]) if len(shap_A) else np.nan

        n_methods = int(uni_flag) + int(rf_flag) + int(mc_flag) + int(shap_flag)

        # 방법 F 결과 취합 (pure 라벨, 3개 lag window 중 최선/최악 판정)
        tf_c = t_f[(t_f.column == c) & (t_f.label == "pure")] if len(t_f) else pd.DataFrame()
        if len(tf_c) == 0:
            temporal_status = "미검사"
        elif (tf_c.interpretation == "선행신호 유지 - 상류 원인 가능성").any():
            temporal_status = "선행신호 유지"
        elif (tf_c.interpretation == "선행신호 소멸 - 결과 공변 해석 지지").all():
            temporal_status = "선행신호 소멸(결과공변 의심)"
        else:
            temporal_status = "판단보류"

        if dstatus == "monitor_only_not_cause":
            tier = "monitor_only"
        elif dstatus == "rejected_by_followup":
            tier = "rejected"
        elif dstatus == "not_related_to_defect":
            tier = "excluded_domain"
        elif has_support and n_methods >= 2 and temporal_status == "선행신호 유지":
            tier = "Tier1_실행준비완료"
        elif has_support and n_methods >= 2 and temporal_status in ("판단보류", "미검사"):
            tier = "Tier2_통계확정_인과방향검증필요"
        elif has_support and n_methods >= 2 and temporal_status == "선행신호 소멸(결과공변 의심)":
            tier = "Tier2b_통계강함_결과공변의심"
        elif has_support and n_methods == 1:
            tier = "Tier3_약한신호"
        elif not has_support and n_methods >= 2:
            tier = "candidate_needs_domain_review"
        else:
            tier = "insufficient_evidence"

        rows.append({
            "defect": dname, "column": c, "layer": layer_of(c), "subsystem": next(
                (s for s, cols in config.SUBSYSTEMS.items() if c in cols),
                "engineered" if c in TEAM_DOMAIN_FEATURES else ("undocumented" if c == "Maintenance_Count" else "-")),
            "domain_status": dstatus, "domain_mechanism": mech, "direction_hypothesis": direction,
            "delta_pure": round(delta_pure, 4) if pd.notna(delta_pure) else None,
            "p_fdr_pure": f"{p_fdr_pure:.3e}" if pd.notna(p_fdr_pure) else None,
            "flag_univariate": uni_flag, "flag_nonlinear": nonlin_flag,
            "flag_rf": rf_flag, "flag_machine_controlled": mc_flag, "flag_shap": shap_flag,
            "shap_mean_abs": round(shap_abs, 5) if pd.notna(shap_abs) else None,
            "n_methods_agree": n_methods, "temporal_status": temporal_status,
            "tier": tier,
        })
    unified = pd.DataFrame(rows)
    tier_order = {"Tier1_실행준비완료": 0, "Tier2_통계확정_인과방향검증필요": 1,
                 "Tier2b_통계강함_결과공변의심": 2, "monitor_only": 3, "Tier3_약한신호": 4,
                 "candidate_needs_domain_review": 5, "rejected": 6, "excluded_domain": 7,
                 "insufficient_evidence": 8}
    unified["_o"] = unified.tier.map(tier_order)
    unified = unified.sort_values(["_o", "n_methods_agree"], ascending=[True, False]).drop(columns="_o")
    unified.to_csv(OUT / f"07_{dname.lower()}_unified_verdict.csv", index=False, encoding="utf-8-sig")
    all_unified[dname] = unified

    print(f"\n  --- {dname} 최종 판정 ---")
    for tr in ["Tier1_실행준비완료", "Tier2_통계확정_인과방향검증필요", "Tier2b_통계강함_결과공변의심", "monitor_only"]:
        sub = unified[unified.tier == tr]
        if len(sub):
            print(f"  [{tr}] " + ", ".join(sub.column.tolist()))

    summary["defects"][dname] = {
        "n_primary": int(primary.sum()), "n_broad": int(broad.sum()), "n_pure": int(pure.sum()),
        "l1_auc": meta_c["l1_auc"], "hgb_auc": meta_c["hgb_auc"],
        "shap_model_meta": meta_d,
        "tier1": unified.loc[unified.tier == "Tier1_실행준비완료", "column"].tolist(),
        "tier2": unified.loc[unified.tier == "Tier2_통계확정_인과방향검증필요", "column"].tolist(),
        "monitor_only": unified.loc[unified.tier == "monitor_only", "column"].tolist(),
    }

# =============================================================================
# 교차 defect 요약 — Vibration 등 여러 defect에 걸친 공통 인자
# =============================================================================
print(f"\n{'='*78}\n### 교차 defect 공통 인자\n{'='*78}")
combined = pd.concat(all_unified.values(), ignore_index=True)
cross_rows = []
for col, g in combined.groupby("column"):
    tiers = dict(zip(g.defect, g.tier))
    n_cause = sum(1 for t in tiers.values() if t.startswith("Tier1") or t.startswith("Tier2"))
    if n_cause >= 2:
        cross_rows.append({"column": col, "n_defects_as_cause": n_cause, **tiers})
cross_df = pd.DataFrame(cross_rows).sort_values("n_defects_as_cause", ascending=False) if cross_rows else pd.DataFrame()
cross_df.to_csv(OUT / "08_cross_defect_vibration.csv", index=False, encoding="utf-8-sig")
print(cross_df.to_string(index=False) if len(cross_df) else "  (2개 이상 defect에서 원인으로 확정된 공통 인자 없음)")

with open(OUT / "00_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("\n완료 —", OUT)
