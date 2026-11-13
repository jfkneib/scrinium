# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Images dans le texte d'une fiche : `![légende](pj:N)` montre la pièce jointe n° N à cet endroit (aperçu, PDF, impression).
La pièce reste stockée avec la fiche (verrouillée avec elle) ; seule la référence est dans le texte."""
import re

SCHEMA = "pj"
_REF = re.compile(r"!\[([^\]]*)\]\(\s*pj:(\d+)\s*\)")


def reference(numero: int, legende: str = "") -> str:
    """Le Markdown qui insère la pièce `numero` ; les crochets de la légende sont neutralisés."""
    return f"![{legende.replace('[', '(').replace(']', ')')}](pj:{int(numero)})"


def trouver(texte: str) -> list[tuple[str, int]]:
    """[(légende, numéro de pièce)] dans l'ordre du texte."""
    return [(m.group(1), int(m.group(2))) for m in _REF.finditer(texte)]


def numeros(texte: str) -> set[int]:
    return {n for _a, n in trouver(texte)}


def remplacer(texte: str, fn) -> str:
    """Remplace chaque référence par `fn(légende, numéro)` (chaîne Markdown)."""
    return _REF.sub(lambda m: fn(m.group(1), int(m.group(2))), texte)
