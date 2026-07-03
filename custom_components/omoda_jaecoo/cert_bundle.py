"""Auto-provisioning of the MQTT mutual-TLS certificates (the car's EMQX broker).

The EMQX client certificates are **universal per-region constants** (`Subject: CN=client`),
**NOT** per-account data: they are identical for all users in a region. They come
verbatim from the **PUBLIC** assets of the official APK (`assets/tspemqx-app-<host>_*`), where
they are obfuscated with a fixed-keystream stream cipher and deobfuscated at runtime by
`libapp.so`. Here they are bundled in the same encrypted form + the keystream (see
`certs/store.json`) and deobfuscated at setup. No per-user data is sent.

Account isolation happens via MQTT username/password (clientId + md5) and topic ACLs,
NOT via the certificate → a single shared cert is the app's own model.
"""
from __future__ import annotations

import base64
import json
import os

_STORE = os.path.join(os.path.dirname(__file__), "certs", "store.json")
_REQUIRED = ("ca.pem", "client.pem", "client.key")


def _load() -> dict:
    with open(_STORE, encoding="utf-8") as f:
        return json.load(f)


def available_regions() -> list[str]:
    """MQTT hosts (regions) for which a bundled cert set exists."""
    try:
        return sorted(_load().get("regions", {}))
    except Exception:
        return []


def decrypt_region(host: str) -> dict[str, bytes] | None:
    """Return {'ca.pem','client.pem','client.key': bytes} for broker `host`, or None.

    Deobfuscates the assets (XOR with the fixed keystream, length-preserving) — identical to
    what `libapp.so` does when it loads the same assets from the APK."""
    try:
        store = _load()
        reg = store.get("regions", {}).get(host)
        if not reg:
            return None
        ks = base64.b64decode(store["ks"])
        out: dict[str, bytes] = {}
        for name in _REQUIRED:
            b64 = reg.get(name)
            if not b64:
                return None
            ct = base64.b64decode(b64)
            if len(ct) > len(ks):
                return None
            out[name] = bytes(c ^ ks[i] for i, c in enumerate(ct))
        return out
    except Exception:
        return None
