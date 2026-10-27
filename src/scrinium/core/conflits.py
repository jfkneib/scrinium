# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Conflits de synchronisation : décider quoi faire, et ne JAMAIS perdre ni écraser en silence (aucun accès réseau ici).

Trois états se comparent pour une fiche suivie : la BASE (ce qui était vrai à la dernière synchronisation réussie, dans l'état de
synchronisation), le LOCAL (la fiche telle qu'elle est maintenant) et le DISTANT (la dernière version du serveur).

    local inchangé,  distant inchangé  -> rien
    local inchangé,  distant plus récent -> recevoir
    local modifié,   distant inchangé  -> envoyer (si on a le droit d'écrire ; sinon : écarter, voir plus bas)
    local modifié,   distant plus récent -> CONFLIT

Résolution (conflit, ou modification locale sur une fiche en lecture seule) : la version LOCALE est mise de côté dans une nouvelle fiche
« titre (conflit AAAA-MM-JJ HH:MM) » (texte et images, sans identifiant : elle n'est pas partagée), la version DISTANTE est reprise
dans la fiche d'origine, et l'utilisateur en est prévenu par l'appelant. Les images remplacées vont à la corbeille."""
import time
from dataclasses import dataclass, field

from .store import Fiche, Store, Theme
from .synchro import EtatSynchro

ROLES_ECRITURE = ("proprietaire", "ecriture")


@dataclass
class ContenuDistant:
    """Dernière version d'une fiche sur le serveur."""
    version: int
    titre: str
    texte: str
    pieces: list = field(default_factory=list)       # [(nom, type MIME, octets)]


def decider(entree: dict, modifiee_localement: bool, version_distante: int, role: str,
            empreinte_locale: str | None = None, empreinte_distante: str | None = None) -> str:
    """Action à faire pour une fiche suivie : « rien », « recevoir », « envoyer », « aligner », « conflit » ou « ecarter ».

    - « aligner » : les deux côtés ont changé mais sont IDENTIQUES (empreintes égales) : il suffit de mémoriser la nouvelle version ;
    - « ecarter » : modification locale sur une fiche en lecture seule (jamais envoyée) : traitée comme un conflit (copie locale)."""
    distant_plus_recent = version_distante > int(entree.get("version", 0))
    if not modifiee_localement:
        return "recevoir" if distant_plus_recent else "rien"
    if not distant_plus_recent:
        return "envoyer" if role in ROLES_ECRITURE else "ecarter"
    if empreinte_locale is not None and empreinte_locale == empreinte_distante:
        return "aligner"
    return "conflit"


def mettre_de_cote(store: Store, th: Theme, f: Fiche, motif: str = "conflit", maintenant: str | None = None) -> tuple:
    """Copie la version locale (titre, texte, images) dans une NOUVELLE fiche du même thème, sans identifiant, et la retourne."""
    if f.verrou:
        raise ValueError("fiche verrouillée : pas synchronisée à ce stade")
    quand = maintenant or time.strftime("%Y-%m-%d %H:%M")
    copie = store.nouvelle_fiche(th)
    store.enregistrer(th, copie, f"{f.titre} ({motif} {quand})", f.texte or "")
    for p in store.lister_pieces(f):
        store.ajouter_piece(copie, p.nom, p.type, store.lire_piece(f, p))
    return th, copie


def appliquer_distant(store: Store, etat: EtatSynchro, th: Theme, f: Fiche, distant: ContenuDistant) -> str:
    """Remplace le contenu local par la version du serveur (titre, texte, images ; les anciennes images vont à la corbeille) et
    mémorise la version. L'identifiant de la fiche ne change pas. Donne l'identifiant."""
    if f.verrou:
        raise ValueError("fiche verrouillée : pas synchronisée à ce stade")
    store.enregistrer(th, f, distant.titre, distant.texte)
    for p in store.lister_pieces(f):
        store.supprimer_piece(f, p)
    for nom, type_, octets in distant.pieces:
        store.ajouter_piece(f, nom, type_, octets)
    return etat.valider(store, th, f, distant.version)


def resoudre(store: Store, etat: EtatSynchro, th: Theme, f: Fiche, distant: ContenuDistant, motif: str = "conflit",
             maintenant: str | None = None) -> tuple:
    """Résolution d'un conflit (ou d'une modification locale refusée) : la version locale est mise de côté, la distante reprise.
    Retourne (thème, fiche de la copie locale). Rien n'est perdu : si la copie ne peut pas être faite, la fiche d'origine n'est pas touchée."""
    copie = mettre_de_cote(store, th, f, motif, maintenant)       # d'abord la copie : en cas d'échec, l'original reste intact
    appliquer_distant(store, etat, th, f, distant)
    return copie
