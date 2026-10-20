# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Capture rapide : fenêtre, enregistrement dans une fiche, fiches verrouillées refusées, canal de l'instance unique."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.i18n import _  # noqa: E402
from scrinium.ui import capture_rapide as cr  # noqa: E402
from scrinium.ui import instance  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _fiche(fen, theme, titre):
    th = fen.store.theme(theme)
    return th, next((f for f in th.fiches if f.titre == titre), None)


def test_enregistre_dans_une_nouvelle_fiche_puis_ajoute(fen):  # noqa: F811
    fen.capture_rapide()
    d = fen._capture
    d.theme.setCurrentText("Perso")
    d.fiche.setEditText("Idées")
    d.texte.setPlainText("première idée")
    assert d.enregistrer()
    _t, f = _fiche(fen, "Perso", "Idées")
    assert f is not None and "### " in f.texte and "première idée" in f.texte
    fen.capture_rapide()
    d2 = fen._capture
    assert d2.theme.currentText() == "Perso" and d2.fiche.currentText() == "Idées"      # dernier choix retenu
    d2.texte.setPlainText("seconde idée")
    d2.horodate.setChecked(False)
    assert d2.enregistrer()
    _t, f = _fiche(fen, "Perso", "Idées")
    assert f.texte.index("première") < f.texte.index("seconde") and f.texte.rstrip().endswith("seconde idée")
    assert fen.store.reglages()["capture_rapide"]["horodate"] is False


def test_refuse_texte_vide_et_fiche_verrouillee(fen):  # noqa: F811
    fen.capture_rapide()
    d = fen._capture
    assert not d.enregistrer() and d.erreur.text()
    th = next(t for t in fen.store.themes if any(f.verrou for f in t.fiches))
    verrouillee = next(f for f in th.fiches if f.verrou)
    d.theme.setCurrentText(th.nom)
    assert verrouillee.titre not in [d.fiche.itemText(i) for i in range(d.fiche.count())]     # jamais proposée
    d.fiche.setEditText(verrouillee.titre)                                                       # mais tapée à la main
    d.texte.setPlainText("intrus")
    assert not d.enregistrer() and "verrouillée" in d.erreur.text()


def test_canal_de_l_instance_unique_ouvre_la_capture(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-cap-{os.getpid()}")
    srv = instance.Serveur()
    recus = []
    srv.capture.connect(lambda: recus.append(1))
    assert instance.demander_capture()
    for _i in range(50):
        QApplication.processEvents()
        if recus:
            break
    assert recus == [1]


def test_sans_instance_demander_capture_est_faux(monkeypatch):
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-aucune-{os.getpid()}")
    assert instance.demander_capture() is False


def test_titre_par_defaut():
    assert _(cr.TITRE_DEFAUT) == "Notes rapides"


def test_theme_propose_meme_inexistant_et_cree_a_l_enregistrement(fen):  # noqa: F811
    fen.capture_rapide()
    d = fen._capture
    assert d.theme.currentText() == _(cr.THEME_DEFAUT) and fen.store.theme(_(cr.THEME_DEFAUT)) is None     # proposé, pas encore créé
    d.texte.setPlainText("une note")
    assert d.enregistrer()
    th = fen.store.theme(_(cr.THEME_DEFAUT))
    assert th is not None and any("une note" in (f.texte or "") for f in th.fiches)
    fen.capture_rapide()
    assert fen._capture.theme.currentText() == _(cr.THEME_DEFAUT)                                          # retenu, et listé une seule fois
    assert [fen._capture.theme.itemText(i) for i in range(fen._capture.theme.count())].count(_(cr.THEME_DEFAUT)) == 1


def test_theme_tape_a_la_main_est_cree_sans_doublon_de_casse(fen):  # noqa: F811
    nb = len(fen.store.themes)
    fen.capture_rapide()
    d = fen._capture
    d.theme.setEditText("perso")                     # existe sous le nom « Perso » : pas de nouveau thème
    d.fiche.setEditText("x")
    d.texte.setPlainText("a")
    assert d.enregistrer() and len(fen.store.themes) == nb
    fen.capture_rapide()
    d = fen._capture
    d.theme.setEditText("Projet Neuf")
    d.fiche.setEditText("x")
    d.texte.setPlainText("b")
    assert d.enregistrer() and fen.store.theme("Projet Neuf") is not None and len(fen.store.themes) == nb + 1


def test_pas_de_theme_cree_si_rien_a_enregistrer(fen):  # noqa: F811
    nb = len(fen.store.themes)
    fen.capture_rapide()
    d = fen._capture
    d.theme.setEditText("Fantôme")
    assert not d.enregistrer()                       # texte vide
    d.texte.setPlainText("t")
    d.fiche.setEditText("  ")
    assert not d.enregistrer() and len(fen.store.themes) == nb and fen.store.theme("Fantôme") is None
