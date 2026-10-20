# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Capture rapide : fenêtre, enregistrement dans une fiche, fiches verrouillées refusées, canal de l'instance unique."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

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
    assert cr.TITRE_DEFAUT == "Notes rapides"
