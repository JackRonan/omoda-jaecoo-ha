"""Pure helpers to interpret the OTP-send subprocess result.

No Home Assistant, no network, no environment reads — so this behaviour is
unit-testable in isolation (see tests/test_otp_reason.py).

The login subprocess (login_omoda.py) ends with a stable sentinel line — either
`RESULT: OK` or `RESULT: FAIL <reason>` — where <reason> is a backend code such as
`email.not.exists` or `captcha.failed`. The reason carries no PIN, OTP or token.
"""

_FAIL = "RESULT: FAIL"

# Backend reason codes → specific, speaking config-flow error keys (defined in
# strings.json / translations). Unknown reasons fall back to the generic
# `otp_send_failed`, so a new/unmapped backend code is surfaced, never swallowed.
ERROR_BY_REASON = {
    "email.not.exists": "email_not_found",
    "captcha.failed": "captcha_failed",
}


def parse_fail_reason(out):
    """Return the reason code carried by the FAIL sentinel in `out`, or "" when the
    output has no sentinel or only an old-style bare `RESULT: FAIL` (backward compat)."""
    for line in (out or "").splitlines():
        s = line.strip()
        if s.startswith(_FAIL):
            return s[len(_FAIL):].strip()
    return ""


def error_key(reason):
    """Map a reason code (or any fallback message) to a config-flow error key."""
    return ERROR_BY_REASON.get((reason or "").strip(), "otp_send_failed")
