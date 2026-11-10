# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Suivi » : la fiche (poids et calories par jour, objectifs) et les statistiques.

Texte d'une fiche (lisible et modifiable à la main ; la ligne « Date » est un tableau Markdown ordinaire) :

    #scrinium-suivi
    taille: 175
    objectif_poids: 72
    objectif_calories: 2000

    | Date | Poids (kg) | Calories | Note |
    |---|---|---|---|
    | 2026-11-10 | 78.4 | 2100 | pizza |

Un jour peut n'avoir qu'un poids, que des calories, ou les deux. Rien n'est exécuté ; ce n'est pas un avis médical."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-suivi"
LIMITES = {"poids": (20.0, 400.0), "calories": (0, 20000), "taille": (50.0, 250.0)}
_LIGNE = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|(.*)\|\s*$")


def nombre(texte, mini, maxi):
    """« 78,4 » -> 78.4 ; None si ce n'est pas un nombre ou s'il sort des limites."""
    t = str(texte if texte is not None else "").strip().replace(",", ".").replace(" ", "")
    t = re.sub(r"\s*(kg|kcal|cm)$", "", t, flags=re.I)
    try:
        v = float(t)
    except ValueError:
        return None
    return v if mini <= v <= maxi and v == v else None


def lire_poids(texte) -> float | None:
    v = nombre(texte, *LIMITES["poids"])
    return None if v is None else round(v, 1)


def lire_calories(texte) -> int | None:
    v = nombre(texte, *LIMITES["calories"])
    return None if v is None else int(round(v))


def lire_jour(texte) -> str:
    """« 2026-11-10 » ou « 10/11/2026 » -> « 2026-11-10 » ; chaîne vide si invalide."""
    t = str(texte or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


@dataclass
class Suivi:
    taille: float | None = None                          # cm (pour l'indice de masse corporelle)
    objectif_poids: float | None = None                  # kg
    objectif_calories: int | None = None                 # kcal par jour
    jours: dict = field(default_factory=dict)            # « 2026-11-10 » -> {"poids": float|None, "calories": int|None, "note": str}

    def _jour(self, jour: str) -> dict:
        return self.jours.setdefault(jour, {"poids": None, "calories": None, "note": ""})

    def _nettoyer(self, jour: str):
        j = self.jours.get(jour)
        if j and j["poids"] is None and j["calories"] is None and not j["note"]:
            del self.jours[jour]

    def poser_poids(self, jour: str, kg) -> bool:
        v = lire_poids(kg) if not isinstance(kg, float) else lire_poids(str(kg))
        if not lire_jour(jour) or (v is None and kg not in (None, "")):
            return False
        self._jour(jour)["poids"] = v
        self._nettoyer(jour)
        return True

    def poser_calories(self, jour: str, kcal) -> bool:
        v = lire_calories(kcal)
        if not lire_jour(jour) or (v is None and kcal not in (None, "")):
            return False
        self._jour(jour)["calories"] = v
        self._nettoyer(jour)
        return True

    def ajouter_calories(self, jour: str, kcal) -> bool:
        """Ajoute des calories au total du jour (on mange plusieurs fois par jour). Un nombre négatif retire (correction), sans descendre sous 0."""
        v = nombre(kcal, -LIMITES["calories"][1], LIMITES["calories"][1])
        if not lire_jour(jour) or v is None:
            return False
        j = self._jour(jour)
        j["calories"] = min(LIMITES["calories"][1], max(0, (j["calories"] or 0) + int(round(v))))
        return True

    def poser_note(self, jour: str, note: str):
        if lire_jour(jour):
            self._jour(jour)["note"] = " ".join(str(note).replace("|", "/").split())[:200]
            self._nettoyer(jour)

    def supprimer(self, jour: str):
        self.jours.pop(jour, None)

    def serie(self, cle: str, depuis: str | None = None) -> list:
        """[(jour, valeur)] triés pour « poids » ou « calories », à partir du jour `depuis` (inclus)."""
        return [(j, d[cle]) for j, d in sorted(self.jours.items()) if d[cle] is not None and (depuis is None or j >= depuis)]


# ---------- le texte de la fiche ----------
def lire(texte: str | None) -> Suivi:
    s = Suivi()
    for ligne in (texte or "").lstrip("﻿").splitlines():
        m = _LIGNE.match(ligne.strip())
        if m:
            jour = lire_jour(m[1])
            cases = [c.strip() for c in m[2].split("|")]
            cases += [""] * (3 - len(cases))
            if jour and jour not in s.jours:
                s.jours[jour] = {"poids": lire_poids(cases[0]), "calories": lire_calories(cases[1]), "note": cases[2][:200]}
                s._nettoyer(jour)
        elif ":" in ligne and not ligne.startswith(("|", "#")):
            cle, _sep, valeur = ligne.partition(":")
            cle = cle.strip().lower()
            if cle == "taille":
                s.taille = nombre(valeur, *LIMITES["taille"])
            elif cle == "objectif_poids":
                s.objectif_poids = lire_poids(valeur)
            elif cle == "objectif_calories":
                s.objectif_calories = lire_calories(valeur)
    return s


def _n(v: float) -> str:
    return ("%.1f" % v).rstrip("0").rstrip(".") if v is not None else ""


def ecrire(s: Suivi) -> str:
    sortie = [MARQUE]
    if s.taille:
        sortie.append("taille: " + _n(s.taille))
    if s.objectif_poids:
        sortie.append("objectif_poids: " + _n(s.objectif_poids))
    if s.objectif_calories:
        sortie.append("objectif_calories: %d" % s.objectif_calories)
    sortie += ["", "| Date | Poids (kg) | Calories | Note |", "|---|---|---|---|"]
    for jour, d in sorted(s.jours.items()):
        sortie.append("| %s | %s | %s | %s |" % (jour, _n(d["poids"]) if d["poids"] is not None else "",
                                                d["calories"] if d["calories"] is not None else "", d["note"]))
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return ecrire(Suivi())


TYPE = TypeFiche("suivi", N_("Suivi poids et calories"), "office-chart-line", modele=texte_neuf)


# ---------- statistiques ----------
def dernier_poids(s: Suivi):
    serie = s.serie("poids")
    return serie[-1] if serie else None


def variation(s: Suivi, jours: int):
    """Variation du poids (kg) entre la dernière pesée et la dernière pesée faite au plus tard `jours` jours avant elle ; None sans les deux."""
    dernier = dernier_poids(s)
    if not dernier:
        return None
    limite = (date.fromisoformat(dernier[0]) - timedelta(days=jours)).isoformat()
    avant = [p for j, p in s.serie("poids") if j <= limite]
    return round(dernier[1] - avant[-1], 1) if avant else None


def moyenne_calories(s: Suivi, jours: int, fin: date):
    """Moyenne des calories des `jours` derniers jours (jusqu'à `fin`), sur les jours renseignés ; None sans donnée."""
    debut = (fin - timedelta(days=jours - 1)).isoformat()
    valeurs = [c for j, c in s.serie("calories", debut) if j <= fin.isoformat()]
    return round(sum(valeurs) / len(valeurs)) if valeurs else None


def imc(kg: float | None, cm: float | None):
    """Indice de masse corporelle (kg/m²), un chiffre après la virgule ; None sans poids ou sans taille. Un nombre, pas un diagnostic."""
    return round(kg / (cm / 100) ** 2, 1) if kg and cm else None


def ecart_objectif(s: Suivi):
    """Kilos qui restent à perdre (positif) ou à prendre (négatif) pour atteindre l'objectif ; None sans objectif ou sans pesée."""
    d = dernier_poids(s)
    return round(d[1] - s.objectif_poids, 1) if d and s.objectif_poids else None


def reste_calories(s: Suivi, jour: str):
    if not s.objectif_calories:
        return None
    return s.objectif_calories - (s.jours.get(jour, {}).get("calories") or 0)


def exemples(aujourdhui: date | None = None) -> list:
    """[(thème, titre, texte)] : un suivi d'exemple sur trois semaines (valeurs inventées)."""
    auj = aujourdhui or date.today()
    s = Suivi(taille=175, objectif_poids=74, objectif_calories=2100)
    poids = [78.6, 78.4, 78.5, 78.1, 78.0, 77.9, 78.2, 77.8, 77.6, 77.7, 77.4, 77.3, 77.5, 77.1, 77.0, 76.9, 77.0, 76.6, 76.5, 76.4, 76.2]
    kcal = [2250, 2050, 2400, 1950, 2100, 2600, 2000, 2150, 1900, 2050, 2300, 2000, 2450, 1850, 2100, 2200, 1950, 2000, 2350, 2050, 1700]
    for i, (p, c) in enumerate(zip(poids, kcal)):
        jour = (auj - timedelta(days=len(poids) - 1 - i)).isoformat()
        s.poser_poids(jour, p)
        s.poser_calories(jour, c)
    return [(_("Suivi (exemples)"), _("Exemple · Poids et calories"), ecrire(s))]
