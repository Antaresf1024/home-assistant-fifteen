"""Coordinateur : un seul appel réseau alimente toutes les entités."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import api
from .const import (
    CONF_CLUSTERS,
    CONF_MAX_AGE,
    CONF_NETWORK,
    CONF_STATIONS,
    DEFAULT_CLUSTERS,
    DEFAULT_MAX_AGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REDISCOVER_BACKOFF_MAX,
    REDISCOVER_BACKOFF_START,
    STATIC_REFRESH_SECONDS,
    STATIC_RETRY_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GbfsData:
    """Instantané cohérent servi aux entités."""

    location: api.FeedLocation
    stations: dict[str, dict[str, Any]] = field(default_factory=dict)
    info: dict[str, dict[str, Any]] = field(default_factory=dict)
    vehicle_types: dict[str, str] = field(default_factory=dict)
    system: dict[str, Any] = field(default_factory=dict)
    last_updated: datetime | None = None
    age: float | None = None
    stale: bool = False
    stale_stations: set[str] = field(default_factory=set)

    def usable(self, station_id: str) -> bool:
        """Vrai si la valeur de cette station peut être publiée telle quelle.

        Quatre refus possibles, tous menant à `unknown` plutôt qu'à une
        ancienne valeur : flux globalement périmé, station absente du flux,
        relevé de station trop vieux, ou station non installée — auquel cas
        un comptage n'a physiquement pas de sens.

        `is_renting` n'entre volontairement PAS dans ce jugement : une station
        fermée à la location a quand même un nombre de vélos certain. C'est sa
        portée qui change, pas sa véracité, et le capteur binaire dédié porte
        déjà cette information.
        """
        if self.stale or station_id in self.stale_stations:
            return False
        station = self.stations.get(station_id)
        if not station:
            return False
        return station.get("is_installed") is not False


class GbfsCoordinator(DataUpdateCoordinator[GbfsData]):
    """Interroge le flux, rebascule de cluster au besoin, contrôle la fraîcheur."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.network_device_id: str | None = None
        self._session = async_get_clientsession(hass)
        self._location: api.FeedLocation | None = None
        self._info: dict[str, dict[str, Any]] = {}
        self._types: dict[str, str] = {}
        self._system: dict[str, Any] = {}
        self._static_expiry = 0.0
        self._next_sweep = 0.0
        self._sweep_failures = 0

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data.get(CONF_NETWORK, '')}".strip(),
            update_interval=timedelta(seconds=self._opt(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )

    def _opt(self, key: str, default: Any) -> Any:
        """Option d'abord, donnée d'entrée ensuite, défaut en dernier."""
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def network(self) -> str:
        return self.entry.data[CONF_NETWORK]

    @property
    def station_ids(self) -> list[str]:
        return list(self._opt(CONF_STATIONS, []))

    @property
    def clusters(self) -> list[str]:
        return list(self._opt(CONF_CLUSTERS, DEFAULT_CLUSTERS))

    @property
    def max_age(self) -> int:
        return int(self._opt(CONF_MAX_AGE, DEFAULT_MAX_AGE))

    @property
    def namespace(self) -> str:
        """Racine stable des identifiants.

        `entry.unique_id` est fixé au moment de la configuration à partir du
        `system_id` du flux, puis persisté : il ne dépend d'aucune lecture
        réseau ultérieure. Faire dépendre l'identité des entités d'un
        `system_information.json` optionnel exposerait à une seconde série
        d'identifiants le jour où ce fichier échoue au démarrage.
        """
        return str(
            self.entry.unique_id or self._system.get("system_id") or self.network
        )

    def _sweep_allowed(self) -> bool:
        """Vrai si un nouveau balayage est dû (immédiat au premier doute)."""
        return time.monotonic() >= self._next_sweep

    def _schedule_next_sweep(self, found_trustworthy: bool) -> None:
        if found_trustworthy:
            self._sweep_failures = 0
        else:
            self._sweep_failures += 1
        delay = min(
            REDISCOVER_BACKOFF_START * (2 ** max(0, self._sweep_failures - 1)),
            REDISCOVER_BACKOFF_MAX,
        )
        self._next_sweep = time.monotonic() + delay
        if not found_trustworthy:
            _LOGGER.debug("Prochain balayage dans %s s", delay)

    async def _async_sweep(self) -> api.FeedCandidate | None:
        """Balaie les clusters et journalise tout changement d'hôte."""
        previous = self._location
        try:
            candidate = await api.async_discover(
                self._session,
                self.network,
                self.clusters,
                required_stations=self.station_ids,
                max_age=self.max_age,
            )
        except api.GbfsError as err:
            _LOGGER.warning("Balayage infructueux pour %s : %s", self.network, err)
            self._schedule_next_sweep(False)
            return None

        if previous is None:
            _LOGGER.info("Flux %s résolu sur %s", self.network, candidate.describe())
        elif previous.base != candidate.location.base:
            _LOGGER.warning(
                "Le flux %s a changé d'hôte : %s -> %s",
                self.network,
                previous.host,
                candidate.location.host,
            )
        self._location = candidate.location
        self._schedule_next_sweep(candidate.trustworthy)
        return candidate

    async def _async_refresh_static(self, location: api.FeedLocation) -> None:
        """Relit les données quasi immuables (noms, capacités, types)."""
        if time.monotonic() < self._static_expiry and self._info:
            return
        complete = True
        try:
            self._info = api.parse_information(
                await api.async_get_json(self._session, location.information_url)
            )
        except api.GbfsError as err:
            _LOGGER.debug("station_information indisponible : %s", err)
            complete = False
        for url, parser, target in (
            (location.vehicle_types_url, api.parse_vehicle_types, "_types"),
            (location.system_url, api.parse_system, "_system"),
        ):
            try:
                setattr(self, target, parser(await api.async_get_json(self._session, url)))
            except api.GbfsError as err:
                _LOGGER.debug("%s indisponible : %s", url.rsplit("/", 1)[-1], err)
                complete = False
        # Une lecture partielle ne doit pas verrouiller douze heures de silence :
        # les noms de stations ou l'identité du réseau manqueraient d'autant.
        self._static_expiry = time.monotonic() + (
            STATIC_REFRESH_SECONDS if complete else STATIC_RETRY_SECONDS
        )

    async def _async_update_data(self) -> GbfsData:
        candidate: api.FeedCandidate | None = None

        if self._location is not None:
            payload = await api._try_get(self._session, self._location.status_url, 10)
            if payload is not None:
                candidate = api.evaluate(
                    self._location, payload, self.station_ids, self.max_age
                )

        # Un 200 ne suffit pas : périmé, amputé ou injoignable, on rebalaie —
        # c'est le seul moyen de quitter un cluster qui répond mais ment.
        if candidate is None or not candidate.trustworthy:
            if self._sweep_allowed():
                if candidate is not None:
                    _LOGGER.info(
                        "Flux courant douteux (%s) : nouveau balayage", candidate.describe()
                    )
                swept = await self._async_sweep()
                if swept is not None and (candidate is None or swept.trustworthy):
                    candidate = swept

        if candidate is None:
            raise UpdateFailed("aucun cluster ne répond")

        await self._async_refresh_static(candidate.location)

        stale = not candidate.fresh
        if stale:
            _LOGGER.warning(
                "Données non fiables sur %s (%s) : valeurs publiées en inconnu",
                candidate.location.host,
                "aucun horodatage exploitable"
                if candidate.age is None
                else f"{candidate.age:.0f} s > {self.max_age} s",
            )

        # Fraîcheur par station : une station peut cesser de remonter alors que
        # le flux global continue d'être republié.
        now = time.time()
        stale_stations: set[str] = set()
        for station_id in self.station_ids:
            station = candidate.stations.get(station_id)
            if not station:
                continue
            reported = api.parse_timestamp(station.get("last_reported"))
            age = None if reported is None else now - reported
            if not api.is_fresh(age, self.max_age):
                stale_stations.add(station_id)
        if stale_stations:
            _LOGGER.warning(
                "Relevés de station périmés, publiés en inconnu : %s",
                ", ".join(sorted(stale_stations)),
            )

        missing = [sid for sid in self.station_ids if sid not in candidate.stations]
        if missing:
            _LOGGER.warning(
                "Stations absentes du flux %s : %s",
                candidate.location.host,
                ", ".join(missing),
            )

        return GbfsData(
            location=candidate.location,
            stations=candidate.stations,
            info=self._info,
            vehicle_types=self._types,
            system=self._system,
            last_updated=(
                None
                if candidate.last_updated is None
                else dt_util.utc_from_timestamp(candidate.last_updated)
            ),
            age=candidate.age,
            stale=stale,
            stale_stations=stale_stations,
        )
