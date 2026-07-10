"""Sensor: lock, seat levels (level) + battery/speed/session
+ bridge diagnostic sensors (command/wake-up/probe results, timestamps).

The entity_ids reproduce 1:1 those of the bridge (omoda_jaecoo_*) for history continuity.
All sensors are RestoreSensor: on HA restart they restore the last known value
as a fallback (parity with the bridge, which persisted via MQTT retained) until
live data arrives from the car.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FIELDS_AS_RICH_ENTITY
from .coordinator import SENSORS
from .entity import OmodaJaecooEntity, get_rt_field


# ───────────────────────── "realtime" sensors (Round B) ─────────────────────────
# Fields of the REST channel /asr/manager/realtime (in coordinator.data["realtime"]),
# updated at the car's WAKE-UP (read-only probe). Unlike the 5A02 (MQTT),
# here the real VALUES of range/odometer/tires/consumption/charging are actually present
# (on the 5A02 they were only unit flags "1"). Validated 1:1 against the official
# CVRealtimeResBean bean of the Chery SDK. A spec table avoids 20+ twin classes.
#
# Values/units CONFIRMED from the live car while awake (2026-06-21, 84 fields):
#   pureElectricRange=60 km · mileageSurplus=215 km (total) · cruiseRange=134 (estimate)
#   lFrontTyreKpa=292 (=42 psi) → kPa · tire temp 34-35 °C · *TyreCall/socLowCall=0=ok
#   oilSurplus=23 → LITERS (215−60=155 km on gasoline /23 L ≈ 15 L/100km) · averageFuel=0.0
#   avgHkPowerKwh50km=20.6 → kWh/100km · totalVoltage=323.1 V · totalCurrent=0.0 A (real HV!)
#   remainChargeTime ABSENT when the car isn't charging (will appear while charging).

C = UnitOfTemperature.CELSIUS
KM = UnitOfLength.KILOMETERS
KPA = UnitOfPressure.KPA
BAR = UnitOfPressure.BAR
MIN = UnitOfTime.MINUTES
VOLT = UnitOfElectricPotential.VOLT
AMP = UnitOfElectricCurrent.AMPERE
KW = UnitOfPower.KILO_WATT
DIST = SensorDeviceClass.DISTANCE
TEMP = SensorDeviceClass.TEMPERATURE
PRESS = SensorDeviceClass.PRESSURE
DUR = SensorDeviceClass.DURATION
VOLTAGE = SensorDeviceClass.VOLTAGE
CURRENT = SensorDeviceClass.CURRENT
POWER = SensorDeviceClass.POWER
MEAS = SensorStateClass.MEASUREMENT
TOTAL = SensorStateClass.TOTAL_INCREASING


@dataclass(frozen=True)
class _RtSpec:
    """Spec of a realtime sensor. `numeric=False` → raw value (state/enum)."""

    suffix: str           # unique_id suffix (stable): f"{vin}_rt_<suffix>"
    name: str             # name → "Omoda / Jaecoo <name>" → slugified entity_id
    field: str | tuple    # key(s) in the realtime dict (tuple = fallback: first present wins,
                          #   so a single spec covers different field names PHEV vs BEV)
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    diag: bool = False
    numeric: bool = True
    vmap: dict | None = None  # raw code → readable text (enum fields)
    invalid: tuple = ()       # values (float) = "no reading" placeholder (HV off) → keep the last known
    compute: Callable | None = None  # value COMPUTED from several realtime fields (ignores `field`)
    scale: float | None = None  # multiplicative factor on the raw value (e.g. kPa→bar = 0.01)
    precision: int | None = None  # decimal digits suggested for the UI


# ── code→text maps for the charging enum fields ──
# The values are 3-state enums ("0"/"1"/"2", confirmed by the comparisons in the app
# code `rus_car_state_model.dart`). `0` = idle state verified from the live car
# (car parked, not charging). The semantics of 1/2 follow the EV convention;
# any unexpected code stays readable as "Unknown (N)" (see
# OmodaJaecooRealtimeSensor._live_value) → no information lost, no invented value.
CHARGE_STATE_MAP = {"0": "Not charging", "1": "Charging", "2": "Charging completed"}
APPT_CHARGE_STATE_MAP = {"0": "Disabled", "1": "Active", "2": "Running"}
FAST_GUN_MAP = {"0": "Disconnected", "1": "Connected", "2": "Connected (fast charging)"}


def _rt_float(rt: dict, *fields):
    """First realtime field present and parsable as a float (multi-name fallback), or None."""
    for f in fields:
        v = get_rt_field(rt, f)
        if v is None or str(v).strip() in ("", "None"):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _range_totale(rt: dict):
    """REAL total range.
    PHEV = electric (`pureElectricRange`) + gasoline (`mileageSurplus`).
    BEV  = electric only (no gasoline field): uses `dynamicPureElectricRange`.
    None if the electric range is missing entirely → the last known value stays (RestoreSensor)."""
    elec = _rt_float(rt, "pureElectricRange", "dynamicPureElectricRange")
    if elec is None:
        return None
    fuel = _rt_float(rt, "mileageSurplus") or 0.0
    return elec + fuel


_RT_SENSORS: list[_RtSpec] = [
    # ── P1 · range / kilometers (km values confirmed from the live car) ──
    # `pureElectricRange` = PHEV; on BEVs that field does NOT exist → the car sends
    # `dynamicPureElectricRange` (real range, = the one shown in the app: e.g. 235 km /
    # 146 mi). Fallback in order so a single spec covers both powertrains.
    _RtSpec("range_elettrico", "Range Electric",
            ("pureElectricRange", "dynamicPureElectricRange"),
            DIST, KM, MEAS, "mdi:map-marker-distance"),
    # WLTP (homologated) range — on BEVs `wltcPureElectricRange` (e.g. 279 km); diagnostic.
    _RtSpec("range_elettrico_wltp", "Range Electric (WLTP)", "wltcPureElectricRange",
            DIST, KM, MEAS, "mdi:map-marker-distance", diag=True),
    # mileageSurplus = GASOLINE range (combustion engine), NOT the total: verified on
    # the live car 2026-06-23 that it stays 215 km while the electric range drops (60→27 km) and
    # the fuel is unchanged (oilSurplus 23 L) → it follows the tank, not the battery.
    _RtSpec("range_benzina", "Range Gasoline", "mileageSurplus",
            DIST, KM, MEAS, "mdi:gas-station"),
    # Real TOTAL range = electric + gasoline (COMPUTED field, not a raw field).
    # Reuses the historical suffix "range_totale" → the entity sensor.omoda_jaecoo_autonomia_totale stays,
    # but now shows the correct sum instead of just mileageSurplus.
    _RtSpec("range_totale", "Range Total", "",
            DIST, KM, MEAS, "mdi:map-marker-distance", compute=_range_totale),
    # cruiseRange = alternative combined estimate (134 km from the live car) → diagnostic.
    _RtSpec("range_combinato", "Range Combined (Estimate)", "cruiseRange",
            DIST, KM, MEAS, "mdi:map-marker-distance", diag=True),
    _RtSpec("odometro", "Odometer", "odometer",
            DIST, KM, TOTAL, "mdi:counter"),
    _RtSpec("km_ibrido", "Hybrid Mileage", "hybridMileage",
            DIST, KM, TOTAL, "mdi:counter", diag=True),
    # ── P1 · TPMS pressure (car field in kPa → shown in BAR as in the app: ÷100) ──
    _RtSpec("gomma_ant_sx_press", "Tire Front Left Pressure", "lFrontTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_ant_dx_press", "Tire Front Right Pressure", "rFrontTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_post_sx_press", "Tire Rear Left Pressure", "lRearTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_post_dx_press", "Tire Rear Right Pressure", "rRearTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    # ── P1 · TPMS temperature (°C, diagnostic) ──
    _RtSpec("gomma_ant_sx_temp", "Tire Front Left Temperature", "lFrontTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_ant_dx_temp", "Tire Front Right Temperature", "rFrontTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_post_sx_temp", "Tire Rear Left Temperature", "lRearTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_post_dx_temp", "Tire Rear Right Temperature", "rRearTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    # ── P2 · consumption and remaining (units confirmed from the live car) ──
    _RtSpec("consumo_carburante", "Fuel Average Consumption", "averageFuel",
            None, "L/100 km", MEAS, "mdi:gas-station"),
    # avgHkPowerKwh50km=20.6 from the live car (PHEV) → kWh/100km (the "50km" name is misleading).
    # On BEVs that field is NOT there: the car sends `avgHkPower` (e.g. 17.7 = 177 Wh/km) → fallback.
    # -100 = "no data" placeholder when the car is parked (HV off) → keep the last known.
    _RtSpec("consumo_elettrico", "Electric Average Consumption",
            ("avgHkPowerKwh50km", "avgHkPower"),
            None, "kWh/100 km", MEAS, "mdi:lightning-bolt", invalid=(-100.0,)),
    # Home Assistant cannot convert energy-per-distance units, so for miles users we also
    # expose the car's own miles-per-kWh efficiency figure (avgHkPowerMikwh, e.g. 3.5).
    _RtSpec("efficienza_elettrica", "Electric Efficiency", "avgHkPowerMikwh",
            None, "mi/kWh", MEAS, "mdi:lightning-bolt", diag=True, invalid=(-100.0,)),
    # oilSurplus=23 from the live car → LITERS (confirmed by the gasoline range calculation).
    _RtSpec("carburante_residuo", "Fuel Remaining", "oilSurplus",
            None, "L", MEAS, "mdi:fuel"),
    # ── P2 · high-voltage battery (valid ONLY when the car is driving/charging) ──
    # When parked the car sends 0 V / -1000 A = "HV off" placeholder, not real readings:
    # marked invalid → the sensor keeps the last known value instead of zeroing out.
    _RtSpec("tensione_hv", "HV Battery Voltage", "totalVoltage",
            VOLTAGE, VOLT, MEAS, "mdi:flash", diag=True, invalid=(0.0,)),
    _RtSpec("corrente_hv", "HV Battery Current", "totalCurrent",
            CURRENT, AMP, MEAS, "mdi:current-dc", diag=True, invalid=(-1000.0,)),
    # ── P2 · charging ──
    # remainChargeTime: ABSENT when the car isn't charging (will appear while charging). Assumed
    # in MINUTES — to be reconfirmed with the car charging. chargeState/appointmentChargeState/
    # fastChargingGunStatus = codes (all 0 = idle from the live car) → raw, to be decoded.
    _RtSpec("tempo_ricarica", "Charge Remaining Time", "remainChargeTime",
            DUR, MIN, None, "mdi:timer-sand"),
    # Instantaneous charging power (kW): 0.0 at idle, rises while charging. Present on BEVs
    # (`chargingPower`) → useful for following an AC/DC session live.
    _RtSpec("potenza_ricarica", "Charging Power", "chargingPower",
            POWER, KW, MEAS, "mdi:ev-station", precision=1),
    _RtSpec("stato_ricarica", "Charge State", "chargeState",
            None, None, None, "mdi:ev-station", diag=True, numeric=False,
            vmap=CHARGE_STATE_MAP),
    _RtSpec("ricarica_prog_stato", "Charge Scheduled Status", "appointmentChargeState",
            None, None, None, "mdi:calendar-clock", diag=True, numeric=False,
            vmap=APPT_CHARGE_STATE_MAP),
    _RtSpec("presa_rapida", "Charge Fast Port", "fastChargingGunStatus",
            None, None, None, "mdi:ev-plug-ccs2", diag=True, numeric=False,
            vmap=FAST_GUN_MAP),
    # ── P2 · climate target ──
    _RtSpec("temp_imp_sx", "Climate Target Temp Left", "frontSetTempLeft",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("temp_imp_dx", "Climate Target Temp Right", "frontSetTempRight",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    # NB: no charge-limit sensor — the OMODA "legend" backend never sends a target-SoC
    # field (maxSocPercent absent; charge limit is car-screen-only). See number.py.
]

# Realtime specs that only make sense on a vehicle with a combustion engine. On a confirmed
# BEV (queryList powerType == 0) these are never created at all — cleaner than letting them
# sit permanently "unavailable". On PHEV/unknown they're created as usual (availability gating
# then hides them if the car happens not to report the field).
_FUEL_ONLY_SUFFIXES = {"range_benzina", "consumo_carburante", "carburante_residuo", "km_ibrido"}


def _rt(coord, field) -> str | None:
    """Raw value of the realtime field, or None if absent/empty. `field` can be a
    tuple of alternative names (PHEV/BEV fallback): the first present wins."""
    rt = coord.data.get("realtime") or {}
    fields = field if isinstance(field, (tuple, list)) else (field,)
    for f in fields:
        v = get_rt_field(rt, f)
        if v is not None and str(v).strip() not in ("", "None"):
            return str(v)
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents: list = [
        OmodaJaecooFieldSensor(coord, s)
        for s in SENSORS
        if s["comp"] == "sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY
    ]
    ents.append(OmodaJaecooBattery(coord))
    ents.append(OmodaJaecooSpeed(coord))
    # — "rich" sensors from the realtime channel (Round B): range, odometer, tires,
    #   consumption, charging, climate target —
    bev = coord.is_pure_electric()
    ents += [OmodaJaecooRealtimeSensor(coord, s) for s in _RT_SENSORS
             if not (bev and s.suffix in _FUEL_ONLY_SUFFIXES)]
    ents.append(OmodaJaecooSessionStatus(coord))
    # — diagnostic sensors (parity with the bridge) —
    # Explicit object_id → the entity_id is STABLE and translation-proof. Without it the
    # entity_id was slugify(name), so renaming the display name (e.g. "… → Diagnostic Command
    # Result") silently moved the entity_id and broke the failed-command blueprint's default.
    ents.append(OmodaJaecooTextSensor(coord, "Diagnostic Command Result", "cmd_status", "cmd_status",
                                      "mdi:car-cog", object_id="omoda_jaecoo_command_result"))
    ents.append(OmodaJaecooTextSensor(coord, "Diagnostic Wake-up Result", "wake_status", "wake_status",
                                      "mdi:car-connected", object_id="omoda_jaecoo_wake_result"))
    ents.append(OmodaJaecooTextSensor(coord, "Diagnostic Location Probe Result", "probe_status", "probe_status",
                                      "mdi:crosshairs-gps", object_id="omoda_jaecoo_location_probe_result"))
    ents.append(OmodaJaecooTimestampSensor(coord, "Diagnostic Last Seen", "lastseen", "last_seen", "mdi:car-clock"))
    ents.append(OmodaJaecooTimestampSensor(coord, "Diagnostic Last Wake-up", "wake_ts", "last_wake", "mdi:car-clock"))
    ents.append(OmodaJaecooTimestampSensor(coord, "Diagnostic Last Position", "pos_fix", "last_pos_fix", "mdi:map-marker-clock"))
    # Freshness of the car's realtime frame (resultTime): how old the shown battery/odometer
    # reading is — useful with a parked car to tell a recent frame from a stale one.
    ents.append(OmodaJaecooTimestampSensor(coord, "Diagnostic Car Data Updated", "car_data_ts", "car_data_ts", "mdi:database-clock"))
    add(ents)


class _OmodaJaecooRestoreSensor(OmodaJaecooEntity, RestoreSensor):
    """Base Omoda / Jaecoo sensor that survives an HA restart.

    The state (5A02 telemetry, realtime, diagnostics) is in-memory in the coordinator
    → after a restart it goes back to `unknown`. Here we restore the last known value and
    use it as a fallback until live data arrives. Subclasses provide
    `_live_value()` (current value from the coordinator, or None if absent)."""

    def __init__(self, coord, name: str, unique_suffix: str, object_id: str | None = None) -> None:
        super().__init__(coord, name, unique_suffix, object_id=object_id,
                         entity_id_format=ENTITY_ID_FORMAT)
        self._restored = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None:
            self._restored = last.native_value

    def _live_value(self):
        """Subclasses: current value from the coordinator, or None if absent."""
        raise NotImplementedError

    @property
    def native_value(self):
        live = self._live_value()
        return live if live is not None else self._restored


class OmodaJaecooFieldSensor(_OmodaJaecooRestoreSensor):
    """lock (0=Locked/1=Unlocked), seat level (Level N) or raw value."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda / Jaecoo {spec['name']}", spec["key"])
        self._key = spec["key"]
        self._kind = spec["kind"]
        if spec.get("icon"):
            self._attr_icon = spec["icon"]
        # technical fields (e.g. roof phase code) → among the diagnostic details
        if spec.get("diag"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _live_value(self):
        v = self.coordinator.data.get("fields", {}).get(self._key)
        if v is None:
            return None
        if self._kind == "lock":
            return "Locked" if str(v) in ("0", "0.0") else "Unlocked"
        if self._kind == "level":
            return f"Level {v}"
        return str(v)


class OmodaJaecooBattery(_OmodaJaecooRestoreSensor):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coord) -> None:
        super().__init__(coord, "Battery", "battery")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        raw = get_rt_field(rt, "dumpEnergy")
        if raw is None:
            return None
        try:
            soc = float(raw)
        except (TypeError, ValueError):
            return None
        # dumpEnergy=0 = "high voltage off" placeholder (car parked), NOT a real
        # 0% charge: return None so the last known SOC stays (as the official app does).
        if soc <= 0:
            return None
        return soc

    @property
    def native_value(self):
        live = self._live_value()
        if live is not None:
            return live
        # don't re-serve a stale "0%" saved before the placeholder fix: 0 is not a
        # valid last-known-value for the battery → better "unknown" until a real
        # reading arrives (first trip/charge or the "Refresh full state" button).
        if self._restored in (0, 0.0, "0", "0.0"):
            return None
        return self._restored


class OmodaJaecooSpeed(_OmodaJaecooRestoreSensor):
    # device_class SPEED lets HA convert to the user's unit system (mph) and enables the
    # per-entity "unit of measurement" override — without it the unit is fixed at km/h.
    _attr_device_class = SensorDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Speed", "speed")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        v = get_rt_field(rt, "vehicleSpeed")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None


class OmodaJaecooRealtimeSensor(_OmodaJaecooRestoreSensor):
    """Generic sensor on a realtime channel field (see `_RT_SENSORS`).

    Same pattern as `OmodaJaecooBattery`/`OmodaJaecooSpeed` but parametric: device_class,
    unit and state_class come from the spec. `numeric=True` converts to float (None
    if not parsable → the RestoreSensor's last known value surfaces); `numeric=False`
    keeps the raw value (charge state codes to be decoded)."""

    def __init__(self, coord, spec: _RtSpec) -> None:
        super().__init__(coord, f"Omoda / Jaecoo {spec.name}", f"rt_{spec.suffix}")
        self._spec = spec
        if spec.device_class:
            self._attr_device_class = spec.device_class
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit
        if spec.state_class:
            self._attr_state_class = spec.state_class
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.precision is not None:
            self._attr_suggested_display_precision = spec.precision
        if spec.diag:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """PHEV/BEV universality: a realtime field that THIS car never sends (e.g.
        gasoline range on a BEV, or an EV-only field on a PHEV) must not stay
        "unknown" forever. It's available only if it has a live or restored value;
        fields absent for the powertrain come out as «unavailable» (the card
        hides them) instead of cluttering the UI with empty sensors."""
        return self._live_value() is not None or self._restored is not None

    def _live_value(self):
        # field COMPUTED from several realtime fields (e.g. total range = electric + gasoline)
        if self._spec.compute is not None:
            rt = self.coordinator.data.get("realtime") or {}
            val = self._spec.compute(rt)
            return None if (val is None or val in self._spec.invalid) else val
        raw = _rt(self.coordinator, self._spec.field)
        if raw is None:
            return None
        if self._spec.vmap is not None:
            key = raw[:-2] if raw.endswith(".0") else raw  # "0.0" → "0"
            return self._spec.vmap.get(key, f"Unknown ({raw})")
        if not self._spec.numeric:
            return raw
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        # "no reading" placeholder (e.g. HV off) → None ⇒ the last known value stays
        if val in self._spec.invalid:
            return None
        return val * self._spec.scale if self._spec.scale is not None else val


class OmodaJaecooSessionStatus(_OmodaJaecooRestoreSensor):
    _attr_icon = "mdi:key-chain"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Diagnostic Session Status", "session_detail")

    def _live_value(self):
        return self.coordinator.data.get("session_detail") or None


class OmodaJaecooTextSensor(_OmodaJaecooRestoreSensor):
    """Diagnostic text sensor (result of the last command/wake-up/probe)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str,
                 object_id: str | None = None) -> None:
        super().__init__(coord, name, suffix, object_id=object_id)
        self._data_key = data_key
        self._attr_icon = icon

    def _live_value(self):
        return self.coordinator.data.get(self._data_key) or None

    @property
    def native_value(self):
        # [H9] the diagnostic results (command/wake-up/probe) are NOT restored: an
        # old result after a restart would be misleading (it would look like the last action
        # just executed). Only the live value; if absent → unknown.
        return self._live_value()


class OmodaJaecooTimestampSensor(_OmodaJaecooRestoreSensor):
    """Diagnostic timestamp (last contact/wake-up/position)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str) -> None:
        super().__init__(coord, name, suffix)
        self._data_key = data_key
        self._attr_icon = icon

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # [H10] device_class TIMESTAMP requires a tz-aware datetime: validate the
        # restored value (ISO string → parse), otherwise None, to avoid emitting the
        # HA "Invalid datetime" warning and showing a malformed timestamp.
        r = self._restored
        if isinstance(r, str):
            r = dt_util.parse_datetime(r)
        if not (isinstance(r, datetime) and r.tzinfo is not None):
            r = None
        self._restored = r

    def _live_value(self):
        return self.coordinator.data.get(self._data_key)
