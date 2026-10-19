/* BuoyUp seller charts: inline SVG, following cathrynlavery/diagram-design's chart rules.
 * One accent (the focal series / bar / bridge), everything else muted; faint gridlines, a zero baseline,
 * honest polylines (no smoothing), no shadows or 3-D. Colours come from CSS tokens through classes
 * (.ch-*), so light and dark themes both work. Drawing functions stay pure: data in, SVG string out.
 * Each mark sits in a focusable <g class="ch-item"> carrying its tooltip data (data-label, data-rows JSON,
 * data-ax/ay anchor); BU.charts.attach(slot) adds hover/touch/keyboard highlight, the tooltip and the
 * "fairy dust" trail (canvas, off under prefers-reduced-motion). */
(function () {
  'use strict';
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Charts are drawn at the card's real pixel width (``width``), so 1 SVG unit = 1 CSS px and labels keep their size.
  let W = 640;
  const M = {l: 64, r: 20, t: 30, b: 40};
  const setW = w => { W = Math.max(280, Math.round(w || 640)); };
  const fitH = (h, d) => Math.max(140, Math.round(h || d));
  // "Nice" axis maximum and 4–5 ticks from zero.
  function scale(max, parts = 4) {
    if (!(max > 0)) return {max: 1, ticks: [0, 1]};
    const raw = max / parts, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    // Ticks are printed as whole numbers: a tiny maximum (a few tệ) must not give 0 · 0 · 1 · 1 · 1.
    const step = Math.max(1, [1, 2, 2.5, 5, 10].map(s => s * mag).find(s => s >= raw));
    const top = Math.ceil(max / step) * step, ticks = [];
    for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v);
    return {max: top, ticks};
  }
  // 12.300 → "12,3 N", 1.250.000 → "1,25 Tr"
  function short(v) {
    const a = Math.abs(v), s = v < 0 ? '−' : '';
    const f = (n, d) => n.toLocaleString('vi-VN', {maximumFractionDigits: d});
    if (a >= 1e6) return s + f(a / 1e6, 2) + ' Tr';
    if (a >= 1e3) return s + f(a / 1e3, 1) + ' N';
    return s + f(a, 0);
  }
  // Tooltip value in full ("166.700"); callers pass ``fmt`` (e.g. v => money(v, 'CNY') → "166.700 tệ").
  const full = v => (v < 0 ? '−' : '') + Math.abs(Number(v) || 0).toLocaleString('vi-VN', {maximumFractionDigits: 2});
  const fmtOf = fmt => v => { try { return typeof fmt === 'function' ? String(fmt(v)) : full(v); } catch (_) { return full(v); } };
  function frame(h, sc, y) {
    const out = [];
    for (const t of sc.ticks) {
      const yy = y(t);
      out.push(`<line class="ch-grid" x1="${M.l}" x2="${W - M.r}" y1="${yy}" y2="${yy}"/>`,
               `<text class="ch-tick" x="${M.l - 8}" y="${yy + 4}" text-anchor="end">${esc(short(t))}</text>`);
    }
    out.push(`<line class="ch-axis" x1="${M.l}" x2="${W - M.r}" y1="${y(0)}" y2="${y(0)}"/>`);
    return out.join('');
  }
  const svg = (h, label, body) => `<svg class="ch" viewBox="0 0 ${W} ${h}" role="group" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet">${body}</svg>`;
  /** One interactive mark. rows: [{n: series name, t: formatted value, k: colour key, x?: extra}]. */
  function item(label, rows, ax, ay, inner) {
    const aria = label + ': ' + rows.map(r => `${r.n} ${r.t}${r.x ? ' (' + r.x + ')' : ''}`).join('; ');
    return `<g class="ch-item" tabindex="0" role="img" aria-label="${esc(aria)}" data-label="${esc(label)}" data-rows="${esc(JSON.stringify(rows))}" data-ax="${ax.toFixed(1)}" data-ay="${ay.toFixed(1)}">${inner}</g>`;
  }
  const hit = (x, y, w, h) => `<rect class="ch-hit" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, w).toFixed(1)}" height="${Math.max(1, h).toFixed(1)}"/>`;
  /** One x label per column (18/10/2026): every label is kept. A label may carry a second line after "\n"
   *  (e.g. the year under January), drawn smaller. When the first lines do not fit the column pitch (a narrow
   *  phone) the labels are slanted instead ("1/26"), and the chart keeps a taller bottom margin for them. */
  function xAxis(labels, pitch) {
    const parts = labels.map(l => String(l == null ? '' : l).split('\n'));
    const longest = Math.max(1, ...parts.map(p => p[0].length));
    const rot = longest * 7 + 4 > pitch, two = !rot && parts.some(p => p.length > 1);
    return {rot, b: rot ? 50 : two ? 52 : M.b,
      text: (l, x, h) => {
        const p = String(l == null ? '' : l).split('\n'), xx = x.toFixed(1);
        if (rot) {
          const t = p[0] + (p[1] ? '/' + p[1].slice(-2) : ''), yy = h - 50 + 15;
          return `<text class="ch-xlab ch-xlab-rot" x="${xx}" y="${yy}" text-anchor="end" transform="rotate(-40 ${xx} ${yy})">${esc(t)}</text>`;
        }
        if (p.length > 1) return `<text class="ch-xlab" x="${xx}" y="${h - 30}" text-anchor="middle">${esc(p[0])}<tspan class="ch-xlab-sub" x="${xx}" dy="15">${esc(p[1])}</tspan></text>`;
        return `<text class="ch-xlab" x="${xx}" y="${two ? h - 30 : h - 14}" text-anchor="middle">${esc(p[0])}</text>`;
      }};
  }
  const extraRows = (more, i) => ((more && more[i]) || []).filter(Boolean).map(r => ({n: r.n, t: r.t, k: r.k || 'note', x: r.x || ''}));

  /** Line chart. series: [{name, values:[n], focal?}], labels: x labels; annotate: index to label on the focal series.
   *  Optional: tips (tooltip label per point, defaults to labels), fmt (full value formatter). */
  function line({labels, series, height = 280, label = '', annotate = null, area = true, width, tips, fmt, xTicks, marks, more}) {
    setW(width);
    const h = fitH(height, 280), n = labels.length, max = Math.max(1, ...series.flatMap(s => s.values.filter(v => v != null)));
    const ph = h - M.t - M.b, sc = scale(max, ph < 140 ? 2 : ph < 200 ? 3 : 4), pw = W - M.l - M.r, F = fmtOf(fmt);
    const x = i => M.l + (n === 1 ? pw / 2 : (pw * i) / (n - 1)), y = v => M.t + ph - (ph * v) / sc.max;
    const body = [frame(h, sc, y)];
    const every = Math.ceil(n / Math.max(3, Math.floor((W - M.l - M.r) / 64)));
    const ticked = Array.isArray(xTicks) ? new Set(xTicks) : null;
    labels.forEach((l, i) => { if (ticked ? ticked.has(i) : ((i % every === 0 && (i === n - 1 || n - 1 - i >= Math.max(1, every * 0.75))) || i === n - 1)) body.push(`<text class="ch-xlab" x="${x(i)}" y="${h - 14}" text-anchor="middle">${esc(l)}</text>`); });
    // Thin vertical markers (e.g. a due date): a dashed line across the plot and a short label above it.
    (marks || []).forEach(m => {
      if (m == null || m.i == null || m.i < 0 || m.i >= n) return;
      const mx = x(m.i), right = mx > W - 90;
      body.push(`<line class="ch-due" x1="${mx.toFixed(1)}" x2="${mx.toFixed(1)}" y1="${M.t - 2}" y2="${(M.t + ph).toFixed(1)}"/>`);
      if (m.label) body.push(`<text class="ch-due-label" x="${(right ? mx - 4 : mx + 4).toFixed(1)}" y="${M.t - 8}" text-anchor="${right ? 'end' : 'start'}">${esc(m.label)}</text>`);
    });
    const order = series.map((s, j) => ({s, j})).sort((a, b) => (a.s.focal ? 1 : 0) - (b.s.focal ? 1 : 0));
    for (const {s, j} of order) {
      const pts = s.values.map((v, i) => v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean);
      if (!pts.length) continue;
      if (s.focal && area && pts.length > 1) {
        const first = s.values.findIndex(v => v != null), last = s.values.length - 1 - [...s.values].reverse().findIndex(v => v != null);
        body.push(`<polygon class="ch-area" data-s="${j}" points="${x(first)},${y(0)} ${pts.join(' ')} ${x(last)},${y(0)}"/>`);
      }
      body.push(`<polyline class="${s.focal ? 'ch-line-focal' : 'ch-line'}" data-s="${j}" points="${pts.join(' ')}"/>`);
      if (s.focal) s.values.forEach((v, i) => { if (v != null) body.push(`<circle class="ch-dot" data-s="${j}" cx="${x(i)}" cy="${y(v)}" r="3.5"/>`); });
    }
    const f = series.find(s => s.focal);
    if (f && annotate != null && f.values[annotate] != null) {
      const ax = x(annotate), ay = y(f.values[annotate]), right = ax > W - 150;
      body.push(`<line class="ch-lead" x1="${ax}" y1="${ay - 6}" x2="${ax}" y2="${Math.max(M.t, ay - 26)}"/>`,
                `<text class="ch-note" x="${right ? ax - 6 : ax + 6}" y="${Math.max(M.t + 10, ay - 28)}" text-anchor="${right ? 'end' : 'start'}">${esc(short(f.values[annotate]))}</text>`);
    }
    // Hover columns: each point owns the strip halfway to its neighbours, so the guide snaps to the nearest point.
    const items = [];
    for (let i = 0; i < n; i++) {
      const rows = series.map((s, j) => s.values[i] == null ? null : {n: s.name || 'Giá trị', t: F(s.values[i]), k: s.focal ? 'focal' : 'muted', s: j, y: +y(s.values[i]).toFixed(1)}).filter(Boolean);
      if (!rows.length) continue;
      const tipRows = rows.concat(extraRows(more, i));
      const l = n === 1 ? M.l : i === 0 ? M.l : (x(i - 1) + x(i)) / 2, r = n === 1 ? W - M.r : i === n - 1 ? W - M.r : (x(i) + x(i + 1)) / 2;
      const top = Math.min(...rows.map(o => o.y));
      items.push(item((tips && tips[i]) || labels[i] || '', tipRows, x(i), top,
        hit(l, M.t - 10, r - l, ph + 10) + `<line class="ch-guide" x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${M.t - 4}" y2="${(M.t + ph).toFixed(1)}"/>` +
        rows.map(o => `<circle class="ch-hot k-${o.k}" data-s="${o.s}" cx="${x(i).toFixed(1)}" cy="${o.y}" r="5.5"/>`).join('')));
    }
    body.push(`<g class="ch-items">${items.join('')}</g>`);
    return svg(h, label, body.join(''));
  }

  const KIND_NAME = {next: 'Kỳ tới', done: 'Đã trả', todo: 'Sắp tới'};
  /** Column chart. bars: [{label, value, kind?: 'done'|'next'|'todo'}]; the 'next' bar is the focal one. Optional: name, fmt. */
  function bars({bars, height = 260, label = '', width, name = 'Giá trị', fmt}) {
    setW(width);
    const h = fitH(height, 260), n = bars.length, ph = h - M.t - M.b, sc = scale(Math.max(1, ...bars.map(b => b.value)), ph < 140 ? 2 : ph < 200 ? 3 : 4), pw = W - M.l - M.r, F = fmtOf(fmt);
    const pitch = pw / Math.max(n, 1), bw = Math.max(8, Math.min(56, pitch * 0.62)), y = v => M.t + ph - (ph * v) / sc.max;
    const body = [frame(h, sc, y)];
    bars.forEach((b, i) => {
      const cx = M.l + pitch * i + pitch / 2, top = y(b.value), cls = b.kind === 'next' ? 'ch-bar-focal' : b.kind === 'done' ? 'ch-bar-done' : 'ch-bar';
      const inner = [`<rect class="${cls} ch-mark" x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${(y(0) - top).toFixed(1)}" rx="2"/>`];
      if (n <= 12) inner.push(`<text class="${b.kind === 'next' ? 'ch-val-focal' : 'ch-val'}" x="${cx}" y="${top - 6}" text-anchor="middle">${esc(short(b.value))}</text>`);
      inner.push(`<text class="ch-xlab" x="${cx}" y="${h - 14}" text-anchor="middle">${esc(b.label)}</text>`, hit(M.l + pitch * i, M.t - 10, pitch, ph + 10));
      const k = b.kind === 'next' ? 'focal' : b.kind === 'done' ? 'done' : 'muted';
      body.push(item(b.label, [{n: name, t: F(b.value), k, x: KIND_NAME[b.kind] || ''}], cx, top, inner.join('')));
    });
    return svg(h, label, body.join(''));
  }

  /** Waterfall: start total → signed bridges → end total. steps: [{label, value, role:'total'|'delta', focal?}] */
  function waterfall({steps, height = 280, label = '', width, fmt}) {
    setW(width);
    const h = fitH(height, 280), n = steps.length, F = fmtOf(fmt);
    let run = 0, peak = 0;
    const placed = steps.map(s => {
      if (s.role === 'total') { run = s.value; peak = Math.max(peak, run); return {...s, from: 0, to: s.value}; }
      const from = run; run += s.value; peak = Math.max(peak, from, run); return {...s, from, to: run};
    });
    const sc = scale(peak), pw = W - M.l - M.r, ph = h - M.t - M.b, pitch = pw / n, bw = Math.min(84, pitch * 0.6), y = v => M.t + ph - (ph * v) / sc.max;
    const body = [frame(h, sc, y)];
    placed.forEach((s, i) => {
      const cx = M.l + pitch * i + pitch / 2, top = y(Math.max(s.from, s.to)), bot = y(Math.min(s.from, s.to));
      const cls = s.focal ? 'ch-wf-focal' : s.role === 'total' ? 'ch-wf-total' : s.value >= 0 ? 'ch-wf-up' : 'ch-wf-down';
      const val = s.role === 'total' ? short(s.value) : (s.value >= 0 ? '+' : '') + short(s.value);
      const ty = s.role === 'delta' && s.value < 0 ? bot + 14 : top - 6;
      const inner = `<rect class="${cls} ch-mark" x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, bot - top).toFixed(1)}"/>` +
        `<text class="${s.focal ? 'ch-val-focal' : 'ch-val'}" x="${cx}" y="${ty}" text-anchor="middle">${esc(val)}</text>` +
        `<text class="ch-xlab" x="${cx}" y="${h - 14}" text-anchor="middle">${esc(s.label)}</text>` + hit(M.l + pitch * i, M.t - 10, pitch, ph + 10);
      body.push(item(s.label, [{n: s.role === 'total' ? 'Tổng' : 'Thay đổi', t: (s.role === 'delta' && s.value > 0 ? '+' : '') + F(s.value), k: s.focal ? 'focal' : 'muted'}], cx, top, inner));
      if (i < n - 1) body.push(`<line class="ch-carry" x1="${(cx + bw / 2).toFixed(1)}" x2="${(cx + pitch - bw / 2).toFixed(1)}" y1="${y(s.to)}" y2="${y(s.to)}"/>`);
    });
    return svg(h, label, body.join(''));
  }

  /** Grouped columns: groups: [{label, values:[focal, muted]}]; first value of each group is the accent.
   *  Optional: names (series names for the tooltip), tips (tooltip label per group), fmt. */
  function grouped({groups, height = 260, label = '', width, names = [], tips, fmt, more}) {
    setW(width);
    const n = groups.length, pw = W - M.l - M.r, pitch = pw / Math.max(n, 1), ax = xAxis(groups.map(g => g.label), pitch);
    const h = fitH(height, 260), ph = h - M.t - ax.b, sc = scale(Math.max(1, ...groups.flatMap(g => g.values)), ph < 140 ? 2 : ph < 200 ? 3 : 4), F = fmtOf(fmt);
    const k = Math.max(1, ...groups.map(g => g.values.length)), bw = Math.max(k > 2 ? 4 : 8, Math.min(44, pitch * 0.7 / k)), gap = k > 2 && pitch < 60 ? 1.5 : 4, y = v => M.t + ph - (ph * v) / sc.max;
    const body = [frame(h, sc, y)];
    groups.forEach((g, i) => {
      const cx = M.l + pitch * i + pitch / 2, x0 = cx - (bw * k + gap * (k - 1)) / 2, inner = [];
      g.values.forEach((v, j) => {
        const x = x0 + j * (bw + gap), top = y(v || 0);
        inner.push(`<rect class="${j === 0 ? 'ch-bar-focal' : j === 2 ? 'ch-bar ch-bar-third' : 'ch-bar'} ch-mark" x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, y(0) - top).toFixed(1)}" rx="2"/>`);
        if (n <= 6 && v && pitch / k >= 30) inner.push(`<text class="${j === 0 ? 'ch-val-focal' : 'ch-val'}" x="${(x + bw / 2).toFixed(1)}" y="${top - 6}" text-anchor="middle">${esc(short(v))}</text>`);
      });
      inner.push(ax.text(g.label, cx, h), hit(M.l + pitch * i, M.t - 10, pitch, ph + 10));
      const rows = g.values.map((v, j) => ({n: names[j] || `Giá trị ${j + 1}`, t: F(v || 0), k: j === 0 ? 'focal' : j === 2 ? 'third' : 'muted'})).concat(extraRows(more, i));
      body.push(item((tips && tips[i]) || g.label, rows, cx, y(Math.max(0, ...g.values.map(v => v || 0))), inner.join('')));
    });
    return svg(h, label, body.join(''));
  }

  /** Columns with a line over the same columns (18/10/2026, Thống kê "Doanh thu 12 tháng"): one x position per
   *  label at the column centre, like grouped(), so two charts with the same labels and width line up.
   *  bars: {name, values, kinds?: per-column key, kindNames?: {key: series name}} (kind 'est' is drawn dashed);
   *  line: {name, values} (the accent; null breaks it). Optional: tips, fmt, more (extra tooltip rows per column). */
  function combo({labels, bars: B, line: L, height = 260, label = '', width, tips, fmt, more}) {
    setW(width);
    const n = labels.length, pw = W - M.l - M.r, pitch = pw / Math.max(n, 1), ax = xAxis(labels, pitch), F = fmtOf(fmt);
    const h = fitH(height, 260), ph = h - M.t - ax.b, all = [...(B ? B.values : []), ...(L ? L.values : [])].filter(v => v != null);
    const sc = scale(Math.max(1, ...all), ph < 140 ? 2 : ph < 200 ? 3 : 4), y = v => M.t + ph - (ph * v) / sc.max;
    const cx = i => M.l + pitch * i + pitch / 2, bw = Math.max(6, Math.min(40, pitch * 0.62));
    const body = [frame(h, sc, y)], items = [];
    if (L) {  // the line under the hover layer, broken where a value is missing
      let seg = [];
      const flush = () => { if (seg.length > 1) body.push(`<polyline class="ch-line-focal" data-s="1" points="${seg.join(' ')}"/>`); seg = []; };
      L.values.forEach((v, i) => { if (v == null) flush(); else seg.push(`${cx(i).toFixed(1)},${y(v).toFixed(1)}`); });
      flush();
    }
    labels.forEach((lab, i) => {
      const v = B ? B.values[i] : null, kind = B && B.kinds ? B.kinds[i] : null, lv = L ? L.values[i] : null, inner = [], rows = [];
      if (v != null) {
        const top = y(v);
        inner.push(`<rect class="ch-bar${kind === 'est' ? ' ch-bar-est' : ''} ch-mark" data-s="0" x="${(cx(i) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, y(0) - top).toFixed(1)}" rx="2"/>`);
        rows.push({n: (B.kindNames && B.kindNames[kind]) || B.name, t: F(v), k: kind === 'est' ? 'est' : 'muted', s: 0, y: +top.toFixed(1)});
      }
      if (lv != null) {
        inner.push(`<circle class="ch-dot" data-s="1" cx="${cx(i).toFixed(1)}" cy="${y(lv).toFixed(1)}" r="3.5"/>`,
                   `<circle class="ch-hot k-focal" data-s="1" cx="${cx(i).toFixed(1)}" cy="${y(lv).toFixed(1)}" r="5.5"/>`);
        rows.push({n: L.name, t: F(lv), k: 'focal', s: 1, y: +y(lv).toFixed(1)});
      }
      inner.push(ax.text(lab, cx(i), h), hit(M.l + pitch * i, M.t - 10, pitch, ph + 10));
      const top = rows.length ? Math.min(...rows.map(r => r.y)) : y(0);
      const all2 = rows.concat(extraRows(more, i));
      items.push(item((tips && tips[i]) || lab, all2.length ? all2 : [{n: 'Chưa có số liệu', t: '—', k: 'note'}], cx(i), top, inner.join('')));
    });
    body.push(`<g class="ch-items">${items.join('')}</g>`);
    return svg(h, label, body.join(''));
  }

  /** Horizontal bars, largest first: rows: [{label, value, note?, noteShort?}] (noteShort under 520px); the top row is the accent.
   *  Optional: name (series name in the tooltip), fmt. The tooltip repeats the note's percentage, if any. */
  function hbars({rows, label = '', width, height, name = 'Giá trị', fmt}) {
    setW(width);
    // The label column fits the longest name (up to 42% of the width); a longer name is cut with "…" and
    // shown in full in the tooltip.
    const est = t => [...String(t)].length * 7.6, vw = W < 520 ? 70 : 150;
    const lw = Math.round(Math.max(80, Math.min(W * 0.42, W - vw - 60, Math.max(0, ...rows.map(r => est(r.label))) + 18)));
    const fit = t => { const c = [...String(t)], m = Math.floor((lw - 18) / 7.6); return c.length <= m ? String(t) : c.slice(0, Math.max(1, m - 1)).join('') + '…'; };
    const narrow = W < 520, n = rows.length, top = 6, F = fmtOf(fmt);
    const row = Math.max(24, Math.min(54, Math.floor(((height || 0) - 12) / Math.max(n, 1)) || 40)), h = top + n * row + 6, bh = Math.max(10, Math.min(26, Math.round(row * 0.6)));
    const max = Math.max(1, ...rows.map(r => r.value)), pw = W - lw - vw - 12;
    const body = [];
    rows.forEach((r, i) => {
      const y = top + i * row, bw = Math.max(2, (pw * r.value) / max), focal = i === 0;
      const extra = String(r.note || '').split('·').map(s => s.trim()).filter(s => /%/.test(s)).join(' · ');
      const inner = `<text class="ch-hlab" x="${lw - 10}" y="${y + row / 2 + 5}" text-anchor="end">${esc(fit(r.label))}</text>` +
                `<rect class="${focal ? 'ch-bar-focal' : 'ch-bar'} ch-mark" x="${lw}" y="${y + (row - bh) / 2}" width="${bw.toFixed(1)}" height="${bh}" rx="3"/>` +
                `<text class="${focal ? 'ch-val-focal' : 'ch-val'}" x="${(lw + bw + 8).toFixed(1)}" y="${y + row / 2 + 5}">${esc((narrow ? r.noteShort : r.note) || r.note || short(r.value))}</text>` + hit(0, y, W, row);
      body.push(item(r.label, [{n: name, t: F(r.value), k: focal ? 'focal' : 'muted', x: extra}], lw + bw, y + (row - bh) / 2, inner));
    });
    body.push(`<line class="ch-axis" x1="${lw}" x2="${lw}" y1="${top}" y2="${h - 6}"/>`);
    return svg(h, label, body.join(''));
  }

  /* ---------- Interaction: highlight, tooltip, fairy dust ---------- */
  const hasDOM = typeof document !== 'undefined' && !!document.createElement && typeof window !== 'undefined';
  const reduced = () => { try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (_) { return false; } };
  let current = null;            // {root, item}
  let docBound = false;
  const hosts = new WeakMap();   // card element → {tip, canvas, ctx, parts, raf, lx, ly, colors}

  function hostOf(root) {
    const el = root.closest('.chart-card') || root;
    let st = hosts.get(el);
    if (!st) { st = {el, parts: [], raf: 0, lx: null, ly: null}; hosts.set(el, st); el.classList.add('ch-host'); }
    return st;
  }
  function tipOf(st) {
    if (!st.tip || !st.tip.isConnected) {
      st.tip = document.createElement('div');
      st.tip.className = 'ch-tip'; st.tip.setAttribute('role', 'tooltip'); st.tip.setAttribute('aria-hidden', 'true'); st.tip.hidden = true;
      st.el.appendChild(st.tip);
    }
    return st.tip;
  }
  function rowsOf(it) { try { return JSON.parse(it.getAttribute('data-rows') || '[]'); } catch (_) { return []; } }
  function fill(tip, it) {
    const rows = rowsOf(it);
    tip.innerHTML = `<div class="ch-tip-h">${esc(it.getAttribute('data-label'))}</div>` + rows.map(r =>
      `<div class="ch-tip-r"><i class="ch-tip-dot k-${esc(r.k)}"></i><span class="ch-tip-n">${esc(r.n)}</span><strong>${esc(r.t)}</strong>${r.x ? `<small>${esc(r.x)}</small>` : ''}</div>`).join('');
  }
  function place(st, it, pt) {
    const tip = st.tip, hr = st.el.getBoundingClientRect(), pad = 6, gap = 14;
    let px, py;
    if (pt) { px = pt.x - hr.left; py = pt.y - hr.top; }
    else {
      const s = it.ownerSVGElement, sr = s.getBoundingClientRect(), vb = s.viewBox && s.viewBox.baseVal, k = vb && vb.width ? sr.width / vb.width : 1;
      px = sr.left - hr.left + Number(it.getAttribute('data-ax')) * k; py = sr.top - hr.top + Number(it.getAttribute('data-ay')) * k;
    }
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = px + gap; if (left + tw > hr.width - pad) left = px - gap - tw;
    let top = py - th - gap; if (top < pad) top = py + gap + 4;
    left = Math.max(pad, Math.min(left, hr.width - tw - pad)); top = Math.max(pad, Math.min(top, hr.height - th - pad));
    tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
  }
  function activate(root, it, pt) {
    const st = hostOf(root), tip = tipOf(st), s = it.ownerSVGElement;
    if (!current || current.item !== it) {
      if (current) deactivate();
      current = {root, item: it};
      it.classList.add('is-on'); if (s) s.classList.add('is-active');
      fill(tip, it); tip.hidden = false;
    }
    // Several series: the one nearest the pointer stays bright, the others dim a little.
    if (s) {
      const rows = rowsOf(it); let near = null;
      if (rows.length > 1 && rows[0].y != null) {
        const sr = s.getBoundingClientRect(), vb = s.viewBox.baseVal, k = vb.width ? sr.width / vb.width : 1, yy = pt ? (pt.y - sr.top) / k : null;
        near = yy == null ? rows[0].s : rows.reduce((b, r) => Math.abs(r.y - yy) < Math.abs(b.y - yy) ? r : b).s;
      }
      s.querySelectorAll('[data-s]').forEach(el => el.classList.toggle('is-dim', near != null && Number(el.getAttribute('data-s')) !== near));
    }
    place(st, it, pt);
  }
  function deactivate() {
    if (!current) return;
    const {root, item: it} = current, s = it.ownerSVGElement, st = hosts.get(root.closest('.chart-card') || root);
    it.classList.remove('is-on'); if (s) { s.classList.remove('is-active'); s.querySelectorAll('.is-dim').forEach(el => el.classList.remove('is-dim')); }
    if (st && st.tip) st.tip.hidden = true;
    current = null;
  }

  // Fairy dust: tiny glowing stars/dots shed along the pointer trail; one rAF loop per card, stopped when empty.
  const MAX_PARTS = 60;
  function colors(st) {
    const cs = getComputedStyle(st.el), dark = /dark/.test(getComputedStyle(document.documentElement).colorScheme || '');
    const p = cs.getPropertyValue('--bu-primary').trim() || '#9b4d6b', a = cs.getPropertyValue('--bu-accent').trim() || '#efc3d3';
    return {dark, list: dark ? [p, a, '#fff6fa', p] : [p, p, a, '#d48aa6']};
  }
  function canvasOf(st) {
    if (!st.canvas || !st.canvas.isConnected) {
      st.canvas = document.createElement('canvas'); st.canvas.className = 'ch-dust'; st.canvas.setAttribute('aria-hidden', 'true');
      st.el.insertBefore(st.canvas, st.tip && st.tip.isConnected ? st.tip : null);
      st.ctx = st.canvas.getContext && st.canvas.getContext('2d');
    }
    const dpr = Math.min(2, window.devicePixelRatio || 1), w = st.el.clientWidth, h = st.el.clientHeight;
    if (st.canvas.width !== Math.round(w * dpr) || st.canvas.height !== Math.round(h * dpr)) {
      st.canvas.width = Math.round(w * dpr); st.canvas.height = Math.round(h * dpr); st.dpr = dpr;
    }
    return st.ctx;
  }
  function sprinkle(st, cx, cy, count) {
    if (reduced() || !window.requestAnimationFrame) return;
    const hr = st.el.getBoundingClientRect(), x = cx - hr.left, y = cy - hr.top;
    if (count == null) {
      if (st.lx != null && Math.hypot(x - st.lx, y - st.ly) < 6) return;
      count = 3;
    }
    st.lx = x; st.ly = y;
    if (!canvasOf(st)) return;
    if (!st.raf) st.colors = colors(st);
    const now = performance.now(), R = (a, b) => a + Math.random() * (b - a);
    for (let i = 0; i < count; i++) {
      if (st.parts.length >= MAX_PARTS) st.parts.shift();
      const up = Math.random() < 0.55;
      st.parts.push({x: x + R(-5, 5), y: y + R(-5, 5), vx: R(-0.03, 0.03), vy: up ? R(-0.05, -0.015) : R(0.01, 0.04), g: up ? -0.00002 : 0.00005,
        born: now, life: R(600, 1000), size: R(2, 5), star: Math.random() < 0.5, rot: R(0, Math.PI), spin: R(-0.004, 0.004), c: st.colors.list[(Math.random() * st.colors.list.length) | 0], tw: R(0, 6)});
    }
    if (!st.raf) { st.last = now; st.raf = requestAnimationFrame(t => frameDust(st, t)); }
  }
  function star(ctx, r) {
    const q = r * 0.28;
    ctx.beginPath(); ctx.moveTo(0, -r);
    ctx.quadraticCurveTo(q, -q, r, 0); ctx.quadraticCurveTo(q, q, 0, r); ctx.quadraticCurveTo(-q, q, -r, 0); ctx.quadraticCurveTo(-q, -q, 0, -r);
    ctx.fill();
  }
  function frameDust(st, t) {
    const ctx = st.ctx, dpr = st.dpr || 1, dt = Math.min(48, t - (st.last || t)); st.last = t;
    if (!ctx || !st.canvas.isConnected) { st.parts = []; st.raf = 0; return; }
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, st.canvas.width, st.canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalCompositeOperation = st.colors && st.colors.dark ? 'lighter' : 'source-over';
    st.parts = st.parts.filter(p => t - p.born < p.life);
    for (const p of st.parts) {
      const age = (t - p.born) / p.life;
      p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.rot += p.spin * dt;
      const twinkle = 0.75 + 0.25 * Math.sin(p.tw + age * 14), alpha = Math.pow(Math.max(0, 1 - age), 1.4) * twinkle, r = p.size * (age < 0.15 ? 0.6 + age * 2.7 : 1 - age * 0.35);
      ctx.save(); ctx.globalAlpha = alpha; ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.fillStyle = p.c; ctx.shadowColor = p.c; ctx.shadowBlur = r * 3;
      if (p.star) star(ctx, r * 1.3); else { ctx.beginPath(); ctx.arc(0, 0, r / 2, 0, Math.PI * 2); ctx.fill(); }
      ctx.restore();
    }
    if (st.parts.length) st.raf = requestAnimationFrame(tt => frameDust(st, tt));
    else { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, st.canvas.width, st.canvas.height); st.raf = 0; st.lx = st.ly = null; }
  }

  /** Wires hover/touch/keyboard to the chart drawn inside ``root`` (a .chart-slot). Safe to call after every redraw:
   *  listeners live on the slot (delegated), so re-rendering its SVG keeps them working. */
  function attach(root) {
    if (!hasDOM || !root || !root.querySelector || !root.addEventListener) return;
    if (current && !current.item.isConnected) deactivate();   // the SVG was redrawn (resize): drop the stale tooltip
    if (root.__chFx) return;
    root.__chFx = true;
    let lastPointer = 0, touchSticky = false;
    const within = e => e.target && e.target.closest ? e.target.closest('.ch-item') : null;
    root.addEventListener('pointermove', e => {
      if (!root.querySelector('svg.ch')) return;
      lastPointer = Date.now();
      const it = within(e);
      if (it) activate(root, it, {x: e.clientX, y: e.clientY});
      else if (!touchSticky) deactivate();
      if (e.target.closest && e.target.closest('svg.ch')) sprinkle(hostOf(root), e.clientX, e.clientY);
    });
    root.addEventListener('pointerdown', e => {
      lastPointer = Date.now();
      const it = within(e);
      if (e.pointerType === 'touch' || e.pointerType === 'pen') {
        if (it) { touchSticky = true; activate(root, it, {x: e.clientX, y: e.clientY}); sprinkle(hostOf(root), e.clientX, e.clientY, 8); }
        else { touchSticky = false; deactivate(); }
      }
    });
    root.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && current && current.root === root) deactivate(); });
    root.addEventListener('focusin', e => {
      const it = within(e); if (!it) return;
      if (Date.now() - lastPointer < 400 && current && current.item === it) return;
      activate(root, it, null);
    });
    root.addEventListener('focusout', e => { if (!root.contains(e.relatedTarget) && current && current.root === root && Date.now() - lastPointer > 400) deactivate(); });
    root.addEventListener('keydown', e => {
      const it = within(e); if (!it) return;
      if (e.key === 'Escape') { deactivate(); return; }
      const step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[e.key]; if (!step) return;
      const all = [...root.querySelectorAll('.ch-item')], next = all[all.indexOf(it) + step];
      if (next) { e.preventDefault(); next.focus(); }
    });
    if (!docBound) {
      docBound = true;
      document.addEventListener('pointerdown', e => { if (current && !current.root.contains(e.target)) deactivate(); }, true);
      document.addEventListener('scroll', () => { if (current && !current.item.isConnected) deactivate(); }, true);
    }
  }

  window.BU = window.BU || {};
  window.BU.charts = {line, bars, waterfall, grouped, combo, hbars, short, attach};
})();
