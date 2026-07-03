"""Cover: trunk, windows, sunroof (state of 5A02 fields + open/close commands).

Merges the read-only states (trunk trunkDoor, windows, sunroof sunroofState) with the
associated open/close buttons into native "cover" entities, with state + action in
a single card. NB: the 4 windows also remain as individual binary_sensors (detail of
"which window"); the "Windows" cover is the aggregate command. Window ventilation
remains a standalone button (not mappable onto open/close). Every open/close
ACTS on the car (= explicit consent from the user).
"""
from __future__ import annotations

from homeassistant.components.cover import (
    ENTITY_ID_FORMAT,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity, OmodaJaecooOptimisticMixin, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([
        OmodaJaecooCover(coord, "Door Trunk", "baule", ["trunkDoor"],
                    "baule_apri", "baule_chiudi", CoverDeviceClass.DOOR, "mdi:car-back"),
        OmodaJaecooCover(coord, "Window Control", "finestrini",
                    ["frontLeftWindowState", "frontRightWindowState",
                     "backLeftWindowState", "backRightWindowState"],
                    "finestrini_apri", "finestrini_chiudi", CoverDeviceClass.WINDOW, "mdi:car-door"),
        OmodaJaecooCover(coord, "Window Sunroof", "tetto", ["sunroofState"],
                    "tetto_apri", "tetto_chiudi", CoverDeviceClass.SHADE, "mdi:car-select"),
    ])


class OmodaJaecooCover(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, CoverEntity, RestoreEntity):
    """Motorized opening: OPEN if at least one of the associated fields is != 0.

    The real state arrives via MQTT only when the car is awake → after a command the
    target state is shown immediately (optimistic) and on HA restart the last known state is restored."""

    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, coord, name, suffix, keys, open_cmd, close_cmd, dclass, icon) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._keys = keys
        self._open_cmd = open_cmd
        self._close_cmd = close_cmd
        self._attr_device_class = dclass
        self._attr_icon = icon
        self._restored: bool | None = None  # True = closed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("open", "closed"):
            self._restored = last.state == "closed"

    def _live_closed(self) -> bool | None:
        fields = self.coordinator.data.get("fields", {})
        # field_on for each field: None=absent, True=open. Aligns "0.0" with the rest.
        states = [field_on(fields.get(k)) for k in self._keys]
        if all(s is None for s in states):
            return None  # no known field → restored/unknown surfaces
        return not any(states)  # at least one open → cover open

    @property
    def is_closed(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value  # True = closed
        live = self._live_closed()
        return live if live is not None else self._restored

    async def async_open_cover(self, **kwargs) -> None:
        await self._run_command(self._open_cmd, False)  # not closed = open

    async def async_close_cover(self, **kwargs) -> None:
        await self._run_command(self._close_cmd, True)
