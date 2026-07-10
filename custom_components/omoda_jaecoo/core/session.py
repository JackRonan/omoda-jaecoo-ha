#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session.py — Omoda token health + OTP re-login driven by Home Assistant.

The token that makes the command buttons work lives in token.json (wake.TOKEN_PATH).
Two ways it can "fall over":
  1) the access_token expires normally  -> refresh() renews it with the refresh_token (NO OTP);
  2) the user opens the official app     -> the session is invalidated (424) and even the
                                           refresh isn't enough -> a new OTP is needed.

This module exposes the primitives the bridge wires to 3 HA entities:
  - check()         -> (ok, detail)      : is the token valid? (tries a BFF login)
  - refresh()       -> bool              : renews the access_token without OTP (keep-alive)
  - request_otp()   -> bool              : sends the OTP code to the email (login_omoda.py sends it)
  - confirm_otp(c)  -> (ok, detail)      : mints the token with the code (prova_token.py) then re-checks

request_otp/confirm_otp run login_omoda.py / prova_token.py AS A SUBPROCESS in the
OMODA_SRC_DIR folder (default = this same `core/` folder, where captcha_solver/omoda
also live) with the current python (sys.executable). In the HA component = HA's
python, which has the manifest's requirements (requests/pycryptodome/numpy/pillow).

Subprocess contract (H7): login_omoda.py and prova_token.py print to stdout a
stable sentinel line `RESULT: OK` / `RESULT: FAIL` and use the returncode (0 ok, !=0
error). request_otp/confirm_otp decide the outcome from returncode + sentinel, NOT from
localized substrings (which would change with the language of the messages).
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wake  # reuses _bff_login / _refresh_token / TOKEN_PATH

EMAIL     = os.environ.get("OMODA_EMAIL", "")   # PER-ACCOUNT: see omoda_jaecoo.env.example
# Folder with login_omoda.py / prova_token.py / omoda.py: by default they are in this same
# folder (package). Override with OMODA_SRC_DIR if they live elsewhere.
OMODA_DIR = os.environ.get("OMODA_SRC_DIR", HERE)
PYEXE     = sys.executable  # the bridge's venv (has captcha/sm4/requests)
_TIMEOUT  = int(os.environ.get("OMODA_OTP_TIMEOUT", "120"))


def check():
    """Returns (ok: bool, detail: str). ok=True if a BFF login with the current token succeeds."""
    try:
        ut, tu = wake._bff_login()
    except Exception as e:
        return False, f"network error: {type(e).__name__}"
    if ut:
        return True, "Session active ✅"
    return False, "Session expired ❌ — press «Request OTP code» (close the official app first)"


def refresh():
    """Renews the access_token with the refresh_token (without OTP). True if renewed."""
    try:
        return bool(wake._refresh_token())
    except Exception:
        return False


def _call_env():
    """Read the per-attempt inputs from os.environ AT CALL TIME, not at import (mirrors
    wake._token_path). The config flow writes OMODA_EMAIL/OMODA_SRC_DIR into os.environ before
    each attempt, but this module is cached in sys.modules, so the module-level EMAIL/OMODA_DIR
    would otherwise stay frozen on whatever the FIRST attempt (or setup) saw — which made a
    corrected email or a switched account keep failing until Home Assistant was restarted."""
    email = os.environ.get("OMODA_EMAIL", EMAIL)
    src_dir = os.environ.get("OMODA_SRC_DIR", OMODA_DIR)
    try:
        timeout = int(os.environ.get("OMODA_OTP_TIMEOUT", str(_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _TIMEOUT
    return email, src_dir, timeout


def request_otp(emit=lambda m: None):
    """Sends the OTP code to the user's email. True if the send succeeded."""
    email, src_dir, timeout = _call_env()
    emit("sending OTP code to email…")
    try:
        r = subprocess.run([PYEXE, "login_omoda.py", "invia", email],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        emit("OTP sending timed out — try again")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    # H7: outcome from returncode + stable sentinel, not from localized substrings
    if r.returncode == 0 and "RESULT: OK" in out:
        emit(f"📧 Code sent to {email} — enter it in the «OTP code» field and press «Confirm OTP»")
        return True
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    emit(f"OTP sending failed: {tail[:120]}")
    return False


def confirm_otp(code, emit=lambda m: None):
    """Mints the token with the OTP code. Returns (ok, detail)."""
    code = (code or "").strip()
    if not code:
        return False, "no code entered"
    email, src_dir, timeout = _call_env()
    emit("minting token with code…")
    try:
        r = subprocess.run([PYEXE, "prova_token.py", email, code],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "token minting timed out"
    out = (r.stdout or "") + (r.stderr or "")
    # H7: outcome from returncode + stable sentinel, not from localized substrings
    if r.returncode == 0 and "RESULT: OK" in out:
        ok, detail = check()
        return ok, ("Session restored ✅" if ok else "token minted but login still failing")
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    return False, f"code rejected: {tail[:120]}"


if __name__ == "__main__":
    print("check:", check())
