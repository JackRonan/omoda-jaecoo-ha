"""
prova_token.py — chiama auth/oauth2/token replicando l'app.

  python3 prova_token.py <email> <code> [secret] [emailfmt] [codefmt]

  secret:   prod (default) | test | h5md5   (h5md5 = vecchio schema MD5/5c7af05e)
  emailfmt: module (default, "APP-LOGIN@<email>") | plain
  codefmt:  plain (default) | padRight32 | padLeft32 | raw  (raw = code non cifrato)

Per testare la FIRMA senza consumare OTP: usa un <code> finto (es. 000000).
Se la firma e' giusta l'errore NON sara' piu' "Authorization authentication failed".
"""
import os, sys, json, requests
import omoda_auth as A

# dove salvare il token coniato (per-account); il bridge/coordinator legge lo stesso path
_TOKEN_OUT = os.environ.get("OMODA_TOKEN_PATH", "token.json")

TOKEN_PATH = "/auth/oauth2/token"

def build_params(email, code, emailfmt, codefmt):
    em = f"APP-LOGIN@{email}" if emailfmt=="module" else email
    cv = code if codefmt=="raw" else A.sm4_code(code, codefmt)
    # ordine come nel builder app: email, code, needDecode, grant_type, scope, loginType, loginAction
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
        # vecchio schema MD5/5c7af05e/marketing, niente brackets (POST)
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
        print(f"[secret={secret} email={emailfmt} code={codefmt}] HTTP {r.status_code}")
        print("  url:", r.url)
        print("  resp:", json.dumps(j, ensure_ascii=False)[:400])
    return r.status_code, j, tok

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    email, code = sys.argv[1], sys.argv[2]
    secret  = sys.argv[3] if len(sys.argv) > 3 else "prod"
    emailfmt= sys.argv[4] if len(sys.argv) > 4 else "module"
    codefmt = sys.argv[5] if len(sys.argv) > 5 else "plain"
    sc, j, tok = call(email, code, secret, emailfmt, codefmt)
    if tok:
        json.dump(j, open(_TOKEN_OUT, "w"), indent=2, ensure_ascii=False)
        print(f"\n✅ LOGIN OK — token salvato in {_TOKEN_OUT}")
