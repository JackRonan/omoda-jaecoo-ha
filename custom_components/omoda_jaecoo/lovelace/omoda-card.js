/*
 * Omoda / Jaecoo vehicle card — sleek summary.
 *
 * At-a-glance: vehicle photo, name, battery %, estimated range, charging state, and
 * warnings (tyre / low battery / offline) shown only when something's wrong.
 * Auto-discovers this integration's entities, so minimal config just works:
 *   type: custom:omoda-card
 * Options:
 *   title: "My Car"          # header title (default: the vehicle's name)
 *   image: "/local/car.png"  # header photo (overrides the one set in the integration options)
 *   show_all: true           # also list every remaining entity, grouped
 *   entities: [...]          # append your own rows (entity ids)
 *   integration: "omoda_jaecoo"  # platform to collect (default)
 *   prefix: "omoda_jaecoo_"      # object_id fallback prefix
 */
class OmodaCard extends HTMLElement {
  setConfig(config) {
    this.config = Object.assign(
      { integration: "omoda_jaecoo", prefix: "omoda_jaecoo_", show_all: false },
      config || {}
    );
  }
  getCardSize() { return 4; }

  _dead(s) { return !s || ["unavailable", "unknown", ""].includes(s.state); }
  _num(s) { const n = s ? parseFloat(s.state) : NaN; return isNaN(n) ? null : n; }
  // Display a value the way Home Assistant would: respects the entity's display precision
  // (so "145.4008… mi" shows as "145 mi" if you set 0 decimals) and unit conversion.
  _disp(s) {
    const h = this._hass;
    if (h && typeof h.formatEntityState === "function") {
      try { return h.formatEntityState(s); } catch (e) { /* fall through */ }
    }
    const n = parseFloat(s.state);
    const u = s.attributes.unit_of_measurement;
    if (isNaN(n)) return u ? `${s.state} ${u}` : s.state;
    const dp = s.attributes.suggested_display_precision;
    const v = typeof dp === "number" ? n.toFixed(dp) : (Number.isInteger(n) ? `${n}` : `${Math.round(n)}`);
    return u ? `${v} ${u}` : v;
  }

  _collect(hass) {
    const c = this.config, out = [];
    const strip = (o) => o.startsWith(c.prefix) ? o.slice(c.prefix.length) : o;
    const reg = hass.entities;
    if (reg) for (const id in reg) {
      if (reg[id].platform !== c.integration) continue;
      const s = hass.states[id]; if (s) out.push({ id, key: strip(id.slice(id.indexOf(".") + 1)), s });
    }
    if (!out.length) for (const id in hass.states) {
      const o = id.slice(id.indexOf(".") + 1);
      if (o.startsWith(c.prefix)) out.push({ id, key: strip(o), s: hass.states[id] });
    }
    return out;
  }

  _find(items, ...keys) {
    for (const k of keys) { const f = items.find((r) => r.key === k); if (f) return f; }
    return null;
  }

  _batteryIcon(v, charging) {
    if (charging) return "mdi:battery-charging";
    if (isNaN(v)) return "mdi:battery";
    const s = Math.round(v / 10) * 10;
    return s >= 100 ? "mdi:battery" : s <= 0 ? "mdi:battery-outline" : `mdi:battery-${s}`;
  }
  _batteryColor(v) {
    if (isNaN(v)) return "var(--primary-text-color)";
    if (v <= 15) return "#e5484d";
    if (v <= 30) return "#f5a623";
    return "#3dd68c";
  }
  _moreInfo(id) {
    this.dispatchEvent(new CustomEvent("hass-more-info",
      { bubbles: true, composed: true, detail: { entityId: id } }));
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.content) {
      const card = document.createElement("ha-card");
      const style = document.createElement("style");
      style.textContent = `
        ha-card { overflow: hidden; }
        .hero { position: relative; min-height: 132px; display: flex; align-items: flex-end;
          background: linear-gradient(135deg, var(--primary-color) 0%, color-mix(in srgb, var(--primary-color) 55%, #000) 100%);
          background-size: cover; background-position: center; }
        .hero.photo { min-height: 190px; }
        .scrim { position: absolute; inset: 0;
          background: linear-gradient(to top, rgba(0,0,0,.66) 0%, rgba(0,0,0,.15) 55%, rgba(0,0,0,0) 100%); }
        .hero-content { position: relative; width: 100%; padding: 16px; display: flex;
          align-items: flex-end; justify-content: space-between; gap: 12px; color: #fff; }
        .name { font-size: 1.35rem; font-weight: 700; line-height: 1.15; text-shadow: 0 1px 4px rgba(0,0,0,.55); }
        .sub { font-size: .82rem; opacity: .9; margin-top: 2px; text-shadow: 0 1px 3px rgba(0,0,0,.5);
          display: flex; align-items: center; gap: 6px; }
        .sub ha-icon { --mdc-icon-size: 16px; }
        .batt { display: flex; align-items: center; gap: 7px; padding: 7px 12px; cursor: pointer;
          background: rgba(0,0,0,.32); border-radius: 999px; backdrop-filter: blur(6px); }
        .batt ha-icon { --mdc-icon-size: 22px; }
        .batt b { font-size: 1.15rem; font-weight: 700; }
        .metrics { display: flex; }
        .metric { flex: 1; padding: 13px 14px; cursor: pointer; text-align: center;
          border-right: 1px solid var(--divider-color, rgba(127,127,127,.18)); }
        .metric:last-child { border-right: none; }
        .metric:hover { background: var(--secondary-background-color); }
        .metric .v { font-size: 1.1rem; font-weight: 700; color: var(--primary-text-color); }
        .metric .l { font-size: .72rem; letter-spacing: .02em; text-transform: uppercase;
          color: var(--secondary-text-color); margin-top: 3px; display: flex; align-items: center;
          justify-content: center; gap: 5px; }
        .metric .l ha-icon { --mdc-icon-size: 14px; }
        .warns { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px;
          border-top: 1px solid var(--divider-color, rgba(127,127,127,.18)); }
        .warn { display: flex; align-items: center; gap: 6px; font-size: .82rem; font-weight: 600;
          color: #e5484d; background: rgba(229,72,77,.13); padding: 5px 11px; border-radius: 999px; cursor: pointer; }
        .warn ha-icon { --mdc-icon-size: 15px; }
        .grp { padding: 12px 16px 2px; font-weight: 600; font-size: .85rem; color: var(--secondary-text-color);
          border-top: 1px solid var(--divider-color, rgba(127,127,127,.18)); }
        .row { display: flex; justify-content: space-between; padding: 7px 16px; cursor: pointer; font-size: .95rem; }
        .row:hover { background: var(--secondary-background-color); }
        .row .val { font-weight: 600; }
      `;
      this.content = document.createElement("div");
      card.appendChild(style); card.appendChild(this.content); this.appendChild(card);
      this.content.addEventListener("click", (e) => {
        const el = e.target.closest("[data-e]");
        if (el) this._moreInfo(el.getAttribute("data-e"));
      });
    }
    this._render(hass);
  }

  _render(hass) {
    const cfg = this.config;
    const items = this._collect(hass);
    const nameSrc = items.find((r) => r.s.attributes.friendly_name)?.s.attributes.friendly_name;
    const device = nameSrc ? nameSrc.split(" ").slice(0, 2).join(" ") : "Omoda / Jaecoo";
    const title = cfg.title || device;

    const bat = this._find(items, "battery") || items.find((r) =>
      r.s.attributes.device_class === "battery" && r.s.attributes.unit_of_measurement === "%");
    const range = this._find(items, "range_electric", "range_total", "range_combined_estimate");
    const chargeState = this._find(items, "charge_state");
    const charging = this._find(items, "charging");
    const plug = this._find(items, "charge_plug");
    const odo = this._find(items, "odometer");
    const isCharging = charging ? charging.s.state === "on"
      : (chargeState && /charg/i.test(chargeState.s.state) && !/not/i.test(chargeState.s.state));
    const batV = bat ? this._num(bat.s) : NaN;

    // ---- hero (photo or gradient) ----
    const img = cfg.image || items.map((r) => r.s.attributes.vehicle_image).find(Boolean) || "";
    const chargeSub = isCharging
      ? `<div class="sub"><ha-icon icon="mdi:flash"></ha-icon>Charging${range && !this._dead(range.s) ? ` · ${this._disp(range.s)}` : ""}</div>`
      : (range && !this._dead(range.s) ? `<div class="sub"><ha-icon icon="mdi:map-marker-distance"></ha-icon>${this._disp(range.s)} range</div>` : "");
    const battBadge = (bat && !this._dead(bat.s))
      ? `<div class="batt" data-e="${bat.id}">
           <ha-icon icon="${this._batteryIcon(batV, isCharging)}" style="color:${this._batteryColor(batV)}"></ha-icon>
           <b>${isNaN(batV) ? bat.s.state : Math.round(batV)}%</b></div>`
      : "";
    const hero = `
      <div class="hero ${img ? "photo" : ""}" style="${img ? `background-image:url('${img}')` : ""}">
        <div class="scrim"></div>
        <div class="hero-content">
          <div><div class="name">${title}</div>${chargeSub}</div>
          ${battBadge}
        </div>
      </div>`;

    // ---- metrics strip (range · charging · odometer) ----
    const metric = (label, icon, s, textFallback) => {
      const v = s && !this._dead(s.s) ? this._disp(s.s) : (textFallback || "—");
      return `<div class="metric" ${s && s.id ? `data-e="${s.id}"` : ""}>
        <div class="v">${v}</div><div class="l"><ha-icon icon="${icon}"></ha-icon>${label}</div></div>`;
    };
    const chargeText = charging && !this._dead(charging.s) ? (isCharging ? "Charging" : "Idle")
      : (chargeState && !this._dead(chargeState.s) ? chargeState.s.state : "—");
    const metrics = `<div class="metrics">
      ${metric("Range", "mdi:map-marker-distance", range)}
      ${metric("Charging", isCharging ? "mdi:battery-charging" : "mdi:power-plug",
          { id: (charging || chargeState || {}).id, s: { state: chargeText, attributes: {} } })}
      ${odo ? metric("Odometer", "mdi:counter", odo)
        : (plug ? metric("Cable", "mdi:power-plug",
            { id: plug.id, s: { state: plug.s.state === "on" ? "Plugged in" : "Unplugged", attributes: {} } }) : "")}
    </div>`;

    // ---- warnings (only active) ----
    const warns = [];
    items.filter((r) => /tire.*warning|tyre.*warning/.test(r.key) && r.s.state === "on")
      .forEach((r) => warns.push({ id: r.id, icon: "mdi:car-tire-alert",
        text: (r.s.attributes.friendly_name || r.key).replace(new RegExp("^" + device + "\\s*", "i"), "").replace(/warning/i, "").trim() }));
    const low = this._find(items, "battery_low");
    if (low && low.s.state === "on") warns.push({ id: low.id, icon: "mdi:battery-alert", text: "Battery low" });
    const conn = this._find(items, "connection");
    if (conn && conn.s.state === "off") warns.push({ id: conn.id, icon: "mdi:wifi-off", text: "Offline" });
    const warnHtml = warns.length ? `<div class="warns">${warns.map((w) =>
      `<div class="warn" data-e="${w.id}"><ha-icon icon="${w.icon}"></ha-icon>${w.text}</div>`).join("")}</div>` : "";

    // ---- optional extra rows / full list ----
    let extra = "";
    const used = new Set([bat, range, chargeState, charging, plug, odo, low, conn].filter(Boolean).map((r) => r.id));
    const rowFor = (id) => {
      const s = hass.states[id]; if (!s) return "";
      const name = (s.attributes.friendly_name || id).replace(new RegExp("^" + device + "\\s*", "i"), "").trim() || id;
      return `<div class="row" data-e="${id}"><div>${name}</div><div class="val">${this._disp(s)}</div></div>`;
    };
    if (Array.isArray(cfg.entities) && cfg.entities.length) {
      extra = `<div class="grp">Details</div>` + cfg.entities.map((e) => rowFor(typeof e === "string" ? e : e.entity)).join("");
    } else if (cfg.show_all) {
      const rest = items.filter((r) => !used.has(r.id) && !this._dead(r.s) && r.s.attributes.entity_category !== "diagnostic");
      if (rest.length) extra = `<div class="grp">More</div>` +
        rest.sort((a, b) => a.key.localeCompare(b.key)).map((r) => rowFor(r.id)).join("");
    }

    this.content.innerHTML = hero + metrics + warnHtml + extra;
  }

  static getStubConfig() { return { type: "custom:omoda-card" }; }
}
customElements.define("omoda-card", OmodaCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "omoda-card",
  name: "Omoda/Jaecoo Card",
  preview: true,
  description: "Sleek summary card for the Omoda/Jaecoo integration (photo, battery, range, charging, warnings).",
});
