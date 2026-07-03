"""Omoda / Jaecoo / Jaecoo custom component — bootstrap.

Replaces the standalone bridge (`ha_bridge.py`): the MQTT/REST logic lives in
`coordinator.py`, the entities are native (no more MQTT Discovery). The "protocol
core" (auth, signing, commands, probe) is reused from `core/` without rewriting
the logic already verified in the field.

⚠️ SCAFFOLD under construction: the config flow (OTP) is active; coordinator and platform
entities are being completed (see SHARING_TODO.md → component roadmap).
"""
from __future__ import annotations

import os
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS

# Vendoring the "protocol core": the modules in core/ import each other by
# name (import wake / import omoda_auth as A …) → add core/ to the path once.
_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# Custom Lovelace card: static-served here and auto-loaded on the frontend so it shows
# up in the card picker without the user manually adding a dashboard resource.
_CARD_PATH = "/omoda_jaecoo_card"
_CARD_URL = f"{_CARD_PATH}/omoda-card.js"


def _cleanup_stale_entities(hass: HomeAssistant, coordinator) -> None:
    """Remove entity-registry entries this integration no longer provides, so upgrades
    don't leave orphaned "unavailable" entities behind. Targeted by unique_id (never a
    blanket wipe), so it can only remove the specific retired entities:
      - the charge-limit sensor + number (backend has no charge-limit endpoint),
      - the on/off command buttons that are now switches (climate macros, theft alarm),
      - on a confirmed BEV, the fuel-only sensors that don't apply."""
    reg = er.async_get(hass)
    vin = coordinator.vin
    stale: list[tuple[str, str]] = [
        ("sensor", f"{vin}_rt_charge_limit"),
        ("number", f"{vin}_charge_limit_number"),
        ("button", f"{vin}_cmd_climate_cool_on"),
        ("button", f"{vin}_cmd_climate_cool_off"),
        ("button", f"{vin}_cmd_climate_heat_on"),
        ("button", f"{vin}_cmd_climate_heat_off"),
        ("button", f"{vin}_cmd_alarm_theft_on"),
        ("button", f"{vin}_cmd_alarm_theft_off"),
        # windows: old cover + ventilate button → replaced by the 3-state select
        ("cover", f"{vin}_finestrini"),
        ("button", f"{vin}_cmd_ventilate_windows"),
    ]
    if coordinator.is_pure_electric():
        for suf in ("rt_range_benzina", "rt_consumo_carburante",
                    "rt_carburante_residuo", "rt_km_ibrido"):
            stale.append(("sensor", f"{vin}_{suf}"))
    for domain, unique_id in stale:
        entity_id = reg.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id:
            reg.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration from a config entry."""
    from .coordinator import OmodaJaecooCoordinator

    coordinator = OmodaJaecooCoordinator(hass, entry)

    # Serve the custom Lovelace card and auto-load it on the frontend so it appears in
    # the dashboard card picker (no manual "add resource" step). Guarded so multiple
    # entries/reloads don't register the static path or JS URL twice.
    if hasattr(hass, "http") and hass.http is not None and not hass.data.get(f"{DOMAIN}_card"):
        lovelace_dir = os.path.join(os.path.dirname(__file__), "lovelace")
        await hass.http.async_register_static_paths([
            StaticPathConfig(_CARD_PATH, lovelace_dir, False)
        ])
        try:
            from homeassistant.components.frontend import add_extra_js_url
            add_extra_js_url(hass, _CARD_URL)
        except Exception:  # noqa: BLE001 — frontend not loaded (headless) → card still usable manually
            pass
        hass.data[f"{DOMAIN}_card"] = True

    # One-time removal of retired entities (charge-limit, on/off buttons now switches,
    # BEV fuel sensors) so upgrades don't leave orphaned "unavailable" entities.
    _cleanup_stale_entities(hass, coordinator)

    # PHASE 3c: the mutual-TLS certs must be present BEFORE connecting the car's MQTT.
    ok, detail = await coordinator.async_provision_certs()
    if not ok:
        raise ConfigEntryNotReady(detail)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # initial session state + start MQTT connection to the car
    await coordinator.async_check_session()
    # [H4] if ANY startup step fails (MQTT connect, starting timers, forwarding
    #      the platforms) we clean up ALL resources already started — the paho client and
    #      the keepalive/poll timers — and remove the coordinator from hass.data, so no
    #      orphan threads/timers remain; then we re-raise → HA retries the setup.
    try:
        await coordinator.async_start()
        # keep-alive: periodic session refresh so the token doesn't expire while idle
        coordinator.async_start_keepalive()
        # periodic telemetry poll (wake-up + read); intervals from the options
        coordinator.async_start_telemetry_poll()
        # drive-detection heartbeat (read-only): kicks off the automatic refresh during a
        # trip. No-op if the "Automatic update" switch is off (the switch restarts it).
        coordinator.async_start_drive_watch()
        # reload the entry when the user changes the options (e.g. poll intervals)
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # backfill vehicle identity (dynamic device name) for entries created before the
        # config flow saved it: in the background, so any reload happens after setup is done.
        hass.async_create_background_task(
            coordinator.async_ensure_vehicle_identity(), "omoda_jaecoo_vehicle_identity")
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await hass.async_add_executor_job(coordinator.async_stop)
        raise
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed → reload the entry to reapply the poll intervals."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # [MED] only if the platform unload succeeded do we tear down the coordinator: if
    #       a platform refuses the unload (ok=False) HA considers the entry still
    #       loaded → we don't destroy the coordinator underneath entities that are still
    #       alive (consistent state; HA will retry the unload).
    if ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            # async_stop is blocking (loop_stop joins the paho thread) → executor.
            await hass.async_add_executor_job(coordinator.async_stop)
    return ok
