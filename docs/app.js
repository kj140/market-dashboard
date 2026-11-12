'use strict';

const AREAS = [
  { key: 'us', flag: '🇺🇸', name: '米国' },
  { key: 'jp', flag: '🇯🇵', name: '日本' },
  { key: 'semi', flag: '🔬', name: '半導体' },
];

const COLORS = {
  line: '#f6a945',
  lineBackfill: 'rgba(246, 169, 69, 0.45)',
  lineHold: '#5d677a',
  grid: '#253049',
  normal: '#4a5878',
  tick: '#8a95a8',
};

// 今日・前日・1週前・1か月前 (drawn in this order of priority: today on top).
const MARKS = [
  { id: 'month', label: '1か月前', color: '#7aa2ff' },
  { id: 'week', label: '1週前', color: '#b58cff' },
  { id: 'prev', label: '前日', color: '#aab6cc' },
  { id: 'today', label: '今日', color: '#ffffff' },
];

const NO_DATA = 'データなし';

const STATUS_LABEL = { live: '取得', stale: '前回値', manual: '手入力', missing: '取得失敗' };

// Scoring keys that are derived from a metric with another key.
const METRIC_OF_KEY = { sox_combo: 'sox_drop' };

const TAB_STORAGE_KEY = 'md.tab';

const state = { latest: null, entries: [], area: 'us', days: 91, chart: null };

// ---------- helpers ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function $(id) { return document.getElementById(id); }

function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return t.toISOString().slice(0, 10);
}

function md(iso) {
  if (!iso) return '';
  const [, m, d] = iso.split('-').map(Number);
  return `${m}/${d}`;
}

// Same rule as history.entry_near: the latest entry dated on or before target.
function entryNear(entries, targetIso) {
  let best = null;
  for (const e of entries) {
    if (e.date <= targetIso && (!best || e.date > best.date)) best = e;
  }
  return best;
}

function fmtNum(v, maxDigits = 2) {
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: maxDigits });
}

function fmtJst(isoDateTime) {
  const t = new Date(isoDateTime);
  if (Number.isNaN(t.getTime())) return null;
  const parts = {};
  new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(t).forEach((p) => { parts[p.type] = p.value; });
  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

function metricOf(key) {
  const m = state.latest.metrics || {};
  return m[METRIC_OF_KEY[key] || key] || null;
}

function labelOf(key) {
  const m = metricOf(key);
  return m && m.label ? m.label : key;
}

function verdictClass(v) {
  if (v === '買い増し') return 'buy';
  if (v === '保有') return 'hold';
  if (v === '全利確' || (typeof v === 'string' && v.startsWith('利確'))) return 'sell';
  return 'none';
}

// Values from config/rules.yaml that the pipeline copies into latest.display.
// Returns null when absent (older latest.json): callers then skip the feature.
function displayValue(key) {
  const d = state.latest.display;
  const v = d ? d[key] : undefined;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function loadTab() {
  try { return localStorage.getItem(TAB_STORAGE_KEY); } catch (e) { return null; }
}

function saveTab(key) {
  try { localStorage.setItem(TAB_STORAGE_KEY, key); } catch (e) { /* storage unavailable */ }
}

// ---------- header ----------

function renderHeader() {
  const gen = state.latest.generated_at;
  const label = fmtJst(gen);
  $('updated').textContent = `最終更新 ${label || '不明'}`;
  const ageHours = (Date.now() - new Date(gen).getTime()) / 3600000;
  const banner = $('stale');
  const staleHours = displayValue('stale_page_hours');
  if (staleHours !== null && (!label || ageHours > staleHours)) {
    banner.textContent = `更新が止まっています（最終 ${label || '不明'}）`;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }

  // Which closes the ratios and verdicts were evaluated on (R18).
  const dates = state.latest.market_dates || {};
  $('eval-dates').textContent = `評価: 米 ${md(dates.us) || '—'}・日 ${md(dates.jp) || '—'} 終値`;
  const mf = state.latest.market_fetch;
  const marketBanner = $('market-fetch');
  if (mf && mf.ok === false) {
    const since = mf.failed_since ? fmtJst(mf.failed_since) : null;
    const lastClose = [dates.us, dates.jp].filter(Boolean).sort().pop();
    marketBanner.textContent = `市場データを取得できていません（${since || '不明'} から）。`
      + `表示中の比率・判定は ${md(lastClose) || '不明'} 終値時点のものです`;
    marketBanner.hidden = false;
  } else {
    marketBanner.hidden = true;
  }
}

// ---------- tabs ----------

function renderTabs() {
  const box = $('tabs');
  box.replaceChildren();
  for (const a of AREAS) {
    const r = state.latest.areas[a.key];
    const btn = el('button', '', `${a.flag} ${a.name} ${r ? r.ratio + '%' : '—'}`);
    btn.type = 'button';
    btn.setAttribute('role', 'tab');
    btn.disabled = !r;
    btn.setAttribute('aria-selected', String(a.key === state.area));
    if (a.key === state.area) btn.classList.add('on');
    if (r && r.on_hold) btn.classList.add('hold');
    if (r && r.prev_ratio !== null && r.prev_ratio !== undefined && r.prev_ratio !== r.ratio) {
      const dot = el('span', 'dot');
      dot.setAttribute('aria-label', '前日から変化');
      btn.appendChild(dot);
    }
    btn.addEventListener('click', () => {
      state.area = a.key;
      saveTab(a.key);
      renderArea();
    });
    box.appendChild(btn);
  }
}

// ---------- area card ----------

function markEntries() {
  const n = state.entries.length;
  if (!n) return {};
  const today = state.entries[n - 1];
  return {
    today,
    prev: n >= 2 ? state.entries[n - 2] : null,
    week: entryNear(state.entries, addDays(today.date, -7)),
    month: entryNear(state.entries, addDays(today.date, -30)),
  };
}

function renderAreaHead() {
  const a = AREAS.find((x) => x.key === state.area);
  const r = state.latest.areas[state.area];
  $('area-title').textContent = `${a.name}キャッシュ目安`;
  $('area-ratio').textContent = `${r.ratio}%`;
  const delta = $('area-delta');
  delta.className = 'delta';
  if (r.prev_ratio === null || r.prev_ratio === undefined) {
    delta.textContent = '';
  } else {
    const d = r.ratio - r.prev_ratio;
    delta.textContent = d > 0 ? `▲${d}` : d < 0 ? `▼${-d}` : '±0';
    if (d > 0) delta.classList.add('up');
    if (d < 0) delta.classList.add('down');
  }
  $('area').classList.toggle('on-hold', !!r.on_hold);
  $('area-hold').hidden = !r.on_hold;
  $('area-reason').textContent = r.reason ? `主な理由：${r.reason}` : '';
}

function renderLegend() {
  const box = $('legend');
  box.replaceChildren();
  const marks = markEntries();
  for (const mk of MARKS.slice().reverse()) {
    const e = marks[mk.id];
    const v = e && e.areas[state.area] ? `${e.areas[state.area].ratio}%` : '—';
    const span = el('span', '', `${mk.label} ${v}`);
    span.style.setProperty('--c', mk.color);
    box.appendChild(span);
  }
}

function renderNotes() {
  const r = state.latest.areas[state.area];
  const ul = $('area-notes');
  ul.replaceChildren();
  const add = (text, warn) => ul.appendChild(el('li', warn ? 'warn' : '', text));

  if (r.missing && r.missing.length) {
    add(`判定に使えなかった指標（取得失敗）：${r.missing.map(labelOf).join('、')}`, false);
  }
  const keys = (r.contributions || []).map((c) => c.key);
  for (const k of keys) {
    const m = metricOf(k);
    if (!m) continue;
    if (m.status === 'stale') {
      add(`前回値を使用：${m.label}（${md(m.as_of)}）`, false);
    }
    if (m.status === 'manual' && m.extra && m.extra.overdue) {
      const days = m.extra.days_since_update;
      let ago = '';
      if (typeof days === 'number') ago = days < 0 ? '、日付が未来です' : `、${days}日前`;
      add(`手入力値が古くなっています：${m.label}（${md(m.as_of)}更新${ago}）`, true);
    }
  }
}

// ---------- chart ----------

const normalLabelPlugin = {
  id: 'normalLabel',
  afterDatasetsDraw(chart) {
    const normal = displayValue('normal_ratio');
    if (normal === null) return;
    const y = chart.scales.y.getPixelForValue(normal);
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.fillStyle = COLORS.tick;
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`普段 ${normal}%`, chartArea.right - 2, y - 3);
    ctx.restore();
  },
};

function windowEntries() {
  const n = state.entries.length;
  if (!n) return [];
  const last = state.entries[n - 1].date;
  const start = entryNear(state.entries, addDays(last, -state.days));
  const from = start ? start.date : addDays(last, -state.days);
  return state.entries.filter((e) => e.date >= from && e.areas && e.areas[state.area]);
}

function renderChart() {
  if (state.chart) { state.chart.destroy(); state.chart = null; }
  const noChart = typeof window.Chart === 'undefined';
  $('chart').hidden = noChart;
  $('chart-error').hidden = !noChart;
  if (noChart) return;
  const rows = windowEntries();
  const area = state.area;
  const labels = rows.map((e) => e.date);
  const values = rows.map((e) => e.areas[area].ratio);
  const marks = markEntries();

  const segColor = (ctx) => {
    const a = rows[ctx.p0DataIndex];
    const b = rows[ctx.p1DataIndex];
    if (a.areas[area].on_hold || b.areas[area].on_hold) return COLORS.lineHold;
    if (a.backfill || b.backfill) return COLORS.lineBackfill;
    return COLORS.line;
  };
  const segDash = (ctx) => {
    const a = rows[ctx.p0DataIndex];
    const b = rows[ctx.p1DataIndex];
    return a.backfill || b.backfill ? [4, 3] : undefined;
  };

  const datasets = [];
  MARKS.forEach((mk, i) => {
    const e = marks[mk.id];
    const idx = e ? rows.indexOf(e) : -1;
    if (idx < 0) return;
    const data = rows.map((_, j) => (j === idx ? values[idx] : null));
    datasets.push({
      label: mk.label,
      data,
      showLine: false,
      pointRadius: mk.id === 'today' ? 6 : 5,
      pointHoverRadius: mk.id === 'today' ? 6 : 5,
      pointBackgroundColor: mk.color,
      pointBorderColor: mk.color,
      order: MARKS.length - i,
    });
  });
  datasets.push({
    label: 'ratio',
    data: values,
    borderColor: COLORS.line,
    borderWidth: 2.5,
    pointRadius: 0,
    pointHoverRadius: 3,
    tension: 0,
    segment: { borderColor: segColor, borderDash: segDash },
    order: 10,
  });
  const normal = displayValue('normal_ratio');
  if (normal !== null) {
    datasets.push({
      label: 'normal',
      data: rows.map(() => normal),
      borderColor: COLORS.normal,
      borderWidth: 1,
      borderDash: [4, 3],
      pointRadius: 0,
      pointHoverRadius: 0,
      order: 11,
    });
  }
  const mainIndex = datasets.findIndex((d) => d.label === 'ratio');

  const shortRange = state.days <= 31;
  state.chart = new window.Chart($('chart'), {
    type: 'line',
    data: { labels, datasets },
    plugins: [normalLabelPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (item) => item.datasetIndex === mainIndex,
          callbacks: {
            title: (items) => (items.length ? md(labels[items[0].dataIndex]) : ''),
            label: (item) => {
              const e = rows[item.dataIndex];
              let s = `${item.parsed.y}%`;
              if (e.backfill) s += '（さかのぼり計算）';
              if (e.areas[area].on_hold) s += '（判定保留）';
              return s;
            },
          },
        },
      },
      scales: {
        y: {
          min: 0,
          max: 90,
          ticks: { stepSize: 30, color: COLORS.tick, font: { size: 11 }, callback: (v) => `${v}%` },
          grid: { color: COLORS.grid },
          border: { display: false },
        },
        x: {
          grid: { display: false },
          border: { color: COLORS.grid },
          ticks: {
            color: COLORS.tick,
            font: { size: 11 },
            autoSkip: false,
            maxRotation: 0,
            callback(value, index) {
              const d = labels[index];
              if (!d) return '';
              if (shortRange) return index % 7 === 0 ? md(d) : '';
              const prev = labels[index - 1];
              if (index === 0 || d.slice(0, 7) !== prev.slice(0, 7)) {
                return `${Number(d.slice(5, 7))}月`;
              }
              return '';
            },
          },
        },
      },
    },
  });
}

// ---------- tickers ----------

function renderTickers() {
  const box = $('tickers');
  box.replaceChildren();
  const list = (state.latest.tickers || []).filter((t) => t.area === state.area);
  if (!list.length) {
    box.appendChild(el('p', 'empty', 'この分野の銘柄はありません'));
    return;
  }
  for (const t of list) {
    const item = el('div', 'tk');
    const row = el('div', 'row');
    row.appendChild(el('b', '', t.name || t.symbol));
    row.appendChild(el('span', `v ${verdictClass(t.verdict)}`, t.verdict));
    item.appendChild(row);

    const unit = String(t.symbol).endsWith('.T') ? '円' : 'ドル';
    const price = t.price === null || t.price === undefined
      ? '価格 —'
      : `${fmtNum(t.price, t.price >= 1000 ? 0 : 2)}${unit}`;
    const drop = t.drop_pct === null || t.drop_pct === undefined
      ? '高値比 —'
      : `高値比 ${t.drop_pct > 0 ? '-' : ''}${fmtNum(t.drop_pct, 1)}%`;
    item.appendChild(el('div', 'px', `${price} ／ ${drop}`));

    // データなし is a fetch state, not a verdict (R19): no 前日→今日 line around it.
    const comparable = t.prev_verdict && t.prev_verdict !== NO_DATA && t.verdict !== NO_DATA;
    if (comparable && t.prev_verdict !== t.verdict) {
      item.appendChild(el('div', 'chg', `前日 ${t.prev_verdict} → 今日 ${t.verdict}`));
    }
    if (t.reason) item.appendChild(el('p', 'rs', t.reason));
    box.appendChild(item);
  }
}

// ---------- metric details ----------

function pointsOf(metricKey) {
  const areas = state.latest.areas;
  const order = [state.area, ...AREAS.map((a) => a.key).filter((k) => k !== state.area)];
  for (const ak of order) {
    const r = areas[ak];
    if (!r) continue;
    for (const c of r.contributions || []) {
      if ((METRIC_OF_KEY[c.key] || c.key) === metricKey) return { found: true, points: c.points };
    }
  }
  return { found: false, points: null };
}

function renderMetrics() {
  const tbody = $('metrics');
  tbody.replaceChildren();
  for (const [key, m] of Object.entries(state.latest.metrics || {})) {
    const tr = el('tr');
    tr.appendChild(el('td', '', m.label || key));

    const value = m.value === null || m.value === undefined ? '—' : `${fmtNum(m.value)}${m.unit || ''}`;
    tr.appendChild(el('td', '', value));

    const st = el('td');
    const overdue = m.status === 'manual' && m.extra && m.extra.overdue;
    const stText = (STATUS_LABEL[m.status] || m.status) + (overdue ? '（古い）' : '');
    st.appendChild(el('span', `st ${overdue ? 'warn' : m.status}`, stText));
    st.appendChild(el('span', 'dt', m.as_of || '—'));
    tr.appendChild(st);

    const p = pointsOf(key);
    let ptText = '—';
    if (p.found && p.points !== null && p.points !== undefined) {
      ptText = p.points > 0 ? `+${p.points}` : String(p.points);
    }
    tr.appendChild(el('td', '', ptText));
    tbody.appendChild(tr);
  }
}

// ---------- wiring ----------

function renderArea() {
  renderTabs();
  renderAreaHead();
  renderLegend();
  renderChart();
  renderNotes();
  renderTickers();
  renderMetrics();
}

function setupRanges() {
  const buttons = Array.from(document.querySelectorAll('#ranges button'));
  for (const b of buttons) {
    b.addEventListener('click', () => {
      state.days = Number(b.dataset.days);
      buttons.forEach((x) => x.classList.toggle('on', x === b));
      renderChart();
    });
  }
}

async function fetchJson(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function main() {
  const sample = new URLSearchParams(location.search).get('sample') === '1';
  const prefix = sample ? 'data/sample-' : 'data/';
  let latest;
  try {
    latest = await fetchJson(`${prefix}latest.json`);
    if (!latest || !latest.areas || !latest.metrics) throw new Error('unexpected shape');
  } catch (e) {
    $('updated').textContent = '';
    $('error').hidden = false;
    return;
  }
  let entries = [];
  try {
    const hist = await fetchJson(`${prefix}history.json`);
    entries = Array.isArray(hist && hist.entries) ? hist.entries.slice() : [];
    entries.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  } catch (e) {
    entries = [];
  }
  state.latest = latest;
  state.entries = entries;

  const saved = loadTab();
  const available = AREAS.filter((a) => latest.areas[a.key]).map((a) => a.key);
  state.area = available.includes(saved) ? saved : available[0];
  if (!state.area) {
    $('error').hidden = false;
    return;
  }

  renderHeader();
  setupRanges();
  $('app').hidden = false;
  renderArea();
}

main();
