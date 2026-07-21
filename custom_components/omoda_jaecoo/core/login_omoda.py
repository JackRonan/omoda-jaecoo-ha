"""
login_omoda.py — full OMODA 'legend' login via EMAIL code.

Two-phase use (the email code expires within a few minutes):
  PHASE 1:  python3 login_omoda.py invia <email>
           -> solves the captcha and triggers the code via email. Prints the outcome.
  PHASE 2:  python3 login_omoda.py token <email> <codice>
           -> tries the known oauth2/token combinations, saves token.json,
              then attempts Stage 2 (TSP + vehicle list).
"""
import os, sys, time, json, hashlib, requests
import captcha_solver as C
import omoda

BFF = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # region (default EU)
SECRET = "5c7af05e6fbf562842ef483ee96e06a0"
NONCE = "chery_legend_marketing"
# MD5 = the gateway's required signature format (interop, not security hashing).
def _md5(s): return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()

def _hdr_form(path):
    ts = int(time.time() * 1000)
    return {"Authorization": omoda.APP_BASIC,
            "TENANT-CODE": omoda.TENANT_CODE, "TENANT-ID": omoda.TENANT_CODE,
            "tenantCode": omoda.TENANT_CODE, "tenantID": omoda.TENANT_CODE, "tenant": omoda.TENANT_CODE,
            "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
            "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0", "Accept-Language": os.environ.get("OMODA_LANGUAGE", "it-IT"),
            "nonce": NONCE, "timestamp": str(ts), "url": path,
            "signature": _md5(f"{SECRET}{NONCE}{path}{ts}"),
            "Content-Type": "application/x-www-form-urlencoded"}

def invia(email):
    """Sends the OTP code via email. Returns True/False (H7: the outcome is the return
    value; __main__ prints the sentinel `RESULT: OK/FAIL` for session.request_otp)."""
    print("Solving the captcha…")
    cv = C.risolvi()
    if not cv:
        print("❌ captcha not solved, try again."); return False
    path = "/marketing/v2/app/code/sendMailCode"
    r = requests.post(BFF + path,
                      data={"email": email, "module": "APP-LOGIN", "captchaVerification": cv},
                      headers=_hdr_form(path), timeout=15)
    try: j = r.json()
    except Exception: j = {"_t": r.text[:200]}
    print(f"sendMailCode -> HTTP {r.status_code} key={j.get('key')} msg={j.get('msg')} data={j.get('data')}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Code sent to the email. Now: python3 login_omoda.py token <email> <codice>")
        return True
    if j.get("key") == "email.not.exists":
        print("⚠️  Email not recognized as an account. Check the address registered in the app.")
    return False

def invia_sms(mobile, area="39"):
    mobile = mobile.lstrip("+").replace(" ", "")
    print("Solving the captcha…")
    cv = C.risolvi()
    if not cv:
        print("❌ captcha not solved, try again."); return False
    path = "/marketing/v2/app/code/sendSmsCode"
    r = requests.post(BFF + path,
                      data={"mobile": mobile, "areaCode": area, "module": "APP-LOGIN", "captchaVerification": cv},
                      headers=_hdr_form(path), timeout=15)
    try: j = r.json()
    except Exception: j = {"_t": r.text[:200]}
    print(f"sendSmsCode -> HTTP {r.status_code} {j}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Code sent via SMS. Now: python3 login_omoda.py token-sms <mobile> <codice>")
        return True
    return False

# oauth2/token combinations to try (codeId is NOT needed)
def _combos(email, code):
    # first: EXACT replica of the app email-login builder (grant_type=email, scope=server, loginType=email, loginAction=1)
    return [
        {"grant_type": "email", "scope": "server", "loginType": "email", "loginAction": "1", "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "email", "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "email", "scope": "server", "loginType": "email", "loginAction": "1", "username": email, "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "password", "loginType": "email", "loginAction": "1", "email": email, "code": code, "needDecode": "0"},
    ]

def _combos_sms(mobile, code, area="39"):
    mobile = mobile.lstrip("+").replace(" ", "")
    return [
        {"grant_type": "mobile", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
        {"grant_type": "mobile", "mobile": f"{area}{mobile}", "code": code, "needDecode": "0"},
        {"grant_type": "password", "loginType": "mobile", "loginAction": "1", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
        {"grant_type": "sms", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
    ]

def _token_headers(path, params):
    """Parameters in QUERY + signature (keys + [values]) — gateway format."""
    keys = list(params.keys())
    vals_csv = ",".join(str(params[k]) for k in keys)
    ts = int(time.time() * 1000)
    return {"Authorization": omoda.APP_BASIC, "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "okhttp/4.9.0",
            "TENANT-CODE": omoda.TENANT_CODE, "TENANT-ID": omoda.TENANT_CODE,
            "tenantCode": omoda.TENANT_CODE, "tenantID": omoda.TENANT_CODE, "tenant": omoda.TENANT_CODE,
            "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
            "appversion": omoda.APP_VERSION, "Accept-Language": os.environ.get("OMODA_LANGUAGE", "it-IT"),
            "nonce": NONCE, "timestamp": str(ts), "url": path, "keys": ",".join(keys),
            "signature": _md5(f"{SECRET}{NONCE}{path}{ts}[{vals_csv}]")}

def token(email, code, sms=False, area="39"):
    win = None
    combos = _combos_sms(email, code, area) if sms else _combos(email, code)
    for params in combos:
        H = _token_headers("/auth/oauth2/token", params)
        r = requests.post(f"{BFF}/auth/oauth2/token", params=params, headers=H, timeout=20)
        try: j = r.json()
        except Exception: j = {"_t": r.text[:150]}
        tok = j.get("access_token") or (j.get("data") or {}).get("access_token")
        print(f"  {params.get('grant_type')}/{params.get('loginType','-')} -> HTTP {r.status_code} "
              f"{'OK!' if tok else (j.get('msg') or j.get('error_description') or j.get('error') or j.get('key'))}")
        if tok: win = j; break
        time.sleep(0.5)
    if not win:
        print("❌ no combination worked (code expired/wrong or different fields)."); return False
    with open("token.json", "w") as fh:
        json.dump(win, fh, indent=2, ensure_ascii=False)
    tok = win.get("access_token") or (win.get("data") or {}).get("access_token")
    # LOW: don't print the token (stdout can end up in the logs) — just confirm
    print("\n✅ LOGIN OK — token saved to token.json.")
    # Stage 2
    HB = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "User-Agent": "okhttp/4.9.0",
          "tenant": omoda.TENANT_CODE, "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
          "appversion": omoda.APP_VERSION}
    for nome, ep in [("TSP login", "tsp/v1/app/auth/login"), ("getTuserId", "tsp/v1/app/auth/getTuserId"),
                     ("vehicles", "tsp/v1/app/vmc/queryList")]:
        try:
            r = requests.post(f"{BFF}/{ep}", json={}, headers=HB, timeout=25)
            print(f"\n=== {nome} [HTTP {r.status_code}] ===\n{r.text[:1200]}")
        except requests.RequestException as e:
            print(f"\n=== {nome}: NETWORK ERROR {e} ===")
    return True

def _emit_result(ok):
    """H7: stable sentinel + exit code for the callers (session.py)."""
    print("RESULT: OK" if ok else "RESULT: FAIL")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    a = sys.argv
    # P1-4: the integration passes the email via OMODA_EMAIL (ephemeral env), not argv.
    # argv still works for manual use.
    if len(a) >= 2 and a[1] == "invia":
        _emit_result(invia(a[2] if len(a) >= 3 else os.environ.get("OMODA_EMAIL", "")))
    elif len(a) >= 3 and a[1] == "invia-sms":
        _emit_result(invia_sms(a[2], a[3] if len(a) > 3 else "39"))
    elif len(a) >= 4 and a[1] == "token":
        _emit_result(token(a[2], a[3]))
    elif len(a) >= 4 and a[1] == "token-sms":
        _emit_result(token(a[2], a[3], sms=True))
    else:
        print(__doc__)
