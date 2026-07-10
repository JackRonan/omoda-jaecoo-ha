"""
captcha_solver.py — solves the AJ-Captcha blockPuzzle of the OMODA 'legend' gateway.

Endpoints (discovered by decompiling the app with blutter):
  POST /api/code/create  -> puzzle (originalImageBase64, jigsawImageBase64, secretKey, token)
  POST /api/code/check   -> verifies the slide (encrypted pointJson)
Encryption: AES/ECB/PKCS7, key = secretKey (UTF-8), output base64.
  pointJson           = AES( JSON({"x":gapX,"y":Y}) , secretKey )
  captchaVerification = AES( token + "---" + JSON({"x":gapX,"y":Y}) , secretKey )
The captchaVerification is passed to sendMailCode/sendSmsCode.
"""
import os, time, hashlib, json, base64, io
import requests, numpy as np
from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import omoda

# NOTE (2026-06-21): the solver NO LONGER uses OpenCV (cv2). The shape-matching is
# reimplemented with only numpy + Pillow → installable on Home Assistant/HAOS
# (numpy has a wheel for every arch, Pillow is already in the HA core), so the entire
# OTP login runs inside HA for anyone installing the component without a pre-existing token.
# Equivalence verified A/B vs cv2 on real captchas (9/10 x identical, the remaining one
# solved BETTER by numpy) + risolvi() end-to-end 5/5.

SECRET = "5c7af05e6fbf562842ef483ee96e06a0"   # gateway signing secret (universal)
NONCE  = "chery_legend_marketing"
ROOT   = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # region (default EU)

def _md5(s): return hashlib.md5(s.encode()).hexdigest()

def _signed_headers(path):
    ts = int(time.time() * 1000)
    return {
        "Authorization": omoda.APP_BASIC, "tenant": omoda.TENANT_CODE,
        "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
        "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0",
        "nonce": NONCE, "timestamp": str(ts), "url": path,
        "signature": _md5(f"{SECRET}{NONCE}{path}{ts}"), "Content-Type": "application/json",
    }

def _aes_b64(plaintext, key):
    c = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    return base64.b64encode(c.encrypt(pad(plaintext.encode("utf-8"), 16))).decode()

def _img(b64): return Image.open(io.BytesIO(base64.b64decode(b64)))

def _dilate3(a):
    """3×3 dilation (8-neighbors) — numpy equivalent of cv2.dilate(kernel 3×3)."""
    p = np.pad(a, 1, mode="edge")
    return np.maximum.reduce([p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                              p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                              p[2:, 0:-2],  p[2:, 1:-1],  p[2:, 2:]])

def _erode3(a):
    """3×3 erosion (8-neighbors) — numpy equivalent of cv2.erode(kernel 3×3)."""
    p = np.pad(a, 1, mode="edge")
    return np.minimum.reduce([p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                              p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                              p[2:, 0:-2],  p[2:, 1:-1],  p[2:, 2:]])

def trova_gap_x(orig_b64, jigsaw_b64):
    """Returns pointJson x. Shape-matching: outline of the piece vs white outlines
    drawn on the background (the real hole has the SAME shape as the piece; the decoys don't).
    pointJson x = (left edge of the hole) - (x0 of the piece in the jigsaw image).

    numpy-only implementation (no cv2): bbox of the piece from the alpha, 3×3
    morphological gradient (dilate−erode) as template, normalized cross-correlation
    (TM_CCORR_NORMED) via sliding_window_view + einsum row by row (memory O(W·h·w))."""
    o = np.asarray(_img(orig_b64).convert("RGB"))
    j = np.asarray(_img(jigsaw_b64).convert("RGBA"))
    m = (j[:, :, 3] > 128).astype(np.uint8)
    ys, xs = np.where(m)
    if ys.size == 0:
        return 0
    x, y = int(xs.min()), int(ys.min())
    w, h = int(xs.max()) - x + 1, int(ys.max()) - y + 1
    sil = m[y:y + h, x:x + w] * 255
    outline = np.clip(_dilate3(sil.astype(np.int16)) - _erode3(sil.astype(np.int16)),
                      0, 255).astype(np.float64)
    white = ((o[:, :, 0] > 185) & (o[:, :, 1] > 185) & (o[:, :, 2] > 185)).astype(np.float64)
    H, W = white.shape
    T = outline
    T2 = float((T * T).sum())
    if T2 <= 0 or H < h or W < w:
        return 0
    sw = np.lib.stride_tricks.sliding_window_view(white, (h, w))   # (H-h+1, W-w+1, h, w)
    best_score, best_x = -1.0, w
    for gy in range(sw.shape[0]):
        wr = sw[gy]                                  # (W-w+1, h, w)
        num = np.einsum("kij,ij->k", wr, T)
        den = np.sqrt(np.einsum("kij,kij->k", wr, wr) * T2)
        den[den == 0] = 1e-9
        res = num / den
        res[:max(1, w)] = 0                          # zero out the left edge (as in the original)
        gx = int(np.argmax(res))
        if res[gx] > best_score:
            best_score, best_x = float(res[gx]), gx
    return int(best_x) - x      # gapLeft - x0_jig

def crea():
    """Creates a puzzle. Returns repData (dict) or None if the gateway responds
    non-JSON / unexpected shape (Aliyun WAF, maintenance): the caller retries."""
    r = requests.post(f"{ROOT}/code/create", json={"captchaType": "blockPuzzle"},
                      headers=_signed_headers("/code/create"), timeout=15)
    try:
        return (r.json().get("data") or {}).get("repData")
    except Exception:
        return None

def _signed_headers_query(path, keys_csv, vals_csv):
    """Signature for requests with QUERY parameters: MD5(secret+nonce+path+ts+'[vals]') + header keys."""
    ts = int(time.time() * 1000)
    return {
        "Authorization": omoda.APP_BASIC, "tenant": omoda.TENANT_CODE,
        "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
        "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0",
        "nonce": NONCE, "timestamp": str(ts), "url": path, "keys": keys_csv,
        "signature": _md5(f"{SECRET}{NONCE}{path}{ts}[{vals_csv}]"), "Content-Type": "application/json",
    }

def check(token, point, secret):
    # The parameters go in the QUERY (the app uses encodeUrl -> ?captchaType=..&pointJson=..&token=..)
    point_json = json.dumps(point, separators=(",", ":"))
    enc = _aes_b64(point_json, secret)
    params = {"captchaType": "blockPuzzle", "pointJson": enc, "token": token}
    keys = "captchaType,pointJson,token"
    vals = f"blockPuzzle,{enc},{token}"
    r = requests.post(f"{ROOT}/code/check", params=params,
                      headers=_signed_headers_query("/code/check", keys, vals), timeout=15)
    try:
        j = r.json()
    except Exception:
        return {}
    return j if isinstance(j, dict) else {}

def risolvi(max_tentativi=12, verbose=True):
    """create+solve+check until it passes (single-use token). Returns captchaVerification or None.
    y of the point = 5 (constant, from decompiling the app)."""
    for t in range(1, max_tentativi + 1):
        rep = crea()
        if not isinstance(rep, dict) or not all(
                rep.get(k) for k in ("token", "secretKey", "originalImageBase64", "jigsawImageBase64")):
            if verbose: print(f"  attempt {t}: create invalid (non-JSON gateway?)")
            time.sleep(0.3)
            continue
        token, secret = rep["token"], rep["secretKey"]
        x = trova_gap_x(rep["originalImageBase64"], rep["jigsawImageBase64"])
        point = {"x": x, "y": 5}
        res = check(token, point, secret)
        d = res.get("data") or {}
        if d.get("repCode") == "0000":
            point_json = json.dumps(point, separators=(",", ":"))
            cv = _aes_b64(f"{token}---{point_json}", secret)
            if verbose: print(f"  ✅ captcha solved on attempt {t} (x={x}).")
            return cv
        if verbose: print(f"  attempt {t}: x={x} -> {d.get('repCode')} {d.get('repMsg')}")
        time.sleep(0.3)
    return None

if __name__ == "__main__":
    cv = risolvi()
    print("\nRESULT:", "OK -> " + cv if cv else "FAILED")
