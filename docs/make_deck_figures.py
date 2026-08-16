"""발표 덱에 넣을 그림 4장. 스윕 표 3장은 make_sweep_tables.py가 따로 만든다.

숫자는 전부 실측이고 출처를 각 함수 주석에 적었다 — 값이 바뀌면 여기 주석부터 보고
재현 명령을 다시 돌린 뒤 그림을 다시 굽는다.

    python3 docs/make_deck_figures.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.family"] = ["Helvetica Neue", "Apple SD Gothic Neo"]
plt.rcParams["axes.unicode_minus"] = False

INK, INK_SOFT, MUTED = "#1F3B57", "#41586E", "#8494A5"
RED, GREEN, AMBER = "#C2372C", "#15654A", "#B06A16"
HAIR = "#DCE3EA"
BOX_BG, GREEN_BG, RED_BG, AMBER_BG = "#F2F6F9", "#E7F4EE", "#FBECEA", "#FBF1E0"
DPI = 200


def canvas(w, h):
    fig = plt.figure(figsize=(w, h), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, fc=BOX_BG, ec="none", lw=0, r=0.10):
    ax.add_patch(FancyBboxPatch((x, y), w, h, ec=ec, fc=fc, lw=lw,
                                boxstyle=f"round,pad=0,rounding_size={r}"))


def arrow(ax, x, y0, y1, color=MUTED):
    ax.add_patch(FancyArrowPatch((x, y0), (x, y1), arrowstyle="-|>",
                                 mutation_scale=13, lw=1.3, color=color,
                                 shrinkA=0, shrinkB=0))


def save(fig, name):
    fig.savefig(f"docs/{name}", dpi=DPI, facecolor="white",
                bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    print("저장: docs/" + name)


# ====================================================== ① 파이프라인 흐름
# 216 그룹 / 5.22샷: raw를 (Machine,Product,Recipe)로 묶어 센 값.
# 51,037행 / 5,927사건 / 44건: trend_analysis.py 실행 로그와 01_level_trend의
# early_warning_active 합계.
def fig_flow():
    W, H = 8.6, 6.9
    fig, ax = canvas(W, H)
    y = H - 0.30
    steps = [
        ("INPUT", "샷 데이터  100,000행 × 4장비 × 89일", BOX_BG, INK, 0.52),
        ("① 그룹 분할", "(장비 × 제품 × 레시피) = 216개 시계열 · 하루 5.22샷",
         BOX_BG, INK, 0.62),
        ("② 기준값", "유형마다 출처가 다르다 — A 안정구간 · B OK median\n"
                    "C 층별 median + 불량으로 학습한 경계 · E 이론 상수",
         BOX_BG, INK, 0.80),
        ("③ 판정", None, GREEN_BG, GREEN, 1.16),
        ("④ 사건화", "연속된 경보를 episode 하나로 묶는다", BOX_BG, INK, 0.62),
        ("OUTPUT", "경보행 51,037   →   사건 5,927   →   화면 44건",
         BOX_BG, INK, 0.52),
    ]
    for i, (title, sub, fc, tc, h) in enumerate(steps):
        box(ax, 0, y - h, W, h, fc=fc)
        ax.text(0.26, y - 0.26, title, fontsize=12, color=tc, fontweight="bold",
                va="top")
        if sub:
            ax.text(2.15, y - 0.27, sub, fontsize=10.5, color=INK_SOFT, va="top",
                    linespacing=1.5)
        else:
            # ③ 판정 — 두 갈래를 나란히
            for j, (nm, ds) in enumerate([
                    ("CUSUM", "평균 수준이 밀렸나"),
                    ("경계 진입", "위험구간에 샷이 들어갔나")]):
                bx = 2.15 + j * 3.30
                box(ax, bx, y - h + 0.16, 2.75, 0.72, fc="white", ec=GREEN, lw=1.1)
                ax.text(bx + 1.375, y - h + 0.66, nm, fontsize=11.5, color=GREEN,
                        fontweight="bold", ha="center", va="center")
                ax.text(bx + 1.375, y - h + 0.38, ds, fontsize=9.3, color=MUTED,
                        ha="center", va="center")
            ax.text(5.175, y - h + 0.52, "OR", fontsize=10.5, color=GREEN,
                    fontweight="bold", ha="center", va="center")
        y -= h
        if i < len(steps) - 1:
            arrow(ax, W / 2, y - 0.05, y - 0.30)
            y -= 0.35
    ax.text(0, 0.02, "하나라도 걸리면 경보다 — 순서가 아니라 병렬이다.  "
                     "계산은 100,000행 전부에 하고 저장만 경보 행으로 거른다.",
            fontsize=9.2, color=MUTED, va="bottom")
    save(fig, "발표_그림_흐름도.png")


# ====================================================== ② 경계값 학습
# 24.7배: 발표_프로젝트_설명.md §3-6. 7/54 그룹 제외: CLAUDE.md 규칙 6.
def fig_stump():
    W, H = 8.6, 4.5
    fig, ax = canvas(W, H)
    y = H - 0.28
    rows = [
        ("INPUT", "샷 값  +  실제 불량 라벨", BOX_BG, INK),
        ("결정트리 스텀프",
         "max_depth = 1 · class_weight = \"balanced\"\n"
         "Product × Recipe 그룹마다 · defect마다 따로 학습", BOX_BG, INK),
        ("방향 필터",
         "학습된 위험 방향이 관계DB와 반대인 그룹은 버린다\n"
         "CLN_Flow↔Particle 54그룹 중 7개 제외 (세정 유량이 높아서\n"
         "파티클이 는다는 건 물리적으로 말이 안 된다)", AMBER_BG, AMBER),
        ("OUTPUT  경계값",
         "CLN_Flow 9.694 아래 → Remain_Coat 불량률 24.7배", GREEN_BG, GREEN),
    ]
    for i, (t, s, fc, tc) in enumerate(rows):
        h = 0.52 + 0.20 * s.count("\n")
        box(ax, 0, y - h, W, h, fc=fc)
        ax.text(0.26, y - 0.25, t, fontsize=11.5, color=tc, fontweight="bold",
                va="top")
        ax.text(2.55, y - 0.26, s, fontsize=10, color=INK_SOFT, va="top",
                linespacing=1.5)
        y -= h
        if i < len(rows) - 1:
            arrow(ax, W / 2, y - 0.04, y - 0.26)
            y -= 0.30
    ax.text(0, 0.02, "결정트리는 순수 노이즈에도 경계를 만들어낸다 — "
                     "'갈라지는가'가 아니라 '도메인과 방향이 맞는가'로 거른다.",
            fontsize=9.2, color=MUTED, va="bottom")
    save(fig, "발표_그림_경계값학습.png")


# ====================================================== ③ 5샷 연속 판정
# _sustained_first(cond, 5) 동작을 그대로 그린 것. 다섯째 샷에 1행만 뜬다.
# 21,426/22,948: trend_analysis.py PERSIST_WINDOW 주석.
def fig_persist():
    N = 14
    CW, ROW = 0.40, 0.86
    W, H = 3.05 + CW * N + 2.35, 0.95 + ROW * 4 + 0.72
    fig, ax = canvas(W, H)
    cases = [
        ("① 4연속에서 끊김", [3, 4, 5, 6], None, "경보 없음", MUTED),
        ("② 5연속", [3, 4, 5, 6, 7], 7, "다섯째 샷에 1행", GREEN),
        ("③ 오래 지속", list(range(3, 11)), 7, "여전히 1행 — 매 샷 아님", GREEN),
        ("④ 1샷씩 오락가락", [2, 4, 7, 9], None, "경보 없음", MUTED),
    ]
    ax.text(0, H - 0.24, "시간 →  샷 하나가 네모 하나", fontsize=9.5, color=MUTED,
            va="top")
    lx = 3.05
    for fc, lab in ((RED, "경계 밖"), ("#EDF1F5", "경계 안")):
        ax.add_patch(FancyBboxPatch((lx, H - 0.44), 0.22, 0.22,
                                    boxstyle="round,pad=0,rounding_size=0.04",
                                    fc=fc, ec="none"))
        ax.text(lx + 0.32, H - 0.33, lab, fontsize=9.5, color=MUTED, va="center")
        lx += 1.25
    ax.add_patch(FancyBboxPatch((lx, H - 0.44), 0.22, 0.22,
                                boxstyle="round,pad=0,rounding_size=0.04",
                                fc="none", ec="none"))
    ax.text(lx, H - 0.33, "▲ 경보가 저장되는 행", fontsize=9.5, color=GREEN,
            va="center")
    y = H - 0.95
    for label, marks, alert, verdict, vc in cases:
        yb = y - ROW
        ax.text(0, yb + ROW / 2 + 0.10, label, fontsize=11, color=INK,
                fontweight="bold", va="center")
        for i in range(N):
            cx = 3.05 + CW * i + CW / 2
            on = i in marks
            ax.add_patch(FancyBboxPatch(
                (cx - 0.15, yb + 0.34), 0.30, 0.30,
                boxstyle="round,pad=0,rounding_size=0.05",
                fc=(RED if on else "#EDF1F5"), ec="none"))
            if alert is not None and i == alert:
                ax.text(cx, yb + 0.14, "▲", fontsize=11, color=GREEN,
                        ha="center", va="center")
        bx = 3.05 + CW * N + 0.24
        box(ax, bx, yb + 0.30, 2.05, 0.40,
            fc=(GREEN_BG if alert is not None else "#F2F4F7"))
        ax.text(bx + 1.02, yb + 0.50, verdict, fontsize=10, color=vc,
                fontweight="bold", ha="center", va="center")
        ax.plot([0, W], [yb, yb], color=HAIR, lw=0.8)
        y = yb
    ax.text(0, y - 0.16,
            "④가 이 규칙의 이유다 — 1샷만 넘어도 진입으로 잡던 때 "
            "Surface_Roughness는 22,948건 중 21,426건(93%)이 경계 근처 노이즈였다.\n"
            "비용은 탐지가 4샷 늦는 것이다. 그룹당 하루 5.22샷이니 약 0.8일.",
            fontsize=9.2, color=MUTED, va="top", linespacing=1.6)
    save(fig, "발표_그림_5샷연속.png")


# ====================================================== ④ 두 판정의 분담
# 127 / 195 / 115, 65개·28.1일: analysis_outputs/trend_analysis_results.csv를
# (장비,컬럼,제품,레시피)로 묶어 첫 진입일과 첫 CUSUM일을 비교한 값.
def fig_overlap():
    W, H = 8.6, 3.5
    fig, ax = canvas(W, H)
    total = 437
    segs = [("CUSUM만", 195, "#DCE7F0", INK),
            ("둘 다", 115, "#CFE6DA", GREEN),
            ("경계값만", 127, "#F6E2C8", AMBER)]
    ax.text(0, H - 0.22, "(장비, 컬럼, 제품, 레시피)  437개 그룹",
            fontsize=11.5, color=INK, fontweight="bold", va="top")
    yb, bh, x = H - 1.62, 0.92, 0.0
    for name, n, fc, tc in segs:
        w = W * n / total
        box(ax, x + 0.03, yb, w - 0.06, bh, fc=fc, r=0.07)
        ax.text(x + w / 2, yb + bh * 0.62, name, fontsize=11, color=tc,
                fontweight="bold", ha="center", va="center")
        ax.text(x + w / 2, yb + bh * 0.26, f"{n}", fontsize=15, color=tc,
                fontweight="bold", ha="center", va="center")
        x += w
    ax.text(0, yb - 0.28,
            "가운데 115개 중 경계값이 먼저인 게 65개 — 평균 28.1일 빠르다.",
            fontsize=10.5, color=INK_SOFT, va="top")
    ax.text(0, yb - 0.72,
            "CUSUM은 '평소와 달라졌나'를 시그마 단위로 볼 뿐 불량과 연결이 없고, "
            "경계값은 불량 라벨로 학습한 선이다.\n"
            "어느 한쪽만 걸었으면 127개 또는 195개를 통째로 놓친다 — 서로 대체가 아니다.",
            fontsize=9.2, color=MUTED, va="top", linespacing=1.6)
    save(fig, "발표_그림_판정분담.png")


# ====================================================== ⑤ 경보 행 → 경보 건수
# 51,037 / 41,714 / 5,927 / 128 / 44 / 9 는 전부 실측이다:
#   행    = trend_analysis_results.csv 행 수
#   샷    = (장비,제품,레시피,컬럼,DateTime) 중복 제거
#   사건  = (장비,제품,레시피,컬럼,episode_id) 고유 수
#   조합  = (장비,컬럼) 고유 수
#   화면  = 01_level_trend의 early_warning_active 합계, full은 alert_level
def fig_funnel():
    steps = [
        ("100,000", "샷 전체", "34개 컬럼 전부에 판정을 돌린다", None, MUTED, "#EDF1F5"),
        ("51,037", "저장된 경보 행", "경보가 켜진 행만 파일에 쓴다",
         "경보 켜진 행만 남긴다", INK, BOX_BG),
        ("41,714", "경보 샷", "한 컬럼이 두 defect의 원인이면 같은 샷이 두 행이 된다",
         "짝(인자, defect) 중복을 접는다", INK, BOX_BG),
        ("5,927", "독립 사건 (episode)",
         "(장비, 제품, 레시피, 컬럼) 안에서 끊기지 않은 구간 하나 = 사건 하나",
         "연속된 경보를 사건 하나로 묶는다", INK, BOX_BG),
        ("128", "(장비, 컬럼) 조합",
         "엔지니어가 보는 건 레시피별 조각이 아니라 \"이 장비의 이 변수\"다",
         "제품 · 레시피 축을 접는다", INK, BOX_BG),
        ("44", "화면에 뜨는 경보", "마지막 경보가 하루 안쪽이면 지금도 켜져 있는 것으로 본다",
         "지금도 진행 중인 것만 남긴다", GREEN, GREEN_BG),
        ("9", "그중 full", "세기 ≥ 1.0 — 점수를 최대폭까지 깎은 경보만 강조 표시",
         "세기로 한 번 더 가른다", GREEN, GREEN_BG),
    ]
    ROW, GAP = 0.86, 0.40
    W = 11.4
    H = 0.30 + len(steps) * ROW + (len(steps) - 1) * GAP + 1.30
    fig, ax = canvas(W, H)
    y = H - 0.30
    for i, (num, label, why, action, tc, bg) in enumerate(steps):
        yb = y - ROW
        box(ax, 0, yb, W, ROW, fc=bg)
        ax.text(2.05, yb + ROW * 0.60, num, fontsize=19, color=tc,
                fontweight="bold", ha="right", va="center")
        ax.text(2.30, yb + ROW * 0.62, label, fontsize=11.5, color=tc,
                fontweight="bold", va="center")
        ax.text(2.30, yb + ROW * 0.26, why, fontsize=9.6, color=MUTED, va="center")
        y = yb
        if i < len(steps) - 1:
            _, nxt_action = steps[i + 1][0], steps[i + 1][3]
            arrow(ax, 1.15, y - 0.06, y - GAP + 0.06)
            ax.text(1.38, y - GAP / 2, nxt_action, fontsize=10, color=INK_SOFT,
                    va="center")
            y -= GAP
    ax.text(0, y - 0.22,
            "사건 5,927개인데 조합이 128개인 이유 — 제품·레시피가 날마다 바뀌므로 "
            "한 그룹의 경보는 자연히 끊긴다.\n"
            "그래서 사건 단위로 지속일을 재면 DP03 Surface_Roughness가 224조각으로 "
            "쪼개져 \"0.1일째\"로 표시됐다. 조합 단위로 이어붙여 고쳤다.",
            fontsize=9.4, color=MUTED, va="top", linespacing=1.6)
    save(fig, "발표_그림_경보건수.png")


if __name__ == "__main__":
    fig_flow()
    fig_stump()
    fig_persist()
    fig_overlap()
    fig_funnel()
