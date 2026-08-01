"""dashboard_data.json을 읽어서 정적 HTML 대시보드(dashboard.html)를 만든다.
실행: python build_dashboard_html.py (이 폴더 안에서, build_health_index.py 먼저 실행 후)
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
data = json.loads((HERE / "dashboard_data.json").read_text(encoding="utf-8"))

DATA_JSON = json.dumps(data, ensure_ascii=False)

HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>DP 설비 Health Index — 러프 대시보드</title>
<style>
:root{
  --bg:#f5f4f8; --surface:#ffffff; --surface-2:#eeecf5;
  --ink:#171523; --ink-muted:#6b6785; --ink-faint:#a4a0bd;
  --accent:#5b54e8; --accent-soft:#eeecfc;
  --border:#e1dff0;
  --good:#0ca30c; --warning:#c98a00; --serious:#c85a34; --critical:#d03b3b;
  --m1:#2a78d6; --m2:#eb6834; --m3:#1baf7a; --m4:#eda100;
  --font-ui: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", "Roboto Mono", "D2Coding", monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    --bg:#0e0c16; --surface:#17142a; --surface-2:#1e1a35;
    --ink:#ede9fb; --ink-muted:#a49dc9; --ink-faint:#726c99;
    --accent:#9089f7; --accent-soft:#242052;
    --border:#2c2650;
    --good:#3fdc5a; --warning:#f0b94d; --serious:#f0855f; --critical:#f0685a;
    --m1:#3987e5; --m2:#d95926; --m3:#199e70; --m4:#c98500;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0e0c16; --surface:#17142a; --surface-2:#1e1a35;
  --ink:#ede9fb; --ink-muted:#a49dc9; --ink-faint:#726c99;
  --accent:#9089f7; --accent-soft:#242052;
  --border:#2c2650;
  --good:#3fdc5a; --warning:#f0b94d; --serious:#f0855f; --critical:#f0685a;
  --m1:#3987e5; --m2:#d95926; --m3:#199e70; --m4:#c98500;
  color-scheme: dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-ui);
  -webkit-font-smoothing:antialiased; line-height:1.5;}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 80px}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;
  border-bottom:1px solid var(--border);padding-bottom:20px;margin-bottom:28px;flex-wrap:wrap}
.eyebrow{font:600 11px/1 var(--font-mono);letter-spacing:.08em;color:var(--accent);
  text-transform:uppercase;margin:0 0 8px}
h1{font-size:26px;margin:0 0 6px;font-weight:700;text-wrap:balance;letter-spacing:-.01em}
.sub{color:var(--ink-muted);font-size:13.5px;margin:0;max-width:56ch}
.meta{font:12px/1.6 var(--font-mono);color:var(--ink-faint);text-align:right}
.meta b{color:var(--ink-muted);font-weight:600}

.callout{display:flex;gap:10px;align-items:flex-start;background:var(--accent-soft);
  border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:28px;
  font-size:13px;color:var(--ink-muted)}
.callout b{color:var(--ink)}

section{margin-bottom:36px}
.section-head{display:flex;align-items:baseline;justify-content:space-between;
  margin-bottom:14px;gap:12px;flex-wrap:wrap}
h2{font-size:15px;margin:0;font-weight:700}
.section-note{font-size:12px;color:var(--ink-faint)}

.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:16px;position:relative;overflow:hidden}
.card .stripe{position:absolute;left:0;top:0;bottom:0;width:4px}
.card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.card-machine{font:700 13px/1 var(--font-mono);letter-spacing:.02em}
.pill{font:600 10.5px/1 var(--font-ui);padding:4px 8px;border-radius:20px;letter-spacing:.02em}
.pill-good{background:color-mix(in srgb, var(--good) 16%, transparent);color:var(--good)}
.pill-warning{background:color-mix(in srgb, var(--warning) 18%, transparent);color:var(--warning)}
.pill-serious{background:color-mix(in srgb, var(--serious) 18%, transparent);color:var(--serious)}
.pill-critical{background:color-mix(in srgb, var(--critical) 18%, transparent);color:var(--critical)}
.card-num{font:700 34px/1 var(--font-mono);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.card-num small{font-size:14px;color:var(--ink-faint);font-weight:500;margin-left:2px}
.card-spark{margin-top:10px;height:36px}
.card-foot{margin-top:8px;font-size:11.5px;color:var(--ink-faint);display:flex;justify-content:space-between}

.chart-box{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:20px 20px 12px;position:relative}
.legend{display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap}
.legend-item{display:flex;align-items:center;gap:6px;font:600 11.5px/1 var(--font-mono);color:var(--ink-muted)}
.legend-dot{width:9px;height:9px;border-radius:2px}
#chart{width:100%;height:280px;display:block}
.tooltip{position:absolute;pointer-events:none;background:var(--ink);color:var(--bg);
  font:12px/1.5 var(--font-mono);padding:8px 10px;border-radius:6px;opacity:0;
  transform:translate(-50%,-110%);transition:opacity .1s;white-space:nowrap;z-index:5}
:root[data-theme="dark"] .tooltip, @media (prefers-color-scheme:dark){.tooltip{background:var(--ink);color:var(--bg)}}
.tooltip b{font-weight:700}

.alert-list{display:flex;flex-direction:column;gap:8px}
.alert{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:12px 14px 12px 16px;display:flex;gap:8px;position:relative;font-size:13px}
.alert .stripe{position:absolute;left:0;top:0;bottom:0;width:4px;border-radius:8px 0 0 8px}
.alert-body{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
.alert-row1{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.alert .machine{font:700 12.5px var(--font-mono)}
.alert .date{font:12px var(--font-mono);color:var(--ink-muted)}
.alert .hi{font:700 16px var(--font-mono);font-variant-numeric:tabular-nums;margin-left:auto}
.alert .badge{font:600 11px var(--font-ui);color:var(--ink-faint);white-space:nowrap}
.alert .factors{display:flex;gap:6px;flex-wrap:wrap}
.chip{font:600 11px var(--font-ui);background:var(--surface-2);border:1px solid var(--border);
  padding:3px 8px;border-radius:5px;color:var(--ink-muted);white-space:nowrap}
.alert-empty{color:var(--ink-faint);font-size:13px;padding:16px;text-align:center;
  background:var(--surface);border:1px dashed var(--border);border-radius:8px}

.sop-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.sop-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.sop-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.sop-factor{font:700 14px var(--font-mono)}
.sop-defects{font:600 10.5px var(--font-ui);color:var(--accent);background:var(--accent-soft);
  padding:3px 8px;border-radius:5px;white-space:nowrap}
.sop-mech{font-size:12.5px;color:var(--ink-muted);margin-bottom:12px;line-height:1.55}
.sop-step{font-size:12.5px;margin-bottom:6px;padding-left:14px;position:relative}
.sop-step:before{content:"";position:absolute;left:0;top:7px;width:5px;height:5px;
  border-radius:50%;background:var(--ink-faint)}
.sop-step b{color:var(--ink)}
.sop-foot{margin-top:12px;padding-top:10px;border-top:1px solid var(--border);
  display:flex;justify-content:space-between;align-items:center}
.sop-source{font:12px var(--font-mono);color:var(--ink-faint)}
.sop-draft{font:700 10px var(--font-ui);color:var(--critical);letter-spacing:.03em}

table{width:100%;border-collapse:collapse;font-size:12.5px}
.table-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--border);border-radius:8px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
th{font:600 11px var(--font-ui);color:var(--ink-faint);text-transform:uppercase;letter-spacing:.04em}
td{font:12.5px var(--font-mono)}
tr:last-child td{border-bottom:none}

footer{margin-top:48px;padding-top:20px;border-top:1px solid var(--border);
  font-size:11.5px;color:var(--ink-faint);line-height:1.7}
footer b{color:var(--ink-muted)}

@media (max-width:820px){
  .cards{grid-template-columns:repeat(2,1fr)}
}
@media (max-width:520px){
  .cards{grid-template-columns:1fr}
  .alert .hi{margin-left:0}
}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div>
      <p class="eyebrow">Goal 5 — Health Index · Draft v0</p>
      <h1>DP 설비 Health Index 대시보드</h1>
      <p class="sub">안정성·열화추세·불량률을 하나의 점수로 합친 러프 버전. 월요일 멘토 미팅용 초안이며 가중치는 잠정치입니다.</p>
    </div>
    <div class="meta">생성 <b id="gen-time"></b><br>데이터 90일 · 장비 4대 · 2026-01-01 ~ 2026-03-30</div>
  </div>

  <div class="callout">
    <span>⚠</span>
    <span><b>이 대시보드는 초안입니다.</b> Health Index 가중치는 잠정치이고, 아래 SOP 제안은 전부
    <code>DRAFT_UNVERIFIED</code> — 멘토·현장 확인 전까지 참고용입니다. 원인 변수는 daeho(Particle)·
    전성재(Remain_Coat)·JHdaimma(Chipping/Micro_Crack)가 각각 확정한 결과를 그대로 가져왔습니다.</span>
  </div>

  <section id="cards-section">
    <div class="section-head">
      <h2>장비 현황 · 최신값</h2>
      <span class="section-note">지난 30일 추세</span>
    </div>
    <div class="cards" id="cards"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>Health Index 추세 (전체 기간)</h2>
      <span class="section-note">선을 올리면 날짜별 값 확인</span>
    </div>
    <div class="chart-box">
      <div class="legend" id="legend"></div>
      <svg id="chart" viewBox="0 0 1100 280" preserveAspectRatio="none"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2>현재 경보 <span class="section-note" id="alert-count"></span></h2>
      <span class="section-note">Health Index 낮은 순 · 최근 7일</span>
    </div>
    <div class="alert-list" id="alerts"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>SOP 제안 (초안)</h2>
      <span class="section-note">경보에 등장한 원인변수 기준</span>
    </div>
    <div class="sop-grid" id="sop"></div>
  </section>

  <footer id="footer"></footer>
</div>

<script id="dashboard-data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
const MCOLOR = {DP01:'var(--m1)', DP02:'var(--m2)', DP03:'var(--m3)', DP04:'var(--m4)'};
const MACHINES = ['DP01','DP02','DP03','DP04'];

document.getElementById('gen-time').textContent = new Date(DATA.generated_at).toLocaleString('ko-KR');

function statusOf(hi){
  if(hi>=90) return {cls:'good', label:'양호'};
  if(hi>=85) return {cls:'warning', label:'관찰 필요'};
  if(hi>=75) return {cls:'serious', label:'주의'};
  return {cls:'critical', label:'위험'};
}

// ---- group series by machine, sorted by date ----
const byMachine = {};
for(const m of MACHINES) byMachine[m] = [];
for(const row of DATA.health_index_series){
  byMachine[row.Machine_ID].push(row);
}
for(const m of MACHINES) byMachine[m].sort((a,b)=> a.date.localeCompare(b.date));

// ---- machine cards ----
const cardsEl = document.getElementById('cards');
for(const m of MACHINES){
  const series = byMachine[m];
  const latest = series[series.length-1];
  const last30 = series.slice(-30);
  const st = statusOf(latest.health_index);
  const min = Math.min(...last30.map(r=>r.health_index));
  const max = Math.max(...last30.map(r=>r.health_index));
  const pad = (max-min) < 1 ? 1 : (max-min)*0.15;
  const lo = min-pad, hi = max+pad;
  const w=240, h=36;
  const pts = last30.map((r,i)=>{
    const x = (i/(last30.length-1))*w;
    const y = h - ((r.health_index-lo)/(hi-lo))*h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <div class="stripe" style="background:var(--${st.cls})"></div>
    <div class="card-head">
      <span class="card-machine">${m}</span>
      <span class="pill pill-${st.cls}">${st.label}</span>
    </div>
    <div class="card-num">${latest.health_index.toFixed(1)}<small>/100</small></div>
    <svg class="card-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="var(--${st.cls})" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div class="card-foot"><span>${latest.date}</span><span>30일 ${min.toFixed(1)}–${max.toFixed(1)}</span></div>
  `;
  cardsEl.appendChild(card);
}

// ---- legend ----
const legendEl = document.getElementById('legend');
for(const m of MACHINES){
  const item = document.createElement('div');
  item.className = 'legend-item';
  item.innerHTML = `<span class="legend-dot" style="background:${MCOLOR[m]}"></span>${m}`;
  legendEl.appendChild(item);
}

// ---- main chart (hand-computed SVG line chart, real data) ----
const svg = document.getElementById('chart');
const tooltip = document.getElementById('tooltip');
const W = 1100, H = 280, ML = 34, MR = 8, MT = 10, MB = 26;
const plotW = W-ML-MR, plotH = H-MT-MB;
const allDates = byMachine.DP01.map(r=>r.date);
const yMin = 60, yMax = 100;

function xFor(i){ return ML + (i/(allDates.length-1))*plotW; }
function yFor(v){ return MT + plotH - ((v-yMin)/(yMax-yMin))*plotH; }

let svgHTML = '';
// gridlines (recessive)
for(let v=yMin; v<=yMax; v+=10){
  svgHTML += `<line x1="${ML}" x2="${W-MR}" y1="${yFor(v)}" y2="${yFor(v)}"
    stroke="var(--border)" stroke-width="1"/>`;
  svgHTML += `<text x="${ML-8}" y="${yFor(v)+4}" text-anchor="end" font-size="10.5"
    font-family="var(--font-mono)" fill="var(--ink-faint)">${v}</text>`;
}
// month ticks
const monthTicks = [];
allDates.forEach((d,i)=>{ if(d.endsWith('-01') || i===0) monthTicks.push(i); });
monthTicks.forEach(i=>{
  svgHTML += `<text x="${xFor(i)}" y="${H-6}" font-size="10.5" font-family="var(--font-mono)"
    fill="var(--ink-faint)">${allDates[i].slice(5)}</text>`;
});

for(const m of MACHINES){
  const pts = byMachine[m].map((r,i)=>`${xFor(i).toFixed(1)},${yFor(r.health_index).toFixed(1)}`).join(' ');
  svgHTML += `<polyline points="${pts}" fill="none" stroke="${MCOLOR[m]}" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" data-machine="${m}"/>`;
}
// hover crosshair group
svgHTML += `<g id="crosshair" style="opacity:0">
  <line id="crossline" x1="0" x2="0" y1="${MT}" y2="${MT+plotH}" stroke="var(--ink-faint)" stroke-width="1" stroke-dasharray="3,3"/>
</g>`;
// hit layer
svgHTML += `<rect id="hit" x="${ML}" y="${MT}" width="${plotW}" height="${plotH}" fill="transparent"/>`;
svg.innerHTML = svgHTML;

const hit = document.getElementById('hit');
const crosshair = document.getElementById('crosshair');
const crossline = document.getElementById('crossline');
const chartBox = svg.closest('.chart-box');

hit.addEventListener('mousemove', (e)=>{
  const rect = svg.getBoundingClientRect();
  const scaleX = W/rect.width;
  const xPix = (e.clientX-rect.left)*scaleX;
  let idx = Math.round(((xPix-ML)/plotW)*(allDates.length-1));
  idx = Math.max(0, Math.min(allDates.length-1, idx));
  const x = xFor(idx);
  crossline.setAttribute('x1', x); crossline.setAttribute('x2', x);
  crosshair.style.opacity = 1;

  const boxRect = chartBox.getBoundingClientRect();
  const relX = (x/W)*rect.width + (rect.left-boxRect.left);
  const relY = (rect.top-boxRect.top) + 20;
  tooltip.style.left = relX+'px';
  tooltip.style.top = relY+'px';
  tooltip.style.opacity = 1;
  let rows = MACHINES.map(m=>{
    const r = byMachine[m][idx];
    return `<div><span style="color:${MCOLOR[m]}">●</span> ${m} <b>${r.health_index.toFixed(1)}</b></div>`;
  }).join('');
  tooltip.innerHTML = `<div style="margin-bottom:4px;color:var(--ink-faint)">${allDates[idx]}</div>${rows}`;
});
hit.addEventListener('mouseleave', ()=>{ crosshair.style.opacity=0; tooltip.style.opacity=0; });

// ---- alerts ----
const alertsEl = document.getElementById('alerts');
document.getElementById('alert-count').textContent = `· ${DATA.alerts.length}건`;
if(DATA.alerts.length===0){
  alertsEl.innerHTML = `<div class="alert-empty">현재 조건(HI&lt;80, 최근 7일)에 해당하는 경보가 없습니다.</div>`;
} else {
  for(const a of DATA.alerts){
    const st = statusOf(a.health_index);
    const factors = a.triggered_factors==='-' ? [] : a.triggered_factors.split(',');
    const row = document.createElement('div');
    row.className = 'alert';
    row.innerHTML = `
      <div class="stripe" style="background:var(--${st.cls})"></div>
      <div class="alert-body">
        <div class="alert-row1">
          <span class="machine">${a.Machine_ID}</span>
          <span class="date">${a.date}</span>
          <span class="badge">${a.trigger_type}</span>
          <span class="hi">${a.health_index.toFixed(1)}</span>
        </div>
        <div class="factors">${factors.map(f=>`<span class="chip">${f}</span>`).join('') || '<span class="chip">복합 원인</span>'}</div>
      </div>
    `;
    alertsEl.appendChild(row);
  }
}

// ---- SOP cards ----
const sopEl = document.getElementById('sop');
for(const s of DATA.sop_suggestions){
  const card = document.createElement('div');
  card.className = 'sop-card';
  card.innerHTML = `
    <div class="sop-top">
      <span class="sop-factor">${s.factor}</span>
      <span class="sop-defects">${s.defects}</span>
    </div>
    <div class="sop-mech">${s.mechanism}</div>
    <div class="sop-step"><b>점검</b> — ${s.check.replace(s.factor+' ','')}</div>
    <div class="sop-step"><b>조치</b> — ${s.action.replace(s.factor+' ','')}</div>
    <div class="sop-foot">
      <span class="sop-source">근거: ${s.source}</span>
      <span class="sop-draft">DRAFT</span>
    </div>
  `;
  sopEl.appendChild(card);
}

// ---- footer ----
document.getElementById('footer').innerHTML = `
  <b>Health Index 산식 (잠정)</b> — 100 − 불량페널티(Yield 7일 이동평균 기반) − 안정성페널티(원인변수 OPCOND 층화 z-score) − 추세페널티(Mann-Kendall 유의 추세 개수). 가중치는 팀 논의로 조정 예정.<br>
  <b>데이터 출처</b> — 전처리: pipeline/(김시우) · Particle: daeho · Remain_Coat: 전성재 · Chipping/Micro_Crack: JHdaimma · 추세검정: pipeline/00_machine_column_trend.csv<br>
  <b>제외 처리</b> — Edge_Burn(멘토 확인 결과 유효 실패모드 아님), Focus/Cutting_Offset(멘토 지정 분석 비활용 변수)은 전 과정에서 제외됨.
`;
</script>
</body></html>
"""

out = HTML.replace("__DATA_JSON__", DATA_JSON)
(HERE / "dashboard.html").write_text(out, encoding="utf-8")
print("dashboard.html 생성 완료:", (HERE / "dashboard.html").stat().st_size, "bytes")

# Artifact 게시용: <!doctype>/<html>/<head>/<body> 래퍼만 제거한 버전 (Artifact 툴이 자체 스켈레톤으로 감쌈)
artifact_body = (
    out
    .replace('<!doctype html><html lang="ko"><head><meta charset="utf-8">\n', "")
    .replace("\n</head>\n<body>\n", "\n")
    .replace("\n</body></html>\n", "\n")
)
(HERE / "dashboard_artifact.html").write_text(artifact_body, encoding="utf-8")
print("dashboard_artifact.html 생성 완료:", (HERE / "dashboard_artifact.html").stat().st_size, "bytes")
