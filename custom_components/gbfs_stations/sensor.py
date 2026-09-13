"""Capteurs : disponibilités par station, par type de véhicule, et santé du flux."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ATTR_AGE, ATTR_CLUSTER, ATTR_SOURCE_URL
from .coordinator import GbfsCoordinator
from .entity import GbfsNetworkEntity, GbfsStationEntity

UNIT_VEHICLES = "vélos"


def _fill_level(station: dict[str, Any], info: dict[str, Any]) -> float | None:
    capacity = info.get("capacity")
    bikes = station.get("num_bikes_available")
    if not capacity or bikes is None:
        return None
    return round(100 * bikes / capacity, 1)


@dataclass(frozen=True, kw_only=True)
class GbfsSensorDescription(SensorEntityDescription):
    """Description adossée à un extracteur (état, informations statiques)."""

    value_fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    # Clé du flux station_status conditionnant la création de l'entité.
    requires: str | None = None
    # Une donnée statique reste valable même si l'état temps réel est périmé.
    static: bool = False


STATION_SENSORS: tuple[GbfsSensorDescription, ...] = (
    GbfsSensorDescription(
        key="bikes_available",
        translation_key="bikes_available",
        native_unit_of_measurement=UNIT_VEHICLES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bike",
        requires="num_bikes_available",
        value_fn=lambda station, info: station.get("num_bikes_available"),
    ),
    GbfsSensorDescription(
        key="docks_available",
        translation_key="docks_available",
        native_unit_of_measurement="places",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:parking",
        requires="num_docks_available",
        value_fn=lambda station, info: station.get("num_docks_available"),
    ),
    GbfsSensorDescription(
        key="bikes_disabled",
        translation_key="bikes_disabled",
        native_unit_of_measurement=UNIT_VEHICLES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bike-fast",
        entity_category=EntityCategory.DIAGNOSTIC,
        requires="num_bikes_disabled",
        value_fn=lambda station, info: station.get("num_bikes_disabled"),
    ),
    GbfsSensorDescription(
        key="docks_disabled",
        translation_key="docks_disabled",
        native_unit_of_measurement="places",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:parking",
        entity_category=EntityCategory.DIAGNOSTIC,
        requires="num_docks_disabled",
        value_fn=lambda station, info: station.get("num_docks_disabled"),
    ),
    GbfsSensorDescription(
        key="fill_level",
        translation_key="fill_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=_fill_level,
    ),
    GbfsSensorDescription(
        key="last_reported",
        translation_key="last_reported",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires="last_reported",
        value_fn=lambda station, info: (
            dt_util.utc_from_timestamp(station["last_reported"])
            if station.get("last_reported")
            else None
        ),
    ),
    GbfsSensorDescription(
        key="capacity",
        translation_key="capacity",
        native_unit_of_measurement="places",
        icon="mdi:tray-full",
        entity_category=EntityCategory.DIAGNOSTIC,
        static=True,
        value_fn=lambda station, info: info.get("capacity"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GbfsCoordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SensorEntity] = [
        GbfsFeedHostSensor(coordinator),
        GbfsFeedUpdatedSensor(coordinator),
        GbfsNetworkTotalSensor(coordinator),
    ]

    for station_id in coordinator.station_ids:
        station = data.stations.get(station_id, {})
        for description in STATION_SENSORS:
            # On ne crée pas d'entité pour un champ que l'opérateur ne publie
            # pas : mieux vaut pas de capteur qu'un capteur toujours inconnu.
            if description.requires and description.requires not in station:
                continue
            entities.append(GbfsStationSensor(coordinator, station_id, description))

        types_present = [
            item
            for item in station.get("vehicle_types_available", [])
            if item.get("vehicle_type_id") is not None
        ]
        # Un seul type de véhicule : le capteur ferait doublon avec
        # « Vélos disponibles ». On ne le crée que sur un réseau qui en mélange
        # plusieurs (Caen en a neuf, Montpellier trois, Metz un seul).
        if len(types_present) > 1:
            for item in types_present:
                type_id = str(item["vehicle_type_id"])
                label = data.vehicle_types.get(type_id, f"Type {type_id}")
                entities.append(
                    GbfsVehicleTypeSensor(coordinator, station_id, type_id, label)
                )

    async_add_entities(entities)


class GbfsStationSensor(GbfsStationEntity, SensorEntity):
    """Une mesure d'une station."""

    entity_description: GbfsSensorDescription

    def __init__(
        self, coordinator: GbfsCoordinator, station_id: str, description: GbfsSensorDescription
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        description = self.entity_description
        if not description.static and not self.usable:
            return None
        return description.value_fn(self.station, self.station_info)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "bikes_available":
            return None
        info = self.station_info
        return {
            "station_id": self.station_id,
            "latitude": info.get("lat"),
            "longitude": info.get("lon"),
            "address": info.get("address"),
        }


class GbfsVehicleTypeSensor(GbfsStationEntity, SensorEntity):
    """Disponibilité par type de véhicule (vélo mécanique, à assistance, etc.)."""

    _attr_native_unit_of_measurement = UNIT_VEHICLES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:bike"

    def __init__(
        self, coordinator: GbfsCoordinator, station_id: str, type_id: str, label: str
    ) -> None:
        super().__init__(coordinator, station_id, f"vehicle_{type_id}")
        self._type_id = type_id
        self._attr_name = label

    @property
    def native_value(self) -> int | None:
        if not self.usable:
            return None
        for item in self.station.get("vehicle_types_available", []):
            if str(item.get("vehicle_type_id")) == self._type_id:
                return item.get("count")
        return None


class GbfsFeedHostSensor(GbfsNetworkEntity, SensorEntity):
    """Hôte réellement utilisé — change tout seul en cas de bascule de cluster."""

    _attr_translation_key = "feed_host"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator: GbfsCoordinator) -> None:
        super().__init__(coordinator, "feed_host")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None or self.coordinator.data.location is None:
            return None
        return self.coordinator.data.location.host

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None or data.location is None:
            return {}
        return {
            ATTR_SOURCE_URL: data.location.status_url,
            ATTR_CLUSTER: data.location.cluster,
            ATTR_AGE: None if data.age is None else round(data.age),
            "clusters_probed": self.coordinator.clusters,
        }


class GbfsFeedUpdatedSensor(GbfsNetworkEntity, SensorEntity):
    """Horodatage annoncé par le flux — la base du contrôle de fraîcheur."""

    _attr_translation_key = "feed_updated"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GbfsCoordinator) -> None:
        super().__init__(coordinator, "feed_updated")

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.last_updated


class GbfsNetworkTotalSensor(GbfsNetworkEntity, SensorEntity):
    """Somme des vélos disponibles sur les stations suivies."""

    _attr_translation_key = "tracked_total"
    _attr_native_unit_of_measurement = UNIT_VEHICLES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:bike"

    def __init__(self, coordinator: GbfsCoordinator) -> None:
        super().__init__(coordinator, "tracked_total")

    @property
    def native_value(self) -> int | None:
        """Somme, ou rien du tout.

        Un total amputé d'une station ressemble à un total complet : si une
        seule des stations suivies est inexploitable, la somme n'a plus de
        sens et vaut `unknown`.
        """
        data = self.coordinator.data
        if data is None:
            return None
        total = 0
        for station_id in self.coordinator.station_ids:
            if not data.usable(station_id):
                return None
            count = data.stations[station_id].get("num_bikes_available")
            if not isinstance(count, int):
                return None
            total += count
        return total
