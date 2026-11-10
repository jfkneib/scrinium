# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Journal : une entrée par jour (humeur + texte) dans une seule fiche (sans interface)."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-journal"
HEURE_RAPPEL = 18                                       # à partir de cette heure, la pastille rappelle d'écrire
MAX_ENTREES = 20000
HUMEURS = {0: "", 1: "😞", 2: "😕", 3: "😐", 4: "🙂", 5: "😀"}
_ENTETE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*(?:\|\s*humeur\s*:\s*(\d))?\s*$", re.I)


@dataclass
class Entree:
    humeur: int = 0
    texte: str = ""


@dataclass
class Journal:
    entrees: dict = field(default_factory=dict)         # « 2026-11-10 » -> Entree


def lire(texte: str | None) -> Journal:
    j, courant, corps = Journal(), None, []

    def fermer():
        if courant is not None:
            t = "\n".join(corps).strip("\n")
            if courant in j.entrees:                      # deux fois le même jour : on garde les deux textes
                prec = j.entrees[courant]
                prec.texte = (prec.texte + "\n\n" + t).strip()
            elif len(j.entrees) < MAX_ENTREES:
                j.entrees[courant] = Entree(humeur_courante[0], t)
    humeur_courante = [0]
    for ligne in (texte or "").lstrip("﻿").splitlines():
        m = _ENTETE.match(ligne.rstrip())
        if m:
            try:
                datetime.strptime(m[1], "%Y-%m-%d")
            except ValueError:
                m = None
        if m:
            fermer()
            courant, corps = m[1], []
            humeur_courante[0] = min(5, int(m[2])) if m[2] else 0
        elif courant is not None:
            corps.append(ligne)
    fermer()
    return j


def ecrire(j: Journal) -> str:
    sortie = [MARQUE]
    for jour in sorted(j.entrees, reverse=True):          # le plus récent d'abord : lisible tel quel
        e = j.entrees[jour]
        if not e.texte.strip() and not e.humeur:
            continue
        sortie += ["", f"## {jour}" + (f" | humeur: {e.humeur}" if e.humeur else "")]
        sortie += [(" " + ligne if _ENTETE.match(ligne) else ligne) for ligne in e.texte.strip("\n").splitlines()]
    return "\n".join(sortie) + "\n"


def definir(j: Journal, jour: str, humeur: int, texte: str) -> None:
    if texte.strip() or humeur:
        j.entrees[jour] = Entree(min(5, max(0, humeur)), texte)
    else:
        j.entrees.pop(jour, None)


def il_y_a(j: Journal, jour: date) -> list:
    """[(années, jour ISO, entrée)] : ce qui a été écrit à la même date les années précédentes (le plus récent d'abord)."""
    res = []
    for annee in range(jour.year - 1, jour.year - 30, -1):
        try:
            d = jour.replace(year=annee).isoformat()
        except ValueError:                                # 29 février
            continue
        if d in j.entrees and j.entrees[d].texte.strip():
            res.append((jour.year - annee, d, j.entrees[d]))
    return res


def serie(j: Journal, aujourdhui: date) -> int:
    """Jours consécutifs écrits, jusqu'à aujourd'hui (ou hier : la journée n'est pas finie)."""
    d = aujourdhui if aujourdhui.isoformat() in j.entrees else aujourdhui - timedelta(days=1)
    n = 0
    while d.isoformat() in j.entrees and j.entrees[d.isoformat()].texte.strip():
        n += 1
        d -= timedelta(days=1)
    return n


def humeur_moyenne(j: Journal, aujourdhui: date, jours: int = 30) -> float | None:
    v = [e.humeur for k, e in j.entrees.items() if e.humeur and (aujourdhui - date.fromisoformat(k)).days in range(jours)]
    return round(sum(v) / len(v), 1) if v else None


def a_faire(texte: str, maintenant: datetime | None = None) -> str | None:
    """Pastille de la liste : le soir, si le journal est tenu mais qu'il n'y a encore rien pour aujourd'hui."""
    m = maintenant or datetime.now()
    if m.hour < HEURE_RAPPEL:
        return None
    j = lire(texte)
    if not j.entrees or m.date().isoformat() in j.entrees:
        return None
    return _("Rien d'écrit pour aujourd'hui")


def texte_neuf() -> str:
    return MARQUE + "\n"


def exemples(aujourdhui: date | None = None) -> list:
    auj = aujourdhui or date.today()
    j = Journal()
    definir(j, (auj - timedelta(days=1)).isoformat(), 4, _("Une bonne journée. Promenade et lecture."))
    definir(j, auj.isoformat(), 3, _("Journée calme. Du rangement."))
    return [(_("Journal (exemples)"), _("Exemple · Mon journal"), ecrire(j))]


TYPE = TypeFiche("journal", N_("Journal"), "view-calendar-day", modele=texte_neuf, a_faire=a_faire)
