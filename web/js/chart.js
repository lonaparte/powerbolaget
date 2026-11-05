'use strict';
// Pixel line charts: a canvas at half resolution, hard steps, no anti-aliasing.
PB.chart = (() => {
  function draw(canvas, series, opts = {}) {
    const P = 1, r = canvas.getBoundingClientRect();
    const W = Math.max(60, Math.floor(r.width / P)), H = Math.max(40, Math.floor(r.height / P));
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    const c = canvas.getContext('2d'); c.imageSmoothingEnabled = false;
    const css = PB.css, ink = css('--ink'), muted = css('--muted'), grid = css('--line');
    c.fillStyle = css('--input'); c.fillRect(0, 0, W, H);
    const left = 34, right = W - 6, top = opts.title ? 32 : 18, bottom = H - 14;
    const all = series.flatMap(s => s.values.filter(v => v != null && isFinite(v)));
    if (!all.length) { c.fillStyle = muted; c.font = '8px monospace'; c.fillText('collecting data…', left, H / 2); return; }
    let lo = Math.min(opts.min ?? Infinity, ...all), hi = Math.max(opts.max ?? -Infinity, ...all);
    if (hi - lo < 1e-6) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * .08; hi += pad; if (lo < 0 || opts.min == null) lo -= pad;
    const n = Math.max(...series.map(s => s.values.length));
    const X = i => left + (right - left) * (n <= 1 ? 0 : i / (n - 1)), Y = v => bottom - (bottom - top) * (v - lo) / (hi - lo);
    c.font = '10px ui-monospace, monospace'; c.textBaseline = 'middle';
    for (let k = 0; k <= 3; k++) {
      const v = lo + (hi - lo) * k / 3, y = Math.round(Y(v));
      c.fillStyle = grid; for (let x = left; x < right; x += 4) c.fillRect(x, y, 2, 1);
      c.fillStyle = muted; c.fillText(Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1), 2, y);
    }
    if (lo < 0 && hi > 0) { c.fillStyle = muted; c.fillRect(left, Math.round(Y(0)), right - left, 1); }
    for (const s of series) {
      c.fillStyle = s.color; let prev = null;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) { prev = null; return; }
        const x = Math.round(X(i)), y = Math.round(Y(v));
        if (prev) {
          const [px, py] = prev;
          const w = s.bold ? 3 : 2;
          if (opts.steps) { c.fillRect(Math.min(px, x), py, Math.abs(x - px) + w, w); c.fillRect(x, Math.min(py, y), w, Math.abs(y - py) + w); }
          else { const dx = Math.abs(x - px), dy = Math.abs(y - py), st = Math.max(dx, dy, 1); for (let k = 0; k <= st; k++) c.fillRect(Math.round(px + (x - px) * k / st), Math.round(py + (y - py) * k / st), w, w); }
        } else c.fillRect(x, y, 2, 2);
        prev = [x, y];
      });
    }
    c.textBaseline = 'top';
    let lx = left, ly = 3;
    if (opts.title) { c.fillStyle = muted; c.fillText(opts.title, left, 3); ly = 17; }
    for (const s of series) {
      if (!s.name) continue;
      const w = 20 + c.measureText(s.name).width;
      if (lx + w > right) { lx = left; ly += 13; }
      c.fillStyle = s.color; c.fillRect(lx, ly + 1, 8, 8); c.fillStyle = ink; c.fillText(s.name, lx + 11, ly); lx += w;
    }
    if (opts.xlabels) { c.fillStyle = muted; c.textBaseline = 'bottom'; c.fillText(opts.xlabels[0], left, H); c.textAlign = 'right'; c.fillText(opts.xlabels[1], right, H); c.textAlign = 'left'; }
  }
  return {draw};
})();
