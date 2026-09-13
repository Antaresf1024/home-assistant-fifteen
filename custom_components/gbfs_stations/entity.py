"""Socle commun des entités : rattachement aux équipements."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GbfsCoordinator


def network_device_info(coordinator: GbfsCoordinator) -> DeviceInfo:
    """Équipement « réseau », parent de toutes les stations."""
    system = coordinator.data.system if coordinator.data else {}
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.namespace)},
        name=system.get("name") or coordinator.network,
        manufacturer=system.get("operator"),
        model="Réseau GBFS",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=system.get("url"),
    )


class GbfsNetworkEntity(CoordinatorEntity[GbfsCoordinator]):
    """Entité rattachée à l'équipement « réseau » (diagnostic du flux)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GbfsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.namespace}_{key}"
        self._attr_device_info = network_device_info(coordinator)


class GbfsStationEntity(CoordinatorEntity[GbfsCoordinator]):
    """Entité rattachée à l'équipement « station »."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GbfsCoordinator, station_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.station_id = station_id
        namespace = coordinator.namespace
        self._attr_unique_id = f"{namespace}_{station_id}_{key}"
        info = (coordinator.data.info if coordinator.data else {}).get(station_id, {})
        system = coordinator.data.system if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{namespace}_{station_id}")},
            name=info.get("name") or station_id,
            manufacturer=system.get("operator"),
            model="Station GBFS",
            # `via_device` (tuple d'identifiants) est déprécié depuis 2026 et
            # cesse de fonctionner en 2027.8 : on rattache par identifiant
            # d'équipement, résolu au chargement de l'entrée.
            via_device_id=coordinator.network_device_id,
        )

    @property
    def station(self) -> dict:
        """État courant de la station, dict vide si absente du flux."""
        return self.coordinator.data.stations.get(self.station_id, {})

    @property
    def station_info(self) -> dict:
        return self.coordinator.data.info.get(self.station_id, {})

    @property
    def usable(self) -> bool:
        """Faux si la donnée est périmée, absente, ou la station non installée."""
        return self.coordinator.data.usable(self.station_id)

