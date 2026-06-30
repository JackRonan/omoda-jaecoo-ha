"""Button: i comandi auto (catalogo core/commands) + sveglia + aggiorna posizione."""
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
    import commands as CMD  # core/ sul path

    ents: list[ButtonEntity] = []
    for key, spec in CMD.COMMANDS:
        # i comandi che ora hanno un lock/switch/cover dedicato NON diventano pulsanti
        if key in COMMANDS_AS_RICH_ENTITY:
            continue
        ents.append(OmodaJaecooCommandButton(coord, key, spec))
    ents.append(OmodaJaecooActionButton(coord, "Omoda / Jaecoo Wake car", "wake", coord.async_wake))
    ents.append(OmodaJaecooActionButton(coord, "Omoda / Jaecoo Refresh location", "refresh_pos", coord.async_probe))
    # Aggiorna stato completo: forza odometro/batteria/tensione REALI accendendo brevemente il
    # clima (unico modo per accendere l'alta tensione, da cui dipendono i dati freschi).
    ents.append(OmodaJaecooActionButton(coord, "Omoda / Jaecoo Refresh full status", "refresh_full",
                                    coord.async_refresh_full_status))
    # recupero sessione: azioni "di servizio" → categoria diagnostica (fuori dai controlli)
    ents.append(OmodaJaecooActionButton(coord, "Omoda / Jaecoo Request OTP code", "otp_request",
                                    coord.async_request_otp, category=EntityCategory.DIAGNOSTIC))
    ents.append(OmodaJaecooActionButton(coord, "Omoda / Jaecoo Confirm OTP", "otp_confirm",
                                    coord.async_confirm_otp, category=EntityCategory.DIAGNOSTIC))
    add(ents)


class OmodaJaecooCommandButton(OmodaJaecooEntity, ButtonEntity):
    """Un pulsante per comando del catalogo. Il tap = consenso esplicito all'attuazione."""

    def __init__(self, coord, key: str, spec: dict) -> None:
        # entity_id = button.omoda_jaecoo_<key> (come il bridge), NON derivato dal nome lungo.
        super().__init__(coord, f"Omoda / Jaecoo {spec['name']}", f"cmd_{key}",
                         object_id=f"omoda_jaecoo_{key}", entity_id_format=ENTITY_ID_FORMAT)
        self._key = key
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    async def async_press(self) -> None:
        # [LOW] l'esito (anche di errore) è già pubblicato nei sensori diagnostici
        # (cmd_status) dal coordinator: qui logghiamo senza propagare un'eccezione grezza.
        try:
            await self.coordinator.async_send_command(self._key)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda / Jaecoo: command «%s» failed", self._key)


class OmodaJaecooActionButton(OmodaJaecooEntity, ButtonEntity):
    """Pulsante per un'azione del coordinator (sveglia/sonda)."""

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
        # [LOW] sveglia/sonda/OTP: l'esito va nei sensori diagnostici; logga e non
        # propagare un'eccezione grezza nella UI.
        try:
            await self._action()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda / Jaecoo: action «%s» failed", self._raw_name)
