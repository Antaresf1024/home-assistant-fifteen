"""Intégration GBFS Stations : suivi de stations de vélos en libre-service."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import GbfsCoordinator
from .entity import network_device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GbfsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Le namespace n'est connu qu'après la première lecture du flux : la
    # migration doit donc précéder la création des plateformes, mais la suivre.
    await _async_migrate_identity(hass, entry, coordinator)

    device_registry = dr.async_get(hass)
    network_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **network_device_info(coordinator)
    )
    coordinator.network_device_id = network_device.id

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Les options changent la liste des stations : un rechargement est le moyen
    # le plus simple d'ajouter ou retirer des équipements sans redémarrage.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_identity(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: GbfsCoordinator
) -> None:
    """Réécrit les identifiants fondés sur l'entry_id vers le system_id.

    Les versions 0.1.x nommaient entités et équipements d'après le
    `config_entry_id`, qui change à chaque suppression/recréation de
    l'intégration — au prix d'entités fantômes suffixées `_2` et de tableaux
    de bord cassés. On bascule sur le `system_id` du flux, stable dans le
    temps, en conservant les `entity_id` existants.
    """
    namespace = coordinator.namespace
    old_prefix = f"{entry.entry_id}_"
    new_prefix = f"{namespace}_"
    if namespace == entry.entry_id:
        return

    migrated = 0

    @callback
    def _migrate(registry_entry: er.RegistryEntry) -> dict[str, str] | None:
        nonlocal migrated
        if registry_entry.unique_id.startswith(old_prefix):
            migrated += 1
            return {
                "new_unique_id": new_prefix + registry_entry.unique_id[len(old_prefix):]
            }
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifiers = set()
        changed = False
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                identifiers.add((domain, identifier))
            elif identifier == entry.entry_id:
                identifiers.add((domain, namespace))
                changed = True
            elif identifier.startswith(old_prefix):
                identifiers.add((domain, new_prefix + identifier[len(old_prefix):]))
                changed = True
            else:
                identifiers.add((domain, identifier))
        if changed:
            device_registry.async_update_device(device.id, new_identifiers=identifiers)

    if migrated:
        _LOGGER.info(
            "Identifiants migrés vers le namespace %s (%s entités)", namespace, migrated
        )

