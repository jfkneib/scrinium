# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Liens [[fiche]] entre fiches : repérage, résolution, aperçu cliquable, rétroliens."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QUrl  # noqa: E402

from scrinium.core import liens_fiches as lf  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402


def test_trouver_ignore_le_code_et_les_doublons():
    t = "Voir [[Assurance maison]] et [[assurance MAISON]], [[Santé/Tension|ma tension]].\n`[[code]]`\n```\n[[bloc]]\n```\n[[ ]] [[a]b]]"
    assert lf.trouver(t) == [("Assurance maison", "Assurance maison"), ("Santé/Tension", "ma tension")]
    assert lf.trouver(None) == [] and lf.trouver("rien") == []


def test_vers_markdown():
    r = lf.vers_markdown("Voir [[Recette tarte|la tarte]] et `[[x]]` [[Autre]]", existe=lambda c: c == "Recette tarte")
    assert "[la tarte](scrinium-fiche:Recette%20tarte)" in r and "[Autre ✚](scrinium-fiche:Autre)" in r and "`[[x]]`" in r


@pytest.fixture
def fen(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s)
    yield w
    w.quitter_vraiment = True
    w.close()


def _fiche(w, theme, titre, texte):
    t = next((x for x in w.store.themes if x.nom == theme), None) or w.store.nouveau_theme(theme)
    f = w.store.nouvelle_fiche(t)
    w.store.enregistrer(t, f, titre, texte)
    return t, f


def test_resoudre_et_retroliens(fen):
    ta, a = _fiche(fen, "Maison", "Assurance maison", "contrat")
    tb, b = _fiche(fen, "Papiers", "Classeur", "voir [[assurance maison]] et [[Inconnue]] et [[Maison/Assurance maison]]")
    assert lf.resoudre(fen.store, "ASSURANCE maison") == (ta, a) and lf.resoudre(fen.store, "Papiers/Assurance maison") is None
    assert lf.resoudre(fen.store, "Maison/Assurance maison") == (ta, a) and lf.resoudre(fen.store, "Inconnue") is None
    assert lf.liens_de(fen.store, tb, b) == [(ta, a)]
    assert lf.retroliens(fen.store, ta, a) == [(tb, b)] and lf.retroliens(fen.store, tb, b) == []


def test_clic_ouvre_la_fiche_et_cree_si_absente(fen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    ta, a = _fiche(fen, "Maison", "Assurance maison", "contrat")
    tb, b = _fiche(fen, "Papiers", "Classeur", "voir [[Assurance maison]] et [[Nouvelle idée]]")
    fen.theme = "Papiers"
    fen.maj_themes()
    fen.maj_fiches()
    fen.selectionner_fiche(__import__("scrinium.core.plugins", fromlist=["FicheVue"]).FicheVue(tb, b))
    fen.format.b_apercu.setChecked(True)
    assert "scrinium-fiche" in fen.apercu.toHtml()
    fen.apercu._lien(QUrl("scrinium-fiche:Assurance%20maison"))
    assert fen.fiche is a and fen.theme == "Maison"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    fen.apercu._lien(QUrl("scrinium-fiche:Nouvelle%20id%C3%A9e"))
    assert fen.fiche.titre == "Nouvelle idée" and lf.resoudre(fen.store, "Nouvelle idée")
