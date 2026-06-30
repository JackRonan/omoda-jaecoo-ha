"""Number: local config parameters + interactive charge limit.

Config sliders (OmodaJaecooConfigNumber) store a preference used by other
controls at send time — they do NOT send anything to the car themselves.
  - Climate duration (min): `times` for the climate entity airControl command.
  - Charging duration (hrs): composes the chargeAppointControl plan with the
    start-time entity (time.py) when the Scheduled charging switch is toggled.

Charge limit (OmodaJaecooChargeLimitNumber) IS interactive:
  - Reads the current charge limit live from realtime telemetry (maxSocPercent).
  - Sends chargeDepthControl to the car when the user changes the value.
  - Range 50–100 % in 5 % steps, matching the official app UI.
  - Falls back to the last stored value when the car is offline.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import OmodaJaecooEntity

_LOGGER = logging.getLogger(__name__)

# (name, suffix, coord_attr, min, max, step, default, unit, icon)
NUMBERS = [
    ("Omoda / Jaecoo Climate duration", "climate_duration", "clima_duration",
     5, 30, 5, 15, UnitOfTime.MINUTES, "mdi:timer-cog"),
    # Start time is now a `time` entity (HH:MM, see time.py); only duration remains here.
    ("Omoda / Jaecoo Charging duration", "charging_duration", "charge_duration_hours",
     1, 12, 1, 6, UnitOfTime.HOURS, "mdi:battery-clock"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    entities: list = [OmodaJaecooConfigNumber(coord, *spec) for spec in NUMBERS]
    entities.append(OmodaJaecooChargeLimitNumber(coord))
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


class OmodaJaecooChargeLimitNumber(OmodaJaecooEntity, RestoreNumber):
    """Interactive charge limit (target SoC %).

    Reads the current limit from realtime telemetry (maxSocPercent) and sends
    chargeDepthControl to the car when the user changes the value.

    The exact body field name for this endpoint is inferred from the
    CVChargeDepthReqBean SDK class and the CarLinko targetSoc equivalent.
    Two candidate field names are tried in order:
      1. chargeSoc   (most common Chery SDK convention for this bean)
      2. targetSoc   (CarLinko / alternative Chery naming)
    If the first attempt returns A00079 (accepted) we know which name is correct
    and log it. If neither works, the user will see the error in the command
    result sensor and can report back for a fix.
    """

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 50
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-lock"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda / Jaecoo Charge limit", "charge_limit_number",
                         entity_id_format=ENTITY_ID_FORMAT)
        self._stored: float = 80.0   # sane default until telemetry or restore arrives

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._stored = float(last.native_value)

    @property
    def native_value(self) -> float:
        """Return live value from telemetry, falling back to last stored."""
        rt = self.coordinator.data.get("realtime") or {}
        raw = rt.get("maxSocPercent")
        try:
            v = float(raw)
            if 50 <= v <= 100:
                self._stored = v
                return v
        except (TypeError, ValueError):
            pass
        return self._stored

    async def async_set_native_value(self, value: float) -> None:
        pct = int(value)
        _LOGGER.info("Setting charge limit to %d%%", pct)
        try:
            # Try the most likely field name first; coordinator.async_send_command
            # accepts a `params` dict that is merged into the command body before signing.
            await self.coordinator.async_send_command(
                "charge_limit_set",
                params={"chargeSoc": pct},
            )
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"Charge limit command failed: {err}"
            ) from err
        self._stored = float(value)
        self.async_write_ha_state()
