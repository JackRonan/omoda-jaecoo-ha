/*
 * Omoda / Jaecoo — Charging Energy Card
 * Single-file custom Lovelace card. No build step, no external deps.
 *
 * Istogramma dell'energia di ricarica per periodo, con selettore stile Energy:
 *   - Giorno    -> 24 barre orarie
 *   - Settimana -> 7 barre giornaliere
 *   - Mese      -> una barra per giorno
 * Barre impilate: VERDE = ricarica a casa (home), GIALLO = fuori casa (away).
 * Dati dalle statistiche a lungo termine (recorder/statistics_during_period, change).
 *
 * Config:
 *   type: custom:omoda-jaecoo-energy-card
 *   home_entity: sensor.home_charging_energy   # default
 *   away_entity: sensor.away_charging_energy    # default
 *   title: "Energia di ricarica"                # opzionale
 *   # striscia "in carica adesso" (potenza + orario fine + casa/fuori):
 *   power_entity: sensor.omoda_jaecoo_charging_power           # default
 *   remaining_entity: sensor.omoda_jaecoo_charge_remaining_time # default (min residui)
 *   charge_state_entity: sensor.omoda_jaecoo_charge_state       # default
 *   tracker_entity: device_tracker.location                     # default (home/away)
 *
 * Seme OOP (oggetti puri, testabili):
 *   DateRange   — mode + ancora -> {start,end,period,bins,label,step}
 *   StatsClient — wrapper WS recorder/statistics_during_period
 *   EnergyModel — allinea i bucket home/away nei bin del range
 *   LiveCharge  — stato "in carica adesso" (potenza, orario fine, casa/fuori)
 *   OmodaJaecooEnergyCard (HTMLElement) — selettore + render SVG + striscia live
 */

const GREEN = '#43c46d';   // home
const YELLOW = '#f2c94c';  // away

/* ────────────────────────────── i18n ────────────────────────────── */
// Base inglese (Home/Away coerenti con translations/en.json); traduzione italiana.
// Lingua auto-selezionata da hass.language, override con `language:` in config.
const STRINGS = {
  en: {
    title: 'Charging Energy',
    mode_day: 'Day', mode_week: 'Week', mode_month: 'Month',
    legend_home: 'Home', legend_away: 'Away',
    tip_home: 'home', tip_away: 'away',
    loading: 'Loading…',
    stats_unavailable: 'Statistics unavailable.',
    no_charging: 'No charging in this period.',
    aria_prev: 'Previous period', aria_next: 'Next period',
    aria_chart: 'Charging energy histogram',
    live_power: 'Charging power',
    live_eta: 'Full charge at',
    live_loc: 'Location',
    live_at_home: 'at home', live_away: 'away',
    live_idle: 'Not charging',
    live_done: 'Charge complete',
    months: ['January','February','March','April','May','June','July','August','September','October','November','December'],
    days: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
  },
  it: {
    title: 'Energia di ricarica',
    mode_day: 'Giorno', mode_week: 'Settimana', mode_month: 'Mese',
    legend_home: 'Casa', legend_away: 'Fuori casa',
    tip_home: 'casa', tip_away: 'fuori',
    loading: 'Carico…',
    stats_unavailable: 'Statistiche non disponibili.',
    no_charging: 'Nessuna ricarica in questo periodo.',
    aria_prev: 'Periodo precedente', aria_next: 'Periodo successivo',
    aria_chart: 'Istogramma energia di ricarica',
    live_power: 'Potenza di ricarica',
    live_eta: 'Carica completa alle',
    live_loc: 'Posizione',
    live_at_home: 'a casa', live_away: 'fuori casa',
    live_idle: 'Non in carica',
    live_done: 'Ricarica completata',
    months: ['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre'],
    days: ['lun','mar','mer','gio','ven','sab','dom'],
  },
};

function pickLang(config, hass) {
  const raw = (config && config.language) || (hass && hass.language) || 'en';
  const code = String(raw).slice(0, 2).toLowerCase();
  return STRINGS[code] ? code : 'en';
}
function tr(lang, key) { return (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key]; }

/* ────────────────────────────── DateRange ────────────────────────────── */
// Oggetto puro: dato mode ('day'|'week'|'month') e una data d'ancora (Date locale),
// produce start/end (Date), il period statistico e i bin [startMs,endMs).
class DateRange {
  constructor(mode, anchor, lang) {
    this.mode = mode;
    this.anchor = anchor;
    this.lang = lang || 'en';
    this.M = tr(this.lang, 'months');
    this.D = tr(this.lang, 'days');
  }

  static startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

  compute() {
    const a = this.anchor;
    if (this.mode === 'day') {
      const start = DateRange.startOfDay(a);
      const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1);
      const bins = [];
      for (let h = 0; h < 24; h++) {
        const s = new Date(start.getFullYear(), start.getMonth(), start.getDate(), h);
        const e = new Date(start.getFullYear(), start.getMonth(), start.getDate(), h + 1);
        bins.push({ s: s.getTime(), e: e.getTime(), label: String(h).padStart(2, '0'), tip: `${String(h).padStart(2,'0')}:00` });
      }
      return { start, end, period: 'hour', bins,
               label: `${a.getDate()} ${this.M[a.getMonth()]} ${a.getFullYear()}` };
    }
    if (this.mode === 'week') {
      const dow = (a.getDay() + 6) % 7;                  // lun=0
      const start = new Date(a.getFullYear(), a.getMonth(), a.getDate() - dow);
      const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7);
      const bins = [];
      for (let i = 0; i < 7; i++) {
        const s = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
        const e = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i + 1);
        bins.push({ s: s.getTime(), e: e.getTime(), label: this.D[i], tip: `${s.getDate()} ${this.M[s.getMonth()].slice(0,3)}` });
      }
      const last = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 1);
      return { start, end, period: 'day', bins,
               label: `${start.getDate()} ${this.M[start.getMonth()].slice(0,3)} – ${last.getDate()} ${this.M[last.getMonth()].slice(0,3)} ${last.getFullYear()}` };
    }
    // month
    const start = new Date(a.getFullYear(), a.getMonth(), 1);
    const end = new Date(a.getFullYear(), a.getMonth() + 1, 1);
    const days = Math.round((end - start) / 86400000);
    const bins = [];
    for (let i = 0; i < days; i++) {
      const s = new Date(start.getFullYear(), start.getMonth(), 1 + i);
      const e = new Date(start.getFullYear(), start.getMonth(), 2 + i);
      bins.push({ s: s.getTime(), e: e.getTime(), label: String(i + 1),
                  tip: `${i + 1} ${this.M[start.getMonth()].slice(0,3)}` });
    }
    return { start, end, period: 'day', bins,
             label: `${this.M[a.getMonth()]} ${a.getFullYear()}` };
  }

  shift(dir) {
    const a = this.anchor;
    if (this.mode === 'day')   return new Date(a.getFullYear(), a.getMonth(), a.getDate() + dir);
    if (this.mode === 'week')  return new Date(a.getFullYear(), a.getMonth(), a.getDate() + 7 * dir);
    return new Date(a.getFullYear(), a.getMonth() + dir, 1);
  }
}

/* ────────────────────────────── StatsClient ────────────────────────────── */
class StatsClient {
  constructor(hass) { this.hass = hass; }

  async fetch(ids, startISO, endISO, period) {
    const res = await this.hass.callWS({
      type: 'recorder/statistics_during_period',
      start_time: startISO,
      end_time: endISO,
      statistic_ids: ids,
      period,
      types: ['change'],
    });
    return res || {};
  }
}

/* ────────────────────────────── EnergyModel ────────────────────────────── */
// Allinea i bucket statistici (home/away) nei bin del range. Puro.
class EnergyModel {
  // stats: { [statId]: [{start, end, change}] } ; bins da DateRange.compute()
  static bin(stats, bins, homeId, awayId) {
    const parseStart = (b) => {
      const v = b.start;
      if (typeof v === 'number') return v;
      const t = Date.parse(v);
      return Number.isNaN(t) ? null : t;
    };
    const place = (arr) => {
      const out = new Array(bins.length).fill(0);
      for (const b of arr || []) {
        const ts = parseStart(b);
        if (ts === null) continue;
        const ch = Number(b.change);
        if (!Number.isFinite(ch) || ch <= 0) continue;     // energia non decresce
        // bin il cui intervallo contiene lo start del bucket
        for (let i = 0; i < bins.length; i++) {
          if (ts >= bins[i].s && ts < bins[i].e) { out[i] += ch; break; }
        }
      }
      return out;
    };
    const home = place(stats[homeId]);
    const away = place(stats[awayId]);
    const rows = bins.map((b, i) => ({ label: b.label, tip: b.tip, home: home[i], away: away[i] }));
    const totHome = home.reduce((a, b) => a + b, 0);
    const totAway = away.reduce((a, b) => a + b, 0);
    return { rows, totHome, totAway, total: totHome + totAway,
             max: Math.max(0, ...rows.map((r) => r.home + r.away)) };
  }
}

/* ────────────────────────────── LiveCharge ────────────────────────────── */
// Stato "in carica adesso" ricavato dagli stati grezzi (stringhe HA). Puro:
// nessun accesso a hass/DOM, così è testabile a parte.
//   power        — potenza istantanea (kW) da chargingPower
//   remain       — minuti residui da remainChargeTime (assente da fermo)
//   chargeState  — testo mappato ('Charging' / 'Not charging' / 'Charging completed')
//   tracker      — stato device_tracker ('home' ⇒ casa, altrimenti fuori)
class LiveCharge {
  static _num(v) {
    if (v === null || v === undefined) return null;
    if (v === 'unavailable' || v === 'unknown' || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  static read(power, remain, chargeState, tracker) {
    const p = LiveCharge._num(power);
    const rem = LiveCharge._num(remain);
    const s = (chargeState === null || chargeState === undefined) ? '' : String(chargeState).toLowerCase();
    // "Charging" ⇒ true; "Not charging" / "Charging completed" ⇒ false.
    const stateCharging = s.includes('charg') && !s.includes('not') && !s.includes('complet');
    const done = s.includes('complet');
    const charging = (p !== null && p > 0) || stateCharging;
    let location = null;               // 'home' | 'away' | null (posizione ignota)
    if (tracker !== null && tracker !== undefined) {
      const t = String(tracker).toLowerCase();
      if (t === 'home') location = 'home';
      else if (t && t !== 'unavailable' && t !== 'unknown' && t !== 'none') location = 'away';
    }
    return { charging, done, powerKw: p, remainMin: rem, location };
  }
}

/* ────────────────────────── OmodaJaecooEnergyCard ────────────────────────── */
class OmodaJaecooEnergyCard extends HTMLElement {
  static getStubConfig() { return { type: 'custom:omoda-jaecoo-energy-card' }; }

  setConfig(config) {
    this._config = config || {};
    this._home = this._config.home_entity || 'sensor.home_charging_energy';
    this._away = this._config.away_entity || 'sensor.away_charging_energy';
    // striscia "in carica adesso" (entità configurabili, default dell'integrazione)
    this._powerEntity = this._config.power_entity || 'sensor.omoda_jaecoo_charging_power';
    this._remainEntity = this._config.remaining_entity || 'sensor.omoda_jaecoo_charge_remaining_time';
    this._chargeStateEntity = this._config.charge_state_entity || 'sensor.omoda_jaecoo_charge_state';
    this._trackerEntity = this._config.tracker_entity || 'device_tracker.location';
    this._lang = 'en';            // ricalcolato al primo hass
    this._title = this._config.title || null;   // se null usa la traduzione
    this._mode = 'day';
    this._anchor = null;          // impostato al primo hass (evita Date fuori contesto)
    this._built = false;
    this._loading = false;
    this._data = null;
    this._error = null;
    this._reqId = 0;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._lang = pickLang(this._config, hass);
    if (this._anchor === null) this._anchor = DateRange.startOfDay(new Date());
    if (!this._built) { this._build(); this._built = true; }
    this._renderLive();            // stato live: aggiorna a ogni update di stato
    if (first) this._reload();
  }

  _t(key) { return tr(this._lang, key); }

  getCardSize() { return 6; }

  _range() { return new DateRange(this._mode, this._anchor, this._lang).compute(); }

  async _reload() {
    if (!this._hass) return;
    const r = this._range();
    const myReq = ++this._reqId;
    this._loading = true; this._error = null; this._renderChrome();
    try {
      const client = new StatsClient(this._hass);
      const stats = await client.fetch([this._home, this._away],
        r.start.toISOString(), r.end.toISOString(), r.period);
      if (myReq !== this._reqId) return;             // richiesta superata
      this._data = EnergyModel.bin(stats, r.bins, this._home, this._away);
    } catch (e) {
      if (myReq !== this._reqId) return;
      this._error = (e && e.message) ? e.message : String(e);
      this._data = null;
      // eslint-disable-next-line no-console
      console.error('[omoda-energy-card] statistiche non disponibili', e);
    } finally {
      if (myReq === this._reqId) { this._loading = false; this._renderAll(); }
    }
  }

  _setMode(mode) {
    if (mode === this._mode) return;
    // conserva il "presente" quando cambio granularità
    this._mode = mode;
    this._anchor = DateRange.startOfDay(new Date());
    this._reload();
  }

  _nav(dir) {
    this._anchor = new DateRange(this._mode, this._anchor, this._lang).shift(dir);
    this._reload();
  }

  _isFuture() {
    // disabilita "avanti" oltre il periodo corrente
    const now = new Date();
    const r = this._range();
    return r.end.getTime() > now.getTime() && this._sameOrAfterStart(r.start, now);
  }

  _sameOrAfterStart(start, now) {
    return now.getTime() >= start.getTime();
  }

  /* ---- rendering ---- */

  _build() {
    this.innerHTML = '';
    const card = document.createElement('ha-card');
    card.innerHTML = `
      <style>${OmodaJaecooEnergyCard.CSS}</style>
      <div class="hdr">
        <div class="title"></div>
        <div class="modes">
          <button data-mode="day">${this._t('mode_day')}</button>
          <button data-mode="week">${this._t('mode_week')}</button>
          <button data-mode="month">${this._t('mode_month')}</button>
        </div>
      </div>
      <div class="nav">
        <button class="prev" aria-label="${this._t('aria_prev')}">‹</button>
        <div class="range-label"></div>
        <button class="next" aria-label="${this._t('aria_next')}">›</button>
      </div>
      <div class="totals"></div>
      <div class="live"></div>
      <div class="chart"></div>
      <div class="legend">
        <span class="lg home">${this._t('legend_home')}</span>
        <span class="lg away">${this._t('legend_away')}</span>
      </div>`;
    this.appendChild(card);
    this._root = card;
    card.querySelector('.title').textContent = this._title || this._t('title');
    card.querySelector('.prev').addEventListener('click', () => this._nav(-1));
    card.querySelector('.next').addEventListener('click', () => this._nav(1));
    card.querySelectorAll('.modes button').forEach((b) => {
      b.addEventListener('click', () => this._setMode(b.dataset.mode));
    });
    this._renderChrome();
  }

  _renderChrome() {
    if (!this._root) return;
    const r = this._range();
    this._root.querySelector('.range-label').textContent = r.label;
    this._root.querySelectorAll('.modes button').forEach((b) => {
      b.classList.toggle('on', b.dataset.mode === this._mode);
    });
    this._root.querySelector('.next').disabled = this._isFuture();
  }

  _stateOf(entityId) {
    const st = this._hass && this._hass.states && this._hass.states[entityId];
    return st ? st.state : null;
  }

  // "adesso + minuti residui" → orario di fine (HH:MM, +data se cade un altro giorno).
  _fmtEta(remainMin) {
    if (remainMin === null || remainMin <= 0) return null;
    const now = new Date();
    const eta = new Date(now.getTime() + remainMin * 60000);
    const hhmm = `${String(eta.getHours()).padStart(2, '0')}:${String(eta.getMinutes()).padStart(2, '0')}`;
    if (eta.getDate() === now.getDate() && eta.getMonth() === now.getMonth()) return hhmm;
    const M = this._t('months');
    return `${hhmm} · ${eta.getDate()} ${M[eta.getMonth()].slice(0, 3)}`;
  }

  _renderLive() {
    if (!this._root) return;
    const el = this._root.querySelector('.live');
    if (!el) return;
    const lc = LiveCharge.read(
      this._stateOf(this._powerEntity),
      this._stateOf(this._remainEntity),
      this._stateOf(this._chargeStateEntity),
      this._stateOf(this._trackerEntity),
    );
    if (!lc.charging) {
      const msg = lc.done ? this._t('live_done') : this._t('live_idle');
      el.className = 'live idle';
      el.innerHTML = `<span class="dot"></span>${this._esc(msg)}`;
      return;
    }
    el.className = 'live on';
    const power = lc.powerKw !== null ? `${lc.powerKw.toFixed(1)} kW` : '—';
    const eta = this._fmtEta(lc.remainMin);
    const loc = lc.location === 'home'
      ? `🟢 ${this._t('live_at_home')}`
      : lc.location === 'away' ? `🟡 ${this._t('live_away')}` : '';
    let html =
      `<div class="live-row"><span class="lbl">⚡ ${this._t('live_power')}</span><span class="val">${this._esc(power)}</span></div>`;
    if (eta)
      html += `<div class="live-row"><span class="lbl">⏳ ${this._t('live_eta')}</span><span class="val">${this._esc(eta)}</span></div>`;
    if (loc)
      html += `<div class="live-row"><span class="lbl">📍 ${this._t('live_loc')}</span><span class="val">${this._esc(loc)}</span></div>`;
    el.innerHTML = html;
  }

  _renderAll() {
    this._renderChrome();
    const totalsEl = this._root.querySelector('.totals');
    const chartEl = this._root.querySelector('.chart');
    if (this._loading) { chartEl.innerHTML = `<div class="msg">${this._t('loading')}</div>`; return; }
    if (this._error)  { chartEl.innerHTML = `<div class="msg err">${this._t('stats_unavailable')}<br><small>${this._esc(this._error)}</small></div>`; totalsEl.textContent=''; return; }
    const d = this._data;
    if (!d || d.total <= 0) {
      totalsEl.innerHTML = `<span class="t total">0.00 kWh</span>`;
      chartEl.innerHTML = `<div class="msg">${this._t('no_charging')}</div>`;
      return;
    }
    totalsEl.innerHTML =
      `<span class="t total">${d.total.toFixed(2)} kWh</span>` +
      `<span class="t home">🟢 ${d.totHome.toFixed(2)}</span>` +
      `<span class="t away">🟡 ${d.totAway.toFixed(2)}</span>`;
    chartEl.innerHTML = this._svg(d);
  }

  _svg(d) {
    const W = 640, H = 220, padL = 34, padR = 8, padT = 10, padB = 22;
    const iw = W - padL - padR, ih = H - padT - padB;
    const n = d.rows.length;
    const bw = iw / n;
    const barw = Math.max(1, bw * 0.72);
    const max = d.max > 0 ? d.max : 1;
    // "nice" scala superiore
    const niceMax = this._niceCeil(max);
    const y = (v) => padT + ih - (v / niceMax) * ih;
    // gridlines (4)
    let grid = '';
    for (let g = 0; g <= 4; g++) {
      const val = (niceMax * g) / 4;
      const gy = y(val);
      grid += `<line x1="${padL}" y1="${gy.toFixed(1)}" x2="${W-padR}" y2="${gy.toFixed(1)}" class="grid"/>`;
      grid += `<text x="${padL-4}" y="${(gy+3).toFixed(1)}" class="ytick">${this._fmt(val)}</text>`;
    }
    let bars = '';
    let labels = '';
    const showEvery = n > 16 ? (n >= 28 ? 5 : 3) : 1;
    d.rows.forEach((r, i) => {
      const cx = padL + bw * i + (bw - barw) / 2;
      const hHome = (r.home / niceMax) * ih;
      const hAway = (r.away / niceMax) * ih;
      const yHome = padT + ih - hHome;
      const yAway = yHome - hAway;
      const tip = `${r.tip}: ${(r.home + r.away).toFixed(2)} kWh\n🟢 ${this._t('tip_home')} ${r.home.toFixed(2)} · 🟡 ${this._t('tip_away')} ${r.away.toFixed(2)}`;
      bars += `<g><title>${this._esc(tip)}</title>`;
      if (hHome > 0) bars += `<rect x="${cx.toFixed(1)}" y="${yHome.toFixed(1)}" width="${barw.toFixed(1)}" height="${hHome.toFixed(1)}" rx="1.5" class="b-home"/>`;
      if (hAway > 0) bars += `<rect x="${cx.toFixed(1)}" y="${yAway.toFixed(1)}" width="${barw.toFixed(1)}" height="${hAway.toFixed(1)}" rx="1.5" class="b-away"/>`;
      if (hHome <= 0 && hAway <= 0) bars += `<rect x="${cx.toFixed(1)}" y="${(padT+ih-1).toFixed(1)}" width="${barw.toFixed(1)}" height="1" class="b-zero"/>`;
      bars += `</g>`;
      if (i % showEvery === 0)
        labels += `<text x="${(cx + barw/2).toFixed(1)}" y="${H-6}" class="xtick">${r.label}</text>`;
    });
    return `<svg viewBox="0 0 ${W} ${H}" class="plot" role="img" aria-label="${this._esc(this._t('aria_chart'))}">
      ${grid}
      <line x1="${padL}" y1="${padT+ih}" x2="${W-padR}" y2="${padT+ih}" class="axis"/>
      ${bars}
      ${labels}
    </svg>`;
  }

  _niceCeil(v) {
    if (v <= 0) return 1;
    const pow = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / pow;
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * pow;
  }
  _fmt(v) { return v >= 10 ? v.toFixed(0) : v.toFixed(1); }
  _esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
}

/* ────────────────────────────── CSS ────────────────────────────── */
OmodaJaecooEnergyCard.CSS = `
  ha-card { padding: 12px 14px 14px; }
  .hdr { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
  .title { font-weight:700; font-size:1.1rem; color:var(--primary-text-color); }
  .modes { display:flex; gap:4px; }
  .modes button { border:none; background:var(--secondary-background-color); color:var(--primary-text-color);
    padding:4px 10px; border-radius:14px; cursor:pointer; font-size:.82rem; }
  .modes button.on { background:var(--primary-color); color:var(--text-primary-color,#fff); font-weight:600; }
  .nav { display:flex; align-items:center; justify-content:center; gap:12px; margin:8px 0 2px; }
  .nav button { border:none; background:transparent; color:var(--primary-text-color); font-size:1.4rem;
    cursor:pointer; line-height:1; padding:0 6px; border-radius:8px; }
  .nav button:hover:not(:disabled) { background:var(--secondary-background-color); }
  .nav button:disabled { opacity:.3; cursor:default; }
  .range-label { min-width:180px; text-align:center; font-weight:600; color:var(--primary-text-color); }
  .totals { display:flex; gap:14px; align-items:baseline; justify-content:center; margin:2px 0 6px; flex-wrap:wrap; }
  .totals .total { font-size:1.25rem; font-weight:700; color:var(--primary-text-color); }
  .totals .home, .totals .away { font-size:.9rem; color:var(--secondary-text-color); }
  .live { margin:2px 0 10px; }
  .live.on { border:1px solid var(--divider-color, rgba(127,127,127,.25)); border-radius:12px;
    padding:8px 12px; background:var(--secondary-background-color); }
  .live-row { display:flex; align-items:baseline; justify-content:space-between; gap:12px;
    padding:3px 0; font-size:.92rem; }
  .live-row + .live-row { border-top:1px dashed var(--divider-color, rgba(127,127,127,.2)); }
  .live-row .lbl { color:var(--secondary-text-color); }
  .live-row .val { font-weight:700; color:var(--primary-text-color); font-variant-numeric:tabular-nums; }
  .live.idle { display:flex; align-items:center; justify-content:center; gap:8px;
    color:var(--secondary-text-color); font-size:.85rem; }
  .live.idle .dot { width:8px; height:8px; border-radius:50%;
    background:var(--divider-color, rgba(127,127,127,.5)); }
  .chart { width:100%; }
  .plot { display:block; width:100%; height:auto; }
  .grid { stroke:var(--divider-color, rgba(127,127,127,.25)); stroke-width:1; }
  .axis { stroke:var(--divider-color, rgba(127,127,127,.5)); stroke-width:1; }
  .ytick { fill:var(--secondary-text-color); font-size:9px; text-anchor:end; }
  .xtick { fill:var(--secondary-text-color); font-size:9px; text-anchor:middle; }
  .b-home { fill:${GREEN}; }
  .b-away { fill:${YELLOW}; }
  .b-zero { fill:var(--divider-color, rgba(127,127,127,.4)); }
  .msg { text-align:center; color:var(--secondary-text-color); padding:28px 8px; }
  .msg.err { color:var(--error-color,#c62828); }
  .legend { display:flex; gap:16px; justify-content:center; margin-top:6px; font-size:.8rem; color:var(--secondary-text-color); }
  .lg::before { content:''; display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
  .lg.home::before { background:${GREEN}; }
  .lg.away::before { background:${YELLOW}; }
`;

/* ────────────────────────────── registrazione ────────────────────────────── */
if (!customElements.get('omoda-jaecoo-energy-card')) {
  customElements.define('omoda-jaecoo-energy-card', OmodaJaecooEnergyCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'omoda-jaecoo-energy-card',
  name: 'Omoda / Jaecoo Charging Energy Card',
  description: 'Charging-energy histogram (home green / away yellow) with an Energy-style period selector.',
  preview: false,
});
// eslint-disable-next-line no-console
console.info('%c OMODA-JAECOO-ENERGY-CARD %c loaded ', 'background:#43c46d;color:#062;', '');
