r"""n8n 리포트용 결합 스크립트 (lsyeon 전용, main 브랜치와 무관).

build_health_index.py가 만든 health_index_data.json에는 그래프를 그릴 시계열
데이터가 없다 — 그건 pipeline/step0_preprocessing.py가 만드는
00_machine_daily_series.csv에 따로 있다. n8n Code 노드가 CSV까지 직접 파싱하게
만들면 복잡해지니, 여기서 미리 두 파일을 합쳐 JSON 하나로 만들어 둔다.

**출력은 stdout이 아니라 임시 폴더의 파일로 쓴다.** n8n Execute Command 노드는
spawn(..., detached: true)로 자식을 띄우는데(ExecuteCommand.node.js), Windows에서
이 옵션은 자식에게 새 콘솔을 붙인다. 그 상태에서 python이 stdout에 뭔가를 쓰면
파이프에도 파일 리다이렉트에도 안 들어가고 그냥 사라지고(exitCode는 0), 게다가
그 뒤에 오는 명령의 출력까지 같이 죽는다. 실측:
    python이 stdout에 출력      -> 캡처 0 bytes
    python이 open()으로 파일 쓰기 -> 정상 기록
    python(무출력) && type 파일   -> 정상 캡처
그래서 파이프라인은 전부 `> NUL`로 출력을 죽이고, 최종 전달만 cmd 내장명령 type이
맡는다. n8n Run Pipeline 명령 끝은 이렇게 된다:
    ... && python <이 파일> > NUL && type "%TEMP%\n8n_report_payload.json"

main 체크아웃 폴더에는 아무것도 안 남긴다(팀 규칙: main은 건드리지 않는다) —
그래서 산출물을 저장소 안이 아니라 %TEMP%에 쓴다. cmd의 %TEMP%와
tempfile.gettempdir()가 같은 경로를 가리키는 것은 확인했다.

health_index_data.json에 실제로 등장한 원인변수(causes)만 골라서 시계열을 붙인다
(전체 컬럼을 다 넣으면 용량이 커진다) — 그래서 오늘 어떤 장비/변수가 위험으로
뜨든 자동으로 맞는 시계열이 따라온다. 하드코딩된 장비/변수 목록이 아니다.

실행: 대상 저장소 루트에서(cwd 기준) python <이 파일의 절대경로>
(health_index_data.json / 00_machine_daily_series.csv가 이미 만들어진 뒤에 실행)

주의: ROOT를 __file__ 기준이 아니라 cwd 기준으로 잡는다 — 이 스크립트는 lsyeon에
있지만, n8n Run Pipeline이 다른 체크아웃(main 등)으로 cd한 뒤 절대경로로 호출하는
용도라 실행 위치와 스크립트 위치가 다르다.
"""
import base64
import io
import json
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 서버 실행이라 GUI 백엔드를 쓰면 안 됨
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

ROOT = Path.cwd()
HI_JSON = ROOT / "26.08.01_Goal5_HealthIndex_Dashboard_김시우" / "health_index_data.json"
DAILY_CSV = ROOT / "analysis_outputs" / "preprocessing" / "00_machine_daily_series.csv"
PAYLOAD = Path(tempfile.gettempdir()) / "n8n_report_payload.json"

# 리포트 등급 경계. JS(Code 노드)도 이 값을 payload["_thresholds"]에서 읽어 쓴다 —
# 두 곳에 각각 상수를 두면 한쪽만 고쳤을 때 조용히 어긋나서, 여기를 단일 출처로 삼는다.
CRITICAL_THRESHOLD = 50
WATCH_THRESHOLD = 80

# 그래프 색 (이메일 리포트의 인라인 색과 맞춤)
C_LINE = "#2c6e8e"
C_CRIT = "#b3362b"
C_MUTED = "#8993a0"


def _korean_font() -> str:
    """설치된 한글 폰트 하나를 고른다. 없으면 라벨이 두부(□)로 나오므로 확인해서 쓴다."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "NanumGothic", "Gulim", "Dotum"):
        if name in installed:
            return name
    return "DejaVu Sans"


def render_chart_png(factor: str, dates: list, values: list, cause: dict) -> str:
    """일별 추세 선그래프를 PNG로 그려 base64 문자열로 돌려준다.

    왜 이미지인가 — 처음엔 인라인 SVG로 그렸는데 Gmail이 이메일 본문의 SVG를 차단해서
    실제 수신 메일에서 그래프가 통째로 안 보였다(실행 16번). data: URI 이미지도 Gmail이
    막고, 외부 호스팅은 서버가 없다. 남는 방법이 PNG를 메일에 첨부(CID)해서
    <img src="cid:...">로 참조하는 것이라 여기서 PNG를 만든다.

    y축 범위는 관리한계까지 넣지 않고 데이터 범위로만 잡는다 — 관리한계는 자연 변동폭보다
    수십 시그마 밖이라 축에 넣으면 실제 등락이 직선으로 뭉개진다. 대신 범위 안에 들어오는
    한계선만 그린다.
    """
    plt.rcParams["font.family"] = _korean_font()
    plt.rcParams["axes.unicode_minus"] = False

    baseline = cause.get("baseline_median")
    lsl, usl = cause.get("control_lsl"), cause.get("control_usl")
    side = cause.get("score_side") or "both"

    fig, ax = plt.subplots(figsize=(6.6, 1.85), dpi=150)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    x = range(len(values))
    ax.plot(x, values, color=C_LINE, linewidth=1.6, zorder=3)
    ax.plot([len(values) - 1], [values[-1]], "o", color=C_CRIT, markersize=4.5, zorder=4)

    # 관리한계까지 축에 포함시킨다 — "지금 값이 한계선까지 얼마나 남았는지"가 이 그래프의
    # 핵심이라, 한계선이 화면 밖으로 나가면 그림이 답을 못 준다. 그 대신 변동폭이 다소
    # 눌리는데, 실제로 봐야 하는 큰 하강은 그대로 보인다.
    ref = [v for v in (baseline, lsl, usl) if v is not None]
    lo = min(list(values) + ref)
    hi = max(list(values) + ref)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.02 or 1
    ymin, ymax = lo - pad, hi + pad

    def hline(v, color, dashed, label, above=False):
        """기준선 + 오른쪽 끝 라벨. 라벨은 기본적으로 선 아래에 둔다 —
        선 위에 두면 마지막 값 표시(빨간 점)와 겹치는 경우가 생긴다."""
        if v is None or not (ymin <= v <= ymax):
            return
        ax.axhline(v, color=color, linewidth=1,
                   linestyle=(0, (5, 4)) if dashed else "-", zorder=2)
        ax.annotate(f"{label} {v}", xy=(1, v), xycoords=("axes fraction", "data"),
                    xytext=(-2, 3 if above else -3), textcoords="offset points",
                    ha="right", va="bottom" if above else "top",
                    fontsize=7.5, color=color)

    hline(usl, C_CRIT if side in ("both", "upper") else C_MUTED, True, "관리상한")
    hline(lsl, C_CRIT if side in ("both", "lower") else C_MUTED, True, "관리하한")
    hline(baseline, C_MUTED, False, "정상값", above=True)

    alert_since = cause.get("alert_since")
    if alert_since:
        idx = next((i for i, d in enumerate(dates) if d >= alert_since), None)
        if idx:
            ax.axvline(idx, color=C_CRIT, linewidth=1, linestyle=(0, (2, 3)),
                       alpha=0.6, zorder=2)
            ax.annotate(f"경보 {alert_since}", xy=(idx, 1), xycoords=("data", "axes fraction"),
                        xytext=(3, -9), textcoords="offset points",
                        fontsize=7.5, color=C_CRIT)

    ax.set_ylim(ymin, ymax)
    ax.set_xlim(-1, len(values))
    ax.set_yticks([])
    ax.set_xticks([0, len(values) - 1])
    ax.set_xticklabels([dates[0], dates[-1]], fontsize=7.5, color=C_MUTED)
    ax.tick_params(axis="x", length=0, pad=4)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(f"{factor} 추세 ({dates[0]} ~ {dates[-1]})",
                 fontsize=8.5, color=C_MUTED, loc="left", pad=6)

    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="#ffffff")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def main() -> None:
    with open(HI_JSON, encoding="utf-8") as f:
        hi = json.load(f)

    cause_cols = set()
    for m in hi["machines"].values():
        for sig in m["defect_signals"].values():
            cause_cols.update(sig.get("causes", {}).keys())

    df = pd.read_csv(DAILY_CSV)
    df = df[df["column"].isin(cause_cols)]

    series: dict[str, dict[str, dict]] = {}
    for (machine, col), g in df.groupby(["Machine_ID", "column"]):
        g = g.sort_values("date")
        series.setdefault(machine, {})[col] = {
            "dates": g["date"].tolist(),
            "values": [round(float(v), 4) for v in g["daily_mean"]],
        }

    hi["_daily_series"] = series
    hi["_thresholds"] = {"critical": CRITICAL_THRESHOLD, "watch": WATCH_THRESHOLD}

    # 리포트에 실제로 그래프가 붙는 자리에만 PNG를 만든다 — 화면 규칙과 같아야 한다:
    #   "위험(HI < CRITICAL) 장비"의 "표시되는 defect(HI < WATCH)"의 "최저 HI 원인변수".
    # 모든 조합을 다 만들면 payload가 불필요하게 커진다.
    charts: dict[str, str] = {}
    for machine, m in hi["machines"].items():
        if m.get("health_index") is None or m["health_index"] >= CRITICAL_THRESHOLD:
            continue
        for sig in m["defect_signals"].values():
            if sig.get("health_index") is None or sig["health_index"] >= WATCH_THRESHOLD:
                continue
            causes = sig.get("causes") or {}
            if not causes:
                continue
            factor = min(causes, key=lambda f: causes[f].get("health_index") or 100)
            key = f"{machine}__{factor}"
            if key in charts:
                continue
            s = series.get(machine, {}).get(factor)
            if not s or len(s["values"]) < 2:
                continue
            charts[key] = render_chart_png(factor, s["dates"], s["values"], causes[factor])

    hi["_charts"] = charts
    PAYLOAD.write_text(json.dumps(hi, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
