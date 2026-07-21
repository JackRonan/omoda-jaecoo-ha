"""wake._bff_login refresh gating (P1-3), probe transient-code message, and codes map."""
import importlib

import pytest
import requests

import wake as WAKE
import probe as PROBE
import codes as CODES
from conftest import FakeResp


def test_bff_login_refreshes_on_missing_usertoken(monkeypatch):
    importlib.reload(WAKE)
    monkeypatch.setattr(WAKE, "_access_token", lambda: "acc")
    # first login returns data with NO userToken; refresh succeeds; retry returns a userToken.
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp({"data": {}})               # no userToken → should trigger refresh
        return FakeResp({"data": {"userToken": "UT", "tUserId": "TU"}})
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(WAKE, "_refresh_token", lambda: True)

    ut, tu = WAKE._bff_login()
    assert ut == "UT" and tu == "TU"
    assert calls["n"] == 2                              # refreshed + retried once


def test_bff_login_gives_up_without_refresh(monkeypatch):
    importlib.reload(WAKE)
    monkeypatch.setattr(WAKE, "_access_token", lambda: "acc")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"data": {}}))
    monkeypatch.setattr(WAKE, "_refresh_token", lambda: False)
    assert WAKE._bff_login() == (None, None)


def test_probe_transient_code_message_is_not_reauth(monkeypatch):
    importlib.reload(PROBE)
    monkeypatch.setattr(PROBE.W, "_bff_login", lambda *a, **k: ("ut", "tu"))
    monkeypatch.setattr(PROBE.W, "_signed_post", lambda ut, path, params: (200, {"code": "A00000"}))
    msgs = []
    res = PROBE.probe_once(msgs.append, force=True)
    assert res["ok"] is True and res["online"] is False
    joined = " ".join(msgs).lower()
    assert "isn't reporting" in joined or "not reporting" in joined
    assert "otp" not in joined                          # transient read must not tell the user to redo OTP


def test_codes_map():
    assert "A00082" in CODES.CODE_MEANING
    assert CODES.meaning("A00079")                      # returns a readable string
