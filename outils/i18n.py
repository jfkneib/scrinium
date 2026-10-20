#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Traductions de Scrinium : extraction des chaînes, vérification, fusion dans po/en.po et po/scrinium.pot.

  outils/i18n.py verifier              code de retour 1 s'il manque une traduction ou si un marqueur de format diffère
  outils/i18n.py manquantes FICHIER    écrit en JSON {msgid: ""} les chaînes à traduire
  outils/i18n.py fusionner FICHIER     ajoute les traductions d'un JSON {msgid: msgstr} puis réécrit po/en.po et po/scrinium.pot

Les textes sources sont en français. Sont extraites les chaînes littérales passées à `_()` (traduction immédiate) ou à `N_()`
(marque une chaîne traduite plus tard : `N_` ne fait rien à l'exécution). Un `_(variable)` n'est pas extractible : on marque
la chaîne d'origine avec `N_()`.
"""
import ast
import json
import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
from scrinium import i18n_po  # noqa: E402

MARQUEURS = re.compile(r"%(?:\([A-Za-z_]+\))?[-#0 +]*\d*(?:\.\d+)?[sdifr%]")


def sources() -> list:
    fichiers = list(RACINE.glob("src/scrinium/**/*.py")) + list(RACINE.glob("plugins/*/*.py"))
    return sorted(f for f in fichiers if f.name not in ("i18n.py", "i18n_po.py"))


def extraire() -> dict:
    """{msgid: [références "fichier:ligne"]} dans l'ordre du code."""
    trouves: dict = {}
    for f in sources():
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "N_") and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    trouves.setdefault(a.value, []).append(f"{f.relative_to(RACINE)}:{n.lineno}")
    return trouves


def catalogue() -> dict:
    return i18n_po.lire_po((RACINE / "po" / "en.po").read_text(encoding="utf-8"))


def marqueurs(texte: str) -> list:
    return sorted(m for m in MARQUEURS.findall(texte) if m != "%%")


def problemes() -> list:
    cat, msgs = catalogue(), extraire()
    res = [f"manquante : {m[:70]!r}  ({refs[0]})" for m, refs in msgs.items() if not cat.get(m)]
    res += [f"marqueurs différents : {m[:60]!r} {marqueurs(m)} -> {marqueurs(cat[m])}" for m in msgs if cat.get(m) and marqueurs(m) != marqueurs(cat[m])]
    return res


def _po(texte: str) -> str:
    if "\n" in texte[:-1]:
        morceaux = texte.splitlines(keepends=True)
        return '""\n' + "\n".join(json.dumps(m, ensure_ascii=False) for m in morceaux)
    return json.dumps(texte, ensure_ascii=False)


def ecrire(traductions: dict) -> None:
    msgs = extraire()
    entetes = ('# English translation of Scrinium.\n# Copyright (C) 2026 Jean-François Kneib\n# Same license as the program (GPL-3.0-or-later).\n#\n'
               'msgid ""\nmsgstr ""\n"Project-Id-Version: scrinium 0.2.0\\n"\n"Report-Msgid-Bugs-To: \\n"\n"PO-Revision-Date: {date}\\n"\n'
               '"Last-Translator: Jean-François Kneib\\n"\n"Language-Team: English\\n"\n"Language: en\\n"\n"MIME-Version: 1.0\\n"\n'
               '"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n')
    date = time.strftime("%Y-%m-%d %H:%M%z")
    pot, en = [entetes.format(date="YEAR-MO-DA HO:MI+ZONE").replace("English translation", "Scrinium translation template").replace("Language: en", "Language: ")], [entetes.format(date=date)]
    for m, refs in msgs.items():
        ref = f"#: {refs[0]}\n" + ("".join(f"#: {r}\n" for r in refs[1:3]) if len(refs) > 1 else "")
        pot.append(f"\n{ref}msgid {_po(m)}\nmsgstr \"\"\n")
        en.append(f"\n{ref}msgid {_po(m)}\nmsgstr {_po(traductions[m])}\n")
    (RACINE / "po" / "scrinium.pot").write_text("".join(pot), encoding="utf-8")
    (RACINE / "po" / "en.po").write_text("".join(en), encoding="utf-8")


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else "verifier"
    if cmd == "verifier":
        p = problemes()
        print("\n".join(p) if p else f"{len(extraire())} chaînes, toutes traduites")
        return 1 if p else 0
    if cmd == "manquantes":
        cat = catalogue()
        manq = {m: "" for m in extraire() if not cat.get(m)}
        Path(argv[2]).write_text(json.dumps(manq, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(manq)} chaînes à traduire écrites dans {argv[2]}")
        return 0
    if cmd == "fusionner":
        nouvelles = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        cat = {**catalogue(), **{m: t for m, t in nouvelles.items() if t}}
        absentes = [m for m in extraire() if not cat.get(m)]
        if absentes:
            print(f"refusé : {len(absentes)} chaînes sans traduction, par exemple {absentes[0][:60]!r}")
            return 1
        ecrire(cat)
        print(f"po/en.po et po/scrinium.pot réécrits ({len(extraire())} chaînes)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
