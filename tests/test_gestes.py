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


# ---------- sélection multiple ----------
def _fiches_pour_supprimer(fen, theme="Lot", n=4):  # noqa: F811
    th = fen.store.theme(theme) or fen.store.nouveau_theme(theme)
    for i in range(n):
        f = fen.store.nouvelle_fiche(th)
        fen.store.enregistrer(th, f, f"fiche {i}", "x")
    fen.theme = theme
    fen.maj_themes()
    fen.maj_fiches()
    return th


def _reponse(monkeypatch, oui=True):
    vus = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda parent, titre, texte, *a, **k: vus.append((titre, texte)) or
        (QMessageBox.StandardButton.Yes if oui else QMessageBox.StandardButton.No)))
    return vus


def test_supprimer_plusieurs_fiches(fen, monkeypatch):  # noqa: F811
    th = _fiches_pour_supprimer(fen)
    vus = _reponse(monkeypatch)
    for i in (0, 2):
        fen.liste.item(i).setSelected(True)
    assert [f.titre for _t, f in fen._fiches_selectionnees()] == ["fiche 0", "fiche 2"]
    fen.supprimer_fiche()
    assert "ces 2 fiches" in vus[0][1] and "fiche 0" in vus[0][1] and "fiche 2" in vus[0][1]
    assert sorted(f.titre for f in th.fiches) == ["fiche 1", "fiche 3"]
    assert len(list(fen.store.paths.corbeille.iterdir())) >= 2


def test_refus_ne_supprime_rien(fen, monkeypatch):  # noqa: F811
    th = _fiches_pour_supprimer(fen)
    _reponse(monkeypatch, oui=False)
    fen.liste.selectAll()
    fen.supprimer_fiche()
    assert len(th.fiches) == 4


def test_supprimer_une_seule_fiche_garde_le_message_habituel(fen, monkeypatch):  # noqa: F811
    th = _fiches_pour_supprimer(fen)
    vus = _reponse(monkeypatch)
    fen.liste.clearSelection()
    fen.liste.setCurrentRow(1)
    fen.supprimer_fiche()
    assert vus[0][1].startswith("Mettre la fiche « fiche 1 »") and len(th.fiches) == 3


def test_supprimer_plusieurs_themes_sans_toutes_les_fiches(fen, monkeypatch):  # noqa: F811
    for nom in ("T1", "T2", "T3"):
        _fiches_pour_supprimer(fen, nom, 2)
    vus = _reponse(monkeypatch)
    fen.liste_themes.clearSelection()
    for nom in ("T1", "T3"):
        fen.liste_themes.item(fen._noms().index(nom)).setSelected(True)
    fen.liste_themes.item(0).setSelected(True)                      # « Toutes les fiches » n'est jamais supprimée
    assert [t.nom for t in fen._themes_selectionnes()] == ["T1", "T3"]
    fen.supprimer_theme()
    assert "ces 2 thèmes" in vus[0][1] and "4 fiche(s)" in vus[0][1] and "· T1" in vus[0][1]
    assert fen.store.theme("T1") is None and fen.store.theme("T3") is None and fen.store.theme("T2") is not None
    assert fen.theme == fen.TOUS


def test_menus_groupes_seulement_suppression(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    _fiches_pour_supprimer(fen)
    vus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: vus.append([x.text() for x in self.actions()]))
    monkeypatch.setattr(fen.liste, "itemAt", lambda pos: fen.liste.item(0))
    fen.liste.selectAll()
    fen._menu_fiche(QPoint(1, 1))
    assert vus[-1] == ["Supprimer les 4 fiches…"]
    fen.liste.clearSelection()
    fen.liste.setCurrentRow(0)
    fen._menu_fiche(QPoint(1, 1))
    assert vus[-1][0] == "Épingler" and vus[-1][-1] == "Supprimer…"
