"""Binary sensor: porte/finestrini/cofano/baule (open) + comfort on/off + stato auto."""
from __future__ import annotations

from homeassistant.components.binary_sensor import ENTITY_ID_FORMAT, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SENSORS
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [Omoda9BinarySensor(coord, s) for s in SENSORS if s["comp"] == "binary_sensor"]
    ents.append(Omoda9Online(coord))
    ents.append(Omoda9Awake(coord))
    ents.append(Omoda9Session(coord))
    add(ents)


class Omoda9BinarySensor(Omoda9Entity, BinarySensorEntity):
    """ON se il campo è != 0 (open/onoff)."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda9 {spec['name']}", spec["key"],
                         entity_id_format=ENTITY_ID_FORMAT)
        self._key = spec["key"]
        self._attr_device_class = spec.get("dclass")

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.data.get("fields", {}).get(self._key)
        if v is None:
            return None
        return str(v) not in ("0", "", "None", "false", "False")


class Omoda9Online(Omoda9Entity, BinarySensorEntity):
    _attr_device_class = "connectivity"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Connessa", "online",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        if "onlineStatus" in rt:
            return str(rt["onlineStatus"]) not in ("0", "", "None")
        return None


class Omoda9Awake(Omoda9Entity, BinarySensorEntity):
    _attr_device_class = "running"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Auto sveglia", "awake",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("awake"))


class Omoda9Session(Omoda9Entity, BinarySensorEntity):
    _attr_device_class = "connectivity"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Sessione", "session",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("session_ok")
