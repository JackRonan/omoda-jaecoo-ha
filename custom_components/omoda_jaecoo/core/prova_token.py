"""
prova_token.py — calls auth/oauth2/token replicating the app.

  python3 prova_token.py <email> <code> [secret] [emailfmt] [codefmt]

  secret:   prod (default) | test | h5md5   (h5md5 = old MD5/5c7af05e scheme)
  emailfmt: module (default, "APP-LOGIN@<email>") | plain
  codefmt:  plain (default) | padRight32 | padLeft32 | raw  (raw = uncrypted code)

To test the SIGNATURE without consuming an OTP: use a fake <code> (e.g. 000000).
If the signature is right the error will NO LONGER be "Authorization authentication failed".
"""
import os, sys, json, requests
import omoda_auth as A

# where to save the minted token (per-account); the bridge/coordinator reads the same path
_TOKEN_OUT = os.environ.get("OMODA_TOKEN_PATH", "token.json")

TOKEN_PATH = "/auth/oauth2/token"

def build_params(email, code, emailfmt, codefmt):
    em = f"APP-LOGIN@{email}" if emailfmt=="module" else email
    cv = code if codefmt=="raw" else A.sm4_code(code, codefmt)
    # order as in the app builder: email, code, needDecode, grant_type, scope, loginType, loginAction
    return {
        "email": em,
        "code": cv,
        "needDecode": "0",
        "grant_type": "email",
        "scope": "server",
        "loginType": "email",
        "loginAction": "1",
    }

def call(email, code, secret="prod", emailfmt="module", codefmt="plain", verbose=True):
    sec = {"prod": A.SIGN_SECRET, "test": A.SIGN_SECRET_TEST}.get(secret)
    params = build_params(email, code, emailfmt, codefmt)
    if secret == "h5md5":
        # old MD5/5c7af05e/marketing scheme, no brackets (POST)
        import hashlib, time
        ts = int(time.time()*1000)
        S, N = "5c7af05e6fbf562842ef483ee96e06a0", "chery_legend_marketing"
        sig = hashlib.md5(f"{S}{N}{TOKEN_PATH}{ts}".encode()).hexdigest()
        H = A.headers_post(TOKEN_PATH)  # base
        H.update({"nonce": N, "timestamp": str(ts), "signature": sig})
    else:
        H = A.headers_post(TOKEN_PATH, secret=sec)
    r = requests.post(A.BFF + "/auth/oauth2/token", params=params, headers=H, timeout=20)
    try: j = r.json()
    except Exception: j = {"_raw": r.text[:300]}
    tok = j.get("access_token") or (j.get("data") or {}).get("access_token")
    if verbose:
        # LOW: this script's stdout passes through HA → redact the tokens in the dumps
        print(f"[secret={secret} email={emailfmt} code={codefmt}] HTTP {r.status_code}")
        print("  url:", r.url)
        print("  resp:", json.dumps(_redact(j), ensure_ascii=False)[:400])
    return r.status_code, j, tok


def _redact(obj):
    """Copy with access_token/refresh_token obscured (for the prints that go into HA)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("access_token", "refresh_token") and v:
                out[k] = f"<{len(str(v))}ch redacted>"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    email, code = sys.argv[1], sys.argv[2]
    secret  = sys.argv[3] if len(sys.argv) > 3 else "prod"
    emailfmt= sys.argv[4] if len(sys.argv) > 4 else "module"
    codefmt = sys.argv[5] if len(sys.argv) > 5 else "plain"
    sc, j, tok = call(email, code, secret, emailfmt, codefmt)
    if tok:
        # atomic write: tmp + rename (token.json never truncated if the process dies)
        tmp = _TOKEN_OUT + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(j, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, _TOKEN_OUT)
        print(f"\n✅ LOGIN OK — token saved to {_TOKEN_OUT}")
        print("RESULT: OK")          # H7: stable sentinel for session.confirm_otp
        sys.exit(0)
    # H7: minting failed → sentinel + exit code != 0 (session.py relies on these)
    print("RESULT: FAIL")
    sys.exit(1)
