"""
captcha_solver.py — risolve l'AJ-Captcha blockPuzzle del gateway OMODA 'legend'.

Endpoint (scoperti decompilando l'app con blutter):
  POST /api/code/create  -> puzzle (originalImageBase64, jigsawImageBase64, secretKey, token)
  POST /api/code/check   -> verifica lo slide (pointJson cifrato)
Cifratura: AES/ECB/PKCS7, chiave = secretKey (UTF-8), output base64.
  pointJson           = AES( JSON({"x":gapX,"y":Y}) , secretKey )
  captchaVerification = AES( token + "---" + JSON({"x":gapX,"y":Y}) , secretKey )
Il captchaVerification va passato a sendMailCode/sendSmsCode.
"""
import os, time, hashlib, json, base64, io
import requests, numpy as np, cv2
from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import omoda

SECRET = "5c7af05e6fbf562842ef483ee96e06a0"   # secret di firma del gateway (universale)
NONCE  = "chery_legend_marketing"
ROOT   = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # regione (default EU)

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

def trova_gap_x(orig_b64, jigsaw_b64):
    """Ritorna pointJson x. Shape-matching: contorno del tassello vs contorni bianchi
    disegnati sullo sfondo (il vero buco ha la STESSA sagoma del tassello; le esche no).
    pointJson x = (bordo sinistro del buco) - (x0 del tassello nell'immagine jigsaw)."""
    o = np.array(_img(orig_b64).convert("RGB"))
    j = np.array(_img(jigsaw_b64).convert("RGBA"))
    m = (j[:, :, 3] > 128).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _ = [int(v) for v in st[big]]
    sil = m[y:y + h, x:x + w] * 255
    outline = cv2.morphologyEx(sil, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    white = ((o[:, :, 0] > 185) & (o[:, :, 1] > 185) & (o[:, :, 2] > 185)).astype(np.uint8) * 255
    res = cv2.matchTemplate(white, outline, cv2.TM_CCORR_NORMED)
    res[~np.isfinite(res)] = 0
    res[:, :max(1, w)] = 0
    _, _, _, loc = cv2.minMaxLoc(res)
    return int(loc[0]) - x      # gapLeft - x0_jig

def crea():
    r = requests.post(f"{ROOT}/code/create", json={"captchaType": "blockPuzzle"},
                      headers=_signed_headers("/code/create"), timeout=15)
    return r.json()["data"]["repData"]

def _signed_headers_query(path, keys_csv, vals_csv):
    """Firma per richieste con parametri in QUERY: MD5(secret+nonce+path+ts+'[vals]') + header keys."""
    ts = int(time.time() * 1000)
    return {
        "Authorization": omoda.APP_BASIC, "tenant": omoda.TENANT_CODE,
        "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
        "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0",
        "nonce": NONCE, "timestamp": str(ts), "url": path, "keys": keys_csv,
        "signature": _md5(f"{SECRET}{NONCE}{path}{ts}[{vals_csv}]"), "Content-Type": "application/json",
    }

def check(token, point, secret):
    # I parametri vanno in QUERY (l'app usa encodeUrl -> ?captchaType=..&pointJson=..&token=..)
    point_json = json.dumps(point, separators=(",", ":"))
    enc = _aes_b64(point_json, secret)
    params = {"captchaType": "blockPuzzle", "pointJson": enc, "token": token}
    keys = "captchaType,pointJson,token"
    vals = f"blockPuzzle,{enc},{token}"
    r = requests.post(f"{ROOT}/code/check", params=params,
                      headers=_signed_headers_query("/code/check", keys, vals), timeout=15)
    return r.json()

def risolvi(max_tentativi=12, verbose=True):
    """create+solve+check finche' non passa (token monouso). Ritorna captchaVerification o None.
    y del punto = 5 (costante, dalla decompilazione dell'app)."""
    for t in range(1, max_tentativi + 1):
        rep = crea()
        token, secret = rep["token"], rep["secretKey"]
        x = trova_gap_x(rep["originalImageBase64"], rep["jigsawImageBase64"])
        point = {"x": x, "y": 5}
        res = check(token, point, secret)
        d = res.get("data") or {}
        if d.get("repCode") == "0000":
            point_json = json.dumps(point, separators=(",", ":"))
            cv = _aes_b64(f"{token}---{point_json}", secret)
            if verbose: print(f"  ✅ captcha risolto al tentativo {t} (x={x}). cv={cv[:32]}…")
            return cv
        if verbose: print(f"  tentativo {t}: x={x} -> {d.get('repCode')} {d.get('repMsg')}")
        time.sleep(0.3)
    return None

if __name__ == "__main__":
    cv = risolvi()
    print("\nRISULTATO:", "OK -> " + cv if cv else "FALLITO")
