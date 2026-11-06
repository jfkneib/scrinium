# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Calculatrice » : un évaluateur arithmétique SÛR (jamais d'`eval` : on lit l'arbre syntaxique et
on n'accepte que des nombres, quelques opérateurs et quelques fonctions) et le format du type de fiche `calculatrice`.

    #scrinium-calculatrice
    2+3*4 = 14
    sqrt(16) = 4

Type NON exécutable : la fiche ne lance rien, elle garde seulement l'historique « calcul = résultat » (une ligne par calcul ; tout
ce qui n'est pas de la forme `calcul = résultat` est conservé tel quel)."""
import ast
import math
import operator
import re

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_

MARQUE = "#scrinium-calculatrice"
TYPE = TypeFiche("calculatrice", N_("Calculatrice"), "accessories-calculator")

MAX_EXPOSANT = 1000
MAX_LONGUEUR = 500
_BINAIRES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNAIRES = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FONCTIONS = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max, "sin": math.sin, "cos": math.cos, "tan": math.tan,
             "ln": math.log, "log": math.log10, "exp": math.exp, "floor": math.floor, "ceil": math.ceil}
CONSTANTES = {"pi": math.pi, "e": math.e}


class ErreurCalcul(ValueError):
    """Expression invalide ou calcul impossible (le message est montré tel quel à l'utilisateur)."""


def _normaliser(expr: str) -> str:
    expr = expr.strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("²", "**2")
    expr = re.sub(r"√\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", expr).replace("√", "sqrt")      # « √9 » = sqrt(9) ; « √(9) » = sqrt(9)
    expr = expr.replace("^", "**")
    if not re.search(r"[A-Za-z]", expr):                         # virgule décimale (« 1,5 ») seulement hors appel de fonction
        expr = re.sub(r"(\d),(\d)", r"\1.\2", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(])", r"(\1/100)", expr)    # « 20% » = 0,2 ; « 7 % 3 » reste un modulo
    return re.sub(r"\)\s*\(", ")*(", re.sub(r"(\d)\s*\(", r"\1*(", expr))   # « 2(3+1) » = 2*(3+1)


def _eval(n):
    if isinstance(n, ast.Expression):
        return _eval(n.body)
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return n.value
    if isinstance(n, ast.Name) and n.id in CONSTANTES:
        return CONSTANTES[n.id]
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UNAIRES:
        return _UNAIRES[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.BinOp) and type(n.op) in _BINAIRES:
        a, b = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > MAX_EXPOSANT:
            raise ErreurCalcul(N_("Exposant trop grand"))
        return _BINAIRES[type(n.op)](a, b)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FONCTIONS and not n.keywords:
        return FONCTIONS[n.func.id](*[_eval(x) for x in n.args])
    raise ErreurCalcul(N_("Expression non comprise"))


def calculer(expr: str):
    """Valeur (int ou float) de l'expression. ErreurCalcul si elle est vide, invalide ou impossible (division par zéro…)."""
    expr = _normaliser(expr or "")
    if not expr:
        raise ErreurCalcul(N_("Rien à calculer"))
    if len(expr) > MAX_LONGUEUR:
        raise ErreurCalcul(N_("Expression trop longue"))
    try:
        v = _eval(ast.parse(expr, mode="eval"))
    except ErreurCalcul:
        raise
    except ZeroDivisionError:
        raise ErreurCalcul(N_("Division par zéro")) from None
    except (SyntaxError, ValueError, TypeError, OverflowError, RecursionError, MemoryError):
        raise ErreurCalcul(N_("Expression non comprise")) from None
    if isinstance(v, complex) or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        raise ErreurCalcul(N_("Résultat impossible"))
    return v


def formater(v) -> str:
    """Texte du résultat : entier exact, sinon 12 chiffres significatifs sans zéros inutiles."""
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return format(v, ".12g")


def calcul_texte(expr: str) -> str:
    """Résultat formaté de l'expression (ErreurCalcul sinon)."""
    return formater(calculer(expr))


# ---------- format de la fiche ----------
def historique(texte: str | None) -> list:
    """[(calcul, résultat)] des lignes « calcul = résultat » de la fiche, dans l'ordre."""
    sortie = []
    for ligne in (texte or "").replace("\r\n", "\n").split("\n")[1:]:
        if "=" in ligne:
            calcul, _sep, res = ligne.rpartition("=")
            if calcul.strip() and res.strip():
                sortie.append((calcul.strip(), res.strip()))
    return sortie


def ajouter(texte: str | None, expr: str, resultat: str) -> str:
    """Texte de la fiche avec la ligne « calcul = résultat » ajoutée à la fin (la marque est mise si elle manque)."""
    lignes = (texte or "").replace("\r\n", "\n").split("\n")
    if not lignes or not lignes[0].startswith(MARQUE):
        lignes = [MARQUE] + [x for x in lignes if x.strip()]
    corps = "\n".join(lignes).rstrip("\n")
    return corps + f"\n{expr.strip()} = {resultat}\n"
