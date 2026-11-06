# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Calc » (éditeur de listes avec totaux par colonne, export / import CSV) : format, totaux, vue dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QTableWidgetSelectionRange  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "calc"
_spec = importlib.util.spec_from_file_location("calc_logique_t", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

TEXTE = """#scrinium-calc
| Date | Valeur | Note |
| --- | --- | --- |
| 2026-11-06 | 12,5 | a |
| 2026-11-07 | 13 | b |
| 2026-11-08 | x | c |

totaux: | somme | nb

Notes libres.
"""


def test_lecture_ecriture_garde_liste_totaux_et_notes():
    lignes, totaux, notes = lg.lire(TEXTE)
    assert len(lignes) == 4 and lignes[0] == ["Date", "Valeur", "Note"] and totaux == ["", "somme", "nb"] and notes == "Notes libres."
    assert lg.ecrire(lignes, totaux, notes) == TEXTE
    assert lg.lire("") == ([], [], "") and lg.lire(None) == ([], [], "") and lg.lire("#scrinium-calc\n") == ([], [], "")
    assert "totaux" not in lg.ecrire(lignes, ["", "", ""])                                     # aucun total : pas de ligne
    assert lg.lire(lg.ecrire([["a|b", "c"], ["1", "2"]]))[0] == [["a|b", "c"], ["1", "2"]]
    assert lg.lire("#scrinium-calc\n| a | b |\n| --- | --- |\n| 1 | 2 |\ntotaux: bidon | max\n")[1] == ["", "max"]   # nom inconnu : ignoré
    assert lg.TYPE.nom == "calc" and not lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE and lg.lire(lg.TYPE.texte_neuf())[0]


def test_totaux():
    lignes, _t, _n = lg.lire(TEXTE)
    assert lg.total(lignes, 1, "somme") == "25,5" and lg.total(lignes, 1, "moyenne") == "12,75" and lg.total(lignes, 1, "min") == "12,5"
    assert lg.total(lignes, 1, "max") == "13" and lg.total(lignes, 1, "nb") == "2"                  # « x » n'est pas un nombre : ignoré
    assert lg.total(lignes, 2, "somme") == "" and lg.total(lignes, 2, "nb") == "0" and lg.total(lignes, 0, "") == "" and lg.total(lignes, 0, "bidon") == ""
    assert lg.nombre("1 200.5") == 1200.5 and lg.nombre("8%") == 0.08 and lg.nombre("2026-11-06") is None and lg.nombre("1,2.3") is None


def test_ajouter_ligne_et_csv():
    lignes, _t, _n = lg.lire(TEXTE)
    assert lg.ajouter_ligne(lignes, date(2026, 11, 9))[-1] == ["2026-11-09", "", ""]
    assert lg.ajouter_ligne([["Nom", "Qté"]], date(2026, 1, 1))[-1] == ["", ""]
    c = lg.vers_csv(lignes)
    assert c.splitlines()[0] == "Date;Valeur;Note" and lg.depuis_csv(c) == lignes
    assert lg.depuis_csv("a,b\n1,2\n\n") == [["a", "b"], ["1", "2"]] and lg.depuis_csv("﻿a;b\n\"x;y\";2") == [["a", "b"], ["x;y", "2"]]
    assert lg.depuis_csv("") == []


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "calc")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("calc"), w.plugins.infos["calc"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _nouvelle(fen):
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == "Calc").trigger()
    return fen.vues_types["calc"]


def test_nouvelle_liste_saisie_et_totaux_recalcules(fen):
    vue = _nouvelle(fen)
    assert fen.pile.currentWidget() is vue and fen.fiche.texte.startswith("#scrinium-calc")
    assert vue.table.columnCount() == 2 and vue.table.rowCount() == 7 and vue.table.item(0, 0).text() == "Date"     # 6 lignes + les totaux
    vue.table.item(1, 1).setText("10")                                        # saisie dans la grille (signal itemChanged)
    vue.table.item(2, 1).setText("12,5")
    assert vue.lignes[1][1] == "10" and vue.table.item(6, 1).text() == "Somme : 22,5"
    fen.sauver()
    assert "| 12,5 |" in fen.fiche.texte and "totaux: | somme" in fen.fiche.texte
    vue.choisir_total(1, "moyenne")
    assert vue.table.item(6, 1).text() == "Moyenne : 11,25"
    vue.choisir_total(1, "")
    assert vue.table.item(6, 1).text() == ""
    assert not vue.table.item(6, 1).flags() & vue.table.item(1, 1).flags().__class__.ItemIsEditable      # la ligne des totaux ne s'édite pas


def test_lignes_colonnes_et_date(fen):
    vue = _nouvelle(fen)
    vue.ajouter_ligne()
    assert vue.table.rowCount() == 8 and vue.table.item(6, 0).text() == date.today().isoformat()
    vue.ajouter_colonne()
    vue.inserer_colonne(0)
    assert vue.table.columnCount() == 4 and len(vue.totaux) == 4
    vue.supprimer_colonnes([0])
    vue.supprimer_lignes([0, 6])                                              # l'en-tête reste
    assert vue.table.columnCount() == 3 and vue.table.rowCount() == 7 and vue.table.item(0, 0).text() == "Date"
    vue.inserer_ligne(1)
    assert vue.table.rowCount() == 8
    vue.modifier_cellule(1, 1, "5")
    vue.vider([(1, 1)])
    assert vue.lignes[1][1] == ""


def test_copier_coller(fen):
    vue = _nouvelle(fen)
    QApplication.clipboard().setText("a\tb\tc\n1\t2\t3")
    vue.table.setCurrentCell(1, 0)
    vue.coller()
    assert vue.lignes[1][:3] == ["a", "b", "c"] and vue.lignes[2][:3] == ["1", "2", "3"] and vue.table.columnCount() == 3 and len(vue.totaux) == 3
    vue.table.clearSelection()
    vue.table.setRangeSelected(QTableWidgetSelectionRange(1, 0, 2, 1), True)
    vue.copier()
    assert QApplication.clipboard().text() == "a\tb\n1\t2"


def test_export_import_csv(fen, tmp_path, monkeypatch):
    vue = _nouvelle(fen)
    vue.modifier_cellule(1, 1, "10")
    mod = sys.modules["scrinium_plugin_calc"]
    cible = tmp_path / "l.csv"
    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cible), "")))
    vue.exporter_csv()
    assert cible.read_text(encoding="utf-8-sig").splitlines()[:2] == ["Date;Valeur", ";10"]
    src = tmp_path / "s.csv"
    src.write_text("x;y\n1;2\n", encoding="utf-8")
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(mod.QMessageBox, "question", staticmethod(lambda *a, **k: mod.QMessageBox.StandardButton.Yes))
    vue.importer_csv()
    assert vue.lignes == [["x", "y"], ["1", "2"]] and vue.table.rowCount() == 3 and vue.totaux == ["", ""]


def test_documentation_dans_le_guide(fen):
    fen.guide()
    assert any("Calc" in f.titre for f in fen.store.theme("Guide").fiches)
