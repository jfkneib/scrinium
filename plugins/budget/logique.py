# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Budget » : un petit suivi de comptes (courses, argent de poche…), pas de la comptabilité.

    #scrinium-budget
    budget: 400
    depart: 50
    mois 2026-11: Rentrée scolaire

    | Date | Libellé | Catégorie | Débit | Crédit |
    | --- | --- | --- | --- | --- |
    | 2026-11-03 | Carrefour | Courses | 45,30 | |
    | 2026-11-05 | Argent de poche | | | 10 |

- `budget:` budget mensuel (facultatif) ; `depart:` solde de départ (facultatif) ; `mois AAAA-MM:` titre d'un onglet (facultatif).
- Une fiche = un budget. Les montants sont gardés en CENTIMES entiers (jamais de dérive de virgule flottante) ; le solde n'est pas écrit :
  il est recalculé. Type NON exécutable. Le reste du texte (notes libres) est conservé.
- Une seconde fiche, `budget-resultat`, totalise tous les budgets (voir `__init__.py`)."""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-budget"
MARQUE_RESULTAT = "#scrinium-budget-resultat"
ENTETES = ["Date", "Libellé", "Catégorie", "Débit", "Crédit"]
MAX_OPERATIONS = 20000


@dataclass
class Operation:
    date: str                  # AAAA-MM-JJ
    libelle: str = ""
    categorie: str = ""
    debit: int = 0             # centimes
    credit: int = 0            # centimes


@dataclass
class Budget:
    operations: list = field(default_factory=list)
    depart: int = 0                                   # solde de départ, centimes
    mensuel: int | None = None                        # budget mensuel, centimes (None = non fixé)
    titres: dict = field(default_factory=dict)        # « 2026-11 » -> titre de l'onglet
    notes: str = ""


# ---------- montants ----------
def centimes(texte) -> int | None:
    """« 45,30 », « 1 200.5 », « 45 € » -> centimes (4530) ; None si ce n'est pas un montant (vide compris)."""
    s = str(texte or "").strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace("€", "")
    if not s or ("," in s and "." in s):
        return None
    s = s.replace(",", ".")
    if not re.fullmatch(r"[+-]?(\d+\.?\d{0,2}|\.\d{1,2})", s):
        return None
    sign = -1 if s.startswith("-") else 1
    entier, _p, dec = s.lstrip("+-").partition(".")
    return sign * (int(entier or 0) * 100 + int((dec + "00")[:2]))


def formater(c: int, fixe: bool = True) -> str:
    """Centimes -> « 45,30 » (deux décimales) ; `fixe=False` : « 45 » quand c'est rond (pour le texte de la fiche)."""
    signe = "-" if c < 0 else ""
    e, d = divmod(abs(int(c)), 100)
    return f"{signe}{e}" + ("" if (d == 0 and not fixe) else f",{d:02d}")


def date_valide(texte: str) -> bool:
    try:
        date.fromisoformat((texte or "").strip())
        return True
    except ValueError:
        return False


def mois_de(texte_date: str) -> str:
    return texte_date.strip()[:7]


def mois_valide(m: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m or ""))


def mois_suivant(m: str) -> str:
    a, n = int(m[:4]), int(m[5:7])
    return f"{a + (n == 12)}-{1 if n == 12 else n + 1:02d}"


def mois_courant(aujourdhui: date | None = None) -> str:
    return (aujourdhui or date.today()).strftime("%Y-%m")


# ---------- le texte de la fiche ----------
def _decouper(ligne: str) -> list:
    s = ligne.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def lire(texte: str | None) -> Budget:
    b = Budget()
    corps = (texte or "").replace("\r\n", "\n").split("\n")
    if corps and corps[0].startswith(MARQUE):
        corps = corps[1:]
    notes = []
    for l in corps:
        m = re.match(r"^(budget|depart|départ)[ \t]*:(.*)$", l.strip(), re.IGNORECASE)
        t = re.match(r"^mois[ \t]+(\d{4}-\d{2})[ \t]*:(.*)$", l.strip(), re.IGNORECASE)
        if l.lstrip().startswith("|"):
            c = _decouper(l)
            if all(re.fullmatch(r":?-{3,}:?", x) for x in c) or c[:1] == ["Date"] or len(b.operations) >= MAX_OPERATIONS:
                continue
            c = (c + [""] * 5)[:5]
            if mois_valide(mois_de(c[0])) and date_valide(c[0]):
                b.operations.append(Operation(c[0].strip(), c[1], c[2], max(0, centimes(c[3]) or 0), max(0, centimes(c[4]) or 0)))
        elif m:
            v = centimes(m.group(2))
            if m.group(1).lower() == "budget":
                b.mensuel = v if v and v > 0 else None
            else:
                b.depart = v or 0
        elif t and mois_valide(t.group(1)):
            if t.group(2).strip():
                b.titres[t.group(1)] = t.group(2).strip()
        else:
            notes.append(l)
    while notes and not notes[-1].strip():
        notes.pop()
    while notes and not notes[0].strip():
        notes.pop(0)
    b.notes = "\n".join(notes)
    return b


def _cellule(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def ecrire(b: Budget) -> str:
    """Texte de la fiche : en-têtes, tableau (trié par date, l'ordre de saisie est gardé à date égale), notes."""
    sortie = [MARQUE]
    if b.mensuel:
        sortie.append("budget: " + formater(b.mensuel, False))
    if b.depart:
        sortie.append("depart: " + formater(b.depart, False))
    sortie += [f"mois {m}: {t}" for m, t in sorted(b.titres.items()) if t.strip()]
    sortie += ["", "| Date | Libellé | Catégorie | Débit | Crédit |", "| --- | --- | --- | --- | --- |"]
    for o in sorted(b.operations, key=lambda o: o.date):                    # tri stable
        sortie.append("| " + " | ".join([o.date, _cellule(o.libelle), _cellule(o.categorie),
                                          formater(o.debit, False) if o.debit else "", formater(o.credit, False) if o.credit else ""]) + " |")
    if b.notes.strip():
        sortie += ["", b.notes.strip("\n")]
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return ecrire(Budget())


# ---------- calculs ----------
def mois_presents(b: Budget, aujourdhui: date | None = None) -> list:
    """Mois à montrer en onglets, du plus ancien au plus récent (sans trou) ; le mois courant s'il n'y a rien."""
    ms = {mois_de(o.date) for o in b.operations} | set(b.titres)
    if not ms:
        ms = {mois_courant(aujourdhui)}
    premier, dernier, sortie = min(ms), max(ms), []
    m = premier
    while m <= dernier and len(sortie) < 600:
        sortie.append(m)
        m = mois_suivant(m)
    return sortie


def operations_du_mois(b: Budget, mois: str) -> list:
    """[(indice dans b.operations, Operation)] du mois, triées par date (ordre de saisie à date égale)."""
    return sorted(((i, o) for i, o in enumerate(b.operations) if mois_de(o.date) == mois), key=lambda x: (x[1].date, x[0]))


def solde_avant(b: Budget, mois: str) -> int:
    """Solde au début du mois : départ + crédits - débits de tous les mois précédents."""
    return b.depart + sum(o.credit - o.debit for o in b.operations if mois_de(o.date) < mois)


def totaux(b: Budget, mois: str | None = None) -> dict:
    """{débit, crédit, solde du mois, solde de fin, reste sur le budget (None si non fixé)} pour un mois (ou pour toute la fiche)."""
    ops = [o for o in b.operations if mois is None or mois_de(o.date) == mois]
    d, c = sum(o.debit for o in ops), sum(o.credit for o in ops)
    debut = b.depart if mois is None else solde_avant(b, mois)
    return {"debit": d, "credit": c, "solde_mois": c - d, "solde_fin": debut + c - d, "debut": debut,
            "reste": (b.mensuel - d) if (b.mensuel and mois is not None) else None}


def par_categorie(b: Budget, mois: str | None = None) -> list:
    """[(catégorie, total des débits)] décroissant ; les opérations sans catégorie sont regroupées sous « » (à nommer à l'affichage)."""
    t: dict = {}
    for o in b.operations:
        if o.debit and (mois is None or mois_de(o.date) == mois):
            t[o.categorie.strip()] = t.get(o.categorie.strip(), 0) + o.debit
    return sorted(t.items(), key=lambda x: (-x[1], x[0].lower()))


def categories(b: Budget) -> list:
    return sorted({o.categorie.strip() for o in b.operations if o.categorie.strip()}, key=str.lower)


def resume_par_mois(b: Budget) -> list:
    """[(mois, titre, totaux)] pour chaque mois présent."""
    return [(m, b.titres.get(m, ""), totaux(b, m)) for m in mois_presents(b)]


def vers_csv(b: Budget, separateur: str = ";") -> str:
    """CSV Date;Libellé;Catégorie;Débit;Crédit;Solde (« ; » : LibreOffice et Excel en français l'ouvrent directement)."""
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=separateur, lineterminator="\n")
    w.writerow(["Date", "Libellé", "Catégorie", "Débit", "Crédit", "Solde"])
    solde = b.depart
    for o in sorted(b.operations, key=lambda o: o.date):
        solde += o.credit - o.debit
        w.writerow([o.date, o.libelle, o.categorie, formater(o.debit) if o.debit else "", formater(o.credit) if o.credit else "", formater(solde)])
    return sortie.getvalue()


def est_budget(texte: str | None) -> bool:
    t = (texte or "").lstrip("\ufeff")
    return t.startswith(MARQUE) and not t.startswith(MARQUE_RESULTAT) and (len(t) == len(MARQUE) or t[len(MARQUE)] in " \t\r\n")


def resultat(budgets: list, mois: str | None = None) -> dict:
    """Totaux de plusieurs budgets : `budgets` = [(nom, Budget)]. {lignes: [(nom, totaux)], total: totaux cumulés}."""
    lignes = [(nom, totaux(b, mois)) for nom, b in budgets]
    cumul = {k: sum(t[k] for _n, t in lignes) for k in ("debit", "credit", "solde_mois", "solde_fin", "debut")}
    cumul["reste"] = sum(t["reste"] for _n, t in lignes if t["reste"] is not None) if any(t["reste"] is not None for _n, t in lignes) else None
    return {"lignes": lignes, "total": cumul}


def mois_de_tous(budgets: list) -> list:
    ms = set()
    for _n, b in budgets:
        ms |= {mois_de(o.date) for o in b.operations}
    return sorted(ms)


TYPE = TypeFiche("budget", N_("Budget"), "wallet-open", modele=texte_neuf)
TYPE_RESULTAT = TypeFiche("budget-resultat", N_("Budget — résultat"), "view-statistics", modele=lambda: MARQUE_RESULTAT + "\n")
