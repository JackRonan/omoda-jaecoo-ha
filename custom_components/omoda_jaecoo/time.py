"""Time: local configuration times (not direct commands to the car).

Like the configuration numbers, these entities do NOT send anything to the car on their own:
they store a preference used by the other controls at send time.
  - Scheduled charging · start time: the time (HH:MM) from which to start
    charging. The "Scheduled charging" switch composes the `chargeAppointControl` plan
    using this value.

Why a `time` entity and not a 0–23 number: the car accepts the time in MINUTES from
midnight (verified live on real scheduled charging: startTime 465 = 07:45)
→ with a time selector you can also pick the minutes, not just the whole hour.

It is a RestoreEntity → on HA restart it restores the last set time and rewrites it
onto the coordinator (from which the switch reads it as `charge_start_minutes`).
"""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import ENTITY_ID_FORMAT, TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity

# (name, suffix, minutes-attribute on the coordinator, default HH, default MM, icon)
TIMES = [
    ("Charge Start Time", "charging_start_time",
     "charge_start_minutes", 8, 0, "mdi:clock-start"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([OmodaJaecooConfigTime(coord, *spec) for spec in TIMES])


class OmodaJaecooConfigTime(OmodaJaecooEntity, TimeEntity, RestoreEntity):
    """Local configuration time selector: publishes the minutes-from-midnight onto the coordinator."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, name, suffix, attr, def_h, def_m, icon) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._attr = attr
        self._attr_icon = icon
        self._value = time(hour=def_h, minute=def_m)
        setattr(coord, attr, def_h * 60 + def_m)   # default immediately available to the switch

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                hh, mm, *_ = (int(p) for p in last.state.split(":"))
                self._value = time(hour=hh, minute=mm)
            except (ValueError, TypeError):
                pass
        self._push()

    def _push(self) -> None:
        setattr(self.coordinator, self._attr, self._value.hour * 60 + self._value.minute)

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        # seconds are not needed (the car works in minutes) → we zero them out
        self._value = value.replace(second=0, microsecond=0)
        self._push()
        self.async_write_ha_state()
