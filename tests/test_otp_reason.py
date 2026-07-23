"""Unit tests for the OTP-send result interpretation (core/otp_result.py).

Pure logic — no Home Assistant, no network — so it runs in a bare `pytest` env
(`pip install pytest && pytest -q tests/`). Guards the reason-parsing and the
reason -> speaking-error mapping used by the config flow.
"""
import json
import os
import sys

_COMP = os.path.join(os.path.dirname(__file__), "..", "custom_components", "omoda_jaecoo")
sys.path.insert(0, os.path.join(_COMP, "core"))

import otp_result as R  # noqa: E402


# ---- parse_fail_reason ---------------------------------------------------------

def test_parse_email_not_exists():
    out = ("Solving the captcha…\n"
           "sendMailCode -> HTTP 200 key=email.not.exists msg=x data=None\n"
           "RESULT: FAIL email.not.exists")
    assert R.parse_fail_reason(out) == "email.not.exists"


def test_parse_captcha_failed():
    out = "Solving the captcha…\n❌ captcha not solved, try again.\nRESULT: FAIL captcha.failed"
    assert R.parse_fail_reason(out) == "captcha.failed"


def test_parse_bare_fail_is_empty():
    # old-style sentinel without a reason -> nothing extracted (backward compatible)
    assert R.parse_fail_reason("boom\nRESULT: FAIL") == ""


def test_parse_no_sentinel_is_empty():
    assert R.parse_fail_reason("just some noise\nno sentinel here") == ""


def test_parse_success_has_no_fail_reason():
    assert R.parse_fail_reason("RESULT: OK") == ""


def test_parse_tolerates_indent_and_trailing_space():
    assert R.parse_fail_reason("   RESULT: FAIL   email.not.exists  ") == "email.not.exists"


def test_parse_none_or_empty():
    assert R.parse_fail_reason(None) == ""
    assert R.parse_fail_reason("") == ""


# ---- error_key -----------------------------------------------------------------

def test_error_key_known_reasons():
    assert R.error_key("email.not.exists") == "email_not_found"
    assert R.error_key("captcha.failed") == "captcha_failed"


def test_error_key_unknown_falls_back():
    assert R.error_key("some.new.backend.code") == "otp_send_failed"
    assert R.error_key("") == "otp_send_failed"
    assert R.error_key(None) == "otp_send_failed"
    assert R.error_key("OTP sending failed: RESULT: FAIL") == "otp_send_failed"


# ---- integration guard: mapped keys must exist in the UI strings ----------------

def test_mapped_error_keys_exist_in_strings():
    for fname in ("strings.json", os.path.join("translations", "en.json")):
        errs = json.load(open(os.path.join(_COMP, fname)))["config"]["error"]
        for key in R.ERROR_BY_REASON.values():
            assert key in errs, f"error key '{key}' missing from {fname}"
