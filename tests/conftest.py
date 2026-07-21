"""Test bootstrap. The integration's `core/` modules import each other by bare name and read
their config from the environment; add core/ to sys.path so they import in isolation, WITHOUT
requiring Home Assistant (these are the pure protocol/auth modules)."""
import os
import sys

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "custom_components", "omoda_jaecoo", "core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)


class FakeResp:
    """Minimal stand-in for a requests/urllib response."""
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload if payload is not None else {}
        self.text = text or ""
        self.status_code = status
        self.status = status
        self.code = status

    def json(self):
        return self._payload

    def read(self):
        import json
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
