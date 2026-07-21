"""Downloadable diagnostics for the Omoda / Jaecoo / Jaecoo integration.

Generates the report HA offers via «Download diagnostics» on the integration
page. Intended for SUPPORT: it contains session state, region parameters,
presence of tokens/certificates and the last telemetry received, but does
NOT expose any personal or secret data:

  • email, PIN, VIN, tUserId            → obscured (REDACTED)
  • GPS position (lat/lon)              → obscured (where you live never leaks)
  • tokens and mutual-TLS certificates  → only «present: yes/no», never the content

This way the user can send you the file completely safely.
"""
from __future__ import annotations

import os
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CERT_FILES

# Keys to obscure wherever they appear (config entry + any nested dicts).
# NB: `seq` is included because the realtime payload's seq is "<VIN>-<timestamp>" → it embeds
# the VIN; without this the VIN leaked into diagnostics via realtime.seq.
TO_REDACT = {
    "email", "pin", "vin", "tuserid", "seq",
    "lat", "lon", "latitude", "longitude", "position",
    "certs_src",   # a local filesystem path = information disclosure
}


def _scrub_vin(obj: Any, vin: str) -> Any:
    """Belt-and-braces: replace the VIN wherever it appears as a SUBSTRING (e.g. inside a
    field the redaction-by-key list doesn't know about), so it can never reach the report."""
    if not vin:
        return obj
    if isinstance(obj, dict):
        return {k: _scrub_vin(v, vin) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_vin(v, vin) for v in obj]
    if isinstance(obj, str) and vin in obj:
        return obj.replace(vin, "**REDACTED**")
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Diagnostic report for a config entry (invoked by «Download diagnostics»)."""
    diag: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            # title forced without VIN (the real title is "Omoda / Jaecoo (<VIN>)")
            "title": "Omoda / Jaecoo",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        diag["coordinator"] = "not initialized (entry not loaded)"
        return diag

    # Presence of the sensitive files as plain booleans — never their content.
    token_present = await hass.async_add_executor_job(
        os.path.isfile, coordinator.token_path
    )
    certs_present: dict[str, bool] = {}
    for fname in CERT_FILES:
        path = os.path.join(coordinator.certs_dir, fname)
        certs_present[fname] = await hass.async_add_executor_job(os.path.isfile, path)

    data = dict(coordinator.data or {})
    has_position = bool(data.get("position"))
    vin = getattr(coordinator, "vin", "") or ""
    # The GPS position is sensitive (where you live) → never exported, not even obscured coord-by-coord.
    realtime = data.get("realtime")
    if isinstance(realtime, dict):
        realtime = _scrub_vin(async_redact_data(realtime, TO_REDACT), vin)
    # 5A02 telemetry (door/climate/seat state…): redact by key + scrub the VIN as a safety net.
    fields = data.get("fields")
    if isinstance(fields, dict):
        fields = _scrub_vin(async_redact_data(dict(fields), TO_REDACT), vin)

    diag["coordinator"] = {
        "region": {
            "bff": coordinator.bff,
            "tsp_host": coordinator.tsp_host,
            "car_mqtt_host": coordinator.car_host,
            "car_mqtt_port": coordinator.car_port,
            "channel_id": coordinator.channel_id,
        },
        "poll": {
            "normal_min": coordinator.poll_normal_min,
            "charging_min": coordinator.poll_charging_min,
            "enabled": coordinator.poll_enabled,
        },
        "token_present": token_present,
        "certs_present": certs_present,
        "state": {
            "session_ok": data.get("session_ok"),
            "session_detail": data.get("session_detail"),
            "awake": data.get("awake"),
            "car_connected": data.get("car_connected"),
            "has_position_fix": has_position,
            "last_seen": data.get("last_seen"),
            "last_wake": data.get("last_wake"),
            "last_pos_fix": data.get("last_pos_fix"),
            "cmd_status": data.get("cmd_status"),
            "wake_status": data.get("wake_status"),
            "probe_status": data.get("probe_status"),
            "realtime": realtime,
            "fields_count": len(data.get("fields") or {}),
            "fields": fields,
        },
    }
    return diag
