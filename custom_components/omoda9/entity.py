"""Base entity Omoda 9: aggancio al coordinator + device_info comune.

Continuità entity_id (FASE 3d): per non perdere storico recorder/dashboard al
cutover dal bridge, ogni entità FORZA il proprio `entity_id` invece di lasciarlo
derivare implicitamente. L'object_id di default = slugify(nome) — che riproduce
ESATTAMENTE gli id `omoda9_*` già generati dal bridge (has_entity_name=False →
HA slugifica il solo nome). Dove il bridge usa un id non derivabile dal nome
(es. i pulsanti comando = `omoda9_<key>`) si passa `object_id` esplicito.
"""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import Omoda9Coordinator


class Omoda9Entity(CoordinatorEntity[Omoda9Coordinator]):
    """Entità base: device unico 'Omoda 9' identificato dal VIN."""

    # has_entity_name=False + nomi espliciti "Omoda9 …" → entity_id stile bridge.
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: Omoda9Coordinator,
        name: str,
        unique_suffix: str,
        *,
        object_id: str | None = None,
        entity_id_format: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.vin}_{unique_suffix}"
        # entity_id ESPLICITO = continuità col bridge (default = slugify(name)).
        if entity_id_format:
            self.entity_id = entity_id_format.format(object_id or slugify(name))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            name="Omoda 9",
            manufacturer="Omoda",
            model="Omoda 9",
        )
