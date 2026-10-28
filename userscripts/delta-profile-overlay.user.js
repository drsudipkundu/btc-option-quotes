// ==UserScript==
// @name         Delta BTCUSD – Volume profile + Option OI overlay (Sudip)
// @namespace    sudip.btc.ladder
// @version      1.8
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
    liqBin: 100,              // USD per row (finer)
    liqRangePct: 12,
    liqMinPct: 3,             // hide rows below N % of the biggest row
    liqHeatmap: true,         // Coinglass-style bands: from when the cluster formed until now
    liqHeatMinPct: 6,         // only rows at least N % of the biggest get a band
    liqHeatAlpha: [0.06, 0.40],
    liqBuckets: [[10, 0.35], [25, 0.30], [50, 0.20], [100, 0.15]],   // assumed leverage mix
    liqMmr: 0.004,
    // shades per leverage, lightest = 10x ... darkest = 100x (longs liquidated below price / shorts above)
    longLevColors: ['255,204,128', '255,138,101', '244,81,30', '183,28,28'],
    shortLevColors: ['200,230,201', '129,199,132', '56,142,60', '27,94,32'],
    liqBarAlpha: 0.7,
    liqLabelsTop: 4,          // label the N biggest long and short rows
    // live order book (Delta public L2 book) - refreshed often, separate from the slow layers above
    bookOn: true,
    bookSec: 15,              // refresh every N seconds
    bookDepth: 1000,          // levels per side requested (about +-2.4 % of price)
    bookBin: 25,              // USD per row
    bookRangePct: 1.2,        // show rows within +-N % of price
    bookMinPct: 15,           // hide rows below N % of the biggest row
    bookStartPct: 50,         // bars start this % from the left edge
    bookWidthPct: 14,
    bidColor: 'rgba(38,166,154,0.55)',
    askColor: 'rgba(239,83,80,0.55)',
    bookLabelsTop: 2,         // label the N biggest bid and ask rows
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
        const max = Math.max(1e-9, ...rows.map(r => r.tot));
        const topOf = lng => rows.filter(r => r.long === lng).sort((a, b) => b.tot - a.tot).slice(0, CFG.liqLabelsTop);
        const tops = new Set([...topOf(true), ...topOf(false)]);
        const span = vr.to - vr.from, x0 = vr.from + span * CFG.liqStartPct / 100;
        const R = Math.min(vr.to, Math.floor(Date.now() / 1000));
        for (const r of rows) {
          if (r.tot / max * 100 < CFG.liqMinPct) continue;
          const p1 = r.b * CFG.liqBin, p2 = p1 + CFG.liqBin, cols = r.long ? CFG.longLevColors : CFG.shortLevColors;
          // heatmap band behind the candles, from the size-weighted time the cluster formed until now
          if (CFG.liqHeatmap && r.tot / max * 100 >= CFG.liqHeatMinPct) {
            const t0 = Math.max(vr.from, Math.round(r.ts / r.tot)), [a0, a1] = CFG.liqHeatAlpha;
            const al = a0 + (a1 - a0) * Math.pow(r.tot / max, 0.8);
            if (t0 < R) c.createMultipointShape([{ time: t0, price: p1 }, { time: R, price: p2 }], {
              shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
              overrides: { backgroundColor: `rgba(${cols[2]},${al.toFixed(2)})`, color: 'rgba(0,0,0,0)', fillBackground: true, linewidth: 0, text: TAG, showLabel: false } });
          }
          // side profile: one segment per leverage, stacked left to right (10x lightest ... 100x darkest)
          let x = x0;
          const totLen = span * (r.tot / max) * CFG.liqWidthPct / 100;
          r.lev.forEach((q, i) => {
            if (q <= 0) return;
            const len = Math.max(totLen * q / r.tot, span * 0.002), last = i === r.lev.length - 1 || r.lev.slice(i + 1).every(z => z <= 0);
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
  function bbar(c, vr, frac, p1, p2, color, text) {
    const span = vr.to - vr.from, len = Math.max(span * frac, span * 0.003);
    const a = vr.from + span * CFG.bookStartPct / 100;
    return c.createMultipointShape([{ time: Math.round(a), price: p1 }, { time: Math.round(a + len), price: p2 }], {
      shape: 'rectangle', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
      overrides: { backgroundColor: color, color: 'rgba(0,0,0,0)', fillBackground: true, linewidth: 0,
                   text: TAGB + (text || ''), showLabel: !!text, textColor: '#e0e0e0', fontSize: 10,
                   horzLabelsAlign: 'left', vertLabelsAlign: 'middle' } });
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
      const mk = (m, color, tops, side) => { for (const [b, q] of m) if (q / max * 100 >= CFG.bookMinPct)
        bbar(c, vr, (q / max) * CFG.bookWidthPct / 100, b * CFG.bookBin, (b + 1) * CFG.bookBin, color,
             tops.has(b) ? `${side} ${(b * CFG.bookBin + CFG.bookBin / 2)} ${q.toFixed(1)} BTC` : ''); };
      mk(bidRows, CFG.bidColor, tb, 'Bid wall'); mk(askRows, CFG.askColor, ta, 'Ask wall');
      if (CFG.bookPocLine && poc != null) {
        const pp = poc * CFG.bookBin + CFG.bookBin / 2;
        c.createShape({ time: Math.round(vr.from + (vr.to - vr.from) * CFG.bookStartPct / 100), price: pp }, {
          shape: 'horizontal_line', lock: true, disableSelection: true, disableSave: true, disableUndo: true,
          overrides: { linecolor: 'rgba(255,193,7,0.85)', linestyle: 2, linewidth: 1, showLabel: true,
                       text: `${TAGB}Liq POC ${pp} (${pSide} ${pv.toFixed(1)} BTC)`, textcolor: '#ffc107', horzLabelsAlign: 'left', vertLabelsAlign: 'top', fontsize: 10 } });
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
            if (s.name !== 'horizontal_line') continue;
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
