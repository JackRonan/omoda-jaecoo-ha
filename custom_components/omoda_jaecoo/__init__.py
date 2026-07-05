"""Omoda / Jaecoo / Jaecoo custom component — bootstrap.

Replaces the standalone bridge (`ha_bridge.py`): the MQTT/REST logic lives in
`coordinator.py`, the entities are native (no more MQTT Discovery). The "protocol
core" (auth, signing, commands, probe) is reused from `core/` without rewriting
the logic already verified in the field.

⚠️ SCAFFOLD under construction: the config flow (OTP) is active; coordinator and platform
entities are being completed (see SHARING_TODO.md → component roadmap).
"""
from __future__ import annotations

import logging
import os
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

# Vendoring the "protocol core": the modules in core/ import each other by
# name (import wake / import omoda_auth as A …) → add core/ to the path once.
_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# Delete the core/ compiled-bytecode cache on import. A HACS update overwrites the .py
# files but leaves the old __pycache__ behind; because the core/ modules are imported by
# bare name, Python could keep loading that stale bytecode after an update — the recurring
# "Italian text / missing Find-Locate buttons after updating" problem. Removing it here (this
# runs before the core modules are imported) forces a fresh compile from the current source.
# Best-effort; ignore any error (read-only FS, permissions, race).
try:
    import shutil as _shutil
    _pyc = os.path.join(_CORE, "__pycache__")
    if os.path.isdir(_pyc):
        _shutil.rmtree(_pyc, ignore_errors=True)
except Exception:  # noqa: BLE001
    pass

# Custom Lovelace card: static-served here and auto-loaded on the frontend so it shows
# up in the card picker without the user manually adding a dashboard resource.
_CARD_PATH = "/omoda_jaecoo_card"
_CARD_URL = f"{_CARD_PATH}/omoda-card.js"


# core/ modules in dependency order (deps before dependents), so reloading them in this
# order makes each pick up freshly-reloaded dependencies.
_CORE_MODULES = (
    "codes", "omoda", "omoda_auth", "tsp_sign", "captcha_solver", "prova_token",
    "login_omoda", "wake", "session", "probe", "provision", "commands",
)


def _load_core_from_disk() -> None:
    """Force-load THIS integration's core/ modules from their own files into sys.modules,
    in dependency order. This is the permanent fix for the recurring "Italian text / missing
    Find-Locate buttons after updating" regression, which had three separate causes that all
    end the same way (button.py does `import commands` and gets the WRONG catalog):

      1. Stale bytecode — a HACS update leaves an old __pycache__ behind (also cleared on import).
      2. Stale sys.modules — on a config reload the modules stay cached from first import.
      3. NAME COLLISION — the core modules use generic bare names (`commands`, `wake`, `session`,
         `codes`…). `commands` especially is a common name; another integration's `commands.py`
         on sys.path could win the bare `import commands`. importlib.reload() can't fix that —
         it reloads whatever object is cached, even if it's the foreign one.

    spec_from_file_location(name, core/<name>.py) loads OUR exact file, freshly compiled, and
    we pin it into sys.modules[name] BEFORE the platforms import it — so button.py/coordinator.py
    always see this integration's catalog regardless of sys.path order or a stale cache. Loading
    in dependency order means each module's bare cross-imports resolve to our just-pinned copies.
    Best-effort; blocking → run in executor. Safe here: setup runs after any prior unload."""
    import importlib.util
    for name in _CORE_MODULES:
        path = os.path.join(_CORE, f"{name}.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module      # pin OURS before exec, so cross-imports resolve to us
            spec.loader.exec_module(module)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Omoda / Jaecoo: could not load core module %s from disk: %s", name, err)


def _cleanup_stale_entities(hass: HomeAssistant, coordinator) -> None:
    """Remove entity-registry entries this integration no longer provides, so upgrades
    don't leave orphaned "unavailable" entities behind. Targeted by unique_id (never a
    blanket wipe), so it can only remove the specific retired entities:
      - the charge-limit sensor + number (backend has no charge-limit endpoint),
      - the on/off command buttons that are now switches (climate macros, theft alarm),
      - on a confirmed BEV, the fuel-only sensors that don't apply."""
    try:
        _do_cleanup_stale_entities(hass, coordinator)
    except Exception as err:  # noqa: BLE001 — cleanup is best-effort, must never break setup
        import logging
        logging.getLogger(__name__).debug("stale-entity cleanup skipped: %s", err)


def _do_cleanup_stale_entities(hass: HomeAssistant, coordinator) -> None:
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
    # Old ITALIAN-key command buttons from early fork versions (keys later renamed to
    # English, or converted to switches). Their unique_ids follow the same `{vin}_cmd_{key}`
    # scheme as the current buttons.
    for key in ("trova_auto", "localizza",
                "clima_raffredda_on", "clima_raffredda_off",
                "clima_riscalda_on", "clima_riscalda_off",
                "finestrini_ventila", "antifurto_on", "antifurto_off"):
        stale.append(("button", f"{vin}_cmd_{key}"))
    if coordinator.is_pure_electric():
        for suf in ("rt_range_benzina", "rt_consumo_carburante",
                    "rt_carburante_residuo", "rt_km_ibrido"):
            stale.append(("sensor", f"{vin}_{suf}"))
    for domain, unique_id in stale:
        entity_id = reg.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id:
            reg.async_remove(entity_id)

    # Belt-and-braces: also remove the retired buttons by their stable entity_id, in case an
    # early version used a different unique_id scheme (async_get_entity_id above wouldn't find
    # them then). Guarded to this integration's platform so nothing unrelated is touched.
    legacy_entity_ids = (
        "button.omoda_jaecoo_trova_auto", "button.omoda_jaecoo_localizza",
        "button.omoda_jaecoo_clima_raffredda_on", "button.omoda_jaecoo_clima_raffredda_off",
        "button.omoda_jaecoo_clima_riscalda_on", "button.omoda_jaecoo_clima_riscalda_off",
        "button.omoda_jaecoo_finestrini_ventila",
        "button.omoda_jaecoo_antifurto_on", "button.omoda_jaecoo_antifurto_off",
    )
    for eid in legacy_entity_ids:
        ent = reg.async_get(eid)
        if ent is not None and ent.platform == DOMAIN:
            reg.async_remove(eid)

    # One-time entity_id migration. The diagnostic text sensors used to derive their entity_id
    # from the (translatable) display name, so renaming them drifted the entity_id (e.g.
    # sensor.diagnostic_command_result) and broke the failed-command blueprint's default. They
    # now have a stable object_id; move anyone still on the old auto-slug onto it. Guarded: only
    # when the entity is still on the EXACT drifted default (so a user-customised id is untouched)
    # and the target entity_id is free.
    for suffix, old_eid, new_eid in (
        ("cmd_status", "sensor.diagnostic_command_result", "sensor.omoda_jaecoo_command_result"),
        ("wake_status", "sensor.diagnostic_wake_up_result", "sensor.omoda_jaecoo_wake_result"),
        ("probe_status", "sensor.diagnostic_location_probe_result", "sensor.omoda_jaecoo_location_probe_result"),
    ):
        cur = reg.async_get_entity_id("sensor", DOMAIN, f"{vin}_{suffix}")
        if cur == old_eid and reg.async_get(new_eid) is None:
            try:
                reg.async_update_entity(cur, new_entity_id=new_eid)
            except Exception as err:  # noqa: BLE001 — migration is best-effort
                _LOGGER.debug("entity_id migration %s skipped: %s", cur, err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the integration from a config entry."""
    # Pin this integration's core/ modules (command catalog, protocol) into sys.modules from
    # their own files FIRST — before coordinator/platforms import them by bare name — so a
    # config reload, a stale bytecode cache, or a name collision can't serve the old catalog
    # (the recurring "Italian text / missing Find-Locate buttons" regression). Best-effort.
    await hass.async_add_executor_job(_load_core_from_disk)

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
            from homeassistant.loader import async_get_integration
            # Version query busts the browser's cache of the card JS on every update — without
            # it you keep seeing the OLD card (the module is cached hard by the frontend).
            try:
                version = (await async_get_integration(hass, DOMAIN)).version
            except Exception:  # noqa: BLE001
                version = ""
            add_extra_js_url(hass, f"{_CARD_URL}?v={version}" if version else _CARD_URL)
        except Exception:  # noqa: BLE001 — frontend not loaded (headless) → card still usable manually
            pass
        hass.data[f"{DOMAIN}_card"] = True

    # One-time removal of retired entities (charge-limit, on/off buttons now switches,
    # BEV fuel sensors) so upgrades don't leave orphaned "unavailable" entities.
    _cleanup_stale_entities(hass, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Set up the ENTITIES first and UNCONDITIONALLY. Their (English) names must always
    # show — even if the car connection (certs / MQTT / session) is temporarily down.
    # If setup failed here, HA would fall back to each entity's stale registry name, which
    # is exactly what made the old Italian names appear to "come back". Entities with no
    # fresh data simply show as unavailable until the connection is up again.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _cleanup_stale_entities(hass, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Everything that can fail transiently (certs, MQTT, session, timers, identity backfill)
    # runs in the background and is BEST-EFFORT — it must NEVER stop the entry from loading.
    async def _start_connection() -> None:
        try:
            ok, detail = await coordinator.async_provision_certs()
            if ok:
                await coordinator.async_start()   # connect the car's MQTT feed
            else:
                _LOGGER.warning(
                    "Omoda / Jaecoo: mutual-TLS certs not ready — running without the live "
                    "MQTT feed (REST polling still works). %s", detail)
        except Exception as err:  # noqa: BLE001 — never break the loaded entry
            _LOGGER.warning(
                "Omoda / Jaecoo: car connection failed at startup (entities stay loaded; "
                "REST keeps working and it will retry): %s", err)
        try:
            await coordinator.async_check_session()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Omoda / Jaecoo: session check failed: %s", err)
        # timers are individually safe (no-ops when their switch/interval is off)
        coordinator.async_start_keepalive()
        coordinator.async_start_telemetry_poll()
        coordinator.async_start_drive_watch()
        try:
            await coordinator.async_ensure_vehicle_identity()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Omoda / Jaecoo: vehicle identity backfill failed: %s", err)

    hass.async_create_background_task(_start_connection(), "omoda_jaecoo_start")
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
