# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Dépôts : le dépôt PERSONNEL (les fiches locales, comme toujours) et des dépôts PARTAGÉS, un par serveur de partage.

Un dépôt partagé est seulement un réglage (nom, adresse du serveur, compte, thème d'arrivée) enregistré dans settings.json ; son
état de synchronisation vit dans `<données>/synchro/<nom>.json` (voir `synchro`). Aucun mot de passe ici : le plugin « Partage »
le garde dans le trousseau du système."""
from dataclasses import dataclass
from urllib.parse import urlparse

from .store import Store
from .synchro import chemin_etat

THEME_ARRIVEE = "Partagées"
HOTES_LOCAUX = ("localhost", "127.0.0.1", "::1")


@dataclass
class Depot:
    nom: str                        # identifiant du dépôt (nom du fichier d'état) : lettres, chiffres, « - », « _ », « . »
    url: str                        # adresse du serveur : https obligatoire (http seulement vers l'ordinateur local, pour les essais)
    compte: str                     # identifiant du compte sur ce serveur
    theme: str = THEME_ARRIVEE      # thème local où arrivent les fiches reçues


def valider(d: Depot) -> Depot:
    """Dépôt nettoyé, ou ValueError (nom, adresse ou compte inutilisables)."""
    nom = "".join(c for c in d.nom.strip() if c.isalnum() or c in "-_.")
    if not nom or nom != d.nom.strip():
        raise ValueError("nom de dépôt invalide (lettres, chiffres, « - », « _ » et « . » seulement)")
    u = urlparse(d.url.strip())
    if not u.hostname or u.scheme not in ("https", "http") or (u.scheme == "http" and u.hostname not in HOTES_LOCAUX):
        raise ValueError("adresse du serveur invalide : https obligatoire (http seulement vers l'ordinateur local)")
    if not d.compte.strip():
        raise ValueError("compte absent")
    theme = d.theme.strip().replace("/", "-").replace("\\", "-") or THEME_ARRIVEE
    return Depot(nom, d.url.strip().rstrip("/"), d.compte.strip(), theme)


def lire_depots(store: Store) -> list:
    """Dépôts partagés enregistrés (ceux dont le réglage est inutilisable sont ignorés)."""
    res = []
    for brut in store.reglages().get("depots", []) if isinstance(store.reglages().get("depots", []), list) else []:
        try:
            res.append(valider(Depot(str(brut.get("nom", "")), str(brut.get("url", "")), str(brut.get("compte", "")),
                                     str(brut.get("theme", THEME_ARRIVEE)))))
        except (ValueError, AttributeError):
            continue
    return res


def enregistrer_depot(store: Store, depot: Depot) -> Depot:
    """Ajoute le dépôt, ou remplace celui qui porte le même nom."""
    d = valider(depot)
    autres = [x for x in lire_depots(store) if x.nom != d.nom]
    store.sauver_reglages(depots=[vars(x) for x in autres + [d]])
    return d


def supprimer_depot(store: Store, nom: str) -> None:
    """Oublie le dépôt ; ses fiches locales sont conservées (elles redeviennent de simples fiches) et son fichier d'état est supprimé."""
    store.sauver_reglages(depots=[vars(x) for x in lire_depots(store) if x.nom != nom])
    chemin_etat(store, nom).unlink(missing_ok=True)
