# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Suivi » : fiche, calculs (poids, calories, variation, IMC) et vue dans la vraie fenêtre."""
import importlib.util
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QDate  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "suivi"
_spec = importlib.util.spec_from_file_location("suivi_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


def test_nombres_tolerants_et_limites():
    assert lg.lire_poids("78,4") == 78.4 and lg.lire_poids(" 78.44 kg ") == 78.4 and lg.lire_poids("") is None
    assert lg.lire_poids("5") is None and lg.lire_poids("999") is None and lg.lire_poids("abc") is None and lg.lire_poids("nan") is None
    assert lg.lire_calories("2 100".replace(" ", "")) == 2100 and lg.lire_calories("-5") is None and lg.lire_calories("99999") is None
    assert lg.lire_jour("10/11/2026") == "2026-11-10" and lg.lire_jour("2026-11-10") == "2026-11-10" and lg.lire_jour("2026-13-40") == ""


def test_texte_aller_retour_et_saisie():
    s = lg.Suivi(taille=175, objectif_poids=72, objectif_calories=2000)
    assert s.poser_poids("2026-11-10", "78,4") and s.ajouter_calories("2026-11-10", "450") and s.ajouter_calories("2026-11-10", "600")
    assert s.jours["2026-11-10"]["calories"] == 1050
    assert s.ajouter_calories("2026-11-10", "-2000") and s.jours["2026-11-10"]["calories"] == 0           # jamais sous zéro
    assert not s.ajouter_calories("2026-11-10", "beaucoup") and not s.poser_poids("pas une date", "70") and not s.poser_poids("2026-11-10", "5")
    s.poser_note("2026-11-10", "pizza | vin\nrouge")
    assert s.jours["2026-11-10"]["note"] == "pizza / vin rouge"
    s.poser_poids("2026-11-11", "")
    assert "2026-11-11" not in s.jours                                              # un jour vide disparaît
    t = lg.ecrire(s)
    assert t.startswith("#scrinium-suivi\ntaille: 175\nobjectif_poids: 72\nobjectif_calories: 2000\n") and "| 2026-11-10 | 78.4 | 0 | pizza / vin rouge |" in t
    assert lg.ecrire(lg.lire(t)) == t
    assert lg.lire("texte libre sans rien").jours == {} and lg.lire(None).jours == {}
    assert lg.lire("| 2026-11-10 | abc | 12 | x |").jours["2026-11-10"] == {"poids": None, "calories": 12, "note": "x"}


def test_statistiques():
    s = lg.Suivi(taille=175, objectif_poids=74, objectif_calories=2000)
    aujourdhui = date(2026, 11, 10)
    for i, (p, c) in enumerate([(80.0, 2200), (79.5, 2000), (79.0, 1800), (78.0, 2100)]):
        j = (aujourdhui - timedelta(days=30 - 10 * i if i < 3 else 0)).isoformat()
        s.poser_poids(j, p)
        s.poser_calories(j, c)
    assert lg.dernier_poids(s) == ("2026-11-10", 78.0)
    assert lg.variation(s, 7) == -1.0 and lg.variation(s, 30) == -2.0 and lg.variation(s, 365) is None
    assert lg.moyenne_calories(s, 7, aujourdhui) == 2100 and lg.moyenne_calories(s, 30, aujourdhui) == 1967       # la pesée d'il y a 30 jours pile est hors fenêtre
    assert lg.moyenne_calories(lg.Suivi(), 7, aujourdhui) is None
    assert lg.imc(76.2, 175) == 24.9 and lg.imc(None, 175) is None and lg.imc(70, None) is None
    assert lg.ecart_objectif(s) == 4.0
    assert lg.reste_calories(s, "2026-11-10") == -100 and lg.reste_calories(lg.Suivi(), "2026-11-10") is None
    assert lg.variation(lg.Suivi(), 7) is None and lg.ecart_objectif(lg.Suivi()) is None


def test_exemple_valide():
    (_theme, _titre, texte), = lg.exemples(date(2026, 11, 10))
    s = lg.lire(texte)
    assert len(s.jours) == 21 and lg.dernier_poids(s) == ("2026-11-10", 76.2) and lg.ecrire(s) == texte


# ---------- dans la vraie fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "suivi")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("suivi"), w.plugins.infos["suivi"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def test_vue_saisie_bilan_et_graphiques(fen):
    vue = fen.vues_types["suivi"]
    textes = []
    vue.modifie.connect(textes.append)
    vue.charger(lg.texte_neuf())
    assert vue.table.rowCount() == 0 and not vue.barre.isVisibleTo(vue)
    vue.e_obj_cal.setText("2000")
    vue._reglages()
    vue.e_poids.setText("78,4")
    vue._poids()
    vue.e_cal.setText("500")
    vue._calories()
    vue.e_cal.setText("700")
    vue._calories()
    assert textes and "objectif_calories: 2000" in textes[-1] and "78.4 | 1200 |" in textes[-1]
    assert vue.table.rowCount() == 1 and vue.table.item(0, 2).text() == "1200"
    assert "78.4 kg" in vue.bilan.text()
    assert vue.barre.maximum() == 2000 and vue.barre.value() == 1200 and "1200 / 2000" in vue.barre.format()
    assert vue.g_poids.points == [(date.today().isoformat(), 78.4)] and vue.g_cal.objectif == 2000
    vue.g_poids.grab()                                                               # le dessin ne plante pas
    vue.g_cal.grab()


def test_saisie_invalide_et_cellule_modifiee_et_suppression(fen):
    vue = fen.vues_types["suivi"]
    vue.charger(lg.ecrire(lg.lire("| 2026-11-09 | 80 | 2000 | a |\n| 2026-11-10 | 79 | 1900 | b |")))
    assert vue.table.rowCount() == 2 and vue.table.item(0, 0).text() == "2026-11-10"   # le plus récent en premier
    vue.e_poids.setText("abc")
    vue._poids()
    assert "non reconnu" in vue.bilan.text() and len(vue.s.jours) == 2
    vue.table.item(0, 1).setText("78,5")
    assert vue.s.jours["2026-11-10"]["poids"] == 78.5
    vue._supprimer([0])
    assert list(vue.s.jours) == ["2026-11-09"]


def test_periode_limite_les_graphiques(fen):
    vue = fen.vues_types["suivi"]
    auj = date.today()
    s = lg.Suivi()
    for k in (0, 10, 60):
        s.poser_poids((auj - timedelta(days=k)).isoformat(), 80 - k / 10)
    vue.charger(lg.ecrire(s))
    vue.c_periode.setCurrentIndex(0)                                                 # 30 jours
    assert len(vue.g_poids.points) == 2
    vue.c_periode.setCurrentIndex(3)                                                 # tout
    assert len(vue.g_poids.points) == 3


def test_couleurs_vert_jaune_rouge(fen):
    import sys
    m = sys.modules.get("scrinium_plugin_suivi")
    if m is None:
        pytest.skip("extension non chargée (lancé seul)")
    assert m.couleur_ratio(0.3).hue() == 120 and m.couleur_ratio(1.0).hue() == 60 and m.couleur_ratio(2.0).hue() == 0


def test_graduations_rondes(fen):
    import sys
    g = sys.modules["scrinium_plugin_suivi"].graduations
    assert g(0, 2808) == [0, 1000, 2000] and g(73.6, 79.0) == [74, 76, 78] and g(0, 10)[0] == 0 and g(0, 10)[-1] == 10
    assert all(isinstance(v, float) or isinstance(v, int) for v in g(0.0, 0.0))
