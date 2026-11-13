// ==UserScript==
// @name         Delta BTCUSD – Volume profile + Option OI overlay (Sudip)
// @namespace    sudip.btc.ladder
// @version      1.8
// @description  Draws a volume profile (left), estimated liquidation clusters (left-centre), BTC option open interest by strike (right) and a small black positioning table (Binance long/short, top traders, taker, open-interest change) on the Delta Exchange BTCUSD chart. Read-only public market data; never places or touches orders.
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
    // positioning table (Binance BTCUSDT; information only - research showed weak direction edge)
    tblOn: true,
    tblTop: 52,               // px from the top of the page
    tblZwin: 500,             // hours used for the z-score (about 21 days; Binance returns at most 500 rows)
  };
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
      try { const t = c.getShapeById(s.id).getProperties().text || ''; if (t.startsWith(TAG)) c.removeEntity(s.id); } catch (e) {}
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


  // ---------------- positioning table (black box, top centre) ----------------
  function mean(a) { return a.reduce((x, y) => x + y, 0) / (a.length || 1); }
  function zscore(arr) {                       // z of the last value vs the whole array
    const m = mean(arr), sd = Math.sqrt(mean(arr.map(v => (v - m) * (v - m)))) || 1e-9;
    return (arr[arr.length - 1] - m) / sd;
  }
  async function positioning() {
    const B = 'https://fapi.binance.com/futures/data/';
    const g = async u => (await fetch(B + u)).json();
    const n = 500;
    const [ga, tp, tk, oi] = await Promise.all([
      g('globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=' + n),
      g('topLongShortPositionRatio?symbol=BTCUSDT&period=1h&limit=' + n),
      g('takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=' + n),
      g('openInterestHist?symbol=BTCUSDT&period=1h&limit=' + (n + 24))]);
    const out = {};
    const a = ga.map(r => Math.log(+r.longShortRatio)); out.all = { v: +ga[ga.length - 1].longShortRatio, d24: +ga[ga.length - 25].longShortRatio, z: zscore(a) };
    const t = tp.map(r => Math.log(+r.longShortRatio)); out.top = { v: +tp[tp.length - 1].longShortRatio, d24: +tp[tp.length - 25].longShortRatio, z: zscore(t) };
    const tr = tk.map(r => +r.buySellRatio); const tl = tr.slice(-24); out.taker = { v: mean(tl), z: zscore(tr.map((_, i) => mean(tr.slice(Math.max(0, i - 23), i + 1)))) };
    const o = oi.map(r => +r.sumOpenInterest); const ch = []; for (let i = 24; i < o.length; i++) ch.push(Math.log(o[i] / o[i - 24]));
    out.oi = { chg: (Math.exp(ch[ch.length - 1]) - 1) * 100, z: zscore(ch), val: o[o.length - 1] };
    out.t = ga[ga.length - 1].timestamp;
    return out;
  }
  function tblHtml(P) {
    const col = z => (Math.abs(z) >= 1.5 ? '#ffb300' : '#cfd8dc');
    const row = (name, v, d, z) => `<tr><td style="text-align:left;padding:1px 8px">${name}</td><td style="text-align:right;padding:1px 6px;color:#fff">${v}</td><td style="text-align:right;padding:1px 6px;color:#90a4ae">${d}</td><td style="text-align:right;padding:1px 6px;color:${col(z)}">${z >= 0 ? '+' : ''}${z.toFixed(1)}</td></tr>`;
    const arrow = (a, b) => (a > b ? '▲' : a < b ? '▼' : '■');
    const watch = P.oi.z >= 1.5 ? '<div style="color:#ffb300;padding:2px 8px">OI jump: bigger move than usual likely in next 24h (range, not direction)</div>' : '';
    const T = new Date(P.t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
    return `<div style="display:flex;justify-content:space-between;padding:2px 8px;color:#90a4ae"><span>Binance BTCUSDT positioning</span><span>${T} <b id="sTblX" style="cursor:pointer;color:#ef5350">×</b></span></div>
<table style="border-collapse:collapse;font-size:11px"><tr style="color:#78909c"><td></td><td style="text-align:right;padding:0 6px">now</td><td style="text-align:right;padding:0 6px">24h ago</td><td style="text-align:right;padding:0 6px">z (21d)</td></tr>
${row('All accounts L/S', P.all.v.toFixed(2) + ' ' + arrow(P.all.v, P.all.d24), P.all.d24.toFixed(2), P.all.z)}
${row('Top traders L/S (pos)', P.top.v.toFixed(2) + ' ' + arrow(P.top.v, P.top.d24), P.top.d24.toFixed(2), P.top.z)}
${row('Taker buy/sell 24h', P.taker.v.toFixed(2), '', P.taker.z)}
${row('Open interest 24h', (P.oi.chg >= 0 ? '+' : '') + P.oi.chg.toFixed(1) + '%', (P.oi.val / 1000).toFixed(1) + 'k BTC', P.oi.z)}
</table>${watch}<div style="padding:2px 8px;color:#546e7a;font-size:10px">info only - weak direction edge in 6-yr test</div>`;
  }
  async function drawTable() {
    if (!CFG.tblOn) return;
    try {
      if (localStorage.getItem('sTblHide') === '1') { const o = document.getElementById('sTbl'); if (o) o.remove(); return; }
      const P = await positioning();
      let box = document.getElementById('sTbl');
      if (!box) {
        box = document.createElement('div'); box.id = 'sTbl';
        box.style.cssText = `position:fixed;top:${CFG.tblTop}px;left:50%;transform:translateX(-50%);z-index:99999;background:rgba(0,0,0,0.88);border:1px solid #37474f;border-radius:6px;font:11px/1.35 system-ui,sans-serif;color:#cfd8dc;padding:3px 0;pointer-events:auto`;
        document.body.appendChild(box);
      }
      box.innerHTML = tblHtml(P);
      const x = document.getElementById('sTblX'); if (x) x.onclick = () => { try { localStorage.setItem('sTblHide', '1'); } catch (e) {} box.remove(); };
    } catch (e) { console.warn('positioning table', e); }
  }

  async function draw() {
    const c = await getChart(); if (!c) return;
    const vr = c.getVisibleRange();
    drawTable();
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

  let timer = null;
  async function start() {
    const c = await getChart(); if (!c) return;
    await draw();
    setInterval(draw, CFG.refreshMin * 60000);
    try { c.onVisibleRangeChanged().subscribe(null, () => { clearTimeout(timer); timer = setTimeout(draw, 1500); }); } catch (e) {}
  }
  start();
})();
