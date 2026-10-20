# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Les tests ne doivent JAMAIS toucher la vraie session graphique : ni fenêtres, ni icônes de la zone de notification, ni presse-papiers.

`os.environ.setdefault` ne suffit pas : si la session définit déjà QT_QPA_PLATFORM (xcb, wayland), la valeur est conservée et les
tests ouvrent de vraies fenêtres. Ici on l'impose, avant l'import de Qt, et on arrête tout si une autre plateforme est en service."""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
for variable in ("DISPLAY", "WAYLAND_DISPLAY"):          # même une erreur de configuration ne doit pas pouvoir atteindre l'écran
    os.environ.pop(variable, None)

import pytest  # noqa: E402


def pytest_runtest_setup(item):
    try:
        from PyQt6.QtGui import QGuiApplication
    except ImportError:
        return
    app = QGuiApplication.instance()
    if app is not None and app.platformName() != "offscreen":
        pytest.exit("Qt n'est pas en mode « offscreen » (%s) : les tests ouvriraient de vraies fenêtres." % app.platformName(), returncode=3)


@pytest.fixture(autouse=True)
def _aucune_boite_modale_inattendue(monkeypatch):
    """Une boîte de dialogue modale non prévue par le test attendrait un clic pour toujours : on la fait échouer à la place.
    Un test qui en attend une la remplace avec `monkeypatch` (il passe après cette protection)."""
    try:
        from PyQt6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox
    except ImportError:
        return

    def interdit(nom):
        def f(*args, **kwargs):
            raise AssertionError(f"boîte de dialogue modale inattendue : {nom} (elle bloquerait le test) ; la remplacer avec monkeypatch")
        return f
    for classe, noms in ((QMessageBox, ("information", "warning", "question", "critical", "about")),
                         (QInputDialog, ("getText", "getItem", "getInt", "getDouble", "getMultiLineText")),
                         (QFileDialog, ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"))):
        for nom in noms:
            monkeypatch.setattr(classe, nom, staticmethod(interdit(f"{classe.__name__}.{nom}")))
    for classe in (QDialog, QMessageBox, QMenu):
        monkeypatch.setattr(classe, "exec", interdit(f"{classe.__name__}.exec"))
