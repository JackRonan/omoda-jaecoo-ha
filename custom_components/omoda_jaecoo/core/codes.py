#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — SINGLE map of tspconsole/BFF Chery response codes → readable text.

Source of truth for the ONLY diagnostic texts shown to the user (HA/monitor).
Before PHASE 1 the same code (e.g. A07900) had 3 different meanings
scattered across commands/wake/probe/provision; this map unifies them. It does NOT change the
command logic: the modules decide the flow on the codes, here there's only the
translation of the code into a phrase.

⚠️ Some codes (first of all A07900) are CONTEXTUAL on the Chery backend: the text
here is the most recurring/useful one; each caller can add context.
"""

# Code → readable phrase (English, for non-technical users).
CODE_MEANING = {
    "000000": "ok ✅",
    "A00079": "command accepted ✅",
    # A00082: the car is BUSY (it processes one command at a time) → the command was NOT
    # executed. Transient: retry in a few seconds (verified live 2026-06-21).
    "A00082": "car busy ⏳ (another command is in progress) — retry in a few seconds",
    # A00084 (i18n: "No vehicle control command permission"): the account/vehicle does not have
    # permission FOR THAT command. Seen live on remoteStart (2026-06-21): our Omoda / Jaecoo
    # does not allow remote engine start, while climate/lock/GPS work.
    "A00084": "command not allowed on this car 🚫 (permission denied for this function)",
    "A00089": "invalid taskId ❌ (requires a taskId authenticated by checkPassword)",
    "A00546": "invalid taskId ❌ (incorrect scene in checkPassword)",
    "A00567": "incomplete checkPassword parameters ❌",
    "A00000": "token expired/invalid ❌ (please redo OTP login)",
    "A07312": "wake rate-limit 🚫 (car is refusing further wake requests right now, try again later)",
    # A07900 is contextual: in poll/probe = car at rest; with commands = invalid signature or
    # car_token. Neutral text that covers the most frequent case.
    "A07900": "car asleep / unreachable (or signature/car_token invalid) ⌛",
}


def meaning(code, default=None):
    """Returns the readable phrase for `code`. If unknown returns `default`
    (or a generic string with the raw code). Also accepts code=None/non-str."""
    if code is None:
        return default if default is not None else "no code"
    key = str(code)
    if key in CODE_MEANING:
        return CODE_MEANING[key]
    return default if default is not None else f"code {key}"


if __name__ == "__main__":
    for c in ("000000", "A00079", "A07900", "A99999", None):
        print(f"{c!s:>8} -> {meaning(c)}")
