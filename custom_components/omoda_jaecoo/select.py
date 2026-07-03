"""Select: windows as a single 3-state control (Closed / Ventilate / Open).

Replaces the old window cover + standalone "Ventilate" button with one neat control that
carries all three window positions the car supports (windowControl controlType 0/2/1).
State + all actions live in a single entity.

The car cannot report "ventilate" distinctly (telemetry only says a window is open or
closed), so — like the comfort switches — the chosen option is shown optimistically right
after a command until fresh telemetry arrives, then Closed/Open is derived from the four
per-window fields (which also stay as individual binary_sensors).
"""
from __future__ import annotations

from homeassistant.components.select import ENTITY_ID_FORMAT, SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity, OmodaJaecooOptimisticMixin, field_on

CLOSED = "Closed"
VENTILATE = "Ventilate"
OPEN = "Open"

# option → catalog command key (windowControl: 0=close, 2=ventilate, 1=open)
_CMD = {CLOSED: "finestrini_chiudi", VENTILATE: "ventilate_windows", OPEN: "finestrini_apri"}
_WINDOW_KEYS = ("frontLeftWindowState", "frontRightWindowState",
                "backLeftWindowState", "backRightWindowState")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([OmodaJaecooWindowSelect(coord)])


class OmodaJaecooWindowSelect(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SelectEntity, RestoreEntity):
    """Windows: Closed / Ventilate / Open in one control."""

    _attr_options = [CLOSED, VENTILATE, OPEN]
    _attr_icon = "mdi:car-door"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Windows", "windows_select", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._restored = last.state

    def _live_option(self) -> str | None:
        """Closed if all windows are closed, Open if any is open, None if unknown.
        (Ventilate is not distinguishable from telemetry → only shown optimistically.)"""
        fields = self.coordinator.data.get("fields", {})
        states = [field_on(fields.get(k)) for k in _WINDOW_KEYS]
        if all(s is None for s in states):
            return None
        return OPEN if any(states) else CLOSED

    @property
    def current_option(self) -> str | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_option()
        return live if live is not None else self._restored

    async def async_select_option(self, option: str) -> None:
        cmd = _CMD.get(option)
        if cmd is None:
            return
        await self._run_command(cmd, option)
