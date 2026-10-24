// ==UserScript==
// @name         Delta BTCUSD – Volume profile + Option OI overlay (Sudip)
// @namespace    sudip.btc.ladder
// @version      1.4
// @description  Draws a volume profile (left), estimated liquidation clusters (left-centre) and BTC option open interest by strike (right) as horizontal bars on the Delta Exchange BTCUSD chart. Read-only public market data; never places or touches orders.
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
    vpDays: 7,                // look-back in days
    vpRes: '15m',             // candle size used to build the profile
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
    liqBin: 200,
    liqRangePct: 12,
    liqMinPct: 8,
    liqBuckets: [[10, 0.35], [25, 0.30], [50, 0.20], [100, 0.15]],   // assumed leverage mix
    liqMmr: 0.004,
    longLiqColor: 'rgba(255,87,34,0.55)',    // longs that get liquidated (below price)
    shortLiqColor: 'rgba(76,175,80,0.55)',   // shorts that get liquidated (above price)
    liqLabelsTop: 2,          // label the N biggest long and short clusters
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
            cl.push({ p: close * (1 - 1 / L + CFG.liqMmr), q: d * lf * w, long: true });
            cl.push({ p: close * (1 + 1 / L - CFG.liqMmr), q: d * (1 - lf) * w, long: false });
          }
        } else if (d < 0 && prev > 0) { const f = o / prev; for (const x of cl) x.q *= f; }
      }
      prev = o;
    }
    const lb = new Map(), sb = new Map();
    for (const x of cl) { const m = x.long ? lb : sb; const b = Math.floor(x.p / CFG.liqBin); m.set(b, (m.get(b) || 0) + x.q); }
    return { lb, sb };
  }

  async function draw() {
    const c = await getChart(); if (!c) return;
    const vr = c.getVisibleRange();
    clearOwn(c);
    let spot = 0;
    if (CFG.vpOn) {
      const bins = await volumeProfile();
      const max = Math.max(...bins.values());
      let poc = null, pv = -1;
      for (const [b, v] of bins) if (v > pv) { pv = v; poc = b; }
      for (const [b, v] of bins) {
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
        const { lb, sb } = await liquidation();
        const inR = b => Math.abs((b + 0.5) * CFG.liqBin / spot - 1) * 100 <= CFG.liqRangePct;
        const all = [...lb.entries(), ...sb.entries()].filter(([b]) => inR(b));
        const max = Math.max(1e-9, ...all.map(x => x[1]));
        const top = m => [...m.entries()].filter(([b]) => inR(b)).sort((a, b) => b[1] - a[1]).slice(0, CFG.liqLabelsTop).map(x => x[0]);
        const tl = top(lb), ts = top(sb);
        for (const [m, col, tops, nm] of [[lb, CFG.longLiqColor, tl, 'Long liq'], [sb, CFG.shortLiqColor, ts, 'Short liq']])
          for (const [b, v] of m) {
            if (!inR(b) || v / max * 100 < CFG.liqMinPct) continue;
            bar(c, 'left', vr, (v / max) * CFG.liqWidthPct / 100, b * CFG.liqBin, (b + 1) * CFG.liqBin, col,
                tops.includes(b) ? `${nm} ${b * CFG.liqBin + CFG.liqBin / 2} ~${v.toFixed(0)} BTC` : '', CFG.liqStartPct);
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
