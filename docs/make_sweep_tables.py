"""스윕 표 — 디자인 재작업.

바꾼 것:
  세로 괘선 전부 제거(가로 헤어라인만)  ·  헤더 색 막대 제거
  판정을 알약 칩으로  ·  숫자는 Helvetica, 한글은 Apple SD Gothic Neo로 폴백
  통과 구간을 왼쪽 세로 괄호로 표시  ·  행 높이·여백 확대
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

plt.rcParams["font.family"] = ["Helvetica Neue", "Apple SD Gothic Neo"]
plt.rcParams["axes.unicode_minus"] = False

INK      = "#16283C"
INK_SOFT = "#4A5F75"
MUTED    = "#8496A8"
HAIR     = "#E3E9EF"
HAIR_STRONG = "#B9C6D2"
RED      = "#BE3A31"
RED_BG   = "#FBEDEB"
GREEN    = "#1B6E52"
GREEN_BG = "#E7F4EE"
AMBER    = "#A9711A"
AMBER_BG = "#FBF1E0"
GREY_BG  = "#EEF2F6"

RH   = 0.52     # 행 높이
HDRH = 0.44
DPI  = 200


def tw(s, fs):
    """글자 폭 어림(인치) — 칩 크기 잡는 용도."""
    return sum(1.0 if ord(c) > 0x1100 else 0.53 for c in s) * fs / 72


def chip(ax, cx, cy, text, fg, bg, fs=10.5):
    w = tw(text, fs) + 0.30
    h = 0.28
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                                boxstyle="round,pad=0,rounding_size=0.14",
                                fc=bg, ec="none", zorder=3))
    ax.text(cx, cy, text, fontsize=fs, color=fg, ha="center", va="center",
            fontweight="bold", zorder=4)


def bracket(ax, x, y_top, y_bot, label, color):
    """통과 구간을 감싸는 세로 괄호."""
    d = 0.10
    ax.plot([x + d, x, x, x + d], [y_top, y_top, y_bot, y_bot],
            color=color, lw=1.6, solid_capstyle="round", zorder=3)
    ax.text(x - 0.10, (y_top + y_bot) / 2, label, fontsize=9.5, color=color,
            ha="center", va="center", rotation=90, fontweight="bold")


def table(fname, eyebrow, title, sub, cols, rows, note, states,
          window=None, fs=11.5, lead_fs=14):
    """cols: [(제목, 폭, 정렬)]   states: 행별 'pick'|'ok'|'bad'|None
       rows: 마지막 칸은 (텍스트, 칩색상키) 튜플이면 칩으로 그린다."""
    LEFT = 0.42 if window else 0.0
    W = LEFT + sum(c[1] for c in cols)
    TOP = 1.30
    BOT = 0.30 + 0.17 * len(note)
    H = TOP + HDRH + RH * len(rows) + BOT

    fig = plt.figure(figsize=(W + 0.9, H + 0.6), dpi=DPI)
    ax = fig.add_axes([0.45 / (W + 0.9), 0.3 / (H + 0.6), W / (W + 0.9), H / (H + 0.6)])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # ---- 제목 블록
    y = H - 0.12
    ax.text(LEFT, y, " ".join(eyebrow), fontsize=9, color=MUTED,
            fontweight="bold", va="top")
    ax.text(LEFT, y - 0.30, title, fontsize=19, color=INK, fontweight="bold", va="top")
    ax.text(LEFT, y - 0.74, sub, fontsize=10.5, color=INK_SOFT, va="top")

    # ---- 헤더 (색 막대 없이 라벨 + 아래 굵은 헤어라인)
    yh = H - TOP
    x = LEFT
    for name, w, al in cols:
        tx = x + 0.02 if al == "l" else x + w - 0.02 if al == "r" else x + w / 2
        ha = {"l": "left", "r": "right", "c": "center"}[al]
        ax.text(tx, yh - HDRH / 2, name, fontsize=9.8, color=MUTED,
                fontweight="bold", ha=ha, va="center", linespacing=1.35)
        x += w
    ax.plot([LEFT, W], [yh - HDRH, yh - HDRH], color=HAIR_STRONG, lw=1.3)

    # ---- 본문
    y = yh - HDRH
    ys = []
    for i, r in enumerate(rows):
        yb, yc = y - RH, y - RH / 2
        ys.append((y, yb))
        st = states[i]
        if st == "pick":
            ax.add_patch(Rectangle((LEFT, yb), W - LEFT, RH, fc=GREEN_BG, ec="none", zorder=0))
        elif st == "bad":
            ax.add_patch(Rectangle((LEFT, yb), W - LEFT, RH, fc="#FCF4F3", ec="none", zorder=0))
        x = LEFT
        for j, ((name, w, al), cell) in enumerate(zip(cols, r)):
            if isinstance(cell, tuple):
                # 채택 행은 배경이 이미 연한 초록이라 같은 톤 칩이 묻힌다 — 솔리드로 뒤집는다
                fg, bg = (("white", GREEN) if st == "pick" else
                          {"g": (GREEN, GREEN_BG), "r": (RED, RED_BG),
                           "a": (AMBER, AMBER_BG), "n": (INK_SOFT, GREY_BG)}[cell[1]])
                chip(ax, x + w / 2, yc, cell[0], fg, bg)
            else:
                if j == 0:
                    col, fsz, fw = (GREEN if st == "pick" else
                                    RED if st == "bad" else INK), fs + 2.5, "bold"
                else:
                    col, fsz, fw = (INK if st == "pick" else INK_SOFT), fs, \
                                   ("bold" if st == "pick" else "normal")
                tx = x + 0.02 if al == "l" else x + w - 0.02 if al == "r" else x + w / 2
                ha = {"l": "left", "r": "right", "c": "center"}[al]
                ax.text(tx, yc, str(cell), fontsize=fsz, color=col,
                        fontweight=fw, ha=ha, va="center", zorder=2)
            x += w
        if i < len(rows) - 1:
            ax.plot([LEFT, W], [yb, yb], color=HAIR, lw=0.8, zorder=1)
        y = yb
    ax.plot([LEFT, W], [y, y], color=HAIR_STRONG, lw=1.3)

    if window:
        a, b, lbl = window
        bracket(ax, LEFT - 0.14, ys[a][0] - 0.03, ys[b][1] + 0.03, lbl, GREEN)

    # ---- 각주
    ny = y - 0.26
    for line in note:
        ax.text(LEFT, ny, line, fontsize=9.3, color=MUTED, va="top")
        ny -= 0.17

    fig.savefig(fname, dpi=DPI, facecolor="white", bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)
    print("저장:", fname)


# ================================================================ K 스윕
table(
    "docs/발표_표_K스윕.png",
    "SWEEP 01", "K를 훑어 쓸 수 있는 구간을 찾는다",
    "H = 4.5 고정 · 파이프라인을 K마다 다시 실행 · 괄호는 실제 고장 시작일 대비 며칠 뒤",
    [("K", 0.95, "l"), ("DP01 정상\n14일 이상 경보", 1.65, "c"),
     ("DP04 CLN_Flow\n실제 02-17", 1.70, "c"), ("DP02\nLaser_Power", 1.55, "c"),
     ("DP03\nHead_Temp", 1.50, "c"), ("판정", 2.05, "c")],
    [["0.50", "9", "02-12  −5", "01-25  −12", "02-08  −3", ("고장 전 오탐", "r")],
     ["0.60", "0", "02-12  −5", "01-30  −7", "02-13  +2", ("고장 전 오탐", "r")],
     ["0.65", "0", "02-19  +2", "02-02  −4", "02-15  +4", ("하한", "g")],
     ["0.70", "0", "02-19  +2", "02-02  −4", "02-17  +6", ("채택", "g")],
     ["0.80", "0", "02-19  +2", "02-05  −1", "02-22  +11", ("상한", "g")],
     ["0.90", "0", "02-19  +2", "02-24  +18", "03-11  +28", ("탐지 지연", "r")]],
    ["쓸 수 있는 구간 [0.65, 0.80] — 하한은 '고장 전 오탐'이, 상한은 '탐지 지연'이 정한다.",
     "DP02·DP03는 고장 전 구간이 이미 기울어져 있어 음수가 오탐이 아니라 조기 탐지다.",
     "'고장 전이면 오탐'을 말할 수 있는 건 그 구간이 평평한 DP04 CLN_Flow뿐이라 하한을 그것으로 정했다."],
    states=["bad", "bad", "ok", "pick", "ok", "bad"],
    window=(2, 4, "쓸 수 있는 구간"))

# ================================================================ H 스윕
table(
    "docs/발표_표_H스윕.png",
    "SWEEP 02", "H는 어디서 나왔나",
    "K = 0.7 고정 · H는 K보다 훨씬 둔하다 — 정상 장비 오탐은 4.0에서 이미 0이고, 그 위는 탐지 속도만 깎인다",
    [("H", 0.85, "l"), ("DP01 정상\n14일 이상", 1.35, "c"), ("DP01\n최장", 1.05, "c"),
     ("DP04\nCLN_Flow", 1.40, "c"), ("DP02\nLaser_Power", 1.45, "c"),
     ("DP03\nHead_Temp", 1.40, "c"), ("경보행", 1.10, "c"), ("판정", 2.30, "c")],
    [["3.5", "0", "12.0일", "02-12  −5", "02-02  −4", "02-13  +2", "71,104", ("탈락 · 고장 전 오탐", "r")],
     ["4.0", "0", "10.5일", "02-19  +2", "02-02  −4", "02-15  +4", "58,695", ("하한", "g")],
     ["4.2", "0", "10.5일", "02-19  +2", "02-02  −4", "02-16  +5", "55,159", ("통과", "n")],
     ["4.3", "0", "10.5일", "02-19  +2", "02-02  −4", "02-16  +5", "53,668", ("통과", "n")],
     ["4.5", "0", "10.5일", "02-19  +2", "02-02  −4", "02-17  +6", "51,037", ("채택", "g")],
     ["4.6", "0", "10.5일", "02-19  +2", "02-04  −2", "02-17  +6", "49,906", ("통과 · 탐지 2일 밀림", "a")],
     ["5.0", "0", "10.5일", "02-19  +2", "02-05  −1", "02-18  +7", "46,284", ("통과 · 탐지 3일 밀림", "a")],
     ["6.0", "0", "10.5일", "02-19  +2", "02-07  +1", "02-19  +8", "40,511", ("통과 · 탐지 5일 밀림", "a")]],
    ["통과 구간 [4.0, 4.5] — 하한 4.0은 단단하다(그 아래는 CLN_Flow가 고장 전에 운다). 상한은 탐지가 밀리기 시작하는 4.6 직전.",
     "4.5는 DP02 Laser_Power 탐지를 안 늦추는 마지막 값이다 — 4.6부터 02-02가 02-04로 밀린다.",
     "K만큼 강한 근거가 아니다. 4.0~4.5는 이 데이터로 우열을 못 가린다 — 4.0이 Head_Temp를 2일 빨리 잡고, 4.5가 경보를 13% 적게 낸다."],
    states=["bad", "ok", "ok", "ok", "pick", "ok", "ok", "ok"],
    window=(1, 4, "쓸 수 있는 구간"), fs=11)


# ================================================================ 2차원 격자
KS = ["0.50", "0.60", "0.65", "0.70", "0.75", "0.80", "0.90"]
HS = ["3.5", "4.0", "4.3", "4.5", "5.0", "6.0"]
G = [["x", "x", "x", "x", "x", "O"],
     ["x", "x", "f", "f", "O", "O"],
     ["x", "f", "O", "O", "O", "O"],
     ["f", "O", "O", "O", "O", "O"],
     ["f", "O", "O", "O", "O", "d"],
     ["O", "O", "d", "d", "d", "d"],
     ["d", "d", "d", "d", "d", "d"]]
FILL = {"O": "#DCEFE6", "x": "#F8DFDB", "f": "#FAEBD5", "d": "#E7ECF1"}
FG = {"O": GREEN, "x": RED, "f": AMBER, "d": "#93A3B3"}
LBL = {"O": "통과", "x": "정상장비 오탐", "f": "고장 전 오탐", "d": "탐지 지연"}

CW, CH, GAP, LW = 1.42, 0.72, 0.055, 1.05
W = LW + CW * len(HS)
TOP, BOT = 1.30, 0.95
Hh = TOP + 0.40 + CH * len(KS) + BOT

fig = plt.figure(figsize=(W + 0.9, Hh + 0.6), dpi=DPI)
ax = fig.add_axes([0.45 / (W + 0.9), 0.3 / (Hh + 0.6), W / (W + 0.9), Hh / (Hh + 0.6)])
ax.set_xlim(0, W); ax.set_ylim(0, Hh); ax.axis("off")

y = Hh - 0.12
ax.text(0, y, "  ".join("SWEEP 03"), fontsize=9, color=MUTED, fontweight="bold", va="top")
ax.text(0, y - 0.30, "K × H 2차원 격자", fontsize=19, color=INK, fontweight="bold", va="top")
ax.text(0, y - 0.74,
        "축을 하나씩만 흔들면 서로를 근거로 삼은 셈이라 42칸을 전부 다시 실행했다 — 18칸 통과 "
        "(탐지 지연 상한 10일)",
        fontsize=10.5, color=INK_SOFT, va="top")

y0 = Hh - TOP
for j, h in enumerate(HS):
    ax.text(LW + CW * j + CW / 2, y0 - 0.20, f"H = {h}", fontsize=10.5,
            color=MUTED, fontweight="bold", ha="center", va="center")
y = y0 - 0.40
for i, k in enumerate(KS):
    yb = y - CH
    dead = all(v != "O" for v in G[i])
    ax.text(LW - 0.16, yb + CH / 2, f"K = {k}", fontsize=11,
            color=RED if dead else INK, fontweight="bold", ha="right", va="center")
    for j, v in enumerate(G[i]):
        x = LW + CW * j
        pick = (k == "0.70" and HS[j] == "4.5")
        ax.add_patch(FancyBboxPatch((x + GAP, yb + GAP), CW - 2 * GAP, CH - 2 * GAP,
                                    boxstyle="round,pad=0,rounding_size=0.09",
                                    fc=FILL[v], ec="none"))
        if pick:
            ax.add_patch(FancyBboxPatch((x + GAP, yb + GAP), CW - 2 * GAP, CH - 2 * GAP,
                                        boxstyle="round,pad=0,rounding_size=0.09",
                                        fc="none", ec=GREEN, lw=2.4))
        ax.text(x + CW / 2, yb + CH / 2, "채택" if pick else LBL[v],
                fontsize=11 if pick else (10.5 if v == "O" else 9.3),
                fontweight="bold" if v == "O" else "normal",
                color=FG[v], ha="center", va="center")
    y = yb

ny = y - 0.30
for line in [
    "통과 영역이 대각선 띠다 — K를 올리면 통과하는 H가 내려간다. 둘 다 민감도를 깎는 손잡이라 서로 상쇄된다.",
    "K = 0.70은 여섯 H 중 다섯에서 통과해 가장 넓다.  K = 0.50은 H = 6.0 한 칸뿐이고, K = 0.90은 어떤 H로도 통과하지 못한다.",
    "(0.70, 4.5)는 상하좌우 이웃이 모두 통과라 경계에 걸친 값이 아니다.  탐지 지연 상한을 7일·14일로 바꿔도 이 칸은 통과다.",
]:
    ax.text(0, ny, line, fontsize=9.3, color=MUTED, va="top")
    ny -= 0.19

fig.savefig("docs/발표_표_KH격자.png", dpi=DPI, facecolor="white",
            bbox_inches="tight", pad_inches=0.22)
plt.close(fig)
print("저장: docs/발표_표_KH격자.png")
