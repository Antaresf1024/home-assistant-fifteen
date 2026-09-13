"""Capteurs binaires : état opérationnel des stations et santé du flux."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GbfsCoordinator
from .entity import GbfsNetworkEntity, GbfsStationEntity


@dataclass(frozen=True, kw_only=True)
class GbfsBinaryDescription(BinarySensorEntityDescription):
    """Description adossée à un extracteur."""

    value_fn: Callable[[dict], bool | None]


STATION_BINARY_SENSORS: tuple[GbfsBinaryDescription, ...] = (
    GbfsBinaryDescription(
        key="renting",
        translation_key="renting",
        value_fn=lambda station: station.get("is_renting"),
    ),
    GbfsBinaryDescription(
        key="returning",
        translation_key="returning",
        value_fn=lambda station: station.get("is_returning"),
    ),
    GbfsBinaryDescription(
        key="installed",
        translation_key="installed",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda station: station.get("is_installed"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GbfsCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [GbfsFeedProblem(coordinator)]
    for station_id in coordinator.station_ids:
        entities.extend(
            GbfsStationBinarySensor(coordinator, station_id, description)
            for description in STATION_BINARY_SENSORS
        )
    async_add_entities(entities)


class GbfsStationBinarySensor(GbfsStationEntity, BinarySensorEntity):
    """Location possible, restitution possible, station installée."""

    entity_description: GbfsBinaryDescription

    def __init__(
        self, coordinator: GbfsCoordinator, station_id: str, description: GbfsBinaryDescription
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if not self.usable:
            return None
        return self.entity_description.value_fn(self.station)


class GbfsFeedProblem(GbfsNetworkEntity, BinarySensorEntity):
    """Actif quand le flux est périmé ou injoignable — c'est l'entité à alerter."""

    _attr_translation_key = "feed_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GbfsCoordinator) -> None:
        super().__init__(coordinator, "feed_problem")

    @property
    def available(self) -> bool:
        # Toujours disponible : c'est justement l'entité qui dit que ça va mal.
        return True

    @property
    def _diagnosis(self) -> str:
        data = self.coordinator.data
        if not self.coordinator.last_update_success or data is None:
            return "flux injoignable"
        if data.stale:
            return (
                "aucun horodatage exploitable"
                if data.age is None
                else f"flux périmé ({data.age:.0f} s)"
            )
        missing = [s for s in self.coordinator.station_ids if s not in data.stations]
        if missing:
            return f"{len(missing)} station(s) absente(s) du flux"
        if data.stale_stations:
            return f"{len(data.stale_stations)} relevé(s) de station périmé(s)"
        return "ok"

    @property
    def is_on(self) -> bool:
        return self._diagnosis != "ok"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "reason": self._diagnosis,
            "age_seconds": None if data is None or data.age is None else round(data.age),
            "max_age_seconds": self.coordinator.max_age,
            "host": None if data is None else data.location.host,
            "stale_stations": sorted(data.stale_stations) if data else [],
        }
