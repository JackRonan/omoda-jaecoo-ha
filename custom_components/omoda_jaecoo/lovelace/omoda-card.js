class OmodaCard extends HTMLElement {
  set hass(hass) {
    if (!this.content) {
      const card = document.createElement("ha-card");
      this.content = document.createElement("div");
      
      const style = document.createElement("style");
      style.textContent = \
        ha-card {
          overflow: hidden;
          background: var(--ha-card-background, var(--card-background-color, white));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, none);
        }
        .header {
          position: relative;
          width: 100%;
          padding-top: 56.25%; /* 16:9 Aspect Ratio */
          background-size: cover;
          background-position: center;
          background-repeat: no-repeat;
        }
        .header-content {
          position: absolute;
          bottom: 16px;
          left: 16px;
          right: 16px;
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          text-shadow: 0px 2px 4px rgba(0,0,0,0.8);
          color: white;
        }
        .battery-container {
          display: flex;
          align-items: center;
          background: rgba(0, 0, 0, 0.5);
          padding: 8px 12px;
          border-radius: 20px;
          backdrop-filter: blur(4px);
        }
        .battery-icon {
          margin-right: 8px;
          --mdc-icon-size: 24px;
        }
        .battery-text {
          font-size: 1.2rem;
          font-weight: bold;
        }
        .title {
          font-size: 1.5rem;
          font-weight: 500;
          background: rgba(0, 0, 0, 0.5);
          padding: 4px 12px;
          border-radius: 16px;
          backdrop-filter: blur(4px);
        }
        .entities-container {
          padding: 16px;
        }
        .entity-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 0;
          border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.1));
        }
        .entity-row:last-child {
          border-bottom: none;
        }
        .entity-info {
          display: flex;
          align-items: center;
        }
        .entity-icon {
          color: var(--state-icon-color);
          margin-right: 16px;
        }
        .entity-name {
          color: var(--primary-text-color);
        }
        .entity-state {
          font-weight: bold;
          color: var(--primary-text-color);
        }
      \;

      card.appendChild(style);
      card.appendChild(this.content);
      this.appendChild(card);
    }

    const config = this.config;
    
    // Header section with Image and Battery
    const imageUrl = config.image || "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/Omoda_E5_in_Malaysia_01.jpg/800px-Omoda_E5_in_Malaysia_01.jpg";
    let batteryHtml = '';
    
    if (config.battery_entity && hass.states[config.battery_entity]) {
      const batteryState = hass.states[config.battery_entity];
      const stateStr = batteryState.state;
      const unit = batteryState.attributes.unit_of_measurement || '%';
      
      let icon = "mdi:battery";
      const val = parseInt(stateStr);
      if (!isNaN(val)) {
        if (val >= 95) icon = "mdi:battery";
        else if (val >= 90) icon = "mdi:battery-90";
        else if (val >= 80) icon = "mdi:battery-80";
        else if (val >= 70) icon = "mdi:battery-70";
        else if (val >= 60) icon = "mdi:battery-60";
        else if (val >= 50) icon = "mdi:battery-50";
        else if (val >= 40) icon = "mdi:battery-40";
        else if (val >= 30) icon = "mdi:battery-30";
        else if (val >= 20) icon = "mdi:battery-20";
        else if (val >= 10) icon = "mdi:battery-10";
        else icon = "mdi:battery-outline";
      }
      
      if (batteryState.attributes.device_class === "battery" && batteryState.state === "on") {
         icon = "mdi:battery-charging";
      }

      batteryHtml = \
        <div class="battery-container">
          <ha-icon class="battery-icon" icon="\"></ha-icon>
          <div class="battery-text">\\</div>
        </div>
      \;
    }

    let titleHtml = config.title ? \<div class="title">\</div>\ : '';

    let headerHtml = \
      <div class="header" style="background-image: url('\')">
        <div class="header-content">
          \
          \
        </div>
      </div>
    \;

    // Entities section
    let entitiesHtml = '<div class="entities-container">';
    if (config.entities && config.entities.length > 0) {
      config.entities.forEach(entityConf => {
        const entityId = typeof entityConf === 'string' ? entityConf : entityConf.entity;
        if (hass.states[entityId]) {
          const stateObj = hass.states[entityId];
          const name = (typeof entityConf === 'object' && entityConf.name) ? entityConf.name : (stateObj.attributes.friendly_name || entityId);
          const icon = (typeof entityConf === 'object' && entityConf.icon) ? entityConf.icon : (stateObj.attributes.icon || "mdi:bookmark");
          const state = stateObj.state;
          const unit = stateObj.attributes.unit_of_measurement || "";
          
          entitiesHtml += \
            <div class="entity-row">
              <div class="entity-info">
                <ha-icon class="entity-icon" icon="\" data-state="\"></ha-icon>
                <div class="entity-name">\</div>
              </div>
              <div class="entity-state">\ \</div>
            </div>
          \;
        }
      });
    }
    entitiesHtml += '</div>';

    this.content.innerHTML = headerHtml + entitiesHtml;
  }

  setConfig(config) {
    if (!config.entities) {
      // It's ok to not have entities, but good to have.
    }
    this.config = config;
  }

  getCardSize() {
    return 4;
  }
}

customElements.define('omoda-card', OmodaCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "omoda-card",
  name: "Omoda/Jaecoo Card",
  preview: true,
  description: "A custom card for the Omoda/Jaecoo vehicle integration."
});
