// ==UserScript==
// @name         Delta BTCUSD – Volume profile + Option OI overlay (Sudip)
// @namespace    sudip.btc.ladder
// @version      2.0
// @description  Draws a volume profile (left), estimated liquidation clusters (left-centre), live order-book walls with a readout box (centre-right) and BTC option open interest by strike (right) as horizontal bars on the Delta Exchange BTCUSD chart. Read-only public market data; never places or touches orders.
// @match        https://www.delta.exchange/app/futures/trade/BTC/BTCUSD*
// @match        https://india.delta.exchange/app/futures/trade/BTC/BTCUSD*
// @grant        none
// @sandbox      raw
// @inject-into  page
// @updateURL    https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/userscripts/delta-profile-overlay.user.js
// @downloadURL  https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/userscripts/delta-profile-overlay.user.js
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ---------------- settings (change freely) ----------------
  const CFG = {
    api: 'https://api.india.delta.exchange/v2',
    refreshMin: 5,            // redraw every N minutes
    // volume profile
    vpOn: true,
    vpSide: 'left',           // 'left' or 'right'
    vpDays: 90,               // look-back in days (long enough to cover the liquidation range)
    vpRangePct: 12,           // show rows within ±N % of price (same as liquidation)
    vpRes: '4h',              // candle size used to build the profile
    vpBin: 200,               // USD per price row
    vpWidthPct: 22,           // longest bar = this % of visible chart width
    vpColor: 'rgba(158,158,158,0.30)',
    vpPocColor: 'rgba(255,193,7,0.55)',   // highest-volume row
    // option open interest by strike
    oiOn: true,
    oiSide: 'right',          // 'left' or 'right'
    oiMaxDays: 7,             // only expiries within N days (1 = daily only)
    oiRangePct: 12,           // only strikes within ±N % of price
    oiWidthPct: 22,
    callColor: 'rgba(244,67,54,0.45)',
    putColor: 'rgba(0,150,136,0.45)',
    oiLabelsTop: 3,           // label the N biggest call and put strikes
    oiMinPct: 8,              // hide strikes whose OI is below N % of the biggest strike
    // estimated liquidation clusters (Binance BTCUSDT open interest + long/short accounts, same model as liquidation-clusters tool)
    liqOn: true,
    liqStartPct: 24,          // bars start this % from the left edge (just right of the volume profile)
    liqWidthPct: 20,
    liqBin: 50,               // USD per row (finer)
    liqNearPct: 4,            // within N % of price the bars get their own scale, so near-price levels are not dwarfed by far ones
    liqNearLabels: 3,         // label the N biggest rows per side inside that zone
    liqRangePct: 12,
    liqMinPct: 5,             // hide rows below N % of the biggest row
    liqHeatmap: true,         // Coinglass-style bands: from when the cluster formed until now
    liqHeatMinPct: 6,         // only rows at least N % of the biggest get a band
    liqHeatAlpha: [0.06, 0.40],
    liqBuckets: [[5, 0.06], [10, 0.20], [15, 0.12], [20, 0.12], [25, 0.14], [33, 0.10], [50, 0.10], [75, 0.08], [100, 0.05], [125, 0.03]],   // assumed leverage mix (more levels = also levels close to price)
    liqMmr: 0.004,
    // shades per leverage, lightest = 10x ... darkest = 100x (longs liquidated below price / shorts above)
    longLevColors: ['255,236,179', '255,204,128', '255,183,77', '255,152,0', '255,112,67', '244,81,30', '216,67,21', '191,54,12', '183,28,28', '136,14,14'],
    shortLevColors: ['220,237,200', '200,230,201', '165,214,167', '129,199,132', '102,187,106', '67,160,71', '56,142,60', '46,125,50', '27,94,32', '10,60,20'],
    liqBarAlpha: 0.7,
    liqLabelsTop: 4,          // label the N biggest long and short rows
    // live order book (Delta public L2 book) - refreshed often, separate from the slow layers above
    bookOn: true,
    bookSec: 15,              // refresh every N seconds
    bookDepth: 1000,          // levels per side requested (about +-2.4 % of price)
    bookBin: 10,              // USD per row
    bookRangePct: 1.0,        // show rows within +-N % of price
    bookMinPct: 6,            // hide rows below N % of the biggest row
    bookGapBars: 1,           // walls start this many candles right of the current candle
    bookWidthBars: 8,         // longest wall = this many candles long (needs that much empty space on the right: drag the chart left)
    bidColor: 'rgba(38,166,154,0.55)',
    askColor: 'rgba(239,83,80,0.55)',
    bidNew: 'rgba(120,255,220,0.95)',   // brighter piece = added since about a minute ago; outline = eaten or pulled
    askNew: 'rgba(255,170,160,0.95)',
    bookChgSec: 60,           // compare with the book about N seconds ago
    bookChgPct: 3,            // a change counts when it is at least N % of the biggest row
    bookLabelsTop: 3,         // label the N biggest bid and ask rows
    bookImbPct: 1,            // book imbalance measured within +-N % of price
    bookTopN: 10,             // 'near' imbalance uses the best N levels each side
    bookPocLine: true,        // amber dashed line at the liquidity POC (biggest resting row)
    ladderCheck: true,        // for each of your green 'buy' lines: is there a bid wall within +-0.1 %?
    ladderTolPct: 0.1,
    ladderStrong: 1.5,        // 'support' = bid size at least N x the average row
    contractBtc: 0.001,       // BTC per contract on Delta
  };
  const TAGB = '\u00a7\u00a7';   // book-layer shapes start with two section signs; the slow layers never delete them
  const TAG = '§';            // every shape this script draws has text starting with §

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function getChart() {
    for (let i = 0; i < 120; i++) {
      const f = [...document.querySelectorAll('iframe')].find(x => x.id && x.id.startsWith('tradingview'));
      try {
        const api = f && f.contentWindow.tradingViewApi;
        const c = api && api.activeChart();
        if (c && c.getVisibleRange().from) return c;
      } catch (e) {}
      await sleep(1000);
    }
    return null;
  }
  async function j(url) { const r = await fetch(url); return (await r.json()).result || []; }

  function clearOwn(c) {
    for (const s of c.getAllShapes()) {
      try { const t = c.getShapeById(s.id).getProperties().text || ''; if (t.startsWith(TAG) && !t.startsWith(TAGB)) c.removeEntity(s.id); } catch (e) {}
    }
  }
  function bar(c, side, vr, frac, p1, p2, color, text, offPct) {
    const span = vr.to - vr.from;
    const len = Math.max(span * frac, span * 0.003);
    const R = Math.min(vr.to, Math.floor(Date.now() / 1000));   // right edge = last candle (future area snaps coarsely)
    const L0 = vr.from + span * (offPct || 0) / 100;
    const a = side === 'left' ? L0 : R - len;
    const b = side === 'left' ? L0 + len : R;
    return c.createMultipointShape([{ time: Math.round(a), price: p1 }, { time: Math.round(b), price: p2 }], {
      shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      overrides: { backgroundColor: color, color: 'rgba(0,0,0,0)', fillBackground: true, linewidth: 0,
                   text: TAG + (text || ''), showLabel: !!text, textColor: '#e0e0e0', fontSize: 10,
                   horzLabelsAlign: side === 'left' ? 'left' : 'right', vertLabelsAlign: 'middle' },
    });
  }

  async function volumeProfile() {
    const now = Math.floor(Date.now() / 1000);
    const cs = await j(`${CFG.api}/history/candles?resolution=${CFG.vpRes}&symbol=BTCUSD&start=${now - CFG.vpDays * 86400}&end=${now}`);
    const bins = new Map();
    for (const k of cs) {
      const lo = Math.floor(k.low / CFG.vpBin), hi = Math.floor(k.high / CFG.vpBin), n = hi - lo + 1;
      for (let b = lo; b <= hi; b++) bins.set(b, (bins.get(b) || 0) + k.volume / n);
    }
    bins.last = cs.length ? cs.reduce((a, k) => (k.time > a.time ? k : a)).close : 0;   // Delta returns newest first
    return bins;
  }
  async function optionOI(spot) {
    const t = await j(`${CFG.api}/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC`);
    const lim = Date.now() + CFG.oiMaxDays * 86400000;
    const call = new Map(), put = new Map();
    for (const o of t) {
      const m = /-(\d{2})(\d{2})(\d{2})$/.exec(o.symbol || '');               // ...-DDMMYY
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
    const g = async u => (await fetch(B + u)).json();
    const [oi, ls, kl] = await Promise.all([
      g('/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=500'),
      g('/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=500'),
      g('/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=500')]);
    const oiT = new Map(oi.map(r => [Math.floor(r.timestamp / 3600000), +r.sumOpenInterest]));
    const lsT = new Map(ls.map(r => [Math.floor(r.timestamp / 3600000), +r.longAccount]));
    let cl = [];   // {p, q, long}
    let prev = null;
    for (const k of kl) {
      const h = Math.floor(k[0] / 3600000) + 1;       // OI stamped at the close of this candle
      const hi = +k[2], lo = +k[3], close = +k[4];
      cl = cl.filter(x => x.long ? x.p < lo : x.p > hi);   // price traded through -> liquidated
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
    // rows: key = side|bin -> total, per-leverage split, size-weighted birth time
    const rows = new Map();
    const li = new Map(CFG.liqBuckets.map(([L], i) => [L, i]));
    for (const x of cl) {
      const b = Math.floor(x.p / CFG.liqBin), key = (x.long ? 'L' : 'S') + b;
      let r = rows.get(key); if (!r) { r = { long: x.long, b, tot: 0, lev: CFG.liqBuckets.map(() => 0), ts: 0 }; rows.set(key, r); }
      r.tot += x.q; r.lev[li.get(x.L)] += x.q; r.ts += x.q * x.t;
    }
    return [...rows.values()];
  }

  async function draw() {
    const c = await getChart(); if (!c) return;
    const vr = c.getVisibleRange();
    clearOwn(c);
    let spot = 0;
    if (CFG.vpOn) {
      const bins = await volumeProfile();
      const vpIn = b => !bins.last || Math.abs((b + 0.5) * CFG.vpBin / bins.last - 1) * 100 <= CFG.vpRangePct;
      const inb = [...bins.entries()].filter(([b]) => vpIn(b));
      const max = Math.max(1e-9, ...inb.map(x => x[1]));
      let poc = null, pv = -1;
      for (const [b, v] of inb) if (v > pv) { pv = v; poc = b; }
      for (const [b, v] of bins) {
        if (!vpIn(b)) continue;
        bar(c, CFG.vpSide, vr, (v / max) * CFG.vpWidthPct / 100, b * CFG.vpBin, (b + 1) * CFG.vpBin,
            b === poc ? CFG.vpPocColor : CFG.vpColor, b === poc ? 'POC ' + (b * CFG.vpBin + CFG.vpBin / 2) : '');
      }
      spot = (poc + 0.5) * CFG.vpBin;
    }
    if (CFG.oiOn) {
      try { const tk = await j(`${CFG.api}/tickers/BTCUSD`); spot = +tk.mark_price || +tk.close || spot; } catch (e) {}
      const { call, put } = await optionOI(spot);
      const max = Math.max(1e-9, ...call.values(), ...put.values());
      const top = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, CFG.oiLabelsTop).map(x => x[0]);
      const tc = top(call), tp = top(put);
      const h = 60; // half-height of each strike bar in USD
      for (const [k, v] of call) if (v / max * 100 >= CFG.oiMinPct) bar(c, CFG.oiSide, vr, (v / max) * CFG.oiWidthPct / 100, k, k + h, CFG.callColor,
                                     tc.includes(k) ? `CE ${k} OI ${v.toFixed(1)} BTC` : '');
      for (const [k, v] of put) if (v / max * 100 >= CFG.oiMinPct) bar(c, CFG.oiSide, vr, (v / max) * CFG.oiWidthPct / 100, k - h, k, CFG.putColor,
                                    tp.includes(k) ? `PE ${k} OI ${v.toFixed(1)} BTC` : '');
    }
    if (CFG.liqOn) {
      try {
        if (!spot) { const tk = await j(`${CFG.api}/tickers/BTCUSD`); spot = +tk.mark_price || spot; }
        const rows = (await liquidation()).filter(r => Math.abs((r.b + 0.5) * CFG.liqBin / spot - 1) * 100 <= CFG.liqRangePct);
        const near = r => Math.abs((r.b + 0.5) * CFG.liqBin / spot - 1) * 100 <= CFG.liqNearPct;
        const max = Math.max(1e-9, ...rows.map(r => r.tot)), maxN = Math.max(1e-9, ...rows.filter(near).map(r => r.tot));
        const topOf = lng => rows.filter(r => r.long === lng).sort((a, b) => b.tot - a.tot).slice(0, CFG.liqLabelsTop);
        const nearTop = lng => rows.filter(r => r.long === lng && near(r)).sort((a, b) => b.tot - a.tot).slice(0, CFG.liqNearLabels);
        const tops = new Set([...topOf(true), ...topOf(false), ...nearTop(true), ...nearTop(false)]);
        const span = vr.to - vr.from, x0 = vr.from + span * CFG.liqStartPct / 100;
        const R = Math.min(vr.to, Math.floor(Date.now() / 1000));
        for (const r of rows) {
          const mx = near(r) ? maxN : max;
          if (r.tot / mx * 100 < CFG.liqMinPct) continue;
          const p1 = r.b * CFG.liqBin, p2 = p1 + CFG.liqBin, cols = r.long ? CFG.longLevColors : CFG.shortLevColors;
          // heatmap band behind the candles, from the size-weighted time the cluster formed until now
          if (CFG.liqHeatmap && r.tot / mx * 100 >= CFG.liqHeatMinPct) {
            const t0 = Math.max(vr.from, Math.round(r.ts / r.tot)), [a0, a1] = CFG.liqHeatAlpha;
            const al = a0 + (a1 - a0) * Math.pow(r.tot / mx, 0.8);
            if (t0 < R) c.createMultipointShape([{ time: t0, price: p1 }, { time: R, price: p2 }], {
              shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
              overrides: { backgroundColor: `rgba(${cols[Math.min(5, cols.length - 1)]},${al.toFixed(2)})`, color: 'rgba(0,0,0,0)', fillBackground: true, linewidth: 0, text: TAG, showLabel: false } });
          }
          // side profile: one segment per leverage, stacked left to right (10x lightest ... 100x darkest)
          let x = x0;
          const totLen = span * (r.tot / mx) * CFG.liqWidthPct / 100;
          r.lev.forEach((q, i) => {
            if (q <= 0) return;
            const len = Math.max(totLen * q / r.tot, span * 0.003), last = i === r.lev.length - 1 || r.lev.slice(i + 1).every(z => z <= 0);
            const lab = last && tops.has(r) ? `${r.long ? 'Long' : 'Short'} liq ${p1 + CFG.liqBin / 2} ~${r.tot.toFixed(0)} BTC` : '';
            c.createMultipointShape([{ time: Math.round(x), price: p1 }, { time: Math.round(x + len), price: p2 }], {
              shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
              overrides: { backgroundColor: `rgba(${cols[i]},${CFG.liqBarAlpha})`, color: 'rgba(0,0,0,0)', fillBackground: true, linewidth: 0,
                           text: TAG + lab, showLabel: !!lab, textColor: '#e0e0e0', fontSize: 10, horzLabelsAlign: 'left', vertLabelsAlign: 'middle' } });
            x += len;
          });
        }
      } catch (e) { console.warn('liq overlay', e); }
    }
  }


  // ---------------- live order-book layer (v1.8) ----------------
  function clearBook(c) {
    for (const s of c.getAllShapes()) {
      try { const t = c.getShapeById(s.id).getProperties().text || ''; if (t.startsWith(TAGB)) c.removeEntity(s.id); } catch (e) {}
    }
  }
  function ivSec(c) {
    try { const r = String(c.resolution()); let m;
      if (/^\d+$/.test(r)) return +r * 60;
      if ((m = /^(\d+)S$/i.exec(r))) return +m[1];
      if ((m = /^(\d*)D$/i.exec(r))) return (+m[1] || 1) * 86400;
      if ((m = /^(\d*)W$/i.exec(r))) return (+m[1] || 1) * 604800;
      if ((m = /^(\d+)h$/i.exec(r))) return +m[1] * 3600; } catch (e) {}
    return 3600;
  }
  const bookHist = [];   // recent book snapshots, to show what was added or pulled
  const BL = (iv, frac) => Math.max(iv * CFG.bookWidthBars * frac, iv * 0.4);
  function bbar(c, vr, frac, p1, p2, color, text, opt) {
    const iv = ivSec(c), last = Math.floor(Date.now() / 1000 / iv) * iv;   // open time of the current candle
    opt = opt || {};
    const a = last + iv * CFG.bookGapBars, len = BL(iv, frac), a0 = opt.from != null ? a + BL(iv, opt.from) : a;
    return c.createMultipointShape([{ time: Math.round(a0), price: p1 }, { time: Math.round(a + len), price: p2 }], {
      shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      overrides: { backgroundColor: color, color: opt.outline ? color : 'rgba(0,0,0,0)', fillBackground: !opt.outline, linewidth: opt.outline ? 1 : 0,
                   text: TAGB + (text || ''), showLabel: !!text, textColor: '#e0e0e0', fontSize: 10,
                   horzLabelsAlign: 'left', vertLabelsAlign: 'middle' } });
  }
  function blabel(c, frac, price, text) {   // the quantity label is its own text shape (a rectangle's own label is clipped when the row is thin)
    const iv = ivSec(c), last = Math.floor(Date.now() / 1000 / iv) * iv, a = last + iv * CFG.bookGapBars;
    return c.createShape({ time: Math.round(a + BL(iv, frac) + iv * 0.15), price }, {
      shape: 'text', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      overrides: { text: TAGB + text, color: '#e0e0e0', fontsize: 10, fillBackground: false, drawBorder: false, backgroundTransparency: 100 } });
  }
  function topPrice(c, spot) {
    try { const r = c.getPanes()[0].getRightPriceScales()[0].getVisiblePriceRange(); if (r && r.to) return r.to - (r.to - r.from) * 0.04; } catch (e) {}
    return spot * 1.02;
  }
  let bookBusy = false;
  async function drawBook() {
    if (!CFG.bookOn || bookBusy) return;
    bookBusy = true;
    try {
      const c = await getChart(); if (!c) return;
      const vr = c.getVisibleRange();
      const res = await (await fetch(`${CFG.api}/l2orderbook/BTCUSD?depth=${CFG.bookDepth}`)).json();
      const bids = (res.result.buy || []).map(x => [+x.price, x.size * CFG.contractBtc]).filter(x => x[0] > 100);
      const asks = (res.result.sell || []).map(x => [+x.price, x.size * CFG.contractBtc]).filter(x => x[0] < 1e6);
      if (!bids.length || !asks.length) return;
      const bb = bids[0][0], ba = asks[0][0], mid = (bb + ba) / 2, spread = ba - bb;
      const lim = mid * CFG.bookRangePct / 100;
      const rowsOf = list => { const m = new Map(); for (const [p, q] of list) if (Math.abs(p - mid) <= lim) { const b = Math.floor(p / CFG.bookBin); m.set(b, (m.get(b) || 0) + q); } return m; };
      const bidRows = rowsOf(bids), askRows = rowsOf(asks);
      const max = Math.max(1e-9, ...bidRows.values(), ...askRows.values());
      const topKeys = m => new Set([...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, CFG.bookLabelsTop).map(x => x[0]));
      const tb = topKeys(bidRows), ta = topKeys(askRows);
      // imbalance
      const sumWithin = (list, pct) => list.reduce((a, [p, q]) => a + (Math.abs(p - mid) <= mid * pct / 100 ? q : 0), 0);
      const B = sumWithin(bids, CFG.bookImbPct), A = sumWithin(asks, CFG.bookImbPct);
      const nb = bids.slice(0, CFG.bookTopN).reduce((a, x) => a + x[1], 0), na = asks.slice(0, CFG.bookTopN).reduce((a, x) => a + x[1], 0);
      const imbFull = (B - A) / (B + A), imbNear = (nb - na) / (nb + na);
      // liquidity POC = biggest single row on either side
      let poc = null, pv = -1, pSide = '';
      for (const [b, q] of bidRows) if (q > pv) { pv = q; poc = b; pSide = 'bid'; }
      for (const [b, q] of askRows) if (q > pv) { pv = q; poc = b; pSide = 'ask'; }
      clearBook(c);
      const nowT = Date.now(); bookHist.push({ t: nowT, bidRows, askRows });
      while (bookHist.length > 2 && nowT - bookHist[1].t > CFG.bookChgSec * 1000 + 20000) bookHist.shift();
      const old = bookHist.length > 1 && nowT - bookHist[0].t >= 20000 ? bookHist[0] : null;
      const thr = CFG.bookChgPct / 100 * max, items = [];
      const collect = (m, pm, color, newCol, tops) => {
        for (const [b, q] of m) if (q / max * 100 >= CFG.bookMinPct) {
          const p0 = pm ? (pm.get(b) || 0) : q, dq = q - p0, top = tops.has(b), changed = !!pm && Math.abs(dq) > thr;
          items.push({ b, q, p0, dq, color, newCol, changed, pr: (top ? 1e6 : 0) + Math.abs(dq) + q, want: top || (!!pm && Math.abs(dq) > 3 * thr),
                       text: `${q.toFixed(0)} BTC` + (changed ? ` (${dq > 0 ? '+' : ''}${dq.toFixed(0)})` : '') });
        }
        if (pm) for (const [b, p0] of pm) if (!m.has(b) && p0 > 4 * thr) items.push({ b, q: 0, p0, dq: -p0, color, newCol, pulled: true, pr: p0, want: true, text: `pulled ${p0.toFixed(0)}` });
      };
      collect(bidRows, old && old.bidRows, CFG.bidColor, CFG.bidNew, tb); collect(askRows, old && old.askRows, CFG.askColor, CFG.askNew, ta);
      let sep = mid * 0.0004;   // minimum price distance between two labels (about 11 px)
      try { const r = c.getPanes()[0].getRightPriceScales()[0].getVisiblePriceRange(), h = c.getPanes()[0].getHeight(); if (r && h > 50) sep = (r.to - r.from) / h * 11; } catch (e) {}
      const used = [], chosen = new Set();
      items.filter(x => x.want).sort((a, b) => b.pr - a.pr).slice(0, 14).forEach(x => { const y = (x.b + 0.5) * CFG.bookBin; if (used.some(u => Math.abs(u - y) < sep)) return; used.push(y); chosen.add(x); });
      for (const x of items) {
        const p1 = x.b * CFG.bookBin, p2 = (x.b + 1) * CFG.bookBin, lab = chosen.has(x) ? x.text : '';
        if (x.pulled) { bbar(c, vr, x.p0 / max, p1, p2, x.newCol, '', { outline: true }); if (lab) blabel(c, x.p0 / max, p2, lab); continue; }
        bbar(c, vr, x.q / max, p1, p2, x.color, '');
        if (lab) blabel(c, Math.max(x.q, x.p0) / max, p2, lab);
        if (x.changed && x.dq > 0) bbar(c, vr, x.q / max, p1, p2, x.newCol, '', { from: x.p0 / max });      // added since about a minute ago
        if (x.changed && x.dq < 0) bbar(c, vr, x.p0 / max, p1, p2, x.newCol, '', { outline: true, from: x.q / max });   // eaten or pulled
      }
      if (CFG.bookPocLine && poc != null) {
        const pp = poc * CFG.bookBin + CFG.bookBin / 2;
        c.createShape({ time: Math.round(vr.from + (vr.to - vr.from) * 0.5), price: pp }, {
          shape: 'horizontal_line', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
          overrides: { linecolor: 'rgba(255,193,7,0.85)', linestyle: 2, linewidth: 1, showLabel: true,
                       text: `${TAGB}Liq POC ${pp} (${pSide} ${pv.toFixed(1)} BTC)`, textcolor: '#ffc107', horzLabelsAlign: 'center', vertLabelsAlign: 'top', fontsize: 10 } });
      }
      // readout box
      const sg = v => (v >= 0 ? '+' : '') + v.toFixed(2);
      const flag = spread > 2 ? '  !! WIDE' : '';
      const lean = imbNear > 0.2 ? 'buy-heavy' : imbNear < -0.2 ? 'sell-heavy' : 'balanced';
      const txt = `${TAGB}BOOK  spread $${spread.toFixed(1)}${flag}\nimbalance near ${sg(imbNear)} (${lean})\nimbalance +-${CFG.bookImbPct}% ${sg(imbFull)}\nbids ${B.toFixed(0)} BTC | asks ${A.toFixed(0)} BTC`;
      c.createShape({ time: Math.round(vr.from + (vr.to - vr.from) * 0.30), price: topPrice(c, mid) }, {
        shape: 'text', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
        overrides: { text: txt, color: '#e0e0e0', fontsize: 11, backgroundColor: 'rgba(30,34,45,0.85)', fillBackground: true,
                     drawBorder: true, borderColor: 'rgba(255,193,7,0.6)' } });
      // ladder-level check on the existing green 'buy' lines (read only; labels are our own)
      if (CFG.ladderCheck) {
        const avg = ([...bidRows.values()].reduce((a, b) => a + b, 0) / Math.max(1, bidRows.size)) || 1e-9;
        const lowBid = bids[bids.length - 1][0];
        for (const s of c.getAllShapes()) {
          try {
            if (!/line|ray/.test(s.name)) continue;
            const sh = c.getShapeById(s.id), t = (sh.getProperties().text || '');
            if (t.startsWith(TAG) || !/buy\s*0\.00/i.test(t)) continue;
            const pr = sh.getPoints()[0].price;
            if (pr < lowBid || pr >= bb) continue;                 // outside the loaded book
            const sz = bids.reduce((a, [p, q]) => a + (Math.abs(p - pr) <= pr * CFG.ladderTolPct / 100 ? q : 0), 0);
            const rowSz = sz / Math.max(1, (2 * pr * CFG.ladderTolPct / 100) / CFG.bookBin);
            const ok = rowSz >= CFG.ladderStrong * avg;
            c.createShape({ time: Math.round(vr.from + (vr.to - vr.from) * 0.30), price: pr }, {
              shape: 'text', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
              overrides: { text: `${TAGB}${ok ? 'bid support' : 'thin'} ${sz.toFixed(1)} BTC within +-${CFG.ladderTolPct}%`,
                           color: ok ? '#26a69a' : '#9e9e9e', fontsize: 10 } });
          } catch (e) {}
        }
      }
    } catch (e) { console.warn('book overlay', e); } finally { bookBusy = false; }
  }

  let timer = null;
  async function start() {
    const c = await getChart(); if (!c) return;
    await draw();
    setInterval(draw, CFG.refreshMin * 60000);
    await drawBook();
    setInterval(drawBook, CFG.bookSec * 1000);
    try { c.onVisibleRangeChanged().subscribe(null, () => { clearTimeout(timer); timer = setTimeout(() => { draw(); drawBook(); }, 1500); }); } catch (e) {}
  }
  start();
})();
