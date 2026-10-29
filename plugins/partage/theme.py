# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partage d'un thème entier : partie sans interface de l'extension « Partage ».

Le serveur ne connaît que des fiches : partager un thème, c'est partager chacune de ses fiches **non verrouillées et à moi**
(les verrouillées et celles reçues d'un autre compte sont écartées, et comptées). Les « membres » du thème sont les comptes qui ont
le MÊME droit sur toutes ces fiches mises en ligne. Un thème peut être « suivi » : à chaque synchronisation, ses nouvelles fiches
sont mises en ligne avec les droits communs des autres."""
from scrinium.core.synchroniser import publier
from scrinium.core.transport import ErreurTransport, Introuvable, Refuse


def fiches_du_theme(store, th, transport) -> tuple[list, list, int]:
    """([(fiche, id déjà connu du serveur ou None)] partageables, [titres écartés (reçues d'un autre)], nombre de verrouillées)."""
    distantes = {r.id: r for r in transport.lister()}
    pretes, autres, verrouillees = [], [], 0
    for f in th.fiches:
        if f.verrou:
            verrouillees += 1
            continue
        ident = store.id_fiche(f)
        r = distantes.get(ident) if ident else None
        if r is not None and r.role != "proprietaire":
            autres.append(f.titre)
            continue
        pretes.append((f, ident if r is not None else None))
    return pretes, autres, verrouillees


def mettre_en_ligne(store, etat, transport, th, pretes) -> list:
    """Publie celles qui ne le sont pas encore ; rend les identifiants de toutes."""
    ids = []
    for f, ident in pretes:
        if ident is None:
            publier(store, etat, transport, th, f)
        ids.append(store.assurer_id(th, f))
    return ids


def droits_communs(transport, idents) -> dict:
    """{compte: rôle} identique sur TOUTES ces fiches (le propriétaire exclu)."""
    commun = None
    for ident in idents:
        try:
            d = {c: r for c, r in transport.droits(ident).items() if r != "proprietaire"}
        except (Refuse, Introuvable):
            continue
        commun = d if commun is None else {c: r for c, r in commun.items() if d.get(c) == r}
    return commun or {}


def partager_theme(store, etat, transport, th, compte, role) -> int:
    """Donne le droit à un compte existant sur tout le thème. Retourne le nombre de fiches."""
    pretes, _autres, _v = fiches_du_theme(store, th, transport)
    ids = mettre_en_ligne(store, etat, transport, th, pretes)
    for ident in ids:
        transport.partager(ident, compte, role)
    return len(ids)


def retirer_theme(store, transport, th, compte) -> None:
    pretes, _a, _v = fiches_du_theme(store, th, transport)
    for _f, ident in pretes:
        if ident is not None:
            try:
                transport.retirer_droit(ident, compte)
            except (Introuvable, Refuse):
                pass


def inviter_theme(store, etat, transport, th, email, role) -> tuple[int, dict]:
    """Une seule invitation (un seul lien) pour tout le thème. Retourne (nombre de fiches, invitation)."""
    pretes, _autres, _v = fiches_du_theme(store, th, transport)
    if not pretes:
        raise ValueError("aucune fiche partageable dans ce thème (verrouillées ou reçues d'un autre compte)")
    ids = mettre_en_ligne(store, etat, transport, th, pretes)
    return len(ids), transport.inviter_groupe(ids, email, role)


def propager(store, etat, transport, th) -> list:
    """Thème suivi : met en ligne les nouvelles fiches avec les droits communs des déjà en ligne. Titres des fiches ajoutées."""
    pretes, _autres, _v = fiches_du_theme(store, th, transport)
    anciennes = [ident for _f, ident in pretes if ident is not None]
    nouvelles = [f for f, ident in pretes if ident is None]
    if not nouvelles:
        return []
    droits = droits_communs(transport, anciennes) if anciennes else {}
    ajoutees = []
    for f in nouvelles:
        try:
            publier(store, etat, transport, th, f)
            ident = store.assurer_id(th, f)
            for compte, role in droits.items():
                transport.partager(ident, compte, role)
        except ErreurTransport:
            raise
        ajoutees.append(f.titre)
    return ajoutees
