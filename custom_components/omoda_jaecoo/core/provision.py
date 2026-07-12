#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
provision.py — Omoda / Jaecoo vehicle command PROVISIONING chain (SESSIONE 16).

DISCOVERY (5-agent workflow, S16 — file:line evidence in SESSIONE16_REPORT.md):
  The `/asc/vehicleControl/*` commands do NOT want the BFF `userToken` (that's the one
  we use → universal A07900), but a **per-vehicle car_token**.
  The app's real chain (rus_car_control_provider.dart:6511-6567) is:

      getTuserId → loginTSP (= car_token) → queryList → setVecDefault(vin)
      → checkPassword(scene=2 → taskId) → command  (Authorization = car_token)

  - `loginCheck` is NOT in this chain (it's the QR login on the infotainment, discarded).
  - Vehicle authorization is not a boolean: it's the int `authorizeType` of the
    RusCarAuthorize bean (==2 owner → controlCarList; ==0 delegated →
    authorizedControlCarList). The VIN must appear in one of the two lists.
  - The car_token on the Dart side = CurrentVehicle.token, populated by getTspToken()/
    loginTSP (NATIVE impl, nop in the DEX). TO-BE-VERIFIED whether it is also a field of the
    BFF `queryList` response: that is EXACTLY what PHASE A below measures.

──────────────────────────────────────────────────────────────────────────────
TWO CLEARLY SEPARATE PHASES:

  PHASE A — `diagnose()` : DIAGNOSTIC, READ-ONLY, **does NOT touch the car**.
      Calls only the BFF (legend-oj): login → getTuserId → queryList.
      For our VIN it prints: membership list, authorizeType, and SEARCHES for a
      possible per-vehicle token field (car_token) in the response.
      NO `/asc/vehicleControl/*`, NO smsAwaken, NO checkPassword.
      It's the test that discriminates hypotheses A/B/C with no effect on the car.

  PHASE B — `run_command()` : ACTIVE. Runs setVecDefault(vin) → checkPassword(PIN)
      → command, using the **car_token** as Authorization (not the userToken).
      To be run ONLY with explicit OK and with the car awake. checkPassword with the
      RIGHT PIN is re-runnable; a WRONG PIN risks the lockout → never guess.

RULES: this module is NOT executed at import. `__main__` by default runs only
PHASE A (read-only). PHASE B starts only with the explicit `command` argument.

Strictly personal use (the user's car/account). Do NOT publish the token/PIN/cert.
"""
import os, sys, json, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import requests
import omoda_auth as A
import tsp_sign as S
import wake as W          # reuses _access_token / _bff_login / _signed_post / _code_of (already verified)
import codes

VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: see omoda_jaecoo.env.example
PIN        = os.environ.get("PIN", os.environ.get("OMODA_PIN", ""))   # control PIN (PER-ACCOUNT)
# Opt-in ONLY (may capture tokens/VIN in the provisioning chain): off unless the user sets
# OMODA_PROV_LOG to a path of their choosing. Avoids writing sensitive data under the package dir.
PROV_LOG   = os.environ.get("OMODA_PROV_LOG")

# BFF endpoints (legend-oj) of the provisioning chain — all POST, Bearer access_token + app sign.
BFF_GETTUSERID    = "/tsp/v1/app/auth/getTuserId"
BFF_QUERYLIST     = "/tsp/v1/app/vmc/queryList"
BFF_SETVECDEFAULT = "/tsp/v1/app/vmc/setVecDefault"
BFF_CHECKPASSWORD = "/tsp/v1/app/cpm/checkPassword"

# candidate key names for the per-vehicle token inside the queryList response (TO-BE-VERIFIED)
CAR_TOKEN_KEYS = ("token", "tspToken", "carToken", "accessToken", "vehicleToken", "controlToken")


# ───────────────────────── util ────────────────────────────────────────────────
def _log(rec: dict):
    if not PROV_LOG:            # opt-in only (may contain tokens/VIN) — see above
        return
    rec = {"ts": round(time.time(), 3),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()), **rec}
    try:
        os.makedirs(os.path.dirname(PROV_LOG), exist_ok=True)
        with open(PROV_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _redact(body: dict) -> dict:
    """For logs/prints: do not show the encrypted PIN or the tokens in clear text."""
    out = {}
    for k, v in (body or {}).items():
        if k in ("password",) or k.lower().endswith("token"):
            out[k] = f"<{len(str(v))}ch>" if v else v
        else:
            out[k] = v
    return out


# ───────────────────────── authenticated BFF calls (patchable in tests) ───────
def _bff_call(path: str, params: dict = None, method: str = "POST"):
    """Authenticated POST/GET to the legend-oj BFF: Bearer access_token + app headerSignature.

    It's the PROVEN scheme (stage2_tsp.py / checkpw_oneshot.py): the BFF's vmc/cpm/auth
    routes accept the access_token as Bearer. Returns (status_code, json)."""
    access = W._access_token()
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    H = A.headers_post(path, extra=extra)
    url = A.BFF + path
    if method.upper() == "GET":
        r = requests.get(url, params=params or {}, headers=H, timeout=25)
    else:
        r = requests.post(url, data=json.dumps(params or {}), headers=H, timeout=25)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:400]}


def get_tuser_id(user_id: str = None):
    """getTuserId — returns (status, json). Query {channelId, userId} (user_id optional)."""
    q = {"channelId": A.CHANNEL_ID}
    if user_id:
        q["userId"] = str(user_id)
    return _bff_call(BFF_GETTUSERID, q, method="GET")


def query_list():
    """queryList — POST {} → vehicle list (controlCarList / authorizedControlCarList)."""
    return _bff_call(BFF_QUERYLIST, {}, method="POST")


def set_vec_default(vin: str = None):
    """setVecDefault — POST {vin}. Binds the active vehicle. Does NOT reach the TBOX."""
    return _bff_call(BFF_SETVECDEFAULT, {"vin": vin or VIN}, method="POST")


def check_password(tuser_id: str, pin: str = None, vin: str = None, scene: int = 2):
    """checkPassword(scene=2) → (status, json, taskId). password = sm4(md5(pin)).

    Recipe settled in S10/confirmed S16: md5(pin) then sm4RandomString (padRight32),
    needDecode=0, type=0, scene=2. The RIGHT PIN is re-runnable (does not increment errors)."""
    pin = pin or PIN
    plain = hashlib.md5(pin.encode("utf-8"), usedforsecurity=False).hexdigest()   # generateMd5(pin) — API-required
    password = A.sm4_code(plain, "padRight32")                # sm4RandomString(md5(pin))
    body = {"vin": vin or VIN, "tUserId": str(tuser_id), "channelId": A.CHANNEL_ID,
            "password": password, "needDecode": 0, "scene": scene, "type": 0}
    sc, j = _bff_call(BFF_CHECKPASSWORD, body, method="POST")
    data = j.get("data") if isinstance(j, dict) and isinstance(j.get("data"), dict) else {}
    task_id = data.get("taskId") or (j.get("taskId") if isinstance(j, dict) else None)
    return sc, j, task_id


def send_command(cmd: str, car_token: str, vin: str = None, tuser_id: str = None,
                 task_id: str = None, extra_body: dict = None):
    """Sends the command to tspconsole-eu with Authorization = **car_token** (not userToken).

    Base body = {channelId, tUserId, vin} (+ taskId if present) as per
    i18n_car_quest_model.dart:3190; `extra_body` for command-specific fields
    (e.g. switchStatus). Reuses wake._signed_post passing the car_token as the token.
    Returns (status, json)."""
    body = {"vin": vin or VIN, "channelId": A.CHANNEL_ID}
    if tuser_id:
        body["tUserId"] = str(tuser_id)
    if task_id:
        body["taskId"] = task_id
    if extra_body:
        body.update(extra_body)
    path = cmd if cmd.startswith("/") else f"/asc/vehicleControl/{cmd}"
    return W._signed_post(car_token, path, body)


# ───────────────────────── vehicle extraction from the queryList response ──────────
def _iter_vehicles(qlist_json):
    """Returns [(list_name, item_dict)] for each vehicle in the response's lists.

    Robust to different shapes: data.controlCarList / data.authorizedControlCarList, but
    also data as a list, or nested lists. list_name = diagnostic label."""
    out = []
    data = qlist_json.get("data") if isinstance(qlist_json, dict) else None
    named = {}
    if isinstance(data, dict):
        for key in ("controlCarList", "authorizedControlCarList", "carList", "list", "vehicles"):
            v = data.get(key)
            if isinstance(v, list):
                named[key] = v
        if not named:
            # data might already be a single vehicle
            if any(k in data for k in ("vin", "VIN")):
                out.append(("data", data))
    elif isinstance(data, list):
        named["data"] = data
    for name, lst in named.items():
        for it in lst:
            if isinstance(it, dict):
                out.append((name, it))
    return out


def _vin_of(item: dict) -> str:
    for k in ("vin", "VIN", "Vin"):
        if item.get(k):
            return str(item[k])
    return ""


def _car_token_in(item: dict):
    """Searches for a per-vehicle token field in the bean (key + value), otherwise (None, None)."""
    for k in CAR_TOKEN_KEYS:
        if item.get(k):
            return k, item[k]
    # case-insensitive search over keys that contain 'token'
    for k, v in item.items():
        if "token" in k.lower() and v:
            return k, v
    return None, None


def find_our_vehicle(qlist_json, vin: str = None):
    """→ dict {found, list_name, authorize_type, car_token_key, car_token, item} for our VIN."""
    vin = vin or VIN
    for list_name, item in _iter_vehicles(qlist_json):
        if _vin_of(item) == vin:
            ck, cv = _car_token_in(item)
            return {"found": True, "list_name": list_name,
                    "authorize_type": item.get("authorizeType"),
                    "car_token_key": ck, "car_token": cv, "item": item}
    return {"found": False, "list_name": None, "authorize_type": None,
            "car_token_key": None, "car_token": None, "item": None}


# ───────────────────────── PHASE A: READ-ONLY diagnostics ─────────────────────
def diagnose(publish):
    """PHASE A — login → getTuserId → queryList. **No command, does not touch the car.**

    Discriminates the hypotheses of the S16 report:
      - VIN present + car_token in the response → hypothesis B solvable (just the bind).
      - VIN present but no car_token → hypothesis A (token from native loginTSP).
      - VIN absent / empty list → account not bound to the vehicle (not bypassable).
    Returns a summary dict. Never raises."""
    try:
        publish("🔎 Vehicle diagnostics (read-only, does not interact with car)…")
        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Session expired: redo OTP login (token.json).")
            return {"ok": False, "reason": "no_usertoken"}

        # getTuserId (informational; tUserId already comes from the login)
        sc_t, j_t = get_tuser_id()
        tuser = tu or (j_t.get("data") if isinstance(j_t, dict) else None)

        # queryList → vehicle lists
        sc_q, j_q = query_list()
        code_q = W._code_of(j_q)
        veh = find_our_vehicle(j_q, VIN)

        _log({"event": "diagnose", "getTuserId_http": sc_t, "queryList_http": sc_q,
              "queryList_code": code_q, "tUserId": tu, "vehicle": {
                  k: veh[k] for k in ("found", "list_name", "authorize_type",
                                      "car_token_key")},
              "car_token_present": bool(veh["car_token"]),
              "queryList_data": j_q.get("data") if isinstance(j_q, dict) else None})

        if not veh["found"]:
            publish(f"🟥 VIN {VIN} NOT present in the lists (code={code_q}). "
                    "→ account not authorized for control: no software bypasses it.")
            return {"ok": True, "found": False, "queryList_code": code_q,
                    "hypothesis": "account_not_bound"}

        at = veh["authorize_type"]
        which = veh["list_name"]
        if veh["car_token"]:
            publish(f"🟩 VIN found in {which} (authorizeType={at}) and the response CONTAINS "
                    f"a per-vehicle token (field '{veh['car_token_key']}') → hypothesis B: "
                    "just the bind + using that car_token in the command.")
            hyp = "B_cartoken_in_querylist"
        else:
            publish(f"🟨 VIN found in {which} (authorizeType={at}) but NO car_token "
                    "in the response → hypothesis A: the car_token comes from loginTSP (native), "
                    "to be replicated. Bind possible, token to be found.")
            hyp = "A_cartoken_from_logintsp"
        return {"ok": True, "found": True, "list_name": which, "authorize_type": at,
                "car_token_key": veh["car_token_key"], "has_car_token": bool(veh["car_token"]),
                "queryList_code": code_q, "tUserId": tu, "hypothesis": hyp}
    except Exception as e:
        publish(f"⚠️ Diagnostics error: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}


# ───────────────────────── PHASE B: active chain (gated) ────────────────────────
def run_command(publish, cmd: str = "remoteStart", pin: str = None,
                extra_body: dict = None, is_awake=None):
    """PHASE B — setVecDefault(vin) → checkPassword(PIN, scene=2) → command with car_token.

    ⚠️ ACTIVE: sends a real command to the car. To be called ONLY with explicit OK and
    the car awake. Uses the car_token found in diagnose() (hypothesis B); if absent,
    it does NOT invent one: it stops and signals that the loginTSP path is needed (hypothesis A).
    Returns a summary dict. Never raises."""
    try:
        if is_awake is not None and not is_awake():
            publish("⌛ Car asleep: the command would return A07900. Wake it first (recent use).")
            return {"ok": False, "reason": "asleep"}

        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Session expired: redo OTP login.")
            return {"ok": False, "reason": "no_usertoken"}

        # 1) diagnostics/queryList to obtain the car_token (hypothesis B)
        sc_q, j_q = query_list()
        veh = find_our_vehicle(j_q, VIN)
        if not veh["found"]:
            publish(f"🟥 VIN not in list (code={W._code_of(j_q)}): not authorized. Stop.")
            return {"ok": False, "reason": "vehicle_not_found"}
        car_token = veh["car_token"]
        if not car_token:
            publish("🟨 No car_token in queryList → requires loginTSP (hypothesis A), "
                    "native implementation not yet replicated. Stop before sending commands.")
            return {"ok": False, "reason": "no_car_token", "hypothesis": "A_cartoken_from_logintsp"}

        # 2) vehicle bind (does NOT touch the TBOX)
        sc_s, j_s = set_vec_default(VIN)
        publish(f"🔗 setVecDefault → {W._code_of(j_s)}")

        # 3) checkPassword(scene=2) → taskId
        sc_p, j_p, task_id = check_password(tu, pin=pin, vin=VIN, scene=2)
        if not task_id:
            publish(f"🔐 checkPassword without taskId (code={W._code_of(j_p)}): "
                    "PIN not accepted or token expired. Stop (no PIN retry).")
            return {"ok": False, "reason": "no_taskid", "code": W._code_of(j_p)}
        publish("🔐 PIN ok, taskId obtained. Sending command with car_token…")

        # 4) command with Authorization = car_token
        sc_c, j_c = send_command(cmd, car_token, vin=VIN, tuser_id=tu,
                                 task_id=task_id, extra_body=extra_body)
        code_c = W._code_of(j_c)
        _log({"event": "command", "cmd": cmd, "car_token_key": veh["car_token_key"],
              "setVecDefault_code": W._code_of(j_s), "checkPassword_http": sc_p,
              "command_http": sc_c, "command_code": code_c})

        if str(code_c) == "A00079":
            publish(f"✅ Command {cmd} ACCEPTED (A00079)! Result via MQTT push.")
            return {"ok": True, "code": code_c, "cmd": cmd}
        if str(code_c) == "A07900":
            publish(f"🟧 Still A07900 with car_token → hypothesis C remains "
                    "(SM4 encrypted body) or incorrect car_token. See data/provision.jsonl.")
        else:
            publish(f"ℹ️ Command {cmd}: code={code_c} ({codes.meaning(code_c)}).")
        return {"ok": True, "code": code_c, "cmd": cmd, "accepted": False}
    except Exception as e:
        publish(f"⚠️ run_command error: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}


# ───────────────────────── self-test (NO real network calls) ───────────
def _mask(o):
    """Redact secret-bearing keys before printing in the CLI self-test, so a taskId / car_token /
    token never lands in stdout (which HA would capture on the subprocess path)."""
    _SECRET = {"token", "car_token", "carToken", "taskId", "task_id",
               "access_token", "refresh_token", "userToken", "password", "vin"}
    if isinstance(o, dict):
        return {k: ("***" if k in _SECRET else _mask(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_mask(x) for x in o]
    return o


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "selftest"

    if arg == "diagnose":
        # PHASE A LIVE (read-only) — the user runs it when they give the OK.
        pub = lambda t: print("  STATUS:", t)
        print(json.dumps(diagnose(pub), ensure_ascii=False, indent=2))
        sys.exit(0)

    if arg == "command":
        # PHASE B LIVE (ACTIVE) — requires env OMODA_CONFIRM=1 to avoid accidental runs.
        if os.environ.get("OMODA_CONFIRM") != "1":
            print("REFUSED: PHASE B is active. Re-run with OMODA_CONFIRM=1 and with the car awake.")
            sys.exit(2)
        cmd = sys.argv[2] if len(sys.argv) > 2 else "remoteStart"
        pub = lambda t: print("  STATUS:", str(t)[:120])
        print(json.dumps(_mask(run_command(pub, cmd=cmd)), ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── default: OFFLINE self-test with mocks (no network) ──
    pub = lambda t: print("  STATUS:", str(t)[:120])

    print("== TEST find_our_vehicle: car_token present in controlCarList ==")
    mock_q = {"code": "000000", "data": {"controlCarList": [
        {"vin": "VIN_PLACEHOLDER", "authorizeType": 2, "token": "CARTOK123", "defaultFlag": 1},
        {"vin": "OTHER", "authorizeType": 0}]}}
    print("  ->", {k: v for k, v in find_our_vehicle(mock_q).items() if k != "item"})

    print("== TEST find_our_vehicle: VIN only in authorized, without token ==")
    mock_q2 = {"code": "000000", "data": {"controlCarList": [],
        "authorizedControlCarList": [{"vin": "VIN_PLACEHOLDER", "authorizeType": 0}]}}
    print("  ->", {k: v for k, v in find_our_vehicle(mock_q2).items() if k != "item"})

    print("== TEST find_our_vehicle: VIN absent ==")
    print("  ->", {k: v for k, v in find_our_vehicle({"code": "000000", "data": {"controlCarList": []}}).items() if k != "item"})

    # NB: the mocks must be assigned to the globals of THIS module (__main__), which is what
    # diagnose()/run_command() resolve at runtime — not to a second `import`.
    print("== TEST diagnose (mock, hypothesis B) ==")
    W._bff_login = lambda: ("FAKE_UT", "FAKE_TUSERID")
    get_tuser_id = lambda user_id=None: (200, {"code": "000000", "data": "FAKE_TUSERID"})
    query_list   = lambda: (200, mock_q)
    print("  ->", diagnose(pub))

    print("== TEST diagnose (mock, hypothesis A: VIN present, no token) ==")
    query_list = lambda: (200, mock_q2)
    print("  ->", diagnose(pub))

    print("== TEST run_command blocked if no car_token (no command network) ==")
    query_list = lambda: (200, mock_q2)
    print("  ->", _mask(run_command(pub, cmd="remoteStart", is_awake=lambda: True)))

    print("== TEST run_command full flow (mock, car_token present) ==")
    query_list      = lambda: (200, mock_q)
    set_vec_default = lambda vin=None: (200, {"code": "000000"})
    check_password  = lambda tuser_id, pin=None, vin=None, scene=2: (200, {"code": "000000", "data": {"taskId": "TASK99"}}, "TASK99")
    sent = {}
    def fake_send(cmd, car_token, vin=None, tuser_id=None, task_id=None, extra_body=None):
        sent.update(cmd=cmd, car_token=car_token, task_id=task_id)
        return 200, {"code": "A00079"}
    send_command = fake_send
    print("  ->", _mask(run_command(pub, cmd="remoteStart", is_awake=lambda: True)))
    print("     (command sent, car_token present =", bool(sent.get("car_token")), ", taskId present =", bool(sent.get("task_id")), ")")

    print("\nOK self-test finished (no real network calls).")
