# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Petits gestes de la fenêtre : refermer une fiche ouverte, ordre des boutons, Ctrl+Maj+N, touche Suppr, choix d'icône."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from scrinium.ui.choix_icone import DialogueIcone, icones_proposees  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _verrouillee(fen):  # noqa: F811
    return next(f for t in fen.store.themes for f in t.fiches if f.verrou)


def test_refermer_une_fiche_ouverte(fen):  # noqa: F811
    demo = _verrouillee(fen)
    th = next(t for t in fen.store.themes if demo in t.fiches)
    fen.store.deverrouiller(demo, "scrinium")
    fen._afficher(th, demo)
    assert not demo.fermee and not fen.b_refermer.isHidden()
    fen.refermer_fiche()
    assert demo.fermee and demo.cle is None and fen.b_refermer.isHidden()
    fen.store.deverrouiller(demo, "scrinium")          # le mot de passe sert de nouveau
    assert not demo.fermee


def test_refermer_sans_effet_sur_une_fiche_non_verrouillee(fen):  # noqa: F811
    libre = next(f for t in fen.store.themes for f in t.fiches if not f.verrou)
    th = next(t for t in fen.store.themes if libre in t.fiches)
    fen._afficher(th, libre)
    assert fen.b_refermer.isHidden()
    fen.refermer_fiche()
    assert not libre.verrou and libre.texte is not None


def test_ordre_des_boutons_et_raccourcis(fen):  # noqa: F811
    actions = fen.barre.actions()
    assert actions.index(fen.a_theme) < actions.index(fen.a_fiche)
    assert fen.a_theme.shortcut().toString() == "Ctrl+Shift+N" and fen.a_fiche.shortcut().toString() == "Ctrl+N"


def _suppr(liste):
    return next(a for a in liste.actions() if a.shortcut().toString() == "Del")


def test_suppr_est_reservee_aux_listes(fen, monkeypatch):  # noqa: F811
    for liste in (fen.liste_themes, fen.liste):
        a = _suppr(liste)
        assert a.shortcutContext() == Qt.ShortcutContext.WidgetShortcut
    assert not any(a.shortcut().toString() == "Del" for a in fen.actions() + fen.texte.actions() + fen.titre.actions())
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    fen.store.nouveau_theme("A supprimer")
    fen.maj_themes()
    fen.liste_themes.setCurrentRow(fen._noms().index("A supprimer"))
    assert fen.theme == "A supprimer"
    _suppr(fen.liste_themes).trigger()
    assert fen.store.theme("A supprimer") is None


def test_choix_d_icone(fen):  # noqa: F811
    noms = icones_proposees("view-pim-notes")
    assert "view-pim-notes" in noms and "scrinium" not in noms
    d = DialogueIcone(None, "Doc", "view-pim-notes")
    assert d.ok.isEnabled() and d.nom() == "view-pim-notes" and d.apercu.pixmap() is not None
    d.choix.setCurrentText("icone-qui-n-existe-pas")
    assert not d.ok.isEnabled()
    d.choix.setCurrentText("edit-find")
    assert d.ok.isEnabled() and d.nom() == "edit-find"


# ---------- export PDF ----------
def _png():
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QColor, QImage
    img = QImage(60, 40, QImage.Format.Format_RGB32)
    img.fill(QColor("steelblue"))
    tampon = QByteArray()
    b = QBuffer(tampon)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "PNG")
    return bytes(tampon)


def test_ecrire_pdf(tmp_path):
    from scrinium.ui import export_pdf
    sans, avec = tmp_path / "sans.pdf", tmp_path / "avec.pdf"
    export_pdf.ecrire_pdf(str(sans), "Titre é", "# Partie\n\n* un\n* deux\n\n**gras**")
    export_pdf.ecrire_pdf(str(avec), "Titre é", "texte", [("a.png", _png()), ("cassee.png", b"pas une image")])
    assert sans.read_bytes().startswith(b"%PDF-") and avec.read_bytes().startswith(b"%PDF-")
    assert avec.stat().st_size > 0


def test_exporter_pdf_depuis_la_fenetre(fen, tmp_path, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog
    libre = next(f for t in fen.store.themes for f in t.fiches if not f.verrou)
    th = next(t for t in fen.store.themes if libre in t.fiches)
    fen._afficher(th, libre)
    cible = tmp_path / "sortie"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cible), "")))
    fen.exporter_pdf()
    assert (tmp_path / "sortie.pdf").read_bytes().startswith(b"%PDF-")
    assert "PDF écrit" in fen.statut.text()


def test_exporter_pdf_fiche_verrouillee(fen, tmp_path, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog
    demo = _verrouillee(fen)
    th = next(t for t in fen.store.themes if demo in t.fiches)
    appels = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: appels.append(1) or (str(tmp_path / "x.pdf"), "")))
    fen._afficher(th, demo)                                     # fermée : rien n'est proposé
    fen.exporter_pdf()
    assert appels == []
    fen.store.deverrouiller(demo, "scrinium")
    fen._afficher(th, demo)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    fen.exporter_pdf()                                          # ouverte, mais l'utilisateur refuse l'export en clair
    assert appels == []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    fen.exporter_pdf()
    assert (tmp_path / "x.pdf").exists()


def test_menu_clic_droit_propose_le_pdf(fen):  # noqa: F811
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    vus = []
    original = QMenu.exec
    try:
        QMenu.exec = lambda self, *a: vus.append([x.text() for x in self.actions()])
        fen.texte.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(1, 1)))
        fen.apercu.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(1, 1)))
    finally:
        QMenu.exec = original
    assert len(vus) == 2 and all("Exporter la fiche en PDF…" in v for v in vus)
