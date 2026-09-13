"""Accès bas niveau aux flux GBFS.

Ce module ne connaît ni Home Assistant, ni les entités : uniquement aiohttp et
la spécification GBFS. Il est donc testable seul (voir tests/test_api.py).

Trois partis pris, tirés de pannes réelles :

1. L'URL qui répond fait autorité, pas le document d'auto-découverte.
   `gbfs.json` peut annoncer des URL pointant vers un hôte mort (observé :
   le cluster `delta` servait Metz tout en annonçant des URL `partners`
   en HTTP 500). On dérive les flux voisins du répertoire de l'URL qui a
   effectivement répondu.

2. Un HTTP 200 ne suffit pas à élire un cluster. Un hôte peut répondre 200
   avec un instantané figé ou amputé des stations suivies. La découverte
   évalue donc chaque candidat sur son contenu — stations présentes et
   horodatage frais — et non sur son seul code de statut.

3. Une fraîcheur invérifiable vaut périmé. Horodatage absent, illisible,
   d'un format inattendu ou situé dans le futur : on refuse de publier,
   on ne suppose pas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Un horodatage dans le futur trahit une horloge serveur déréglée. Au-delà de
# cette avance, la donnée est refusée : sinon un âge négatif passe le contrôle
# de fraîcheur haut la main, et une date absurde devient un gage de qualité.
CLOCK_TOLERANCE = 60

STATUS_FILE = "station_status.json"
INFORMATION_FILE = "station_information.json"
VEHICLE_TYPES_FILE = "vehicle_types.json"
SYSTEM_FILE = "system_information.json"

# Les deux tracés de chemin observés chez Fifteen selon les réseaux.
URL_PATTERNS = (
    "https://gbfs.{cluster}.fifteen.eu/gbfs/2.2/{network}/en/{filename}",
    "https://gbfs.{cluster}.fifteen.eu/gbfs/{network}/{filename}",
)


class GbfsError(Exception):
    """Erreur générique de la couche flux."""


class FeedUnavailable(GbfsError):
    """Le flux n'a pas répondu, ou a répondu autre chose que du JSON GBFS."""


class FeedNotFound(GbfsError):
    """Aucun candidat exploitable après balayage."""


def parse_timestamp(value: Any) -> int | None:
    """Horodatage GBFS en secondes Unix, ou None si inexploitable.

    GBFS 2.x publie un entier Unix, GBFS 3.0 une chaîne ISO 8601. Tout ce qui
    n'est ni l'un ni l'autre retourne None — et None sera traité comme périmé
    par l'appelant, jamais comme « pas de problème ».
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            _LOGGER.debug("Horodatage illisible : %r", value)
            return None
        if parsed.tzinfo is None:
            # GBFS impose un décalage, mais un flux qui l'omet serait sinon lu
            # dans le fuseau de Home Assistant : deux heures d'erreur en été,
            # silencieuses, et du bon côté pour passer le contrôle de fraîcheur.
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


@dataclass(frozen=True, slots=True)
class FeedLocation:
    """Emplacement résolu d'un jeu de flux GBFS.

    `base` est le répertoire de l'URL qui a répondu ; tous les autres flux en
    sont dérivés par voisinage, jamais lus dans `gbfs.json`.
    """

    base: str

    @classmethod
    def from_url(cls, url: str) -> "FeedLocation":
        return cls(base=url.rsplit("/", 1)[0])

    def _child(self, filename: str) -> str:
        return f"{self.base}/{filename}"

    @property
    def status_url(self) -> str:
        return self._child(STATUS_FILE)

    @property
    def information_url(self) -> str:
        return self._child(INFORMATION_FILE)

    @property
    def vehicle_types_url(self) -> str:
        return self._child(VEHICLE_TYPES_FILE)

    @property
    def system_url(self) -> str:
        return self._child(SYSTEM_FILE)

    @property
    def host(self) -> str:
        return urlparse(self.base).netloc

    @property
    def cluster(self) -> str | None:
        """`delta` pour gbfs.delta.fifteen.eu, None pour un hôte non Fifteen."""
        parts = self.host.split(".")
        if len(parts) >= 3 and parts[0] == "gbfs" and parts[-2:] == ["fifteen", "eu"]:
            return parts[1]
        return None


@dataclass(frozen=True, slots=True)
class FeedCandidate:
    """Un flux qui a répondu, avec le jugement porté sur son contenu."""

    location: FeedLocation
    stations: dict[str, dict[str, Any]]
    last_updated: int | None
    age: float | None
    complete: bool
    fresh: bool

    @property
    def trustworthy(self) -> bool:
        """Vrai si ce candidat peut alimenter les entités tel quel."""
        return self.complete and self.fresh

    def describe(self) -> str:
        parts = [self.location.host]
        parts.append("complet" if self.complete else "stations manquantes")
        if self.age is None:
            parts.append("sans horodatage exploitable")
        elif self.age < -CLOCK_TOLERANCE:
            parts.append(f"daté dans le futur ({-self.age:.0f} s d'avance)")
        else:
            parts.append(f"{self.age:.0f} s" + ("" if self.fresh else " — périmé"))
        return ", ".join(parts)


def candidate_urls(network: str, clusters: list[str], filename: str) -> Iterator[str]:
    """Génère les URL à tester, par ordre de préférence."""
    for cluster in clusters:
        for pattern in URL_PATTERNS:
            yield pattern.format(cluster=cluster, network=network, filename=filename)


async def async_get_json(
    session: aiohttp.ClientSession, url: str, timeout: int = 10
) -> dict[str, Any]:
    """Récupère un document JSON, ou lève FeedUnavailable."""
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                raise FeedUnavailable(f"HTTP {resp.status}")
            # content_type=None : certains clusters servent du text/plain.
            payload = await resp.json(content_type=None)
    except asyncio.TimeoutError as err:
        raise FeedUnavailable("délai dépassé") from err
    except aiohttp.ClientError as err:
        raise FeedUnavailable(str(err)) from err
    except ValueError as err:
        raise FeedUnavailable(f"réponse non JSON: {err}") from err

    if not isinstance(payload, dict):
        raise FeedUnavailable("racine JSON inattendue")
    return payload


async def _try_get(
    session: aiohttp.ClientSession, url: str, timeout: int
) -> dict[str, Any] | None:
    try:
        return await async_get_json(session, url, timeout)
    except GbfsError as err:
        _LOGGER.debug("Candidat écarté %s : %s", url, err)
        return None


def is_fresh(age: float | None, max_age: float | None) -> bool:
    """Un âge est frais s'il existe, n'est pas dans le futur, et tient le seuil."""
    if age is None:
        return False
    if age < -CLOCK_TOLERANCE:
        return False
    return max_age is None or age <= max_age


def evaluate(
    location: FeedLocation,
    payload: dict[str, Any],
    required_stations: Iterable[str] = (),
    max_age: float | None = None,
) -> FeedCandidate:
    """Juge une charge utile : stations attendues présentes, horodatage frais."""
    last_updated, stations = parse_status(payload)
    age = None if last_updated is None else time.time() - last_updated
    # Fraîcheur fermée par défaut : sans horodatage exploitable, on ne publie pas.
    fresh = is_fresh(age, max_age)
    required = [sid for sid in required_stations]
    complete = bool(stations) and all(sid in stations for sid in required)
    return FeedCandidate(
        location=location,
        stations=stations,
        last_updated=last_updated,
        age=age,
        complete=complete,
        fresh=fresh,
    )


async def async_discover(
    session: aiohttp.ClientSession,
    target: str,
    clusters: list[str],
    required_stations: Iterable[str] = (),
    max_age: float | None = None,
    timeout: int = 8,
) -> FeedCandidate:
    """Élit le meilleur flux disponible pour un réseau.

    `target` est soit un identifiant de réseau (« metz »), auquel cas les
    clusters sont balayés, soit une URL complète vers `gbfs.json` ou
    `station_status.json`, utilisée telle quelle.

    Un candidat digne de confiance — stations attendues présentes et données
    fraîches — l'emporte toujours. À défaut, le premier flux lisible est
    retourné quand même, mais marqué : l'appelant publiera `unknown` plutôt
    que de rendre les entités indisponibles, et saura pourquoi.
    """
    target = target.strip()
    if target.startswith(("http://", "https://")):
        urls = [target]
    else:
        urls = list(candidate_urls(target, clusters, STATUS_FILE))

    # Balayage concurrent, mais sélection dans l'ordre de préférence : on ne
    # veut pas que le gagnant dépende de la latence du moment.
    payloads = await asyncio.gather(*(_try_get(session, u, timeout) for u in urls))

    fallback: FeedCandidate | None = None
    rejected: list[str] = []

    for url, payload in zip(urls, payloads):
        if payload is None:
            continue
        location = FeedLocation.from_url(url)
        if "stations" not in payload.get("data", {}):
            # L'URL fournie était probablement gbfs.json : on lit le voisin.
            payload = await _try_get(session, location.status_url, timeout)
            if payload is None:
                continue

        candidate = evaluate(location, payload, required_stations, max_age)
        if candidate.trustworthy:
            _LOGGER.debug("Flux retenu : %s", candidate.describe())
            return candidate

        rejected.append(candidate.describe())
        if fallback is None:
            fallback = candidate

    if fallback is not None:
        _LOGGER.warning(
            "Aucun cluster pleinement fiable ; repli sur %s. Candidats : %s",
            fallback.location.host,
            " | ".join(rejected),
        )
        return fallback

    raise FeedNotFound(
        f"aucun flux exploitable pour « {target} » ({len(urls)} candidats testés)"
    )


def parse_status(payload: dict[str, Any]) -> tuple[int | None, dict[str, dict[str, Any]]]:
    """Retourne (last_updated exploitable ou None, {station_id: état})."""
    stations = {
        station["station_id"]: station
        for station in payload.get("data", {}).get("stations", [])
        if station.get("station_id")
    }
    return parse_timestamp(payload.get("last_updated")), stations


def parse_information(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        station["station_id"]: station
        for station in payload.get("data", {}).get("stations", [])
        if station.get("station_id")
    }


def parse_vehicle_types(payload: dict[str, Any]) -> dict[str, str]:
    """{vehicle_type_id: libellé lisible}."""
    types: dict[str, str] = {}
    for item in payload.get("data", {}).get("vehicle_types", []):
        type_id = item.get("vehicle_type_id")
        if not type_id:
            continue
        label = item.get("name") or item.get("form_factor") or type_id
        if isinstance(label, list) and label:  # GBFS 3.0 : tableau localisé
            label = label[0].get("text", type_id)
        propulsion = item.get("propulsion_type")
        if propulsion == "electric_assist" and "électri" not in str(label).lower():
            label = f"{label} électrique"
        types[str(type_id)] = str(label).capitalize()
    return types


def parse_system(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    name = data.get("name")
    if isinstance(name, list) and name:  # GBFS 3.0
        name = name[0].get("text")
    return {
        "name": name or data.get("system_id"),
        "operator": data.get("operator"),
        "system_id": data.get("system_id"),
        "url": data.get("url"),
    }

