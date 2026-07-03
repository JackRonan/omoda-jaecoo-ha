"""Switch: climate + comfort (defrost, steering wheel, seats).

Each switch merges the read-only state (a 5A02 telemetry field) with the two
ON/OFF commands from the catalog into a single card: ON via app = function enabled (climate at
21°/defrost/seats for ~15 min with the car's auto-shutoff timer), OFF = manual
shutoff command. The toggle ACTUATES on the car (= explicit user consent).

The two seats (driver heating / ventilation) are MUTUALLY EXCLUSIVE on the car side:
turning on the air turns off the heat and vice versa (verified in telemetry) → we reflect it
immediately in the optimistic state too, in addition to the real fields when they arrive.
"""
from __future__ import annotations

import ast
import asyncio

from homeassistant.components.switch import (
    ENTITY_ID_FORMAT,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, MACRO_WAKE_WAIT, MACRO_PRESET_S
from .entity import OmodaJaecooEntity, OmodaJaecooOptimisticMixin, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    # NB: the climate is NO longer here → it's a climate entity (climate.py) with a settable
    # temperature. What remains: comfort/seats/defrost + the two EV charging switches.
    ricarica = OmodaJaecooChargeSwitch(coord)
    ricarica_prog = OmodaJaecooScheduledChargeSwitch(coord)
    parabrezza = OmodaJaecooComfortSwitch(
        coord, "Climate Windshield Defrost", "frontWindshieldHeat", "frontWindshieldHeat",
        "defrost_parabrezza", "defrost_parabrezza_off", "mdi:car-defrost-front")
    lunotto = OmodaJaecooComfortSwitch(
        coord, "Climate Rear Window Defrost", "rWinHeatingState", "rWinHeatingState",
        "defrost_lunotto", "defrost_lunotto_off", "mdi:car-defrost-rear")
    volante = OmodaJaecooComfortSwitch(
        coord, "Climate Steering Wheel Heating", "steerWheelHeating", "steerWheelHeating",
        "volante_caldo", "volante_caldo_off", "mdi:steering")
    sedile_caldo = OmodaJaecooComfortSwitch(
        coord, "Seat Driver Heating", "dSeatHeatingState", "dSeatHeatingState",
        "sedile_guida_caldo", "sedile_guida_caldo_off", "mdi:car-seat-heater")
    sedile_aria = OmodaJaecooComfortSwitch(
        coord, "Seat Driver Ventilation", "dSeatVentilateState", "dSeatVentilateState",
        "sedile_guida_aria", "sedile_guida_aria_off", "mdi:car-seat-cooler")
    # passenger and rear L/R seats: same model as the driver (telemetry *State*
    # ↔ seatControl command). Rear center excluded (no dedicated command).
    pass_caldo = OmodaJaecooComfortSwitch(
        coord, "Seat Passenger Heating", "pSeatHeatingState", "pSeatHeatingState",
        "sedile_passeggero_caldo", "sedile_passeggero_caldo_off", "mdi:car-seat-heater")
    pass_aria = OmodaJaecooComfortSwitch(
        coord, "Seat Passenger Ventilation", "pSeatVentilateState", "pSeatVentilateState",
        "sedile_passeggero_aria", "sedile_passeggero_aria_off", "mdi:car-seat-cooler")
    psx_caldo = OmodaJaecooComfortSwitch(
        coord, "Seat Rear Left Heating", "lSeatHeatingState2", "lSeatHeatingState2",
        "sedile_post_sx_caldo", "sedile_post_sx_caldo_off", "mdi:car-seat-heater")
    psx_aria = OmodaJaecooComfortSwitch(
        coord, "Seat Rear Left Ventilation", "lSeatVentilateState2", "lSeatVentilateState2",
        "sedile_post_sx_aria", "sedile_post_sx_aria_off", "mdi:car-seat-cooler")
    pdx_caldo = OmodaJaecooComfortSwitch(
        coord, "Seat Rear Right Heating", "rSeatHeatingState2", "rSeatHeatingState2",
        "sedile_post_dx_caldo", "sedile_post_dx_caldo_off", "mdi:car-seat-heater")
    pdx_aria = OmodaJaecooComfortSwitch(
        coord, "Seat Rear Right Ventilation", "rSeatVentilateState2", "rSeatVentilateState2",
        "sedile_post_dx_aria", "sedile_post_dx_aria_off", "mdi:car-seat-cooler")
    # heat and air are mutually exclusive on EVERY seat → reciprocal wiring per pair
    for caldo, aria in ((sedile_caldo, sedile_aria), (pass_caldo, pass_aria),
                        (psx_caldo, psx_aria), (pdx_caldo, pdx_aria)):
        caldo._exclusive = aria
        aria._exclusive = caldo
    # comfort "all" macro (coolingControl/heatingControl): climate + all seats (+ steering wheel
    # and defrosters for heat) in a single command, like the app. They work with the car OFF.
    # Cool and heat are mutually exclusive.
    raffredda = OmodaJaecooClimaMacroSwitch(
        coord, "Climate Cool Down All", "raffredda_tutto",
        "climate_cool_on", "climate_cool_off", "mdi:snowflake")
    riscalda = OmodaJaecooClimaMacroSwitch(
        coord, "Climate Heat Up All", "riscalda_tutto",
        "climate_heat_on", "climate_heat_off", "mdi:heat-wave")
    raffredda._exclusive = riscalda
    riscalda._exclusive = raffredda
    antifurto = OmodaJaecooTheftAlarmSwitch(coord)
    polling = OmodaJaecooPollingSwitch(coord)
    add([ricarica, ricarica_prog, parabrezza, lunotto, volante,
         sedile_caldo, sedile_aria, pass_caldo, pass_aria,
         psx_caldo, psx_aria, pdx_caldo, pdx_aria,
         raffredda, riscalda, antifurto, polling])


class OmodaJaecooComfortSwitch(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """Comfort switch: ON if the associated 5A02 field is != 0.

    The real state arrives via MQTT only when the car is awake → after a command the
    target state is shown immediately (optimistic, see OmodaJaecooOptimisticMixin) and on an
    HA restart the last known state is restored."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coord, name: str, suffix: str, field: str,
                 on_cmd: str, off_cmd: str, icon: str) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._field = field
        self._on_cmd = on_cmd
        self._off_cmd = off_cmd
        self._attr_icon = icon
        self._restored: bool | None = None
        self._exclusive: "OmodaJaecooComfortSwitch | None" = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_on(self) -> bool | None:
        return field_on(self.coordinator.data.get("fields", {}).get(self._field))

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_on()
        return live if live is not None else self._restored

    async def async_turn_on(self, **kwargs) -> None:
        # mutual exclusion: turning this on immediately turns off the twin (e.g. seat air↔heat)
        if self._exclusive is not None:
            self._exclusive._set_optimistic(False)
        await self._run_command(self._on_cmd, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command(self._off_cmd, False)


class OmodaJaecooChargeSwitch(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """IMMEDIATE charging on/off (chargeStartStopControl, controlType 1/0).

    On this channel the car does NOT publish a "charging" state → the switch is
    optimistic: after the command it shows the target immediately and on restart restores
    the last known state. The plug-connected state is the binary_sensor `Charge plug`."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:battery-charging"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Charge Switch", "ricarica", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        return self._restored

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("ricarica_start", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("ricarica_stop", False)


class OmodaJaecooClimaMacroSwitch(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """Climate "all" macro (coolingControl/heatingControl): a preset that turns on climate +
    ALL seats (+ windshield/rear-window defrosters and steering wheel for heat) in one shot,
    with a single command — exactly like the official app.

    ⚠️ The comfort modules (climate+seats) respond ONLY when the vehicle is awake and its systems
    are powered. Pressing the macro on a sleeping car (parked recently) makes all the modules
    time out. So the macro WAKES the car first (locate/vehicleLocation) and WAITS
    MACRO_WAKE_WAIT seconds for the TBOX to power the comfort bus, THEN sends the command — in
    BOTH directions (shutdown wakes too, so "all OFF" reaches the rear
    seats, which are independent of the climate). Verified live 2026-06-21.

    State: the car does NOT publish a dedicated "preset active" state → a switch with its own
    state (PERSISTENT optimistic: not cleared by telemetry messages, otherwise
    it couldn't be turned off). It auto-shuts off by itself after MACRO_PRESET_S (the car closes the
    preset after ~15 min). Cool and Heat are mutually exclusive."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coord, name: str, suffix: str,
                 on_cmd: str, off_cmd: str, icon: str) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._on_cmd = on_cmd
        self._off_cmd = off_cmd
        self._attr_icon = icon
        self._restored: bool | None = None
        self._expire_unsub = None
        self._exclusive: "OmodaJaecooClimaMacroSwitch | None" = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_expire()
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        return bool(self._restored)

    def _handle_coordinator_update(self) -> None:
        # macro WITHOUT a real state from the car → do NOT clear the state on telemetry messages
        # (the mixin would): we keep the state we set, we only update the UI.
        self.async_write_ha_state()

    def _cancel_expire(self) -> None:
        if self._expire_unsub is not None:
            self._expire_unsub()
            self._expire_unsub = None

    @callback
    def _set_state(self, value: bool) -> None:
        self._set_optimistic(value)
        self._restored = value

    async def _wake_then(self, cmd: str, target: bool) -> None:
        """Wake the car, wait for the comfort modules to be powered, then send the command."""
        self._cancel_expire()
        self._set_state(target)
        # wake (vehicleLocation = wake + GPS, benign); don't block the macro if it fails
        try:
            await self.coordinator.async_send_command("locate_car")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(MACRO_WAKE_WAIT)  # let the comfort bus power up
        try:
            await self.coordinator.async_send_command(cmd)
        except Exception as err:  # noqa: BLE001
            self._set_state(False)
            self.async_write_ha_state()
            raise HomeAssistantError(f"Command «{cmd}» failed: {err}") from err
        if target:
            # the car closes the preset after ~15 min → brings the switch back to OFF by itself
            @callback
            def _expire(_now) -> None:
                self._expire_unsub = None
                self._set_state(False)
                self.async_write_ha_state()
            self._expire_unsub = async_call_later(self.hass, MACRO_PRESET_S, _expire)

    async def async_turn_on(self, **kwargs) -> None:
        if self._exclusive is not None:
            self._exclusive._cancel_expire()
            self._exclusive._set_state(False)
            self._exclusive.async_write_ha_state()
        await self._wake_then(self._on_cmd, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._wake_then(self._off_cmd, False)


class OmodaJaecooScheduledChargeSwitch(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """SCHEDULED charging on/off (chargeAppointControl, body with a nested array).

    When turned on, it builds the plan from the preferences (time entity "start
    time" + number "duration", every day) and sends mainSwitch=1 + active plan;
    turning off sends mainSwitch=0. startTime is in MINUTES from midnight (verified
    live: 465 = 07:45). The real state arrives from the `chargeAppointPlans` telemetry."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Charge Scheduled Switch", "ricarica_programmata",
                         entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_on(self) -> bool | None:
        raw = self.coordinator.data.get("fields", {}).get("chargeAppointPlans")
        if not raw:
            return None
        try:
            plans = ast.literal_eval(raw) if isinstance(raw, str) else raw
            if plans:
                return field_on(plans[0].get("switchStatus"))
        except (ValueError, SyntaxError, AttributeError, IndexError, TypeError):
            return None
        return None

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_on()
        return live if live is not None else self._restored

    def _plan(self, switch_status: int) -> dict:
        # start time in minutes-from-midnight from the time entity; fallback to the old
        # hours slider (compat) and finally 08:00 if no preference is available yet.
        mins = getattr(self.coordinator, "charge_start_minutes", None)
        if mins is None:
            mins = int(getattr(self.coordinator, "charge_start_hour", 8) or 8) * 60
        dur_h = int(getattr(self.coordinator, "charge_duration_hours", 6) or 6)
        return {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": int(mins),
                "switchStatus": switch_status, "timeConsuming": dur_h * 60}

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_on", True,
                                {"mainSwitch": 1, "chargeAppointPlans": [self._plan(1)]})

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_off", False,
                                {"mainSwitch": 0, "chargeAppointPlans": [self._plan(0)]})


class OmodaJaecooPollingSwitch(OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """"Auto Update" switch: enables/disables the periodic poll
    (wake + read) without touching the options. It is NOT a command to the car: it acts only
    on the local timer. ON by default; the state is restored on an HA restart.

    When it is OFF the car is no longer woken automatically: the sensors stay
    on the last known value (refreshable by hand with the "Refresh location" button)."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:autorenew"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Auto Update", "polling_auto",
                         entity_id_format=ENTITY_ID_FORMAT)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # restore the last choice: if it was OFF, stop the poll started by default in setup.
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.set_poll_enabled(last.state == "on")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.poll_enabled)

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_poll_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_poll_enabled(False)
        self.async_write_ha_state()


class OmodaJaecooTheftAlarmSwitch(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, SwitchEntity, RestoreEntity):
    """Car theft alarm (theftAlarm setSwitch, /act endpoint).

    ON = the car triggers the alarm and sends alerts in case of unauthorized movement,
    door forcing, window breakage or other break-ins (official app description).
    Unlike the comfort features, the state is NOT in MQTT telemetry: it's read via REST
    (querySwitch). Strategy: initial seed from the real reading, then optimistic state after
    the toggle (setSwitch ACTUATES and wants the car awake), and restore of the last
    known state on an HA restart."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:shield-car"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Alarm Theft", "antifurto", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None
        self._real: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"
        # seed the real state from the backend (read-only, best-effort: must not break the setup)
        try:
            v = await self.coordinator.async_query_theft()
            if v is not None:
                self._real = v != 0
                self.async_write_ha_state()
        except Exception:  # noqa: BLE001
            pass

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        if self._real is not None:
            return self._real
        return self._restored

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("alarm_theft_on", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("alarm_theft_off", False)
