# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Tri manuel des thèmes et des fiches : réglage de l'utilisateur, suite des renommages, glisser-déposer, Alt+Haut / Alt+Bas."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QMenu  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    for t in list(s.themes):                                            # sans les fiches d'exemple du premier lancement
        s.supprimer_theme(t)
    for nom in ("Alpha", "Beta", "Gamma"):
        th = s.nouveau_theme(nom)
        for titre in ("a", "b", "c"):
            f = s.nouvelle_fiche(th)
            s.enregistrer(th, f, f"{titre}-{nom}", "x")
    return s


def _noms(store):
    return [t.nom for t in store.themes_tries()]


def _titres(store, theme):
    return [f.titre for f in store.fiches_triees(store.theme(theme))]


def test_sans_reglage_ordre_alphabetique(store):
    assert _noms(store) == ["Alpha", "Beta", "Gamma"] and _titres(store, "Beta") == ["a-Beta", "b-Beta", "c-Beta"]


def test_ordre_manuel_les_nouveaux_a_la_fin(store):
    store.ordonner_themes(["Gamma", "Alpha"])
    assert _noms(store) == ["Gamma", "Alpha", "Beta"]
    store.nouveau_theme("Aardvark")                                     # nouveauté : après les thèmes rangés, par ordre alphabétique
    assert _noms(store) == ["Gamma", "Alpha", "Aardvark", "Beta"]
    th = store.theme("Beta")
    fichiers = {f.titre: f.path.name for f in th.fiches}
    store.ordonner_fiches(th, [fichiers["c-Beta"], fichiers["a-Beta"]])
    assert _titres(store, "Beta") == ["c-Beta", "a-Beta", "b-Beta"]
    assert Store(store.paths).ordre()["themes"] == ["Gamma", "Alpha"]    # persistant
    store.ordonner_themes(None)
    store.ordonner_fiches(th, None)
    assert _noms(store)[0] == "Aardvark" and _titres(store, "Beta") == ["a-Beta", "b-Beta", "c-Beta"]
    assert store.ordre() == {"themes": [], "fiches": {}}


def test_ordre_suit_renommages_et_suppressions(store):
    store.ordonner_themes(["Gamma", "Beta", "Alpha"])
    th = store.theme("Gamma")
    fichiers = {f.titre: f.path.name for f in th.fiches}
    store.ordonner_fiches(th, [fichiers["c-Gamma"], fichiers["b-Gamma"], fichiers["a-Gamma"]])
    f = next(x for x in th.fiches if x.titre == "b-Gamma")
    store.enregistrer(th, f, "zz renommée", "x")                         # le fichier change de nom avec le titre
    assert _titres(store, "Gamma") == ["c-Gamma", "zz renommée", "a-Gamma"]
    store.renommer_theme(th, "Delta")
    assert _noms(store) == ["Delta", "Beta", "Alpha"] and _titres(store, "Delta") == ["c-Gamma", "zz renommée", "a-Gamma"]
    store.verrouiller(th, f, "mdp1234", sans_secours=True)
    store.retirer_verrou(th, f)
    assert _titres(store, "Delta")[1] == "zz renommée"
    store.supprimer_fiche(th, f)
    assert store.ordre()["fiches"]["Delta"] == [next(x.path.name for x in th.fiches if x.titre == "c-Gamma"),
                                                 next(x.path.name for x in th.fiches if x.titre == "a-Gamma")]
    store.supprimer_theme(th)
    assert store.ordre() == {"themes": ["Beta", "Alpha"], "fiches": {}}


def test_reglage_ordre_abime_ignore(store):
    store.sauver_reglages(ordre="n'importe quoi")
    assert _noms(store) == ["Alpha", "Beta", "Gamma"]
    store.sauver_reglages(ordre={"themes": None, "fiches": {"Beta": "x", "Alpha": [1, "ok.md"]}})
    assert store.ordre() == {"themes": [], "fiches": {"Alpha": ["ok.md"]}}
    assert _noms(store) == ["Alpha", "Beta", "Gamma"]


# ---------- fenêtre ----------
def _noms_liste(fen):  # noqa: F811
    return [fen.liste_themes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(1, fen.liste_themes.count())]


def _depot(fen):  # noqa: F811
    for t in list(fen.store.themes):
        fen.store.supprimer_theme(t)
    for nom in ("Alpha", "Beta", "Gamma"):
        th = fen.store.nouveau_theme(nom)
        for titre in ("a", "b", "c"):
            f = fen.store.nouvelle_fiche(th)
            fen.store.enregistrer(th, f, f"{titre}-{nom}", "x")
    fen.maj_themes()
    fen.maj_fiches()


def test_glisser_deposer_des_themes(fen):  # noqa: F811
    _depot(fen)
    base = [n for n in _noms_liste(fen) if n in ("Alpha", "Beta", "Gamma")]
    liste = fen.liste_themes
    assert not (liste.item(0).flags() & Qt.ItemFlag.ItemIsDragEnabled)                  # « Toutes les fiches » ne se déplace pas
    ligne = liste.row(next(liste.item(i) for i in range(liste.count()) if liste.item(i).data(Qt.ItemDataRole.UserRole) == "Gamma"))
    it = liste.takeItem(ligne)                                                          # résultat d'un glisser-déposer vers le haut
    liste.insertItem(1, it)
    liste.reordonnee.emit()
    assert _noms_liste(fen)[0] == "Gamma" and fen.store.ordre()["themes"][0] == "Gamma"
    assert liste.item(0).data(Qt.ItemDataRole.UserRole) is None and fen.theme == fen.TOUS


def test_epingle_reste_au_dessus_meme_apres_deplacement(fen):  # noqa: F811
    _depot(fen)
    fen.store.epingler_theme(fen.store.theme("Beta"))
    fen.store.ordonner_themes(["Gamma", "Alpha", "Beta"])
    fen.maj_themes()
    assert _noms_liste(fen)[:3] == ["Beta", "Gamma", "Alpha"]


def test_alt_haut_bas_themes_et_fiches(fen):  # noqa: F811
    _depot(fen)
    fen.liste_themes.setCurrentRow(fen._noms().index("Beta"))
    fen.deplacer(fen.liste_themes, -1)
    base = _noms_liste(fen)
    assert base.index("Beta") < base.index("Alpha") and fen.theme == "Beta"
    fen.deplacer(fen.liste_themes, +1)
    fen.deplacer(fen.liste_themes, +1)
    assert _noms_liste(fen) == ["Alpha", "Gamma", "Beta"]
    # fiches : dans la vue d'un thème
    fen.theme = "Alpha"
    fen.liste_themes.setCurrentRow(fen._noms().index("Alpha"))
    assert [f.titre for _t, f in fen.rows] == ["a-Alpha", "b-Alpha", "c-Alpha"]
    fen.liste.setCurrentRow(2)
    fen.deplacer(fen.liste, -1)
    assert [f.titre for _t, f in fen.rows] == ["a-Alpha", "c-Alpha", "b-Alpha"] and fen.fiche.titre == "c-Alpha"
    fen.deplacer(fen.liste, +1)
    assert [f.titre for _t, f in fen.rows] == ["a-Alpha", "b-Alpha", "c-Alpha"]
    fen.liste.setCurrentRow(0)
    fen.deplacer(fen.liste, -1)                                                          # en butée : rien ne bouge
    assert [f.titre for _t, f in fen.rows] == ["a-Alpha", "b-Alpha", "c-Alpha"]


def test_glisser_deposer_des_fiches_seulement_dans_un_theme(fen):  # noqa: F811
    from PyQt6.QtWidgets import QAbstractItemView
    _depot(fen)
    fen.liste_themes.setCurrentRow(0)
    assert fen.liste.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop        # « Toutes les fiches »
    fen.liste_themes.setCurrentRow(fen._noms().index("Beta"))
    assert fen.liste.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
    it = fen.liste.takeItem(2)                                                          # c-Beta tout en haut
    fen.liste.insertItem(0, it)
    fen.liste.reordonnee.emit()
    assert [f.titre for _t, f in fen.rows] == ["c-Beta", "a-Beta", "b-Beta"]
    fen.recherche.setText("Beta")                                                       # pendant une recherche : pas de déplacement
    assert fen.liste.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    avant = fen.store.ordre()
    fen.deplacer(fen.liste, 1)
    assert fen.store.ordre() == avant


def test_menu_propose_l_ordre_alphabetique_apres_un_tri(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtCore import QPoint
    _depot(fen)
    vus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: vus.append([x.text() for x in self.actions()]))
    fen.liste_themes.setCurrentRow(fen._noms().index("Alpha"))
    fen._menu_theme(QPoint(1, 1))
    assert not any("alphabétique" in x for x in vus[-1])
    fen.deplacer(fen.liste_themes, +1)
    fen._menu_theme(QPoint(1, 1))
    assert any("Remettre les thèmes" in x for x in vus[-1])
    fen._ordre_alphabetique_themes()
    assert fen.store.ordre()["themes"] == []
