"""Config flow Omoda / Jaecoo / Jaecoo — per-user login with ONLY email + PIN.

No more VIN/tUserId to enter by hand: they are discovered from the backend after the OTP
(`tsp/v1/app/auth/login` → tUserId, `tsp/v1/app/vmc/queryList` → VIN). The credentials
stay in the config_entry of YOUR Home Assistant (no central server).

Flow:
  1) user            → email, PIN (+ optional region) → solves the captcha and sends the OTP
  2) otp             → code received via email → mints the token → discovers tUserId + VIN
  3) select_vehicle  → (only if the account has multiple vehicles) VIN selection
  → creates the entry
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PIN, CONF_VIN, CONF_TUSERID,
    CONF_BFF, CONF_TSP_HOST, CONF_CERTS_SRC, CONF_CHANNEL_ID,
    CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, DEFAULTS,
    CONF_POLL_NORMAL, CONF_POLL_CHARGING,
    DEFAULT_POLL_NORMAL_MIN, DEFAULT_POLL_CHARGING_MIN,
    CONF_VEHICLE_NAME, capabilities_from_item,
)

_LOGGER = logging.getLogger(__name__)

_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def _pending_token_path(hass: HomeAssistant) -> str:
    """Temporary path where the token is minted until the VIN is known."""
    return hass.config.path("omoda9_pending_token.json")


def _prepare_env(hass: HomeAssistant, data: dict, token_path: str | None = None) -> None:
    """Set up the environment for the core/ modules (read at import-time) from the flow data."""
    os.environ["OMODA_EMAIL"] = data.get(CONF_EMAIL, "")
    os.environ["OMODA_PIN"] = data.get(CONF_PIN, "")
    os.environ["VIN"] = data.get(CONF_VIN, "")
    os.environ["TUSERID"] = data.get(CONF_TUSERID, "")
    os.environ["CHANNEL_ID"] = str(data.get(CONF_CHANNEL_ID, DEFAULTS[CONF_CHANNEL_ID]))
    os.environ["OMODA_BFF"] = data.get(CONF_BFF, DEFAULTS[CONF_BFF])
    os.environ["TSP_HOST"] = data.get(CONF_TSP_HOST, DEFAULTS[CONF_TSP_HOST])
    os.environ["OMODA_LANGUAGE"] = "it-IT"
    os.environ["OMODA_DEPT_ID"] = "39"
    os.environ["OMODA_TOKEN_PATH"] = token_path or _pending_token_path(hass)
    os.environ["OMODA_SRC_DIR"] = _CORE


def _send_otp(hass: HomeAssistant, data: dict, token_path: str | None = None) -> tuple[bool, str]:
    """Solves the captcha and sends the OTP to the email (executor) → core.session.request_otp."""
    _prepare_env(hass, data, token_path)
    import session as SESSION
    msgs: list[str] = []
    ok = SESSION.request_otp(emit=msgs.append)
    return ok, (msgs[-1] if msgs else "")


def _mint_token(hass: HomeAssistant, data: dict, code: str,
                token_path: str | None = None) -> tuple[bool, str]:
    """Mints the token from the OTP code (executor) → core.session.confirm_otp.
    token_path=None mints to the pending path (initial setup); a per-VIN path is passed
    during re-authentication so the fresh token lands where the coordinator reads it."""
    _prepare_env(hass, data, token_path)
    import session as SESSION
    return SESSION.confirm_otp(code)


def _discover(hass: HomeAssistant, data: dict) -> tuple[bool, str, list[str], list[dict], str]:
    """After the OTP: discovers (tUserId, [VIN], [vehicle items]) from the just-minted token.
    Read-only. Returns (ok, tuserid, vins, vehicles, detail)."""
    _prepare_env(hass, data)
    try:
        import requests
        import omoda_auth as A
        import wake
        wake.TOKEN_PATH = _pending_token_path(hass)   # just-minted token
        _ut, tu = wake._bff_login()
        if not tu:
            return False, "", [], [], "backend login failed"
        access = wake._access_token()
        headers = A.headers_post("/tsp/v1/app/vmc/queryList", extra={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*"})
        r = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList",
                          data=json.dumps({}), headers=headers, timeout=25)
        j = r.json()
        lst = j.get("data")
        vins: list[str] = []
        vehicles: list[dict] = []
        if isinstance(lst, list):
            for v in lst:
                if isinstance(v, dict) and v.get("vin"):
                    vins.append(str(v["vin"]))
                    vehicles.append(v)
        return True, str(tu), vins, vehicles, ("ok" if vins else "no vehicle found")
    except Exception as e:  # noqa: BLE001
        return False, "", [], [], f"vehicle discovery error: {type(e).__name__}"


def _finalize_token(hass: HomeAssistant, vin: str) -> bool:
    """Moves the 'pending' token to the definitive per-VIN token-path.

    Returns True if the token is in place (moved now or already present),
    False if the move fails: in that case the flow must be failed,
    because without a token the coordinator could not authenticate."""
    pend = _pending_token_path(hass)
    dest = hass.config.path(f"omoda9_{vin}_token.json")
    try:
        if os.path.isfile(pend):
            os.replace(pend, dest)
        return os.path.isfile(dest)
    except OSError as e:
        _LOGGER.error("Omoda / Jaecoo: unable to move the token to %s: %s", dest, e)
        return False


def _cleanup_pending(hass: HomeAssistant) -> None:
    """Removes any orphaned *_pending_token.json (OTP that failed / was aborted)."""
    pend = _pending_token_path(hass)
    try:
        if os.path.isfile(pend):
            os.remove(pend)
    except OSError as e:  # noqa: BLE001
        _LOGGER.debug("Omoda / Jaecoo: pending token cleanup failed: %s", e)


class OmodaJaecooConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handles the integration's config flow (email + PIN, the rest is discovered)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._tuserid: str = ""
        self._vins: list[str] = []
        self._vehicles: list[dict] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "OmodaJaecooOptionsFlow":
        return OmodaJaecooOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            ok, _msg = await self.hass.async_add_executor_job(
                _send_otp, self.hass, self._data
            )
            if ok:
                return await self.async_step_otp()
            errors["base"] = "otp_send_failed"

        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PIN): str,
            # Only for regions outside Europe / advanced setup (default EU).
            vol.Optional(CONF_BFF, default=DEFAULTS[CONF_BFF]): str,
            vol.Optional(CONF_TSP_HOST, default=DEFAULTS[CONF_TSP_HOST]): str,
            # Car's MQTT broker + channel id: region-specific (default EU). Without
            # these fields a non-EU setup would stay hooked to the European broker.
            vol.Optional(CONF_CAR_MQTT_HOST, default=DEFAULTS[CONF_CAR_MQTT_HOST]): str,
            vol.Optional(CONF_CAR_MQTT_PORT, default=DEFAULTS[CONF_CAR_MQTT_PORT]): vol.Coerce(int),
            vol.Optional(CONF_CHANNEL_ID, default=DEFAULTS[CONF_CHANNEL_ID]): str,
            vol.Optional(CONF_CERTS_SRC, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_otp(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            ok, _msg = await self.hass.async_add_executor_job(
                _mint_token, self.hass, self._data, user_input["code"].strip()
            )
            if ok:
                d_ok, tu, vins, vehicles, _detail = await self.hass.async_add_executor_job(
                    _discover, self.hass, self._data
                )
                if not d_ok or not vins:
                    # Token minted but no vehicle: the pending token is unusable.
                    await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
                    errors["base"] = "no_vehicle"
                else:
                    self._tuserid = tu
                    self._vins = vins
                    self._vehicles = vehicles
                    if len(vins) == 1:
                        return await self._create_entry(vins[0])
                    return await self.async_step_select_vehicle()
            else:
                # Wrong/expired OTP: discard any pending token already written.
                await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
                errors["base"] = "otp_invalid"

        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(step_id="otp", data_schema=schema, errors=errors)

    async def async_step_select_vehicle(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return await self._create_entry(user_input[CONF_VIN])
        schema = vol.Schema({vol.Required(CONF_VIN): vol.In(self._vins)})
        return self.async_show_form(step_id="select_vehicle", data_schema=schema)

    async def _create_entry(self, vin: str):
        # VIN uniqueness as early as possible: as soon as we know the VIN, before creating
        # the entry. NB: for a single-VIN account the OTP has already been spent by the time
        # we get here — the backend does not expose the VIN before authentication,
        # so it is not possible to abort as "already configured" before the OTP.
        await self.async_set_unique_id(vin)
        try:
            self._abort_if_unique_id_configured()
        except AbortFlow:
            # VIN already configured: the just-minted token is not needed, remove it.
            await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
            raise
        self._data[CONF_VIN] = vin
        self._data[CONF_TUSERID] = self._tuserid
        # Persist the per-vehicle capabilities (powertrain, climate range) discovered from
        # queryList so entities can adapt from the very first setup (no backfill reload needed).
        item = next((v for v in self._vehicles if str(v.get("vin")) == vin), None)
        if item is not None:
            self._data.update(capabilities_from_item(item))
        ok = await self.hass.async_add_executor_job(_finalize_token, self.hass, vin)
        if not ok:
            await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
            return self.async_abort(reason="token_move_failed")
        return self.async_create_entry(title=f"Omoda / Jaecoo ({vin})", data=self._data)

    # ───────────────────────── re-authentication (session expired → new OTP) ─────────────────
    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Triggered by the coordinator when the session hard-expires (needs a fresh OTP).
        HA shows the "needs re-authentication" notification and opens this flow."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"])
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Re-login: on first display send a fresh OTP to the account email; on submit mint a
        new token into the existing per-VIN path and reload the entry."""
        entry = self._reauth_entry
        vin = (entry.data if entry else {}).get(CONF_VIN, "")
        token_path = self.hass.config.path(f"omoda9_{vin}_token.json")
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input["code"].strip()
            ok, _detail = await self.hass.async_add_executor_job(
                _mint_token, self.hass, self._data, code, token_path)
            if ok:
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = "otp_invalid"
        else:
            # first display → send the OTP code to the account email
            ok, _msg = await self.hass.async_add_executor_job(
                _send_otp, self.hass, self._data, token_path)
            if not ok:
                errors["base"] = "otp_send_failed"

        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors,
            description_placeholders={"email": self._data.get(CONF_EMAIL, "")})


class OmodaJaecooOptionsFlow(config_entries.OptionsFlow):
    """Options: the two telemetry poll intervals (minutes). 0 = disabled.

    `poll_normal_min` = at rest/parked; `poll_charging_min` = when the car is
    plugged into the charger (usually shorter, to follow the charging)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opt = self._entry.options or {}
        # current vehicle name (override or the detected one), to pre-fill the field
        cur_name = opt.get(CONF_VEHICLE_NAME) or self._entry.data.get(CONF_VEHICLE_NAME) or ""
        schema = vol.Schema({
            vol.Optional(
                CONF_POLL_NORMAL,
                default=opt.get(CONF_POLL_NORMAL, DEFAULT_POLL_NORMAL_MIN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
            vol.Optional(
                CONF_POLL_CHARGING,
                default=opt.get(CONF_POLL_CHARGING, DEFAULT_POLL_CHARGING_MIN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
            # manual override of the vehicle name (empty = use the one detected from the car)
            vol.Optional(
                CONF_VEHICLE_NAME,
                description={"suggested_value": cur_name},
            ): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
