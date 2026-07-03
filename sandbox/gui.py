#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py — simple Streamlit GUI for the OMODA / Jaecoo API sandbox.

Same idea as omoda_sandbox.py (reuses the integration's real auth/signing from
`custom_components/omoda_jaecoo/core/`, outside Home Assistant) but with a point-and-click
UI: sign in, see live status, and fire any command the app supports.

Run:  streamlit run sandbox/gui.py
Config + minted token live OUTSIDE the repo (~/.omoda_jaecoo_sandbox), shared with the CLI.
"""
import json
import os
import sys

import streamlit as st

# ── locate core/ + isolated data dir (identical to the CLI) ──────────────────
SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SANDBOX_DIR)
CORE_DIR = os.path.join(REPO_ROOT, "custom_components", "omoda_jaecoo", "core")
DATA_DIR = os.environ.get("OMODA_SANDBOX_HOME") or os.path.join(
    os.path.expanduser("~"), ".omoda_jaecoo_sandbox")
os.makedirs(DATA_DIR, exist_ok=True)
ENV_FILE = os.path.join(DATA_DIR, "omoda_sandbox.env")

CONFIG_KEYS = [
    ("OMODA_EMAIL", ""), ("VIN", ""), ("OMODA_PIN", ""),
    ("OMODA_BFF", "https://legend-oj.omodaauto.nl/api"),
    ("TSP_HOST", "https://tspconsole-eu.cheryinternational.com"),
    ("OMODA_TENANT_CODE", "300006"), ("OMODA_COUNTRY_ID", "1"),
    ("OMODA_DEPT_ID", "39"), ("TSP_APP_ID", "eu-1"), ("OMODA_LANGUAGE", "en-GB"),
]


def _load_env():
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    for k, d in CONFIG_KEYS:
        if not os.environ.get(k) and d:
            os.environ[k] = d
    os.environ.setdefault("OMODA_TOKEN_PATH", os.path.join(DATA_DIR, "token.json"))


def _save_env():
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        for k, _d in CONFIG_KEYS:
            fh.write(f"{k}={os.environ.get(k, '')}\n")
        fh.write(f"OMODA_TOKEN_PATH={os.environ.get('OMODA_TOKEN_PATH', '')}\n")


_load_env()
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import requests                     # noqa: E402
import omoda_auth as A              # noqa: E402
import tsp_sign as S                # noqa: E402
import wake as W                    # noqa: E402
import commands as CMD              # noqa: E402
import codes as CODES               # noqa: E402
import login_omoda as LOGIN         # noqa: E402
import prova_token as MINT          # noqa: E402
import time                         # noqa: E402


def _apply_env():
    """Push edited config into the already-imported core modules (they snapshot env)."""
    W.VIN = CMD.VIN = os.environ.get("VIN", "")
    W.TSP_HOST = CMD.TSP_HOST = os.environ.get("TSP_HOST", W.TSP_HOST)
    CMD.PIN = os.environ.get("OMODA_PIN", "")
    LOGIN.BFF = A.BFF = os.environ.get("OMODA_BFF", A.BFF)


# ── data-returning helpers (no printing) ─────────────────────────────────────
def discover_vin():
    try:
        access = W._access_token()
    except Exception:
        return None, "No token yet — sign in first."
    extra = {"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    try:
        r = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList", data="{}",
                          headers=A.headers_post("/tsp/v1/app/vmc/queryList", extra=extra), timeout=25)
        j = r.json()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    lst = j.get("data") if isinstance(j, dict) else None
    vins = [str(v["vin"]) for v in lst if isinstance(v, dict) and v.get("vin")] if isinstance(lst, list) else []
    return (vins, j)


def tsp_read(path, body):
    ut, _ = W._bff_login()
    if not ut:
        return None, {"error": "no session — sign in"}
    try:
        return W._signed_post(ut, path, dict(body))
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


def bff_post(path, body):
    try:
        access = W._access_token()
    except Exception:
        return None, {"error": "no token"}
    extra = {"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    try:
        r = requests.post(A.BFF + path, data=json.dumps(body),
                          headers=A.headers_post(path, extra=extra), timeout=25)
        return r.status_code, r.json()
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


def signed_command(endpoint=None, path=None, body=None):
    """Arbitrary vehicle command via the real taskId + sign path. Returns (status, json)."""
    _apply_env()
    vin = os.environ.get("VIN", "")
    token, tuid = W._bff_login()
    if not token:
        return None, {"error": "no session — sign in"}
    taskid, src = CMD.get_taskid(tuid, emit=lambda m: None)
    if not taskid:
        return None, {"error": "no taskId (set PIN; checkPassword must succeed)"}
    ts = int(time.time() * 1000)
    b = dict(body or {})
    b.update({"clientType": "1", "seq": f"{vin}-{ts}", "taskId": taskid, "vin": vin})
    m = S.sign_body(b, ts)
    headers = {"Authorization": token, "timestamp": str(ts),
               "Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}
    url = CMD.TSP_HOST + (path or ("/asc/vehicleControl/" + endpoint))
    try:
        r = requests.post(url, data=json.dumps(m, separators=(",", ":")).encode(), headers=headers, timeout=25)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_raw": r.text[:400]}
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


def send_catalog(key, params=None):
    """Send a command from the catalog (reuses CMD.send, which mints taskId + signs)."""
    _apply_env()
    logs = []
    try:
        result = CMD.send(key, emit=logs.append, params=params)
    except Exception as e:
        result = f"error: {type(e).__name__}: {e}"
    return result, logs


def decode(code):
    return CODES.meaning(code, default=f"code {code}") if code is not None else "—"


# ── UI ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="OMODA / Jaecoo Sandbox", page_icon="🚗", layout="wide")
st.title("🚗 OMODA / Jaecoo — API Sandbox")
st.caption("Point-and-click access to the vehicle API, outside Home Assistant. Raw JSON on tap.")

# ---- sidebar: config + auth ----
with st.sidebar:
    st.header("Configuration")
    for k, _d in CONFIG_KEYS:
        val = st.text_input(k, value=os.environ.get(k, ""),
                            type="password" if k == "OMODA_PIN" else "default")
        os.environ[k] = val
    if st.button("💾 Save config"):
        _save_env(); _apply_env(); st.success("Saved.")
    _apply_env()

    st.divider()
    st.header("Sign in")
    if st.button("① Send OTP to email"):
        with st.spinner("Solving captcha + sending code…"):
            ok = LOGIN.invia(os.environ.get("OMODA_EMAIL", ""))
        st.success("Code sent — check email.") if ok else st.error("Failed to send OTP.")
    otp = st.text_input("OTP code")
    if st.button("② Confirm OTP → mint token"):
        with st.spinner("Minting token…"):
            try:
                status, j, tok = MINT.call(os.environ.get("OMODA_EMAIL", ""), otp.strip(),
                                           secret="prod", emailfmt="module", codefmt="plain", verbose=False)
            except Exception as e:
                status, j, tok = None, {"error": str(e)}, None
        if tok:
            path = os.environ["OMODA_TOKEN_PATH"]
            json.dump(j, open(path, "w", encoding="utf-8"), indent=2)
            vins, _ = discover_vin()
            if vins and not os.environ.get("VIN"):
                os.environ["VIN"] = vins[0]; _save_env(); _apply_env()
            st.success(f"Signed in ✅  VIN(s): {', '.join(vins) if vins else '—'}")
        else:
            st.error("OTP rejected (wrong/expired?).")

    st.divider()
    # session status
    try:
        ut, _tu = W._bff_login()
        st.success("Session active ✅") if ut else st.warning("Session expired — sign in.")
    except Exception:
        st.info("Not signed in.")
    st.caption(f"VIN: {os.environ.get('VIN') or '—'}")

# ---- main tabs ----
tab_status, tab_ctrl, tab_win, tab_adv = st.tabs(
    ["📊 Status", "🎛️ Controls", "🪟 Windows", "🔧 Advanced"])

with tab_status:
    if st.button("🔄 Refresh live data"):
        st.session_state["rt"] = tsp_read("/asr/manager/realtime", {"vin": os.environ.get("VIN", "")})
        st.session_state["loc"] = tsp_read("/asc/vehicleControl/queryVehicleLocation", {"vin": os.environ.get("VIN", "")})
    rt = st.session_state.get("rt")
    if rt:
        _st, j = rt
        body = (j.get("body") or j.get("data") or {}) if isinstance(j, dict) else {}
        if body:
            c = st.columns(4)
            c[0].metric("Battery", f"{body.get('dumpEnergy', '—')}%")
            c[1].metric("Range (km)", body.get("dynamicPureElectricRange", body.get("pureElectricRange", "—")))
            c[2].metric("Odometer (km)", body.get("odometer", "—"))
            c[3].metric("Charging", {"0": "No", "1": "Yes", "2": "Done"}.get(str(body.get("chargeState")), "—"))
            st.subheader("Openings")
            doors = {"Front L": "frontLeftDoor", "Front R": "frontRightDoor", "Rear L": "backLeftDoor",
                     "Rear R": "backRightDoor", "Trunk": "trunkDoor", "Lock": "doorLock"}
            wins = {"Front L": "frontLeftWindowState", "Front R": "frontRightWindowState",
                    "Rear L": "backLeftWindowState", "Rear R": "backRightWindowState", "Sunroof": "sunroofState"}
            cd, cw = st.columns(2)
            with cd:
                st.markdown("**Doors / lock**")
                for name, key in doors.items():
                    v = body.get(key)
                    if key == "doorLock":
                        st.write(f"{name}: {'🔒 Locked' if str(v) in ('0','0.0') else '🔓 Unlocked'}")
                    else:
                        st.write(f"{name}: {'🟠 Open' if str(v) not in ('0','0.0','None','') else '🟢 Closed'}")
            with cw:
                st.markdown("**Windows**")
                for name, key in wins.items():
                    v = body.get(key)
                    st.write(f"{name}: {'🟠 Open' if str(v) not in ('0','0.0','None','') else '🟢 Closed'}")
        with st.expander("Raw realtime JSON"):
            st.json(j)
    if st.session_state.get("loc"):
        with st.expander("Raw location JSON"):
            st.json(st.session_state["loc"][1])

with tab_ctrl:
    st.caption("⚠️ These ACTUATE the real vehicle.")
    groups = {}
    for key, spec in CMD.COMMANDS:
        groups.setdefault(spec.get("group", "Other"), []).append((key, spec))
    for gname, cmds in groups.items():
        st.subheader(gname)
        cols = st.columns(3)
        for i, (key, spec) in enumerate(cmds):
            if cols[i % 3].button(spec["name"], key=f"cmd_{key}"):
                with st.spinner(f"Sending {spec['name']}…"):
                    result, logs = send_catalog(key)
                st.info(result)

with tab_win:
    st.subheader("All windows")
    c = st.columns(3)
    if c[0].button("Open all"):
        st.info(send_catalog("finestrini_apri")[0])
    if c[1].button("Ventilate"):
        st.info(send_catalog("ventilate_windows")[0])
    if c[2].button("Close all"):
        st.info(send_catalog("finestrini_chiudi")[0])

    st.divider()
    st.subheader("Individual window — experiment")
    st.caption("The app only exposes all-windows control; this tries candidate per-window bodies "
               "on windowControl. Look for code 000000 / A00079 (accepted) vs A00567 (bad params).")
    which = st.selectbox("Window", ["front left", "front right", "rear left", "rear right"])
    action = st.radio("Action", ["open (1)", "close (0)"], horizontal=True)
    ct = "1" if action.startswith("open") else "0"
    # candidate field names per window position (front-left etc.)
    pos = {"front left": ("fl", "frontLeft", "1"), "front right": ("fr", "frontRight", "2"),
           "rear left": ("bl", "backLeft", "3"), "rear right": ("br", "backRight", "4")}[which]
    candidates = [
        {"controlType": ct, "windowType": pos[2]},
        {"controlType": ct, "position": pos[2]},
        {f"{pos[0]}Window": ct},
        {f"{pos[1]}Window": ct},
        {f"{pos[1]}WindowControl": ct},
        {"controlType": ct, "windowLocation": pos[2]},
    ]
    if st.button("🧪 Try candidate per-window bodies"):
        rows = []
        for body in candidates:
            status, j = signed_command(endpoint="windowControl", body=body)
            code = j.get("code") if isinstance(j, dict) else None
            rows.append({"body": json.dumps(body), "http": status, "code": code, "meaning": decode(code)})
            time.sleep(1.0)
        st.table(rows)
        st.caption("If one shows code 000000/A00079, per-window control works with that body — tell the "
                   "developer and it can be added to the integration.")

with tab_adv:
    st.subheader("Raw request")
    method = st.radio("Method", ["POST", "GET"], horizontal=True)
    layer = st.radio("Layer", ["TSP (signed)", "BFF (bearer)"], horizontal=True)
    path = st.text_input("Path", "/asr/manager/realtime")
    rawbody = st.text_area("JSON body", '{"vin": "%s"}' % os.environ.get("VIN", ""))
    if st.button("Send raw"):
        try:
            body = json.loads(rawbody) if rawbody.strip() else {}
        except json.JSONDecodeError as e:
            st.error(f"Bad JSON: {e}"); body = None
        if body is not None:
            if method == "GET":
                try:
                    access = W._access_token()
                    r = requests.get(A.BFF + path, headers=A.headers_post(path, extra={
                        "Authorization": f"Bearer {access}", "Accept": "application/json"}), timeout=25)
                    st.json(r.json())
                except Exception as e:
                    st.error(str(e))
            elif layer.startswith("TSP"):
                st.json(tsp_read(path, body)[1])
            else:
                st.json(bff_post(path, body)[1])

    st.divider()
    st.subheader("Generic signed command")
    ep = st.text_input("Endpoint (under /asc/vehicleControl/) or full /path", "chargeDepthControl")
    gbody = st.text_area("Body JSON", '{"chargeSoc": 80}', key="gbody")
    if st.button("Send generic command"):
        try:
            b = json.loads(gbody) if gbody.strip() else {}
            p = ep if ep.startswith("/") else None
            status, j = signed_command(endpoint=None if p else ep, path=p, body=b)
            st.json(j)
            code = j.get("code") if isinstance(j, dict) else None
            if code is not None:
                st.caption(f"code {code} → {decode(code)}")
        except json.JSONDecodeError as e:
            st.error(f"Bad JSON: {e}")

    st.divider()
    if st.button("Fetch error-code dictionary (allErrorCodes)"):
        try:
            access = W._access_token()
            r = requests.get(A.BFF + "/tsp/dictConfig/c/allErrorCodes",
                             headers=A.headers_post("/tsp/dictConfig/c/allErrorCodes", extra={
                                 "Authorization": f"Bearer {access}", "Accept": "application/json"}), timeout=25)
            st.json(r.json())
        except Exception as e:
            st.error(str(e))
