"""Diagnostics : de quoi comprendre une panne sans accès au shell."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import GbfsCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: GbfsCoordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "resolved": {
            "host": data.location.host if data and data.location else None,
            "cluster": data.location.cluster if data and data.location else None,
            "status_url": data.location.status_url if data and data.location else None,
        },
        "freshness": {
            "last_updated": data.last_updated.isoformat() if data and data.last_updated else None,
            "age_seconds": round(data.age) if data and data.age is not None else None,
            "max_age_seconds": coordinator.max_age,
            "stale": data.stale if data else None,
            "error": data.error if data else None,
        },
        "counts": {
            "stations_in_feed": len(data.stations) if data else 0,
            "stations_tracked": len(coordinator.station_ids),
            "vehicle_types": data.vehicle_types if data else {},
        },
        "tracked": {
            sid: data.stations.get(sid) for sid in coordinator.station_ids
        } if data else {},
    }
