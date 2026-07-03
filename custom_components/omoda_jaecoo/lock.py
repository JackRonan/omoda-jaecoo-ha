"""Lock: door lock (state of doorLock field + lock/unlock commands).

Merges into a single native entity what were previously two separate things: the
"Lock" sensor (read-only) and the two Lock/Unlock buttons. Tapping lock/unlock
ACTS on the car (= explicit consent from the user), like the old buttons.
"""
from __future__ import annotations

from homeassistant.components.lock import ENTITY_ID_FORMAT, LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import OmodaJaecooEntity, OmodaJaecooOptimisticMixin, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([OmodaJaecooLock(hass.data[DOMAIN][entry.entry_id])])


class OmodaJaecooLock(OmodaJaecooOptimisticMixin, OmodaJaecooEntity, LockEntity, RestoreEntity):
    """Car lock: 0=Locked, 1=Unlocked (doorLock field).

    The real state arrives via MQTT only when the car is awake → after a command the
    target state is shown immediately (optimistic, see OmodaJaecooOptimisticMixin) and on
    HA restart the last known state is restored."""

    _attr_icon = "mdi:car-door-lock"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Lock", "lock", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("locked", "unlocked"):
            self._restored = last.state == "locked"

    def _live_locked(self) -> bool | None:
        # doorLock: 0 = Locked, !=0 = Unlocked → locked = NOT field_on (aligned
        # with binary/switch/cover, "0.0" included). field_on None = field absent.
        on = field_on(self.coordinator.data.get("fields", {}).get("doorLock"))
        return None if on is None else not on

    @property
    def is_locked(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_locked()
        return live if live is not None else self._restored

    async def async_lock(self, **kwargs) -> None:
        await self._run_command("blocca", True)

    async def async_unlock(self, **kwargs) -> None:
        await self._run_command("sblocca", False)
