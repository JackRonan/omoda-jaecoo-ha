"""session.py — status marker (P1-1) and email/OTP passed via env not argv (P1-4)."""
import importlib

import pytest

import session as SESSION
from conftest import FakeResp


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    importlib.reload(SESSION)
    monkeypatch.setenv("OMODA_EMAIL", "user@example.com")
    monkeypatch.setenv("OMODA_SRC_DIR", ".")
    yield


class _Run:
    def __init__(self):
        self.argv = None
        self.env = None

    def __call__(self, argv, **kw):
        self.argv = argv
        self.env = kw.get("env") or {}
        return FakeResp(text="")  # returncode/stdout set below via subclass

    class _R:
        returncode = 0
        stdout = "RESULT: OK\n"
        stderr = ""


def _fake_run(store):
    def run(argv, **kw):
        store["argv"] = argv
        store["env"] = kw.get("env") or {}
        r = _Run._R()
        return r
    return run


def test_check_status_markers(monkeypatch):
    monkeypatch.setattr(SESSION.wake, "_bff_login", lambda *a, **k: ("ut", "tu"))
    ok, _d, status = SESSION.check()
    assert ok and status == SESSION.STATUS_OK

    monkeypatch.setattr(SESSION.wake, "_bff_login", lambda *a, **k: (None, None))
    ok, _d, status = SESSION.check()
    assert not ok and status == SESSION.STATUS_EXPIRED

    def boom(*a, **k):
        raise ConnectionError("net down")
    monkeypatch.setattr(SESSION.wake, "_bff_login", boom)
    ok, _d, status = SESSION.check()
    assert not ok and status == SESSION.STATUS_NET_ERROR


def test_request_otp_passes_email_via_env_not_argv(monkeypatch):
    store = {}
    monkeypatch.setattr(SESSION.subprocess, "run", _fake_run(store))
    assert SESSION.request_otp() is True
    assert "user@example.com" not in store["argv"]          # email NOT on the command line
    assert store["env"].get("OMODA_EMAIL") == "user@example.com"


def test_confirm_otp_passes_code_via_env_not_argv(monkeypatch):
    store = {}
    monkeypatch.setattr(SESSION.subprocess, "run", _fake_run(store))
    monkeypatch.setattr(SESSION.wake, "_bff_login", lambda *a, **k: ("ut", "tu"))
    ok, _detail = SESSION.confirm_otp("654321")
    assert ok is True
    assert "654321" not in store["argv"]
    assert store["env"].get("OMODA_OTP") == "654321"
