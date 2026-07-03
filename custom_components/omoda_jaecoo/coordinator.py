"""Omoda / Jaecoo coordinator — natively replaces ha_bridge.py (car MQTT + probe).

Receives the car's 5A02 events via MQTT (mutual-TLS, paho in a thread), parses them
(exact same mapping as the bridge: see SENSORS) and keeps the current state in
`self.data`. The native entities read from here. Commands/wake/probe/session are
delegated to the "protocol core" in `core/` (run in an executor).

NB: the `core/` modules read their config from env at import-time → we set os.environ
FROM the entry before importing them (assumption: one car per HA instance).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import ssl
import threading
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CAR_SEED, DEFAULT_AWAKE_WINDOW, DEFAULT_SESSION_EVERY, CERT_FILES,
    CONF_VIN, CONF_TUSERID, CONF_PIN, CONF_EMAIL, CONF_CERTS_SRC,
    CONF_BFF, CONF_TSP_HOST, CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, CONF_CHANNEL_ID,
    CONF_POLL_NORMAL, CONF_POLL_CHARGING, DEFAULT_POLL_NORMAL_MIN,
    DEFAULT_POLL_CHARGING_MIN, POLL_WAKE_WAIT, COMMAND_LOCK_S,
    HV_ON_POLL_EVERY, HV_ON_POLL_MAX,
    CHARGING_POLL_EVERY, CHARGING_POLL_MAX, DRIVE_WATCH_EVERY,
    CONF_VEHICLE_NAME, DATA_VEHICLE_MODEL, DATA_VEHICLE_BRAND,
    DEFAULTS,
)

# Minimal certs for mutual-TLS MQTT (the server .cer isn't needed for tls_set, as in the bridge).
REQUIRED_CERTS = ("ca.pem", "client.pem", "client.key")

_LOGGER = logging.getLogger(__name__)


def _derive_brand(text: str | None) -> str:
    """Brand from the vehicle name/model (e.g. fullName 'JAECOO 7' → 'Jaecoo')."""
    t = (text or "").upper()
    if "JAECOO" in t:
        return "Jaecoo"
    if "OMODA" in t:
        return "Omoda"
    return "Chery"


# Car-field → entity map (identical to the bridge: ha_bridge.py SENSORS).
# kind: open|onoff → binary_sensor ON if != 0 ; lock → 0=Locked/1=Unlocked ; level → sensor 0-3
SENSORS = [
    {"key": "frontLeftDoor",  "name": "Door Front Left",  "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "frontRightDoor", "name": "Door Front Right",  "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "backLeftDoor",   "name": "Door Rear Left", "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "backRightDoor",  "name": "Door Rear Right", "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "trunkDoor",      "name": "Door Trunk",               "comp": "binary_sensor", "dclass": "opening","kind": "open"},
    {"key": "hood",           "name": "Door Hood",              "comp": "binary_sensor", "dclass": "opening","kind": "open"},
    {"key": "liftgateOperateState", "name": "Door Tailgate Moving", "comp": "binary_sensor", "dclass": "moving", "kind": "onoff"},
    {"key": "doorLock",       "name": "Lock",           "comp": "sensor",        "dclass": None,     "kind": "lock"},
    {"key": "frontLeftWindowState",  "name": "Window Front Left",  "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "frontRightWindowState", "name": "Window Front Right",  "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "backLeftWindowState",   "name": "Window Rear Left", "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "backRightWindowState",  "name": "Window Rear Right", "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "sunroofState",   "name": "Window Sunroof",      "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "sunshadeState",  "name": "Window Sunshade",       "comp": "binary_sensor", "dclass": "window", "kind": "open", "diag": True},
    {"key": "frontHVACState", "name": "Climate",               "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "airPurification","name": "Climate Air Purification",  "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "frontWindshieldHeat", "name": "Climate Windshield Defrost", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "fWinHeatingState","name": "Climate Windshield Heating", "comp": "binary_sensor", "dclass": "running", "kind": "onoff", "diag": True},
    {"key": "rWinHeatingState","name": "Climate Rear Window Defrost",    "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "steerWheelHeating","name": "Climate Steering Wheel Heating",   "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "dSeatHeatingState","name": "Seat Driver Heating",     "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "pSeatHeatingState","name": "Seat Passenger Heating","comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "dSeatVentilateState","name": "Seat Driver Ventilation",      "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "pSeatVentilateState","name": "Seat Passenger Ventilation", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "lSeatHeatingState2","name": "Seat Rear Left Heating",      "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "rSeatHeatingState2","name": "Seat Rear Right Heating",      "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "mSeatHeatingState2","name": "Seat Rear Center Heating","comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "lSeatVentilateState2","name": "Seat Rear Left Ventilation",       "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    {"key": "rSeatVentilateState2","name": "Seat Rear Right Ventilation",       "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    {"key": "mSeatVentilateState2","name": "Seat Rear Center Ventilation", "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    # — additional telemetry (fields already sent by the car in the 5A02) —
    {"key": "chargeGunState", "name": "Charge Plug",  "comp": "binary_sensor", "dclass": "plug",    "kind": "onoff"},
    {"key": "engineState",    "name": "Engine",          "comp": "binary_sensor", "dclass": "running", "kind": "onoff", "icon": "mdi:engine"},
    # sunroofMoveState = sunroof movement PHASE code (values 1/2/3/4/8, never 0):
    # not a clean on/off (there's no known "stopped" value) → raw diagnostic sensor.
    {"key": "sunroofMoveState", "name": "Window Sunroof Motion State", "comp": "sensor", "dclass": None, "kind": "value", "icon": "mdi:car-select", "diag": True},
]
# NB fields deliberately NOT mapped (verified on real events.jsonl, 2026-06-21):
#   rangeUnit / averageFuelUnit / tirePressureUnit are ALWAYS "1" = they are unit-of-measure
#   FLAGS, NOT the value. The car doesn't send the real range/consumption/tire-pressure
#   value on this channel → mapping them would show a fixed "1". Deferred:
#   the other channel is needed (realtime /asr/manager or nested TPMS structure) → Round B.
META = {s["key"]: s for s in SENSORS}

# Meta-fields of command CONFIRMATION pushes (110x/1105/1135…): they are NOT vehicle
# state telemetry → they must not go into "fields" (see _on_car_message / Item 4).
CMD_CONFIRM_META = ("result", "resultTime", "seq", "reason", "hasAsy")

# [MED] "geo" fields allowed in self.position (1301 push / realtime probe). We keep
# ONLY the geolocation: battery/speed/online live in self.data["realtime"].
GEO_KEYS = ("lat", "lon", "latitude", "longitude", "speed", "vehicleSpeed",
            "direction", "heading", "altitude", "gpsTime", "positionTime")


class OmodaJaecooCoordinator(DataUpdateCoordinator):
    """Holds the MQTT connection to the car and the state; exposes actions via core/."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        cfg = {**DEFAULTS, **dict(entry.data)}
        self.vin = cfg[CONF_VIN]
        self.tuserid = cfg[CONF_TUSERID]
        self.channel_id = str(cfg.get(CONF_CHANNEL_ID, "1"))
        self.car_host = cfg[CONF_CAR_MQTT_HOST]
        self.car_port = int(cfg[CONF_CAR_MQTT_PORT])
        self.awake_window = DEFAULT_AWAKE_WINDOW
        # per-entry storage (token + certs) in HA's config dir
        self.token_path = hass.config.path(f"omoda9_{self.vin}_token.json")
        self.certs_dir = hass.config.path(f"{DOMAIN}_{self.vin}_certs")
        self.certs_src = cfg.get(CONF_CERTS_SRC) or ""
        self.tsp_host = cfg[CONF_TSP_HOST]
        self.pin = cfg.get(CONF_PIN, "")
        self.bff = cfg[CONF_BFF]
        self.email = cfg.get(CONF_EMAIL, "")

        # vehicle identity for the HA device. Priority: manual override (options) →
        # value saved in entry.data (config flow / backfill) → None (→ fallback in entity.py).
        opt = entry.options or {}
        override = str(opt.get(CONF_VEHICLE_NAME) or "").strip()
        self.vehicle_name = override or cfg.get(CONF_VEHICLE_NAME) or None
        self.vehicle_model = cfg.get(DATA_VEHICLE_MODEL) or None
        self.vehicle_brand = cfg.get(DATA_VEHICLE_BRAND) or None

        # env for the core/ modules (we'll import them AFTER setting the environment).
        # [H1] DIRECT assignment (not setdefault): with multiple entries/reloads in the same
        # process, setdefault would keep the FIRST entry's values → stale config.
        os.environ["VIN"] = self.vin
        os.environ["TUSERID"] = self.tuserid
        os.environ["CHANNEL_ID"] = self.channel_id
        os.environ["OMODA_TOKEN_PATH"] = self.token_path
        os.environ["OMODA_BFF"] = self.bff
        os.environ["TSP_HOST"] = self.tsp_host
        os.environ["OMODA_LANGUAGE"] = os.environ.get("OMODA_LANGUAGE", "it-IT")
        os.environ["OMODA_DEPT_ID"] = os.environ.get("OMODA_DEPT_ID", "39")
        if self.pin:
            os.environ["OMODA_PIN"] = self.pin
        if self.email:
            os.environ["OMODA_EMAIL"] = self.email

        self._car = None  # paho mqtt.Client (imported in _connect_car, executor)
        self._keepalive_unsub = None  # cancels the session keep-alive timer
        # periodic telemetry poll (wake+read). Intervals in MINUTES from the options
        # (0 = off): at rest `poll_normal_min`, at the charger `poll_charging_min`.
        opt = entry.options or {}
        self.poll_normal_min = int(opt.get(CONF_POLL_NORMAL, DEFAULT_POLL_NORMAL_MIN))
        self.poll_charging_min = int(opt.get(CONF_POLL_CHARGING, DEFAULT_POLL_CHARGING_MIN))
        self._poll_unsub = None       # cancels the poll timer (async_call_later)
        self._poll_busy = False       # avoids overlap between cycles
        # "high voltage on" follow-up: when HV is on (driving/charging) the realtime
        # telemetry is TRUE → we re-read in bursts to capture odometer/SOC as they climb, then
        # stop on our own when it turns off. Zero commands to the car (see HV_ON_POLL_* in const).
        self._hv_poll_unsub = None    # self-rescheduling timer of the HV follow-up
        self._hv_poll_count = 0       # close-together reads done in the HV-on window (cap HV_ON_POLL_MAX)
        self._startup_probe_unsub = None  # one-shot: seeds the follow-up right after startup
        # drive-detection heartbeat (read-only): starts the automatic refresh during a
        # trip, since the moving car does NOT send MQTT pushes. See DRIVE_WATCH_EVERY.
        self._drive_watch_unsub = None
        # "Automatic update" switch: OFF by default — the poll wakes the car, so it only
        # starts if the user explicitly turns it on. The user's choice is then
        # remembered across restarts (RestoreEntity switch).
        self.poll_enabled = False
        self._cmd_busy_until = 0.0     # anti-double-tap: monotonic up to which a command is "in flight"
        self._fields: dict[str, str] = {}
        self._state_lock = threading.Lock()  # [H2] serializes _fields/position across paho/executor/loop threads
        self._last_msg_ts: float = 0.0
        self.position: dict | None = None
        self.otp_code: str = ""   # set by the «OTP Code» text entity, read by confirm
        self.data = {"fields": {}, "position": None,
                     "awake": False, "car_connected": False,
                     "session_ok": None, "session_detail": "",
                     # — diagnostic sensors (parity with the bridge) —
                     "cmd_status": None, "wake_status": None, "probe_status": None,
                     "last_seen": None, "last_wake": None, "last_pos_fix": None,
                     "realtime": None}

    # ───────────────── mutual-TLS certificate provisioning (PHASE 3c) ─────────────────
    async def async_provision_certs(self) -> tuple[bool, str]:
        """Ensures the mutual-TLS certs in the per-entry certs_dir. Returns (ok, detail).

        Strategy (from-scratch cert provisioning is not yet automatable —
        the 4 certs come from the app's device registration, not reproducible here):
          1) if the 3 required certs are ALREADY in certs_dir → ok;
          2) otherwise, if `certs_src` (a folder inside HA's filesystem) contains
             them → copy them into certs_dir;
          3) otherwise → (False) with instructions on where to put them manually.
        """
        return await self.hass.async_add_executor_job(self._provision_certs)

    def _provision_certs(self) -> tuple[bool, str]:
        os.makedirs(self.certs_dir, mode=0o700, exist_ok=True)

        def _have_required() -> bool:
            return all(os.path.isfile(os.path.join(self.certs_dir, f)) for f in REQUIRED_CERTS)

        if _have_required():
            return True, "certs present"

        # 1) manual override: folder specified in certs_src
        if self.certs_src and os.path.isdir(self.certs_src):
            copied = []
            for f in CERT_FILES:
                src = os.path.join(self.certs_src, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(self.certs_dir, f))
                    os.chmod(os.path.join(self.certs_dir, f), 0o600)
                    copied.append(f)
            if _have_required():
                return True, f"certs imported from {self.certs_src}: {', '.join(copied)}"

        # 2) auto-provisioning from the bundled universal per-region certs (see cert_bundle)
        try:
            from .cert_bundle import decrypt_region
            certs = decrypt_region(self.car_host)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[certs] bundle not available for %s: %s", self.car_host, err)
            certs = None
        if certs:
            try:
                for name, data in certs.items():
                    p = os.path.join(self.certs_dir, name)
                    with open(p, "wb") as fh:
                        fh.write(data)
                    os.chmod(p, 0o600)
            except OSError as err:
                return False, f"writing certs from the bundle failed in {self.certs_dir}: {err}"
            if _have_required():
                return True, f"certs auto-provisioned ({self.car_host})"

        return False, (f"mutual-TLS certs missing for {self.car_host}: region not in the bundle. "
                       f"Copy {', '.join(REQUIRED_CERTS)} into {self.certs_dir} "
                       f"(or specify a folder in certs_src).")

    # ───────────────── car MQTT lifecycle ─────────────────
    async def async_start(self) -> None:
        """Starts the MQTT connection to the car (paho runs in its own thread)."""
        await self.hass.async_add_executor_job(self._connect_car)

    # ───────────────── session keep-alive (periodic token refresh) ─────────────────
    def async_start_keepalive(self) -> None:
        """Schedules a periodic session refresh so the token doesn't expire.

        `_bff_login` renews the access_token itself with the refresh_token when it
        expires (without OTP) → rechecking the session every `DEFAULT_SESSION_EVERY`
        keeps the session alive even at rest (rotating the refresh_token before its
        window closes) and avoids a surprise re-OTP due to inactivity. As a
        bonus it updates the session entities. It does not protect against opening the
        official app (single session on the cloud side → OTP is still required)."""
        if self._keepalive_unsub is not None:
            return
        self._keepalive_unsub = async_track_time_interval(
            self.hass, self._keepalive, timedelta(seconds=DEFAULT_SESSION_EVERY)
        )

    async def _keepalive(self, _now) -> None:
        try:
            ok, detail = await self.async_check_session()
            _LOGGER.debug("[keepalive] session %s — %s", "ok" if ok else "KO", detail)
        except Exception as err:  # noqa: BLE001 — a network error must not stop the timer
            _LOGGER.debug("[keepalive] non-blocking error: %s", err)

    # ───────────────── periodic telemetry poll (wake + read) ─────────────────
    def async_start_telemetry_poll(self) -> None:
        """Starts the periodic poll if at least one interval is active (>0).

        Self-rescheduling timer (`async_call_later`): the interval is DYNAMIC — shorter
        when the car is plugged into the charger (`poll_charging_min`), otherwise
        `poll_normal_min`. Each cycle WAKES the car (vehicleLocation = position) and
        forces a realtime read (telemetry)."""
        if not self.poll_enabled:
            _LOGGER.debug("[poll] disabled by the switch")
            return
        if self.poll_normal_min <= 0 and self.poll_charging_min <= 0:
            _LOGGER.debug("[poll] disabled (both intervals at 0)")
            return
        if self._poll_unsub is None:
            self._schedule_next_poll()
        # Initial SEED: a realtime read ~15s after startup (giving MQTT time to
        # connect). If the car is charging/driving (HV on) the close 2-min follow-up
        # starts IMMEDIATELY, without waiting for the first periodic poll (up to 30 min) — the car
        # at rest does NOT send MQTT, so without this seed the sensors would stay
        # frozen after a restart while charging until the poll fired. Read-only: no command to the car. One-shot.
        if self._startup_probe_unsub is None:
            self._startup_probe_unsub = async_call_later(self.hass, 15, self._startup_probe_cb)

    async def _startup_probe_cb(self, _now) -> None:
        self._startup_probe_unsub = None
        try:
            await self.async_probe(force=True)
        except Exception as err:  # noqa: BLE001 — the seed must not make startup fail
            _LOGGER.debug("[poll] initial probe (seed) failed: %s", err)

    @callback
    def set_poll_enabled(self, on: bool) -> None:
        """Enables/disables the periodic poll at runtime ("Automatic update" switch)."""
        self.poll_enabled = on
        if on:
            self.async_start_telemetry_poll()
            self.async_start_drive_watch()
        else:
            if self._poll_unsub is not None:
                self._poll_unsub()
                self._poll_unsub = None
            if self._drive_watch_unsub is not None:
                self._drive_watch_unsub()
                self._drive_watch_unsub = None

    def async_start_drive_watch(self) -> None:
        """Starts the drive-detection heartbeat (read-only). It's tied to `poll_enabled`
        ("Automatic update" switch): every `DRIVE_WATCH_EVERY` it checks whether HV is
        on and, if so, starts the close follow-up. Idempotent."""
        if self._drive_watch_unsub is not None or not self.poll_enabled:
            return
        self._drive_watch_unsub = async_track_time_interval(
            self.hass, self._drive_watch_cb, timedelta(seconds=DRIVE_WATCH_EVERY)
        )

    async def _drive_watch_cb(self, _now) -> None:
        """A READ-ONLY realtime read to notice that the car is driving (the moving car
        does not send MQTT pushes). If the close follow-up is already running (driving/charging)
        or a poll cycle is running, skip: no overlap. If it finds HV on, `async_probe`
        arms the 60s loop itself that will follow the whole trip. NO command/wake to the car."""
        if not self.poll_enabled or self._hv_poll_unsub is not None or self._poll_busy:
            return
        self._poll_busy = True
        try:
            await self.async_probe(force=True)
        except Exception as err:  # noqa: BLE001 — a network error must not stop the timer
            _LOGGER.debug("[drive-watch] read failed: %s", err)
        finally:
            self._poll_busy = False

    def _is_plugged(self) -> bool:
        """True if the charging plug is connected (chargeGunState != 0). Reads the
        freshest value: realtime if present, otherwise the last 5A02 via MQTT."""
        from .entity import field_on
        rt = self.data.get("realtime") or {}
        v = rt.get("chargeGunState")
        if v is None:
            with self._state_lock:
                v = self._fields.get("chargeGunState")
        return bool(field_on(v))

    def _schedule_next_poll(self) -> None:
        """Reschedules the next poll based on the current plug state. If the current
        state has interval 0 (disabled mode) it does NOT wake, but rechecks later
        (to notice when the charger connection changes)."""
        mins = self.poll_charging_min if self._is_plugged() else self.poll_normal_min
        if not mins or mins <= 0:
            # current state off → recheck with the other interval (or 60 min) without waking
            mins = self.poll_charging_min or self.poll_normal_min or 60
        self._poll_unsub = async_call_later(self.hass, mins * 60, self._telemetry_poll_cb)

    async def _telemetry_poll_cb(self, _now) -> None:
        self._poll_unsub = None
        try:
            mins = self.poll_charging_min if self._is_plugged() else self.poll_normal_min
            if mins and mins > 0 and not self._poll_busy:
                self._poll_busy = True
                try:
                    await self._do_poll_cycle()
                finally:
                    self._poll_busy = False
        except Exception as err:  # noqa: BLE001 — an error must not stop the timer
            _LOGGER.debug("[poll] non-blocking error: %s", err)
        finally:
            # reschedule ONLY if the poll is still active: if set_poll_enabled(False)
            # arrived during the cycle (await), it found _poll_unsub=None and couldn't
            # cancel anything → without this guard we'd re-arm a "zombie" timer.
            if self.poll_enabled:
                self._schedule_next_poll()

    async def _do_poll_cycle(self) -> None:
        """One cycle: wake (position via vehicleLocation/1301) + realtime read."""
        _LOGGER.debug("[poll] cycle: wake + realtime read (plugged=%s)", self._is_plugged())
        try:
            await self.async_send_command("locate_car")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[poll] wake (locate_car) failed: %s", err)
        await asyncio.sleep(POLL_WAKE_WAIT)
        try:
            await self.async_probe(force=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[poll] realtime read failed: %s", err)

    def _connect_car(self) -> None:
        self._bind_core()
        # import here (executor): at module level it causes a blocking-call warning in the loop.
        import paho.mqtt.client as mqtt

        seed = os.environ.get("CAR_SEED", CAR_SEED)
        car_user = self.tuserid
        car_pass = hashlib.md5((self.tuserid + seed).encode()).hexdigest()
        client_id = f"app_{self.channel_id}_{self.tuserid}"   # exact: the broker's ACL
        topic = f"app/{self.channel_id}/{self.tuserid}/account/msgCenter/msg"

        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=client_id, protocol=mqtt.MQTTv311, clean_session=False)
        c.username_pw_set(car_user, car_pass)
        c.tls_set(ca_certs=os.path.join(self.certs_dir, "ca.pem"),
                  certfile=os.path.join(self.certs_dir, "client.pem"),
                  keyfile=os.path.join(self.certs_dir, "client.key"),
                  cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        c.tls_insecure_set(True)  # the broker uses a non-matching CN (as in the bridge)

        def on_connect(cl, u, flags, rc, props=None):
            ok = (rc == 0) or (getattr(rc, "value", 1) == 0)
            self._update({"car_connected": ok})
            _LOGGER.info("[car] MQTT on_connect rc=%s → %s (sub %s)",
                         rc, "connected" if ok else "REFUSED", topic if ok else "-")
            if ok:
                cl.subscribe(topic, qos=1)

        def on_disconnect(cl, u, *a):
            self._update({"car_connected": False})
            _LOGGER.info("[car] MQTT disconnected")

        c.on_connect = on_connect
        c.on_disconnect = on_disconnect
        c.on_message = self._on_car_message
        # [H4] reconnection backoff (avoids the default 1s storming when the network is down)
        c.reconnect_delay_set(min_delay=1, max_delay=120)
        # [H4] the initial connect can fail (DNS/cert/network) → ConfigEntryNotReady,
        #      so HA retries the setup instead of leaving the client hanging.
        try:
            c.connect(self.car_host, self.car_port, keepalive=60)
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(
                f"car MQTT connection failed ({self.car_host}:{self.car_port}): {err}"
            ) from err
        c.loop_start()
        self._car = c

    def async_stop(self) -> None:
        """[MED] MQTT shutdown. Blocking (loop_stop joins the paho thread) →
        called in an executor by async_unload_entry. `disconnect()` BEFORE
        `loop_stop()`: this way the loop processes the CONNACK/DISCONNECT and the thread exits
        cleanly without a join that waits for the keepalive."""
        if self._keepalive_unsub is not None:
            self._keepalive_unsub()
            self._keepalive_unsub = None
        if self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None
        if self._hv_poll_unsub is not None:
            self._hv_poll_unsub()
            self._hv_poll_unsub = None
        if self._startup_probe_unsub is not None:
            self._startup_probe_unsub()
            self._startup_probe_unsub = None
        if self._drive_watch_unsub is not None:
            self._drive_watch_unsub()
            self._drive_watch_unsub = None
        if self._car is not None:
            try:
                self._car.disconnect()
                self._car.loop_stop()
            except Exception as err:  # noqa: BLE001 — the stop must not make the unload fail
                _LOGGER.debug("[car] error in async_stop: %s", err)
            self._car = None

    def _on_car_message(self, c, u, msg) -> None:
        """Parsing identical to ha_bridge.car_on_message (paho thread → push to HA)."""
        try:
            obj = json.loads(msg.payload.decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[car] undecodable MQTT payload: %s", err)
            return
        content = obj.get("content", obj)
        data = content.get("data", {}) if isinstance(content, dict) else {}
        if not isinstance(data, dict):
            data = {}
        svc = str(content.get("serviceType")) if isinstance(content, dict) else ""
        now = time.time()
        now_dt = dt_util.utcnow()
        _LOGGER.debug("[car] message received (svc %s): %d fields", svc or "?", len(data))

        patch = {"last_seen": now_dt}

        # [MED] serviceType 1301 = POSITION push (lat/lon) → device_tracker. We
        # discriminate on the message TYPE (not just the presence of lat/lon) and
        # keep ONLY the geolocation in position (no **data).
        if svc == "1301" and "lat" in data and "lon" in data:
            geo = {k: data[k] for k in GEO_KEYS if k in data}
            with self._state_lock:
                self.position = geo
                pos_copy = dict(geo)
            patch["position"] = pos_copy
            patch["last_pos_fix"] = now_dt

        # [Item4] command CONFIRMATION push: the car replies to every vehicleControl/X with a
        # 110x/1105/1135 message that carries result/resultTime/seq (+ reason on failures)
        # BESIDES the real state fields. We recognize it by the presence of result/seq ("pure"
        # 5A02 telemetry doesn't have them). The state fields still go into fields;
        # the meta-fields (CMD_CONFIRM_META) do NOT (they're not vehicle state).
        is_confirmation = "result" in data or "seq" in data

        # [H2] _fields/_last_msg_ts also touched by the executor → under lock; emit a COPY
        with self._state_lock:
            was_awake = bool(self._last_msg_ts) and (now - self._last_msg_ts) < self.awake_window
            self._last_msg_ts = now
            for k, v in data.items():
                if k != "time" and k not in CMD_CONFIRM_META:
                    self._fields[k] = str(v)
            fields_copy = dict(self._fields)

        patch.update({"fields": fields_copy, "awake": True})
        if is_confirmation:
            patch["cmd_status"] = self._format_cmd_result(data)
            self.clear_command_busy()  # command resolved → immediately unblock the next one (anti-double-tap)
        self._update(patch)

        # [H3] wake-up edge → one realtime probe (read-only). Scheduling the
        # task MUST happen on the loop: from the paho thread use call_soon_threadsafe.
        if not was_awake:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_probe())
            )

        # [HV] the car is DRIVING (engine on) → high voltage is ON and the realtime has the
        # TRUE values (odometer/SOC climbing). We force a realtime read (bypasses the
        # probe's cooldown) which in turn starts the close follow-up while HV stays
        # on. Only if there isn't already a follow-up running, so reads don't overlap.
        driving = False
        try:
            driving = int(float(fields_copy.get("engineState", 0))) == 1
        except (TypeError, ValueError):
            driving = False
        # [Charging] plug connected → charge in progress: start the close follow-up here too,
        # so the automatic refresh starts as soon as the charger is plugged in (without waiting for
        # the 39-min periodic poll) and follows the progress. `field_on` as in _is_plugged().
        from .entity import field_on
        plugged = field_on(fields_copy.get("chargeGunState"))
        if (driving or plugged) and self._hv_poll_unsub is None and not is_confirmation:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_probe(force=True))
            )

    @staticmethod
    def _format_cmd_result(data: dict) -> str:
        """Translates the REAL outcome of a command confirmation push into a phrase for the user.

        Distinct from the backend's "accepted" (A00079, shown at send time): here it's what
        the CAR reports after trying to execute. CONSERVATIVE interpretation, based on
        the real data (events.jsonl 2026-06-21) and the meaning of the bean:
          - `reason` (list) is populated ONLY on failures → if present = NOT successful;
          - `result`: 5 = async operation still in progress (always with hasAsy=1);
            1/2 = executed/applied (vehicle state updated);
          - other codes → reported raw, without inventing their meaning."""
        result = str(data.get("result", "")).strip()
        reason = data.get("reason")
        if reason:  # list of failure reasons reported by the car
            return f"The car reported a problem ❌ ({reason})"[:255]
        if result == "5":
            return "Command running on the car… ⏳"
        if result in ("1", "2"):
            return "Command executed and confirmed by the car ✅"
        return f"Confirmation received from the car (outcome code {result or '?'})"[:255]

    def _update(self, patch: dict) -> None:
        """Updates self.data and notifies the entities (thread-safe from the paho thread)."""
        self.hass.loop.call_soon_threadsafe(self._apply_update, patch)

    def _apply_update(self, patch: dict) -> None:
        self.data = {**self.data, **patch}
        self.async_set_updated_data(self.data)

    # ───────────────── bind config → core/ modules ─────────────────
    def _bind_core(self) -> None:
        """Injects THIS entry's config into the globals of the core/ modules.

        The core/ modules read VIN/PIN/token-path/TSP from env AT IMPORT-TIME: if the
        config flow already imported them (with an unknown VIN), or if ANOTHER entry
        imported first, their globals would stay stale in the same process.
        [H1] Here we force them ALL to THIS entry's values → robust with respect to
        import order and multiple entries/reloads. Idempotent, in an executor."""
        import wake, commands, probe, session
        import omoda_auth as A
        # env for the modules that re-read it at runtime (wake._token_path, omoda.py, …)
        os.environ["OMODA_TOKEN_PATH"] = self.token_path
        os.environ["VIN"] = self.vin
        os.environ["TUSERID"] = self.tuserid
        os.environ["CHANNEL_ID"] = self.channel_id
        # per-account globals of the core/ modules
        wake.VIN = self.vin
        wake.TSP_HOST = self.tsp_host
        wake.TOKEN_PATH = self.token_path
        commands.VIN = self.vin
        commands.PIN = self.pin
        commands.TSP_HOST = self.tsp_host
        # MINT_TASKID from the environment value (default 1 = the buttons mint their own
        # taskId, fix S26) — re-evaluated here so it doesn't stay stale across entries/reloads.
        commands.MINT_TASKID = os.environ.get("OMODA_MINT_TASKID", "1") not in ("0", "", "false", "no")
        # taskId file in the per-VIN config dir (survives HACS updates, no shared stale)
        commands.TASKID_FILE = self.hass.config.path(f"{DOMAIN}_{self.vin}_taskid.txt")
        probe.VIN = self.vin
        session.EMAIL = self.email
        A.BFF = self.bff
        A.CHANNEL_ID = self.channel_id
        A.COUNTRY_ID = os.environ.get("OMODA_COUNTRY_ID", A.COUNTRY_ID)

    # ───────────────── anti-double-tap (one command at a time) ─────────────────
    @callback
    def command_busy(self) -> bool:
        """True if an actuating command is still "in flight" (recently sent, confirmation
        not yet arrived). The car executes one at a time → blocks double-taps."""
        return time.monotonic() < self._cmd_busy_until

    @callback
    def mark_command_sent(self) -> None:
        self._cmd_busy_until = time.monotonic() + COMMAND_LOCK_S

    @callback
    def clear_command_busy(self) -> None:
        self._cmd_busy_until = 0.0

    # ───────────────── actions (delegated to core/, in an executor) ─────────────────
    async def async_send_command(self, key: str, params: dict | None = None) -> str:
        return await self.hass.async_add_executor_job(self._send_command, key, params)

    def _send_command(self, key: str, params: dict | None = None) -> str:
        self._bind_core()
        self.mark_command_sent()  # also covers poll/wake (locate) that don't go through the mixin
        import commands as CMD  # core/ is on the path (see __init__)
        msgs: list[str] = []

        def emit(m):
            msgs.append(str(m))
            _LOGGER.info("[cmd] %s", m)
            self._update({"cmd_status": str(m)[:255]})

        CMD.send(key, emit=emit, params=params)
        return msgs[-1] if msgs else "sent"

    async def async_query_theft(self) -> int | None:
        """Anti-theft state via REST (read-only); None if not available."""
        return await self.hass.async_add_executor_job(self._query_theft)

    def _query_theft(self) -> int | None:
        self._bind_core()
        import commands as CMD  # core/ is on the path (see __init__)
        return CMD.query_theft_switch()

    async def async_wake(self) -> None:
        await self.hass.async_add_executor_job(self._wake)

    def _wake(self) -> None:
        self._bind_core()
        import wake as WAKE

        def emit(m):
            _LOGGER.info("[wake] %s", m)
            self._update({"wake_status": str(m)[:255]})

        self._update({"last_wake": dt_util.utcnow()})
        # is_awake: if the car is already publishing on MQTT the SMS isn't needed.
        result = WAKE.do_wake(emit, is_awake=lambda: bool(self.data.get("awake")), send_sms=True)
        # [FALLBACK] smsAwaken is unreliable (test 2026-06-21: A07900 twice) → if it didn't
        # wake the car, fall back to a REAL command (vehicleLocation), which wakes it on the
        # first try and also returns the GPS. At the coordinator level to avoid circular
        # imports (wake.py is imported by commands.py).
        if not (isinstance(result, dict) and result.get("online")):
            if self.data.get("awake"):
                return  # meanwhile an MQTT message arrived → already awake
            emit("SMS wake unsuccessful → falling back to Locate (vehicleLocation)…")
            try:
                self._send_command("locate_car")
            except Exception as err:  # noqa: BLE001 — the fallback must not make the wake fail
                emit(f"Locate fallback failed: {err}")

    def _is_hv_on(self) -> bool:
        """True if high voltage is on (driving, charging or climate): it's the ONLY state in which
        /asr/manager/realtime reports REAL odometer/SOC/voltage. With HV off they are
        stale/placeholder values (old odometer, dumpEnergy=0, totalVoltage=0, totalCurrent=-1000).
        Reads the freshest realtime (probe) falling back to the last 5A02 via MQTT."""
        rt = self.data.get("realtime") or {}
        with self._state_lock:
            fields = dict(self._fields)
        for k in ("hVoltageState", "engineState"):
            v = rt.get(k)
            if v is None:
                v = fields.get(k)
            try:
                if int(float(v)) == 1:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    @callback
    def _arm_hv_followup(self) -> None:
        """After every realtime read: if there's freshness to follow, schedule another close
        read, otherwise (or once the cap is reached) stop the loop. No commands to the car: it
        just reads. Two cases that keep the loop alive:
          - **HV on** (driving/climate): follows odometer/SOC climbing, 60s interval, cap ~90 min;
          - **plug connected** (charging): follows the charge progress for HOURS, a more
            relaxed interval (`CHARGING_POLL_EVERY`) and a much higher cap (`CHARGING_POLL_MAX`).
        During a charge HV is on, so the realtime has real battery/current/time-remaining
        values: this is exactly what enables the automatic refresh while the plug is connected."""
        if self._hv_poll_unsub is not None:
            self._hv_poll_unsub()
            self._hv_poll_unsub = None
        plugged = self._is_plugged()
        # the plug takes priority: the "charging" cap/interval (longer) also covers HV on
        if plugged:
            every, cap = CHARGING_POLL_EVERY, CHARGING_POLL_MAX
        elif self._is_hv_on():
            every, cap = HV_ON_POLL_EVERY, HV_ON_POLL_MAX
        else:
            self._hv_poll_count = 0
            return
        if self._hv_poll_count < cap:
            self._hv_poll_count += 1
            self._hv_poll_unsub = async_call_later(self.hass, every, self._hv_followup_cb)
        else:
            self._hv_poll_count = 0

    async def _hv_followup_cb(self, _now) -> None:
        self._hv_poll_unsub = None
        await self.async_probe(force=True)

    async def async_probe(self, force: bool = False) -> None:
        await self.hass.async_add_executor_job(self._probe, force)
        # if the read found HV on, follow the freshness window (auto-loop)
        self._arm_hv_followup()

    def _probe(self, force: bool = False) -> None:
        self._bind_core()
        import probe as PROBE

        def emit(m):
            _LOGGER.info("[probe] %s", m)
            self._update({"probe_status": str(m)[:255]})

        # force=True (periodic poll): ignore the probe's 30-min cooldown.
        PROBE.probe_once(emit, force=force, on_data=self._on_probe_data)

    def _on_probe_data(self, data: dict) -> None:
        """Realtime data (GPS/battery/speed/online) from the probe → position state.

        Runs in the executor thread: accesses to self.position are serialized with the
        lock and a COPY is always emitted (no sharing by reference)."""
        patch: dict = {"realtime": dict(data) if isinstance(data, dict) else data}
        if isinstance(data, dict) and "lat" in data and "lon" in data:
            geo = {k: data[k] for k in GEO_KEYS if k in data}
            with self._state_lock:
                self.position = {**(self.position or {}), **geo}
                pos_copy = dict(self.position)
            patch["position"] = pos_copy
            patch["last_pos_fix"] = dt_util.utcnow()
        self._update(patch)

    async def async_refresh_full_status(self) -> None:
        """«Refresh full status» button: brings the REAL odometer/battery/voltage into HA.

        The realtime channel gives the real values ONLY with high voltage on; there is no
        "light" command that forces a fresh report (verified from reverse-engineering the
        Chery SDK). So: if HV is already on (driving/charging) it just reads; otherwise it
        turns on the climate BRIEFLY (the only way to turn high voltage on), reads the real
        data, then turns the climate off. ⚠️ ACTS on the car: the climate stays on ~1 minute."""
        def emit(m):
            _LOGGER.info("[refresh] %s", m)
            self._update({"probe_status": str(m)[:255]})

        # 1) immediate read: if HV is already on, everything is already fresh
        await self.async_probe(force=True)
        if self._is_hv_on():
            emit("Status updated — high voltage already on ✅")
            return

        # 2) turn on the climate to wake the high voltage
        emit("Turning on climate for ~1 min to read real data (odometer/battery)…")
        try:
            await self.async_send_command("clima_on")
        except Exception as err:  # noqa: BLE001
            emit(f"Failed to turn on climate: {err}")
            return

        # 3) read the realtime until high voltage is up (max ~2.5 min)
        got = False
        for _ in range(6):
            await asyncio.sleep(POLL_WAKE_WAIT)
            try:
                await self.async_probe(force=True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("[refresh] realtime read failed: %s", err)
            if self._is_hv_on():
                got = True
                break

        # 4) always turn the climate off (even on failure)
        try:
            await self.async_send_command("clima_off")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[refresh] turning off the climate failed: %s", err)
        emit("Status updated with real data ✅" if got
             else "Car did not wake in time — try again, or it will update on next drive")

    async def async_ensure_vehicle_identity(self) -> None:
        """Best-effort backfill of the vehicle identity (name/model/brand) for the HA device.

        Needed for entries created BEFORE the config flow saved it: if it's missing in entry.data
        (and there's no manual override) it reads it ONCE from queryList and persists it, so on
        subsequent restarts it's already cached (no new calls). Read-only, doesn't block the
        setup: on error the fallback "Omoda / Jaecoo / Jaecoo" remains."""
        if str((self.entry.options or {}).get(CONF_VEHICLE_NAME) or "").strip():
            return  # manual override: don't overwrite
        if self.entry.data.get(CONF_VEHICLE_NAME):
            return  # already cached
        info = await self.hass.async_add_executor_job(self._fetch_vehicle_identity)
        if not info or not info.get(CONF_VEHICLE_NAME):
            return
        self.vehicle_name = info.get(CONF_VEHICLE_NAME)
        self.vehicle_model = info.get(DATA_VEHICLE_MODEL)
        self.vehicle_brand = info.get(DATA_VEHICLE_BRAND)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **info})  # → one reload (then it's cached)

    def _fetch_vehicle_identity(self) -> dict | None:
        """queryList (read-only) → {vehicle_name, vehicle_model, vehicle_brand} for the VIN."""
        try:
            self._bind_core()
            import wake, omoda_auth as A, requests
            wake._bff_login()
            access = wake._access_token()
            headers = A.headers_post("/tsp/v1/app/vmc/queryList", extra={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json, text/plain, */*"})
            j = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList",
                              data="{}", headers=headers, timeout=20).json()
            data = j.get("data")
            cands = []
            if isinstance(data, list):
                cands = data
            elif isinstance(data, dict):
                for k in ("controlCarList", "authorizedControlCarList", "carList", "vehicles"):
                    if isinstance(data.get(k), list):
                        cands += data[k]
                if not cands and "vin" in data:
                    cands = [data]
            item = next((x for x in cands if isinstance(x, dict)
                         and str(x.get("vin")) == self.vin), None)
            if item is None and cands and isinstance(cands[0], dict):
                item = cands[0]
            if not item:
                return None
            nick = str(item.get("nickname") or "").strip()
            full = str(item.get("fullName") or "").strip()
            name = nick or (full.title() if full else "")
            if not name:
                return None
            return {CONF_VEHICLE_NAME: name,
                    DATA_VEHICLE_MODEL: (full.title() if full else None),
                    DATA_VEHICLE_BRAND: _derive_brand(full or nick)}
        except Exception as err:  # noqa: BLE001 — best-effort, must not make the setup fail
            _LOGGER.debug("[vehicle] identity not retrieved: %s", err)
            return None

    async def async_check_session(self) -> tuple[bool, str]:
        ok, detail = await self.hass.async_add_executor_job(self._check_session)
        self._update({"session_ok": ok, "session_detail": detail})
        return ok, detail

    def _check_session(self) -> tuple[bool, str]:
        self._bind_core()
        import session as SESSION
        return SESSION.check()

    # ───────────────── session recovery (OTP from HA) ─────────────────
    async def async_request_otp(self) -> str:
        """Sends the OTP code to the account's email (button «Request OTP»)."""
        return await self.hass.async_add_executor_job(self._request_otp)

    def _request_otp(self) -> str:
        self._bind_core()
        import session as SESSION
        msgs: list[str] = []
        SESSION.request_otp(emit=msgs.append)
        detail = msgs[-1] if msgs else "request sent"
        self._update({"session_detail": detail})
        return detail

    async def async_confirm_otp(self) -> tuple[bool, str]:
        """Mints the token with the entered code (button «Confirm OTP») and rechecks the session."""
        ok, detail = await self.hass.async_add_executor_job(self._confirm_otp, self.otp_code)
        self._update({"session_ok": ok, "session_detail": detail})
        return ok, detail

    def _confirm_otp(self, code: str) -> tuple[bool, str]:
        self._bind_core()
        import session as SESSION
        return SESSION.confirm_otp(code or "")
