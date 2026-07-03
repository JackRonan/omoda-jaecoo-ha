"""Device tracker: the car's GPS position (push 1301 / realtime probe)."""
from __future__ import annotations

from homeassistant.components.device_tracker import (
    ENTITY_ID_FORMAT,
    SourceType,
    TrackerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([OmodaJaecooTracker(coord)])


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class OmodaJaecooTracker(OmodaJaecooEntity, TrackerEntity, RestoreEntity):
    """GPS position. The live position is held in-memory in the coordinator (push 1301 /
    realtime probe) → after an HA restart it stays `unknown` until you press
    «Locate»/«Refresh location». So as not to lose the position on the map,
    at boot the last known fix is restored and used as a fallback until a live
    reading arrives (the bridge achieved the same effect via MQTT retained)."""

    _attr_icon = "mdi:car"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Location", "position",
                         entity_id_format=ENTITY_ID_FORMAT)
        self._restored_lat: float | None = None
        self._restored_lon: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._restored_lat = _f(last.attributes.get("latitude"))
            self._restored_lon = _f(last.attributes.get("longitude"))

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        live = _f(pos.get("lat") or pos.get("latitude"))
        return live if live is not None else self._restored_lat

    @property
    def longitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        live = _f(pos.get("lon") or pos.get("longitude"))
        return live if live is not None else self._restored_lon
