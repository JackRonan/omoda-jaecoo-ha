#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wake.py — "Wake car" Omoda / Jaecoo: EXACT replica of the official app's flow
          (1× smsAwaken → poll realtime/location), meant to be invoked
          by the Home Assistant button exposed by ha_bridge.py.

Flow (verified against the real code, SESSIONE11_REPORT.md):
  1) bff_login()  : token.json (access_token) → POST {BFF}/tsp/v1/app/auth/login → userToken/tUserId
  2) smsAwaken    : POST {TSP}/asc/vehicleControl/smsAwaken {vin}, signed with tsp_sign
                    code "000000" = wake accepted; "A07312" = rate-limit/quota SMS-wake.
  3) poll ~60s    : /asr/manager/realtime + /asc/vehicleControl/queryVehicleLocation every 5s.
                    In parallel the bridge's MQTT listener catches the 5A02 → is_awake() becomes True.

⚠️  smsAwaken HAS A REAL RATE-LIMIT. The button must NOT be hammered:
    - `do_wake` respects a COOLDOWN (default 300s) between two smsAwaken actually sent;
    - only one `do_wake` at a time (anti double-tap lock).

Strictly personal use (the user's car/account). Do NOT publish the token/cert.
"""
import os, sys, json, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import requests
import omoda_auth as A
import tsp_sign as S
import codes

# C1: serializes the token refreshes. keep-alive (coordinator) and a command can
# trigger _refresh_token() together: without a lock both would use the SAME
# refresh_token, Chery rotates it on every use → the second refresh invalidates the
# first one's token and the session drops. The lock + double-check (below) avoids the double refresh.
_TOKEN_LOCK = threading.Lock()

TSP_HOST   = os.environ.get("TSP_HOST", "https://tspconsole-eu.cheryinternational.com")   # region (default EU)
VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: see omoda_jaecoo.env.example


def _token_path() -> str:
    """Path of the canonical token, re-read from env on EVERY access (NOT frozen at import).

    Needed because core/ is imported only once in the HA process but with
    different contexts: the config flow mints the token in a 'pending' path, the runtime
    uses the per-VIN one. Reading TOKEN_PATH at import-time would give the wrong path
    (e.g. the post-OTP verification was reading the old, already-invalidated per-VIN token)."""
    return os.environ.get("OMODA_TOKEN_PATH") or os.path.join(HERE, "token.json")


# Compat: some legacy calls use wake.TOKEN_PATH as the initial value.
TOKEN_PATH = _token_path()
# persistent cooldown state (survives bridge restarts)
WAKE_STATE = os.environ.get("OMODA_WAKE_STATE", os.path.join(HERE, "data", "wake_state.json"))

COOLDOWN_S = int(os.environ.get("WAKE_COOLDOWN", "300"))   # min seconds between two smsAwaken sent
POLL_N     = int(os.environ.get("WAKE_POLL_N", "12"))      # no. of poll cycles
POLL_EVERY = int(os.environ.get("WAKE_POLL_EVERY", "5"))   # seconds between one poll and the next

_BUSY = threading.Lock()   # only one wake at a time


# ───────────────────────── cooldown persistence ────────────────────────────────
def _load_last_sms() -> float:
    try:
        with open(WAKE_STATE, "r", encoding="utf-8") as f:
            return float(json.load(f).get("last_sms_ts", 0.0))
    except Exception:
        return 0.0

def _save_last_sms(ts: float):
    try:
        os.makedirs(os.path.dirname(WAKE_STATE), exist_ok=True)
        with open(WAKE_STATE, "w", encoding="utf-8") as f:
            json.dump({"last_sms_ts": ts}, f)
    except Exception:
        pass


# ───────────────────────── REST calls (patchable in tests) ──────────────────
def _access_token():
    """Reads the access_token from token.json. Defensive: handles both {data:{...}} and
    the flat format, and does not blow up with KeyError if the field is missing (returns None).
    Single point for reading the token: commands/provision use this."""
    with open(_token_path()) as fh:
        tok = json.load(fh)
    if not isinstance(tok, dict):
        return None
    d = tok.get("data", tok)
    if isinstance(d, dict) and d.get("access_token"):
        return d["access_token"]
    return tok.get("access_token")

def _refresh_token() -> bool:
    """Renews the access_token with the `refresh_token` grant (NO OTP) and rewrites token.json.
    Same endpoint/headers as the OTP login (login_otp.py), which is NOT behind the Aliyun firewall.
    Returns True if it obtained a new access_token, False otherwise (e.g. expired refresh → OTP needed).

    C1: protected by `_TOKEN_LOCK` with double-check. I snapshot the access_token the
    caller saw (BEFORE the lock); inside the lock I re-read token.json: if on
    disk the access_token has already changed, another thread has already renewed → I do NOT redo
    the refresh (redoing it would burn the new refresh_token and invalidate the session)."""
    # pre-lock snapshot: the token the caller considered expired
    try:
        with open(_token_path()) as fh:
            tok0 = json.load(fh)
    except Exception:
        return False
    seen_at = (tok0.get("data", tok0) or {}).get("access_token") if isinstance(tok0, dict) else None

    with _TOKEN_LOCK:
        # double-check INSIDE the lock: re-read the current state of the file
        try:
            with open(_token_path()) as fh:
                tok = json.load(fh)
        except Exception:
            return False
        d = (tok.get("data", tok) or {}) if isinstance(tok, dict) else {}
        cur_at = d.get("access_token")
        if seen_at and cur_at and cur_at != seen_at:
            # already renewed by another thread: the token on disk is valid, don't touch it
            return True
        rt = d.get("refresh_token")
        if not rt:
            return False
        # Verified recipe (= identical to the OTP login in prova_token.py): application signature
        # via headers_post + parameters in QUERY STRING. Without the signature the gateway responds 428.
        TP = "/auth/oauth2/token"
        params = {"grant_type": "refresh_token", "refresh_token": rt, "scope": "server"}
        try:
            H = A.headers_post(TP, secret=A.SIGN_SECRET)
            r = requests.post(A.BFF + TP, params=params, headers=H, timeout=20)
            j = r.json()
        except Exception:
            return False
        if not isinstance(j, dict):
            return False
        at = j.get("access_token") or (j.get("data") or {}).get("access_token")
        if not at:
            return False
        # atomic write: new token to a temp file then rename (token.json never corrupted)
        try:
            path = _token_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            return False
        return True

def _bff_login(_allow_refresh=True):
    """Returns (userToken, tUserId). Raises on network error; (None,None) if rejected.
    If the session has expired it attempts ONE automatic refresh_token (without OTP) and retries once."""
    tok = _access_token()
    H = A.headers_post("/tsp/v1/app/auth/login", extra={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*"})
    r = requests.post(A.BFF + "/tsp/v1/app/auth/login",
                      data=json.dumps({"channelId": A.CHANNEL_ID}), headers=H, timeout=20)
    # expired token/424: the BFF may return a body whose TOP-LEVEL is a string
    # (not a dict) → r.json() is a str and .get would blow up. Treat everything as an invalid session.
    try:
        j = r.json()
    except Exception:
        return None, None
    d = j.get("data", {}) if isinstance(j, dict) else None
    if not isinstance(d, dict):
        # expired session: try ONE automatic token renewal and retry only once
        if _allow_refresh and _refresh_token():
            return _bff_login(_allow_refresh=False)
        return None, None
    return d.get("userToken"), d.get("tUserId")

def _signed_post(ut: str, path: str, params: dict):
    ts = int(time.time() * 1000)
    body = S.sign_body(dict(params), ts)
    headers = S.auth_headers(ut, ts)
    headers.update({"Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": "okhttp/4.9.0", "version": A.APP_VERSION, "agent": "android"})
    r = requests.post(TSP_HOST + path, data=json.dumps(body), headers=headers, timeout=25)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:300]}

def _code_of(j):
    return j.get("code") if isinstance(j, dict) else j

def _payload(j):
    """Useful payload of the tspconsole response: under "data" on some endpoints and
    under "body" on others (e.g. /asr/manager/realtime → "body" with 84 fields). Returns
    the first non-empty dict, or None."""
    if not isinstance(j, dict):
        return None
    for k in ("data", "body"):
        v = j.get(k)
        if isinstance(v, dict) and v:
            return v
    return None


def _has_live_data(j):
    return _payload(j) is not None


# ───────────────────────── button orchestration ──────────────────────────
def do_wake(publish, is_awake=None, send_sms=True):
    """Runs the wake flow and reports the status (already-readable strings) via `publish`.

      publish(text)  -> callback that writes the status to HA + monitor (called multiple times)
      is_awake()     -> optional callback: True if the bridge is already receiving MQTT events (car awake)
      send_sms       -> if False does NOT actually send smsAwaken (only for test/diagnostics)

    Returns a summary dict {ok, online, code, ...}. Never raises: every error → status.
    """
    if not _BUSY.acquire(blocking=False):
        publish("A wake request is already in progress. Please wait…")
        return {"ok": False, "reason": "busy"}
    try:
        return _do_wake_inner(publish, is_awake, send_sms)
    except Exception as e:
        publish(f"Wake request failed: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        _BUSY.release()


def _do_wake_inner(publish, is_awake, send_sms):
    now = time.time()

    # 0) anti rate-limit cooldown (only if we will actually send the SMS)
    if send_sms:
        last = _load_last_sms()
        wait = COOLDOWN_S - (now - last)
        if last and wait > 0:
            mm, ss = divmod(int(wait), 60)
            publish(f"Please wait {mm}m {ss:02d}s before waking the vehicle again (rate limit).")
            return {"ok": False, "reason": "cooldown", "wait_s": int(wait)}

    # if the car is already publishing on MQTT, it is already awake: no SMS
    if is_awake and is_awake():
        publish("The vehicle is already awake — no wake needed.")
        return {"ok": True, "online": True, "reason": "already_awake"}

    # 1) BFF login → userToken
    publish("Signing in…")
    ut, tu = _bff_login()
    if not ut:
        publish("Session expired — please re-authenticate (this happens if the official app is open).")
        return {"ok": False, "reason": "no_usertoken"}

    # 2) smsAwaken (only once)
    code = None
    if send_sms:
        sc, j = _signed_post(ut, "/asc/vehicleControl/smsAwaken", {"vin": VIN})
        code = _code_of(j)
        _save_last_sms(time.time())     # record IMMEDIATELY for the cooldown, even on error
        if str(code) in ("000000", "A00079"):
            publish("Wake request sent — waiting for the vehicle to connect…")
        elif str(code) == "A07312":
            publish("Wake rate-limited — the vehicle is refusing wake requests right now. Please try again later.")
            return {"ok": False, "online": False, "code": code, "reason": "rate_limit"}
        else:
            publish(f"Wake not accepted ({code}: {codes.meaning(code)}). Continuing to listen…")
    else:
        publish("(test) wake request not sent; polling only.")

    # 3) poll realtime/location + MQTT listening, for ~POLL_N*POLL_EVERY seconds
    for i in range(POLL_N):
        if is_awake and is_awake():
            publish("Vehicle online — receiving live data.")
            return {"ok": True, "online": True, "code": code, "via": "mqtt"}
        sc1, j1 = _signed_post(ut, "/asr/manager/realtime", {"vin": VIN})
        sc2, j2 = _signed_post(ut, "/asc/vehicleControl/queryVehicleLocation", {"vin": VIN})
        if _has_live_data(j1) or _has_live_data(j2):
            publish("Vehicle online — live data received.")
            return {"ok": True, "online": True, "code": code, "via": "rest",
                    "data": _payload(j1) or _payload(j2)}
        secs_left = (POLL_N - i - 1) * POLL_EVERY
        publish(f"Waiting for the vehicle to wake — ~{secs_left}s remaining…")
        time.sleep(POLL_EVERY)

    publish("The vehicle is still asleep. Try again after it has been driven recently or has a good signal.")
    return {"ok": True, "online": False, "code": code, "reason": "still_asleep"}


# ───────────────────────── self-test (NO network calls) ─────────────────
if __name__ == "__main__":
    # Test of the orchestration WITHOUT touching the network or sending smsAwaken.
    import wake as W
    msgs = []
    pub = lambda t: (msgs.append(t), print("  STATUS:", t))[1]

    print("== TEST 1: car already awake (is_awake=True) → no SMS ==")
    msgs.clear()
    print("  ->", W.do_wake(pub, is_awake=lambda: True, send_sms=True))

    print("== TEST 2: cooldown active ==")
    msgs.clear()
    W._load_last_sms = lambda: time.time() - 10   # last SMS 10s ago
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))

    print("== TEST 3: full MOCK flow (no network): smsAwaken=000000, then MQTT awake ==")
    msgs.clear()
    W._load_last_sms = lambda: 0.0
    W._save_last_sms = lambda ts: None
    W._bff_login = lambda: ("FAKE_USERTOKEN", "FAKE_TUSERID")
    calls = {"n": 0}
    def fake_post(ut, path, params):
        calls["n"] += 1
        if path.endswith("smsAwaken"):
            return 200, {"code": "000000"}
        return 200, {"code": "A07900"}   # realtime/location still offline
    W._signed_post = fake_post
    awake_state = {"v": False}
    def fake_awake():
        # becomes awake after the 2nd poll round
        awake_state["v"] = calls["n"] >= 3
        return awake_state["v"]
    W.POLL_EVERY = 0    # fast test
    print("  ->", W.do_wake(pub, is_awake=fake_awake, send_sms=True))

    print("== TEST 4: expired token (bff_login → None) ==")
    msgs.clear()
    W._bff_login = lambda: (None, None)
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))

    print("== TEST 5: rate-limit A07312 ==")
    msgs.clear()
    W._bff_login = lambda: ("FAKE", "1")
    W._signed_post = lambda ut, path, params: (200, {"code": "A07312"})
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))
    print("\nOK self-test finished (no real network calls).")
