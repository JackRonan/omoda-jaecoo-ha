"""
omoda.py — client for the OMODA/JAECOO telematics API (backend "legend", Chery/LionAI).

Shared module: EU PRODUCTION environment constants, signing helpers (still to be
confirmed), and low-level functions for the REST calls.

Everything derives from OMODA_JAECOO_HANDOFF.md (static reverse engineering of APK 1.1.9).
NOTE: the request signature (timestamp/nonce/sign) is NOT yet confirmed —
the hypotheses live in `firma_ipotesi_*` and are chosen by iterating on the
server errors (see probe.py).

Strictly personal use, on your own vehicle and account.
"""

import os
import time
import uuid
import hashlib
import hmac
import json

import requests


# ─────────────────────────────────────────────────────────────────────────────
# Environment constants — EU PRODUCTION (from assets/flutter_assets/env/.env.prod)
# ─────────────────────────────────────────────────────────────────────────────
BFF = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")  # REST backend (default EU)
H5 = os.environ.get("OMODA_H5", "https://legend-oj.omodaauto.nl/h5")

# App CLIENT auth (NOT the user credentials): base64 of "legendApp:legendApp"
APP_BASIC = "Basic bGVnZW5kQXBwOmxlZ2VuZEFwcA=="

TENANT_CODE = os.environ.get("OMODA_TENANT_CODE", "300006")   # instance tenant (default EU)
CHANNEL_ID = os.environ.get("CHANNEL_ID", "1")
COUNTRY_ID = os.environ.get("OMODA_COUNTRY_ID", "1")          # 1 = EU
APP_VERSION = "1.1.9"
APP_VERSION_CODE = "26060602"

# Alternative environments (cross-check if prod misbehaves) — see handoff §3
BFF_SIT = "https://api-app-stg-eu-oj.lionaitech.com/api"
BFF_UAT = "https://legend-oj-uat.omodaauto.nl/api"

# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints (paths relative to BFF = host + "/api"). See FINDINGS.md.
# ─────────────────────────────────────────────────────────────────────────────
EP_LOGIN = "auth/oauth2/token"               # ✅ no signature, wants OTP ("code" field)
EP_LOGOUT = "auth/token/logout"
EP_SEND_SMS = "marketing/v2/app/code/sendSmsCode"   # ⚠️ behind Aliyun WAF (405 on attempts)
EP_SEND_MAIL = "marketing/v2/app/code/sendMailCode"
EP_IS_REGISTER = "marketing/v1/app/user/isRegister"  # requires Bearer
EP_TSP_LOGIN = "tsp/v1/app/auth/login"       # Stage 2 telematics
EP_TSP_TUSERID = "tsp/v1/app/auth/getTuserId"
EP_VMC_LIST = "tsp/v1/app/vmc/queryList"     # ⭐ vehicle list (VIN)
EP_VMC_ATTRS = "tsp/v1/app/vmc/queryAttributes"  # ⭐⭐ status/telemetry

# secretKey / encryption key candidates, extracted from the binary (handoff §6)
AES_KEY_HEX = "d6031998d1b3bbfebf59cc9bbff9aee1"
EC_PUBKEY_HEX = (
    "0418de98b02db9a306f2afcd7235f72a819b80ab12ebd653172476fecd462aab"
    "ffc4ff191b946a5f54d8d0aa2f418808cc25ab056962d30651a114afd2755ad3"
    "36747f93475b7a1fca3b88f2b6a208ccfe469408584dc2b2912675bf5b9e582928"
)


# ─────────────────────────────────────────────────────────────────────────────
# Signature hypotheses (handoff §6) — to be confirmed by iterating on server errors.
# Each function takes the dict of parameters to sign + the secretKey and returns
# the `sign` string. One hypothesis is tried at a time until the server stops
# complaining about "sign missing/wrong".
# ─────────────────────────────────────────────────────────────────────────────
def _params_ordinati(params):
    """k=v concatenated with & in alphabetical key order (typical Chinese pattern)."""
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def firma_ipotesi_1(params, secret):
    """MD5(ordered_params + "&key=" + secret), uppercase hex."""
    s = _params_ordinati(params) + "&key=" + secret
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest().upper()


def firma_ipotesi_2(params, secret):
    """HMAC-SHA256(ordered_params, secret), lowercase hex."""
    s = _params_ordinati(params)
    return hmac.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest()


def firma_ipotesi_3(params, secret, app_id="legendApp"):
    """MD5(appId + timestamp + nonce + secret), uppercase hex."""
    s = f"{app_id}{params.get('timestamp','')}{params.get('nonce','')}{secret}"
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest().upper()


# ─────────────────────────────────────────────────────────────────────────────
# Request helpers
# ─────────────────────────────────────────────────────────────────────────────
def nuovo_timestamp():
    return str(int(time.time() * 1000))


def nuovo_nonce():
    return uuid.uuid4().hex


def header_base(extra=None):
    """Headers common to all BFF calls. `extra` overrides/adds."""
    h = {
        "Authorization": APP_BASIC,
        "tenant": TENANT_CODE,          # header name to verify
        "channelId": CHANNEL_ID,
        "countryId": COUNTRY_ID,
        "appversion": APP_VERSION,
        "timestamp": nuovo_timestamp(),
        "nonce": nuovo_nonce(),
        "User-Agent": "okhttp/4.9.0",   # typical Android/Flutter client
    }
    if extra:
        h.update(extra)
    return h


def stampa_risposta(r):
    """Readable dump of the response — to paste in for iterating on the signature."""
    print(f"→ {r.request.method} {r.url}")
    print(f"  HTTP {r.status_code}  content-type={r.headers.get('content-type')}")
    body = r.text
    try:
        body = json.dumps(r.json(), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print("  body:")
    for line in body.splitlines() or [body]:
        print("    " + line)
    print()
    return r
