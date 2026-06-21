"""Button: i comandi auto (catalogo core/commands) + sveglia + aggiorna posizione."""
from __future__ import annotations

from homeassistant.components.button import ENTITY_ID_FORMAT, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    import commands as CMD  # core/ sul path

    ents: list[ButtonEntity] = []
    for key, spec in CMD.COMMANDS:
        ents.append(Omoda9CommandButton(coord, key, spec))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Sveglia auto", "wake", coord.async_wake))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Aggiorna posizione", "refresh_pos", coord.async_probe))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Richiedi codice OTP", "otp_request", coord.async_request_otp))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Conferma OTP", "otp_confirm", coord.async_confirm_otp))
    add(ents)


class Omoda9CommandButton(Omoda9Entity, ButtonEntity):
    """Un pulsante per comando del catalogo. Il tap = consenso esplicito all'attuazione."""

    def __init__(self, coord, key: str, spec: dict) -> None:
        # entity_id = button.omoda9_<key> (come il bridge), NON derivato dal nome lungo.
        super().__init__(coord, f"Omoda9 {spec['name']}", f"cmd_{key}",
                         object_id=f"omoda9_{key}", entity_id_format=ENTITY_ID_FORMAT)
        self._key = key
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(self._key)


class Omoda9ActionButton(Omoda9Entity, ButtonEntity):
    """Pulsante per un'azione del coordinator (sveglia/sonda)."""

    _ICONS = {
        "wake": "mdi:car-connected",
        "refresh_pos": "mdi:crosshairs-gps",
        "otp_request": "mdi:email-fast",
        "otp_confirm": "mdi:check-decagram",
    }

    def __init__(self, coord, name: str, suffix: str, action) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._action = action
        self._attr_icon = self._ICONS.get(suffix, "mdi:gesture-tap-button")

    async def async_press(self) -> None:
        await self._action()
