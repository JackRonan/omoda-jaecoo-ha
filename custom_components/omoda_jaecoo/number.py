"""Number: local config parameters.

Config sliders (OmodaJaecooConfigNumber) store a preference used by other
controls at send time — they do NOT send anything to the car themselves.
  - Climate duration (min): `times` for the climate entity airControl command.
  - Charging duration (hrs): composes the chargeAppointControl plan with the
    start-time entity (time.py) when the Scheduled charging switch is toggled.

NB: there is deliberately NO charge-limit / target-SoC number here. The OMODA
"legend" backend has no charge-limit endpoint (confirmed against the app binary:
only chargeAppointControl exists; `chargeDepthControl` returns A07334 = unsupported
for the vehicle). Charge limit is car-screen-only for OMODA/Jaecoo.
"""
from __future__ import annotations

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import OmodaJaecooEntity

# (name, suffix, coord_attr, min, max, step, default, unit, icon)
NUMBERS = [
    ("Climate Duration", "climate_duration", "clima_duration",
     5, 30, 5, 15, UnitOfTime.MINUTES, "mdi:timer-cog"),
    # Start time is now a `time` entity (HH:MM, see time.py); only duration remains here.
    ("Charge Duration", "charging_duration", "charge_duration_hours",
     1, 12, 1, 6, UnitOfTime.HOURS, "mdi:battery-clock"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    entities: list = [OmodaJaecooConfigNumber(coord, *spec) for spec in NUMBERS]
    add(entities)


class OmodaJaecooConfigNumber(OmodaJaecooEntity, RestoreNumber):
    """Local config slider: writes its value onto the coordinator for other entities to read."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, name, suffix, attr, vmin, vmax, step, default, unit, icon) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._attr = attr
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._value = float(default)
        setattr(coord, attr, default)   # default immediately available to consumers

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._value = float(last.native_value)
        self._push()

    def _push(self) -> None:
        # Keep value as int when it is whole (hours/days) so command bodies
        # don't end up with "8.0" where the app sends integers.
        v = int(self._value) if float(self._value).is_integer() else self._value
        setattr(self.coordinator, self._attr, v)

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self._push()
        self.async_write_ha_state()
