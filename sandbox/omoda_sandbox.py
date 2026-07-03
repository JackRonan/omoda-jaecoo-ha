#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
omoda_sandbox.py — standalone OMODA / Jaecoo API testing tool.

Reuses the REAL auth/signing logic from the Home Assistant integration
(`custom_components/omoda_jaecoo/core/`) WITHOUT importing Home Assistant.
Nothing here modifies the integration; it only imports its modules.

Goal: observability. Every call prints the exact raw JSON the API returned so
you can see what the car actually reports and where the mapping into HA breaks.

Auth chain (identical to the app / the integration):
  1) captcha_solver.risolvi()  -> solves AJ-Captcha slide puzzle
  2) login_omoda.invia(email)  -> sends OTP to email
  3) prova_token.call(...)     -> mints token.json (SM4 code + SHA256 signature)
  4) wake._bff_login()         -> exchanges access_token for a TSP userToken
  5) wake._signed_post(...)    -> Chery SDK signed reads/commands

Run:  python omoda_sandbox.py
Config is read from sandbox/omoda_sandbox.env (see .env.example) and can be
edited live from the menu.
"""
import os
import sys
import json
import time

# Windows consoles default to cp1252 and choke on the arrows/emoji in labels.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — older Pythons / redirected streams
    pass

# ─────────────────────────────────────────────────────────────────────────────
# 0. Locate the integration's core/ package and this sandbox dir
# ─────────────────────────────────────────────────────────────────────────────
SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SANDBOX_DIR)
CORE_DIR = os.path.join(REPO_ROOT, "custom_components", "omoda_jaecoo", "core")

# All runtime state (config + minted token) lives OUTSIDE the repo, so nothing
# sensitive is ever written under the git tree. Override with OMODA_SANDBOX_HOME.
DATA_DIR = os.environ.get("OMODA_SANDBOX_HOME") or os.path.join(
    os.path.expanduser("~"), ".omoda_jaecoo_sandbox")
os.makedirs(DATA_DIR, exist_ok=True)
ENV_FILE = os.path.join(DATA_DIR, "omoda_sandbox.env")

if not os.path.isdir(CORE_DIR):
    sys.exit(f"core/ not found at {CORE_DIR} — run this from inside the repo.")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Config — load .env-style file, then set os.environ BEFORE importing core
#    (core modules read env at import time).
# ─────────────────────────────────────────────────────────────────────────────
# key -> (default, help). Region defaults = EU, same as the integration.
CONFIG_KEYS = [
    ("OMODA_EMAIL",       "",                                             "account email (for OTP login)"),
    ("VIN",               "",                                             "vehicle VIN (optional — auto-discovered from queryList)"),
    ("OMODA_PIN",         "",                                             "6-digit car PIN (needed only for commands / taskId)"),
    ("OMODA_BFF",         "https://legend-oj.omodaauto.nl/api",           "BFF REST base (region)"),
    ("TSP_HOST",          "https://tspconsole-eu.cheryinternational.com", "TSP telematics host (region)"),
    ("OMODA_TENANT_CODE", "300006",                                       "tenant code (region)"),
    ("OMODA_COUNTRY_ID",  "1",                                            "country id (1 = EU)"),
    ("OMODA_DEPT_ID",     "39",                                           "dept / phone prefix (39 = IT, 33 = FR, 49 = DE)"),
    ("TSP_APP_ID",        "eu-1",                                         "TSP SDK app id (region)"),
    ("OMODA_LANGUAGE",    "en-GB",                                        "Accept-Language header"),
]


def _load_env_file():
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _apply_defaults():
    for key, default, _ in CONFIG_KEYS:
        if not os.environ.get(key) and default:
            os.environ[key] = default
    # Isolate the sandbox token OUTSIDE the repo (never clobber the integration's).
    os.environ.setdefault("OMODA_TOKEN_PATH", os.path.join(DATA_DIR, "token.json"))
    # Don't auto-mint taskIds unless the user asks (avoids PIN-lockout surprises).
    os.environ.setdefault("OMODA_MINT_TASKID", "1")


def _save_env_file():
    lines = ["# omoda_sandbox config — edit here or via the menu\n"]
    for key, _default, help_txt in CONFIG_KEYS:
        lines.append(f"# {help_txt}\n{key}={os.environ.get(key, '')}\n")
    lines.append(f"OMODA_TOKEN_PATH={os.environ.get('OMODA_TOKEN_PATH', '')}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


_load_env_file()
_apply_defaults()

# ─────────────────────────────────────────────────────────────────────────────
# 2. Import the real core modules (add core/ to sys.path — the modules
#    cross-import each other by bare name, relying on this).
# ─────────────────────────────────────────────────────────────────────────────
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

try:
    import requests
    import omoda_auth as A          # signing / SM4 / headers
    import tsp_sign as S            # Chery SDK request signing
    import wake as W                # _bff_login / _signed_post / _refresh_token / token I/O
    import commands as CMD          # command catalog + send()
    import codes as CODES           # response-code meanings
    import login_omoda as LOGIN     # OTP send (captcha + sendMailCode/sendSmsCode)
    import prova_token as MINT      # token minting
    import probe as PROBE           # combined read probe (optional)
except Exception as e:  # noqa: BLE001
    sys.exit(f"Failed to import core modules from {CORE_DIR}:\n  {type(e).__name__}: {e}\n"
             "Install deps:  pip install -r sandbox/requirements.txt")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Pretty raw-JSON output (rich if available, else stdlib)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.json import JSON as RichJSON
    from rich.panel import Panel
    from rich.table import Table
    _con = Console()
    _HAVE_RICH = True
except Exception:  # noqa: BLE001
    _con = None
    _HAVE_RICH = False


def out(title, status=None, body=None):
    """Dump a labelled raw response. `body` is printed verbatim as JSON."""
    hdr = title if status is None else f"{title}  [HTTP {status}]"
    if _HAVE_RICH:
        _con.rule(f"[bold cyan]{hdr}")
    else:
        print("\n" + "=" * 70 + f"\n{hdr}\n" + "=" * 70)
    if body is None:
        return
    if isinstance(body, (dict, list)):
        txt = json.dumps(body, ensure_ascii=False, indent=2)
    else:
        txt = str(body)
    if _HAVE_RICH:
        try:
            _con.print(RichJSON(txt))
        except Exception:  # noqa: BLE001 — non-JSON body
            _con.print(txt)
    else:
        print(txt)


def info(msg):
    (_con.print(f"[dim]{msg}[/dim]") if _HAVE_RICH else print(msg))


def warn(msg):
    (_con.print(f"[yellow]{msg}[/yellow]") if _HAVE_RICH else print(msg))


def err(msg):
    (_con.print(f"[red]{msg}[/red]") if _HAVE_RICH else print(msg))


def ask(prompt, default=""):
    s = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return s or default


def confirm(prompt):
    return input(f"{prompt} (type 'yes'): ").strip().lower() == "yes"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Low-level helpers that mirror how the integration talks to each API layer
# ─────────────────────────────────────────────────────────────────────────────
def _refresh_core_globals():
    """Core modules snapshot some env into module globals at import. If config was
    edited live, push the changes into the already-imported modules."""
    W.VIN = CMD.VIN = PROBE.VIN = os.environ.get("VIN", "")
    W.TSP_HOST = CMD.TSP_HOST = os.environ.get("TSP_HOST", W.TSP_HOST)
    CMD.PIN = os.environ.get("OMODA_PIN", "")
    LOGIN.BFF = MINT.A.BFF = A.BFF = os.environ.get("OMODA_BFF", A.BFF)
    A.TENANT_CODE = os.environ.get("OMODA_TENANT_CODE", A.TENANT_CODE)
    A.COUNTRY_ID = os.environ.get("OMODA_COUNTRY_ID", A.COUNTRY_ID)
    # Keep wake's cooldown/taskid state OUT of the repo's core/data dir too.
    W.WAKE_STATE = os.path.join(DATA_DIR, "wake_state.json")
    CMD.TASKID_FILE = os.path.join(DATA_DIR, "taskid.txt")


def discover_vin(interactive=True, quiet=False):
    """Pull the VIN(s) from queryList exactly like the integration's config_flow.
    Sets os.environ['VIN'] to the (chosen) VIN. Returns the VIN or None."""
    try:
        access = W._access_token()
    except Exception:  # noqa: BLE001
        access = None
    if not access:
        if not quiet:
            warn("no token yet — mint one via the Auth menu, then discover VIN.")
        return None
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    H = A.headers_post("/tsp/v1/app/vmc/queryList", extra=extra)
    try:
        r = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList",
                          data=json.dumps({}), headers=H, timeout=25)
        j = r.json()
    except Exception as e:  # noqa: BLE001
        err(f"queryList failed: {type(e).__name__}: {e}")
        return None
    lst = j.get("data") if isinstance(j, dict) else None
    vins = [str(v["vin"]) for v in lst if isinstance(v, dict) and v.get("vin")] \
        if isinstance(lst, list) else []
    if not vins:
        warn("no vehicles found on this account (session expired?).")
        return None
    if len(vins) == 1:
        vin = vins[0]
    elif interactive:
        for i, v in enumerate(vins, 1):
            print(f"  {i}. {v}")
        pick = ask("choose vehicle #", "1")
        try:
            vin = vins[int(pick) - 1]
        except (ValueError, IndexError):
            warn("bad choice.")
            return None
    else:
        vin = vins[0]
    os.environ["VIN"] = vin
    _refresh_core_globals()
    if not quiet:
        info(f"VIN discovered: {vin}  ({len(vins)} vehicle(s) on account)")
    return vin


def _need_vin():
    """Ensure a VIN is set; auto-discover from queryList if not. Returns bool."""
    if os.environ.get("VIN"):
        return True
    info("VIN not set — discovering from queryList…")
    return bool(discover_vin(interactive=True))


def tsp_login():
    """BFF -> TSP userToken. Returns (userToken, tUserId) or (None, None)."""
    try:
        return W._bff_login()
    except Exception as e:  # noqa: BLE001
        err(f"network error: {type(e).__name__}: {e}")
        return None, None


def tsp_read(path, body):
    """Signed TSP POST (Chery SDK signing) — the read path used by the poller."""
    if "vin" in body and not body.get("vin"):
        if not _need_vin():
            return
        body = {**body, "vin": os.environ["VIN"]}
    ut, _tu = tsp_login()
    if not ut:
        warn("no userToken — session expired? use Auth menu (Send OTP / Confirm OTP).")
        return
    try:
        status, j = W._signed_post(ut, path, dict(body))
    except Exception as e:  # noqa: BLE001
        err(f"network error: {type(e).__name__}: {e}")
        return
    code = j.get("code") if isinstance(j, dict) else None
    out(f"POST {path}", status, j)
    if code:
        info(f"code {code} → {CODES.meaning(code)}")


def bff_post(path, body):
    """Bearer-authenticated BFF POST (access_token + app signature). Used for
    queryList / setVecDefault / checkPassword etc."""
    try:
        access = W._access_token()
    except Exception as e:  # noqa: BLE001
        err(f"no token.json / unreadable ({e}) — mint a token via the Auth menu first.")
        return
    if not access:
        warn("token.json has no access_token — do the OTP login first.")
        return
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    H = A.headers_post(path, extra=extra)
    try:
        r = requests.post(A.BFF + path, data=json.dumps(body), headers=H, timeout=25)
    except Exception as e:  # noqa: BLE001
        err(f"network error: {type(e).__name__}: {e}")
        return
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        j = {"_raw": r.text[:800]}
    out(f"POST {path}", r.status_code, j)


def bff_get(path, params=None):
    """Bearer-authenticated BFF GET (access_token + app signature) — for the read-only
    metadata endpoints found in the app (defaultEnv, allErrorCodes, version, tenantByCode)."""
    try:
        access = W._access_token()
    except Exception:  # noqa: BLE001
        access = None
    extra = {"Accept": "application/json, text/plain, */*"}
    if access:
        extra["Authorization"] = f"Bearer {access}"
    H = A.headers_post(path, extra=extra)
    try:
        r = requests.get(A.BFF + path, params=params or {}, headers=H, timeout=25)
    except Exception as e:  # noqa: BLE001
        err(f"network error: {type(e).__name__}: {e}")
        return
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        j = {"_raw": r.text[:1500]}
    out(f"GET {path}", r.status_code, j)


def _bff_get_json(path, params=None):
    """Like bff_get but returns (status, json) without printing. For internal lookups."""
    try:
        access = W._access_token()
    except Exception:  # noqa: BLE001
        access = None
    extra = {"Accept": "application/json, text/plain, */*"}
    if access:
        extra["Authorization"] = f"Bearer {access}"
    H = A.headers_post(path, extra=extra)
    try:
        r = requests.get(A.BFF + path, params=params or {}, headers=H, timeout=25)
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return None, None


_ERR_MAP: dict = {}


def _walk_codes(obj, out):
    """Recursively harvest {code: message} pairs from the allErrorCodes JSON (structure
    unknown, so match common key names for the code and its human text)."""
    if isinstance(obj, dict):
        code = None
        msg = None
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in ("code", "errorcode", "errcode", "errorno", "key") and isinstance(v, (str, int)):
                code = str(v)
            if lk in ("msg", "message", "desc", "description", "cnname", "enname",
                      "value", "text", "content", "remark") and isinstance(v, str) and v:
                msg = msg or v
        if code and msg:
            out[code] = msg
        for v in obj.values():
            _walk_codes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_codes(v, out)


def load_error_map(force=False):
    """Fetch + cache the backend allErrorCodes dictionary as {code: text}."""
    global _ERR_MAP
    if _ERR_MAP and not force:
        return _ERR_MAP
    _st, j = _bff_get_json("/tsp/dictConfig/c/allErrorCodes")
    m: dict = {}
    if j is not None:
        _walk_codes(j, m)
    _ERR_MAP = m
    return m


def decode(code):
    """Human meaning for a response code: local codes.py map first, then the fetched
    allErrorCodes dictionary, else a placeholder."""
    if code is None:
        return "no code"
    local = CODES.meaning(code, default=None)
    if local:
        return local
    return load_error_map().get(str(code), f"(unknown {code})")


def signed_command(endpoint=None, path=None, body=None, params=None):
    """Send an ARBITRARY vehicle command through the verified actuate path: BFF login →
    mint taskId (checkPassword, needs PIN) → tsp_sign → POST to the TSP host. Prints the
    RAW JSON response + decoded code. This is the experimentation primitive: point it at
    any endpoint/body the app might support and see exactly what the car returns.

    ⚠️ ACTUATES the vehicle if the endpoint is a real command. Caller confirms first."""
    _refresh_core_globals()
    if not _need_vin():
        return
    vin = os.environ["VIN"]
    token, tuid = W._bff_login()
    if not token:
        warn("no userToken — session expired? redo OTP (Auth menu).")
        return
    taskid, src = CMD.get_taskid(tuid, emit=info)
    if not taskid:
        warn("no taskId — needs OMODA_PIN set, and checkPassword must succeed.")
        return
    ts = int(time.time() * 1000)
    b = dict(body or {})
    if params:
        b.update(params)
    b.update({"clientType": "1", "seq": f"{vin}-{ts}", "taskId": taskid, "vin": vin})
    m = S.sign_body(b, ts)
    payload = json.dumps(m, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"Authorization": token, "timestamp": str(ts),
               "Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}
    url = CMD.TSP_HOST + (path or ("/asc/vehicleControl/" + endpoint))
    info(f"POST {url}  (taskId src: {src})")
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=25)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"_raw": r.text[:800]}
        status = r.status_code
    except Exception as e:  # noqa: BLE001
        err(f"network error: {type(e).__name__}: {e}")
        return
    out(f"{path or endpoint}", status, j)
    code = j.get("code") if isinstance(j, dict) else None
    if code is not None:
        info(f"code {code} → {CODES.meaning(code)}")
    return code


# ─────────────────────────────────────────────────────────────────────────────
# 5. Menu actions — Authentication
# ─────────────────────────────────────────────────────────────────────────────
def act_send_otp_email():
    email = os.environ.get("OMODA_EMAIL", "") or ask("email")
    os.environ["OMODA_EMAIL"] = email
    _refresh_core_globals()
    info("solving captcha + requesting email OTP (this can take a few seconds)…")
    ok = LOGIN.invia(email)
    (info if ok else warn)("OTP request " + ("sent ✅ — check your email." if ok else "FAILED ❌"))


def act_send_otp_sms():
    mobile = ask("mobile number (with or without country code)")
    area = ask("area code", os.environ.get("OMODA_DEPT_ID", "39"))
    info("solving captcha + requesting SMS OTP…")
    ok = LOGIN.invia_sms(mobile, area)
    (info if ok else warn)("SMS OTP " + ("sent ✅" if ok else "FAILED ❌"))


def act_confirm_otp():
    """Mint a token from an OTP code. Dumps the RAW token response (incl. tokens)."""
    email = os.environ.get("OMODA_EMAIL", "") or ask("email")
    code = ask("OTP code you received")
    if not code:
        warn("no code entered.")
        return
    codefmt = ask("code format (plain / padRight32 / padLeft32 / raw)", "plain")
    secret = ask("signing secret (prod / test / h5md5)", "prod")
    info("minting token…")
    try:
        status, j, tok = MINT.call(email, code, secret=secret, emailfmt="module",
                                   codefmt=codefmt, verbose=False)
    except Exception as e:  # noqa: BLE001
        err(f"mint failed: {type(e).__name__}: {e}")
        return
    out("POST /auth/oauth2/token (RAW, tokens NOT redacted)", status, j)
    if tok:
        path = os.environ["OMODA_TOKEN_PATH"]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(j, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        info(f"✅ token saved to {path}")
        discover_vin(interactive=True, quiet=False)   # same as config_flow._discover
    else:
        warn("no access_token in response — code wrong/expired or wrong format/secret. "
             "Try codefmt=padRight32 or a fresh OTP.")


def act_confirm_otp_bruteforce():
    """Try every (secret, codefmt) combo for one OTP — useful when the exact
    format is unknown. Stops at the first that returns an access_token."""
    email = os.environ.get("OMODA_EMAIL", "") or ask("email")
    code = ask("OTP code")
    if not code:
        return
    combos = [(s, c) for s in ("prod", "test", "h5md5")
              for c in ("plain", "padRight32", "padLeft32", "raw")]
    for secret, codefmt in combos:
        try:
            status, j, tok = MINT.call(email, code, secret=secret, emailfmt="module",
                                       codefmt=codefmt, verbose=False)
        except Exception as e:  # noqa: BLE001
            info(f"secret={secret} code={codefmt} -> error {type(e).__name__}")
            continue
        msg = (j.get("msg") or j.get("error_description") or j.get("error")
               or j.get("key")) if isinstance(j, dict) else None
        info(f"secret={secret:6} code={codefmt:10} HTTP {status} "
             f"{'✅ TOKEN!' if tok else (msg or '')}")
        if tok:
            out("winning response (RAW)", status, j)
            path = os.environ["OMODA_TOKEN_PATH"]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(j, fh, indent=2, ensure_ascii=False)
            info(f"✅ token saved to {path}")
            return
    warn("no combo worked — OTP likely wrong/expired.")


def act_refresh_token():
    info("refreshing access_token with refresh_token (no OTP)…")
    try:
        ok = W._refresh_token()
    except Exception as e:  # noqa: BLE001
        err(f"error: {type(e).__name__}: {e}")
        return
    (info if ok else warn)("refresh " + ("OK ✅ (token.json updated)" if ok else
                                         "FAILED ❌ (refresh expired → redo OTP)"))


def act_check_session():
    ut, tu = tsp_login()
    if ut:
        out("BFF login (session check)", 200, {"userToken_present": True, "tUserId": tu})
        info("Session active ✅")
    else:
        warn("Session expired ❌ — redo OTP (close the official app first).")


def act_show_token():
    path = os.environ["OMODA_TOKEN_PATH"]
    if not os.path.exists(path):
        warn(f"no token file at {path}")
        return
    with open(path, encoding="utf-8") as fh:
        out(f"{path} (RAW)", None, json.load(fh))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Menu actions — Read endpoints
# ─────────────────────────────────────────────────────────────────────────────
def act_vehicle_list():
    bff_post("/tsp/v1/app/vmc/queryList", {})


def act_discover_vin():
    discover_vin(interactive=True)


def act_vehicle_attrs():
    if not _need_vin():
        return
    bff_post("/tsp/v1/app/vmc/queryAttributes", {"vin": os.environ["VIN"]})


def act_realtime():
    tsp_read("/asr/manager/realtime", {"vin": ""})


def act_location():
    tsp_read("/asc/vehicleControl/queryVehicleLocation", {"vin": ""})


def act_travel():
    tsp_read("/asd/travelManage/travelQuery", {"vin": ""})


def act_theft_switch():
    tsp_read("/act/theftAlarm/querySwitch", {"vin": ""})


def act_probe_all():
    """Runs the integration's combined read probe (realtime+location+travel)."""
    if not _need_vin():
        return

    def pub(t):
        info(t)
    res = PROBE.probe_once(pub, force=True)
    out("probe_once() result", None, res)


def act_default_env():
    """App bootstrap/environment metadata (GET, no vehicle needed)."""
    bff_get("/tsp/v1/app/env/defaultEnv")


def act_error_codes():
    """Full backend response-code dictionary — decodes A00079/A07312/etc."""
    bff_get("/tsp/dictConfig/c/allErrorCodes")


def act_query_attributes():
    """Static vehicle spec (powertrain, battery kWh, model…) — tells you PHEV vs BEV."""
    if not _need_vin():
        return
    bff_post("/tsp/v1/app/vmc/queryAttributes", {"vin": os.environ["VIN"]})


# ─────────────────────────────────────────────────────────────────────────────
# 7. Menu actions — Commands (ACTUATE the car)
# ─────────────────────────────────────────────────────────────────────────────
def act_list_commands():
    if _HAVE_RICH:
        t = Table("key", "endpoint/path", "name", "group")
        for k, v in CMD.COMMANDS:
            t.add_row(k, v.get("path") or v.get("endpoint", ""), v["name"], v["group"])
        _con.print(t)
    else:
        for k, v in CMD.COMMANDS:
            print(f"{k:26s} {(v.get('path') or v.get('endpoint','')):30s} {v['name']}")


def act_send_command():
    act_list_commands()
    key = ask("command key to send")
    if key not in CMD.CMD_MAP:
        warn(f"unknown key: {key}")
        return
    raw = ask("param overrides as JSON (optional, e.g. {\"temperature\":\"22.0\"})", "")
    params = None
    if raw:
        try:
            params = json.loads(raw)
        except json.JSONDecodeError as e:
            err(f"bad JSON: {e}")
            return
    if not _need_vin():
        return
    c = CMD.CMD_MAP[key]
    warn(f"⚠️  This ACTUATES the car: {c['name']} "
         f"({c.get('path') or '/asc/vehicleControl/' + c['endpoint']})")
    if not confirm("Send this command to the real vehicle?"):
        info("aborted.")
        return
    _refresh_core_globals()
    result = CMD.send(key, emit=info, params=params)
    out(f"command {key} result", None, result)


def act_generic_command():
    """Send an ARBITRARY vehicle command (mints taskId + signs like the real app).
    Use this to probe endpoints the integration doesn't implement yet."""
    endpoint = ask("endpoint under /asc/vehicleControl/ (e.g. chargeDepthControl), "
                   "or full path starting with /")
    if not endpoint:
        return
    raw = ask("JSON body (e.g. {\"chargeSoc\": 80})", "{}")
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        err(f"bad JSON: {e}")
        return
    path = endpoint if endpoint.startswith("/") else None
    ep = None if path else endpoint
    warn(f"⚠️  This may ACTUATE the car (endpoint: {endpoint}).")
    if not confirm("Send this command to the real vehicle?"):
        info("aborted.")
        return
    signed_command(endpoint=ep, path=path, body=body)


# Candidate charge-limit / target-SOC endpoints. NOTE: static reverse-engineering of the
# app (v1.0.2 + v1.1.9) did NOT reveal a real charge-limit REST endpoint — it may be
# device-screen only. These are best-guess names from the Chery SDK / CarLinko conventions;
# this sweep fires each and shows the raw response so you can spot one the backend accepts
# (look for code 000000 / A00079 = accepted, vs A00084 not-allowed / A00567 bad-params).
_CHARGE_LIMIT_CANDIDATES = [
    ("chargeDepthControl", lambda soc: {"chargeSoc": soc}),
    ("chargeDepthControl", lambda soc: {"chargeDepth": soc}),
    ("chargeLimitControl", lambda soc: {"chargeSoc": soc}),
    ("chargeLimitControl", lambda soc: {"socLimit": soc}),
    ("batteryChargeControl", lambda soc: {"targetSoc": soc}),
    ("chargeControl", lambda soc: {"chargeSoc": soc, "controlType": "2"}),
    ("chargeAppointControl", lambda soc: {"mainSwitch": 1, "chargeSoc": soc}),
]


def act_charge_limit_experiment():
    """Sweep candidate charge-limit endpoints with a target SOC and show raw responses.
    The app captures had no confirmed charge-limit endpoint, so this is empirical probing."""
    if not _need_vin():
        return
    soc = ask("target SOC % to try (e.g. 80)", "80")
    try:
        soc_i = int(soc)
    except ValueError:
        err("SOC must be an integer.")
        return
    warn("⚠️  Each candidate is a real signed command that MAY actuate charging config. "
         "No confirmed charge-limit endpoint exists in the captured app — this is probing.")
    if not confirm(f"Fire {len(_CHARGE_LIMIT_CANDIDATES)} candidate charge-limit commands (SOC={soc_i})?"):
        info("aborted.")
        return
    results = []
    for endpoint, build in _CHARGE_LIMIT_CANDIDATES:
        body = build(soc_i)
        info(f"\n── trying {endpoint}  body={body} ──")
        code = signed_command(endpoint=endpoint, body=body)
        results.append((endpoint, body, code))
        time.sleep(1.0)  # be gentle: car handles one command at a time
    load_error_map()  # decode table for unknown codes
    info("\n=== charge-limit sweep summary ===")
    for endpoint, body, code in results:
        verdict = "✅ ACCEPTED" if str(code) in ("000000", "A00079") else f"{code} — {decode(code)}"
        info(f"  {endpoint:22s} {json.dumps(body)} → {verdict}")


# chargeDepthControl is the CONFIRMED-EXISTING endpoint (returns HTTP 200, not 404, unlike the
# invented names). The command was rejected (A07334) — either wrong body fields or a state
# precondition (e.g. must be plugged in / charging). This sweep tries body-field variants on
# that one endpoint so we can find the shape the backend accepts. `maxSocPercent` is the field
# the telemetry channel REPORTS the limit under, so it's the strongest guess for the setter.
def _charge_depth_bodies(soc):
    return [
        {"maxSocPercent": soc},
        {"maxSocPercent": str(soc)},
        {"chargeSoc": soc},
        {"chargeSoc": str(soc)},
        {"chargeDepth": soc},
        {"socLimit": soc},
        {"targetSoc": soc},
        {"chargeSocPercent": soc},
        {"soc": soc},
        {"value": soc},
        {"chargeSoc": soc, "controlType": "1"},
        {"chargeSoc": soc, "needDecode": 0},
        {"maxSocPercent": soc, "controlType": "1"},
    ]


def act_charge_depth_sweep():
    """Sweep body-field variants on the confirmed chargeDepthControl endpoint + auto-decode codes."""
    if not _need_vin():
        return
    soc = ask("target SOC % (e.g. 80)", "80")
    try:
        soc_i = int(soc)
    except ValueError:
        err("SOC must be an integer.")
        return
    bodies = _charge_depth_bodies(soc_i)
    warn(f"⚠️  {len(bodies)} real signed commands to chargeDepthControl (the endpoint that EXISTS). "
         "Best run with the car PLUGGED IN / charging — A07334 may be a 'not charging' precondition.")
    if not confirm(f"Fire {len(bodies)} body variants (SOC={soc_i})?"):
        info("aborted.")
        return
    load_error_map()
    results = []
    for body in bodies:
        info(f"\n── chargeDepthControl  body={body} ──")
        code = signed_command(endpoint="chargeDepthControl", body=body)
        results.append((body, code))
        time.sleep(1.0)
    info("\n=== chargeDepthControl body sweep summary ===")
    for body, code in results:
        verdict = "✅ ACCEPTED" if str(code) in ("000000", "A00079") else f"{code} — {decode(code)}"
        info(f"  {json.dumps(body)} → {verdict}")
    info("\nTip: if EVERY variant gives the same code, it's a STATE precondition (plug in / start "
         "charging and retry), not a body problem. Menu 'Error-code dictionary' shows all meanings.")


def act_raw_request():
    """Fire an arbitrary request at any endpoint — max observability."""
    method = ask("method: (p)ost / (g)et", "p").lower()
    layer = ask("layer: (t)sp signed / (b)ff bearer", "t").lower()
    path = ask("path (e.g. /asr/manager/realtime)")
    if not path:
        return
    if method.startswith("g"):
        bff_get(path)
        return
    raw = ask("JSON body", '{"vin": "%s"}' % os.environ.get("VIN", ""))
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        err(f"bad JSON: {e}")
        return
    if layer.startswith("b"):
        bff_post(path, body)
    else:
        tsp_read(path, body)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Menu actions — Config
# ─────────────────────────────────────────────────────────────────────────────
def act_show_config():
    rows = [(k, os.environ.get(k, ""), h) for k, _d, h in CONFIG_KEYS]
    rows.append(("OMODA_TOKEN_PATH", os.environ.get("OMODA_TOKEN_PATH", ""), "sandbox token file"))
    if _HAVE_RICH:
        t = Table("key", "value", "meaning")
        for k, v, h in rows:
            shown = ("•" * len(v)) if (k == "OMODA_PIN" and v) else v
            t.add_row(k, shown, h)
        _con.print(t)
    else:
        for k, v, h in rows:
            shown = ("•" * len(v)) if (k == "OMODA_PIN" and v) else v
            print(f"{k:20s} = {shown:45s} # {h}")


def act_edit_config():
    act_show_config()
    key = ask("key to change (blank to cancel)")
    if not key:
        return
    valid = {k for k, _d, _h in CONFIG_KEYS} | {"OMODA_TOKEN_PATH"}
    if key not in valid:
        warn(f"unknown key: {key}")
        return
    os.environ[key] = ask(f"new value for {key}", os.environ.get(key, ""))
    _refresh_core_globals()
    _save_env_file()
    info(f"{key} updated + saved to {ENV_FILE}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Menu loop
# ─────────────────────────────────────────────────────────────────────────────
MENU = [
    ("— Authentication —", None),
    ("Send OTP to email (captcha + sendMailCode)", act_send_otp_email),
    ("Send OTP via SMS", act_send_otp_sms),
    ("Confirm OTP → mint & save token", act_confirm_otp),
    ("Confirm OTP → brute-force format (unknown format)", act_confirm_otp_bruteforce),
    ("Refresh access token (no OTP)", act_refresh_token),
    ("Check session (BFF login)", act_check_session),
    ("Show saved token.json (raw)", act_show_token),
    ("— Read endpoints (raw JSON) —", None),
    ("Discover VIN from account (queryList)", act_discover_vin),
    ("Vehicle list  (queryList)", act_vehicle_list),
    ("Vehicle attributes  (queryAttributes)", act_vehicle_attrs),
    ("Realtime telemetry  (/asr/manager/realtime)", act_realtime),
    ("Location  (queryVehicleLocation)", act_location),
    ("Travel  (travelQuery)", act_travel),
    ("Theft alarm switch  (querySwitch)", act_theft_switch),
    ("Combined probe (realtime+location+travel)", act_probe_all),
    ("Default env / app metadata (GET)", act_default_env),
    ("Error-code dictionary (GET allErrorCodes)", act_error_codes),
    ("— Commands (ACTUATE) —", None),
    ("List command catalog", act_list_commands),
    ("Send a command", act_send_command),
    ("Send a GENERIC command (any endpoint + body)", act_generic_command),
    ("Charge-limit experiment (probe candidate endpoints)", act_charge_limit_experiment),
    ("Charge-depth body sweep (chargeDepthControl variants + decode)", act_charge_depth_sweep),
    ("— Advanced / config —", None),
    ("Raw request (any endpoint, GET/POST)", act_raw_request),
    ("Show config", act_show_config),
    ("Edit config", act_edit_config),
]


def main():
    _refresh_core_globals()
    title = "OMODA / Jaecoo API sandbox"
    if _HAVE_RICH:
        _con.print(Panel.fit(f"[bold]{title}[/bold]\n"
                             f"core: {CORE_DIR}\n"
                             f"token: {os.environ['OMODA_TOKEN_PATH']}\n"
                             f"BFF: {A.BFF}   TSP: {os.environ.get('TSP_HOST')}",
                             border_style="cyan"))
    else:
        print(f"{title}\ncore: {CORE_DIR}\ntoken: {os.environ['OMODA_TOKEN_PATH']}")
    if not os.environ.get("VIN"):
        info("VIN not set — it's auto-discovered from queryList after login (like the "
             "integration). No need to enter it.")

    # numbered index over the non-separator rows
    while True:
        print()
        idx = {}
        n = 0
        for label, action in MENU:
            if action is None:
                if _HAVE_RICH:
                    _con.print(f"[bold cyan]{label}[/bold cyan]")
                else:
                    print(f"\n{label}")
            else:
                n += 1
                idx[str(n)] = action
                print(f"  {n:2d}. {label}")
        print("   q. Quit")
        choice = input("\nselect: ").strip().lower()
        if choice in ("q", "quit", "exit"):
            break
        action = idx.get(choice)
        if not action:
            warn("invalid choice.")
            continue
        try:
            action()
        except KeyboardInterrupt:
            warn("\n(interrupted)")
        except Exception as e:  # noqa: BLE001 — sandbox: never crash the menu
            err(f"action error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nbye.")
