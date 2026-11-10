# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fiches « liste » (inventaire, collection, mots de passe…) : un tableau Markdown lisible, sans interface.

Le texte d'une fiche : la marque (`#scrinium-<type>`), des réglages `clé: valeur` facultatifs, une ligne vide, puis un tableau Markdown dont
les colonnes sont celles du type. Les colonnes sont lues **par position** (l'en-tête n'est qu'un titre, il peut être traduit ou modifié) ;
un `|` dans une cellule est écrit `/`. Tolérant : une ligne qui n'a pas la bonne forme est ignorée, jamais d'exception."""
import re
from dataclasses import dataclass, field
from datetime import datetime

GENRES = ("texte", "nombre", "date", "case", "choix", "secret")
MAX_LIGNES = 5000


@dataclass(frozen=True)
class Colonne:
    cle: str                                  # identifiant interne
    titre: str                                # titre affiché (N_, traduit à l'affichage)
    genre: str = "texte"                      # texte · nombre · date (AAAA-MM-JJ) · case (oui/vide) · choix · secret (masqué à l'écran)
    choix: tuple = ()                         # valeurs possibles (genre « choix », N_ à traduire à l'affichage)


def lire_nombre(texte) -> str:
    """« 1 200,50 € » -> « 1200.5 » ; chaîne vide si ce n'est pas un nombre."""
    t = re.sub(r"[^\d,.\-]", "", str(texte or "").replace(" ", "").replace("\xa0", "")).replace(",", ".")
    if t.count(".") > 1:
        t = t.replace(".", "", t.count(".") - 1)
    try:
        v = float(t)
    except ValueError:
        return ""
    if v != v or abs(v) > 1e12:
        return ""
    return ("%.2f" % v).rstrip("0").rstrip(".")


def lire_jour(texte) -> str:
    t = str(texte or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def normaliser_cellule(c: Colonne, valeur) -> str:
    v = " ".join(str(valeur if valeur is not None else "").replace("|", "/").split()) if c.genre != "secret" else \
        str(valeur if valeur is not None else "").replace("|", "/").replace("\n", " ").strip()
    if c.genre == "nombre":
        return lire_nombre(v)
    if c.genre == "date":
        return lire_jour(v)
    if c.genre == "case":
        return "oui" if v.lower() in ("oui", "o", "x", "1", "vrai", "true", "yes", "✔") else ""
    if c.genre == "choix":
        return next((x for x in c.choix if x.casefold() == v.casefold()), v if not c.choix else "")
    return v[:500]


def normaliser(colonnes: list, ligne: dict) -> dict:
    return {c.cle: normaliser_cellule(c, ligne.get(c.cle, "")) for c in colonnes}


@dataclass
class Document:
    reglages: dict = field(default_factory=dict)          # clé -> texte (hors tableau)
    lignes: list = field(default_factory=list)            # [{clé de colonne: texte}]


def lire(texte: str | None, marque: str, colonnes: list, cles_reglages: tuple = ()) -> Document:
    doc = Document()
    for brut in (texte or "").lstrip("﻿").splitlines():
        ligne = brut.strip()
        if ligne.startswith(marque):
            continue
        if ligne.startswith("|"):
            cases = [c.strip() for c in ligne.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cases if c) and any(cases):
                continue                                   # ligne de séparation
            if len(doc.lignes) < MAX_LIGNES:
                doc.lignes.append(("brut", cases))
        elif ":" in ligne and not doc.lignes:
            cle, _sep, valeur = ligne.partition(":")
            if cle.strip().lower() in cles_reglages:
                doc.reglages[cle.strip().lower()] = valeur.strip()
    brutes = [c for _t, c in doc.lignes]
    doc.lignes = []
    for i, cases in enumerate(brutes):
        if i == 0 and _est_entete(cases, colonnes):
            continue
        d = normaliser(colonnes, {c.cle: (cases[k] if k < len(cases) else "") for k, c in enumerate(colonnes)})
        if any(d.values()):
            doc.lignes.append(d)
    return doc


def _est_entete(cases: list, colonnes: list) -> bool:
    """Première ligne du tableau : l'en-tête (titres de colonnes, dans une langue ou l'autre), pas une ligne de données."""
    if not cases:
        return False
    premiers = {c.titre.casefold() for c in colonnes}
    return cases[0].casefold() in premiers or cases[0].casefold().startswith("---")


def ecrire(doc: Document, marque: str, colonnes: list, titres: list | None = None) -> str:
    """`titres` : les titres (déjà traduits) pour l'en-tête ; sinon ceux des colonnes."""
    sortie = [marque]
    sortie += [f"{k}: {v}" for k, v in doc.reglages.items() if v != ""]
    sortie += ["", "| " + " | ".join(titres or [c.titre for c in colonnes]) + " |", "|" + "---|" * len(colonnes)]
    for d in doc.lignes[:MAX_LIGNES]:
        sortie.append("| " + " | ".join(normaliser_cellule(c, d.get(c.cle, "")) for c in colonnes) + " |")
    return "\n".join(sortie) + "\n"
