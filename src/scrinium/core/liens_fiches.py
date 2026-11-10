# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Liens entre fiches : `[[Titre]]`, `[[Thème/Titre]]` ou `[[Titre|texte affiché]]` dans le texte d'une fiche (sans interface).

Le lien est **dans le texte** (principe « tout est fiche ») : il survit à la copie, au partage et à l'export. Il se résout par le titre
(sans tenir compte des majuscules) ; un titre en double mène à la première fiche (thème du lien, si donné, puis ordre des thèmes). Une
fiche verrouillée fermée n'a pas de texte lisible : elle peut être la cible d'un lien, mais ne montre pas ses propres liens."""
import re
from urllib.parse import quote

SCHEMA = "scrinium-fiche"
_LIEN = re.compile(r"\[\[([^\[\]\n|]{1,120}?)(?:\|([^\[\]\n]{1,120}))?\]\]")
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)            # le code n'est jamais transformé


def trouver(texte: str | None) -> list:
    """[(cible, texte affiché)] des liens du texte (hors code), dans l'ordre, sans doublon."""
    vus, res = set(), []
    for i, morceau in enumerate(_CODE.split(texte or "")):
        if i % 2:
            continue
        for m in _LIEN.finditer(morceau):
            cible = " ".join(m[1].split())
            if cible and cible.casefold() not in vus:
                vus.add(cible.casefold())
                res.append((cible, " ".join((m[2] or cible).split())))
    return res


def resoudre(store, cible: str):
    """(thème, fiche) désignés par `cible` (« Titre » ou « Thème/Titre »), ou None."""
    cible = " ".join(str(cible).split())
    theme, titre = None, cible
    if "/" in cible:
        t, _sep, reste = cible.partition("/")
        if any(x.nom.casefold() == t.strip().casefold() for x in store.themes):
            theme, titre = t.strip().casefold(), reste.strip()
    for th in store.themes:
        if theme and th.nom.casefold() != theme:
            continue
        for f in th.fiches:
            if f.titre.strip().casefold() == titre.casefold():
                return th, f
    return None


def vers_markdown(texte: str, existe=None) -> str:
    """Le texte pour l'aperçu : chaque `[[lien]]` devient un lien Markdown `scrinium-fiche:cible` (cliquable)."""
    def remplacer(m):
        cible = " ".join(m[1].split())
        if not cible:
            return m[0]
        affiche = " ".join((m[2] or cible).split()).replace("\\", "\\\\")
        marque = "" if existe is None or existe(cible) else " ✚"             # ✚ : la fiche n'existe pas encore (un clic la crée)
        return f"[{affiche}{marque}]({SCHEMA}:{quote(cible, safe='')})"
    sortie = []
    for i, morceau in enumerate(_CODE.split(texte or "")):
        sortie.append(morceau if i % 2 else _LIEN.sub(remplacer, morceau))
    return "".join(sortie)


def liens_de(store, theme, fiche) -> list:
    """[(thème, fiche)] vers lesquelles pointe la fiche (existantes seulement)."""
    if fiche.fermee:
        return []
    res = []
    for cible, _aff in trouver(fiche.texte):
        r = resoudre(store, cible)
        if r is not None and r[1] is not fiche and r not in res:
            res.append(r)
    return res


def retroliens(store, theme, fiche) -> list:
    """[(thème, fiche)] qui pointent vers `fiche` (fiches lisibles seulement)."""
    res = []
    for th in store.themes:
        for f in th.fiches:
            if f is fiche or f.fermee:
                continue
            if any((resoudre(store, c) or (None, None))[1] is fiche for c, _a in trouver(f.texte)):
                res.append((th, f))
    return res
