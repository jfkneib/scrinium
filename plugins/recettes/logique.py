# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Recettes : ingrédients, étapes, quantités recalculées pour N personnes (sans interface)."""
import re
from dataclasses import dataclass, field
from fractions import Fraction

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-recettes"
MAX_PERSONNES = 100
MAX_LIGNES = 200
_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8"}
_QUANTITE = re.compile(r"^\s*(?:[-*•]\s*)?(?P<q>\d+\s+\d+/\d+|\d+/\d+|\d+\s*[½¼¾⅓⅔⅛]|[½¼¾⅓⅔⅛]|\d+(?:[.,]\d+)?)(?P<reste>(?!\d).*)$", re.S)


@dataclass
class Recette:
    personnes: int = 4
    temps: str = ""
    etiquettes: list = field(default_factory=list)
    note: int = 0                                         # 0 = pas de note ; 1 à 5 étoiles
    ingredients: list = field(default_factory=list)
    etapes: list = field(default_factory=list)


def _nettoyer(ligne: str) -> str:
    return " ".join(ligne.split())[:200]


def lire(texte: str | None) -> Recette:
    r, section = Recette(), None
    for brut in (texte or "").lstrip("﻿").splitlines():
        ligne = brut.strip()
        if ligne.startswith(MARQUE):
            continue
        if ligne.startswith("## "):
            titre = ligne[3:].strip().lower()
            section = "ing" if titre.startswith("ingr") else ("etapes" if titre[:4] in ("étap", "etap", "prép", "prep", "step") else None)
            continue
        if section is None:
            cle, sep, valeur = ligne.partition(":")
            cle = cle.strip().lower()
            if not sep:
                continue
            if cle == "personnes":
                m = re.search(r"\d+", valeur)
                r.personnes = min(MAX_PERSONNES, max(1, int(m[0]))) if m else 4
            elif cle == "temps":
                r.temps = _nettoyer(valeur)[:40]
            elif cle == "etiquettes":
                r.etiquettes = [e for e in (_nettoyer(x)[:30] for x in valeur.split(",")) if e][:20]
            elif cle == "note":
                m = re.search(r"\d", valeur)
                r.note = min(5, int(m[0])) if m else 0
        elif ligne and section == "ing" and len(r.ingredients) < MAX_LIGNES:
            r.ingredients.append(_nettoyer(re.sub(r"^[-*•]\s*", "", ligne)))
        elif ligne and section == "etapes" and len(r.etapes) < MAX_LIGNES:
            r.etapes.append(re.sub(r"^\d+[.)]\s*", "", ligne)[:1000])
    return r


def ecrire(r: Recette) -> str:
    sortie = [MARQUE, f"personnes: {r.personnes}"]
    if r.temps:
        sortie.append(f"temps: {r.temps}")
    if r.etiquettes:
        sortie.append("etiquettes: " + ", ".join(r.etiquettes))
    if r.note:
        sortie.append(f"note: {r.note}")
    sortie += ["", "## Ingrédients"] + [f"- {i}" for i in r.ingredients if i]
    sortie += ["", "## Étapes"] + [f"{n}. {e}" for n, e in enumerate([e for e in r.etapes if e], 1)]
    return "\n".join(sortie) + "\n"


def _nombre(q: str) -> Fraction | None:
    q = q.strip()
    for k, v in _FRACTIONS.items():
        q = q.replace(k, " " + v)
    try:
        total = Fraction(0)
        for part in q.split():
            total += Fraction(part.replace(",", ".")) if "/" not in part else Fraction(part)
        return total
    except (ValueError, ZeroDivisionError):
        return None


def _formater(v: Fraction, virgule: bool) -> str:
    if v.denominator == 1:
        return str(v.numerator)
    s = ("%.2f" % float(v)).rstrip("0").rstrip(".")
    return s.replace(".", ",") if virgule else s


def mettre_a_l_echelle(ingredient: str, facteur: float) -> str:
    """« 200 g de farine » × 1,5 -> « 300 g de farine » ; une ligne sans quantité au début (« sel », « 1 pincée » est mise à l'échelle) reste telle quelle."""
    m = _QUANTITE.match(ingredient)
    if not m or facteur == 1:
        return ingredient
    v = _nombre(m["q"])
    if v is None:
        return ingredient
    return _formater(v * Fraction(facteur).limit_denominator(1000), "," in m["q"]) + m["reste"]


def pour(r: Recette, personnes: int) -> list:
    """Ingrédients recalculés pour `personnes`."""
    f = personnes / max(1, r.personnes)
    return [mettre_a_l_echelle(i, f) for i in r.ingredients]


def liste_de_courses(recettes: list, personnes: list) -> str:
    return "\n".join("- " + i for r, p in zip(recettes, personnes) for i in pour(r, p))


def etoiles(n: int) -> str:
    return "★" * n + "☆" * (5 - n) if n else ""


def texte_neuf() -> str:
    return ecrire(Recette())


def exemples() -> list:
    r = Recette(4, "40 min", [_("dessert"), _("rapide")], 4,
                [_("200 g de farine"), _("3 œufs"), _("1/2 litre de lait"), _("2 c. à soupe de sucre"), _("1 pincée de sel")],
                [_("Mélanger la farine, le sucre et le sel."), _("Ajouter les œufs puis le lait peu à peu."), _("Laisser reposer 30 minutes, puis cuire à la poêle.")])
    return [(_("Recettes (exemples)"), _("Exemple · Crêpes"), ecrire(r))]


TYPE = TypeFiche("recettes", N_("Recette"), "folder-cookbook", modele=texte_neuf)
