"""commands.py — taskId minting error-routing (P0/P1) and command failure handling."""
import importlib

import pytest
import requests

import commands as CMD
from conftest import FakeResp


@pytest.fixture(autouse=True)
def _reset():
    # fresh module state each test (module globals like _PIN_FAIL/_TASKID_CACHE persist)
    importlib.reload(CMD)
    CMD.PIN = "1234"
    CMD.VIN = "VINTEST"
    CMD.MINT_TASKID = True
    yield


def _mock_checkpassword(monkeypatch, resp_payload):
    """Make every BFF POST return `resp_payload` (the checkPassword result is what matters)."""
    monkeypatch.setattr(CMD.wake, "_access_token", lambda: "access-tok")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(resp_payload))


def test_mint_returns_taskid_and_resets_counter(monkeypatch):
    _mock_checkpassword(monkeypatch, {"code": "000000", "data": {"taskId": "TID123"}})
    CMD._PIN_FAIL["n"] = 1
    assert CMD._mint_taskid("tuid") == "TID123"
    assert CMD._PIN_FAIL["n"] == 0            # success resets the anti-lockout


def test_session_code_routes_reauth_no_lockout(monkeypatch):
    _mock_checkpassword(monkeypatch, {"code": "A00000"})
    with pytest.raises(CMD.CommandError) as ei:
        CMD._mint_taskid("tuid")
    assert ei.value.reason == "reauth"
    assert CMD._PIN_FAIL["n"] == 0            # session error must NOT count as a wrong PIN


def test_config_code_routes_config_no_lockout(monkeypatch):
    _mock_checkpassword(monkeypatch, {"code": "A00374"})   # a permission/config code
    with pytest.raises(CMD.CommandError) as ei:
        CMD._mint_taskid("tuid")
    assert ei.value.reason == "config"
    assert CMD._PIN_FAIL["n"] == 0


def test_unknown_code_routes_pin_and_counts(monkeypatch):
    _mock_checkpassword(monkeypatch, {"code": "A09999"})   # unknown → conservative PIN branch
    with pytest.raises(CMD.CommandError) as ei:
        CMD._mint_taskid("tuid")
    assert ei.value.reason == "pin"
    assert CMD._PIN_FAIL["n"] == 1            # counts toward the anti-lockout


def test_empty_pin_raises_pin(monkeypatch):
    CMD.PIN = ""
    with pytest.raises(CMD.CommandError) as ei:
        CMD._mint_taskid("tuid")
    assert ei.value.reason == "pin"


def test_reset_pin_lockout():
    CMD._PIN_FAIL["n"] = 5
    CMD.reset_pin_lockout()
    assert CMD._PIN_FAIL["n"] == 0


def test_code_sets_and_retryable():
    assert "A00082" in CMD.FAILURE_CODES and "A00082" in CMD.RETRYABLE_CODES
    assert CMD.CommandError("busy", code="A00082").retryable is True
    assert CMD.CommandError("x", code="A00084").retryable is False


def test_send_raises_on_failure_code(monkeypatch):
    # a known command that goes through the full send() path
    key = CMD.COMMANDS[0][0]
    monkeypatch.setattr(CMD.wake, "_bff_login", lambda *a, **k: ("usertok", "tuid"))
    monkeypatch.setattr(CMD, "get_taskid", lambda tuid, emit=lambda m: None, allow_cache=True: ("TID", "cache"))

    class _Ctx:
        def __enter__(self): return FakeResp({"code": "A00084"})
        def __exit__(self, *a): return False
    monkeypatch.setattr(CMD.urllib.request, "urlopen", lambda *a, **k: _Ctx())
    with pytest.raises(CMD.CommandError) as ei:
        CMD.send(key)
    assert ei.value.code == "A00084"


def test_send_returns_on_success(monkeypatch):
    key = CMD.COMMANDS[0][0]
    monkeypatch.setattr(CMD.wake, "_bff_login", lambda *a, **k: ("usertok", "tuid"))
    monkeypatch.setattr(CMD, "get_taskid", lambda tuid, emit=lambda m: None, allow_cache=True: ("TID", "cache"))

    class _Ctx:
        def __enter__(self): return FakeResp({"code": "A00079"})
        def __exit__(self, *a): return False
    monkeypatch.setattr(CMD.urllib.request, "urlopen", lambda *a, **k: _Ctx())
    out = CMD.send(key)
    assert "A00079" in out                    # success surfaced, no raise
