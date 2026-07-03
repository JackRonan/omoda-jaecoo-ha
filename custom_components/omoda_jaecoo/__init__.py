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

from .const import DOMAIN, PLATFORMS

# Vendoring the "protocol core": the modules in core/ import each other by
# name (import wake / import omoda_auth as A …) → add core/ to the path once.
_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration from a config entry."""
    from .coordinator import OmodaJaecooCoordinator

    coordinator = OmodaJaecooCoordinator(hass, entry)

    # Register the path for the custom Lovelace card
    if hasattr(hass, "http") and hass.http is not None:
        lovelace_dir = os.path.join(os.path.dirname(__file__), "lovelace")
        await hass.http.async_register_static_paths([
            StaticPathConfig("/omoda_jaecoo_card", lovelace_dir, False)
        ])

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
