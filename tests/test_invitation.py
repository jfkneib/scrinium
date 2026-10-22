# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fiche « Inviter à installer Scrinium » : texte (liens, aucune variable oubliée, FR/EN), création sans doublon ni écrasement, envoi."""
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium import __version__, i18n  # noqa: E402
from scrinium.core import invitation  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


@pytest.fixture
def langue_remise():
    avant = i18n.langue()
    yield
    i18n.init(avant)


def test_texte_liens_et_marche_a_suivre():
    t = invitation.texte("9.8.7")
    assert "releases/download/v9.8.7/scrinium_9.8.7_all.deb" in t and "SHA256SUMS" in t and "sha256sum -c SHA256SUMS" in t
    assert "sudo apt install ./scrinium_9.8.7_all.deb" in t and invitation.DEPOT in t and "./install.sh" in t
    assert not re.search(r"%\(|%s|\{\w+\}", t)                                 # aucune variable de modèle oubliée
    assert "mot de passe" in t and "Extensions" in t and t.endswith("\n")
    assert f"v{__version__}" in invitation.texte()                            # par défaut : la version qui crée la fiche
    assert "Windows" in t and "macOS" in t and "pas encore" in t.lower()      # honnête sur ce qui n'existe pas
    assert "releases/download/v9.8.7/Scrinium-9.8.7-setup.exe" in t and "Informations complémentaires" in t      # Windows : installateur
    assert "pip install https://github.com/jfkneib/scrinium/archive/refs/tags/v9.8.7.zip" in t                  # macOS : en attendant
    for nom in ("Agenda", "Courriel", "Applications", "Lecture à voix haute", "OCR", "Dictée", "Traduction", "Capture et console"):
        assert nom in t                                                       # les extensions intéressantes sont présentées


def test_texte_en_anglais(langue_remise):
    i18n.init("en")
    t = invitation.texte("9.8.7")
    assert "Hello," in t and "Debian or Ubuntu" in t and "Bonjour" not in t and "Extensions" in t
    assert not re.search(r"%\(|%s", t) and "scrinium_9.8.7_all.deb" in t
    assert invitation.titre_fiche() == "Invitation to try Scrinium" and "Windows" in t and "macOS" in t and "Tesseract" in t


def test_inviter_cree_une_fois_sans_ecraser(fen):  # noqa: F811
    fen.inviter()
    th = fen.store.theme(invitation.nom_theme())
    assert th is not None and (th.path / ".icone").read_text().strip() == "mail-send"
    f = next(x for x in th.fiches if x.titre == invitation.titre_fiche())
    assert "sha256sum -c" in f.texte and fen.fiche is f and fen.theme == th.nom
    fen.texte.setPlainText(fen.texte.toPlainText() + "\nPS : à bientôt !")      # l'utilisateur personnalise sa fiche dans l'éditeur
    fen.inviter()
    assert len([x for x in th.fiches if x.titre == invitation.titre_fiche()]) == 1
    g = next(x for x in th.fiches if x.titre == invitation.titre_fiche())
    assert "à bientôt" in g.texte                                              # rouverte, jamais écrasée
    assert len(fen.store.themes) == len({t.nom for t in fen.store.themes})


def test_inviter_ouvre_l_envoi_si_courriel_actif(fen):  # noqa: F811
    appels = []

    class FauxCourriel:
        def envoyer(self):
            appels.append(fen.fiche.titre)
    fen.plugins.actifs["courriel"] = (FauxCourriel(), None)
    fen.inviter()
    for _i in range(20):
        QApplication.processEvents()
    assert appels == [invitation.titre_fiche()]                                # la fiche d'invitation est la fiche courante


def test_inviter_sans_courriel_explique(fen):  # noqa: F811
    fen.plugins.actifs.pop("courriel", None)
    fen.inviter()
    assert "Courriel" in fen.statut.text()


def test_bienvenue_a_une_fiche_pour_inviter(fen):  # noqa: F811
    bienvenue = fen.store.theme("Bienvenue")
    assert any(f.titre.startswith("6") and "Inviter" in f.titre for f in bienvenue.fiches)
