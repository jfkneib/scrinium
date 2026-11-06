# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Calculatrice » : un évaluateur arithmétique SÛR (jamais d'`eval` : on lit l'arbre syntaxique et
on n'accepte que des nombres, quelques opérateurs et quelques fonctions)."""
import ast
import math
import operator
import re

from scrinium.i18n import N_

MAX_EXPOSANT = 1000
MAX_LONGUEUR = 500
_BINAIRES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNAIRES = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_FACTORIELLE = 170
def _cbrt(x):
    """Racine cubique (math.cbrt n'existe qu'à partir de Python 3.11)."""
    r = round(abs(x) ** (1 / 3))
    r = float(r) if r ** 3 == abs(x) else abs(x) ** (1 / 3)
    return -r if x < 0 else r


FONCTIONS = {"sqrt": math.sqrt, "cbrt": _cbrt, "abs": abs, "round": round, "min": min, "max": max, "ln": math.log, "log": math.log10,
             "log2": math.log2, "exp": math.exp, "floor": math.floor, "ceil": math.ceil, "sinh": math.sinh, "cosh": math.cosh,
             "tanh": math.tanh, "rad": math.radians, "deg": math.degrees}


def _factorielle(n):
    if n != int(n) or n < 0 or n > MAX_FACTORIELLE:
        raise ErreurCalcul(N_("Résultat impossible"))
    return math.factorial(int(n))


def _fonctions(degres: bool) -> dict:
    """Fonctions permises ; les angles sont en degrés ou en radians selon le mode (sin, cos, tan, asin, acos, atan)."""
    def entree(f):
        return (lambda x: f(math.radians(x))) if degres else f

    def sortie(f):
        return (lambda x: math.degrees(f(x))) if degres else f

    def net(f):                                              # sin(180°) = 0 et non 1,2e-16
        return lambda x: round(f(x), 12) + 0.0

    def tangente(x):
        if degres and x % 180 == 90:
            raise ErreurCalcul(N_("Résultat impossible"))
        return math.tan(math.radians(x) if degres else x)

    f = dict(FONCTIONS)
    f.update({"sin": net(entree(math.sin)), "cos": net(entree(math.cos)), "tan": net(tangente),
              "asin": sortie(math.asin), "acos": sortie(math.acos), "atan": sortie(math.atan), "fact": _factorielle})
    return f
CONSTANTES = {"pi": math.pi, "e": math.e}


class ErreurCalcul(ValueError):
    """Expression invalide ou calcul impossible (le message est montré tel quel à l'utilisateur)."""


def _normaliser(expr: str) -> str:
    expr = expr.strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("²", "**2")
    expr = re.sub(r"√\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", expr).replace("√", "sqrt")      # « √9 » = sqrt(9) ; « √(9) » = sqrt(9)
    expr = expr.replace("^", "**")
    expr = re.sub(r"(\d+(?:\.\d+)?|\([^()]*\))\s*!", r"fact(\1)", expr)                 # « 5! » = fact(5)
    if not re.search(r"[A-Za-z]", expr):                         # virgule décimale (« 1,5 ») seulement hors appel de fonction
        expr = re.sub(r"(\d),(\d)", r"\1.\2", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(])", r"(\1/100)", expr)    # « 20% » = 0,2 ; « 7 % 3 » reste un modulo
    return re.sub(r"\)\s*\(", ")*(", re.sub(r"(?<![A-Za-z])(\d)\s*\(", r"\1*(", expr))   # « 2(3+1) » = 2*(3+1)


def _eval(n, fonctions):
    if isinstance(n, ast.Expression):
        return _eval(n.body, fonctions)
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return n.value
    if isinstance(n, ast.Name) and n.id in CONSTANTES:
        return CONSTANTES[n.id]
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UNAIRES:
        return _UNAIRES[type(n.op)](_eval(n.operand, fonctions))
    if isinstance(n, ast.BinOp) and type(n.op) in _BINAIRES:
        a, b = _eval(n.left, fonctions), _eval(n.right, fonctions)
        if isinstance(n.op, ast.Pow) and abs(b) > MAX_EXPOSANT:
            raise ErreurCalcul(N_("Exposant trop grand"))
        return _BINAIRES[type(n.op)](a, b)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in fonctions and not n.keywords:
        args = [_eval(x, fonctions) for x in n.args]
        try:
            return fonctions[n.func.id](*args)
        except ValueError:                                  # hors du domaine : sqrt(-1), ln(0), asin(2)…
            raise ErreurCalcul(N_("Résultat impossible")) from None
    raise ErreurCalcul(N_("Expression non comprise"))


def calculer(expr: str, degres: bool = False):
    """Valeur (int ou float) de l'expression ; `degres` : les angles de sin, cos, tan, asin, acos, atan sont en degrés (sinon en radians).
    ErreurCalcul si elle est vide, invalide ou impossible (division par zéro…)."""
    expr = _normaliser(expr or "")
    if not expr:
        raise ErreurCalcul(N_("Rien à calculer"))
    if len(expr) > MAX_LONGUEUR:
        raise ErreurCalcul(N_("Expression trop longue"))
    try:
        v = _eval(ast.parse(expr, mode="eval"), _fonctions(degres))
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


def calcul_texte(expr: str, degres: bool = False) -> str:
    """Résultat formaté de l'expression (ErreurCalcul sinon)."""
    return formater(calculer(expr, degres))
