"""Binary sensor: doors/windows/hood/trunk (open) + comfort on/off + car state.

The car's physical state (5A02) and connectivity are in-memory in the coordinator →
after an HA restart they go back to `unknown`. The state binary_sensors are RestoreEntity:
they restore the last known on/off as a fallback (parity with the bridge, which persisted via
MQTT retained) until live data arrives. Exception: `auto_sveglia` does NOT persist
(it's a derived flag "the car is publishing right now" → at boot it must be off).
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, FIELDS_AS_RICH_ENTITY
from .coordinator import SENSORS
from .entity import OmodaJaecooEntity, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [
        OmodaJaecooBinarySensor(coord, s)
        for s in SENSORS
        if s["comp"] == "binary_sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY
    ]
    ents.append(OmodaJaecooOnline(coord))
    ents.append(OmodaJaecooAwake(coord))
    ents.append(OmodaJaecooSession(coord))
    # — warnings from the realtime channel (Round B): tires + low battery —
    for suffix, name, field, dc in _RT_BINARIES:
        ents.append(OmodaJaecooRealtimeBinary(coord, name, suffix, field, dc))
    add(ents)


# Warnings present on the realtime channel: ON = anomaly. `*TyreCall` = tire
# pressure warning (device_class PROBLEM); `socLowCall` = traction battery low
# (device_class BATTERY → on = "low"). ON/OFF convention (1=warning) to be confirmed from
# the live car. (suffix, name, realtime field, device_class)
_RT_BINARIES = [
    ("front_left_tire_warning", "Tire Front Left Warning", "lFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("front_right_tire_warning", "Tire Front Right Warning", "rFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("rear_left_tire_warning", "Tire Rear Left Warning", "lRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("rear_right_tire_warning", "Tire Rear Right Warning", "rRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("battery_low", "Battery Low", "socLowCall", BinarySensorDeviceClass.BATTERY),
]


class _OmodaJaecooRestoreBinary(OmodaJaecooEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor that restores the last on/off state on HA restart.

    Subclasses provide `_live_is_on()` (current state from the coordinator, or
    None if absent); while live is None the last restored value is used."""

    def __init__(self, coord, name: str, unique_suffix: str) -> None:
        super().__init__(coord, name, unique_suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_is_on(self) -> bool | None:
        raise NotImplementedError

    @property
    def is_on(self) -> bool | None:
        live = self._live_is_on()
        return live if live is not None else self._restored


class OmodaJaecooBinarySensor(_OmodaJaecooRestoreBinary):
    """ON if the field is != 0 (open/onoff)."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, spec["name"], spec["key"])
        self._key = spec["key"]
        dc = spec.get("dclass")
        self._attr_device_class = BinarySensorDeviceClass(dc) if dc else None
        # fields the car never sends while parked (e.g. sunroof blind, windshield heating):
        # they always stay "unknown" → in the diagnostic category, out of the main controls.
        if spec.get("diag"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _live_is_on(self) -> bool | None:
        # [MED] None/"None"/"" = absent → None (the restored value surfaces, not a false off);
        # numeric comparison via field_on (aligns "0.0" with lock/switch/cover).
        return field_on(self.coordinator.data.get("fields", {}).get(self._key))


class OmodaJaecooOnline(_OmodaJaecooRestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Diagnostic Connection", "online")
        self._attr_translation_key = "connection"

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt["onlineStatus"]) if "onlineStatus" in rt else None


class OmodaJaecooRealtimeBinary(_OmodaJaecooRestoreBinary):
    """Generic warning on a realtime channel field (see `_RT_BINARIES`).

    Same pattern as `OmodaJaecooOnline` (reads from coordinator.data["realtime"]) but in
    the diagnostic category. ON if the field is != 0; absent → restores the last known."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, field: str,
                 device_class: BinarySensorDeviceClass) -> None:
        super().__init__(coord, name, f"rt_{suffix}")
        self._field = field
        self._attr_device_class = device_class

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt[self._field]) if self._field in rt else None


class OmodaJaecooAwake(OmodaJaecooEntity, BinarySensorEntity):
    """Derived flag "the car is publishing right now" — NOT persistent (off at boot)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Diagnostic Car Awake", "awake",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("awake"))


class OmodaJaecooSession(_OmodaJaecooRestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Diagnostic Session", "session")

    def _live_is_on(self) -> bool | None:
        return self.coordinator.data.get("session_ok")
