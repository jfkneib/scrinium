# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Favoris épinglés : thèmes et fiches (réglages de l'utilisateur), suite des renommages, ordre dans les listes, boutons et menus."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    for nom in ("Alpha", "Beta", "Gamma"):
        th = s.nouveau_theme(nom)
        for titre in ("un", "deux"):
            f = s.nouvelle_fiche(th)
            s.enregistrer(th, f, f"{titre} {nom}", "texte")
    return s


def _f(store, theme, titre):
    th = store.theme(theme)
    return th, next(f for f in th.fiches if f.titre == titre)


def test_epingler_et_desepingler(store):
    th = store.theme("Beta")
    t2, f = _f(store, "Beta", "un Beta")
    assert not store.theme_epingle(th) and not store.fiche_epinglee(t2, f)
    store.epingler_theme(th)
    store.epingler_fiche(t2, f)
    assert store.theme_epingle(th) and store.fiche_epinglee(t2, f)
    assert Store(store.paths).theme_epingle(th)                        # persistant (settings.json)
    store.epingler_theme(th, False)
    store.epingler_fiche(t2, f, False)
    assert store.favoris() == {"themes": [], "fiches": []}


def test_les_favoris_suivent_les_renommages(store):
    th, f = _f(store, "Beta", "un Beta")
    store.epingler_theme(th)
    store.epingler_fiche(th, f)
    store.enregistrer(th, f, "titre changé", "texte")                  # le fichier change de nom avec le titre
    assert store.fiche_epinglee(th, f)
    store.renommer_theme(th, "Bêta")
    assert store.theme_epingle(th) and store.fiche_epinglee(th, f)
    assert store.favoris()["themes"] == ["Bêta"] and store.favoris()["fiches"][0].startswith("Bêta/")
    store.verrouiller(th, f, "mdp1234", sans_secours=True)             # .md -> .lock
    assert store.fiche_epinglee(th, f)
    store.retirer_verrou(th, f)
    assert store.fiche_epinglee(th, f)


def test_les_favoris_disparaissent_avec_la_suppression(store):
    th, f = _f(store, "Alpha", "un Alpha")
    store.epingler_theme(th)
    store.epingler_fiche(th, f)
    store.supprimer_fiche(th, f)
    assert store.favoris()["fiches"] == [] and store.favoris()["themes"] == ["Alpha"]
    store.supprimer_theme(th)
    assert store.favoris() == {"themes": [], "fiches": []}
    gamma, g = _f(store, "Gamma", "deux Gamma")                        # un thème de même préfixe n'est pas touché
    store.epingler_fiche(gamma, g)
    store.nouveau_theme("Gamma2")
    store.supprimer_theme(store.theme("Gamma2"))
    assert store.fiche_epinglee(gamma, g)


def test_reglage_favoris_abime_ignore(store):
    store.sauver_reglages(favoris="n'importe quoi")
    assert store.favoris() == {"themes": [], "fiches": []}
    store.sauver_reglages(favoris={"themes": [1, "Alpha"], "fiches": None})
    assert store.favoris() == {"themes": ["Alpha"], "fiches": []}


# ---------- fenêtre ----------
from PyQt6.QtWidgets import QMenu  # noqa: E402

from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _themes(fen):  # noqa: F811
    return [fen.liste_themes.item(i).text().split("  (")[0] for i in range(1, fen.liste_themes.count())]


def test_theme_epingle_monte_en_tete_avec_une_punaise(fen):  # noqa: F811
    for nom in ("Alpha", "Zeta"):
        fen.store.nouveau_theme(nom)
    fen.maj_themes()
    assert _themes(fen)[0] != "Zeta"
    fen.liste_themes.setCurrentRow(fen._noms().index("Zeta"))
    fen.b_pin_theme.click()
    assert _themes(fen)[0] == "Zeta" and fen.theme == "Zeta"           # la sélection suit le thème déplacé
    assert fen.b_pin_theme.isChecked()
    assert fen.liste_themes.item(1).icon().cacheKey() != fen.liste_themes.item(len(_themes(fen))).icon().cacheKey()
    fen.b_pin_theme.click()
    assert _themes(fen) == sorted(_themes(fen), key=str.lower) and not fen.b_pin_theme.isChecked()


def test_fiche_epinglee_en_tete_de_liste(fen):  # noqa: F811
    th = fen.store.nouveau_theme("Liste")
    for t in ("a", "b", "c"):
        f = fen.store.nouvelle_fiche(th)
        fen.store.enregistrer(th, f, t, "x")
    fen.theme = "Liste"
    fen.maj_themes()
    fen.maj_fiches()
    assert [f.titre for _t, f in fen.rows] == ["a", "b", "c"]
    fen.epingler_fiche(th, next(f for f in th.fiches if f.titre == "c"))
    assert [f.titre for _t, f in fen.rows] == ["c", "a", "b"]
    assert fen.store.fiche_epinglee(*fen.rows[0]) and not fen.store.fiche_epinglee(*fen.rows[1])


def test_menus_clic_droit_proposent_epingler(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtCore import QPoint
    vus = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: vus.append([x.text() for x in self.actions()]))
    th = fen.store.nouveau_theme("Menu")
    f = fen.store.nouvelle_fiche(th)
    fen.store.enregistrer(th, f, "titre", "x")
    fen.theme = "Menu"
    fen.maj_themes()
    fen.maj_fiches()
    monkeypatch.setattr(fen.liste, "itemAt", lambda pos: fen.liste.item(0))
    fen._menu_fiche(QPoint(1, 1))
    fen._menu_theme(QPoint(1, 1))
    assert vus[0][0] == "Épingler" and vus[1][0] == "Épingler"
    fen.epingler_fiche(th, f)
    fen._menu_fiche(QPoint(1, 1))
    assert vus[2][0] == "Désépingler"
