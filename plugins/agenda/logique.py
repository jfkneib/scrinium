# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Agenda et rappels » : événements, échéances, rappels à notifier.

Un événement : {"id", "titre", "quand" ("AAAA-MM-JJ HH:MM", heure locale), "fiche" ({"theme", "titre"} ou None), "notifie" (bool)}."""
import uuid
from datetime import datetime, timedelta

FORMAT = "%Y-%m-%d %H:%M"
MAX_EVENEMENTS = 2000


def en_date(texte: str) -> datetime | None:
    try:
        return datetime.strptime(str(texte), FORMAT)
    except ValueError:
        return None


def en_texte(d: datetime) -> str:
    return d.strftime(FORMAT)


def normaliser(e) -> dict | None:
    """Événement valide (champs nettoyés) ou None s'il n'a ni titre ni date lisible."""
    if not isinstance(e, dict):
        return None
    titre = " ".join(str(e.get("titre", "")).split())
    quand = en_date(e.get("quand", ""))
    if not titre or quand is None:
        return None
    fiche = e.get("fiche")
    if isinstance(fiche, dict) and fiche.get("theme") and fiche.get("titre"):
        fiche = {"theme": str(fiche["theme"]), "titre": str(fiche["titre"])}
    else:
        fiche = None
    return {"id": str(e.get("id") or uuid.uuid4().hex[:12]), "titre": titre[:200], "quand": en_texte(quand), "fiche": fiche,
            "notifie": bool(e.get("notifie"))}


def charger(brut) -> list:
    """Liste d'événements valides, triés par date, sans doublon d'identifiant."""
    vus, res = set(), []
    for e in brut if isinstance(brut, list) else []:
        n = normaliser(e)
        if n and n["id"] not in vus:
            vus.add(n["id"])
            res.append(n)
    return sorted(res, key=lambda x: x["quand"])[:MAX_EVENEMENTS]


def ajouter(evenements: list, titre: str, quand: datetime, fiche: dict | None = None, id_: str | None = None) -> dict:
    """Ajoute un événement (ValueError si le titre est vide ou la liste pleine) ; renvoie l'événement créé."""
    if len(evenements) >= MAX_EVENEMENTS:
        raise ValueError("trop d'événements")
    n = normaliser({"titre": titre, "quand": en_texte(quand), "fiche": fiche, "id": id_})
    if n is None:
        raise ValueError("titre vide")
    evenements.append(n)
    evenements.sort(key=lambda x: x["quand"])
    return n


def a_notifier(evenements: list, maintenant: datetime) -> list:
    """Événements dont l'heure est venue et qui n'ont pas encore été annoncés."""
    return [e for e in evenements if not e["notifie"] and en_date(e["quand"]) <= maintenant]


def a_venir(evenements: list, maintenant: datetime) -> list:
    return [e for e in evenements if en_date(e["quand"]) > maintenant]


def delai_texte(quand: datetime, maintenant: datetime) -> str:
    """« dans 3 h », « demain 09:00 », « il y a 2 j »… (court, pour une liste)."""
    from scrinium.i18n import _
    ecart = quand - maintenant
    if ecart < timedelta(0):
        retard = -ecart
        if retard < timedelta(hours=1):
            return _("en retard de %d min") % max(1, retard.seconds // 60)
        if retard < timedelta(days=1):
            return _("en retard de %d h") % (retard.seconds // 3600)
        return _("en retard de %d j") % retard.days
    if ecart < timedelta(hours=1):
        return _("dans %d min") % max(1, ecart.seconds // 60)
    if ecart < timedelta(days=1):
        return _("dans %d h") % (ecart.seconds // 3600)
    return _("dans %d j") % ecart.days
