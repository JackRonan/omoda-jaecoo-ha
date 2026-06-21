"""Switch: clima (stato campo frontHVACState + comandi clima_on/clima_off).

Fonde il binary_sensor "Clima" (sola lettura) con i pulsanti Clima ON/OFF in un unico
interruttore. ON via app = climatizzazione a 21° per 15 min (vedi catalogo comandi).
Il toggle ATTUA sull'auto (= consenso esplicito dell'utente).
"""
from __future__ import annotations

from homeassistant.components.switch import (
    ENTITY_ID_FORMAT,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import Omoda9Entity, Omoda9OptimisticMixin, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([Omoda9ClimaSwitch(hass.data[DOMAIN][entry.entry_id])])


class Omoda9ClimaSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Climatizzazione: ON se frontHVACState != 0.

    Lo stato reale arriva via MQTT solo ad auto sveglia → dopo un comando si mostra
    subito lo stato target (ottimistico) e al riavvio di HA si ripristina l'ultimo noto."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Clima", "clima", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_on(self) -> bool | None:
        return field_on(self.coordinator.data.get("fields", {}).get("frontHVACState"))

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_on()
        return live if live is not None else self._restored

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("clima_on", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("clima_off", False)
