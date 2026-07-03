/*
 * Omoda / Jaecoo vehicle card — universal, powertrain-agnostic.
 *
 * Works for BEV, PHEV, or any vehicle the integration supports WITHOUT a manual
 * entity list: it auto-discovers every entity whose object_id starts with the
 * integration prefix (default "omoda_jaecoo_") and lays them out in groups,
 * hiding anything that is unavailable/unknown (e.g. petrol range on a BEV).
 *
 * Minimal config:
 *   type: custom:omoda-card
 * Optional:
 *   title: "My Car"            # header title (default: device/friendly name)
 *   image: "/local/car.png"    # header background image
 *   prefix: "omoda_jaecoo_"    # entity object_id prefix to collect
 *   hide_unavailable: true     # hide unavailable/unknown rows (default true)
 *   show_diagnostic: false     # include diagnostic-category entities (default false)
 */
class OmodaCard extends HTMLElement {
  // ---- grouping rules: label + matcher over the stripped object_id ----
  static GROUPS = [
    { id: "energy",  label: "Energy & Range", icon: "mdi:lightning-bolt",
      match: (k) => /range|odometer|battery|consumption|charge|mileage|speed/.test(k) },
    { id: "climate", label: "Climate",        icon: "mdi:thermometer",
      match: (k) => /climate|seat|windshield|defrost|steering|temp|hvac|air/.test(k) },
    { id: "access",  label: "Doors & Windows", icon: "mdi:car-door",
      match: (k) => /door|window|sunroof|trunk|tailgate|lock|hood|sunshade/.test(k) },
    { id: "tires",   label: "Tires",          icon: "mdi:car-tire-alert",
      match: (k) => /tire|tyre/.test(k) },
    { id: "other",   label: "Vehicle",        icon: "mdi:car-info",
      match: () => true },
  ];

  setConfig(config) {
    this.config = Object.assign(
      { integration: "omoda_jaecoo", prefix: "omoda_jaecoo_",
        hide_unavailable: true, show_diagnostic: false },
      config || {}
    );
  }

  // Entities of THIS integration. Primary: hass.entities platform match (catches every
  // entity_id naming, incl. the unprefixed sensor.battery / sensor.speed). Fallback for
  // older frontends: object_id prefix. Returns [{id, key, s}] with `key` = object_id minus prefix.
  _collect(hass) {
    const cfg = this.config;
    const out = [];
    const strip = (objectId) => objectId.startsWith(cfg.prefix) ? objectId.slice(cfg.prefix.length) : objectId;
    const reg = hass.entities; // frontend entity registry map (may be undefined on old cores)
    if (reg) {
      for (const id in reg) {
        if (reg[id].platform !== cfg.integration) continue;
        const s = hass.states[id];
        if (!s) continue;
        out.push({ id, key: strip(id.slice(id.indexOf(".") + 1)), s });
      }
    }
    if (!out.length) { // fallback: prefix scan
      for (const id in hass.states) {
        const objectId = id.slice(id.indexOf(".") + 1);
        if (!objectId.startsWith(cfg.prefix)) continue;
        out.push({ id, key: strip(objectId), s: hass.states[id] });
      }
    }
    return out;
  }

  getCardSize() { return 6; }

  _isDead(s) {
    return !s || s.state === "unavailable" || s.state === "unknown" || s.state === "";
  }

  _fmt(s) {
    const unit = s.attributes.unit_of_measurement;
    return unit ? `${s.state} ${unit}` : s.state;
  }

  _battery(items) {
    // dedicated SOC sensor: device_class battery + %, object_id ending "battery"
    let found = items.find(({ key, s }) =>
      s.entity_id.startsWith("sensor.") && s.attributes.device_class === "battery" &&
      s.attributes.unit_of_measurement === "%" && !this._isDead(s));
    if (!found) found = items.find(({ key, s }) =>
      s.entity_id.startsWith("sensor.") && key.endsWith("battery") && !this._isDead(s));
    return found ? found.s : null;
  }

  _range(items) {
    for (const want of ["range_electric", "range_total", "range_combined_estimate", "range_gasoline"]) {
      const found = items.find(({ key, s }) => key === want && !this._isDead(s));
      if (found) return found.s;
    }
    return null;
  }

  _batteryIcon(val, charging) {
    if (charging) return "mdi:battery-charging";
    if (isNaN(val)) return "mdi:battery";
    const step = Math.round(val / 10) * 10;
    return step >= 100 ? "mdi:battery" : step <= 0 ? "mdi:battery-outline" : `mdi:battery-${step}`;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.content) {
      const card = document.createElement("ha-card");
      const style = document.createElement("style");
      style.textContent = `
        .header { position: relative; width: 100%; padding-top: 46%;
          background-size: cover; background-position: center; background-color: var(--secondary-background-color); }
        .header-overlay { position: absolute; inset: 0;
          background: linear-gradient(to top, rgba(0,0,0,0.55), rgba(0,0,0,0) 45%); }
        .header-content { position: absolute; left: 16px; right: 16px; bottom: 14px;
          display: flex; justify-content: space-between; align-items: flex-end; color: #fff;
          text-shadow: 0 1px 3px rgba(0,0,0,0.8); }
        .title { font-size: 1.35rem; font-weight: 600; }
        .badges { display: flex; gap: 8px; align-items: center; }
        .badge { display: flex; align-items: center; gap: 6px; font-weight: 600;
          background: rgba(0,0,0,0.45); padding: 6px 10px; border-radius: 16px; backdrop-filter: blur(4px); }
        .badge ha-icon { --mdc-icon-size: 20px; }
        .group-title { display: flex; align-items: center; gap: 8px; font-weight: 600;
          color: var(--primary-text-color); padding: 14px 16px 4px; font-size: 0.95rem; }
        .group-title ha-icon { --mdc-icon-size: 18px; color: var(--state-icon-color); }
        .row { display: flex; justify-content: space-between; align-items: center;
          padding: 8px 16px; cursor: pointer; border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.08)); }
        .row:hover { background: var(--secondary-background-color); }
        .row:last-child { border-bottom: none; }
        .left { display: flex; align-items: center; gap: 14px; min-width: 0; }
        .left ha-icon { color: var(--state-icon-color); flex: none; }
        .name { color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .val { font-weight: 600; color: var(--primary-text-color); text-align: right; flex: none; padding-left: 12px; }
        .empty { padding: 16px; color: var(--secondary-text-color); }
      `;
      this.content = document.createElement("div");
      card.appendChild(style);
      card.appendChild(this.content);
      this.appendChild(card);
    }
    this._render(hass);
  }

  _render(hass) {
    const cfg = this.config;

    // ---- collect this vehicle's entities (platform match, prefix fallback) ----
    const collected = this._collect(hass);

    // ---- header (title + battery + range) ----
    const anyName = collected.find((r) => r.s.attributes.friendly_name)?.s.attributes.friendly_name;
    const deviceName = anyName ? anyName.split(" ").slice(0, 2).join(" ") : "Omoda / Jaecoo";
    const title = cfg.title || deviceName;

    const bat = this._battery(collected);
    const rng = this._range(collected);
    const chargeState = (collected.find((r) => r.key === "charge_state")?.s.state || "").toLowerCase();
    const charging = chargeState.includes("charg") && !chargeState.includes("not");
    let badges = "";
    if (bat) {
      const val = parseFloat(bat.state);
      badges += `<div class="badge" data-e="${bat.entity_id}">
        <ha-icon icon="${this._batteryIcon(val, charging)}"></ha-icon>${bat.state}%</div>`;
    }
    if (rng) {
      badges += `<div class="badge" data-e="${rng.entity_id}">
        <ha-icon icon="mdi:map-marker-distance"></ha-icon>${this._fmt(rng)}</div>`;
    }

    const img = cfg.image;
    const headerBg = img ? `background-image:url('${img}')` : "";
    const header = `
      <div class="header" style="${headerBg}">
        <div class="header-overlay"></div>
        <div class="header-content">
          <div class="title">${title}</div>
          <div class="badges">${badges}</div>
        </div>
      </div>`;

    // ---- filter + group the rest ----
    const usedInHeader = new Set([bat && bat.entity_id, rng && rng.entity_id].filter(Boolean));
    const rows = collected.filter(({ id, s }) => {
      if (usedInHeader.has(id)) return false;
      if (!cfg.show_diagnostic && s.attributes.entity_category === "diagnostic") return false;
      if (cfg.hide_unavailable && this._isDead(s)) return false;
      return true;
    });

    let body = "";
    for (const g of OmodaCard.GROUPS) {
      const inGroup = rows.filter((r) => !r._used && g.match(r.key));
      inGroup.forEach((r) => (r._used = true));
      if (!inGroup.length) continue;
      inGroup.sort((a, b) => (a.s.attributes.friendly_name || a.id).localeCompare(b.s.attributes.friendly_name || b.id));
      body += `<div class="group-title"><ha-icon icon="${g.icon}"></ha-icon>${g.label}</div>`;
      for (const { id, s } of inGroup) {
        const name = (s.attributes.friendly_name || id).replace(new RegExp("^" + deviceName + "\\s*", "i"), "").trim() || id;
        const icon = s.attributes.icon || "mdi:card-bullet";
        body += `
          <div class="row" data-e="${id}">
            <div class="left"><ha-icon icon="${icon}"></ha-icon><div class="name">${name}</div></div>
            <div class="val">${this._fmt(s)}</div>
          </div>`;
      }
    }
    if (!body) body = `<div class="empty">Waiting for vehicle data… (wake the car or run a status refresh)</div>`;

    this.content.innerHTML = header + body;

    // ---- click → more-info ----
    this.content.querySelectorAll("[data-e]").forEach((el) => {
      el.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          bubbles: true, composed: true,
          detail: { entityId: el.getAttribute("data-e") },
        }));
      });
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
  description: "Universal vehicle card for the Omoda/Jaecoo integration (BEV/PHEV, auto-discovers entities).",
});
