"""Config flow Omoda 9 / Jaecoo — autenticazione per-utente (OTP via email).

Questo È il "sistema di autenticazione per gli altri utenti": ogni utente inserisce
le proprie credenziali (email/PIN/VIN/tUserId) e fa il login OTP dalla UI di HA.
Le credenziali finiscono nel config_entry del SUO Home Assistant (nessun server
centrale, nessun dato condiviso). Riusa il flusso OTP già verificato in core/.

Flusso:
  1) async_step_user  → email, PIN, VIN, tUserId (+ regione opzionale) → invia OTP
  2) async_step_otp   → codice ricevuto via email → conia il token → crea l'entry
"""
from __future__ import annotations

import os
import sys
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PIN, CONF_VIN, CONF_TUSERID,
    CONF_BFF, CONF_TSP_HOST, CONF_CERTS_SRC, DEFAULTS,
)

_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def _prepare_env(hass: HomeAssistant, data: dict) -> None:
    """Imposta l'ambiente per i moduli core/ (lette a import-time) dai dati del flow."""
    from .const import CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, CONF_CHANNEL_ID
    os.environ["OMODA_EMAIL"] = data[CONF_EMAIL]
    os.environ["OMODA_PIN"] = data[CONF_PIN]
    os.environ["VIN"] = data[CONF_VIN]
    os.environ["TUSERID"] = data[CONF_TUSERID]
    os.environ["CHANNEL_ID"] = str(data.get(CONF_CHANNEL_ID, DEFAULTS[CONF_CHANNEL_ID]))
    os.environ["OMODA_BFF"] = data.get(CONF_BFF, DEFAULTS[CONF_BFF])
    os.environ["TSP_HOST"] = data.get(CONF_TSP_HOST, DEFAULTS[CONF_TSP_HOST])
    os.environ["OMODA_TOKEN_PATH"] = hass.config.path(f"{DOMAIN}_{data[CONF_VIN]}_token.json")
    os.environ["OMODA_SRC_DIR"] = _CORE


def _session_ok(hass: HomeAssistant, data: dict) -> bool:
    """True se esiste già un token valido per questo VIN (executor) → core.session.check.

    È il path di MIGRAZIONE/riuso: se un token valido è già presente nella token_path
    per-entry (es. copiato dal bridge), si crea l'entry SENZA OTP. Necessario anche su
    HAOS, dove il captcha del login OTP (opencv) non è installabile.
    """
    _prepare_env(hass, data)
    token_path = os.environ.get("OMODA_TOKEN_PATH", "")
    if not token_path or not os.path.isfile(token_path):
        return False
    import session as SESSION
    try:
        ok, _ = SESSION.check()
        return bool(ok)
    except Exception:
        return False


def _send_otp(hass: HomeAssistant, data: dict) -> tuple[bool, str]:
    """Invia il codice OTP all'email (executor) → core.session.request_otp."""
    _prepare_env(hass, data)
    import session as SESSION
    msgs: list[str] = []
    ok = SESSION.request_otp(emit=msgs.append)
    return ok, (msgs[-1] if msgs else "")


def _mint_token(hass: HomeAssistant, data: dict, code: str) -> tuple[bool, str]:
    """Conia il token dal codice OTP (executor) → core.session.confirm_otp."""
    _prepare_env(hass, data)
    import session as SESSION
    return SESSION.confirm_otp(code)


class Omoda9ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il config flow dell'integrazione."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            await self.async_set_unique_id(user_input[CONF_VIN])
            self._abort_if_unique_id_configured()
            # Path di riuso/migrazione: token valido già presente → entry senza OTP.
            if await self.hass.async_add_executor_job(_session_ok, self.hass, self._data):
                return self.async_create_entry(
                    title=f"Omoda 9 ({self._data.get(CONF_VIN, '')})",
                    data=self._data,
                )
            try:
                ok, msg = await self.hass.async_add_executor_job(
                    _send_otp, self.hass, self._data
                )
            except NotImplementedError:
                # scaffold: salta l'invio finché il wiring core non è completato
                return await self.async_step_otp()
            if ok:
                return await self.async_step_otp()
            errors["base"] = "otp_send_failed"

        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PIN): str,
            vol.Required(CONF_VIN): str,
            vol.Required(CONF_TUSERID): str,
            vol.Optional(CONF_BFF, default=DEFAULTS[CONF_BFF]): str,
            vol.Optional(CONF_TSP_HOST, default=DEFAULTS[CONF_TSP_HOST]): str,
            # FASE 3c: cartella (dentro il filesystem di HA) coi 4 cert mutual-TLS da
            # importare. Vuoto = si mettono a mano in omoda9_<VIN>_certs/.
            vol.Optional(CONF_CERTS_SRC, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_otp(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok, msg = await self.hass.async_add_executor_job(
                    _mint_token, self.hass, self._data, user_input["code"].strip()
                )
            except NotImplementedError:
                ok, msg = True, "scaffold"  # consente di completare il flow in dev
            if ok:
                return self.async_create_entry(
                    title=f"Omoda 9 ({self._data.get(CONF_VIN, '')})",
                    data=self._data,
                )
            errors["base"] = "otp_invalid"

        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(step_id="otp", data_schema=schema, errors=errors)
