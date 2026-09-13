"""Parcours de configuration : réseau, puis choix des stations."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
)

_LOGGER = logging.getLogger(__name__)


def _station_options(stations: dict[str, dict]) -> list[selector.SelectOptionDict]:
    """Libellés lisibles, triés par nom, valeur = station_id."""
    return [
        selector.SelectOptionDict(value=station_id, label=station.get("name") or station_id)
        for station_id, station in sorted(
            stations.items(), key=lambda item: (item[1].get("name") or item[0]).lower()
        )
    ]


def _stations_schema(
    stations: dict[str, dict], selected: list[str] | None = None
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STATIONS, default=selected or []): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_station_options(stations),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _tuning_schema(options: dict[str, Any]) -> dict:
    return {
        vol.Optional(
            CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=30, max=3600, step=10, unit_of_measurement="s")
        ),
        vol.Optional(
            CONF_MAX_AGE, default=options.get(CONF_MAX_AGE, DEFAULT_MAX_AGE)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=60, max=86400, step=60, unit_of_measurement="s")
        ),
        vol.Optional(
            CONF_CLUSTERS, default=options.get(CONF_CLUSTERS, DEFAULT_CLUSTERS)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=DEFAULT_CLUSTERS, multiple=True, custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }


class GbfsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'un réseau, puis sélection des stations à suivre."""

    VERSION = 1

    def __init__(self) -> None:
        self._network: str = ""
        self._location: api.FeedLocation | None = None
        self._stations: dict[str, dict] = {}
        self._title: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            network = user_input[CONF_NETWORK].strip()
            session = async_get_clientsession(self.hass)
            try:
                candidate = await api.async_discover(
                    session,
                    network,
                    DEFAULT_CLUSTERS,
                    max_age=DEFAULT_MAX_AGE,
                )
                location = candidate.location
                information = api.parse_information(
                    await api.async_get_json(session, location.information_url)
                )
                system = api.parse_system(
                    await api.async_get_json(session, location.system_url)
                )
            except api.FeedNotFound:
                errors["base"] = "not_found"
            except api.GbfsError:
                errors["base"] = "cannot_connect"
            else:
                if not information:
                    errors["base"] = "no_stations"
                else:
                    await self.async_set_unique_id(
                        system.get("system_id") or f"{location.host}/{network}"
                    )
                    self._abort_if_unique_id_configured()
                    self._network = network
                    self._location = location
                    self._stations = information
                    self._title = system.get("name") or network
                    return await self.async_step_stations()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NETWORK): str}),
            errors=errors,
            description_placeholders={"example": "metz"},
        )

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._title,
                data={CONF_NETWORK: self._network, CONF_STATIONS: user_input[CONF_STATIONS]},
            )

        return self.async_show_form(
            step_id="stations",
            data_schema=_stations_schema(self._stations),
            description_placeholders={
                "network": self._title,
                "count": str(len(self._stations)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return GbfsOptionsFlow()


class GbfsOptionsFlow(OptionsFlow):
    """Modifier les stations suivies et les réglages, sans redémarrage."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        current = {**entry.data, **entry.options}

        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            user_input[CONF_MAX_AGE] = int(user_input[CONF_MAX_AGE])
            return self.async_create_entry(data=user_input)

        # Liste fraîche si l'intégration tourne, sinon repli sur la sélection
        # existante pour ne jamais bloquer l'accès aux réglages.
        coordinator = getattr(entry, "runtime_data", None)
        stations = getattr(coordinator, "data", None)
        known = stations.info if stations else {}
        if not known:
            known = {sid: {"name": sid} for sid in current.get(CONF_STATIONS, [])}

        schema = vol.Schema(
            {
                **_stations_schema(known, current.get(CONF_STATIONS, [])).schema,
                **_tuning_schema(current),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
