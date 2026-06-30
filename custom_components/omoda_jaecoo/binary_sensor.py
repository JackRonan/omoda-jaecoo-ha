"""Binary sensor: porte/finestrini/cofano/baule (open) + comfort on/off + stato auto.

Lo stato fisico dell'auto (5A02) e la connettività sono in-memory nel coordinator →
dopo un riavvio di HA tornano `unknown`. I binary_sensor di stato sono RestoreEntity:
ripristinano l'ultimo on/off noto come fallback (parità col bridge, che persisteva via
MQTT retained) finché non arriva un dato live. Eccezione: `auto_sveglia` NON persiste
(è un flag derivato "l'auto sta pubblicando adesso" → al boot deve essere off).
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, FIELDS_AS_RICH_ENTITY
from .coordinator import SENSORS
from .entity import OmodaJaecooEntity, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [
        OmodaJaecooBinarySensor(coord, s)
        for s in SENSORS
        if s["comp"] == "binary_sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY
    ]
    ents.append(OmodaJaecooOnline(coord))
    ents.append(OmodaJaecooAwake(coord))
    ents.append(OmodaJaecooSession(coord))
    # — avvisi dal canale realtime (Round B): gomme + batteria scarica —
    for suffix, name, field, dc in _RT_BINARIES:
        ents.append(OmodaJaecooRealtimeBinary(coord, name, suffix, field, dc))
    add(ents)


# Avvisi (warning) presenti sul canale realtime: ON = anomalia. `*TyreCall` = avviso
# pressione gomma (device_class PROBLEM); `socLowCall` = batteria di trazione scarica
# (device_class BATTERY → on = "low"). Convenzione ON/OFF (1=avviso) da confermare dal
# vivo. (suffix, nome, campo realtime, device_class)
_RT_BINARIES = [
    ("front_left_tire_warning", "Front left tire warning", "lFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("front_right_tire_warning", "Front right tire warning", "rFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("rear_left_tire_warning", "Rear left tire warning", "lRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("rear_right_tire_warning", "Rear right tire warning", "rRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("battery_low", "Battery low", "socLowCall", BinarySensorDeviceClass.BATTERY),
]


class _OmodaJaecooRestoreBinary(OmodaJaecooEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor che ripristina l'ultimo stato on/off al riavvio di HA.

    Le sottoclassi forniscono `_live_is_on()` (stato corrente dal coordinator, o
    None se assente); finché il live è None si usa l'ultimo valore ripristinato."""

    def __init__(self, coord, name: str, unique_suffix: str) -> None:
        super().__init__(coord, name, unique_suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_is_on(self) -> bool | None:
        raise NotImplementedError

    @property
    def is_on(self) -> bool | None:
        live = self._live_is_on()
        return live if live is not None else self._restored


class OmodaJaecooBinarySensor(_OmodaJaecooRestoreBinary):
    """ON se il campo è != 0 (open/onoff)."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda / Jaecoo {spec['name']}", spec["key"])
        self._key = spec["key"]
        dc = spec.get("dclass")
        self._attr_device_class = BinarySensorDeviceClass(dc) if dc else None
        # campi che l'auto non invia mai da ferma (es. tendina tetto, risc. parabrezza):
        # restano sempre "unknown" → in categoria diagnostica, fuori dai controlli principali.
        if spec.get("diag"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _live_is_on(self) -> bool | None:
        # [MED] None/"None"/"" = assente → None (emerge il restored, non un falso off);
        # confronto numerico via field_on (allinea "0.0" con lock/switch/cover).
        return field_on(self.coordinator.data.get("fields", {}).get(self._key))


class OmodaJaecooOnline(_OmodaJaecooRestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda / Jaecoo Connessione", "online")
        # entity_id PINNED allo storico `omoda_jaecoo_connessa` (dashboard/automazioni non si rompono);
        # translation_key forzato a "connessa" per combaciare con la chiave in translations/*.json
        # (altrimenti la base la deriverebbe da "Connessione" → "connessione", chiave inesistente).
        self.entity_id = ENTITY_ID_FORMAT.format("omoda_jaecoo_connessa")
        self._attr_translation_key = "connessa"

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt["onlineStatus"]) if "onlineStatus" in rt else None


class OmodaJaecooRealtimeBinary(_OmodaJaecooRestoreBinary):
    """Avviso generico su un campo del canale realtime (vedi `_RT_BINARIES`).

    Stesso pattern di `OmodaJaecooOnline` (legge da coordinator.data["realtime"]) ma in
    categoria diagnostica. ON se il campo è != 0; assente → ripristina l'ultimo noto."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, field: str,
                 device_class: BinarySensorDeviceClass) -> None:
        super().__init__(coord, f"Omoda / Jaecoo {name}", f"rt_{suffix}")
        self._field = field
        self._attr_device_class = device_class

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt[self._field]) if self._field in rt else None


class OmodaJaecooAwake(OmodaJaecooEntity, BinarySensorEntity):
    """Flag derivato "l'auto sta pubblicando adesso" — NON persistente (off al boot)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda / Jaecoo Car awake", "awake",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("awake"))


class OmodaJaecooSession(_OmodaJaecooRestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda / Jaecoo Session", "session")

    def _live_is_on(self) -> bool | None:
        return self.coordinator.data.get("session_ok")
