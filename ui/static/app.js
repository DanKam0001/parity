/* ============================================================
   Parity UI — app.js
   Vanilla JS, no build step, no external JS libraries.
   ============================================================ */

'use strict';

// ── globals ─────────────────────────────────────────────────
const API = {
  map:     '/api/map',
  rules:   '/api/rules',
  source:  '/api/source',
  report:  '/api/report?seed=7&accounts=2000',
  prove:   (seed) => `/api/prove?seed=${seed}&accounts=2000`,
  mutants: '/api/mutants',
  confirm: '/api/confirm',
};

// Global data cache
let _sourceData = null;
let _reportData = null;
let _mutantsData = null;
let _mapData = null;

// ── helpers ──────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function codeLines(lines, startLine, highlightRange, specialFn) {
  // Returns an array of .code-line divs with line numbers
  const frag = document.createDocumentFragment();
  lines.forEach((txt, i) => {
    const lineNo = startLine + i;
    const row = el('div', 'code-line');
    const inRange = highlightRange && lineNo >= highlightRange[0] && lineNo <= highlightRange[1];
    if (inRange) row.classList.add('hl-line');
    const ln = el('span', 'code-ln', lineNo);
    const tc = el('span', 'code-text');
    if (specialFn) {
      tc.innerHTML = specialFn(txt);
    } else {
      tc.textContent = txt;
    }
    row.append(ln, tc);
    frag.appendChild(row);
  });
  return frag;
}

function highlightFaithful(line) {
  // Wrap FAITHFUL or MANUAL REVIEW in amber span
  return escapeHtml(line).replace(
    /(FAITHFUL|MANUAL REVIEW)/g,
    '<span class="hl-faithful">$1</span>'
  );
}

// ── Section 1: System Map ────────────────────────────────────
async function loadMap() {
  const container = document.getElementById('stat-tiles');
  const svgEl = document.getElementById('sysmap-svg');
  try {
    const data = await fetchJSON(API.map);
    _mapData = data;
    renderStatTiles(data, container);
    renderSysMap(data, svgEl);
  } catch(e) {
    container.innerHTML = `<p class="error-msg">Could not load system map: ${e.message}</p>`;
  }
}

function renderStatTiles(data, container) {
  const stats = data.stats || {};
  // Compute total COBOL lines from nodes
  const totalLines = (data.nodes || []).reduce((s, n) => s + (n.line_count || 0), 0);
  const items = [
    { label: 'Lines of COBOL', value: totalLines.toLocaleString() },
    { label: 'Programs', value: stats.programs ?? '—' },
    { label: 'Batch', value: stats.batch ?? '—' },
    { label: 'Online (CICS)', value: stats.online ?? '—' },
    { label: 'JCL Jobs', value: stats.jobs ?? '—' },
    { label: 'Datasets', value: stats.datasets ?? '—' },
  ];
  items.forEach(({ label, value }) => {
    const tile = el('div', 'stat-tile');
    tile.innerHTML = `<div class="st-value">${value}</div><div class="st-label">${label}</div>`;
    container.appendChild(tile);
  });
}

function renderSysMap(data, svgEl) {
  const nodes = data.nodes || [];
  const edges = data.edges || [];

  // Column layout: JOBS | BATCH | DATASETS | ONLINE
  const cols = {
    job:     { label: 'JOBS',           x: 0, nodes: [] },
    batch:   { label: 'BATCH PROGRAMS', x: 1, nodes: [] },
    dataset: { label: 'DATASETS',       x: 2, nodes: [] },
    online:  { label: 'ONLINE (CICS)',  x: 3, nodes: [] },
  };
  const typeToCol = { job: 'job', batch: 'batch', dataset: 'dataset', online: 'online' };

  nodes.forEach(n => {
    const col = typeToCol[n.type] || 'batch';
    cols[col].nodes.push(n);
  });

  const COL_W = 200;
  const NODE_H = 28;
  const NODE_W = 160;
  const COL_PAD_X = 20;
  const ROW_GAP = 10;
  const HEADER_H = 36;
  const PADDING = 16;
  const MIN_COL_H = 120;

  // Compute column heights
  let maxColNodes = 0;
  Object.values(cols).forEach(c => {
    if (c.nodes.length > maxColNodes) maxColNodes = c.nodes.length;
  });
  const svgH = Math.max(MIN_COL_H, HEADER_H + maxColNodes * (NODE_H + ROW_GAP) + PADDING * 2);
  const svgW = Object.keys(cols).length * COL_W + PADDING * 2;

  svgEl.setAttribute('viewBox', `0 0 ${svgW} ${svgH}`);
  svgEl.setAttribute('width', svgW);
  svgEl.setAttribute('height', svgH);
  svgEl.style.minHeight = svgH + 'px';

  const NS = 'http://www.w3.org/2000/svg';
  function svgEl2(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }

  // Map nodeId -> svg position (center)
  const nodePos = {};

  // Render columns
  Object.values(cols).forEach((col, ci) => {
    const cx = PADDING + ci * COL_W;
    // Column label
    const lbl = svgEl2('text', {
      x: cx + COL_W / 2,
      y: HEADER_H / 2 + 4,
      'text-anchor': 'middle',
      class: 'sysmap-col-label',
    });
    lbl.textContent = col.label;
    svgEl.appendChild(lbl);

    // Column background
    const colBg = svgEl2('rect', {
      x: cx,
      y: HEADER_H,
      width: COL_W,
      height: svgH - HEADER_H,
      fill: 'none',
      stroke: '#2a3040',
      'stroke-width': '1',
      rx: '4',
    });
    svgEl.appendChild(colBg);

    col.nodes.forEach((node, ni) => {
      const nx = cx + COL_PAD_X;
      const ny = HEADER_H + PADDING + ni * (NODE_H + ROW_GAP);
      const cx2 = nx + NODE_W / 2;
      const cy2 = ny + NODE_H / 2;
      nodePos[node.id] = { x: cx2, y: cy2, ex: nx + NODE_W, ey: ny + NODE_H / 2, sx: nx, sy: cy2 };

      const g = svgEl2('g', { class: `sysmap-node${node.id === 'pgm:CBACT04C' ? ' clickable' : ''}`, 'data-nid': node.id });

      const colors = {
        job:     { fill: '#1e2430', stroke: '#2a3040' },
        batch:   { fill: '#1e2a3a', stroke: '#2a3a50' },
        dataset: { fill: '#1a2a1a', stroke: '#2a3a2a' },
        online:  { fill: '#2a1e3a', stroke: '#3a2a50' },
      };
      const c = colors[node.type] || colors.batch;

      const rect = svgEl2('rect', {
        x: nx, y: ny,
        width: NODE_W, height: NODE_H,
        fill: c.fill, stroke: c.stroke, 'stroke-width': '1',
        rx: '4', ry: '4',
      });
      g.appendChild(rect);

      const txt = svgEl2('text', {
        x: cx2, y: cy2 + 4,
        'text-anchor': 'middle',
        class: 'sysmap-node',
      });
      txt.textContent = node.name || node.id;
      g.appendChild(txt);

      if (node.id === 'pgm:CBACT04C') {
        rect.setAttribute('stroke', '#4f9cf9');
        txt.setAttribute('fill', '#4f9cf9');
        g.addEventListener('click', () => {
          document.getElementById('s2').scrollIntoView({ behavior: 'smooth' });
        });
      }

      svgEl.appendChild(g);
    });
  });

  // Edges first (behind nodes)
  const edgeGroup = svgEl2('g', { class: 'edges' });
  svgEl.insertBefore(edgeGroup, svgEl.firstChild);

  edges.forEach((edge, i) => {
    const from = nodePos[edge.from];
    const to   = nodePos[edge.to];
    if (!from || !to) return;

    // Curved path
    const mx = (from.ex + to.sx) / 2;
    const path = svgEl2('path', {
      d: `M ${from.ex} ${from.ey} C ${mx} ${from.ey}, ${mx} ${to.sy}, ${to.sx} ${to.sy}`,
      class: 'sysmap-edge',
      'data-from': edge.from,
      'data-to': edge.to,
      'data-idx': i,
    });
    edgeGroup.appendChild(path);
  });

  // Hover interactions
  const allNodes = svgEl.querySelectorAll('.sysmap-node');
  const allEdges = svgEl.querySelectorAll('.sysmap-edge');

  function highlight(nodeId) {
    const connected = new Set([nodeId]);
    allEdges.forEach(e => {
      if (e.dataset.from === nodeId || e.dataset.to === nodeId) {
        connected.add(e.dataset.from);
        connected.add(e.dataset.to);
      }
    });
    allNodes.forEach(g => {
      const nid = g.dataset.nid;
      if (connected.has(nid)) {
        g.classList.remove('faded');
        g.classList.add('highlight');
      } else {
        g.classList.add('faded');
        g.classList.remove('highlight');
      }
    });
    allEdges.forEach(e => {
      if (e.dataset.from === nodeId || e.dataset.to === nodeId) {
        e.classList.add('highlight');
        e.classList.remove('faded');
      } else {
        e.classList.add('faded');
        e.classList.remove('highlight');
      }
    });
  }

  function clearHighlight() {
    allNodes.forEach(g => g.classList.remove('faded', 'highlight'));
    allEdges.forEach(e => e.classList.remove('faded', 'highlight'));
  }

  allNodes.forEach(g => {
    g.addEventListener('mouseenter', () => highlight(g.dataset.nid));
    g.addEventListener('mouseleave', clearHighlight);
  });

  // Expose trace for demo
  window.demo._trace = (nodeId) => {
    highlight(nodeId);
    setTimeout(clearHighlight, 2000);
  };
}

// ── Section 2: Business Rules ────────────────────────────────
async function loadRules() {
  const grid = document.getElementById('rules-grid');
  grid.innerHTML = '<p class="loading-msg">Loading rules…</p>';
  try {
    const data = await fetchJSON(API.rules);
    grid.innerHTML = '';
    (data.rules || []).forEach(rule => renderRuleCard(rule, grid));
  } catch(e) {
    grid.innerHTML = `<p class="error-msg">Could not load rules: ${e.message}</p>`;
  }
}

function renderRuleCard(rule, container) {
  const card = el('div', 'rule-card');
  card.dataset.id = rule.id;

  const kindClass = {
    calculation: 'badge-calc',
    update: 'badge-update',
    control: 'badge-control',
    output: 'badge-output',
    default: 'badge-default',
    lookup: 'badge-lookup',
    risk: 'badge-risk',
  }[rule.kind] || 'badge-calc';

  const hdr = el('div', 'rule-header');
  hdr.innerHTML = `<span class="rule-id">${escapeHtml(rule.id)}</span>
    <span class="rule-title">${escapeHtml(rule.title)}</span>`;

  const meta = el('div', 'rule-meta');
  meta.innerHTML = `<span class="badge ${kindClass}">${escapeHtml(rule.kind)}</span>`;
  if (rule.kind === 'risk') {
    meta.innerHTML += ` <span class="badge badge-risk">⚠ RISK</span>`;
  }

  const body = el('div', 'rule-body', rule.rule);

  card.append(hdr, meta, body);

  if (rule.verified && rule.lines) {
    const cite = el('div', 'rule-citation');
    cite.innerHTML = `<span>✓ citation checked</span>
      <span style="color:var(--muted)">CBACT04C.cbl lines ${rule.lines[0]}–${rule.lines[1]}</span>`;
    card.appendChild(cite);
  }

  // Code block (hidden until expanded)
  if (rule.code && rule.code.length > 0) {
    const codeBlock = el('div', 'rule-code-block');
    const pre = el('pre');
    const startLine = rule.lines ? rule.lines[0] : 1;
    rule.code.forEach((line, i) => {
      const row = el('div', 'rule-code-line');
      const ln = el('span', 'rule-code-ln', startLine + i);
      const txt = el('span', null, line);
      row.append(ln, txt);
      pre.appendChild(row);
    });
    codeBlock.appendChild(pre);
    card.appendChild(codeBlock);
  }

  card.addEventListener('click', () => {
    card.classList.toggle('expanded');
  });

  container.appendChild(card);
}

// ── Section 3: Translation Layer ────────────────────────────
async function loadSource() {
  const list = document.getElementById('translation-list');
  list.innerHTML = '<p class="loading-msg">Loading source…</p>';
  try {
    const data = await fetchJSON(API.source);
    _sourceData = data;
    renderTranslationList(data);
  } catch(e) {
    list.innerHTML = `<p class="error-msg">Could not load source: ${e.message}</p>`;
  }
}

function renderTranslationList(data) {
  const list = document.getElementById('translation-list');
  list.innerHTML = '';
  (data.links || []).forEach((link, i) => {
    const item = el('div', 'tl-item');
    item.dataset.idx = i;
    // Full method name, let it wrap; paragraphs on its own line below
    item.innerHTML = `<span class="tl-tick" id="tl-tick-${i}"> </span>
      <span class="tl-name" style="white-space:normal;word-break:break-word">${escapeHtml(link.method)}</span>
      <span class="tl-para">${escapeHtml((link.paragraphs || []).join(', '))}</span>`;
    item.addEventListener('click', () => showLink(i));
    list.appendChild(item);
  });
  // Auto-select first link
  if (data.links && data.links.length > 0) showLink(0);
}

function showLink(i) {
  if (!_sourceData) return;
  const data = _sourceData;
  const links = data.links || [];
  if (i < 0 || i >= links.length) return;

  const link = links[i];
  const panes = document.getElementById('translation-panes');
  panes.classList.remove('hidden');

  // Highlight active list item
  document.querySelectorAll('.tl-item').forEach((el, idx) => {
    el.classList.toggle('active', idx === i);
  });

  // COBOL pane: show first cobol range
  const cobolPre = document.getElementById('cobol-pane');
  cobolPre.innerHTML = '';
  if (link.cobol_ranges && link.cobol_ranges.length > 0) {
    const [cs, ce] = link.cobol_ranges[0];
    const slice = data.cobol.slice(cs - 1, ce);
    cobolPre.appendChild(codeLines(slice, cs, [cs, ce]));
    // Scroll first highlighted line into view
    requestAnimationFrame(() => {
      const hl = cobolPre.querySelector('.hl-line');
      if (hl) hl.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }

  // Java pane
  const javaPre = document.getElementById('java-pane');
  javaPre.innerHTML = '';
  if (link.java_start && link.java_end) {
    const [js, je] = [link.java_start, link.java_end];
    const slice = data.java.slice(js - 1, je);
    javaPre.appendChild(codeLines(slice, js, [js, je], highlightFaithful));
    requestAnimationFrame(() => {
      const hl = javaPre.querySelector('.hl-line');
      if (hl) hl.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }
}

// Convert all links animation
async function convertAll() {
  if (!_sourceData) return;
  const links = _sourceData.links || [];
  const btn = document.getElementById('btn-convert');
  const status = document.getElementById('convert-status');
  btn.disabled = true;
  status.textContent = `0 / ${links.length} mapped`;

  for (let i = 0; i < links.length; i++) {
    showLink(i);
    await new Promise(r => setTimeout(r, 800));
    const tick = document.getElementById(`tl-tick-${i}`);
    if (tick) tick.textContent = '✓';
    status.textContent = `${i + 1} / ${links.length} mapped`;
  }
  btn.disabled = false;
}

document.getElementById('btn-convert').addEventListener('click', convertAll);

// ── Section 4: Record Decoder ────────────────────────────────
async function loadDecoder() {
  const container = document.getElementById('decoder-container');
  container.innerHTML = '<p class="loading-msg">Loading…</p>';
  try {
    const data = await fetchJSON(API.report);
    _reportData = data;
    renderDecoder(data, container);
  } catch(e) {
    container.innerHTML = `<p class="error-msg">Could not load report: ${e.message}</p>`;
  }
}

function renderDecoder(report, container) {
  container.innerHTML = '';
  const edgeCases = report.edge_cases || [];
  const fallbackCase = edgeCases.find(ec => ec.tag === 'fallback');
  if (!fallbackCase || !fallbackCase.tcatbal_rows || !fallbackCase.tcatbal_rows.length) {
    container.innerHTML = '<p class="loading-msg">No fallback edge case found in report.</p>';
    return;
  }
  const row = fallbackCase.tcatbal_rows[0];
  const raw = row.raw || '';
  const decoded = row.decoded || {};

  // CVTRA01Y field layout (0-based start, exclusive end):
  // TRANCAT-ACCT-ID  0..10  len 11  PIC 9(11)
  // TRANCAT-TYPE-CD 11..12  len  2  PIC X(02)
  // TRANCAT-CD      13..16  len  4  PIC 9(04)
  // TRAN-CAT-BAL    17..27  len 11  PIC S9(09)V99
  const fields = [
    { name: 'ACCT-ID',      label: 'TRANCAT-ACCT-ID', start: 0,  len: 11, pic: 'PIC 9(11)' },
    { name: 'TYPE-CD',      label: 'TRANCAT-TYPE-CD', start: 11, len: 2,  pic: 'PIC X(02)' },
    { name: 'CAT-CD',       label: 'TRANCAT-CD',      start: 13, len: 4,  pic: 'PIC 9(04)' },
    { name: 'TRAN-CAT-BAL', label: 'TRAN-CAT-BAL',   start: 17, len: 11, pic: 'PIC S9(09)V99' },
  ];

  // Underline colours matching card top-border colours
  const fieldColors = ['#4f9cf9', '#a78bfa', '#22c55e', '#f59e0b'];

  // Build annotated raw string — each field span uses a coloured underline
  const rawDiv = el('div', 'decoder-raw');
  let html = '';
  let pos = 0;
  fields.forEach((f, fi) => {
    if (f.start > pos) {
      html += escapeHtml(raw.slice(pos, f.start));
    }
    const color = fieldColors[fi];
    html += `<span class="dec-field-${fi}" title="${escapeHtml(f.label)}" data-dfield="${fi}" style="border-bottom:2px solid ${color};padding-bottom:1px">${escapeHtml(raw.slice(f.start, f.start + f.len))}</span>`;
    pos = f.start + f.len;
  });
  if (pos < raw.length) html += escapeHtml(raw.slice(pos));
  rawDiv.innerHTML = html;

  // Overpunch note
  const note = el('div', 'decoder-note');
  note.textContent = 'The last character of TRAN-CAT-BAL uses COBOL overpunched sign encoding: the final digit is replaced by a special character that encodes both the digit and the sign (positive: {ABCDEFGHI for 0–9; negative: }JKLMNOPQR for 0–9). This allows signed decimal values to fit in a pure DISPLAY field with no extra sign byte.';
  container.append(rawDiv, note);

  // Field cards
  const fieldsDiv = el('div', 'decoder-fields');
  const decodedKeys = Object.keys(decoded);

  fields.forEach((f, fi) => {
    const card = el('div', `dec-card dec-color-${fi}`);
    card.dataset.dfield = fi;

    const rawText = raw.slice(f.start, f.start + f.len);
    // Find decoded value: exact label match first, then exact name, then prefix scan
    let decodedVal = decoded[f.label] ?? decoded[f.name] ?? null;
    if (decodedVal === null) {
      const k = decodedKeys.find(k =>
        k.toUpperCase() === f.label.toUpperCase() ||
        k.toUpperCase() === f.name.toUpperCase() ||
        k.toUpperCase().includes(f.name.toUpperCase())
      );
      decodedVal = k != null ? decoded[k] : '—';
    }

    card.innerHTML = `
      <div class="dec-card-name">${escapeHtml(f.label)}</div>
      <div class="dec-card-raw">"${escapeHtml(rawText)}"</div>
      <div class="dec-card-decoded">${escapeHtml(String(decodedVal))}</div>
      <div class="dec-card-pic">${escapeHtml(f.pic)}</div>
    `;

    // Hover cross-link
    card.addEventListener('mouseenter', () => {
      hiField(fi);
    });
    card.addEventListener('mouseleave', () => {
      document.querySelectorAll('.dec-field-0,.dec-field-1,.dec-field-2,.dec-field-3')
        .forEach(s => s.style.outline = '');
      document.querySelectorAll('.dec-card').forEach(c => c.classList.remove('hover'));
    });

    fieldsDiv.appendChild(card);
  });

  // Hover on raw spans
  rawDiv.querySelectorAll('[data-dfield]').forEach(span => {
    span.addEventListener('mouseenter', () => hiField(+span.dataset.dfield));
    span.addEventListener('mouseleave', () => {
      document.querySelectorAll('.dec-field-0,.dec-field-1,.dec-field-2,.dec-field-3')
        .forEach(s => s.style.outline = '');
      document.querySelectorAll('.dec-card').forEach(c => c.classList.remove('hover'));
    });
  });

  container.appendChild(fieldsDiv);
}

function hiField(fi) {
  const colors = ['#4f9cf9','#a78bfa','#22c55e','#f59e0b'];
  // Reset all underline opacities (we use outline for the hover glow, not border)
  for (let i = 0; i < 4; i++) {
    const s = document.querySelector(`.dec-field-${i}`);
    if (s) s.style.outline = '';
  }
  const span = document.querySelector(`.dec-field-${fi}`);
  if (span) span.style.outline = `2px solid ${colors[fi]}`;

  document.querySelectorAll('.dec-card').forEach(c => {
    c.classList.toggle('hover', +c.dataset.dfield === fi);
  });
}

// ── Section 5: Edge Cases ────────────────────────────────────
const EC_WHY = {
  negative:  'Account has a negative category balance — interest truncation toward zero must not flip the sign.',
  cent:      'Balance is so small that monthly interest rounds down to exactly ¢0.00 — a zero-amount transaction is still written.',
  fallback:  'Account group not found in DISCGRP — program falls back to the DEFAULT group key.',
  zero_rate: 'Disclosure group has rate = 0.00 — entire calculation is skipped; no transaction is written.',
  huge:      'Very large balance — verifies that 9-digit integer part does not overflow PIC S9(09)V99.',
  last:      'This is the last account in the file — COBOL\'s test-before loop exits without updating the account master (known bug, intentionally preserved).',
};

async function loadEdgeCases() {
  const grid = document.getElementById('edge-cases-grid');
  grid.innerHTML = '<p class="loading-msg">Loading…</p>';
  try {
    // Reuse cached report if available
    if (!_reportData) {
      _reportData = await fetchJSON(API.report);
    }
    if (!_mutantsData) {
      _mutantsData = await fetchJSON(API.mutants);
    }
    renderEdgeCases(_reportData, _mutantsData, grid);
  } catch(e) {
    grid.innerHTML = `<p class="error-msg">Could not load edge cases: ${e.message}</p>`;
  }
}

function renderEdgeCases(report, mutants, grid) {
  grid.innerHTML = '';
  const edgeCases = report.edge_cases || [];
  edgeCases.forEach(ec => {
    const card = renderEcCard(ec);
    grid.appendChild(card);
  });

  // Red CAUGHT card for "floats" mutant
  const floatsMutant = mutants.find(m => m.id === 'floats');
  if (floatsMutant) {
    const card = renderCaughtCard(floatsMutant);
    grid.appendChild(card);
  }
}

function renderEcCard(ec) {
  const card = el('div', 'ec-card');

  const hdr = el('div', 'ec-header');
  hdr.innerHTML = `<span class="ec-tag">${escapeHtml(ec.tag)}</span>
    <span class="ec-acct">acct ${ec.acct_id}</span>`;

  const why = el('div', 'ec-why', EC_WHY[ec.tag] || ec.tag);

  card.append(hdr, why);

  // TCAT-BAL values table
  if (ec.tcatbal_rows && ec.tcatbal_rows.length) {
    const tbl = el('table', 'ec-tcat-table');
    tbl.innerHTML = '<thead><tr><th>Type</th><th>Cat</th><th>Balance</th><th>Rate raw</th></tr></thead>';
    const tbody = el('tbody');
    ec.tcatbal_rows.forEach(row => {
      const d = row.decoded || {};
      const tr = el('tr');
      tr.innerHTML = `<td>${escapeHtml(d['TRANCAT-TYPE-CD'] || '—')}</td>
        <td>${escapeHtml(d['TRANCAT-CD'] || '—')}</td>
        <td>${escapeHtml(d['TRAN-CAT-BAL'] || '—')}</td>
        <td>${escapeHtml(row.rate_raw || '—')}</td>`;
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    card.appendChild(tbl);
  }

  // COBOL vs Java comparison
  const cobolDecoded = ec.acctfile_cobol_output?.decoded || {};
  const javaDecoded  = ec.acctfile_java_output?.decoded  || {};
  const cobolBal = cobolDecoded['ACCT-CURR-BAL'] ?? '—';
  const javaBal  = javaDecoded['ACCT-CURR-BAL']  ?? '—';

  const cmp = el('div', 'ec-compare');
  cmp.innerHTML = `
    <div class="ec-compare-col">
      <div class="ec-compare-label">COBOL wrote — ACCT-CURR-BAL</div>
      <div class="ec-compare-val">${escapeHtml(String(cobolBal))}</div>
    </div>
    <div class="ec-compare-col">
      <div class="ec-compare-label">Java wrote — ACCT-CURR-BAL</div>
      <div class="ec-compare-val">${escapeHtml(String(javaBal))}</div>
    </div>
  `;
  card.appendChild(cmp);

  // TRAN-AMT comparison
  const cobolTranAmts = (ec.transact_cobol || []).map(t => t.decoded?.['TRAN-AMT'] ?? '—');
  const javaTranAmts  = (ec.transact_java  || []).map(t => t.decoded?.['TRAN-AMT'] ?? '—');
  if (cobolTranAmts.length > 0 || javaTranAmts.length > 0) {
    const tranCmp = el('div', 'ec-compare');
    tranCmp.style.marginTop = '8px';
    tranCmp.innerHTML = `
      <div class="ec-compare-col">
        <div class="ec-compare-label">COBOL TRAN-AMT</div>
        <div class="ec-compare-val" style="font-size:12px">${escapeHtml(cobolTranAmts.join(', ') || '—')}</div>
      </div>
      <div class="ec-compare-col">
        <div class="ec-compare-label">Java TRAN-AMT</div>
        <div class="ec-compare-val" style="font-size:12px">${escapeHtml(javaTranAmts.join(', ') || '—')}</div>
      </div>
    `;
    card.appendChild(tranCmp);
  }

  // Identical check
  const balMatch = String(cobolBal) === String(javaBal);
  const tranMatch = JSON.stringify(cobolTranAmts) === JSON.stringify(javaTranAmts);
  if (balMatch && tranMatch) {
    const ident = el('div', 'ec-identical', '✓ IDENTICAL');
    if (ec.tag === 'last') {
      ident.textContent = '✓ IDENTICAL — FAITHFUL: Java intentionally keeps this COBOL bug';
      ident.style.fontSize = '12px';
    }
    card.appendChild(ident);
  }

  return card;
}

function renderCaughtCard(mutant) {
  const card = el('div', 'ec-card ec-caught');
  const hdr = el('div', 'ec-header');
  hdr.innerHTML = `<span class="ec-tag" style="color:var(--red);background:var(--red-dim)">mutant: ${escapeHtml(mutant.id)}</span>
    <span style="font-size:13px;font-weight:700;color:var(--red)">✗ CAUGHT</span>`;

  const desc = el('div', 'ec-why', mutant.description);

  card.append(hdr, desc);

  // First field difference
  if (mutant.fields && mutant.fields.length > 0) {
    const f = mutant.fields[0];
    const ex = f.example || {};
    const diff = el('div', 'ec-diff-field');
    diff.innerHTML = `
      <div class="df-label">${escapeHtml(f.field)} · ${f.mismatch_count} mismatches</div>
      <div class="df-cobol">COBOL: ${escapeHtml(String(ex.cobol_value))}</div>
      <div class="df-java">Java:  ${escapeHtml(String(ex.java_value))}</div>
    `;
    card.appendChild(diff);
  }

  return card;
}

// ── Section 6: Side by Side ──────────────────────────────────
// CVTRA05Y exact field layout (0-based start, length)
const TRANSACT_FIELDS = [
  { name: 'TRAN-ID',             start: 0,   len: 16  },
  { name: 'TRAN-TYPE-CD',        start: 16,  len: 2   },
  { name: 'TRAN-CAT-CD',         start: 18,  len: 4   },
  { name: 'TRAN-SOURCE',         start: 22,  len: 10  },
  { name: 'TRAN-DESC',           start: 32,  len: 100 },
  { name: 'TRAN-AMT',            start: 132, len: 11  },
  { name: 'TRAN-MERCHANT-ID',    start: 143, len: 9   },
  { name: 'TRAN-MERCHANT-NAME',  start: 152, len: 50  },
  { name: 'TRAN-MERCHANT-CITY',  start: 202, len: 50  },
  { name: 'TRAN-MERCHANT-ZIP',   start: 252, len: 10  },
  { name: 'TRAN-CARD-NUM',       start: 262, len: 16  },
  { name: 'TRAN-ORIG-TS',        start: 278, len: 26  },
  { name: 'TRAN-PROC-TS',        start: 304, len: 26  },
  { name: 'FILLER',              start: 330, len: 20  },
];

const TS_FIELD_NAMES = new Set(['TRAN-ORIG-TS', 'TRAN-PROC-TS']);

let _sbsEdgeCases = [];
let _sbsBugOn = false;

async function loadSideBySide() {
  const sel = document.getElementById('sbs-tx-select');
  try {
    if (!_reportData) {
      _reportData = await fetchJSON(API.report);
    }
    if (!_mutantsData) {
      _mutantsData = await fetchJSON(API.mutants);
    }

    // Collect transactions from edge cases
    _sbsEdgeCases = [];
    (_reportData.edge_cases || []).forEach(ec => {
      (ec.transact_cobol || []).forEach((tx, i) => {
        _sbsEdgeCases.push({
          label: `${ec.tag} · acct ${ec.acct_id} · tx ${i + 1}`,
          cobol_raw: tx.raw,
          cobol_decoded: tx.decoded || {},
          java_raw: (ec.transact_java?.[i])?.raw || tx.raw,
          java_decoded: (ec.transact_java?.[i])?.decoded || tx.decoded || {},
          tag: ec.tag,
        });
      });
    });

    sel.innerHTML = '';
    _sbsEdgeCases.forEach((tx, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = tx.label;
      sel.appendChild(opt);
    });

    if (_sbsEdgeCases.length > 0) renderSideBySide(0);

  } catch(e) {
    document.getElementById('sbs-chars').innerHTML =
      `<p class="error-msg">Could not load side-by-side: ${e.message}</p>`;
  }
}

// Overpunch encoding table (positive: digit 0-9 → {ABCDEFGHI; negative: }JKLMNOPQR)
const _POS_OVER = '{ABCDEFGHI';
const _NEG_OVER = '}JKLMNOPQR';
function encodeOverpunch(decimalStr) {
  // Takes a decimal string like "-8990.61" or "520.98" and encodes the last
  // digit as an overpunch character.  Returns an 11-char field (PIC S9(09)V99).
  const neg = decimalStr.startsWith('-');
  const digits = decimalStr.replace(/[^0-9]/g, '');  // strip sign and decimal point
  const padded = digits.padStart(11, '0');            // 9 integer + 2 fractional = 11
  const last = +padded[10];
  const overpunch = neg ? _NEG_OVER[last] : _POS_OVER[last];
  return padded.slice(0, 10) + overpunch;
}

// Returns the "rounding" mutant's TRAN-AMT example, or null
function getRoundingMutantExample() {
  if (!_mutantsData) return null;
  const m = _mutantsData.find(m => m.id === 'rounding');
  if (!m) return null;
  const f = (m.fields || []).find(f => f.field === 'TRAN-AMT');
  return f ? f.example : null;
}

function renderSideBySide(idx) {
  if (!_sbsEdgeCases[idx]) return;
  const tx = _sbsEdgeCases[idx];

  // TS byte ranges
  const tsRanges = TRANSACT_FIELDS
    .filter(f => TS_FIELD_NAMES.has(f.name))
    .map(f => [f.start, f.start + f.len - 1]);
  function isTs(pos) { return tsRanges.some(([s,e]) => pos >= s && pos <= e); }

  // Field boundary positions for thin separators
  const fieldBoundaries = new Set();
  TRANSACT_FIELDS.forEach(f => {
    fieldBoundaries.add(f.start);
    fieldBoundaries.add(f.start + f.len);
  });

  function buildCharRow(label, cobolRaw, javaRaw) {
    // Renders one labelled row of per-character spans, horizontally scrollable
    let cRaw = cobolRaw; let jRaw = javaRaw;
    const maxLen = Math.max(cRaw.length, jRaw.length);
    while (cRaw.length < maxLen) cRaw += ' ';
    while (jRaw.length  < maxLen) jRaw  += ' ';

    const row = el('div', 'sbs-row');
    const lbl = el('div', 'sbs-row-label', label);
    const code = document.createElement('code');
    code.style.cssText = 'font-family:var(--mono);font-size:12px;white-space:pre;display:inline';

    const raw = label === 'COBOL' ? cRaw : jRaw;
    for (let i = 0; i < raw.length; i++) {
      const ch = raw[i];
      if (fieldBoundaries.has(i) && i > 0) {
        const sep = document.createElement('span');
        sep.style.cssText = 'border-left:1px solid #2a3040';
        code.appendChild(sep);
      }
      const span = document.createElement('span');
      span.textContent = ch === ' ' ? '\u00b7' : ch;
      span.title = `pos ${i}`;
      const same = cRaw[i] === jRaw[i];
      const ts   = isTs(i);
      if (ts)        span.style.color = 'var(--amber)';
      else if (same) span.style.color = 'var(--green)';
      else           span.style.color = 'var(--red)';
      if (ch === ' ') span.style.opacity = '0.35';
      code.appendChild(span);
    }
    row.append(lbl, code);
    return row;
  }

  const charsDiv = document.getElementById('sbs-chars');
  charsDiv.innerHTML = '';

  charsDiv.appendChild(buildCharRow('COBOL', tx.cobol_raw || '', tx.java_raw || ''));
  charsDiv.appendChild(buildCharRow('Java',  tx.cobol_raw || '', tx.java_raw || ''));

  renderSbsTable(tx);
}

// Render the planted-bug view from the rounding mutant's own TRAN-AMT example.
// Shows only the two encoded 11-char fields; all other data is from the mutant JSON.
function renderBugView() {
  const bugEx = getRoundingMutantExample();
  const charsDiv = document.getElementById('sbs-chars');
  const tbl      = document.getElementById('sbs-field-table');
  charsDiv.innerHTML = '';
  tbl.innerHTML = '';

  if (!bugEx) {
    charsDiv.innerHTML = '<p class="error-msg">Rounding mutant TRAN-AMT example not found.</p>';
    return;
  }

  // Label
  const info = el('div', null);
  info.style.cssText = 'font-size:12px;color:var(--muted);margin-bottom:10px;font-family:var(--mono)';
  info.textContent = `planted bug: rounding · transaction ${bugEx.key}`;
  charsDiv.appendChild(info);

  // Encode both values as 11-char overpunched fields
  const cobolEncoded = encodeOverpunch(String(bugEx.cobol_value));
  const javaEncoded  = encodeOverpunch(String(bugEx.java_value));

  // Build two labelled rows showing only the TRAN-AMT field characters
  ['COBOL', 'Java'].forEach(side => {
    const encoded = side === 'COBOL' ? cobolEncoded : javaEncoded;
    const row = el('div', 'sbs-row');
    const lbl = el('div', 'sbs-row-label', side);
    const code = document.createElement('code');
    code.style.cssText = 'font-family:var(--mono);font-size:14px;white-space:pre;display:inline;letter-spacing:0.1em';

    for (let i = 0; i < encoded.length; i++) {
      const ch = encoded[i];
      const same = cobolEncoded[i] === javaEncoded[i];
      const span = document.createElement('span');
      span.textContent = ch;
      span.title = `pos ${i}`;
      span.style.color = same ? 'var(--green)' : 'var(--red)';
      if (!same) span.style.fontWeight = '700';
      code.appendChild(span);
    }
    row.append(lbl, code);
    charsDiv.appendChild(row);
  });

  // Small decoded label below each row
  const dec = el('div', null);
  dec.style.cssText = 'font-size:12px;margin-top:6px;font-family:var(--mono)';
  dec.innerHTML =
    `<span style="color:var(--green)">COBOL: ${escapeHtml(String(bugEx.cobol_value))}</span>` +
    `&nbsp;&nbsp;` +
    `<span style="color:var(--red)">Java (mutant): ${escapeHtml(String(bugEx.java_value))}</span>`;
  charsDiv.appendChild(dec);

  // Field table — one row for TRAN-AMT only
  const thead = el('thead');
  thead.innerHTML = '<tr><th>Field</th><th>COBOL</th><th>Java (mutant)</th><th></th></tr>';
  tbl.appendChild(thead);
  const tbody = el('tbody');
  const tr = el('tr');
  tr.innerHTML = `
    <td class="td-field">TRAN-AMT</td>
    <td class="td-same">${escapeHtml(String(bugEx.cobol_value))}</td>
    <td class="td-diff">${escapeHtml(String(bugEx.java_value))}</td>
    <td><span class="td-neq">≠ DIFFERENT</span></td>
  `;
  tbody.appendChild(tr);
  tbl.appendChild(tbody);
}

function renderSbsTable(tx) {
  const tbl = document.getElementById('sbs-field-table');
  tbl.innerHTML = '';
  const thead = el('thead');
  thead.innerHTML = '<tr><th>Field</th><th>COBOL</th><th>Java</th><th></th></tr>';
  tbl.appendChild(thead);
  const tbody = el('tbody');

  const cd = tx.cobol_decoded || {};
  const jd = tx.java_decoded  || {};

  TRANSACT_FIELDS.forEach(f => {
    if (f.name === 'FILLER') return;
    const ts = TS_FIELD_NAMES.has(f.name);

    const rawC = (tx.cobol_raw || '').slice(f.start, f.start + f.len);
    const rawJ = (tx.java_raw  || '').slice(f.start, f.start + f.len);
    const cv = cd[f.name] !== undefined ? String(cd[f.name]) : rawC.trim();
    const jv = jd[f.name] !== undefined ? String(jd[f.name]) : rawJ.trim();
    const same = cv === jv;

    const tr = el('tr');
    let statusHtml, cvClass, jvClass;

    if (ts) {
      statusHtml = `<span class="td-ts">clock · format ✓</span>`;
      cvClass = 'td-ts'; jvClass = 'td-ts';
    } else if (same) {
      statusHtml = `<span class="td-eq">=</span>`;
      cvClass = 'td-same'; jvClass = 'td-same';
    } else {
      statusHtml = `<span class="td-neq">≠ DIFFERENT</span>`;
      cvClass = 'td-diff'; jvClass = 'td-diff';
    }

    tr.innerHTML = `
      <td class="td-field">${escapeHtml(f.name)}</td>
      <td class="${cvClass}">${escapeHtml(cv)}</td>
      <td class="${jvClass}">${escapeHtml(jv)}</td>
      <td>${statusHtml}</td>
    `;
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
}

document.getElementById('sbs-tx-select').addEventListener('change', e => {
  if (!_sbsBugOn) renderSideBySide(+e.target.value);
});
document.getElementById('sbs-bug-toggle').addEventListener('change', e => {
  _sbsBugOn = e.target.checked;
  const sel = document.getElementById('sbs-tx-select');
  sel.style.visibility = _sbsBugOn ? 'hidden' : '';
  if (_sbsBugOn) {
    renderBugView();
  } else {
    renderSideBySide(+sel.value);
  }
});

// ── Section 7: The Proof ─────────────────────────────────────
async function loadProof() {
  try {
    if (!_reportData) {
      _reportData = await fetchJSON(API.report);
    }
    const confirm = await fetchJSON(API.confirm);
    renderProof(_reportData, confirm);
  } catch(e) {
    document.getElementById('proof-summary').innerHTML =
      `<p class="error-msg">Could not load proof: ${e.message}</p>`;
  }
}

function renderProof(report, confirm) {
  const acct = report.acctfile || {};
  const tran = report.transact || {};

  // Big count
  const totalMatched = (acct.matched || 0) + (tran.matched || 0);
  const totalCount   = (acct.cobol_count || 0) + (tran.cobol_count || 0);

  const summary = document.getElementById('proof-summary');
  summary.innerHTML = `
    <div class="proof-big">${totalMatched.toLocaleString()} / ${totalCount.toLocaleString()} output records identical</div>
    <div class="proof-note">Clock fields (TRAN-ORIG-TS, TRAN-PROC-TS) are format-checked, not byte-compared — timestamps are wall-clock values written at runtime and will always differ.</div>
  `;

  // Meters
  const meters = document.getElementById('proof-meters');
  meters.innerHTML = '';
  [
    { name: 'ACCTFILE', matched: acct.matched || 0, total: acct.cobol_count || 0 },
    { name: 'TRANSACT', matched: tran.matched || 0, total: tran.cobol_count || 0 },
  ].forEach(({ name, matched, total }) => {
    const pct = total > 0 ? (matched / total * 100) : 0;
    const row = el('div', 'proof-meter-row');
    row.innerHTML = `
      <div class="proof-meter-label">
        <span>${name}</span>
        <span>${matched.toLocaleString()} / ${total.toLocaleString()} (${pct.toFixed(1)}%)</span>
      </div>
      <div class="proof-meter-bar">
        <div class="proof-meter-fill" style="width:0%" data-pct="${pct}"></div>
      </div>
    `;
    meters.appendChild(row);
  });
  // Animate meters
  requestAnimationFrame(() => {
    meters.querySelectorAll('.proof-meter-fill').forEach(fill => {
      fill.style.width = fill.dataset.pct + '%';
    });
  });

  // Confirm seeds
  const seedsDiv = document.getElementById('confirm-seeds');
  seedsDiv.innerHTML = '';
  const seedLabel = el('p', null);
  seedLabel.style.cssText = 'font-size:13px;color:var(--muted);margin-bottom:10px';
  seedLabel.textContent = 'Fresh seeds (never used during development):';
  seedsDiv.appendChild(seedLabel);
  (confirm || []).forEach(c => {
    const chip = el('div', 'confirm-chip');
    chip.innerHTML = `<span class="cc-seed">seed=${c.seed}</span>
      <span class="cc-verdict"> · ${escapeHtml(c.verdict)}</span>`;
    seedsDiv.appendChild(chip);
  });
}

async function runProof(seed) {
  const log = document.getElementById('prove-log');
  log.classList.remove('hidden');
  log.innerHTML = '';

  function appendLog(msg, cls) {
    const line = el('span', `log-line ${cls || ''}`, msg);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  appendLog(`[0.0s] Starting proof · seed=${seed} · accounts=2000`);
  const t0 = Date.now();
  const ticker = setInterval(() => {
    appendLog(`[${((Date.now() - t0) / 1000).toFixed(1)}s] running…`);
  }, 2000);

  try {
    const resp = await fetch(API.prove(seed), { method: 'POST' });
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    const r = await resp.json();
    clearInterval(ticker);
    appendLog(`[${((Date.now() - t0) / 1000).toFixed(1)}s] Done.`);
    appendLog(`Passed: ${r.passed}`, r.passed ? 'log-ok' : 'log-err');
    if (r.verdict) appendLog(r.verdict, r.passed ? 'log-ok' : 'log-err');
    // Reload report + confirm seeds and update proof section
    try {
      const [newReport, newConfirm] = await Promise.all([
        fetchJSON(`/api/report?seed=${seed}&accounts=2000`),
        fetchJSON(API.confirm),
      ]);
      _reportData = newReport;
      renderProof(newReport, newConfirm);
    } catch(_) {}
  } catch(e) {
    clearInterval(ticker);
    appendLog(`Error: ${e.message}`, 'log-err');
  }
}

document.getElementById('btn-run-proof').addEventListener('click', () => {
  const seed = +document.getElementById('prove-seed').value || 99;
  runProof(seed);
});

// ── Section 8: Planted Bugs ──────────────────────────────────
async function loadMutants() {
  const hdr = document.getElementById('mutants-header');
  const grid = document.getElementById('mutants-grid');
  grid.innerHTML = '<p class="loading-msg">Loading mutants…</p>';
  try {
    if (!_mutantsData) {
      _mutantsData = await fetchJSON(API.mutants);
    }
    renderMutants(_mutantsData, hdr, grid);
  } catch(e) {
    grid.innerHTML = `<p class="error-msg">Could not load mutants: ${e.message}</p>`;
  }
}

function renderMutants(mutants, hdr, grid) {
  const caught = mutants.filter(m => m.caught).length;
  hdr.textContent = `${caught} / ${mutants.length} caught`;

  grid.innerHTML = '';
  mutants.forEach(m => {
    const card = el('div', `mutant-card ${m.caught ? 'caught' : 'missed'}`);

    const mhdr = el('div', 'mutant-header');
    mhdr.innerHTML = `
      <span class="mutant-id">${escapeHtml(m.id)}</span>
      <span class="mutant-verdict-badge ${m.caught ? 'caught' : 'missed'}">${m.caught ? 'CAUGHT' : 'MISSED'}</span>
    `;

    const desc = el('div', 'mutant-desc', m.description);
    const vline = el('div', 'mutant-verdict-line', m.verdict || '');

    card.append(mhdr, desc, vline);

    // First differing field
    if (m.fields && m.fields.length > 0) {
      const f = m.fields[0];
      const ex = f.example || {};
      const fd = el('div', 'mutant-field');
      fd.innerHTML = `
        <div class="mf-label">${escapeHtml(f.field)} · ${f.mismatch_count} mismatch${f.mismatch_count !== 1 ? 'es' : ''}</div>
        <div class="mf-cobol">COBOL: ${escapeHtml(String(ex.cobol_value ?? '—'))}</div>
        <div class="mf-java">Java:  ${escapeHtml(String(ex.java_value ?? '—'))}</div>
      `;
      card.appendChild(fd);
    }

    grid.appendChild(card);
  });
}

// ── demo API ─────────────────────────────────────────────────
const cursor = document.getElementById('demo-cursor');

function cursorTo(selector, offsetX = 0, offsetY = 0) {
  const target = document.querySelector(selector);
  if (!target) return;
  cursor.style.display = 'block';
  const rect = target.getBoundingClientRect();
  cursor.style.left = (rect.left + rect.width / 2 + offsetX + window.scrollX) + 'px';
  cursor.style.top  = (rect.top  + rect.height / 2 + offsetY + window.scrollY) + 'px';
}

function scrollTo(selector, block = 'start') {
  const target = document.querySelector(selector);
  if (target) target.scrollIntoView({ behavior: 'smooth', block });
}

function glow(selector) {
  const target = document.querySelector(selector);
  if (!target) return;
  target.style.transition = 'box-shadow 0.3s';
  target.style.boxShadow = '0 0 0 3px var(--accent)';
  setTimeout(() => { target.style.boxShadow = ''; }, 1500);
}

async function runScript(steps) {
  for (const [seconds, fn] of steps) {
    await new Promise(r => setTimeout(r, seconds * 1000));
    fn();
  }
}

function pickTx(i) {
  const sel = document.getElementById('sbs-tx-select');
  if (sel.options[i]) {
    sel.value = i;
    sel.dispatchEvent(new Event('change'));
  }
}

function mutantBug(on) {
  const chk = document.getElementById('sbs-bug-toggle');
  chk.checked = !!on;
  chk.dispatchEvent(new Event('change'));
}

window.demo = {
  convert:     () => convertAll(),
  showLink:    (i) => showLink(i),
  hiField:     (i) => hiField(i),
  trace:       (nodeId) => window.demo._trace && window.demo._trace(nodeId),
  glow:        glow,
  cursorTo:    cursorTo,
  scroll:      scrollTo,
  pickTx:      pickTx,
  mutant:      mutantBug,
  runProof:    (seed) => runProof(seed),
  run:         runScript,
  _trace:      null,
};

// ── Bootstrap ────────────────────────────────────────────────
async function init() {
  // Load all sections in parallel where possible
  loadMap();
  loadRules();
  loadSource();

  // Sections 4–8 all depend on /api/report and /api/mutants
  try {
    const [report, mutants] = await Promise.all([
      fetchJSON(API.report),
      fetchJSON(API.mutants),
    ]);
    _reportData = report;
    _mutantsData = mutants;

    renderDecoder(report, document.getElementById('decoder-container'));
    renderEdgeCases(report, mutants, document.getElementById('edge-cases-grid'));

    const confirm = await fetchJSON(API.confirm);
    renderProof(report, confirm);
    renderMutants(mutants, document.getElementById('mutants-header'), document.getElementById('mutants-grid'));

    // Side-by-side
    await loadSideBySide();
  } catch(e) {
    console.error('Failed to load report/mutants:', e);
    ['decoder-container', 'edge-cases-grid', 'proof-summary', 'mutants-grid'].forEach(id => {
      const el2 = document.getElementById(id);
      if (el2 && !el2.innerHTML.trim()) {
        el2.innerHTML = `<p class="error-msg">Data unavailable: ${e.message}</p>`;
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', init);
