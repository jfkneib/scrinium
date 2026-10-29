# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Les tests ne doivent JAMAIS toucher la vraie session graphique : ni fenêtres, ni icônes de la zone de notification, ni presse-papiers.

`os.environ.setdefault` ne suffit pas : si la session définit déjà QT_QPA_PLATFORM (xcb, wayland), la valeur est conservée et les
tests ouvrent de vraies fenêtres. Ici on l'impose, avant l'import de Qt, et on arrête tout si une autre plateforme est en service."""
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
for variable in ("DISPLAY", "WAYLAND_DISPLAY"):          # même une erreur de configuration ne doit pas pouvoir atteindre l'écran
    os.environ.pop(variable, None)

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _application_qt_unique():
    """UNE SEULE QApplication pour toute la session de tests, gardée en vie jusqu'au bout.

    Avant, chaque fichier de tests en créait une dans une fixture « module » ; à la fin du fichier, Python la détruisait,
    puis le fichier suivant en recréait une. Or `scrinium.ui.icons` garde un cache d'icônes (QIcon) créées sous l'ancienne
    application : leur réutilisation sous la nouvelle plantait de façon aléatoire (« Segmentation fault » dans Fenetre._ui,
    vu sur GitHub en Python 3.12 et 3.13 et une fois en local). Les fichiers de tests continuent d'écrire
    `QApplication.instance() or QApplication([])` : ils trouvent désormais toujours celle-ci."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    app = QApplication.instance() or QApplication([])
    yield app


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


@pytest.fixture(autouse=True)
def _sans_extensions_officielles(monkeypatch):
    """Par défaut, aucun test ne voit les extensions du dépôt (isolation) : un test qui en veut passe `officiels=[...]` au Gestionnaire.
    La vraie fonction reste accessible sous `plugins.dossiers_officiels_reels`."""
    from scrinium.core import plugins
    plugins.dossiers_officiels_reels = getattr(plugins, "dossiers_officiels_reels", plugins.dossiers_officiels)
    monkeypatch.setattr(plugins, "dossiers_officiels", lambda: [])


RACINE = Path(__file__).resolve().parent.parent

def _php_sqlite():
    php = shutil.which("php")
    if not php:
        return None
    ok = subprocess.run([php, "-r", "exit(extension_loaded('pdo_sqlite') && extension_loaded('mbstring') ? 0 : 1);"]).returncode == 0
    return php if ok else None


MDP = {"jfk": "motdepasse-jfk", "dede": "motdepasse-dede", "alphonse": "motdepasse-alphonse"}


@pytest.fixture(scope="session")
def php(tmp_path_factory):
    if os.environ.get("SCRINIUM_TEST_PHP_URL"):         # serveur déjà lancé ailleurs (comptes jfk, dede, alphonse existants)
        yield os.environ["SCRINIUM_TEST_PHP_URL"]
        return
    php = _php_sqlite()
    if not php:
        pytest.skip("PHP avec pdo_sqlite absent")
    d = tmp_path_factory.mktemp("serveur")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    url = f"http://127.0.0.1:{port}"
    (d / "config.php").write_text(f"""<?php return ['base_url' => '{url}', 'donnees' => '{d}/donnees',
        'db' => ['type' => 'sqlite', 'chemin' => '{d}/s.sqlite'], 'cout_hash' => 4];""")
    env = dict(os.environ, SCRINIUM_CONFIG=str(d / "config.php"))
    cli = str(RACINE / "serveur" / "bin" / "scrinium-serveur")
    subprocess.run([php, cli, "initialiser"], env=env, check=True, capture_output=True)
    for nom, mdp in MDP.items():
        subprocess.run([php, cli, "creer-compte", nom], env=env, input=mdp + "\n", text=True, check=True, capture_output=True)
    pub = RACINE / "serveur" / "public"
    proc = subprocess.Popen([php, "-S", f"127.0.0.1:{port}", "-t", str(pub), str(pub / "index.php")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(5)


