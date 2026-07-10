"""Repair flow — "wrong command PIN": reconfigure the 4-digit remote-command PIN without
removing the integration.

The issue is raised by the coordinator (`_raise_pin_issue`) when a command fails because the
backend rejects the taskId (wrong PIN / anti-lockout). The PIN is NOT used to log in →
correcting it is a pure write to entry.data + reload; the reload also resets the module-level
anti-lockout (`commands.reset_pin_lockout` in `_bind_core`)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import CONF_PIN


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Factory HA calls for the `pin_wrong` issue."""
    return OmodaJaecooPinRepairFlow(data or {})


class OmodaJaecooPinRepairFlow(RepairsFlow):
    """Ask for the new command PIN and apply it to the entry (then reload)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._entry_id: str | None = data.get("entry_id")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_pin()

    async def async_step_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        entry = (
            self.hass.config_entries.async_get_entry(self._entry_id)
            if self._entry_id
            else None
        )
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        errors: dict[str, str] = {}
        if user_input is not None:
            new_pin = (user_input.get(CONF_PIN) or "").strip()
            if not new_pin:
                errors["base"] = "pin_required"
            else:
                # write the new PIN and reload: _bind_core detects the change and resets the
                # anti-lockout; completing the fix flow removes the issue.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_PIN: new_pin}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(title="", data={})
        schema = vol.Schema(
            {vol.Required(CONF_PIN, default=entry.data.get(CONF_PIN, "")): str}
        )
        return self.async_show_form(step_id="pin", data_schema=schema, errors=errors)
