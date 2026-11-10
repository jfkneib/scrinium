# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Échéances » : la fiche, la prochaine date d'une échéance qui se répète, les statuts, les totaux et les rappels.

Texte d'une fiche (un tableau Markdown ordinaire, lisible et modifiable à la main) :

    #scrinium-echeances
    devise: €

    | Échéance | Date | Répétition | Montant | Rappel (jours) | Note |
    |---|---|---|---|---|---|
    | Assurance auto | 2026-12-15 | annuel | 612 | 30 | contrat 123 |

Répétition : vide (une fois), mensuel, trimestriel, semestriel, annuel, 2 ans. Une échéance qui se répète passe d'elle-même à la date suivante ;
une échéance « une fois » dont la date est passée est « en retard » jusqu'à ce qu'on la modifie ou la supprime."""
import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-echeances"
MAX_ECHEANCES = 300
RAPPEL_DEFAUT = 30
# (nombre de mois, mot écrit dans la fiche, libellé)
REPETITIONS = ((0, "", N_("Une fois")), (1, "mensuel", N_("Chaque mois")), (3, "trimestriel", N_("Chaque trimestre")),
               (6, "semestriel", N_("Chaque semestre")), (12, "annuel", N_("Chaque année")), (24, "2 ans", N_("Tous les 2 ans")))
_MOTS = {mot: mois for mois, mot, _l in REPETITIONS if mot} | {"mois": 1, "trimestre": 3, "semestre": 6, "an": 12, "annee": 12, "année": 12,
                                                              "bisannuel": 24, "24 mois": 24, "12 mois": 12, "6 mois": 6, "3 mois": 3, "1 mois": 1,
                                                              "monthly": 1, "yearly": 12, "annual": 12}
_LIGNE = re.compile(r"\|\s*(.*?)\s*\|\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\s*\|(.*)\|\s*$")


def lire_jour(texte) -> str:
    t = str(texte or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def lire_repetition(texte) -> int:
    t = str(texte or "").strip().lower()
    return _MOTS.get(t, _MOTS.get(t.removeprefix("chaque ").removeprefix("tous les ").strip(), 0))


def mot_repetition(mois: int) -> str:
    return next((mot for m, mot, _l in REPETITIONS if m == mois), "")


def lire_montant(texte) -> float | None:
    t = re.sub(r"[^\d,.\-]", "", str(texte or "").replace(" ", ""))
    try:
        v = float(t.replace(",", "."))
    except ValueError:
        return None
    return v if 0 <= v <= 1e9 else None


def formater_montant(v: float | None, devise: str = "€") -> str:
    if v is None:
        return ""
    t = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    t = t[:-3] if t.endswith(",00") else t
    return f"{t} {devise}".strip()


@dataclass
class Echeance:
    nom: str
    date: str                                            # prochaine échéance connue (« 2026-12-15 »)
    mois: int = 0                                        # 0 = une fois ; sinon période de répétition en mois
    montant: float | None = None
    rappel: int = RAPPEL_DEFAUT                          # jours avant la date où l'on est prévenu
    note: str = ""


@dataclass
class Document:
    devise: str = "€"
    echeances: list = None

    def __post_init__(self):
        self.echeances = self.echeances or []


def normaliser(e: Echeance) -> Echeance | None:
    nom, jour = " ".join(str(e.nom).replace("|", "/").split())[:80], lire_jour(e.date)
    if not nom or not jour:
        return None
    return Echeance(nom, jour, e.mois if e.mois in {m for m, _mot, _l in REPETITIONS} else 0, e.montant,
                    min(max(int(e.rappel), 0), 365), " ".join(str(e.note).replace("|", "/").split())[:200])


# ---------- le texte de la fiche ----------
def lire(texte: str | None) -> Document:
    doc = Document()
    for ligne in (texte or "").lstrip("﻿").splitlines():
        m = _LIGNE.match(ligne.strip())
        if m:
            c = [x.strip() for x in m[3].split("|")] + [""] * 4
            try:
                rappel = int(c[2]) if c[2] else RAPPEL_DEFAUT
            except ValueError:
                rappel = RAPPEL_DEFAUT
            e = normaliser(Echeance(m[1], m[2], lire_repetition(c[0]), lire_montant(c[1]), rappel, c[3]))
            if e and len(doc.echeances) < MAX_ECHEANCES:
                doc.echeances.append(e)
        elif ":" in ligne and not ligne.startswith(("|", "#")) and ligne.partition(":")[0].strip().lower() == "devise":
            doc.devise = ligne.partition(":")[2].strip()[:6] or "€"
    return doc


def ecrire(doc: Document) -> str:
    sortie = [MARQUE, "devise: " + doc.devise, "", "| Échéance | Date | Répétition | Montant | Rappel (jours) | Note |", "|---|---|---|---|---|---|"]
    for e in doc.echeances[:MAX_ECHEANCES]:
        montant = "" if e.montant is None else (("%.2f" % e.montant).rstrip("0").rstrip("."))
        sortie.append("| %s | %s | %s | %s | %d | %s |" % (e.nom.replace("|", "/"), e.date, mot_repetition(e.mois), montant, e.rappel,
                                                         e.note.replace("|", "/").replace("\n", " ")))
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return ecrire(Document())


TYPE = TypeFiche("echeances", N_("Échéances et abonnements"), "view-calendar-tasks", modele=texte_neuf)


# ---------- dates ----------
def ajouter_mois(d: date, n: int) -> date:
    """d + n mois ; le jour est ramené à la fin du mois si besoin (31 janvier + 1 mois = 28 ou 29 février)."""
    total = d.year * 12 + (d.month - 1) + n
    annee, mois = divmod(total, 12)
    return date(annee, mois + 1, min(d.day, calendar.monthrange(annee, mois + 1)[1]))


def prochaine(e: Echeance, aujourdhui: date) -> date:
    """Prochaine date : celle de la fiche, ou, pour une échéance qui se répète et dont la date est passée, la première date à venir de la série."""
    origine = date.fromisoformat(e.date)
    if not e.mois or origine >= aujourdhui:
        return origine
    k = max(0, ((aujourdhui.year - origine.year) * 12 + aujourdhui.month - origine.month) // e.mois)
    d = ajouter_mois(origine, k * e.mois)
    while d < aujourdhui:
        k += 1
        d = ajouter_mois(origine, k * e.mois)
    return d


def occurrences(e: Echeance, du: date, au: date) -> list:
    """Dates de l'échéance comprises entre `du` et `au` (inclus)."""
    origine = date.fromisoformat(e.date)
    if not e.mois:
        return [origine] if du <= origine <= au else []
    res, k = [], 0
    d = origine
    while d <= au:
        if d >= du:
            res.append(d)
        k += 1
        d = ajouter_mois(origine, k * e.mois)
        if len(res) > 400:
            break
    return res


def jours_restants(e: Echeance, aujourdhui: date) -> int:
    return (prochaine(e, aujourdhui) - aujourdhui).days


def statut(e: Echeance, aujourdhui: date) -> str:
    """« retard » (une fois, date passée), « urgent » (7 jours ou moins, dans le rappel), « bientot » (dans le rappel), « ok »."""
    j = jours_restants(e, aujourdhui)
    if j < 0:
        return "retard"
    if j <= e.rappel:
        return "urgent" if j <= min(7, e.rappel) else "bientot"
    return "ok"


def trier(echeances: list, aujourdhui: date) -> list:
    return sorted(echeances, key=lambda e: (prochaine(e, aujourdhui), e.nom.lower()))


def resume(doc: Document, aujourdhui: date) -> dict:
    """Chiffres de la fiche : retards, échéances sous 30 jours, montant à payer sous 30 jours et sur 12 mois (toutes les occurrences à venir)."""
    horizon30, horizon365 = aujourdhui + timedelta(days=30), aujourdhui + timedelta(days=365)
    retards = [e for e in doc.echeances if statut(e, aujourdhui) == "retard"]
    sous30 = [e for e in doc.echeances if 0 <= jours_restants(e, aujourdhui) <= 30]
    m30 = sum((e.montant or 0) * len(occurrences(e, aujourdhui, horizon30)) for e in doc.echeances)
    m365 = sum((e.montant or 0) * len(occurrences(e, aujourdhui, horizon365)) for e in doc.echeances)
    return {"retards": len(retards), "sous30": len(sous30), "montant30": m30, "montant365": m365}


# ---------- rappels ----------
def a_notifier(doc: Document, aujourdhui: date, deja: dict, prefixe: str) -> list:
    """[(cle, échéance, jours restants)] à signaler : une seule fois par échéance et par date (rappel), et une fois pour un retard.
    `deja` (cle -> jour de la notification) est mis à jour ; les entrées de plus d'un an sont oubliées."""
    for cle in [c for c, j in deja.items() if j < (aujourdhui - timedelta(days=400)).isoformat()]:
        del deja[cle]
    res = []
    for e in doc.echeances:
        s = statut(e, aujourdhui)
        if s == "ok":
            continue
        cle = f"{prefixe}|{e.nom}|{prochaine(e, aujourdhui).isoformat()}|{'retard' if s == 'retard' else 'rappel'}"
        if cle not in deja:
            deja[cle] = aujourdhui.isoformat()
            res.append((cle, e, jours_restants(e, aujourdhui)))
    return res


def message(e: Echeance, jours: int, aujourdhui: date, devise: str = "€") -> str:
    d = prochaine(e, aujourdhui).strftime("%d/%m/%Y")
    montant = (" · " + formater_montant(e.montant, devise)) if e.montant is not None else ""
    if jours < 0:
        return _("« %(nom)s » : échéance dépassée depuis %(n)d jour(s) (%(date)s)%(m)s") % {"nom": e.nom, "n": -jours, "date": d, "m": montant}
    if jours == 0:
        return _("« %(nom)s » : c'est aujourd'hui (%(date)s)%(m)s") % {"nom": e.nom, "date": d, "m": montant}
    return _("« %(nom)s » : dans %(n)d jour(s) (%(date)s)%(m)s") % {"nom": e.nom, "n": jours, "date": d, "m": montant}


def exemples(aujourdhui: date | None = None) -> list:
    """[(thème, titre, texte)] : un exemple d'échéances proches et lointaines (valeurs inventées)."""
    auj = aujourdhui or date.today()
    j = lambda n: (auj + timedelta(days=n)).isoformat()                    # noqa: E731
    doc = Document("€", [
        Echeance(_("Assurance auto"), j(25), 12, 612.0, 30, _("contrat à renouveler")),
        Echeance(_("Abonnement vidéo"), j(5), 1, 13.99, 7, ""),
        Echeance(_("Nom de domaine"), j(100), 12, 12.0, 30, ""),
        Echeance(_("Certificat du site"), j(8), 12, 0.0, 30, _("à renouveler avant la date")),
        Echeance(_("Contrôle technique"), j(200), 24, 78.0, 60, ""),
        Echeance(_("Garantie du lave-linge"), j(40), 0, None, 60, _("garder la facture")),
    ])
    return [(_("Échéances (exemples)"), _("Exemple · Mes échéances"), ecrire(doc))]
