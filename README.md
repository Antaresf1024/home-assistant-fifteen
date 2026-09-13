# Stations GBFS Fifteen pour Home Assistant

[![Validation](https://github.com/Antaresf1024/home-assistant-fifteen/actions/workflows/validate.yml/badge.svg)](https://github.com/Antaresf1024/home-assistant-fifteen/actions/workflows/validate.yml)

Intégration Home Assistant robuste pour les réseaux de vélos en libre-service
opérés par Fifteen, notamment Graou’Lib Metz. Elle trouve automatiquement le
cluster GBFS Fifteen fonctionnel et refuse de présenter comme fiable un nombre
de vélos qui ne l’est pas.

> [!IMPORTANT]
> Ce projet communautaire est indépendant. Il n’est ni affilié ni approuvé par
> Fifteen, Graou’Lib ou l’Eurométropole de Metz.

## Fonctionnalités

- configuration entièrement depuis l’interface Home Assistant ;
- sélection des seules stations à suivre ;
- bascule automatique entre les clusters GBFS Fifteen connus ;
- contrôle de l’horodatage du flux et de chaque station ;
- aucune ancienne valeur présentée comme une donnée actuelle ;
- entités de diagnostic pour l’hôte retenu, l’horodatage et la santé du flux ;
- un appareil par station et un appareil parent pour le réseau ;
- aucun compte Fifteen, jeton ou recours à une API privée.

## Installation

### Avec HACS

1. Ouvrez HACS.
2. Ajoutez ce dépôt comme **dépôt personnalisé** de type **Intégration** :
   `https://github.com/Antaresf1024/home-assistant-fifteen`
3. Installez **Fifteen GBFS Stations**.
4. Redémarrez Home Assistant.

### Manuellement

Copiez le dossier `custom_components/gbfs_stations` dans le dossier
`custom_components` de votre configuration Home Assistant, puis redémarrez
Home Assistant.

## Configuration

Dans Home Assistant, ouvrez **Paramètres → Appareils et services → Ajouter une
intégration**, puis recherchez **Fifteen GBFS Stations**.

Saisissez l’identifiant du réseau Fifteen, par exemple `metz`, puis
sélectionnez les stations à suivre. Le bouton **Configurer** permet ensuite de
modifier la sélection, l’intervalle d’interrogation, l’âge maximal accepté et
la liste des clusters.

Valeurs par défaut :

- interrogation toutes les 120 secondes ;
- âge maximal accepté de 300 secondes ;
- clusters : `delta`, `partners`, `iota`, `kappa`, `theta`, `omega`,
  `beta`, `sigma`.

## Fiabilité des données

Une réponse HTTP réussie ne suffit pas. Un flux candidat n’est accepté que si :

- son horodatage est présent, valide et pas anormalement situé dans le futur ;
- son âge reste inférieur à la limite configurée ;
- toutes les stations sélectionnées sont présentes ;
- chaque station sélectionnée possède un `last_reported` récent.

Lorsqu’un flux répond mais échoue à l’un de ces contrôles, les mesures
dynamiques passent à `unknown`. Le total des stations suivies passe également
à `unknown` dès qu’une seule station n’est plus fiable.

Une panne de transport complète est volontairement traitée différemment : si
aucun cluster ne répond, la mise à jour du coordinateur échoue et ses mesures
passent à `unavailable`. Cela permet de distinguer un service injoignable d’un
flux joignable mais incertain. L’entité **Flux en défaut** reste disponible et
signale la panne.

### Sémantique de `is_renting`

`num_bikes_available` est publié tel que fourni par l’opérateur lorsque la
station est installée et que les données sont fraîches, même si
`is_renting` vaut `false`. L’intégration conserve ainsi l’inventaire publié
au lieu de le réinterpréter silencieusement.

Pour répondre à la question opérationnelle « puis-je louer un vélo ici
maintenant ? », utilisez toujours le capteur binaire **Location possible** avec
le nombre de vélos. Une station peut contenir des vélos tout en refusant
temporairement les locations.

## Pourquoi une bascule entre clusters ?

Les réseaux Fifteen peuvent être déplacés d’un cluster d’infrastructure à un
autre. De plus, un document d’auto-découverte GBFS peut temporairement annoncer
des URL situées sur un autre cluster défaillant.

L’intégration dérive donc les flux voisins depuis l’URL qui a réellement
répondu et contrôle le contenu de chaque candidat avant de le retenir.

## Diagnostics

L’intégration fournit notamment :

- **Hôte du flux** : serveur Fifteen actuellement utilisé ;
- **Flux mis à jour** : horodatage annoncé par le flux GBFS ;
- **Flux en défaut** : actif si le flux est injoignable, périmé, incomplet ou
  contient une station suivie dont le relevé est périmé ;
- **Vélos sur les stations suivies** : total tout ou rien.

Les diagnostics de l’intégration peuvent être téléchargés depuis Home
Assistant pour accompagner un signalement. Vérifiez le fichier avant de le
partager : il contient les identifiants des stations et la configuration du
réseau.

## Périmètre et limites

La découverte automatique cible les structures d’URL GBFS observées chez
Fifteen. Ce projet n’utilise pas l’API privée de l’application Fifteen.

La structure des URL, les noms des clusters et le comportement des flux restent
sous le contrôle du fournisseur et peuvent évoluer sans préavis. Les données
GBFS ainsi que les noms Fifteen et Graou’Lib restent soumis aux droits et
conditions de leurs propriétaires respectifs.

## Signaler un problème

Ouvrez un [ticket GitHub](https://github.com/Antaresf1024/home-assistant-fifteen/issues)
en joignant, si possible, les diagnostics de l’intégration après les avoir
vérifiés.

## Licence

[MIT](LICENSE) © 2026 Antaresf1024

---

## English summary

**Fifteen GBFS Stations** is a resilient Home Assistant custom integration for
Fifteen-operated bike-sharing networks, including Graou’Lib Metz.

It automatically probes known Fifteen GBFS clusters and selects a feed only
when its timestamp is fresh and every followed station is present with a recent
report. A feed that responds with uncertain data produces `unknown` values; a
complete transport outage intentionally produces `unavailable`. The
**Rental possible** binary sensor must be considered alongside the reported
bike count when `is_renting` is false.

The integration uses public GBFS feeds only. It requires no Fifteen account,
token or private API. Install it through HACS as a custom integration
repository, or copy `custom_components/gbfs_stations` manually.

This independent community project is not affiliated with or endorsed by
Fifteen, Graou’Lib or Eurométropole de Metz.
