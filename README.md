# Fifteen GBFS Stations for Home Assistant

Resilient Home Assistant custom integration for Fifteen bike-sharing networks,
including Graou’Lib Metz. It automatically finds the working Fifteen GBFS
cluster and refuses to publish bike counts that cannot be trusted.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with or
> endorsed by Fifteen, Graou’Lib or Eurométropole de Metz.

## Features

- configuration entirely from the Home Assistant UI;
- selection of only the stations you want to monitor;
- automatic failover across known Fifteen GBFS clusters;
- validation of both feed and per-station timestamps;
- no cached count presented as current data;
- diagnostic entities exposing the selected host, feed timestamp and health;
- one device per station and one parent device for the bike-sharing network;
- no Fifteen account, token or private API.

## Installation

### HACS

1. Open HACS.
2. Add this repository as a custom repository of type **Integration**:
   `https://github.com/Antaresf1024/home-assistant-fifteen`
3. Install **Fifteen GBFS Stations**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/gbfs_stations` into the `custom_components`
directory of your Home Assistant configuration, then restart Home Assistant.

## Configuration

In Home Assistant, go to **Settings → Devices & services → Add integration**
and search for **Fifteen GBFS Stations**.

Enter the Fifteen network identifier, for example `metz`, then select the
stations to follow. The station selection, polling interval, maximum accepted
age and cluster list can later be changed from **Configure**.

The defaults are:

- polling interval: 120 seconds;
- maximum accepted age: 300 seconds;
- clusters: `delta`, `partners`, `iota`, `kappa`, `theta`, `omega`,
  `beta`, `sigma`.

## Data reliability

A successful HTTP response is not enough. A candidate feed is accepted only
when:

- its timestamp is present, valid and not unexpectedly in the future;
- it is younger than the configured maximum age;
- every selected station is present;
- each selected station has a recent `last_reported` timestamp.

When a feed responds but any of these checks fails, dynamic measurements
become `unknown`. The total across followed stations is also `unknown` if a
single station cannot be trusted.

A complete transport outage is intentionally different: if no cluster
responds at all, the coordinator update fails and its measurement entities
become `unavailable`. This distinguishes an unreachable service from a feed
that responded with uncertain data. The **Feed problem** entity remains
available and reports the outage.

### Meaning of `is_renting`

`num_bikes_available` is published as reported when the station is installed
and the data is fresh, even if `is_renting` is false. This preserves the
operator's reported inventory rather than silently rewriting it.

For the operational question “can I rent a bike here now?”, always use the
station's **Rental possible** binary sensor together with the bike count.
A station may contain bikes while temporarily refusing rentals.

## Why cluster failover is necessary

Fifteen networks can move between infrastructure clusters. In addition, a
GBFS discovery document may temporarily advertise feed URLs on a different,
unhealthy cluster. This integration derives sibling feeds from the URL that
actually responded and evaluates every candidate's contents before selecting
it.

## Diagnostics

The integration provides:

- **Feed host** — the Fifteen host currently serving the network;
- **Feed updated** — the timestamp supplied by the GBFS feed;
- **Feed problem** — on when the feed is unreachable, stale, incomplete or
  contains stale selected stations;
- **Bikes on followed stations** — an all-or-nothing total.

Home Assistant's integration diagnostics can be downloaded when reporting an
issue. Review the file before sharing it, as station identifiers and network
configuration are included.

## Scope and limitations

The automatic discovery logic targets Fifteen's observed GBFS URL layouts.
This project does not use Fifteen's private application API. Endpoint layout,
cluster names and feed behaviour remain controlled by the provider and may
change without notice.

GBFS data and the Fifteen and Graou’Lib names remain subject to their
respective owners' terms and rights.

## License

[MIT](LICENSE) © 2026 Antaresf1024
