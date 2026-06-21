"""Device tracker: posizione GPS dell'auto (push 1301 / sonda realtime)."""
from __future__ import annotations

from homeassistant.components.device_tracker import (
    ENTITY_ID_FORMAT,
    SourceType,
    TrackerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([Omoda9Tracker(coord)])


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Omoda9Tracker(Omoda9Entity, TrackerEntity):
    _attr_icon = "mdi:car"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Posizione", "position",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        return _f(pos.get("lat") or pos.get("latitude"))

    @property
    def longitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        return _f(pos.get("lon") or pos.get("longitude"))
