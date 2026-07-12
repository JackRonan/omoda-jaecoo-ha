#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tsp_sign.py — REST signing for the Chery Vehicle SDK (PROD EU), reconstructed
byte-for-byte from the smali `smali_dex2/h/ldkb.smali` (session 8, 2026-06-17):

  - method b(Map,J,String)  : builds the string-to-sign
  - method c(String)        : SHA-256 -> hex -> toUpperCase()  (UPPERCASE!)
  - method a(Map,J,String)  : for tagEncrypt="1" adds appId, signs, adds sign
  - method a(J,String)      : header Authorization=token, timestamp, x-TenantId=""

Algorithm (EU, tagEncrypt="1"):
  half      = EVEN-position characters of APP_SECRET (-> "EUProd89ec59274d23491084af")
  base      = <params sorted alphabetically "k=v&" non-empty> + "secretKey=" + half + "&timestamp=" + ts
  sign      = SHA256(base) in UPPERCASE HEX
  body JSON = { ...params..., "appId": <APP_ID>, "sign": <sign> }
  header    = { Authorization: <userToken>, timestamp: <ts>, x-TenantId: "" }
"""
import os
import hashlib
import base64

# REGION constants (environments[0] in Config.java). Default EU, override via env.
APP_ID     = os.environ.get("TSP_APP_ID", "eu-1")
APP_SECRET = "EBUJPYr7oDd48C9Te9c755942Y7T48dV293Y4Z931J098X41aYf0"
TAG_ENCRYPT = "1"          # EU = SHA-256 (NOT HMAC)

def half_secret(secret: str = APP_SECRET) -> str:
    """EVEN-position characters (indices 0,2,4,...) -> 'EUProd89ec59274d23491084af'."""
    return "".join(secret[i] for i in range(len(secret)) if i % 2 == 0)

HALF = half_secret()   # "EUProd89ec59274d23491084af"

def _flatten_value(v):
    """Serializes a nested ARRAY value the way the native SDK does (a(JSONObject) in
    ldkb.smali) BEFORE computing the sign. For each element:
      - object   → 'key=value&' with keys sorted alphabetically (empty values skipped),
                   and its possible sub-list flattened recursively;
      - scalar   → str(element) concatenated WITHOUT separator (e.g. [1,2,3] → '123').
    The trailing '&' is removed. Verified byte-for-byte on 4/4 real
    `chargeAppointControl` envelopes (cycleData [1..7] → '1234567')."""
    if isinstance(v, list):
        sb = ""
        for el in v:
            if isinstance(el, dict):
                fl = _flatten_obj(el)
                for k in sorted(fl.keys()):
                    val = fl[k]
                    if val is None or val == "":
                        continue
                    sb += f"{k}={val}&"
            else:
                sb += str(el)
        if sb.endswith("&"):
            sb = sb[:-1]
        return sb
    return v


def _flatten_obj(obj: dict) -> dict:
    """Copy of the object with only the list values flattened (see _flatten_value).
    Scalar values stay unchanged → for FLAT bodies it is a no-op (the historic
    algorithm stays identical, verified on 63/63 flat envelopes)."""
    return {k: (_flatten_value(v) if isinstance(v, list) else v) for k, v in obj.items()}


def build_sign(params: dict, ts_ms: int, half: str = HALF) -> str:
    """Replicates b(Map,J,String) for tagEncrypt='1': UPPERCASE SHA-256.

    Nested array values (e.g. `chargeAppointPlans`) are first flattened the way
    the native SDK does (_flatten_obj); without arrays the behavior is unchanged. Note:
    it flattens a COPY → the body returned by sign_body keeps the real array."""
    flat = _flatten_obj(params)
    parts = []
    for k in sorted(flat.keys()):                # Arrays.sort on the keys
        v = flat[k]
        if v is None or v == "":                 # null/"" skipped
            continue
        parts.append(f"{k}={v}&")
    base = "".join(parts) + f"secretKey={half}&timestamp={ts_ms}"
    # DISCOVERY S23 (2026-06-20, eCapture/Conscrypt capture): the REAL encoding of the sign
    # is base64(sha256(base)).upper(), NOT hexdigest().upper(). Verified on 71 real
    # envelopes (airControl/coolingControl/heatingControl/lockControl/seatControl/window/findCar...).
    return base64.b64encode(hashlib.sha256(base.encode("utf-8"), usedforsecurity=False).digest()).decode().upper()

def sign_body(body_params: dict, ts_ms: int) -> dict:
    """Replicates a(Map,J,String) tag1: returns the final JSON body {params, appId, sign}."""
    m = dict(body_params)
    m["appId"] = APP_ID                          # appId among the signed parameters
    sign = build_sign(m, ts_ms)
    m["sign"] = sign                             # sign added AFTER signing
    return m

def auth_headers(user_token: str, ts_ms: int, tenant_id: str = "") -> dict:
    """Replicates a(J,String) tag1: Authorization=token, timestamp, x-TenantId."""
    return {
        "Authorization": user_token,
        "timestamp": str(ts_ms),
        "x-TenantId": tenant_id or "",
    }

if __name__ == "__main__":
    print("HALF loaded:", bool(HALF), f"(len {len(HALF)})")
    ts = 1700000000000
    demo = sign_body({"vin": "VIN_PLACEHOLDER"}, ts)
    print("demo body:", demo)
