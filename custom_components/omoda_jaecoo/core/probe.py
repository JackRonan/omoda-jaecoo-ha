#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py — "Location probe" Omoda / Jaecoo.

Question it answers (never cleanly tested so far): when the car is REALLY
awake (it is publishing 5A02 on MQTT), does the tspconsole-eu channel return
GPS location / realtime data, or still `A07900`?

SESSIONE 14 discovery (verified against the code of BOTH apps, EU + Russian):
  - There is NO BFF endpoint for the commands. The "legend" BFF only has
    auth/cpm(PIN)/env/map/vac/vmc. The commands/location ALL go through the Chery
    SDK → tspconsole-eu `/asc/vehicleControl/*` and `/asr/manager/realtime`,
    i.e. EXACTLY the paths we already use. No hidden channel.
  - So the only remaining variable is the car's AWAKE STATE. The app
    succeeds because it commands a just-used car; we fall onto A07900 (asleep)
    and cannot wake it (smsAwaken at A07312, per-account quota).

This probe is READ-ONLY: it calls `/asr/manager/realtime {vin}` and
`/asc/vehicleControl/queryVehicleLocation {vin}` (the same ones as wake.py's
poll). It does NOT send smsAwaken, does NOT send commands, does NOT touch the PIN. It's benign:
it's what the app does when you open the "location" page.

It should be invoked by the bridge (ha_bridge.py) on the asleep→awake rising edge, with
a long cooldown (default 30 min) so it doesn't repeat on every 5A02.

Strictly personal use (the user's car/account). Do NOT publish the token/cert.
"""
import os, sys, json, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Reuses the already-verified infrastructure of wake.py: BFF login + signed tspconsole POST.
import wake as W
import codes

VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: see omoda_jaecoo.env.example
PROBE_LOG  = os.environ.get("OMODA_PROBE_LOG", os.path.join(HERE, "data", "probe.jsonl"))
COOLDOWN_S = int(os.environ.get("PROBE_COOLDOWN", "1800"))   # 30 min: 1 probe per wake

_BUSY = threading.Lock()
_last_run = {"ts": 0.0}

# "rich" fields of the CVRealtimeResBean we care about most (if they ever arrive)
RICH_KEYS = ("lat", "lon", "altitude", "direction", "gpsSpeed", "vehicleSpeed",
             "odometer", "dumpEnergy", "electricRange", "pureElectricRange",
             "chargeState", "inCarTemperature", "onlineStatus")


def _log(rec: dict):
    rec = {"ts": round(time.time(), 3),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()), **rec}
    try:
        os.makedirs(os.path.dirname(PROBE_LOG), exist_ok=True)
        with open(PROBE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rich(data: dict) -> dict:
    """Extracts the interesting fields if present, for the readable summary."""
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in RICH_KEYS if k in data}


def probe_once(publish, force=False, on_data=None):
    """Runs ONE read-only probe and reports the outcome via `publish(text)`.

    Returns a dict {ok, online, got_data, codes, rich}. Never raises.
    `force=True` ignores the cooldown (for the manual test).
    `on_data(data)` (optional): callback invoked with the raw `data` dict ONLY when
    live data is received (car awake) — the bridge uses it to publish GPS/battery in HA.
    """
    if not _BUSY.acquire(blocking=False):
        return {"ok": False, "reason": "busy"}
    try:
        now = time.time()
        if not force and _last_run["ts"] and (now - _last_run["ts"]) < COOLDOWN_S:
            return {"ok": False, "reason": "cooldown",
                    "wait_s": int(COOLDOWN_S - (now - _last_run["ts"]))}
        _last_run["ts"] = now

        publish("🛰️ Location probe: the car is awake, trying to read GPS/realtime…")
        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Probe: session expired (redo OTP login). Retrying at the next wake")
            _log({"event": "probe", "ok": False, "reason": "no_usertoken"})
            return {"ok": False, "reason": "no_usertoken"}

        sc1, j1 = W._signed_post(ut, "/asr/manager/realtime", {"vin": VIN})
        sc2, j2 = W._signed_post(ut, "/asc/vehicleControl/queryVehicleLocation", {"vin": VIN})
        # travelQuery: we look for km/odometer (field not seen yet; we'll reveal it on the 1st real wake)
        sc3, j3 = W._signed_post(ut, "/asd/travelManage/travelQuery", {"vin": VIN})
        c1, c2, c3 = W._code_of(j1), W._code_of(j2), W._code_of(j3)
        got1, got2, got3 = W._has_live_data(j1), W._has_live_data(j2), W._has_live_data(j3)

        # combined data: realtime has priority (lat/lon/battery), travel/location add extra fields.
        # The payload is under "data" or "body" depending on the endpoint (realtime → "body"): W._payload
        # handles both, otherwise the 84 realtime fields were being lost.
        data = {}
        for src, got in ((j2, got2), (j3, got3), (j1, got1)):
            payload = W._payload(src)
            if got and isinstance(payload, dict):
                data.update(payload)
        rich = _rich(data)
        _log({"event": "probe", "ok": True, "realtime_code": c1, "location_code": c2,
              "travel_code": c3, "got_realtime": got1, "got_location": got2, "got_travel": got3,
              "rich": rich, "data": data or None,
              "travel_data": j3.get("data") if got3 else None})

        got1 = got1 or got3   # if travelQuery brings data with the car awake, it counts as "live"
        if (got1 or got2) and on_data and data:
            try:
                on_data(data)
            except Exception as e:
                publish(f"⚠️ Probe: data publishing error ({type(e).__name__})")

        if got1 or got2:
            if rich:
                bits = ", ".join(f"{k}={v}" for k, v in rich.items())
                publish(f"🟢🛰️ BREAKTHROUGH: realtime data received with the car awake! {bits}")
            else:
                publish("🟢🛰️ Probe: data received with the car awake (see data/probe.jsonl)")
            return {"ok": True, "online": True, "got_data": True,
                    "codes": [c1, c2, c3], "rich": rich}

        publish(f"🟡 Probe: still no location with the car awake "
                f"(realtime={c1} [{codes.meaning(c1)}], location={c2}, travel={c3}). "
                "Confirmed: another step is needed")
        return {"ok": True, "online": False, "got_data": False, "codes": [c1, c2, c3]}
    except Exception as e:
        publish(f"⚠️ Probe error: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        _BUSY.release()


# ───────────────────────── self-test (NO network) ─────────────────────────────
if __name__ == "__main__":
    pub = lambda t: print("  STATUS:", t)

    print("== TEST 1: realtime data received (mock) → BREAKTHROUGH ==")
    W._bff_login = lambda: ("FAKE_UT", "1")
    W._signed_post = lambda ut, path, params: (200, {"code": "000000", "data": {
        "lat": "45.07", "lon": "7.68", "dumpEnergy": "82", "vehicleSpeed": "0",
        "onlineStatus": "1"}}) if "realtime" in path else (200, {"code": "A07900"})
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))

    print("== TEST 2: still A07900 with the car awake (mock) ==")
    W._signed_post = lambda ut, path, params: (200, {"code": "A07900"})
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))

    print("== TEST 3: cooldown active ==")
    _last_run["ts"] = time.time()
    print("  ->", probe_once(pub))

    print("== TEST 4: expired token ==")
    W._bff_login = lambda: (None, None)
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))
    print("\nOK self-test finished (no real network calls).")
