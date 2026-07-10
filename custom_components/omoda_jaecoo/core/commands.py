#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
commands.py — Catalog + dispatch of Omoda / Jaecoo car commands (tspconsole EU REST).

Reuses the chain verified in S24:
  - userToken via  wake._bff_login()      (OTP token in token.json, automatic refresh)
  - signature      tsp_sign.sign_body()   (base64(sha256(base)).upper())
  - taskId         get_taskid()           (env TASKID -> piggyback file -> auto-minted checkPassword)

POST  https://tspconsole-eu.cheryinternational.com/asc/vehicleControl/<endpoint>
Header: Authorization=<userToken>, timestamp=<ms>, Content-Type=application/json; charset=utf-8,
        User-Agent=okhttp/4.9.2

⚠️  Every send() with a valid taskId ACTS on the car. It is meant to be invoked ONLY
    by the user tapping a button in Home Assistant (= their explicit consent).
    Body catalog reconstructed 1:1 from the real envelopes in
    /root/omoda_jaecoo_capture_20260620/command_envelopes.txt.
"""
import os
import sys
import json
import time
import hashlib
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import wake
import tsp_sign
import omoda_auth as A
import codes
# H8: removed `importlib.reload(tsp_sign)` at import-time (pointless side-effect; tsp_sign
# is not mutated elsewhere and reloading it at import could wipe out any monkeypatch).

# PER-ACCOUNT data: no default — supplied via omoda_jaecoo.env (see omoda_jaecoo.env.example).
VIN        = os.environ.get("VIN", "")
PIN        = os.environ.get("OMODA_PIN", "")
TSP_HOST   = os.environ.get("TSP_HOST", "https://tspconsole-eu.cheryinternational.com")   # region (default EU)
TASKID_FILE = os.environ.get("OMODA_TASKID_FILE", os.path.join(HERE, "data", "taskid.txt"))
MINT_TASKID = os.environ.get("OMODA_MINT_TASKID", "1") not in ("0", "", "false", "no")

# ───────────────────────── Command catalog ─────────────────────────
# Each entry: key -> {endpoint, body(specific fixed values), name, icon, group}
# The common fields (clientType/seq/taskId/vin/appId/sign) are added by send().
COMMANDS = [
    # — Climate —
    # climate ON/OFF: temperature and duration are PARAMETRIC (passed by the climate entity via
    # `params`); the values in the body are only the defaults when invoked without override.
    ("clima_on",  {"endpoint": "airControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Climate ON", "icon": "mdi:air-conditioner", "group": "Climate"}),
    ("clima_off", {"endpoint": "airControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Climate OFF", "icon": "mdi:air-conditioner", "group": "Climate"}),
    ("defrost_parabrezza", {"endpoint": "frontWindshieldControl",
                   "body": {"frontWindshieldHeat": "1", "times": "15"},
                   "name": "Windshield defrost", "icon": "mdi:car-defrost-front", "group": "Climate"}),
    ("defrost_parabrezza_off", {"endpoint": "frontWindshieldControl",
                   "body": {"frontWindshieldHeat": "0"},
                   "name": "Windshield defrost OFF", "icon": "mdi:car-defrost-front", "group": "Climate"}),
    ("defrost_lunotto", {"endpoint": "backDefrostingControl",
                   "body": {"backDefrosting": "1", "times": "15"},
                   "name": "Rear window defrost", "icon": "mdi:car-defrost-rear", "group": "Climate"}),
    ("defrost_lunotto_off", {"endpoint": "backDefrostingControl",
                   "body": {"backDefrosting": "0"},
                   "name": "Rear window defrost OFF", "icon": "mdi:car-defrost-rear", "group": "Climate"}),
    ("volante_caldo", {"endpoint": "steeringWheelControl",
                   "body": {"controlType": "1"},
                   "name": "Steering wheel heating", "icon": "mdi:steering", "group": "Climate"}),
    ("volante_caldo_off", {"endpoint": "steeringWheelControl",
                   "body": {"controlType": "0"},
                   "name": "Steering wheel heating OFF", "icon": "mdi:steering", "group": "Climate"}),
    ("sedile_guida_caldo", {"endpoint": "seatControl",
                   "body": {"mSeatHeating": "3", "times": "15"},
                   "name": "Driver seat heating", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_guida_caldo_off", {"endpoint": "seatControl",
                   "body": {"mSeatHeating": "0"},
                   "name": "Driver seat heating OFF", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_guida_aria", {"endpoint": "seatControl",
                   "body": {"mSeatAiry": "3", "times": "15"},
                   "name": "Driver seat ventilation", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_guida_aria_off", {"endpoint": "seatControl",
                   "body": {"mSeatAiry": "0"},
                   "name": "Driver seat ventilation OFF", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    # Passenger and rear seats — same single `seatControl` endpoint, parameters
    # confirmed from the CVSeatControlReqBean bean (p=passenger, bl=rear left, br=rear right).
    # Rear center: the bean has NO dedicated parameter → no command.
    ("sedile_passeggero_caldo", {"endpoint": "seatControl",
                   "body": {"pSeatHeating": "3", "times": "15"},
                   "name": "Passenger seat heating", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_passeggero_caldo_off", {"endpoint": "seatControl",
                   "body": {"pSeatHeating": "0"},
                   "name": "Passenger seat heating OFF", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_passeggero_aria", {"endpoint": "seatControl",
                   "body": {"pSeatAiry": "3", "times": "15"},
                   "name": "Passenger seat ventilation", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_passeggero_aria_off", {"endpoint": "seatControl",
                   "body": {"pSeatAiry": "0"},
                   "name": "Passenger seat ventilation OFF", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_post_sx_caldo", {"endpoint": "seatControl",
                   "body": {"blSeatHeating": "3", "times": "15"},
                   "name": "Rear left seat heating", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_post_sx_caldo_off", {"endpoint": "seatControl",
                   "body": {"blSeatHeating": "0"},
                   "name": "Rear left seat heating OFF", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_post_sx_aria", {"endpoint": "seatControl",
                   "body": {"blSeatAiry": "3", "times": "15"},
                   "name": "Rear left seat ventilation", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_post_sx_aria_off", {"endpoint": "seatControl",
                   "body": {"blSeatAiry": "0"},
                   "name": "Rear left seat ventilation OFF", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_post_dx_caldo", {"endpoint": "seatControl",
                   "body": {"brSeatHeating": "3", "times": "15"},
                   "name": "Rear right seat heating", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_post_dx_caldo_off", {"endpoint": "seatControl",
                   "body": {"brSeatHeating": "0"},
                   "name": "Rear right seat heating OFF", "icon": "mdi:car-seat-heater", "group": "Climate"}),
    ("sedile_post_dx_aria", {"endpoint": "seatControl",
                   "body": {"brSeatAiry": "3", "times": "15"},
                   "name": "Rear right seat ventilation", "icon": "mdi:car-seat-cooler", "group": "Climate"}),
    ("sedile_post_dx_aria_off", {"endpoint": "seatControl",
                   "body": {"brSeatAiry": "0"},
                   "name": "Rear right seat ventilation OFF", "icon": "mdi:car-seat-cooler", "group": "Climate"}),

    # — Climate: comfort "all" macros (coolingControl/heatingControl) —
    # Single preset that turns on climate + ALL seats (+ defrosters and steering wheel for heating)
    # in one shot. Body reconstructed 1:1 from the app's real envelopes in
    # 30_capture/omoda_jaecoo_capture_20260620/command_envelopes.txt. NB: they use `duration` (NOT
    # `times`); seat values 3=on/0=off; temperature 15.0 (max cold) / 31.0 (max hot).
    # ⚠️ IMPORTANT (verified live 2026-06-21): these commands — like ALL comfort ones —
    # are rejected by the car with a timeout if the vehicle is ON/occupied (safety
    # lockout). With the engine off they work and turn on all modules. It is not a problem
    # with the command: with the car off, climate+seats+steering wheel+windshield+rear window all respond ✅.
    ("climate_cool_on", {"endpoint": "coolingControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "15.0", "duration": "15",
                            "mSeatAiry": "3", "pSeatAiry": "3", "blSeatAiry": "3", "brSeatAiry": "3"},
                   "name": "Cool down all", "icon": "mdi:snowflake", "group": "Climate"}),
    ("climate_cool_off", {"endpoint": "coolingControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "15.0", "duration": "15",
                            "mSeatAiry": "0", "pSeatAiry": "0", "blSeatAiry": "0", "brSeatAiry": "0"},
                   "name": "Cool down all OFF", "icon": "mdi:snowflake-off", "group": "Climate"}),
    ("climate_heat_on", {"endpoint": "heatingControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "31.0", "duration": "15",
                            "frontWindshieldHeat": "1", "backDefrosting": "1", "steerWheelHeatSwitch": "1",
                            "mSeatHeating": "3", "pSeatHeating": "3", "blSeatHeating": "3", "brSeatHeating": "3"},
                   "name": "Heat up all", "icon": "mdi:heat-wave", "group": "Climate"}),
    ("climate_heat_off", {"endpoint": "heatingControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "31.0", "duration": "15",
                            "frontWindshieldHeat": "0", "backDefrosting": "0", "steerWheelHeatSwitch": "0",
                            "mSeatHeating": "0", "pSeatHeating": "0", "blSeatHeating": "0", "brSeatHeating": "0"},
                   "name": "Heat up all OFF", "icon": "mdi:heat-wave", "group": "Climate"}),

    # — Doors / locks —
    ("sblocca",   {"endpoint": "lockControl", "body": {"lockType": "1"},
                   "name": "Unlock doors", "icon": "mdi:lock-open-variant", "group": "Access"}),
    ("blocca",    {"endpoint": "lockControl", "body": {"lockType": "0"},
                   "name": "Lock doors", "icon": "mdi:lock", "group": "Access"}),
    ("baule_apri",  {"endpoint": "powerLiftgateControl", "body": {"controlType": "1"},
                   "name": "Open trunk", "icon": "mdi:car-back", "group": "Access"}),
    ("baule_chiudi", {"endpoint": "powerLiftgateControl", "body": {"controlType": "0"},
                   "name": "Close trunk", "icon": "mdi:car-back", "group": "Access"}),

    # — Windows / roof —
    ("finestrini_apri",   {"endpoint": "windowControl", "body": {"controlType": "1"},
                   "name": "Open windows", "icon": "mdi:car-door", "group": "Windows and roof"}),
    ("finestrini_chiudi", {"endpoint": "windowControl", "body": {"controlType": "0"},
                   "name": "Close windows", "icon": "mdi:car-door", "group": "Windows and roof"}),
    ("ventilate_windows", {"endpoint": "windowControl", "body": {"controlType": "2"},
                   "name": "Window Ventilate", "icon": "mdi:weather-windy", "group": "Windows and roof"}),
    ("tetto_apri",   {"endpoint": "skylightControl", "body": {"controlType": "1", "skylightType": "1"},
                   "name": "Open sunroof", "icon": "mdi:car-select", "group": "Windows and roof"}),
    ("tetto_chiudi", {"endpoint": "skylightControl", "body": {"controlType": "0", "skylightType": "1"},
                   "name": "Close sunroof", "icon": "mdi:car-select", "group": "Windows and roof"}),

    # — EV charging —
    # IMMEDIATE charging start/stop (endpoint chargeStartStopControl, bean CVChargeStartStopBean
    # → only `controlType`; 1=start, 0=stop, same convention as all the *Control ones).
    ("ricarica_start", {"endpoint": "chargeStartStopControl", "body": {"controlType": "1"},
                   "name": "Start charging", "icon": "mdi:battery-charging", "group": "Charging"}),
    ("ricarica_stop", {"endpoint": "chargeStartStopControl", "body": {"controlType": "0"},
                   "name": "Stop charging", "icon": "mdi:battery-off", "group": "Charging"}),
    # SCHEDULED charging (chargeAppointControl) — body with nested ARRAY `chargeAppointPlans`
    # (the nested signature is resolved in tsp_sign, verified on 4/4 real envelopes). mainSwitch =
    # master switch; the plan (time/duration/days) is passed by the entity via `params`.
    # cycleData [1..7] = days; startTime/timeConsuming in MINUTES; switchStatus = plan active.
    ("ricarica_prog_on", {"endpoint": "chargeAppointControl",
                   "body": {"mainSwitch": 1, "chargeAppointPlans": [
                       {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": 480,
                        "switchStatus": 1, "timeConsuming": 360}]},
                   "name": "Scheduled charging ON", "icon": "mdi:calendar-clock", "group": "Charging"}),
    ("ricarica_prog_off", {"endpoint": "chargeAppointControl",
                   "body": {"mainSwitch": 0, "chargeAppointPlans": [
                       {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": 480,
                        "switchStatus": 0, "timeConsuming": 360}]},
                   "name": "Scheduled charging OFF", "icon": "mdi:calendar-remove", "group": "Charging"}),
    # NB: no charge-limit / target-SoC command. The OMODA "legend" backend has no such
    # endpoint — the app binary only calls chargeAppointControl, and chargeDepthControl
    # returns A07334 (unsupported for the vehicle). Charge limit is car-screen-only.

    # — Other —
    ("find_car", {"endpoint": "findCar", "body": {},
                   "name": "Diagnostic Find Car (Flash)", "icon": "mdi:car-search", "group": "Other"}),
    # NB: remoteStart (remote engine start) REMOVED: tried live (2026-06-21) →
    # the car responds A00084 "No vehicle control command permission" (permission denied for
    # this vehicle). No point exposing a button that always fails. The
    # CVRemoteStartReqBean bean (no fields) remains known in case the permission changes in the future.
    # GPS location request: does NOT act on anything; the car responds with an MQTT push serviceType 1301
    # (lat/lon) that the bridge wires into the device_tracker. It is the app's method for the at-rest position.
    ("locate_car", {"endpoint": "vehicleLocation", "body": {},
                   "name": "Diagnostic Locate Car (GPS)", "icon": "mdi:crosshairs-gps", "group": "Other"}),

    # — Security — Theft alarm (theftAlarm). Alerts+siren for unauthorized movement,
    # door break-in, window breakage (official app description). NB: lives on /act (NOT
    # /asc/vehicleControl) → uses the `path` key instead of `endpoint`. Body = theftAlarmSwitch
    # 0/1; send() adds clientType/seq/vin and the minted taskId (the backend requires it:
    # A00643 without it). State readable via query_theft_switch() (/act/theftAlarm/querySwitch).
    ("alarm_theft_on",  {"path": "/act/theftAlarm/setSwitch", "body": {"theftAlarmSwitch": "1"},
                   "name": "Theft alarm ON", "icon": "mdi:shield-car", "group": "Security"}),
    ("alarm_theft_off", {"path": "/act/theftAlarm/setSwitch", "body": {"theftAlarmSwitch": "0"},
                   "name": "Theft alarm OFF", "icon": "mdi:shield-off-outline", "group": "Security"}),
]
CMD_MAP = {k: v for k, v in COMMANDS}

# tspconsole response codes → readable text: now from the SINGLE map core/codes.py.
CODE_MEANING = codes.CODE_MEANING

# Command outcome: the backend always answers HTTP 200; the real result is the body `code`.
# SUCCESS_CODES = accepted by the backend (the car then confirms via MQTT 110x).
# FAILURE_CODES = NOT executed (car busy/asleep, permission denied, invalid taskId or token).
# Distinguishing the two is what lets the optimistic entities revert instead of showing a fake
# success when the car refused (see OmodaJaecooOptimisticMixin._run_command).
SUCCESS_CODES = frozenset({"000000", "A00079"})
FAILURE_CODES = frozenset({
    "A00082",   # car busy (transient, retryable)
    "A00084",   # command not allowed on this car
    "A00089", "A00546", "A00567",   # invalid taskId / checkPassword
    "A00000",   # token expired/invalid
    "A07312",   # wake rate-limit
    "A07900",   # car asleep / invalid signature or car_token
})
RETRYABLE_CODES = frozenset({"A00082"})   # only "car busy" is worth retrying


class CommandError(Exception):
    """A command the backend/car REFUSED (not executed). `code` = tspconsole code,
    `retryable` = retrying makes sense (e.g. car busy). `reason` routes the REMEDY in the
    coordinator (by cause, not just code):
      - "pin"    = wrong/missing/anti-locked command PIN → reconfigure the PIN (Repair issue /
                   Configure → Reconfigure). NOT a session problem: the token is valid.
      - "reauth" = session/token expired (login failed, code A00000) → native HA re-auth (new
                   OTP). The OTP does NOT change the PIN — the two channels are distinct.
      - None     = other car refusal (busy, not allowed, asleep): just surface the message.
    The coordinator lets it propagate; the optimistic entity catches it to revert the optimistic
    state and show the real error instead of staying on a fake success."""

    def __init__(self, message: str, code: str | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.retryable = code in RETRYABLE_CODES


# H6 anti-lockout: stop after N consecutive failed checkPassword calls within a window,
# to avoid tripping the account's PIN lock (a wrong PIN increments the
# errors on the Chery side). A success (taskId obtained) resets the counter.
_PIN_FAIL = {"n": 0, "ts": 0.0}
_PIN_FAIL_MAX = int(os.environ.get("OMODA_PIN_FAIL_MAX", "2"))
_PIN_FAIL_WINDOW = int(os.environ.get("OMODA_PIN_FAIL_WINDOW", "600"))
# checkPassword codes that do NOT indicate a wrong PIN (session/token) → they don't count
# toward the anti-lockout (otherwise an expired token would wrongly block minting).
_NON_PIN_CODES = {"A00000"}


def reset_pin_lockout() -> None:
    """Reset the wrong-PIN anti-lockout counter. `_PIN_FAIL` is module-level: a plain entry
    reload (e.g. after correcting the PIN) does NOT re-import the module, so without this reset
    commands would stay blocked until the window (600s) lapses or HA restarts. Called when the
    PIN is reconfigured (config flow / Repair) and from the coordinator's _bind_core when it
    detects the PIN changed."""
    _PIN_FAIL["n"] = 0
    _PIN_FAIL["ts"] = 0.0


def _mint_taskid(tuid):
    """Mints a taskId with the app's BFF chain (queryList→setVecDefault→checkPassword).
       FIX S26 (2026-06-20): scene=0 (NOT 2) → the minted taskId is blessed by tspconsole
       (airControl A00079). scene=2 gave A00089; scene=1 A00089; scene>=3 A00546. Objective #1 SOLVED.

       H6: refuses to mint if the PIN is empty (does NOT call checkPassword empty) and
       auto-blocks after too many consecutive wrong PINs to avoid the account lockout."""
    if not (PIN or "").strip():
        raise CommandError(
            "Command PIN not configured — set it in the integration settings", reason="pin")
    now = time.time()
    if _PIN_FAIL["n"] >= _PIN_FAIL_MAX and (now - _PIN_FAIL["ts"]) < _PIN_FAIL_WINDOW:
        raise CommandError(
            f"Command PIN temporarily blocked ({_PIN_FAIL['n']} wrong attempts) — reconfigure "
            "the PIN in the integration settings, then retry", reason="pin")

    import requests
    access = wake._access_token()
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}

    def bff(path, body):
        H = A.headers_post(path, extra=extra)
        r = requests.post(A.BFF + path, data=json.dumps(body), headers=H, timeout=25)
        try:
            j = r.json()
        except Exception:
            return {"_raw": r.text[:200]}
        # MED: the BFF may return a non-dict top-level (string) → normalize to {}
        return j if isinstance(j, dict) else {}

    bff("/tsp/v1/app/vmc/queryList", {})
    bff("/tsp/v1/app/vmc/setVecDefault", {"vin": VIN})
    plain = hashlib.md5(PIN.encode()).hexdigest()
    password = A.sm4_code(plain, "padRight32")
    j = bff("/tsp/v1/app/cpm/checkPassword",
            {"vin": VIN, "tUserId": str(tuid), "channelId": A.CHANNEL_ID,
             "password": password, "needDecode": 0, "scene": 0, "type": 0})
    data = j.get("data") if isinstance(j.get("data"), dict) else {}
    tid = data.get("taskId") or j.get("taskId")
    if tid:
        _PIN_FAIL["n"] = 0          # success → reset the anti-lockout counter
        return tid
    # no taskId: distinguish the CAUSE to route the right remedy.
    code = j.get("code")
    if str(code) in _NON_PIN_CODES:
        # session/token (A00000): NOT the PIN's fault → don't count anti-lockout, ask for reauth.
        raise CommandError(
            "Session expired — re-authenticate from the Home Assistant notification (new OTP)",
            code=str(code), reason="reauth")
    # any other no-taskId outcome = command PIN rejected → count it and ask for a PIN reconfig.
    _PIN_FAIL["n"] += 1
    _PIN_FAIL["ts"] = now
    raise CommandError(
        "Wrong command PIN — reconfigure it in the integration settings", reason="pin")


# In-memory taskId cache. Minting a taskId runs the full checkPassword (PIN) round-trip,
# which is the slow part of every command. The taskId stays valid for a while, so we reuse
# it and only re-mint when the car rejects it as invalid/expired (A00089/A00546) or the TTL
# lapses — turning most commands into a single signed POST instead of PIN + POST.
_TASKID_TTL = int(os.environ.get("OMODA_TASKID_TTL", "600"))   # reuse a minted taskId up to ~10 min
_TASKID_CACHE = {"tid": None, "ts": 0.0}


def invalidate_taskid():
    """Drop the cached taskId (call when the car rejects it as invalid/expired)."""
    _TASKID_CACHE["tid"] = None
    _TASKID_CACHE["ts"] = 0.0


def get_taskid(tuid, emit=lambda m: None, allow_cache=True):
    """taskId source, in order: env TASKID → piggyback file → cached → auto-minted checkPassword."""
    t = os.environ.get("TASKID")
    if t:
        return t.strip(), "env"
    try:
        if os.path.exists(TASKID_FILE):
            with open(TASKID_FILE) as fh:
                v = fh.read().strip()
            if v:
                return v, "file"
    except OSError:
        pass
    if allow_cache and _TASKID_CACHE["tid"] and (time.time() - _TASKID_CACHE["ts"]) < _TASKID_TTL:
        return _TASKID_CACHE["tid"], "cache"
    if MINT_TASKID:
        emit("authenticating (checkPassword)…")
        try:
            tid = _mint_taskid(tuid)
        except CommandError as e:
            # wrong PIN / anti-lockout / session: publish the detail and PROPAGATE (no longer
            # swallowed) → send() lets it rise with its `reason` for the remedy routing.
            emit(str(e))
            raise
        except Exception as e:  # noqa: BLE001 — unexpected mint error → generic PIN reason
            emit(f"checkPassword failed: {e}")
            raise CommandError(
                "Command PIN could not be verified — reconfigure it in the integration "
                f"settings ({e})", reason="pin") from e
        if tid:
            _TASKID_CACHE["tid"] = tid
            _TASKID_CACHE["ts"] = time.time()
            return tid, "checkPassword"
    return None, "none"


def send(cmd_key, emit=lambda m: None, params=None):
    """Sends a command. emit(str) receives the steps (to publish them on HA).
       `params` (optional) = overrides/additions to the catalog body BEFORE the common
       fields → enables the parametric commands (climate: temperature/times; immediate
       charging: controlType; scheduled charging: mainSwitch + chargeAppointPlans).
       The system fields (clientType/seq/taskId/vin) always remain the ones minted here.
       Returns a readable result string."""
    c = CMD_MAP.get(cmd_key)
    if not c:
        emit(f"unknown command: {cmd_key}")
        raise CommandError(f"Unknown command: {cmd_key}")

    token, tuid = wake._bff_login()
    if not token:
        emit("login failed (token expired? redo OTP with official app closed)")
        raise CommandError(
            "Session expired — re-authenticate from the Home Assistant notification (new OTP)",
            reason="reauth")

    url = TSP_HOST + (c.get("path") or ("/asc/vehicleControl/" + c["endpoint"]))
    # Try with the cached taskId; if the car rejects it as invalid/expired, re-mint once.
    for attempt in (1, 2):
        # get_taskid propagates CommandError (PIN/anti-lockout/session) with its `reason`.
        taskid, src = get_taskid(tuid, emit, allow_cache=(attempt == 1))
        if not taskid:
            # no taskId but no exception = minting disabled and no env/file taskId → config issue.
            emit("no taskId available")
            raise CommandError(
                "Wrong command PIN — reconfigure it in the integration settings", reason="pin")

        ts = int(time.time() * 1000)
        body = dict(c["body"])
        if params:
            body.update(params)    # parametric override (temperature/duration/controlType/plan)
        body.update({"clientType": "1", "seq": f"{VIN}-{ts}", "taskId": taskid, "vin": VIN})
        m = tsp_sign.sign_body(body, ts)
        payload = json.dumps(m, separators=(",", ":"), ensure_ascii=False).encode()
        headers = {"Authorization": token, "timestamp": str(ts),
                   "Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}
        emit(f"sending {c['name']}…")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status = e.code
        except Exception as e:
            emit(f"network error: {e}")
            raise CommandError(f"Network error while sending the command: {e}")

        code = None
        try:
            code = json.loads(raw).get("code")
        except Exception:
            pass
        # cached taskId no longer valid → drop it and re-mint a fresh one (one retry).
        if str(code) in ("A00089", "A00546") and attempt == 1 and src != "env":
            invalidate_taskid()
            continue

        meaning = CODE_MEANING.get(code, raw[:120])
        out = f"{c['name']}: HTTP {status} {code or ''} — {meaning}"
        emit(out)
        # Real outcome from `code`: a known failure code = command NOT executed → raise so the
        # optimistic entity reverts (the emit already published the detail to «Command Result»).
        # Unknown codes stay non-blocking (return): we don't invent a failure.
        if str(code) in FAILURE_CODES:
            # A00000 = token expired → reauth (new OTP); other refusals (busy / not allowed /
            # asleep) have no automatic remedy → just surface the message.
            reason = "reauth" if str(code) == "A00000" else None
            raise CommandError(out, code=str(code), reason=reason)
        return out


def query_theft_switch():
    """Reads the theft alarm state (READ-ONLY, /act/theftAlarm/querySwitch).
       Returns 1/0 (int) or None if unavailable. Does NOT use a taskId nor act on anything:
       the response puts the value under `body.theftAlarmSwitch`."""
    token, _tuid = wake._bff_login()
    if not token:
        return None
    try:
        _status, j = wake._signed_post(token, "/act/theftAlarm/querySwitch", {"vin": VIN})
    except Exception:
        return None
    if isinstance(j, dict):
        body = j.get("body") if isinstance(j.get("body"), dict) else {}
        v = body.get("theftAlarmSwitch")
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


if __name__ == "__main__":
    # Diagnostics: list the commands (does NOT send anything).
    for k, v in COMMANDS:
        print(f"{k:22s} {(v.get('path') or v.get('endpoint','')):28s} {v['body']}")
