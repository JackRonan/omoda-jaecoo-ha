#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session.py — salute del token Omoda + re-login OTP guidato da Home Assistant.

Il token che fa funzionare i pulsanti comando vive in token.json (wake.TOKEN_PATH).
Due modi in cui può "cadere":
  1) l'access_token scade normalmente  -> refresh() lo rinnova col refresh_token (NIENTE OTP);
  2) Rino apre l'app ufficiale          -> la sessione viene invalidata (424) e nemmeno il
                                           refresh basta -> serve un OTP nuovo.

Questo modulo espone le primitive che il ponte cabla a 3 entità HA:
  - check()         -> (ok, dettaglio)   : il token è valido? (prova un login BFF)
  - refresh()       -> bool              : rinnova l'access_token senza OTP (keep-alive)
  - request_otp()   -> bool              : invia il codice OTP alla mail (login_omoda.py invia)
  - confirm_otp(c)  -> (ok, dettaglio)   : conia il token col codice (prova_token.py)  poi ricontrolla

request_otp/confirm_otp girano login_omoda.py / prova_token.py COME SOTTOPROCESSO nella
cartella OMODA_SRC_DIR (default = questa stessa cartella `core/`, dove vivono anche
captcha_solver/omoda) col python corrente (sys.executable). Nel component HA = il python
di HA, che ha le requirements del manifest (requests/pycryptodome/numpy/pillow).

Contratto sottoprocessi (H7): login_omoda.py e prova_token.py stampano su stdout una
riga-sentinella stabile `RESULT: OK` / `RESULT: FAIL` e usano il returncode (0 ok, !=0
errore). request_otp/confirm_otp decidono l'esito su returncode + sentinella, NON su
sottostringhe localizzate (che cambierebbero con la lingua dei messaggi).
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wake  # riusa _bff_login / _refresh_token / TOKEN_PATH

EMAIL     = os.environ.get("OMODA_EMAIL", "")   # PER-ACCOUNT: vedi omoda_jaecoo.env.example
# Cartella con login_omoda.py / prova_token.py / omoda.py: di default sono in questa stessa
# cartella (pacchetto). Override con OMODA_SRC_DIR se vivono altrove.
OMODA_DIR = os.environ.get("OMODA_SRC_DIR", HERE)
PYEXE     = sys.executable  # il venv del ponte (ha captcha/sm4/requests)
_TIMEOUT  = int(os.environ.get("OMODA_OTP_TIMEOUT", "120"))


def check():
    """Ritorna (ok: bool, dettaglio: str). ok=True se un login BFF col token attuale riesce."""
    try:
        ut, tu = wake._bff_login()
    except Exception as e:
        return False, f"errore rete: {type(e).__name__}"
    if ut:
        return True, "Session active ✅"
    return False, "Session expired ❌ — press «Request OTP code» (close the official app first)"


def refresh():
    """Rinnova l'access_token col refresh_token (senza OTP). True se rinnovato."""
    try:
        return bool(wake._refresh_token())
    except Exception:
        return False


def request_otp(emit=lambda m: None):
    """Invia il codice OTP alla mail di Rino. True se l'invio è andato a buon fine."""
    emit("sending OTP code to email…")
    try:
        r = subprocess.run([PYEXE, "login_omoda.py", "invia", EMAIL],
                           cwd=OMODA_DIR, capture_output=True, text=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        emit("OTP sending timed out — try again")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        emit(f"📧 Code sent to {EMAIL} — enter it in the «OTP code» field and press «Confirm OTP»")
        return True
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    emit(f"OTP sending failed: {tail[:120]}")
    return False


def confirm_otp(code, emit=lambda m: None):
    """Conia il token col codice OTP. Ritorna (ok, dettaglio)."""
    code = (code or "").strip()
    if not code:
        return False, "no code entered"
    emit("minting token with code…")
    try:
        r = subprocess.run([PYEXE, "prova_token.py", EMAIL, code],
                           cwd=OMODA_DIR, capture_output=True, text=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "token minting timed out"
    out = (r.stdout or "") + (r.stderr or "")
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        ok, detail = check()
        return ok, ("Session restored ✅" if ok else "token minted but login still failing")
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    return False, f"code rejected: {tail[:120]}"


if __name__ == "__main__":
    print("check:", check())
