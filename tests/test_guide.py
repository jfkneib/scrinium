# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Thème « Guide » (présentation de Scrinium) : contenu, création sans écrasement."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium.core import guide  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def test_contenu():
    fiches = guide.fiches(Path("/home/x/fiches"))
    assert len(fiches) == 7 and len({t for t, _x in fiches}) == 7
    tout = "\n".join(t for _x, t in fiches)
    assert "/home/x/fiches" in tout and "DBus" in tout and "Calculatrice" in tout
    assert "%s" not in tout


def test_menu_aide_cree_rouvre_sans_ecraser(fen):  # noqa: F811
    fen.guide()
    th = fen.store.theme("Guide")
    assert len(th.fiches) == 7 and fen.theme == "Guide" and fen.fiche.titre.startswith("Guide 1")
    f = next(x for x in th.fiches if x.titre.startswith("Guide 3"))
    fen.store.enregistrer(th, f, f.titre, "ma version")
    fen.store.supprimer_fiche(th, next(x for x in th.fiches if x.titre.startswith("Guide 5")))
    fen.guide()
    th = fen.store.theme("Guide")
    assert len(th.fiches) == 7
    assert next(x for x in th.fiches if x.titre.startswith("Guide 3")).texte == "ma version"
