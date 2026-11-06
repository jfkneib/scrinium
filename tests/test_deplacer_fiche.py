# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Ranger une fiche dans un autre thème : magasin (fichier, images, favoris, ordre) et fenêtre (clic droit, dépôt sur un thème)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402


def _magasin(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    a, b = s.nouveau_theme("A"), s.nouveau_theme("B")
    f = s.nouvelle_fiche(a)
    s.enregistrer(a, f, "Ma fiche", "texte")
    return s, a, b, f


def test_deplacer_fiche_avec_ses_images_et_ses_favoris(tmp_path):
    s, a, b, f = _magasin(tmp_path)
    pj = f.path.with_name(f.path.stem + ".pj")
    pj.mkdir()
    (pj / "1.png").write_bytes(b"x")
    s.epingler_fiche(a, f)
    ancien = f.path
    assert s.deplacer_fiche(a, f, b)
    assert f.path == b.path / "Ma fiche.md" and f.path.exists() and not ancien.exists()
    assert (b.path / "Ma fiche.pj" / "1.png").exists() and not pj.exists()
    assert f in b.fiches and f not in a.fiches
    s2 = Store(Paths(tmp_path / "am"))
    s2.charger()
    assert [x.titre for x in s2.theme("B").fiches] == ["Ma fiche"] and not s2.theme("A").fiches        # relu du disque
    assert s.fiche_epinglee(b, f) and not s.fiche_epinglee(a, f)                                        # l'épingle a suivi
    assert not s.deplacer_fiche(b, f, b)                                                                # même thème : rien


def test_nom_deja_pris_dans_le_theme_vise(tmp_path):
    s, a, b, f = _magasin(tmp_path)
    g = s.nouvelle_fiche(b)
    s.enregistrer(b, g, "Ma fiche", "autre")
    assert s.deplacer_fiche(a, f, b)
    assert f.path.name == "Ma fiche (2).md" and g.path.name == "Ma fiche.md" and g.texte == "autre"


def test_fiche_verrouillee_fermee_se_deplace_sans_etre_ouverte(tmp_path):
    s, a, b, f = _magasin(tmp_path)
    s.verrouiller(a, f, "mdp")
    s.refermer(f)
    assert s.deplacer_fiche(a, f, b) and f.path.suffix == ".lock" and f.fermee and f.path.parent == b.path


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_fenetre_clic_droit_et_depot_sur_un_theme(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s, a, b, f = _magasin(tmp_path)
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s, theme="A")
    try:
        w.liste.setCurrentRow(0)
        a, b = w.store.theme("A"), w.store.theme("B")             # la fenêtre relit le magasin : ce sont d'autres objets
        f = a.fiches[0]
        assert w.fiche is f
        w.deplacer_fiches_vers(b.path.name)                     # ce que fait le dépôt sur le thème B ou l'entrée du clic droit
        assert f in b.fiches and f.path.parent == b.path and w.fiche is None      # affichée dans A : elle en disparaît
        noms = [w.liste_themes.item(i).text() for i in range(w.liste_themes.count())]
        assert any(n.startswith("A  (0)") for n in noms) and any(n.startswith("B  (1)") for n in noms)
        assert w.liste.count() == 0                              # on est dans A, la fiche est partie
        w.deplacer_fiches_vers("inconnu")                        # thème inexistant : sans effet
        assert f in b.fiches
    finally:
        w.quitter_vraiment = True
        w.close()


def test_depot_d_une_fiche_sur_un_theme_declenche_le_signal(app, tmp_path, monkeypatch):
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s, a, b, f = _magasin(tmp_path)
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s, theme="A")
    try:
        lt = w.liste_themes
        ligne_b = next(i for i in range(lt.count()) if lt.item(i).text().startswith("B"))
        pos = QPointF(lt.visualItemRect(lt.item(ligne_b)).center())
        recu = []
        lt.fiches_deposees.connect(recu.append)
        ev = QDropEvent(pos, Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        monkeypatch.setattr(QDropEvent, "source", lambda self: w.liste)         # le glisser vient de la liste des fiches
        lt.dropEvent(ev)
        app.processEvents()
        assert recu == [w.store.theme("B").path.name] and ev.dropAction() == Qt.DropAction.CopyAction     # Copy : Qt ne retire rien de la liste source
        recu.clear()
        ev2 = QDropEvent(QPointF(2, 500), Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, QMimeData(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        lt.dropEvent(ev2)                                                        # dépôt dans le vide : rien
        app.processEvents()
        assert recu == []
    finally:
        w.quitter_vraiment = True
        w.close()


def test_montrer_ne_sort_pas_la_fenetre_du_plein_ecran(app, tmp_path, monkeypatch):
    from PyQt6.QtCore import Qt
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s, a, b, f = _magasin(tmp_path)
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s)
    try:
        w.show()
        w.setWindowState(Qt.WindowState.WindowMaximized)
        app.processEvents()
        assert w.isMaximized()
        w.montrer(theme="A")                                   # ce que font les extensions (bouton Applications, afficher_fiche…)
        app.processEvents()
        assert w.isMaximized()
        w.hide()
        w.montrer()                                            # fenêtre cachée (zone de notification) : revient maximisée
        app.processEvents()
        assert w.isVisible() and w.isMaximized()
    finally:
        w.quitter_vraiment = True
        w.close()
