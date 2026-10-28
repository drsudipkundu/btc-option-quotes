/* My Bots chart page overlay (v1.1, 28-Oct-2026): same layers as the Delta userscript v1.9, drawn on a canvas over the lightweight-charts chart.
   Volume profile (left), estimated liquidation clusters (left-centre), BTC option OI (right), live order-book walls just right of the
   current candle, liquidity POC line, book readout box, ladder-level wall check (on the bot's own green 'buy' lines).
   Read-only public data. Loaded by chartpage.py via one <script> tag; needs the page globals chart, cs, sym, res, RES, light, wrap. */
(function () {
  'use strict';
  if (window.__BCO) return; window.__BCO = true;
  const CFG = {
    api: 'https://api.india.delta.exchange/v2',
    refreshMin: 5,
    vpOn: true, vpDays: 90, vpRangePct: 12, vpRes: '4h', vpBin: 200, vpWidthPct: 22,
    vpColor: 'rgba(158,158,158,0.30)', vpPocColor: 'rgba(255,193,7,0.55)',
    oiOn: true, oiMaxDays: 7, oiRangePct: 12, oiWidthPct: 22,
    callColor: 'rgba(244,67,54,0.45)', putColor: 'rgba(0,150,136,0.45)', oiLabelsTop: 3, oiMinPct: 8,
    liqOn: true, liqStartPct: 24, liqWidthPct: 20, liqBin: 100, liqRangePct: 12, liqMinPct: 3,
    liqHeatmap: true, liqHeatMinPct: 6, liqHeatAlpha: [0.06, 0.40],
    liqBuckets: [[10, 0.35], [25, 0.30], [50, 0.20], [100, 0.15]], liqMmr: 0.004,
    longLevColors: ['255,204,128', '255,138,101', '244,81,30', '183,28,28'],
    shortLevColors: ['200,230,201', '129,199,132', '56,142,60', '27,94,32'],
    liqBarAlpha: 0.7, liqLabelsTop: 4,
    bookOn: true, bookSec: 15, bookDepth: 1000, bookBin: 25, bookRangePct: 1.2, bookMinPct: 15,
    bookGapBars: 1, bookWidthBars: 5,
    bidColor: 'rgba(38,166,154,0.55)', askColor: 'rgba(239,83,80,0.55)', bookLabelsTop: 2,
    bookImbPct: 1, bookTopN: 10, bookPocLine: true,
    ladderCheck: true, ladderTolPct: 0.1, ladderStrong: 1.5, contractBtc: 0.001,
  };
  const wrap = document.getElementById('wrap');
  const cv = document.createElement('canvas');
  cv.id = 'bco'; cv.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;z-index:6';
  wrap.appendChild(cv);
  const g = cv.getContext('2d');

  // ---------------- strategy dropdown: choose which strategy's bot drawings are visible ----------------
  const STRATS = [['all', 'All strategies'], ['ladder', 'Ladder v9'], ['lv11', 'Ladder v11'], ['lv12', 'Ladder v12'],
                  ['v4a', 'Night v4A-CG'], ['v5a', 'Night v5A-CG'], ['manual', 'My paper trades']];
  const LSget = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const LSset = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
  let selStrat = LSget('bco_strat'); if (!STRATS.some(x => x[0] === selStrat)) selStrat = 'ladder';
  const stratOf = x => x.strat || (/^V4A/.test(x.label || '') ? 'v4a' : /^V5A/.test(x.label || '') ? 'v5a' : /^MY PAPER/.test(x.label || '') ? 'manual' : 'ladder');
  const keep = x => selStrat === 'all' || stratOf(x) === selStrat;
  try {   // the page draws its lines from api('/api/auto...'); filter that answer
    const origApi = window.api;
    window.api = async function (u, o) {
      const r = await origApi.call(this, u, o);
      return (typeof u === 'string' && u.indexOf('/api/auto') === 0 && Array.isArray(r)) ? r.filter(keep) : r;
    };
  } catch (e) { console.warn('bco api wrap', e); }
  const sel = document.createElement('select'); sel.id = 'stratSel'; sel.title = 'Show the drawings of this strategy';
  sel.style.cssText = 'margin-left:8px;padding:3px 6px';
  STRATS.forEach(([k, n]) => { const o = document.createElement('option'); o.value = k; o.textContent = n; sel.appendChild(o); });
  sel.value = selStrat;
  const anchor = document.getElementById('auto'); (anchor && anchor.parentElement ? anchor.parentElement : document.querySelector('.bar')).after(sel);
  sel.onchange = () => { selStrat = sel.value; LSset('bco_strat', selStrat); try { autoLines(); } catch (e) {} bookRefresh(); };
  try { autoLines(); } catch (e) {}   // apply the saved choice at once
  const S = { vp: null, oi: null, liq: null, book: null, ladder: [], ver: 0 };
  const isLight = () => { try { return !!light; } catch (e) { return false; } };
  const ivSec = () => { try { return RES[res] || 3600; } catch (e) { return 3600; } };
  const isBtc = () => { try { return sym === 'BTCUSD'; } catch (e) { return false; } };
  async function j(url) { const r = await fetch(url); return (await r.json()).result || []; }

  // ---------------- data (same models as the Delta userscript) ----------------
  async function volumeProfile() {
    const now = Math.floor(Date.now() / 1000);
    const cs_ = await j(`${CFG.api}/history/candles?resolution=${CFG.vpRes}&symbol=BTCUSD&start=${now - CFG.vpDays * 86400}&end=${now}`);
    const bins = new Map();
    for (const k of cs_) {
      const lo = Math.floor(k.low / CFG.vpBin), hi = Math.floor(k.high / CFG.vpBin), n = hi - lo + 1;
      for (let b = lo; b <= hi; b++) bins.set(b, (bins.get(b) || 0) + k.volume / n);
    }
    bins.last = cs_.length ? cs_.reduce((a, k) => (k.time > a.time ? k : a)).close : 0;
    return bins;
  }
  async function optionOI(spot) {
    const t = await j(`${CFG.api}/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC`);
    const lim = Date.now() + CFG.oiMaxDays * 86400000;
    const call = new Map(), put = new Map();
    for (const o of t) {
      const m = /-(\d{2})(\d{2})(\d{2})$/.exec(o.symbol || '');
      if (m && new Date(Date.UTC(2000 + +m[3], +m[2] - 1, +m[1], 12)).getTime() > lim) continue;
      const k = +o.strike_price, oi = +o.oi || 0;
      if (!k || !oi || Math.abs(k / spot - 1) * 100 > CFG.oiRangePct) continue;
      const map = o.contract_type === 'call_options' ? call : put;
      map.set(k, (map.get(k) || 0) + oi);
    }
    return { call, put };
  }
  async function liquidation() {
    const B = 'https://fapi.binance.com';
    const gj = async u => (await fetch(B + u, { referrerPolicy: 'no-referrer' })).json();   // Binance refuses requests that carry this page's referrer
    const [oi, ls, kl] = await Promise.all([
      gj('/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=500'),
      gj('/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=500'),
      gj('/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=500')]);
    const oiT = new Map(oi.map(r => [Math.floor(r.timestamp / 3600000), +r.sumOpenInterest]));
    const lsT = new Map(ls.map(r => [Math.floor(r.timestamp / 3600000), +r.longAccount]));
    let cl = [], prev = null;
    for (const k of kl) {
      const h = Math.floor(k[0] / 3600000) + 1, hi = +k[2], lo = +k[3], close = +k[4];
      cl = cl.filter(x => x.long ? x.p < lo : x.p > hi);
      const o = oiT.get(h); if (o == null) continue;
      if (prev != null) {
        const d = o - prev;
        if (d > 0) {
          const lf = lsT.has(h) ? lsT.get(h) : 0.5;
          for (const [L, w] of CFG.liqBuckets) {
            const t = Math.floor(k[0] / 1000) + 3600;
            cl.push({ p: close * (1 - 1 / L + CFG.liqMmr), q: d * lf * w, long: true, L, t });
            cl.push({ p: close * (1 + 1 / L - CFG.liqMmr), q: d * (1 - lf) * w, long: false, L, t });
          }
        } else if (d < 0 && prev > 0) { const f = o / prev; for (const x of cl) x.q *= f; }
      }
      prev = o;
    }
    const rows = new Map(), li = new Map(CFG.liqBuckets.map(([L], i) => [L, i]));
    for (const x of cl) {
      const b = Math.floor(x.p / CFG.liqBin), key = (x.long ? 'L' : 'S') + b;
      let r = rows.get(key); if (!r) { r = { long: x.long, b, tot: 0, lev: CFG.liqBuckets.map(() => 0), ts: 0 }; rows.set(key, r); }
      r.tot += x.q; r.lev[li.get(x.L)] += x.q; r.ts += x.q * x.t;
    }
    return [...rows.values()];
  }
  async function slowRefresh() {
    if (!isBtc()) return;
    let spot = 0;
    try { const tk = await j(`${CFG.api}/tickers/BTCUSD`); spot = +tk.mark_price || +tk.close || 0; } catch (e) {}
    S.spot = spot;
    const tasks = [];
    if (CFG.vpOn) tasks.push(volumeProfile().then(v => { S.vp = v; }).catch(e => console.warn('bco vp', e)));
    if (CFG.oiOn && spot) tasks.push(optionOI(spot).then(v => { S.oi = v; }).catch(e => console.warn('bco oi', e)));
    if (CFG.liqOn) tasks.push(liquidation().then(v => { S.liq = v; }).catch(e => console.warn('bco liq', e)));
    await Promise.all(tasks); S.ver++;
  }
  let bookBusy = false;
  async function bookRefresh() {
    if (!CFG.bookOn || bookBusy || !isBtc()) return;
    bookBusy = true;
    try {
      const res_ = await (await fetch(`${CFG.api}/l2orderbook/BTCUSD?depth=${CFG.bookDepth}`)).json();
      const bids = (res_.result.buy || []).map(x => [+x.price, x.size * CFG.contractBtc]).filter(x => x[0] > 100);
      const asks = (res_.result.sell || []).map(x => [+x.price, x.size * CFG.contractBtc]).filter(x => x[0] < 1e6);
      if (!bids.length || !asks.length) return;
      const bb = bids[0][0], ba = asks[0][0], mid = (bb + ba) / 2, spread = ba - bb, lim = mid * CFG.bookRangePct / 100;
      const rowsOf = list => { const m = new Map(); for (const [p, q] of list) if (Math.abs(p - mid) <= lim) { const b = Math.floor(p / CFG.bookBin); m.set(b, (m.get(b) || 0) + q); } return m; };
      const bidRows = rowsOf(bids), askRows = rowsOf(asks);
      const max = Math.max(1e-9, ...bidRows.values(), ...askRows.values());
      const topKeys = m => new Set([...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, CFG.bookLabelsTop).map(x => x[0]));
      const sumWithin = (list, pct) => list.reduce((a, [p, q]) => a + (Math.abs(p - mid) <= mid * pct / 100 ? q : 0), 0);
      const B = sumWithin(bids, CFG.bookImbPct), A = sumWithin(asks, CFG.bookImbPct);
      const nb = bids.slice(0, CFG.bookTopN).reduce((a, x) => a + x[1], 0), na = asks.slice(0, CFG.bookTopN).reduce((a, x) => a + x[1], 0);
      let poc = null, pv = -1, pSide = '';
      for (const [b, q] of bidRows) if (q > pv) { pv = q; poc = b; pSide = 'bid'; }
      for (const [b, q] of askRows) if (q > pv) { pv = q; poc = b; pSide = 'ask'; }
      // ladder check on the bot's own green 'buy' lines
      let ladder = [];
      if (CFG.ladderCheck) {
        try {
          const lines = (await (await fetch('/api/auto?sym=BTCUSD')).json()).filter(keep);
          const avg = ([...bidRows.values()].reduce((a, b) => a + b, 0) / Math.max(1, bidRows.size)) || 1e-9;
          const lowBid = bids[bids.length - 1][0];
          for (const L of (Array.isArray(lines) ? lines : [])) {
            if (!/^buy\s*0\.00/i.test(L.label || '')) continue;
            const pr = +L.price; if (pr < lowBid || pr >= bb) continue;
            const sz = bids.reduce((a, [p, q]) => a + (Math.abs(p - pr) <= pr * CFG.ladderTolPct / 100 ? q : 0), 0);
            const rowSz = sz / Math.max(1, (2 * pr * CFG.ladderTolPct / 100) / CFG.bookBin);
            ladder.push({ pr, sz, ok: rowSz >= CFG.ladderStrong * avg });
          }
        } catch (e) {}
      }
      S.book = { bb, ba, mid, spread, bidRows, askRows, max, tb: topKeys(bidRows), ta: topKeys(askRows), B, A,
                 imbFull: (B - A) / (B + A), imbNear: (nb - na) / (nb + na), poc, pv, pSide };
      S.ladder = ladder; S.ver++;
    } catch (e) { console.warn('bco book', e); } finally { bookBusy = false; }
  }

  // ---------------- drawing ----------------
  function draw() {
    const W = wrap.clientWidth, H = wrap.clientHeight, dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
    }
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    if (!isBtc()) return;
    const ts = chart.timeScale(), plotW = ts.width(), tsH = ts.height ? ts.height() : 26, plotH = H - tsH;
    const lr = ts.getVisibleLogicalRange(); if (!lr || plotW <= 0) return;
    const iv = ivSec(), spacing = plotW / (lr.to - lr.from);
    // the chart's own newest bar (the page may lag the clock by a candle or two); times after it are extrapolated
    let Tb = null; try { const d = cs.dataByIndex(Math.floor(lr.to), -1); if (d) Tb = d.time; } catch (e) {}
    if (Tb == null) return;
    const xb = ts.timeToCoordinate(Tb); if (xb == null) return;
    const lastT = Math.max(Tb, Math.floor(Date.now() / 1000 / iv) * iv);
    const X = t => { if (t >= Tb) return xb + (t - Tb) / iv * spacing; const x = ts.timeToCoordinate(t); return x == null ? 0 : x; };
    const xLast = X(lastT);
    const Y = p => cs.priceToCoordinate(p);
    const txt = isLight() ? '#1f2937' : '#e0e0e0';
    g.save(); g.beginPath(); g.rect(0, 0, plotW, plotH); g.clip();
    const R = (x1, p1, x2, p2, fill) => {   // rectangle between two prices
      const ya = Y(p1), yb = Y(p2); if (ya == null || yb == null) return;
      g.fillStyle = fill; g.fillRect(Math.min(x1, x2), Math.min(ya, yb), Math.abs(x2 - x1), Math.max(1, Math.abs(yb - ya)));
    };
    const label = (s, x, p, align) => { const y = Y(p); if (y == null) return; g.font = '10px sans-serif'; g.fillStyle = txt; g.textAlign = align || 'left'; g.textBaseline = 'middle'; g.fillText(s, x, y); };
    // volume profile (left edge)
    if (S.vp) {
      const bins = S.vp, vpIn = b => !bins.last || Math.abs((b + 0.5) * CFG.vpBin / bins.last - 1) * 100 <= CFG.vpRangePct;
      const inb = [...bins.entries()].filter(([b]) => vpIn(b));
      const max = Math.max(1e-9, ...inb.map(x => x[1])); let poc = null, pv = -1;
      for (const [b, v] of inb) if (v > pv) { pv = v; poc = b; }
      for (const [b, v] of bins) { if (!vpIn(b)) continue;
        R(0, b * CFG.vpBin, (v / max) * CFG.vpWidthPct / 100 * plotW, (b + 1) * CFG.vpBin, b === poc ? CFG.vpPocColor : CFG.vpColor); }
      if (poc != null) label('POC ' + (poc * CFG.vpBin + CFG.vpBin / 2), 2, (poc + 0.5) * CFG.vpBin);
    }
    // liquidation clusters
    if (S.liq && S.spot) {
      const rows = S.liq.filter(r => Math.abs((r.b + 0.5) * CFG.liqBin / S.spot - 1) * 100 <= CFG.liqRangePct);
      const max = Math.max(1e-9, ...rows.map(r => r.tot));
      const topOf = lng => rows.filter(r => r.long === lng).sort((a, b) => b.tot - a.tot).slice(0, CFG.liqLabelsTop);
      const tops = new Set([...topOf(true), ...topOf(false)]);
      const x0 = plotW * CFG.liqStartPct / 100;
      for (const r of rows) {
        if (r.tot / max * 100 < CFG.liqMinPct) continue;
        const p1 = r.b * CFG.liqBin, p2 = p1 + CFG.liqBin, cols = r.long ? CFG.longLevColors : CFG.shortLevColors;
        if (CFG.liqHeatmap && r.tot / max * 100 >= CFG.liqHeatMinPct) {
          const [a0, a1] = CFG.liqHeatAlpha, al = a0 + (a1 - a0) * Math.pow(r.tot / max, 0.8);
          R(X(Math.round(r.ts / r.tot)), p1, xLast, p2, `rgba(${cols[2]},${al.toFixed(2)})`);
        }
        let x = x0; const totLen = plotW * (r.tot / max) * CFG.liqWidthPct / 100;
        r.lev.forEach((q, i) => { if (q <= 0) return;
          const len = Math.max(totLen * q / r.tot, plotW * 0.002);
          R(x, p1, x + len, p2, `rgba(${cols[i]},${CFG.liqBarAlpha})`); x += len; });
        if (tops.has(r)) label(`${r.long ? 'Long' : 'Short'} liq ${p1 + CFG.liqBin / 2} ~${r.tot.toFixed(0)} BTC`, x + 4, (p1 + p2) / 2);
      }
    }
    // option OI (right, ending at the current candle)
    if (S.oi) {
      const { call, put } = S.oi, max = Math.max(1e-9, ...call.values(), ...put.values()), h = 60;
      const top = m => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, CFG.oiLabelsTop).map(x => x[0]);
      const tc = top(call), tp = top(put);
      for (const [k, v] of call) if (v / max * 100 >= CFG.oiMinPct) { const len = (v / max) * CFG.oiWidthPct / 100 * plotW;
        R(xLast - len, k, xLast, k + h, CFG.callColor); if (tc.includes(k)) label(`CE ${k} OI ${v.toFixed(1)} BTC`, xLast - len, k + h / 2); }
      for (const [k, v] of put) if (v / max * 100 >= CFG.oiMinPct) { const len = (v / max) * CFG.oiWidthPct / 100 * plotW;
        R(xLast - len, k - h, xLast, k, CFG.putColor); if (tp.includes(k)) label(`PE ${k} OI ${v.toFixed(1)} BTC`, xLast - len, k - h / 2); }
    }
    // order book walls just right of the current candle
    const bk = S.book;
    if (bk) {
      const xs = xLast + spacing * CFG.bookGapBars;
      const wall = (m, color, tops) => { for (const [b, q] of m) if (q / bk.max * 100 >= CFG.bookMinPct) {
        const len = Math.max(spacing * CFG.bookWidthBars * (q / bk.max), spacing * 0.5);
        R(xs, b * CFG.bookBin, xs + len, (b + 1) * CFG.bookBin, color);
        if (tops.has(b)) label(`${q.toFixed(0)} BTC`, xs + 2, (b + 0.5) * CFG.bookBin); } };
      wall(bk.bidRows, CFG.bidColor, bk.tb); wall(bk.askRows, CFG.askColor, bk.ta);
      if (CFG.bookPocLine && bk.poc != null) {
        const pp = bk.poc * CFG.bookBin + CFG.bookBin / 2, y = Y(pp);
        if (y != null) { g.strokeStyle = 'rgba(255,193,7,0.9)'; g.setLineDash([6, 4]); g.lineWidth = 1; g.beginPath(); g.moveTo(0, y); g.lineTo(plotW, y); g.stroke(); g.setLineDash([]);
          g.font = '10px sans-serif'; g.fillStyle = isLight() ? '#b45309' : '#ffc107'; g.textAlign = 'center'; g.textBaseline = 'bottom';
          g.fillText(`Liq POC ${pp} (${bk.pSide} ${bk.pv.toFixed(1)} BTC)`, plotW * 0.5, y - 1); }
      }
      // readout box
      const sg = v => (v >= 0 ? '+' : '') + v.toFixed(2);
      const lean = bk.imbNear > 0.2 ? 'buy-heavy' : bk.imbNear < -0.2 ? 'sell-heavy' : 'balanced';
      const lines = [`BOOK  spread $${bk.spread.toFixed(1)}${bk.spread > 2 ? '  !! WIDE' : ''}`, `imbalance near ${sg(bk.imbNear)} (${lean})`,
                     `imbalance +-${CFG.bookImbPct}% ${sg(bk.imbFull)}`, `bids ${bk.B.toFixed(0)} BTC | asks ${bk.A.toFixed(0)} BTC`];
      g.font = '11px sans-serif'; const bw = Math.max(...lines.map(s => g.measureText(s).width)) + 12, bx = plotW * 0.30, by = 8, bh = lines.length * 15 + 8;
      g.fillStyle = 'rgba(30,34,45,0.85)'; g.fillRect(bx, by, bw, bh); g.strokeStyle = 'rgba(255,193,7,0.6)'; g.lineWidth = 1; g.strokeRect(bx, by, bw, bh);
      g.fillStyle = '#e0e0e0'; g.textAlign = 'left'; g.textBaseline = 'top'; lines.forEach((s, i) => g.fillText(s, bx + 6, by + 6 + i * 15));
      // ladder-level check labels
      for (const L of S.ladder) { const y = Y(L.pr); if (y == null) continue;
        g.font = '10px sans-serif'; g.fillStyle = L.ok ? '#26a69a' : '#9e9e9e'; g.textAlign = 'left'; g.textBaseline = 'bottom';
        g.fillText(`${L.ok ? 'bid support' : 'thin'} ${L.sz.toFixed(1)} BTC within +-${CFG.ladderTolPct}%`, plotW * 0.30, y - 2); }
    }
    g.restore();
  }
  let sig = '';
  function tick() {
    try {
      const ts = chart.timeScale(), lr = ts.getVisibleLogicalRange();
      const s = [lr && lr.from, lr && lr.to, cs.priceToCoordinate(80000), cs.priceToCoordinate(70000), wrap.clientWidth, wrap.clientHeight,
                 isLight(), sym, res, S.ver, ts.width(), Math.floor(Date.now() / 60000)].join('|');
      if (s !== sig) { sig = s; draw(); }
    } catch (e) {}
    requestAnimationFrame(tick);
  }
  tick();
  slowRefresh(); setInterval(slowRefresh, CFG.refreshMin * 60000);
  bookRefresh(); setInterval(bookRefresh, CFG.bookSec * 1000);
})();
