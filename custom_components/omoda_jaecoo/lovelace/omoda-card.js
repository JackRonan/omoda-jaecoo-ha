/*
 * Omoda / Jaecoo vehicle card — curated summary.
 *
 * Shows the important things at a glance: vehicle name, battery %, charging state,
 * estimated range, and (only when there's a problem) warnings — tyre pressure, low
 * battery, lost connection. Auto-discovers this integration's entities, so minimal
 * config just works:
 *   type: custom:omoda-card
 * Options:
 *   title: "My Car"        # header title (default: the device/friendly name)
 *   image: "/local/car.png" # header background image
 *   entities: [...]        # extra rows to append (entity ids or {entity,name,icon})
 *   show_all: true         # append every remaining integration entity, grouped
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
  getCardSize() { return 5; }

  _dead(s) { return !s || ["unavailable", "unknown", ""].includes(s.state); }
  _num(s) { const n = s ? parseFloat(s.state) : NaN; return isNaN(n) ? null : n; }
  _fmt(s) { const u = s.attributes.unit_of_measurement; return u ? `${s.state} ${u}` : s.state; }

  // Collect this integration's entities: platform match (catches unprefixed sensor.battery),
  // object_id-prefix fallback for older frontends.
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
    if (v <= 15) return "var(--error-color, #db4437)";
    if (v <= 30) return "var(--warning-color, #ffa600)";
    return "var(--success-color, #43a047)";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.content) {
      const card = document.createElement("ha-card");
      const style = document.createElement("style");
      style.textContent = `
        .header { position: relative; padding: 16px; display: flex; justify-content: space-between;
          align-items: center; gap: 12px; }
        .header.img { padding-top: 40%; background-size: cover; background-position: center; }
        .header.img .overlay { position: absolute; inset: 0;
          background: linear-gradient(to top, rgba(0,0,0,.55), rgba(0,0,0,0) 60%); }
        .header.img .title, .header.img .bat-pct { color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,.8); }
        .head-row { position: absolute; left: 16px; right: 16px; bottom: 12px;
          display: flex; justify-content: space-between; align-items: flex-end; }
        .title { font-size: 1.3rem; font-weight: 600; }
        .bat { display: flex; align-items: center; gap: 8px; }
        .bat ha-icon { --mdc-icon-size: 30px; }
        .bat-pct { font-size: 1.5rem; font-weight: 700; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
          background: var(--divider-color, rgba(0,0,0,.1)); }
        .stat { background: var(--ha-card-background, var(--card-background-color, #fff));
          padding: 12px 16px; cursor: pointer; }
        .stat:hover { background: var(--secondary-background-color); }
        .stat .label { color: var(--secondary-text-color); font-size: .8rem; display: flex;
          align-items: center; gap: 6px; }
        .stat .label ha-icon { --mdc-icon-size: 16px; }
        .stat .value { font-size: 1.15rem; font-weight: 600; margin-top: 2px; }
        .warnings { padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 8px;
          border-top: 1px solid var(--divider-color, rgba(0,0,0,.1)); }
        .warn { display: flex; align-items: center; gap: 6px; font-size: .85rem; font-weight: 600;
          color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent);
          padding: 4px 10px; border-radius: 14px; cursor: pointer; }
        .warn ha-icon { --mdc-icon-size: 16px; }
        .group-title { padding: 12px 16px 2px; font-weight: 600; font-size: .9rem;
          border-top: 1px solid var(--divider-color, rgba(0,0,0,.1)); }
        .row { display: flex; justify-content: space-between; padding: 6px 16px; cursor: pointer; }
        .row:hover { background: var(--secondary-background-color); }
        .row .name { color: var(--primary-text-color); }
        .row .val { font-weight: 600; }
      `;
      this.content = document.createElement("div");
      card.appendChild(style); card.appendChild(this.content); this.appendChild(card);
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
    const range = this._find(items, "range_electric", "range_total", "range_combined_estimate", "range_gasoline");
    const chargeState = this._find(items, "charge_state");
    const charging = this._find(items, "charging");
    const plug = this._find(items, "charge_plug");
    const speed = this._find(items, "speed");

    const isCharging = charging ? charging.s.state === "on"
      : (chargeState && /charg/i.test(chargeState.s.state) && !/not/i.test(chargeState.s.state));
    const batV = bat ? this._num(bat.s) : null;

    // ---- header ----
    // Image priority: explicit card config → the vehicle_image set in the integration
    // options (exposed on the device_tracker) → none.
    const img = cfg.image || items.map((r) => r.s.attributes.vehicle_image).find(Boolean) || "";
    const header = `
      <div class="header ${img ? "img" : ""}" style="${img ? `background-image:url('${img}')` : ""}">
        ${img ? '<div class="overlay"></div>' : ""}
        ${img ? `<div class="head-row"><div class="title">${title}</div>
              ${bat && !this._dead(bat.s) ? `<div class="bat" data-e="${bat.id}">
                <ha-icon icon="${this._batteryIcon(batV, isCharging)}" style="color:${this._batteryColor(batV)}"></ha-icon>
                <span class="bat-pct">${bat.s.state}%</span></div>` : ""}</div>`
          : `<div class="title">${title}</div>
             ${bat && !this._dead(bat.s) ? `<div class="bat" data-e="${bat.id}">
                <ha-icon icon="${this._batteryIcon(batV, isCharging)}" style="color:${this._batteryColor(batV)}"></ha-icon>
                <span class="bat-pct" style="color:${this._batteryColor(batV)}">${bat.s.state}%</span></div>` : ""}`}
      </div>`;

    // ---- primary stats ----
    const stat = (label, icon, s, fallback) => {
      const val = s && !this._dead(s.s) ? this._fmt(s.s) : (fallback || "—");
      const de = s ? `data-e="${s.id}"` : "";
      return `<div class="stat" ${de}><div class="label"><ha-icon icon="${icon}"></ha-icon>${label}</div>
        <div class="value">${val}</div></div>`;
    };
    const chargeText = charging && !this._dead(charging.s)
      ? (isCharging ? "Charging" : "Not charging")
      : (chargeState && !this._dead(chargeState.s) ? chargeState.s.state : "—");
    const stats = `<div class="stats">
      ${stat("Range", "mdi:map-marker-distance", range)}
      ${stat("Charging", isCharging ? "mdi:battery-charging" : "mdi:power-plug", { id: (charging || chargeState || {}).id, s: { state: chargeText, attributes: {} } }, chargeText)}
      ${plug && !this._dead(plug.s) ? stat("Cable", plug.s.state === "on" ? "mdi:power-plug" : "mdi:power-plug-off",
          { id: plug.id, s: { state: plug.s.state === "on" ? "Connected" : "Unplugged", attributes: {} } }) :
        (speed ? stat("Speed", "mdi:speedometer", speed) : "")}
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
    const warnHtml = warns.length ? `<div class="warnings">${warns.map((w) =>
      `<div class="warn" data-e="${w.id}"><ha-icon icon="${w.icon}"></ha-icon>${w.text}</div>`).join("")}</div>` : "";

    // ---- optional extra rows / full list ----
    let extra = "";
    const used = new Set([bat, range, chargeState, charging, plug, speed, low, conn].filter(Boolean).map((r) => r.id));
    const rowFor = (id) => {
      const s = hass.states[id]; if (!s) return "";
      const name = (s.attributes.friendly_name || id).replace(new RegExp("^" + device + "\\s*", "i"), "").trim() || id;
      return `<div class="row" data-e="${id}"><div class="name">${name}</div><div class="val">${this._fmt(s)}</div></div>`;
    };
    if (Array.isArray(cfg.entities) && cfg.entities.length) {
      extra += `<div class="group-title">Details</div>` +
        cfg.entities.map((e) => rowFor(typeof e === "string" ? e : e.entity)).join("");
    } else if (cfg.show_all) {
      const rest = items.filter((r) => !used.has(r.id) && !this._dead(r.s) &&
        r.s.attributes.entity_category !== "diagnostic");
      if (rest.length) extra += `<div class="group-title">More</div>` +
        rest.sort((a, b) => a.key.localeCompare(b.key)).map((r) => rowFor(r.id)).join("");
    }

    this.content.innerHTML = header + stats + warnHtml + extra;
    this.content.querySelectorAll("[data-e]").forEach((el) => {
      const id = el.getAttribute("data-e");
      if (!id || id === "undefined") return;
      el.addEventListener("click", () => this.dispatchEvent(new CustomEvent("hass-more-info",
        { bubbles: true, composed: true, detail: { entityId: id } })));
    });
  }

  static getStubConfig() { return { type: "custom:omoda-card" }; }
}
customElements.define("omoda-card", OmodaCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "omoda-card",
  name: "Omoda/Jaecoo Card",
  preview: true,
  description: "Curated summary card for the Omoda/Jaecoo integration (battery, range, charging, warnings).",
});
