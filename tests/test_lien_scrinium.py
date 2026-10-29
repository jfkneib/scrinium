# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Liens `scrinium://…` ouverts par le système : canal de l'instance unique et affichage dans la fenêtre."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.ui import instance  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811

LIEN = "scrinium://rejoindre?serveur=https%3A%2F%2Fs.exemple.org&jeton=abc"


def _attendre(cond, delai=3.0):
    fin = time.time() + delai
    while time.time() < fin and not cond():
        QApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_le_lien_traverse_le_canal_de_l_instance(fen, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-lien-{os.getpid()}")
    recus = []
    serveur = instance.Serveur(fen)
    serveur.lien.connect(recus.append)
    assert instance.envoyer_lien(LIEN)
    assert _attendre(lambda: recus) and recus == [LIEN]


def test_sans_instance_le_lien_n_est_pas_envoye(monkeypatch):
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-vide-{os.getpid()}")
    assert not instance.envoyer_lien(LIEN)


def test_ouvrir_lien_confie_au_plugin_partage(fen):  # noqa: F811
    appels = []

    class Faux:
        def rejoindre_lien(self, lien):
            appels.append(lien)
    fen.plugins.actifs["partage"] = (Faux(), None)
    fen.ouvrir_lien(LIEN)
    assert appels == [LIEN]


def test_ouvrir_lien_sans_partage_explique(fen):  # noqa: F811
    fen.plugins.actifs.pop("partage", None)
    fen.ouvrir_lien(LIEN)
    assert "Partage" in fen.statut.text()
