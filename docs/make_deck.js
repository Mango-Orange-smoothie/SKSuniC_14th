// 추세분석 판정 덱 6장. 17조 덱 문법(머리 띠 / 2단 제목 / ❖ 리드 / → 결론)을 따른다.
const P = require("pptxgenjs");
const D = "/Users/gimsiu/Downloads/suni c 14조/docs/";

const INK = "1F3B57", SOFT = "41586E", MUTED = "8494A5";
const RED = "C2372C", GREEN = "15654A", AMBER = "B06A16";
const HAIR = "DCE3EA", BG = "F2F6F9", GBG = "E7F4EE", RBG = "FBECEA", ABG = "FBF1E0";
const F = "Arial";
const W = 13.333, H = 7.5;
const M = 0.62;                       // 좌우 여백
const CW = W - M * 2;                 // 본문 폭
const CONCL = 6.62;                   // 결론 줄 y

const pptx = new P();
pptx.defineLayout({ name: "W", width: W, height: H });
pptx.layout = "W";

const STAGES = ["배경", "데이터", "판정", "검증", "결론"];

function slide(stage, eyebrow, title, lead) {
  const s = pptx.addSlide();
  s.background = { color: "FFFFFF" };
  // 머리 띠
  let x = M;
  STAGES.forEach((t, i) => {
    const on = t === stage;
    s.addText(t, {
      x, y: 0.24, w: 0.58, h: 0.24, fontFace: F, fontSize: 10.5,
      color: on ? INK : MUTED, bold: on, align: "left",
    });
    if (i < STAGES.length - 1)
      s.addText("·", { x: x + 0.58, y: 0.24, w: 0.18, h: 0.24, fontFace: F, fontSize: 10.5, color: HAIR, align: "center" });
    x += 0.78;
  });
  s.addText(eyebrow, {
    x: W - M - 3.2, y: 0.24, w: 3.2, h: 0.24, fontFace: F, fontSize: 10.5,
    color: MUTED, bold: true, align: "right", charSpacing: 1.6,
  });
  s.addShape(pptx.ShapeType.line, {
    x: M, y: 0.58, w: CW, h: 0, line: { color: HAIR, width: 0.75 },
  });
  s.addText(title, {
    x: M, y: 0.72, w: CW, h: 0.5, fontFace: F, fontSize: 26, color: INK, bold: true,
  });
  if (lead)
    s.addText(lead, {
      x: M, y: 1.28, w: CW, h: 0.34, fontFace: F, fontSize: 13, color: SOFT,
    });
  return s;
}

function concl(s, text) {
  s.addShape(pptx.ShapeType.line, {
    x: M, y: CONCL, w: CW, h: 0, line: { color: HAIR, width: 0.75 },
  });
  s.addText(text, {
    x: M, y: CONCL + 0.12, w: CW, h: 0.34, fontFace: F, fontSize: 13,
    color: GREEN, bold: true,
  });
}

function note(s, lines, y) {
  s.addText(lines.map((t) => ({ text: t, options: { breakLine: true } })), {
    x: M, y, w: CW, h: 0.24 * lines.length, fontFace: F, fontSize: 9.5,
    color: MUTED, lineSpacingMultiple: 1.35,
  });
}

// 값 카드 (숫자 + 라벨)
function stat(s, x, y, w, h, big, label, color, bg) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, fill: { color: bg || BG }, line: { type: "none" }, rectRadius: 0.06,
  });
  s.addText(big, {
    x, y: y + 0.14, w, h: 0.44, fontFace: F, fontSize: 22, color, bold: true, align: "center",
  });
  s.addText(label, {
    x, y: y + h - 0.42, w, h: 0.30, fontFace: F, fontSize: 10.5, color: MUTED, align: "center",
  });
}

const T = (v, o = {}) => ({ text: v, options: { fontFace: F, fontSize: 11, color: INK, ...o } });

/* ═══════════════════════════════ 1. 흐름 */
{
  const s = slide("판정", "PIPELINE 01", "추세분석 — 스펙 안에서 움직이는 것을 잡는다",
    "❖ 스펙을 벗어나면 이미 알람이 간다. 우리가 푸는 건 스펙 안에서 안 보이는 것이다.");

  s.addImage({ path: D + "발표_그림_흐름도.png", x: M, y: 1.76, w: 5.83, h: 4.72 });

  const bx = 6.78, bw = W - M - bx;
  s.addText("기존 방법으로는 DP02 · DP03가 정상으로 보인다", {
    x: bx, y: 1.80, w: bw, h: 0.30, fontFace: F, fontSize: 12.5, color: INK, bold: true,
  });
  const rows = [
    ["스펙 위반 판정", "89일 · 4장비", "지속 위반 0건"],
    ["Cpk", "열화 2.62", "정상 2.90"],
    ["육안", "이동 폭", "샷 표준편차의 0.57배"],
  ];
  let ry = 2.24;
  rows.forEach(([a, b, c]) => {
    s.addShape(pptx.ShapeType.roundRect, {
      x: bx, y: ry, w: bw, h: 0.72, fill: { color: RBG }, line: { type: "none" }, rectRadius: 0.06,
    });
    s.addText(a, { x: bx + 0.16, y: ry + 0.08, w: bw - 0.32, h: 0.26, fontFace: F, fontSize: 11, color: RED, bold: true });
    s.addText(`${b}    ${c}`, { x: bx + 0.16, y: ry + 0.36, w: bw - 0.32, h: 0.26, fontFace: F, fontSize: 10.5, color: SOFT });
    ry += 0.84;
  });
  s.addText("확인된 열화 9건 중 7건이 1σ 미만으로 움직인다.\n스펙폭 대비로는 1.7 ~ 4.2%다.", {
    x: bx, y: ry + 0.10, w: bw, h: 0.7, fontFace: F, fontSize: 11, color: SOFT, lineSpacingMultiple: 1.4,
  });

  concl(s, "→ 판정은 두 갈래이고 하나라도 걸리면 경보다. 순서가 아니라 병렬이다.");
  note(s, ["· 스펙 위반 · 설비 상한 경로가 코드에는 더 있으나 본 발표 범위 밖이다."], CONCL + 0.52);
  s.addNotes("스펙 검사로 0건이라는 게 이 프로젝트의 출발점이다. 기존 방법으로 안 보이는 걸 잡는 게 목표이므로, 스펙 위반 경로는 발표에서 다루지 않는다.");
}

/* ═══════════════════════════════ 2. CUSUM */
{
  const s = slide("판정", "METHOD 01", "CUSUM — 작은 편차를 누적해서 본다",
    "❖ Laser_Power는 스펙폭의 4.2%만 움직였다. 어떤 고정 선을 그어도 안 걸린다.");

  s.addShape(pptx.ShapeType.roundRect, {
    x: M, y: 1.82, w: 6.1, h: 1.86, fill: { color: BG }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText("판정식", { x: M + 0.24, y: 1.96, w: 2, h: 0.26, fontFace: F, fontSize: 11, color: MUTED, bold: true });
  s.addText([
    { text: "C⁺ = max(0,  C⁺ + z − K)", options: { breakLine: true } },
    { text: "C⁻ = min(0,  C⁻ + z + K)", options: { breakLine: true } },
    { text: "경보  ⟺  C⁺ > H   또는   C⁻ < −H", options: {} },
  ], {
    x: M + 0.24, y: 2.28, w: 5.6, h: 1.00, fontFace: "Courier New", fontSize: 14,
    color: INK, lineSpacingMultiple: 1.5,
  });
  s.addText("K = 0.7σ      H = 4.5σ", {
    x: M + 0.24, y: 3.34, w: 5.6, h: 0.28, fontFace: F, fontSize: 12, color: GREEN, bold: true,
  });

  s.addShape(pptx.ShapeType.roundRect, {
    x: 7.05, y: 1.82, w: W - M - 7.05, h: 1.86, fill: { color: GBG }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText("DP04  CLN_Flow", { x: 7.29, y: 1.96, w: 3, h: 0.26, fontFace: F, fontSize: 11, color: GREEN, bold: true });
  [["실제 하강 시작", "02-17", MUTED],
   ["CUSUM 경보", "02-19   (+2일)", GREEN],
   ["관리하한 3σ 돌파", "03-01", MUTED]].forEach(([a, b, c], i) => {
    s.addText(a, { x: 7.29, y: 2.34 + i * 0.36, w: 2.3, h: 0.28, fontFace: F, fontSize: 11.5, color: SOFT });
    s.addText(b, { x: 9.6, y: 2.34 + i * 0.36, w: 2.9, h: 0.28, fontFace: F, fontSize: 11.5, color: c, bold: c === GREEN });
  });
  s.addText("→  관리도보다 10일 빠르다", {
    x: 7.29, y: 3.36, w: 4.6, h: 0.28, fontFace: F, fontSize: 12, color: GREEN, bold: true,
  });

  s.addShape(pptx.ShapeType.roundRect, {
    x: M, y: 3.98, w: CW, h: 1.14, fill: { color: "FFFFFF" }, line: { color: GREEN, width: 1.1 }, rectRadius: 0.08,
  });
  s.addText("K는 식 안에 있고, H는 식 밖에 있다", {
    x: M + 0.3, y: 4.12, w: CW - 0.6, h: 0.32, fontFace: F, fontSize: 15, color: GREEN, bold: true,
  });
  s.addText("K가 매 샷 얼마를 버릴지 정해 누적의 모양을 만들고, H는 다 쌓인 뒤 수평선 하나를 그을 뿐이다.", {
    x: M + 0.3, y: 4.52, w: CW - 0.6, h: 0.32, fontFace: F, fontSize: 12, color: SOFT,
  });

  s.addText("K보다 작은 편차는 계속 버려 0으로 리셋된다 — 한 번 튄 값에는 반응하지 않는다.\n그 작은 편차가 56일간 한 방향으로 쌓이면 CUSUM은 반드시 터진다.", {
    x: M, y: 5.36, w: CW, h: 0.7, fontFace: F, fontSize: 12, color: SOFT, lineSpacingMultiple: 1.4,
  });

  concl(s, "→ 관리도는 '지금 이 샷이 선을 넘었나', CUSUM은 '지금까지 한 방향으로 얼마나 쌓였나'를 본다.");
  s.addNotes("K가 재귀식 안에 있다는 것이 핵심이다. 지속 편차가 K보다 크면 어떤 H로도 막을 수 없고, 작으면 어떤 H로도 안 터진다. 그래서 K가 구속 조건이고 H는 눈금이다.");
}

/* ═══════════════════════════════ 3-A. 왜 채점인가 + K */
{
  const s = slide("검증", "METHOD 02", "K = 0.7 — 정답 있는 장비로 채점해서 골랐다",
    "❖ 교과서는 목표 ARL로 h를 푼다. 우리는 그럴 수 없었다.");

  s.addShape(pptx.ShapeType.roundRect, {
    x: M, y: 1.80, w: 6.1, h: 1.34, fill: { color: RBG }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText("교과서 방법이 안 되는 이유", { x: M + 0.24, y: 1.92, w: 5.6, h: 0.26, fontFace: F, fontSize: 11, color: RED, bold: true });
  s.addText("ARL은 관리도 한 개의 수인데 장비당 스트림이 1,836개다.\nK0.5 / H4.0의 ARL₀ 169샷을 그대로 쓰면 정상 장비 1대 · 89일에\n기대 오경보가 5,033건이다.", {
    x: M + 0.24, y: 2.24, w: 5.6, h: 0.82, fontFace: F, fontSize: 11, color: SOFT, lineSpacingMultiple: 1.4,
  });

  s.addShape(pptx.ShapeType.roundRect, {
    x: 7.05, y: 1.80, w: W - M - 7.05, h: 1.34, fill: { color: GBG }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText("대신 쓴 것 — 정답지", { x: 7.29, y: 1.92, w: 5, h: 0.26, fontFace: F, fontSize: 11, color: GREEN, bold: true });
  s.addText("멘토가 주입 시나리오를 확정해줬다. DP01만 시나리오가 없다.\n그래서 DP01에 뜨는 지속경보는 전부 오탐이고,\n이걸 채점표로 쓸 수 있다.", {
    x: 7.29, y: 2.24, w: 5.4, h: 0.82, fontFace: F, fontSize: 11, color: SOFT, lineSpacingMultiple: 1.4,
  });

  s.addImage({ path: D + "발표_표_K스윕.png", x: M, y: 3.30, w: 5.14, h: 3.06 });

  const bx = 6.05, bw = W - M - bx;
  s.addText("경계는 감시 규모에 딸린 값이다", {
    x: bx, y: 3.34, w: bw, h: 0.28, fontFace: F, fontSize: 12, color: INK, bold: true,
  });
  s.addText("DP01 오탐이 0이 되는 K", {
    x: bx, y: 3.64, w: bw, h: 0.24, fontFace: F, fontSize: 10, color: MUTED,
  });
  [["제품 1종", "306", "0.40"], ["제품 2종", "612", "0.45"],
   ["제품 3종", "918", "0.50"], ["제품 4종", "1,224", "0.55"],
   ["제품 6종", "1,836", "0.60"]].forEach(([a, b, c], i) => {
    const yy = 3.94 + i * 0.34, last = i === 4;
    if (last) s.addShape(pptx.ShapeType.roundRect, { x: bx, y: yy - 0.03, w: bw, h: 0.32, fill: { color: GBG }, line: { type: "none" }, rectRadius: 0.04 });
    s.addText(a, { x: bx + 0.08, y: yy, w: 1.18, h: 0.26, fontFace: F, fontSize: 10.5, color: last ? GREEN : SOFT, bold: last });
    s.addText(b, { x: bx + 1.3, y: yy, w: 0.9, h: 0.26, fontFace: F, fontSize: 10.5, color: MUTED, align: "right" });
    s.addText(c, { x: bx + 2.3, y: yy, w: 0.7, h: 0.26, fontFace: F, fontSize: 10.5, color: last ? GREEN : INK, bold: true, align: "right" });
  });
  s.addText("스트림 6배마다 하한이 0.20 올라간다.\n감시 범위를 넓히면 다시 잰다.", {
    x: bx, y: 5.72, w: bw, h: 0.6, fontFace: F, fontSize: 10, color: MUTED, lineSpacingMultiple: 1.35,
  });

  concl(s, "→ 하한은 '고장 전 오탐'이, 상한은 '탐지 지연'이 정한다. 한 점이 아니라 구간이다.");
  s.addNotes("스트림이 많을수록 어딘가에서 한 번 울릴 확률이 올라가는 다중비교 문제다. K=0.7은 상수가 아니라 이 감시 규모에 딸린 값이라고 말해야 한다.");
}

/* ═══════════════════════════════ 3-B. H · 격자 · 과적합 */
{
  const s = slide("검증", "METHOD 03", "H = 4.5 — 그리고 과적합이 아닌 이유",
    "❖ 축을 하나씩만 흔들면 서로를 근거로 삼은 셈이라 42칸을 전부 다시 실행했다.");

  s.addImage({ path: D + "발표_표_KH격자.png", x: M, y: 1.76, w: 5.69, h: 4.62 });

  const bx = 6.60, bw = W - M - bx;
  s.addText("검증 세 가지 — 성격이 다르다", {
    x: bx, y: 1.80, w: bw, h: 0.28, fontFace: F, fontSize: 12.5, color: INK, bold: true,
  });
  [["교과서값 K0.5 / H4.0", "DP01 32 vs DP02 32 — 안 갈림", RED, RBG],
   ["안정성 — 컬럼 홀/짝 반으로", "경계 K  0.60 / 0.55", SOFT, BG],
   ["안정성 — 기간 전/후 반으로", "경계 K  0.60 / 0.55", SOFT, BG],
   ["교차검증 — 장비 하나씩 빼고", "세 폴드 전부 0.7 생존", GREEN, GBG]].forEach(([a, b, c, bg], i) => {
    const yy = 2.20 + i * 0.80;
    s.addShape(pptx.ShapeType.roundRect, { x: bx, y: yy, w: bw, h: 0.68, fill: { color: bg }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(a, { x: bx + 0.16, y: yy + 0.06, w: bw - 0.32, h: 0.26, fontFace: F, fontSize: 10.5, color: MUTED });
    s.addText(b, { x: bx + 0.16, y: yy + 0.32, w: bw - 0.32, h: 0.28, fontFace: F, fontSize: 11.5, color: c, bold: true });
  });
  s.addShape(pptx.ShapeType.roundRect, {
    x: bx, y: 5.44, w: bw, h: 0.94, fill: { color: ABG }, line: { type: "none" }, rectRadius: 0.06,
  });
  s.addText("검증 못 한 것 — 먼저 말한다", { x: bx + 0.16, y: 5.52, w: bw - 0.32, h: 0.26, fontFace: F, fontSize: 11, color: AMBER, bold: true });
  s.addText("정상 장비가 DP01 하나뿐이라 오탐 기준은 홀드아웃이 불가능하다.\n교차검증된 건 탐지 쪽이고, 오탐 쪽은 안정성 검사까지다.", {
    x: bx + 0.16, y: 5.80, w: bw - 0.32, h: 0.52, fontFace: F, fontSize: 9.8, color: SOFT, lineSpacingMultiple: 1.35,
  });

  concl(s, "→ K는 손잡이가 하나고 단조라 맞출 자유도가 애초에 작다. (0.70, 4.5)는 이웃이 모두 통과다.");
  s.addNotes("탐지 지연 상한을 7일·10일·14일 어디로 잡아도 (0.70, 4.5)는 통과한다. 격자의 판정 기준을 물어보면 10일이라고 답한다.");
}

/* ═══════════════════════════════ 4. CUSUM 한계 → 경계 진입 */
{
  const s = slide("판정", "METHOD 04", "CUSUM이 못 보는 것 — 불량으로 학습한 경계",
    "❖ CUSUM은 '평소와 달라졌다'만 말한다. 달라졌다고 불량이 나는 건 아니다.");

  s.addShape(pptx.ShapeType.roundRect, {
    x: M, y: 1.78, w: CW, h: 0.62, fill: { color: RBG }, line: { type: "none" }, rectRadius: 0.06,
  });
  s.addText([
    T("CUSUM이 재는 것    ", { color: RED, bold: true }),
    T("(현재값 − 정상값) / σ", { fontFace: "Courier New", fontSize: 12 }),
    T("      통계적 거리일 뿐, 불량과 연결이 없다", { color: SOFT }),
  ], { x: M + 0.24, y: 1.90, w: CW - 0.48, h: 0.38 });

  s.addImage({ path: D + "발표_그림_경계값학습.png", x: M, y: 2.56, w: 6.35, h: 3.43 });
  s.addImage({ path: D + "발표_그림_5샷연속.png", x: 7.20, y: 2.72, w: 5.51, h: 2.64 });

  s.addText("진입 판정", { x: 7.20, y: 2.44, w: 5.5, h: 0.26, fontFace: F, fontSize: 12, color: INK, bold: true });
  s.addText("if  값이 경계 밖  &&  5샷 연속   →   그 다섯째 샷에 1행", {
    x: 7.20, y: 5.44, w: 5.51, h: 0.30, fontFace: "Courier New", fontSize: 11.5, color: GREEN,
  });
  s.addText("진입 1,461건 — 오래 지속돼도 사건 하나당 1행이다.", {
    x: 7.20, y: 5.78, w: 5.51, h: 0.28, fontFace: F, fontSize: 10.5, color: MUTED,
  });

  concl(s, "→ 결정트리는 순수 노이즈에도 경계를 만든다. 그래서 도메인 방향과 반대면 버린다.");
  s.addNotes("방향 필터 실측: CLN_Flow↔Particle 7개 그룹을 빼니 DP03의 10일짜리 경보가 오탐으로 사라졌고 경보행이 9,941에서 9,701로 줄었다.");
}

/* ═══════════════════════════════ 5. 둘 다 필요 */
{
  const s = slide("검증", "METHOD 05", "왜 둘 다 거는가 — 서로 대체가 아니다",
    "❖ 예전엔 유형이 어느 판정을 받을지까지 정했다. 그러면 서로 잡는 게 다른데 한쪽만 본다.");

  s.addImage({ path: D + "발표_그림_판정분담.png", x: M, y: 1.86, w: 7.6, h: 3.26 });

  const bx = 8.55, bw = W - M - bx;
  [["CUSUM", "평균 수준이 밀렸나 (누적)", "서서히 진행되는 열화", INK, BG],
   ["경계 진입", "위험구간에 샷이 들어갔나 (꼬리)", "평균은 멀쩡한데 개별 샷이 튐", GREEN, GBG]].forEach(([a, b, c, tc, bg], i) => {
    const yy = 1.90 + i * 1.36;
    s.addShape(pptx.ShapeType.roundRect, { x: bx, y: yy, w: bw, h: 1.20, fill: { color: bg }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(a, { x: bx + 0.18, y: yy + 0.10, w: bw - 0.36, h: 0.28, fontFace: F, fontSize: 13, color: tc, bold: true });
    s.addText(b, { x: bx + 0.18, y: yy + 0.44, w: bw - 0.36, h: 0.26, fontFace: F, fontSize: 10.5, color: SOFT });
    s.addText(c, { x: bx + 0.18, y: yy + 0.76, w: bw - 0.36, h: 0.26, fontFace: F, fontSize: 10.5, color: MUTED });
  });
  s.addText("유형이 정하는 건 두 가지뿐이다 —\n기준값을 어디서 가져오나, CUSUM을 편측으로 볼까 양측으로 볼까.", {
    x: bx, y: 4.72, w: bw, h: 0.66, fontFace: F, fontSize: 10.5, color: SOFT, lineSpacingMultiple: 1.4,
  });

  s.addText("어느 한쪽만 걸었으면 127개 또는 195개를 통째로 놓친다.", {
    x: M, y: 5.34, w: 7.6, h: 0.32, fontFace: F, fontSize: 13, color: INK, bold: true,
  });
  note(s, [
    "· 재현: analysis_outputs/trend_analysis_results.csv를 (장비, 컬럼, 제품, 레시피)로 묶어 첫 진입일과 첫 CUSUM일을 비교",
    "· '접근' 판정(넘기 전에 미리 잡는 경로)은 26.08.17에 제거했다 — 잡은 고장 0건, 오탐 2건",
  ], 5.76);

  concl(s, "→ 하나를 고르는 게 아니라 둘 다 건다.");
  s.addNotes("접근 제거 근거: 첫 조건이 '아직 안 넘음'이라 실제 열화에서는 값이 이미 넘어 있어 걸릴 자리가 없다. 창을 30까지 키워도 세 고장의 탐지일이 안 바뀐다.");
}

/* ═══════════════════════════════ 6. 사건화 · 세기 */
{
  const s = slide("결론", "PIPELINE 02", "경보 행 51,037에서 경보 44건까지",
    "❖ early_warning은 상태다. 이상이 지속되면 매 샷 True가 되므로 행을 그대로 세면 안 된다.");

  s.addImage({ path: D + "발표_그림_경보건수.png", x: M, y: 1.74, w: 5.51, h: 4.86 });

  const bx = 6.42, bw = W - M - bx;
  s.addText("44건이 다 같은 경보가 아니다", {
    x: bx, y: 1.78, w: bw, h: 0.32, fontFace: F, fontSize: 15, color: INK, bold: true,
  });

  s.addShape(pptx.ShapeType.roundRect, {
    x: bx, y: 2.20, w: bw, h: 1.30, fill: { color: BG }, line: { type: "none" }, rectRadius: 0.08,
  });
  s.addText([
    { text: "성숙도 = min(1,  지속일 / 14)     증거가 쌓였나", options: { breakLine: true } },
    { text: "긴급도 = min(1,  14 / 도달예상일)  곧 넘나", options: { breakLine: true } },
    { text: "세기   = max(성숙도, 긴급도)", options: {} },
  ], {
    x: bx + 0.22, y: 2.34, w: bw - 0.44, h: 1.02, fontFace: "Courier New", fontSize: 10.5,
    color: INK, lineSpacingMultiple: 1.5,
  });

  s.addShape(pptx.ShapeType.roundRect, { x: bx, y: 3.62, w: bw / 2 - 0.10, h: 1.36, fill: { color: GBG }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText("full", { x: bx, y: 3.74, w: bw / 2 - 0.10, h: 0.32, fontFace: F, fontSize: 16, color: GREEN, bold: true, align: "center" });
  s.addText("9건", { x: bx, y: 4.10, w: bw / 2 - 0.10, h: 0.28, fontFace: F, fontSize: 12.5, color: GREEN, bold: true, align: "center" });
  s.addText("지속 25.4 ~ 59.5일", { x: bx, y: 4.42, w: bw / 2 - 0.10, h: 0.26, fontFace: F, fontSize: 10, color: SOFT, align: "center" });
  s.addText("점수를 최대폭까지 깎음", { x: bx, y: 4.66, w: bw / 2 - 0.10, h: 0.26, fontFace: F, fontSize: 9.5, color: MUTED, align: "center" });

  const bx2 = bx + bw / 2 + 0.10;
  s.addShape(pptx.ShapeType.roundRect, { x: bx2, y: 3.62, w: bw / 2 - 0.10, h: 1.36, fill: { color: BG }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText("early", { x: bx2, y: 3.74, w: bw / 2 - 0.10, h: 0.32, fontFace: F, fontSize: 16, color: MUTED, bold: true, align: "center" });
  s.addText("35건", { x: bx2, y: 4.10, w: bw / 2 - 0.10, h: 0.28, fontFace: F, fontSize: 12.5, color: SOFT, bold: true, align: "center" });
  s.addText("지속 0.0 ~ 5.2일", { x: bx2, y: 4.42, w: bw / 2 - 0.10, h: 0.26, fontFace: F, fontSize: 10, color: SOFT, align: "center" });
  s.addText("흐리게 표시", { x: bx2, y: 4.66, w: bw / 2 - 0.10, h: 0.26, fontFace: F, fontSize: 9.5, color: MUTED, align: "center" });

  s.addShape(pptx.ShapeType.roundRect, {
    x: bx, y: 5.10, w: bw, h: 0.62, fill: { color: "FFFFFF" }, line: { color: GREEN, width: 1.1 }, rectRadius: 0.06,
  });
  s.addText("5.2일과 25.4일 사이가 비어 있다", {
    x: bx + 0.20, y: 5.22, w: bw - 0.40, h: 0.38, fontFace: F, fontSize: 12.5, color: GREEN, bold: true, align: "center",
  });
  s.addText("14일 선이 경계 사례를 하나도 만들지 않는다 — 12일이나 20일로 바꿔도 같은 분류가 나온다.", {
    x: bx, y: 5.82, w: bw, h: 0.52, fontFace: F, fontSize: 10, color: MUTED, lineSpacingMultiple: 1.35,
  });

  concl(s, "→ boolean 하나로 칠하면 '39.6일째'와 '0.2일째'가 같은 배지를 받는다.");
  note(s, ["· 이 구분이 없던 때는 활성 경보 76건 중 63건이 세기 0.5 미만이었고 그 63건의 HI가 전부 96 이상이었다 — 'HI 99인데 빨간 경보'가 화면의 기본 상태였다."], CONCL + 0.52);
  s.addNotes("세기는 새로 만든 기준이 아니라 점수가 이미 쓰고 있는 값을 그대로 표시로 보낸 것이다. 그래야 배지와 점수가 다른 말을 할 수 없다.");
}

pptx.writeFile({ fileName: D + "발표_추세분석_판정.pptx" })
  .then((f) => console.log("저장:", f));
