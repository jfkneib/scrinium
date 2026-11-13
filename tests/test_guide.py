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
    assert len(fiches) == 8 and len({t for t, _x in fiches}) == 8 and fiches[0][0] == guide.titre_sommaire()
    tout = "\n".join(t for _x, t in fiches)
    assert "/home/x/fiches" in tout and "DBus" in tout and "Calculatrice" in tout
    assert "%s" not in tout


def test_menu_aide_cree_rouvre_sans_ecraser(fen):  # noqa: F811
    fen.guide()
    th = fen.store.theme("Guide")
    assert len(th.fiches) == 8 and fen.theme == "Guide" and fen.fiche.titre == guide.titre_sommaire()      # le guide s'ouvre sur le sommaire
    f = next(x for x in th.fiches if x.titre.startswith("Guide 3"))
    fen.store.enregistrer(th, f, f.titre, "ma version")
    fen.store.supprimer_fiche(th, next(x for x in th.fiches if x.titre.startswith("Guide 5")))
    fen.guide()
    th = fen.store.theme("Guide")
    assert len(th.fiches) == 8
    assert next(x for x in th.fiches if x.titre.startswith("Guide 3")).texte == "ma version"


def test_sommaire_et_liens_du_guide():
    """Le sommaire mène à chaque page, chaque page revient au sommaire et enchaîne la suivante ; aucun lien cassé (même pour les extensions)."""
    from scrinium.core import liens_fiches
    fiches = guide.fiches(Path("/home/x/fiches")) + guide.fiches_extensions([("Veille", "texte de la veille")])
    titres = {t.casefold() for t, _x in fiches}
    sommaire = guide.titre_sommaire()
    cibles_du_sommaire = {c.casefold() for c, _a in liens_fiches.trouver(fiches[0][1])}
    assert cibles_du_sommaire == {t.casefold() for t, _x in fiches[1:8]}                      # les sept pages, pas les extensions
    for titre, texte in fiches[1:]:
        cibles = {c.casefold() for c, _a in liens_fiches.trouver(texte)}
        assert sommaire.casefold() in cibles, titre                                           # retour au sommaire partout
    for titre, texte in fiches:
        for cible, _a in liens_fiches.trouver(texte):
            assert cible.casefold() in titres, f"{titre} : lien cassé [[{cible}]]"
    assert "[[Titre d'une fiche]]" in fiches[0][1] and "`[[Titre d'une fiche]]`" in fiches[0][1]    # l'exemple est dans un code : jamais un lien
