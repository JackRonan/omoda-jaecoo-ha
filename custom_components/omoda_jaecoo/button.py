"""Button: the car commands (core/commands catalog) + wake + refresh location."""
from __future__ import annotations

import logging

from homeassistant.components.button import ENTITY_ID_FORMAT, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COMMANDS_AS_RICH_ENTITY, DOMAIN
from .entity import OmodaJaecooEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    import commands as CMD  # core/ on the path

    ents: list[ButtonEntity] = []
    for key, spec in CMD.COMMANDS:
        # commands that now have a dedicated lock/switch/cover do NOT become buttons
        if key in COMMANDS_AS_RICH_ENTITY:
            continue
        ents.append(OmodaJaecooCommandButton(coord, key, spec))
    # service/diagnostic actions → all in the DIAGNOSTIC category so they group neatly
    # in the device's Diagnostic section, away from the primary vehicle controls.
    DIAG = EntityCategory.DIAGNOSTIC
    ents.append(OmodaJaecooActionButton(coord, "Diagnostic Wake Car", "wake", coord.async_wake, category=DIAG))
    ents.append(OmodaJaecooActionButton(coord, "Diagnostic Refresh Location", "refresh_pos", coord.async_probe, category=DIAG))
    # Refresh full status: forces REAL odometer/battery/voltage by briefly turning on the
    # climate (the only way to power the high-voltage bus that the fresh data depends on).
    ents.append(OmodaJaecooActionButton(coord, "Diagnostic Refresh Full Status", "refresh_full",
                                    coord.async_refresh_full_status, category=DIAG))
    ents.append(OmodaJaecooActionButton(coord, "Diagnostic Request OTP Code", "otp_request",
                                    coord.async_request_otp, category=DIAG))
    ents.append(OmodaJaecooActionButton(coord, "Diagnostic Confirm OTP", "otp_confirm",
                                    coord.async_confirm_otp, category=DIAG))
    add(ents)


class OmodaJaecooCommandButton(OmodaJaecooEntity, ButtonEntity):
    """One button per catalog command. The tap = explicit consent to actuate."""

    def __init__(self, coord, key: str, spec: dict) -> None:
        # entity_id = button.omoda_jaecoo_<key> (like the bridge), NOT derived from the long name.
        super().__init__(coord, spec['name'], f"cmd_{key}",
                         object_id=f"omoda_jaecoo_{key}", entity_id_format=ENTITY_ID_FORMAT)
        self._key = key
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    async def async_press(self) -> None:
        # [LOW] the outcome (including errors) is already published in the diagnostic sensors
        # (cmd_status) by the coordinator: here we log without propagating a raw exception.
        try:
            await self.coordinator.async_send_command(self._key)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda / Jaecoo: command «%s» failed", self._key)


class OmodaJaecooActionButton(OmodaJaecooEntity, ButtonEntity):
    """Button for a coordinator action (wake/probe)."""

    _ICONS = {
        "wake": "mdi:car-connected",
        "refresh_pos": "mdi:crosshairs-gps",
        "refresh_full": "mdi:car-info",
        "otp_request": "mdi:email-fast",
        "otp_confirm": "mdi:check-decagram",
    }

    def __init__(self, coord, name: str, suffix: str, action, category=None) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._action = action
        self._attr_icon = self._ICONS.get(suffix, "mdi:gesture-tap-button")
        if category is not None:
            self._attr_entity_category = category

    async def async_press(self) -> None:
        # [LOW] wake/probe/OTP: the outcome goes into the diagnostic sensors; log and do not
        # propagate a raw exception into the UI.
        try:
            await self._action()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda / Jaecoo: action «%s» failed", self._raw_name)
