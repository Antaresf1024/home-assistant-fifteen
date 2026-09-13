"""Constantes de l'intégration GBFS Stations."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "gbfs_stations"

CONF_NETWORK: Final = "network"
CONF_STATIONS: Final = "stations"
CONF_CLUSTERS: Final = "clusters"
CONF_MAX_AGE: Final = "max_age"

# Hôtes Fifteen connus, par ordre de probabilité. Le premier qui répond avec la
# station demandée gagne. Cette liste est volontairement en dur : voir README,
# section « Pourquoi ne pas faire confiance au document d'auto-découverte ».
DEFAULT_CLUSTERS: Final[list[str]] = [
    "delta",
    "partners",
    "iota",
    "kappa",
    "theta",
    "omega",
    "beta",
    "sigma",
]

# Intervalle de rafraîchissement du station_status (le ttl GBFS est de 60 s ;
# 120 s reste poli vis-à-vis de l'opérateur).
DEFAULT_SCAN_INTERVAL: Final = 120

# Au-delà de cet âge, une réponse HTTP 200 est considérée comme non fiable et
# les valeurs sont publiées en `unknown` plutôt qu'affichées comme fraîches.
# Le ttl annoncé est de 60 s et le relevé de 120 s : 300 s laisse passer deux
# cycles manqués, pas davantage.
DEFAULT_MAX_AGE: Final = 300

# Balayage de repli : immédiat au premier doute, puis recul exponentiel tant
# qu'aucun cluster fiable n'est trouvé. Une panne côté opérateur ne doit pas
# nous faire tirer seize requêtes toutes les deux minutes pendant des heures.
REDISCOVER_BACKOFF_START: Final = 60
REDISCOVER_BACKOFF_MAX: Final = 3600

# Nouvelle tentative rapprochée quand une lecture statique a échoué, au lieu
# d'attendre la demi-journée prévue pour des données qui ne bougent pas.
STATIC_RETRY_SECONDS: Final = 300

# Les données statiques (noms, capacités, coordonnées) ne bougent quasiment
# jamais : on les relit deux fois par jour.
STATIC_REFRESH_SECONDS: Final = 43200

ATTR_SOURCE_URL: Final = "source_url"
ATTR_CLUSTER: Final = "cluster"
ATTR_AGE: Final = "age_seconds"

