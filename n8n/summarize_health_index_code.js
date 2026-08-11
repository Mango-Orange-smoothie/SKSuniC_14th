// n8n "Summarize Health Index" Code 노드용 (lsyeon 참고용 사본).
// 실제 반영은 n8n 화면에서 이 내용을 그대로 붙여넣어야 함 — n8n 워크플로우 export/
// import 절차(README 참고)를 밟기 전까지는 이 파일 자체가 실행되는 게 아님.

const data = JSON.parse($input.first().json.stdout);
// 등급 경계는 combine_report_data.py가 payload에 실어 보낸다(단일 출처).
// 예전 payload로 돌려도 죽지 않게 기본값을 둔다.
const CRITICAL_THRESHOLD = data._thresholds?.critical ?? 50;
const WATCH_THRESHOLD = data._thresholds?.watch ?? 80;
// {"DP04__CLN_Flow": "<base64 png>"} — 파이썬이 matplotlib로 그려 넣은 추세 그래프.
const chartPngs = data._charts || {};

// 이 실행에서 실제로 쓴 그래프만 메일에 첨부한다.
// binaries: n8n Code 노드가 돌려주는 binary 프로퍼티(첨부 파일이 됨)
// cids: emailSend 노드의 Attachments 옵션에 넘길 이름 목록
const binaries = {};
const cids = [];
function chartImg(machineId, factorName) {
  const b64 = chartPngs[`${machineId}__${factorName}`];
  if (!b64) return '';
  const cid = `chart_${cids.length}`;
  binaries[cid] = { data: b64, mimeType: 'image/png', fileName: `${cid}.png` };
  cids.push(cid);
  // width는 지정하되 height는 비워둬야 세로가 안 찌그러진다. display:block 은 Gmail의
  // 이미지 아래 여백 제거용.
  return `<div style="margin:8px 0 10px;padding:6px;background:#ffffff;border:1px solid #dde1e4;border-radius:6px;">
    <img src="cid:${cid}" alt="${esc(factorName)} 추세" width="600" style="display:block;width:100%;max-width:600px;height:auto;border:0;" />
  </div>`;
}

// rel_20_tier_table.csv (JHdaimma님 관계DB, 11행) — 파일이 작아 코드에 직접 박아둠.
// 테이블이 바뀌면 이 상수도 같이 업데이트해야 함.
const TIER_LOOKUP = {
  'Chipping|Power_Efficiency': '즉시조치',
  'Chipping|Laser_Power': '즉시조치',
  'Chipping|Head_Temp': '즉시조치',
  'Remain_Coat|CLN_Pressure': '급락알람',
  'Remain_Coat|CLN_Flow': '즉시조치',
  'Chipping|Cooling_Flow': '조건부조치',
  'Particle|CLN_Flow': '조건부조치',
  'Micro_Crack|Cooling_Flow': '감시',
  'Micro_Crack|Cooling_Water_Temp': '판단보류',
  'Particle|CLN_Pressure': '판단보류',
  'Particle|Surface_Roughness': '감시(경보)',
};

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const trendLabel = (dir) => dir === 'up' ? '상승 추세' : dir === 'down' ? '하강 추세' : '-';
const tierOf = (defect, factor) => TIER_LOOKUP[`${defect}|${factor}`] || null;
const tierColor = (hi) => hi === null ? '#9aa3ac' : hi < CRITICAL_THRESHOLD ? '#b3362b' : hi < WATCH_THRESHOLD ? '#a8721c' : '#9aa3ac';
const tierName = (hi) => hi === null ? 'ok' : hi < CRITICAL_THRESHOLD ? 'critical' : hi < WATCH_THRESHOLD ? 'watch' : 'ok';

const machines = Object.entries(data.machines).map(([id, m]) => ({
  machine_id: id,
  health_index: m.health_index,
  worst_defect: m.worst_defects?.[0]?.defect ?? null,
  worst_factor: m.worst_defects?.[0]?.worst_factor ?? null,
  defect_signals: m.defect_signals || {},
}));
machines.sort((a, b) => (a.health_index ?? 100) - (b.health_index ?? 100));

const critical = machines.filter(m => m.health_index !== null && m.health_index < CRITICAL_THRESHOLD);
const watch = machines.filter(m => m.health_index !== null && m.health_index >= CRITICAL_THRESHOLD && m.health_index < WATCH_THRESHOLD);
const okMachines = machines.filter(m => m.health_index === null || m.health_index >= WATCH_THRESHOLD);

const summaryText = critical.length
  ? `⚠️ 위험 장비 ${critical.length}대: ` + critical.map(w => `${w.machine_id}(${w.health_index})`).join(', ')
  : (watch.length ? `현재 위험 장비 없음, 주의 ${watch.length}대: ` + watch.map(w => `${w.machine_id}(${w.health_index})`).join(', ')
  : `현재 위험/주의 장비 없음`);

// 장비 전체 현황
const fleetHtml = machines.map(m => {
  const tier = tierName(m.health_index);
  const color = tierColor(m.health_index);
  const bg = tier === 'critical' ? '#fbeae8' : tier === 'watch' ? '#fbf2e2' : '#e7f2ec';
  const border = tier === 'critical' ? '#e7bcb6' : tier === 'watch' ? '#e9d2a3' : '#bfdccc';
  return `<td style="padding:10px 10px;border:1px solid ${border};background:${bg};border-radius:8px;">
    <div style="font-family:monospace;font-size:12px;font-weight:600;color:#5b6570;">${esc(m.machine_id)}</div>
    <div style="font-family:monospace;font-size:20px;font-weight:700;color:${color};">${m.health_index}</div>
    <div style="font-size:10.5px;color:#8993a0;white-space:nowrap;"><b style="color:#8993a0;">불량</b> ${esc(m.worst_defect)}</div>
    <div style="font-size:10.5px;color:#8993a0;white-space:nowrap;"><b style="color:#8993a0;">주요 지표</b> ${esc(m.worst_factor)}</div>
  </td>`;
}).join('');

// 위험/주의 카드 공통 렌더러. includeChart=true면 defect의 첫(최저) 원인변수에만 그래프를 붙인다.
function renderMachineCard(m, tierClass, includeChart) {
  const border = tierClass === 'critical' ? '#e7bcb6' : '#e9d2a3';
  const accent = tierClass === 'critical' ? '#b3362b' : '#a8721c';
  const bg = tierClass === 'critical' ? '#fbeae8' : '#fbf2e2';

  let defectsHtml = '';
  const defectsSorted = Object.entries(m.defect_signals).sort((a, b) => (a[1].health_index ?? 100) - (b[1].health_index ?? 100));
  for (const [defect, sig] of defectsSorted) {
    if (sig.health_index === null || sig.health_index >= WATCH_THRESHOLD) continue;

    const factorsSorted = Object.entries(sig.causes || {}).sort((a, b) => (a[1].health_index ?? 100) - (b[1].health_index ?? 100));
    if (!factorsSorted.length) continue;

    let rowsHtml = '';
    let chartHtml = '';
    let isFirst = true;
    for (const [factorName, c] of factorsSorted) {
      const t = tierName(c.health_index);
      const color = tierColor(c.health_index);
      const margin = c.health_index !== null ? Math.max(0, Math.min(100, 100 - c.health_index)) : 0;
      // 조치 태그(즉시조치/급락알람 등)는 관계DB에 박힌 "변수-불량 쌍의 고정 속성"이라
      // 건강도와 무관하다. 그대로 다 붙이면 HI 100인 변수에도 "즉시조치"가 달려서
      // 지금 당장 손대라는 뜻으로 오해된다 — 위험/주의 구간(HI < 80)일 때만 표시한다.
      const tier = (t === 'ok') ? null : tierOf(defect, factorName);
      rowsHtml += `<div style="padding:6px 0;border-top:1px solid #dde1e4;">
        <div style="font-size:12px;font-weight:600;">${esc(factorName)}${tier ? ` <span style="display:inline-block;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;border:1px solid #e7bcb6;color:#b3362b;letter-spacing:0.02em;">${esc(tier)}</span>` : ''}
          <span style="float:right;font-family:monospace;font-weight:700;color:${color};">${c.health_index}</span></div>
        <div style="height:6px;border-radius:3px;background:#dde1e4;overflow:hidden;margin:4px 0 2px;">
          <div style="height:6px;border-radius:3px;background:${color};width:${margin}%;"></div>
        </div>
        <div style="font-size:12.5px;color:#8993a0;display:flex;justify-content:space-between;">
          <span style="color:#5b6570;font-weight:600;">${trendLabel(c.trend_direction)}</span><span>여유 ${c.health_index}%</span>
        </div>
        <div style="font-size:12px;color:#5b6570;font-family:monospace;">현재 ${c.current_value} · 기준 ${c.baseline_median} · 범위 ${c.lsl}~${c.usl}</div>
      </div>`;

      if (isFirst && includeChart) {
        chartHtml = chartImg(m.machine_id, factorName);
      }
      isFirst = false;
    }

    const occText = sig.actual_occurred_recent_7d
      ? `최근 7일 실제 발생 ${sig.occurred_days_recent_7d}일 (계속 발생 중)`
      : `최근 7일 실제 발생 없음 (선행 신호 단계)`;
    const worstFactorName = factorsSorted[0][0];

    defectsHtml += `<div style="padding:12px 16px;border-top:1px dashed #dde1e4;">
      <p style="font-size:13px;font-weight:700;margin:0 0 2px;">${esc(defect)} <span style="display:inline-block;font-size:9.5px;font-weight:700;padding:1px 5px;border-radius:3px;background:#b3362b;color:#fff;margin-left:5px;">경보 활성</span> <span style="font-size:9.5px;font-weight:600;color:#5b6570;margin-left:4px;">${esc(worstFactorName)} 악화 중</span></p>
      <p style="font-size:11px;color:#8993a0;margin:0 0 8px;">${occText} · 최저 지표 ${esc(worstFactorName)} 기준</p>
      ${rowsHtml}
      ${chartHtml}
    </div>`;
  }
  if (!defectsHtml) return '';

  return `<div style="margin:10px 0;border:1px solid ${border};border-left:4px solid ${accent};border-radius:8px;overflow:hidden;">
    <div style="padding:12px 16px;background:${bg};display:flex;justify-content:space-between;">
      <span style="font-family:monospace;font-weight:700;font-size:15px;">${esc(m.machine_id)}</span>
      <span style="font-family:monospace;font-weight:700;font-size:18px;color:${accent};">${m.health_index}</span>
    </div>
    ${defectsHtml}
  </div>`;
}

const criticalCardsHtml = critical.map(m => renderMachineCard(m, 'critical', true)).join('');
const watchCardsHtml = watch.map(m => renderMachineCard(m, 'watch', false)).join('');

// 정상 목록
const okHtml = okMachines.map(m => `<div style="display:flex;gap:10px;padding:8px 14px;background:#e7f2ec;border-top:1px solid #bfdccc;font-size:12px;">
  <span style="font-family:monospace;font-weight:700;width:42px;">${esc(m.machine_id)}</span>
  <span style="font-family:monospace;font-weight:700;color:#3c7a5d;width:34px;">${m.health_index}</span>
  <span style="color:#5b6570;"><b style="color:#8993a0;">불량</b> ${esc(m.worst_defect)} · <b style="color:#8993a0;">주요 지표</b> ${esc(m.worst_factor)}</span>
</div>`).join('');

const reportHtml = `<div style="font-family:-apple-system,'Segoe UI',Roboto,'Malgun Gothic',Helvetica,Arial,sans-serif;max-width:640px;color:#1a2027;">
  <h2 style="margin:0 0 4px;">Health Index 데일리 리포트</h2>
  <p style="color:#8993a0;font-size:12px;margin:0 0 14px;">생성 ${esc(data.generated_at)}</p>
  <p style="font-size:15px;"><b>${esc(summaryText)}</b></p>
  <p style="margin:0 0 6px;font-size:11px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;color:#8993a0;">장비 전체 현황</p>
  <p style="margin:0 0 8px;font-size:11px;color:#8993a0;">🔴 위험 &lt;${CRITICAL_THRESHOLD} · 🟡 주의 ${CRITICAL_THRESHOLD}~${WATCH_THRESHOLD} · 🟢 정상 ≥${WATCH_THRESHOLD}</p>
  <table cellpadding="0" cellspacing="8" style="border-collapse:separate;width:100%;"><tr>${fleetHtml}</tr></table>

  ${criticalCardsHtml ? `<p style="margin:16px 0 0;font-size:11px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;color:#8993a0;">장비 상세 현황</p>
  <p style="margin:2px 0 10px;font-size:11px;color:#8993a0;text-transform:uppercase;letter-spacing:0.06em;">위험 (Health Index &lt; ${CRITICAL_THRESHOLD})</p>
  ${criticalCardsHtml}` : ''}

  ${watchCardsHtml ? `<p style="margin:16px 0 0;font-size:11px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;color:#8993a0;">주의 (Health Index ${CRITICAL_THRESHOLD}~${WATCH_THRESHOLD})</p>
  ${watchCardsHtml}` : ''}

  ${okHtml ? `<p style="margin:16px 0 6px;font-size:11px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;color:#8993a0;">정상 (Health Index ≥ ${WATCH_THRESHOLD})</p>
  <div style="border:1px solid #dde1e4;border-radius:8px;overflow:hidden;">${okHtml}</div>` : ''}
</div>`;

return [{
  json: {
    generated_at: data.generated_at,
    critical_threshold: CRITICAL_THRESHOLD,
    watch_threshold: WATCH_THRESHOLD,
    summary: summaryText,
    report_html: reportHtml,
    has_warning: critical.length > 0,
    // emailSend 노드의 Attachments 옵션에 이 값을 식으로 넘긴다: {{ $json.chart_cids }}
    // 고정 목록으로 적으면 안 된다 — n8n이 assertBinaryData로 검사해서 그날 그래프가
    // 하나라도 비면 예외가 난다. 그래프가 아예 없으면 빈 문자열이 되고, 빈 문자열은
    // falsy라 n8n이 첨부 처리 자체를 건너뛴다(에러 안 남).
    chart_cids: cids.join(','),
    critical,
    // 메일 제목 식이 예전부터 $json.warnings.length 를 쓰고 있다(위험 장비 수).
    // 필드명을 critical로 바꾸면서 그 식이 undefined를 참조하게 됐으므로 별칭을 같이 내보낸다
    // — n8n 화면에서 제목 식을 고치게 하는 것보다 이쪽이 덜 깨진다.
    warnings: critical,
    watch,
    machines: machines.map(({ defect_signals, ...rest }) => rest),
  },
  binary: binaries,
}];
