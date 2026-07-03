"""Climate: advanced Omoda / Jaecoo climate control (pre-conditioning with settable temperature).

Replaces the old fixed 21° climate switch: now you set the desired temperature
(16–30 °C) and the car applies it (heats or cools up to the setpoint).
Uses the `airControl` command (the same, live-verified one that started the
fixed climate), varying `temperature` and the `times` duration (from number.omoda_jaecoo_clima_durata).

HA model: a single climate entity with OFF / HEAT_COOL modes (= the car brings the cabin
to the setpoint by heating or cooling) + a single temperature slider. The
on/off state comes from the `frontHVACState` telemetry; after a command the target
(optimistic) state is shown immediately until new data arrives from the car.

Heated/ventilated seats and the defrosters stay separate switches (switch.py):
so turning on the climate does NOT touch the seat state.
"""
from __future__ import annotations

from homeassistant.components.climate import (
    ENTITY_ID_FORMAT,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity, field_on

MIN_TEMP = 16.0
MAX_TEMP = 30.0
DEFAULT_TEMP = 21.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([OmodaJaecooClimate(coord)])


class OmodaJaecooClimate(OmodaJaecooEntity, ClimateEntity, RestoreEntity):
    """Car climate: ON (HEAT_COOL) at the chosen setpoint / OFF, via airControl."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_icon = "mdi:air-conditioner"
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coord) -> None:
        # entity_id FORCED to climate.omoda_jaecoo_clima (like the other component entities,
        # otherwise HA derives it "dirty" with the device name: climate.omoda_9_omoda_jaecoo_clima).
        # unique_id distinct from the old switch (suffix "climate") → new entity, not a rename.
        super().__init__(coord, "Climate", "climate", entity_id_format=ENTITY_ID_FORMAT)
        # Temperature range/step come from the vehicle's queryList capabilities when known
        # (e.g. a Jaecoo/PHEV differs), else the standard OMODA 16–30 °C / 1° defaults.
        self._attr_min_temp = float(coord.climate_min_temp) if coord.climate_min_temp else MIN_TEMP
        self._attr_max_temp = float(coord.climate_max_temp) if coord.climate_max_temp else MAX_TEMP
        self._attr_target_temperature_step = (
            float(coord.climate_temp_step) if coord.climate_temp_step else 1.0)
        self._target = min(self._attr_max_temp, max(self._attr_min_temp, DEFAULT_TEMP))
        self._opt_on: bool | None = None
        self._opt_anchor = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            t = last.attributes.get(ATTR_TEMPERATURE)
            try:
                if t is not None:
                    self._target = min(self._attr_max_temp, max(self._attr_min_temp, float(t)))
            except (TypeError, ValueError):
                pass

    # ── state ──
    def _live_on(self) -> bool | None:
        return field_on(self.coordinator.data.get("fields", {}).get("frontHVACState"))

    @property
    def target_temperature(self) -> float:
        return self._target

    @property
    def hvac_mode(self) -> HVACMode:
        on = self._opt_on
        if on is None:
            on = self._live_on()
        return HVACMode.HEAT_COOL if on else HVACMode.OFF

    def _handle_coordinator_update(self) -> None:
        # a new message from the car (last_seen changed) invalidates the optimism
        if self._opt_on is not None and \
                self.coordinator.data.get("last_seen") != self._opt_anchor:
            self._opt_on = None
            self._opt_anchor = None
        super()._handle_coordinator_update()

    def _set_optimistic(self, on: bool) -> None:
        self._opt_on = on
        self._opt_anchor = self.coordinator.data.get("last_seen")
        self.async_write_ha_state()

    # ── commands ──
    def _params(self) -> dict:
        dur = int(getattr(self.coordinator, "clima_duration", 15) or 15)
        return {"temperature": f"{self._target:.1f}", "times": str(dur)}

    async def _send(self, key: str, on: bool) -> None:
        self._set_optimistic(on)
        try:
            await self.coordinator.async_send_command(key, self._params())
        except Exception as err:  # noqa: BLE001
            self._opt_on = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Climate command failed: {err}") from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._send("clima_off", False)
        else:
            await self._send("clima_on", True)

    async def async_turn_on(self) -> None:
        await self._send("clima_on", True)

    async def async_turn_off(self) -> None:
        await self._send("clima_off", False)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        self._target = min(self._attr_max_temp, max(self._attr_min_temp, float(temp)))
        # if the climate is already on, immediately reapply the new setpoint; otherwise
        # just store it (it will be used at the next turn-on).
        if self.hvac_mode != HVACMode.OFF:
            await self._send("clima_on", True)
        else:
            self.async_write_ha_state()
