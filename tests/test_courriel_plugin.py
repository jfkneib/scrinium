# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Courriel dans la vraie fenêtre : un envoi raté (mauvais mot de passe) ne fait JAMAIS perdre les modifications
de l'objet et du message, la fiche reste intacte, et le mot de passe faux est redemandé."""
import os
import shutil
import smtplib
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "courriel"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setitem(sys.modules, "keyring", None)          # pas de trousseau : le mot de passe n'existe que si on le saisit
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "courriel")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("courriel"), w.plugins.infos["courriel"].erreur
    p = w.plugins.actifs["courriel"][0]
    p.ctx.reglages.set("smtp", {"hote": "smtp.exemple.fr", "securite": "starttls", "port": 587, "utilisateur": "moi",
                                "expediteur": "moi@exemple.fr", "nom": "Moi"})
    w.nouvelle_fiche()
    w.titre.setText("Ma fiche")
    w.texte.setPlainText("Texte d'origine de la fiche.")
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def attendre(app, cond, delai=5.0):
    fin = time.time() + delai
    while time.time() < fin:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_mauvais_mot_de_passe_conserve_les_modifications_et_redemande(fen, app, monkeypatch):
    mod = sys.modules["scrinium_plugin_courriel"]
    p = fen.plugins.actifs["courriel"][0]
    ouvertures, corps_vus, envois = [], [], []

    def faux_exec(self):
        ouvertures.append(1)
        if len(ouvertures) == 1:                                  # 1re ouverture : l'utilisateur personnalise puis envoie
            self.corps.setPlainText("Cher Dédé,\n\n" + self.corps.toPlainText())
            self.sujet.setText("Pour Dédé")
        corps_vus.append((self.sujet.text(), self.corps.toPlainText(), not self.erreur.isHidden()))
        self.destinataires = ["dede@exemple.fr"]
        return len(ouvertures) <= 2                               # 3e ouverture (si elle a lieu) : « Annuler »
    monkeypatch.setattr(mod.DialogueEnvoi, "exec", faux_exec)
    mots = iter([("faux", True), ("bon", True)])
    demandes = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: demandes.append(1) or next(mots)))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: pytest.fail("pas de boîte modale d'erreur")))

    def faux_envoyer(smtp, mdp, msg):
        envois.append((mdp, msg["Subject"], msg.get_content()))
        if mdp == "faux":
            raise smtplib.SMTPAuthenticationError(535, b"identifiants refuses")
    monkeypatch.setattr(mod.logique, "envoyer", faux_envoyer)

    p.envoyer()
    assert attendre(app, lambda: len(envois) == 2)                # 1er essai refusé, 2e accepté
    assert attendre(app, lambda: p._dialogue is None)
    assert [e[0] for e in envois] == ["faux", "bon"] and len(demandes) == 2        # le faux mot de passe a été redemandé
    # la fenêtre rouverte contenait toujours l'objet et le message modifiés, et montrait l'erreur
    assert corps_vus[1][0] == "Pour Dédé" and corps_vus[1][1].startswith("Cher Dédé,") and corps_vus[1][2] is True
    assert envois[1][1] == "Pour Dédé" and envois[1][2].startswith("Cher Dédé,")   # c'est la version personnalisée qui est partie
    assert fen.fiche.texte == "Texte d'origine de la fiche." and "Dédé" not in fen.texte.toPlainText()   # la fiche n'a jamais bougé


def test_annuler_le_mot_de_passe_ne_perd_rien(fen, app, monkeypatch):
    mod = sys.modules["scrinium_plugin_courriel"]
    p = fen.plugins.actifs["courriel"][0]
    ouvertures = []

    def faux_exec(self):
        ouvertures.append(self.corps.toPlainText())
        if len(ouvertures) == 1:
            self.corps.setPlainText("Mon petit mot.")
        self.destinataires = ["dede@exemple.fr"]
        return len(ouvertures) == 1
    monkeypatch.setattr(mod.DialogueEnvoi, "exec", faux_exec)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))          # « Annuler » au mot de passe
    monkeypatch.setattr(mod.logique, "envoyer", lambda *a: pytest.fail("rien ne doit partir"))
    p.envoyer()
    assert attendre(app, lambda: len(ouvertures) == 2)
    assert ouvertures[1] == "Mon petit mot."                                   # la fenêtre revient avec le message modifié
    assert attendre(app, lambda: p._dialogue is None)


def test_erreur_reseau_rouvre_avec_le_message(fen, app, monkeypatch):
    mod = sys.modules["scrinium_plugin_courriel"]
    p = fen.plugins.actifs["courriel"][0]
    p.secret.session = "bon"
    etats = []

    def faux_exec(self):
        etats.append((self.corps.toPlainText(), self.erreur.text()))
        if len(etats) == 1:
            self.corps.setPlainText("Version personnalisée")
        self.destinataires = ["dede@exemple.fr"]
        return len(etats) == 1
    monkeypatch.setattr(mod.DialogueEnvoi, "exec", faux_exec)

    def panne(*a):
        raise OSError("serveur injoignable")
    monkeypatch.setattr(mod.logique, "envoyer", panne)
    p.envoyer()
    assert attendre(app, lambda: len(etats) == 2)
    assert etats[1][0] == "Version personnalisée" and "serveur injoignable" in etats[1][1] and "conservé" in etats[1][1]
    assert p.secret.session == "bon"                       # une panne réseau ne fait pas oublier un mot de passe correct
