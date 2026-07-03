#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py — simple Streamlit GUI for the OMODA / Jaecoo API sandbox.

Reuses the integration's real auth/signing from `custom_components/omoda_jaecoo/core/`
(outside Home Assistant) behind a point-and-click UI: sign in, see live status, fire any
command the app supports, and experiment with undocumented ones (e.g. per-window control).

Run:  python -m streamlit run gui.py
Config + minted token live OUTSIDE the repo (~/.omoda_jaecoo_sandbox), shared with the CLI.
"""
import json
import os
import re
import sys
import time

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
_ADVANCED_KEYS = {"OMODA_BFF", "TSP_HOST", "OMODA_TENANT_CODE", "OMODA_COUNTRY_ID",
                  "OMODA_DEPT_ID", "TSP_APP_ID", "OMODA_LANGUAGE"}


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


def _apply_env():
    W.VIN = CMD.VIN = os.environ.get("VIN", "")
    W.TSP_HOST = CMD.TSP_HOST = os.environ.get("TSP_HOST", W.TSP_HOST)
    CMD.PIN = os.environ.get("OMODA_PIN", "")
    LOGIN.BFF = A.BFF = os.environ.get("OMODA_BFF", A.BFF)


# ── data-returning helpers (no printing) ─────────────────────────────────────
def session_ok():
    try:
        ut, _ = W._bff_login()
        return bool(ut)
    except Exception:
        return False


def discover_vin():
    try:
        access = W._access_token()
    except Exception:
        return [], None
    extra = {"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    try:
        j = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList", data="{}",
                          headers=A.headers_post("/tsp/v1/app/vmc/queryList", extra=extra), timeout=25).json()
    except Exception:
        return [], None
    lst = j.get("data") if isinstance(j, dict) else None
    vins = [str(v["vin"]) for v in lst if isinstance(v, dict) and v.get("vin")] if isinstance(lst, list) else []
    return vins, j


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


def bff_get(path):
    try:
        access = W._access_token()
    except Exception:
        access = None
    extra = {"Accept": "application/json"}
    if access:
        extra["Authorization"] = f"Bearer {access}"
    try:
        return requests.get(A.BFF + path, headers=A.headers_post(path, extra=extra), timeout=25).json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def signed_command(endpoint=None, path=None, body=None):
    """Arbitrary vehicle command via the real taskId + sign path. Returns (status, json)."""
    _apply_env()
    vin = os.environ.get("VIN", "")
    token, tuid = W._bff_login()
    if not token:
        return None, {"error": "no session — sign in"}
    taskid, _src = CMD.get_taskid(tuid, emit=lambda m: None)
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
    _apply_env()
    logs = []
    try:
        return CMD.send(key, emit=logs.append, params=params), logs
    except Exception as e:
        return f"error: {type(e).__name__}: {e}", logs


def decode(code):
    return CODES.meaning(code, default=f"code {code}") if code is not None else "—"


def accepted(code):
    return str(code) in ("000000", "A00079")


def result_banner(msg, code=None):
    if code is not None and accepted(code):
        st.success(f"✅ {msg}")
    elif code is not None:
        st.warning(f"{msg}  —  {code}: {decode(code)}")
    else:
        st.info(msg)


# ── page config + header ─────────────────────────────────────────────────────
st.set_page_config(page_title="OMODA / Jaecoo Sandbox", page_icon="🚗", layout="wide")
_apply_env()
signed = session_ok()

# ── sidebar: sign-in + config ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🚗 OMODA / Jaecoo Sandbox")
    st.success("Signed in") if signed else st.error("Not signed in")
    st.caption(f"VIN: `{os.environ.get('VIN') or '—'}`")

    with st.expander("🔑 Sign in", expanded=not signed):
        os.environ["OMODA_EMAIL"] = st.text_input("Account email", value=os.environ.get("OMODA_EMAIL", ""))
        os.environ["OMODA_PIN"] = st.text_input("Vehicle PIN", value=os.environ.get("OMODA_PIN", ""), type="password")
        if st.button("① Send OTP to email", use_container_width=True):
            with st.spinner("Solving captcha + sending code…"):
                ok = LOGIN.invia(os.environ.get("OMODA_EMAIL", ""))
            st.success("Code sent — check your email.") if ok else st.error("Failed to send OTP.")
        otp = st.text_input("OTP code from email")
        if st.button("② Confirm OTP", type="primary", use_container_width=True):
            with st.spinner("Minting token…"):
                try:
                    _s, j, tok = MINT.call(os.environ.get("OMODA_EMAIL", ""), otp.strip(),
                                           secret="prod", emailfmt="module", codefmt="plain", verbose=False)
                except Exception as e:
                    j, tok = {"error": str(e)}, None
            if tok:
                json.dump(j, open(os.environ["OMODA_TOKEN_PATH"], "w", encoding="utf-8"), indent=2)
                vins, _ = discover_vin()
                if vins and not os.environ.get("VIN"):
                    os.environ["VIN"] = vins[0]
                _save_env()
                st.success(f"Signed in ✅  VIN(s): {', '.join(vins) or '—'}")
                st.rerun()
            else:
                st.error("OTP rejected (wrong/expired?).")

    with st.expander("⚙️ Config", expanded=False):
        os.environ["VIN"] = st.text_input("VIN (auto-discovered)", value=os.environ.get("VIN", ""))
        for k in [k for k, _ in CONFIG_KEYS if k in _ADVANCED_KEYS]:
            os.environ[k] = st.text_input(k, value=os.environ.get(k, ""))
        if st.button("💾 Save config", use_container_width=True):
            _save_env(); _apply_env(); st.toast("Saved.")
    _apply_env()

if not signed:
    st.title("🚗 OMODA / Jaecoo — API Sandbox")
    st.info("👈 Sign in from the sidebar to begin: enter your **email + PIN**, "
            "**Send OTP**, then **Confirm OTP**. The VIN is discovered automatically.")
    st.caption("Reuses the integration's real auth outside Home Assistant. Nothing here changes your HA setup.")
    st.stop()

# ── live vehicle header (metrics bar) ────────────────────────────────────────
if "rt" not in st.session_state:
    st.session_state["rt"] = tsp_read("/asr/manager/realtime", {"vin": os.environ.get("VIN", "")})
rt_status, rt_json = st.session_state["rt"]
_body = (rt_json.get("body") or rt_json.get("data") or {}) if isinstance(rt_json, dict) else {}


def _b(key, default="—"):
    v = _body.get(key)
    return v if v not in (None, "", "None") else default


hcol = st.columns([3, 1, 1, 1, 1, 1])
hcol[0].markdown("### OMODA / Jaecoo")
hcol[1].metric("Battery", f"{_b('dumpEnergy')}%")
hcol[2].metric("Range km", _b("dynamicPureElectricRange", _b("pureElectricRange")))
hcol[3].metric("Odometer", _b("odometer"))
hcol[4].metric("Lock", "🔒" if str(_b("doorLock")) in ("0", "0.0") else "🔓")
hcol[5].metric("Charging", {"0": "No", "1": "Yes", "2": "Done"}.get(str(_b("chargeState")), "—"))
if st.button("🔄 Refresh live data"):
    st.session_state["rt"] = tsp_read("/asr/manager/realtime", {"vin": os.environ.get("VIN", "")})
    st.rerun()
st.divider()

# ── tabs ─────────────────────────────────────────────────────────────────────
tab_status, tab_climate, tab_access, tab_charge, tab_win, tab_adv = st.tabs(
    ["📊 Status", "❄️ Climate", "🚪 Access", "🔋 Charging", "🪟 Windows & Roof", "🔧 Advanced"])


def fire(key, params=None, label=None):
    with st.spinner(f"Sending {label or key}…"):
        res, _ = send_catalog(key, params=params)
    st.toast(res)
    st.session_state["last_result"] = res


def group(name):
    return [(k, v) for k, v in CMD.COMMANDS if v.get("group") == name]


def _pair(cmds):
    """Split a group into On/Off pairs + singles, matched by normalised name."""
    by = {}
    for k, v in cmds:
        name = v.get("name") or k
        lbl = re.sub(r"\s+(ON|OFF)$", "", name, flags=re.I).strip()
        d = by.setdefault(lbl, {"on": None, "off": None})
        (d.__setitem__("off", k) if name.strip().upper().endswith("OFF") else d.__setitem__("on", k))
    pairs, singles = [], []
    for lbl, d in by.items():
        if d["on"] and d["off"]:
            pairs.append((lbl, d["on"], d["off"]))
        else:
            singles.append((lbl, d["on"] or d["off"]))
    return pairs, singles


def toggle_rows(cmds, skip=()):
    """Render each On/Off pair as one labelled row with On + Off buttons."""
    pairs, singles = _pair(cmds)
    for lbl, on_k, off_k in pairs:
        if on_k in skip:
            continue
        c = st.columns([3, 1, 1])
        c[0].markdown(f"**{lbl}**")
        if c[1].button("On", key=f"on_{on_k}", use_container_width=True):
            fire(on_k, label=f"{lbl} on")
        if c[2].button("Off", key=f"off_{off_k}", use_container_width=True):
            fire(off_k, label=f"{lbl} off")
    for lbl, k in singles:
        if st.button(lbl, key=f"one_{k}", use_container_width=True):
            fire(k, label=lbl)


with tab_status:
    if _body:
        st.subheader("Openings")
        doors = [("Front left door", "frontLeftDoor"), ("Front right door", "frontRightDoor"),
                 ("Rear left door", "backLeftDoor"), ("Rear right door", "backRightDoor"),
                 ("Trunk", "trunkDoor"), ("Hood", "hood")]
        wins = [("Front left window", "frontLeftWindowState"), ("Front right window", "frontRightWindowState"),
                ("Rear left window", "backLeftWindowState"), ("Rear right window", "backRightWindowState"),
                ("Sunroof", "sunroofState")]
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Doors**")
            for name, k in doors:
                st.write(f"{name}: {'🟠 Open' if str(_b(k, '0')) not in ('0', '0.0') else '🟢 Closed'}")
        with cB:
            st.markdown("**Windows / roof**")
            for name, k in wins:
                st.write(f"{name}: {'🟠 Open' if str(_b(k, '0')) not in ('0', '0.0') else '🟢 Closed'}")
        with st.expander("Raw realtime JSON"):
            st.json(rt_json)
    else:
        st.warning("No live data — the car may be asleep. Press **Refresh live data** (a recently-driven "
                   "or charging car reports more).")

with tab_climate:
    st.caption("⚠️ Actuates the real vehicle. Comfort commands usually work only when the car is awake.")
    st.markdown("**Cabin climate**")
    c = st.columns([2, 1, 1])
    temp = c[0].slider("Target °C", 16.0, 32.0, 21.0, 0.5)
    if c[1].button("Climate On", type="primary", use_container_width=True):
        fire("clima_on", params={"temperature": f"{temp:.1f}"}, label=f"Climate on @ {temp:.1f}°C")
    if c[2].button("Climate Off", use_container_width=True):
        fire("clima_off", label="Climate off")
    d = st.columns(2)
    if d[0].button("❄️ Cool down all", use_container_width=True):
        fire("climate_cool_on", label="Cool down all")
    if d[1].button("🔥 Heat up all", use_container_width=True):
        fire("climate_heat_on", label="Heat up all")
    st.divider()
    st.markdown("**Defrost / heating**")
    toggle_rows(group("Climate"), skip=("clima_on", "climate_cool_on", "climate_heat_on"))

with tab_access:
    st.markdown("**Doors & trunk**")
    toggle_rows(group("Access"))
    st.divider()
    st.markdown("**Security**")
    toggle_rows(group("Security"))
    st.divider()
    st.markdown("**Find the car**")
    toggle_rows(group("Other"))

with tab_charge:
    toggle_rows(group("Charging"))

with tab_win:
    st.subheader("All windows")
    c = st.columns(3)
    if c[0].button("⬆️ Open all", use_container_width=True):
        st.toast(send_catalog("finestrini_apri")[0])
    if c[1].button("🌬️ Ventilate", use_container_width=True):
        st.toast(send_catalog("ventilate_windows")[0])
    if c[2].button("⬇️ Close all", use_container_width=True):
        st.toast(send_catalog("finestrini_chiudi")[0])

    st.subheader("Sunroof")
    c = st.columns(3)
    if c[0].button("⬆️ Open roof", use_container_width=True):
        st.toast(send_catalog("tetto_apri")[0])
    if c[1].button("⬇️ Close roof", use_container_width=True):
        st.toast(send_catalog("tetto_chiudi")[0])

    st.divider()
    st.subheader("🧪 Individual window — experiment")
    st.markdown(
        "The **sunroof** opens with `skylightControl(controlType, **skylightType**)` — a type/id "
        "selector alongside open/close. Windows *might* follow the same shape: "
        "`windowControl(controlType, **windowType**)`. This tests that idea (and a few fallbacks) "
        "per window. A response code **`000000` / `A00079`** means it was **accepted**; "
        "`A00567` = wrong fields, `A00084` = not allowed.")

    win = st.selectbox("Window", ["Front left", "Front right", "Rear left", "Rear right"])
    act = st.radio("Action", ["Open", "Close"], horizontal=True)
    ct = "1" if act == "Open" else "0"
    # best-guess windowType id per window (mirrors skylightType=1 for the roof)
    wtype = {"Front left": "1", "Front right": "2", "Rear left": "3", "Rear right": "4"}[win]
    field = {"Front left": ("fl", "frontLeft"), "Front right": ("fr", "frontRight"),
             "Rear left": ("bl", "backLeft"), "Rear right": ("br", "backRight")}[win]

    cands = [
        # sunroof-style: controlType + a type/id selector (the most likely shape)
        {"controlType": ct, "windowType": wtype},
        {"controlType": ct, "skylightType": wtype},        # in case it reuses the roof field name
        {"controlType": ct, "position": wtype},
        {"controlType": ct, "windowLocation": wtype},
        # per-window field-name shapes
        {f"{field[1]}Window": ct},
        {f"{field[0]}Window": ct},
    ]
    colr = st.columns([1, 1])
    if colr[0].button("🧪 Test this window", type="primary", use_container_width=True):
        rows = []
        prog = st.progress(0.0)
        for i, body in enumerate(cands):
            status, j = signed_command(endpoint="windowControl", body=body)
            code = j.get("code") if isinstance(j, dict) else None
            rows.append({"body": json.dumps(body), "HTTP": status, "code": code,
                         "result": ("✅ ACCEPTED" if accepted(code) else decode(code))})
            prog.progress((i + 1) / len(cands)); time.sleep(1.0)
        prog.empty()
        st.dataframe(rows, use_container_width=True, hide_index=True)
        if any(accepted(r["code"]) for r in rows):
            st.success("A candidate was accepted — per-window control works! Send the winning body to the developer.")
        else:
            st.info("All rejected — this window/shape isn't accepted. Try a different window, or it's "
                    "genuinely all-windows-only on this backend.")
    st.caption("Tip: run with the car awake (recently driven / charging). Watch the physical window to "
               "see which `windowType` id maps to which window.")

with tab_adv:
    st.subheader("Generic signed command")
    ep = st.text_input("Endpoint under /asc/vehicleControl/ (or full /path)", "windowControl")
    gbody = st.text_area("Body JSON", '{"controlType": "1", "windowType": "1"}', key="gbody")
    if st.button("Send signed command", type="primary"):
        try:
            b = json.loads(gbody) if gbody.strip() else {}
            p = ep if ep.startswith("/") else None
            status, j = signed_command(endpoint=None if p else ep, path=p, body=b)
            code = j.get("code") if isinstance(j, dict) else None
            result_banner(f"HTTP {status}", code)
            st.json(j)
        except json.JSONDecodeError as e:
            st.error(f"Bad JSON: {e}")

    st.divider()
    st.subheader("Raw read")
    method = st.radio("Method", ["TSP signed POST", "BFF bearer POST", "BFF GET"], horizontal=True)
    rpath = st.text_input("Path", "/asr/manager/realtime")
    rbody = st.text_area("Body JSON (POST only)", '{"vin": "%s"}' % os.environ.get("VIN", ""))
    if st.button("Send read"):
        if method == "BFF GET":
            st.json(bff_get(rpath))
        else:
            try:
                body = json.loads(rbody) if rbody.strip() else {}
            except json.JSONDecodeError as e:
                st.error(f"Bad JSON: {e}"); body = None
            if body is not None:
                st.json((tsp_read if method.startswith("TSP") else bff_post)(rpath, body)[1])

    st.divider()
    if st.button("📖 Error-code dictionary (allErrorCodes)"):
        st.json(bff_get("/tsp/dictConfig/c/allErrorCodes"))
