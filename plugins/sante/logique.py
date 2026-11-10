# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Santé : tension et traitement (sans interface). Un carnet, pas un avis médical : les repères de couleur sont indicatifs.

Texte de la fiche : `## Tension` (tableau : date, heure, haute, basse, pouls, note), `## Traitement` (tableau : médicament, dose, horaires, du, au, note),
`## Prises` (une ligne `AAAA-MM-JJ HH:MM nom` par prise cochée, 90 jours conservés)."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-sante"
MAX_MESURES = 5000
MAX_MEDICAMENTS = 50
CONSERVER_PRISES = 90                                    # jours
TOLERANCE = 30                                           # minutes : une prise est « en retard » (pastille) passé son horaire
_HEURE = re.compile(r"^([01]?\d|2[0-3])[:h]([0-5]\d)$")


@dataclass
class Mesure:
    jour: str
    heure: str
    haute: int
    basse: int
    pouls: int = 0
    note: str = ""


@dataclass
class Medicament:
    nom: str
    dose: str = ""
    horaires: list = field(default_factory=list)         # ["08:00", "20:00"]
    debut: str = ""
    fin: str = ""
    note: str = ""


@dataclass
class Document:
    mesures: list = field(default_factory=list)
    medicaments: list = field(default_factory=list)
    prises: set = field(default_factory=set)             # {(« 2026-11-10 », « 08:00 », « nom »)}


def lire_jour(t) -> str:
    t = str(t or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def lire_heure(t) -> str:
    m = _HEURE.match(str(t or "").strip().lower())
    return f"{int(m[1]):02d}:{m[2]}" if m else ""


def lire_horaires(t) -> list:
    res = []
    for x in re.split(r"[,;/ ]+", str(t or "")):
        h = lire_heure(x)
        if h and h not in res:
            res.append(h)
    return sorted(res)


def _entier(t, mini, maxi) -> int:
    m = re.search(r"\d+", str(t or ""))
    v = int(m[0]) if m else 0
    return v if mini <= v <= maxi else 0


def mesure_valide(haute: int, basse: int) -> bool:
    return 50 <= haute <= 300 and 30 <= basse <= 200 and haute > basse


def lire(texte: str | None) -> Document:
    d, section = Document(), None
    for brut in (texte or "").lstrip("﻿").splitlines():
        ligne = brut.strip()
        if ligne.startswith("## "):
            titre = ligne[3:].strip().lower()
            section = "tension" if titre.startswith("tens") else ("traitement" if titre.startswith("trait") else ("prises" if titre.startswith("pris") else None))
            continue
        if section == "prises":
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) (.{1,80})", ligne)
            if m and lire_jour(m[1]):
                d.prises.add((m[1], m[2], m[3]))
        elif section in ("tension", "traitement") and ligne.startswith("|"):
            c = [x.strip() for x in ligne.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", x) for x in c if x):
                continue
            if section == "tension" and len(c) >= 4 and lire_jour(c[0]) and len(d.mesures) < MAX_MESURES:
                h, b = _entier(c[2], 0, 400), _entier(c[3], 0, 400)
                if mesure_valide(h, b):
                    d.mesures.append(Mesure(lire_jour(c[0]), lire_heure(c[1]), h, b, _entier(c[4] if len(c) > 4 else "", 20, 250),
                                            (c[5] if len(c) > 5 else "")[:200]))
            elif section == "traitement" and len(c) >= 1 and c[0] and not (c[0].casefold() in ("médicament", "medicament") and (len(c) < 2 or c[1].casefold() == "dose")) and len(d.medicaments) < MAX_MEDICAMENTS:
                d.medicaments.append(Medicament(" ".join(c[0].split())[:80], (c[1] if len(c) > 1 else "")[:40], lire_horaires(c[2] if len(c) > 2 else ""),
                                                lire_jour(c[3] if len(c) > 3 else ""), lire_jour(c[4] if len(c) > 4 else ""), (c[5] if len(c) > 5 else "")[:200]))
    return d


def ecrire(d: Document, aujourdhui: date | None = None) -> str:
    auj = aujourdhui or date.today()
    s = [MARQUE, "", "## Tension", "| Date | Heure | Haute | Basse | Pouls | Note |", "|---|---|---|---|---|---|"]
    for m in sorted(d.mesures, key=lambda m: (m.jour, m.heure))[-MAX_MESURES:]:
        s.append("| %s | %s | %d | %d | %s | %s |" % (m.jour, m.heure, m.haute, m.basse, m.pouls or "", m.note.replace("|", "/")))
    s += ["", "## Traitement", "| Médicament | Dose | Horaires | Du | Au | Note |", "|---|---|---|---|---|---|"]
    for x in d.medicaments[:MAX_MEDICAMENTS]:
        s.append("| %s | %s | %s | %s | %s | %s |" % (x.nom.replace("|", "/"), x.dose.replace("|", "/"), ", ".join(x.horaires), x.debut, x.fin, x.note.replace("|", "/")))
    limite = (auj - timedelta(days=CONSERVER_PRISES)).isoformat()
    s += ["", "## Prises"] + [f"{j} {h} {n}" for j, h, n in sorted(d.prises) if j >= limite]
    return "\n".join(s) + "\n"


# ---------- tension ----------
def categorie(haute: int, basse: int) -> str:
    """Repère indicatif (classes de la Société européenne d'hypertension) : le plus élevé des deux chiffres décide."""
    if haute >= 180 or basse >= 110:
        return "grave"
    if haute >= 160 or basse >= 100:
        return "forte2"
    if haute >= 140 or basse >= 90:
        return "forte1"
    if haute >= 130 or basse >= 85:
        return "limite"
    if haute >= 120 or basse >= 80:
        return "normale"
    return "optimale"


LIBELLES = {"optimale": N_("optimale"), "normale": N_("normale"), "limite": N_("normale haute"), "forte1": N_("élevée (grade 1)"),
            "forte2": N_("élevée (grade 2)"), "grave": N_("très élevée (grade 3)")}
COULEURS = {"optimale": "#bfe6c2", "normale": "#d8f0c0", "limite": "#fff0a8", "forte1": "#ffd9a0", "forte2": "#ffb3a0", "grave": "#ff8f8f"}


def moyenne(mesures: list, aujourdhui: date, jours: int = 30):
    """(haute, basse, pouls) moyens sur les `jours` derniers jours, ou None."""
    m = [x for x in mesures if 0 <= (aujourdhui - date.fromisoformat(x.jour)).days < jours]
    if not m:
        return None
    p = [x.pouls for x in m if x.pouls]
    return (round(sum(x.haute for x in m) / len(m)), round(sum(x.basse for x in m) / len(m)), round(sum(p) / len(p)) if p else 0)


# ---------- traitement ----------
def en_cours(x: Medicament, jour: date) -> bool:
    j = jour.isoformat()
    return (not x.debut or x.debut <= j) and (not x.fin or j <= x.fin)


def prises_du_jour(d: Document, jour: date) -> list:
    """[(heure, médicament, dose, pris ?)] de la journée, dans l'ordre des heures."""
    res = []
    for x in d.medicaments:
        if en_cours(x, jour):
            for h in x.horaires:
                res.append((h, x.nom, x.dose, (jour.isoformat(), h, x.nom) in d.prises))
    return sorted(res)


def basculer_prise(d: Document, jour: date, heure: str, nom: str) -> None:
    cle = (jour.isoformat(), heure, nom)
    d.prises.symmetric_difference_update({cle})


def en_retard(d: Document, maintenant: datetime) -> list:
    """Prises du jour non cochées dont l'horaire (plus 30 minutes) est passé."""
    limite = (maintenant - timedelta(minutes=TOLERANCE)).strftime("%H:%M")
    return [(h, n, dose) for h, n, dose, pris in prises_du_jour(d, maintenant.date()) if not pris and h <= limite]


def a_faire(texte: str, maintenant: datetime | None = None) -> str | None:
    retard = en_retard(lire(texte), maintenant or datetime.now())
    return _("%d prise(s) de médicament à cocher") % len(retard) if retard else None


def texte_neuf() -> str:
    return ecrire(Document())


def exemples(aujourdhui: date | None = None) -> list:
    auj = aujourdhui or date.today()
    d = Document()
    for i, (h, b) in enumerate([(128, 82), (135, 86), (122, 78), (141, 91), (126, 80)]):
        d.mesures.append(Mesure((auj - timedelta(days=4 - i)).isoformat(), "08:00", h, b, 68 + i))
    d.medicaments.append(Medicament(_("Médicament exemple"), _("1 comprimé"), ["08:00", "20:00"], (auj - timedelta(days=30)).isoformat()))
    return [(_("Santé (exemples)"), _("Exemple · Mon carnet de santé"), ecrire(d, auj))]


TYPE = TypeFiche("sante", N_("Santé (tension, traitement)"), "health", modele=texte_neuf, a_faire=a_faire)
