# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Calc » : un petit éditeur de LISTES avec de petits calculs (`#scrinium-calc`).

    #scrinium-calc
    | Date | Valeur |
    | --- | --- |
    | 2026-11-06 | 12,5 |
    | 2026-11-07 | 13 |

    totaux: | somme

Une liste = un tableau Markdown (première ligne : les en-têtes). La ligne « totaux: » dit, colonne par colonne, quel total afficher en bas
(somme, moyenne, min, max, nb ; vide = aucun). Pas de formules cellule par cellule : c'est le rôle de l'extension Tableur. Type NON
exécutable. Le reste du texte (notes libres) est conservé. (Les petites fonctions de lecture du tableau ressemblent à celles du Tableur :
les extensions sont indépendantes, l'une peut être activée sans l'autre.)"""
import csv
import io
import re
from datetime import date

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-calc"
MAX_LIGNES = 5000
MAX_COLONNES = 52
TOTAUX = ("somme", "moyenne", "min", "max", "nb")
_TOTAUX_LIGNE = re.compile(r"^totaux[ \t]*:(.*)$", re.IGNORECASE)


def _decouper(ligne: str) -> list:
    s = ligne.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def _ligne(cellules: list) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cellules) + " |"


def lire(texte: str | None) -> tuple:
    """(lignes, totaux, notes) : `lignes` rectangulaire (texte brut) ; `totaux` = un nom de total (ou « ») par colonne ; `notes` = le reste."""
    corps = (texte or "").replace("\r\n", "\n").split("\n")
    if corps and corps[0].startswith(MARQUE):
        corps = corps[1:]
    lignes, notes, spec = [], [], None
    for l in corps:
        m = _TOTAUX_LIGNE.match(l.strip())
        if l.lstrip().startswith("|"):
            c = _decouper(l)
            if not all(re.fullmatch(r":?-{3,}:?", x) for x in c):
                lignes.append(c)
        elif m:
            spec = [x.strip().lower() for x in m.group(1).split("|")]
        else:
            notes.append(l)
    while notes and not notes[-1].strip():
        notes.pop()
    while notes and not notes[0].strip():
        notes.pop(0)
    lignes = lignes[:MAX_LIGNES]
    largeur = min(max((len(r) for r in lignes), default=0), MAX_COLONNES)
    lignes = [(r + [""] * largeur)[:largeur] for r in lignes]
    spec = [x if x in TOTAUX else "" for x in (spec or [])]
    return lignes, (spec + [""] * largeur)[:largeur], "\n".join(notes)


def ecrire(lignes: list, totaux: list | None = None, notes: str = "") -> str:
    sortie = [MARQUE]
    if lignes:
        sortie += [_ligne(lignes[0]), "|" + " --- |" * len(lignes[0])] + [_ligne(r) for r in lignes[1:]]
        if any(totaux or []):
            sortie += ["", ("totaux: " + " | ".join(totaux)).replace(":  |", ": |").rstrip()]
    if notes.strip():
        sortie += ["", notes.strip("\n")]
    return "\n".join(sortie) + "\n"


def vide(colonnes: int = 2, lignes: int = 5) -> list:
    entetes = [_("Date"), _("Valeur")] + [""] * max(0, colonnes - 2)
    return [entetes[:colonnes]] + [[""] * colonnes for _i in range(lignes)]


def texte_neuf() -> str:
    return ecrire(vide(), ["", "somme"])


TYPE = TypeFiche("calc", N_("Calc"), "view-list-details", modele=texte_neuf)


# ---------- nombres et totaux ----------
def nombre(texte: str):
    """Nombre contenu dans le texte d'une cellule (« 12,5 », « 1 200.5 », « 8% »), sinon None."""
    s = texte.strip().replace("\u00a0", "").replace(" ", "")
    pct = s.endswith("%")
    s = s[:-1] if pct else s
    if not s or ("," in s and "." in s):
        return None
    s = s.replace(",", ".")
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", s):
        return None
    v = float(s) / (100 if pct else 1)
    return int(v) if v == int(v) and abs(v) < 1e15 else v


def formater(v) -> str:
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return format(v, ".10g").replace(".", ",")


def total(lignes: list, colonne: int, fonction: str):
    """Total (texte formaté) d'une colonne sur les lignes de données (hors en-tête) ; chaîne vide s'il n'y a rien à calculer."""
    if fonction not in TOTAUX:
        return ""
    nums = [n for r in lignes[1:] if (n := nombre(r[colonne])) is not None]
    if fonction == "nb":
        return str(len(nums))
    if not nums:
        return ""
    return formater({"somme": sum(nums), "moyenne": sum(nums) / len(nums), "min": min(nums), "max": max(nums)}[fonction])


def ajouter_ligne(lignes: list, aujourdhui: date | None = None) -> list:
    """Ajoute une ligne vide ; si la première colonne s'intitule « Date », elle reçoit la date du jour (AAAA-MM-JJ)."""
    lignes = lignes or vide()
    nouvelle = [""] * len(lignes[0])
    if lignes[0][0].strip().lower() in ("date", "jour", "day"):
        nouvelle[0] = (aujourdhui or date.today()).isoformat()
    return lignes + [nouvelle]


# ---------- CSV ----------
def vers_csv(lignes: list, separateur: str = ";") -> str:
    """CSV (« ; » par défaut : LibreOffice et Excel en français l'ouvrent directement)."""
    sortie = io.StringIO()
    csv.writer(sortie, delimiter=separateur, lineterminator="\n").writerows(lignes)
    return sortie.getvalue()


def depuis_csv(texte: str) -> list:
    """Tableau rectangulaire lu dans un CSV ; le séparateur (; , tabulation |) est deviné sur la première ligne."""
    texte = (texte or "").lstrip("\ufeff").replace("\r\n", "\n")
    sep = max((";", ",", "\t", "|"), key=texte.split("\n", 1)[0].count)
    lignes = [r for r in csv.reader(io.StringIO(texte), delimiter=sep) if any(c.strip() for c in r)][:MAX_LIGNES]
    largeur = min(max((len(r) for r in lignes), default=0), MAX_COLONNES)
    return [([c.strip() for c in r] + [""] * largeur)[:largeur] for r in lignes]
