"""Constants for the Omoda / Jaecoo custom component."""

DOMAIN = "omoda_jaecoo"
PLATFORMS = ["sensor", "binary_sensor", "button", "lock", "switch", "climate",
             "number", "time", "cover", "select", "device_tracker", "text"]

# Car fields (5A02) now represented by native ACTUATABLE entities (lock/switch/cover):
# excluded from creating read-only sensor/binary_sensor so we don't duplicate them.
# The comfort fields (defrost/steering wheel/driver-passenger-rear seats) are now
# ON/OFF switches (see switch.py). NB: the rear CENTER seat
# (mSeatHeatingState2/mSeatVentilateState2) has NO dedicated command → stays read-only.
FIELDS_AS_RICH_ENTITY = {
    "doorLock", "frontHVACState", "trunkDoor", "sunroofState",
    "frontWindshieldHeat", "rWinHeatingState", "steerWheelHeating",
    "dSeatHeatingState", "dSeatVentilateState",
    # passenger seat
    "pSeatHeatingState", "pSeatVentilateState",
    # rear left/right seats (telemetry *State2 ↔ bl/br SeatControl command)
    "lSeatHeatingState2", "lSeatVentilateState2",
    "rSeatHeatingState2", "rSeatVentilateState2",
}

# Catalog commands now handled by lock/switch/cover → excluded from single buttons
# (tapping the lock/switch/cover invokes the same catalog command).
COMMANDS_AS_RICH_ENTITY = {
    "blocca", "sblocca",
    # clima_on/clima_off are now driven by the climate entity (climate.py) → no buttons.
    "clima_on", "clima_off",
    # EV charging: dedicated switches (switch.py) → no single buttons.
    "ricarica_start", "ricarica_stop", "ricarica_prog_on", "ricarica_prog_off",
    "baule_apri", "baule_chiudi",
    # windows: now a 3-state select (Closed/Ventilate/Open) → no buttons (see select.py)
    "finestrini_apri", "finestrini_chiudi", "ventilate_windows",
    "tetto_apri", "tetto_chiudi",
    # comfort: every function is a switch (ON+OFF) → no single buttons
    "defrost_parabrezza", "defrost_parabrezza_off",
    "defrost_lunotto", "defrost_lunotto_off",
    "volante_caldo", "volante_caldo_off",
    "sedile_guida_caldo", "sedile_guida_caldo_off",
    "sedile_guida_aria", "sedile_guida_aria_off",
    "sedile_passeggero_caldo", "sedile_passeggero_caldo_off",
    "sedile_passeggero_aria", "sedile_passeggero_aria_off",
    "sedile_post_sx_caldo", "sedile_post_sx_caldo_off",
    "sedile_post_sx_aria", "sedile_post_sx_aria_off",
    "sedile_post_dx_caldo", "sedile_post_dx_caldo_off",
    "sedile_post_dx_aria", "sedile_post_dx_aria_off",
    # climate "all" macros: dedicated switches (Climate Cool/Heat Up All) → no duplicate buttons.
    "climate_cool_on", "climate_cool_off",
    "climate_heat_on", "climate_heat_off",
    # theft alarm: dedicated switch (Alarm Theft) → no duplicate ON/OFF buttons.
    "alarm_theft_on", "alarm_theft_off",
}

# config_entry keys (per-account data, entered in the config flow)
CONF_EMAIL = "email"
CONF_PIN = "pin"
CONF_VIN = "vin"
CONF_TUSERID = "tuserid"

# Vehicle identity for the HA device (dynamic name: "Omoda / Jaecoo", "Jaecoo 7"…). `vehicle_name`
# = nickname/model from the app, saved in entry.data (captured at config flow or backfilled);
# it is also an OPTION for the manual override. model/brand stay only in entry.data.
CONF_VEHICLE_NAME = "vehicle_name"
CONF_VEHICLE_IMAGE = "vehicle_image"   # optional image URL, shown by the custom card
DATA_VEHICLE_MODEL = "vehicle_model"
DATA_VEHICLE_BRAND = "vehicle_brand"
# fallback when the model is not (yet) known
DEFAULT_VEHICLE_NAME = "Omoda / Jaecoo"

# Per-vehicle CAPABILITIES discovered from queryList (stored in entry.data, so entities
# can adapt to the specific car). All optional — absent = "unknown", entities fall back
# to safe defaults (show everything / standard climate range), so there is no regression.
DATA_POWER_TYPE = "power_type"          # 0 = pure electric (BEV); other/None = has combustion / unknown
DATA_CLIMATE_MIN = "climate_min_temp"   # queryList minTemperature (°C)
DATA_CLIMATE_MAX = "climate_max_temp"   # queryList maxTemperature (°C)
DATA_CLIMATE_STEP = "climate_temp_step"  # queryList temperatureStepLength (°C)


def capabilities_from_item(item: dict) -> dict:
    """Extract the per-vehicle capability fields from a queryList vehicle item.
    Returns a dict of the DATA_* keys present (missing/invalid fields are skipped)."""
    out: dict = {}
    if not isinstance(item, dict):
        return out
    pt = item.get("powerType")
    if pt is not None:
        out[DATA_POWER_TYPE] = pt
    for src, dst in (("minTemperature", DATA_CLIMATE_MIN),
                     ("maxTemperature", DATA_CLIMATE_MAX),
                     ("temperatureStepLength", DATA_CLIMATE_STEP)):
        v = item.get(src)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[dst] = float(v)
    return out

# REGION parameters (default = Europe). Exposed as options to support other regions.
CONF_BFF = "bff"
CONF_TSP_HOST = "tsp_host"
CONF_CAR_MQTT_HOST = "car_mqtt_host"
CONF_CAR_MQTT_PORT = "car_mqtt_port"
CONF_CHANNEL_ID = "channel_id"

# MQTT mutual-TLS certificate provisioning (PHASE 3c). Folder (inside the HA filesystem)
# to import the 4 certs from into the per-entry certs_dir. Empty = certs placed by hand.
CONF_CERTS_SRC = "certs_src"

# The 4 mutual-TLS files expected in the per-entry certs_dir (= those of the bridge certs_eu/).
CERT_FILES = ("ca.pem", "client.pem", "client.key", "eu_prd_cheryinternational.cer")

DEFAULTS = {
    CONF_BFF: "https://legend-oj.omodaauto.nl/api",
    CONF_TSP_HOST: "https://tspconsole-eu.cheryinternational.com",
    CONF_CAR_MQTT_HOST: "tspemqx-app-eu.cheryinternational.com",
    CONF_CAR_MQTT_PORT: 8083,
    CONF_CHANNEL_ID: "1",
}

# Shared app constant (not a user secret): seed to derive the MQTT password
CAR_SEED = "fa89db3abe8045919d70c6ed3cc65bc5"

# Intervals (seconds)
DEFAULT_SESSION_EVERY = 900
DEFAULT_AWAKE_WINDOW = 300

# Periodic telemetry poll (wake + realtime read). TWO intervals in MINUTES,
# customizable from the integration options; 0 = disabled:
#   - CONF_POLL_NORMAL  : at rest/parked (default 60 min)
#   - CONF_POLL_CHARGING: when plugged into the charger (default 30 min). Since v1.5.14 it is NO
#     longer the mechanism that follows the charge (that's the 2-min CHARGING_POLL_EVERY loop, in
#     read-only): here it stays only as a BACKSTOP that starts that loop if the car doesn't announce
#     the cable connection by itself, + periodic GPS refresh. While charging the car is powered.
# The "plugged in" state is detected from `chargeGunState` (cable connected).
# ⚠️ every cycle WAKES the car (vehicleLocation) for fresh position + telemetry even
# when parked → tiny 12V drain and possible contention with the official app.
CONF_POLL_NORMAL = "poll_normal_min"
CONF_POLL_CHARGING = "poll_charging_min"
DEFAULT_POLL_NORMAL_MIN = 60
DEFAULT_POLL_CHARGING_MIN = 30
# wait between the wake (locate) and the forced realtime read, so the car comes back online
POLL_WAKE_WAIT = 25
# High voltage (HV) and FRESH telemetry. Discovery verified live 2026-06-22: the
# /asr/manager/realtime channel reports REAL odometer/SOC/voltage/current only when the high voltage
# is on (hVoltageState=1: driving, charging, or climate on); with HV off it returns a stale
# snapshot (old odometer, dumpEnergy=0, totalVoltage=0, totalCurrent=-1000). There is no
# "light" command that forces a fresh report (confirmed by reverse-engineering the native
# Chery SDK): the only way is to read while the HV is ALREADY on. So, as soon as we see the HV
# on, we re-read the realtime rapidly to capture the values as they rise (odometer/battery),
# then stop by ourselves when it turns off again. Zero commands to the car.
HV_ON_POLL_EVERY = 60   # seconds between two realtime reads while the high voltage is on
HV_ON_POLL_MAX = 90     # safety cap on the number of close reads (~90 min of driving)
# CHARGING: when the cable is connected the car charges for HOURS (e.g. 246 min seen live 2026-06-23)
# and the HV is on → the realtime has REAL battery/current/voltage/remaining-time. The same close
# loop then follows the charge progress, but with a more relaxed interval and a much higher cap
# than driving (a full AC charge can last several hours). Verified 2026-06-23: with the car
# charging a realtime read immediately gives updated stato_ricarica/corrente_hv/tempo_residuo.
CHARGING_POLL_EVERY = 120   # seconds between two realtime reads while the cable is connected (charging)
CHARGING_POLL_MAX = 300     # safety cap (~10h: covers a full AC charge with margin)
# DRIVING (detection heartbeat): the car IN MOTION does not send MQTT pushes (verified live
# 2026-06-24: while driving the MQTT session is connected but no 5A02 arrives → engine/
# speed stayed at the previous day) and the periodic "wake+read" poll is every ~hour. Without
# a dedicated heartbeat the automatic refresh during a trip would NEVER start. This timer does ONLY
# a realtime read (NO command, NO wake, zero 12V): as soon as it finds the HV on, that same
# read arms the follow-up at HV_ON_POLL_EVERY (60s) which then follows the whole trip. If the
# follow-up is already active (driving/charging) the heartbeat does nothing. With the car parked it's a
# single GET to the cloud each interval (the realtime returns the stale snapshot, discarded): no car drain.
DRIVE_WATCH_EVERY = 180     # seconds between two "are you driving?" checks (read-only, no commands)
# wait in the comfort macros between the wake (locate) and sending coolingControl/heatingControl:
# the climate+seat modules only respond with the car AWAKE and it takes time for the TBOX to power the
# comfort bus. Verified live 2026-06-21: with ~35s the macro command succeeds; with
# 14s it failed (TBOX↔ECU timeout). Below this value the macros go back to erroring.
MACRO_WAKE_WAIT = 35
# duration of the comfort preset (coolingControl/heatingControl use duration/times = 15 min):
# the car turns it off by itself after this time → the macro switch returns to OFF on its own so it
# doesn't stay "on" for nothing. +60s of margin.
MACRO_PRESET_S = 15 * 60 + 60

# Anti double-tap: the car runs ONE command at a time (A00082 = "vehicle busy").
# After a command, for these seconds a new ACTUATING command is rejected with a
# clear message instead of queuing/flooding. The lock releases earlier if the
# confirmation arrives from the car. Safety cap in case the confirmation never arrives.
COMMAND_LOCK_S = 12
