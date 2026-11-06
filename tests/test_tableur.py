# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Tableur » (tableur) : format Markdown, formules sûres, vue de la grille dans la vraie fenêtre."""
import importlib.util
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QTableWidgetSelectionRange  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "tableur"
_spec = importlib.util.spec_from_file_location("tableur_logique_t", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

TEXTE = """#scrinium-tableur
| Date | Valeur | Double |
| --- | --- | --- |
| 2026-11-06 | 12,5 | =B2*2 |
| 2026-11-07 | 13 | =B3*2 |
| Somme | =SOMME(B2:B3) | =SOMME(C2:C3) |

Notes libres.
"""


def feuille(texte=TEXTE):
    return lg.Feuille(lg.lire(texte)[0])


def test_lecture_ecriture_garde_le_tableau_et_les_notes():
    lignes, notes = lg.lire(TEXTE)
    assert len(lignes) == 4 and lignes[0] == ["Date", "Valeur", "Double"] and lignes[3][1] == "=SOMME(B2:B3)" and notes == "Notes libres."
    assert lg.ecrire(lignes, notes) == TEXTE
    assert lg.lire("") == ([], "") and lg.lire(None) == ([], "") and lg.lire("#scrinium-tableur\n") == ([], "")
    assert lg.lire(lg.ecrire([["a|b", "c"], ["1", "2"]]))[0] == [["a|b", "c"], ["1", "2"]]         # la barre verticale est protégée
    assert lg.TYPE.nom == "tableur" and not lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE and lg.lire(lg.TYPE.texte_neuf())[0]


def test_lignes_inegales_deviennent_rectangulaires():
    lignes, _n = lg.lire("#scrinium-tableur\n| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 | 4 |\n")
    assert [len(r) for r in lignes] == [4, 4, 4]                                # largeur = la plus longue des lignes


@pytest.mark.parametrize("attendu,l,c", [("25", 1, 2), ("26", 2, 2), ("25,5", 3, 1), ("51", 3, 2), ("Date", 0, 0)])
def test_resultats(attendu, l, c):
    assert feuille().affichage(l, c) == attendu


@pytest.mark.parametrize("formule,attendu", [
    ("=1+2*3", "7"), ("=(1+2)*3", "9"), ("=10/4", "2,5"), ("=2^10", "1024"), ("=A2+1", "#VALEUR!"), ("=B2-B3", "-0,5"),
    ("=MOYENNE(B2:B3)", "12,75"), ("=MAX(B2:B3)-MIN(B2:B3)", "0,5"), ("=NB(A2:B3)", "2"), ("=ARRONDI(B2/3;1)", "4,2"),
    ("=somme(b2:b3)", "25,5"), ("=SUM(B2:B3)", "25,5"), ("=1/0", "#DIV/0!"), ("=ZZZ(1)", "#NOM?"), ("=Z99", "#REF!"),
    ("=(1+", "#ERREUR!"), ("=200*20%", "40"), ("=2*(3+1)", "8"), ("=RACINE(16)", "4"), ("=SOMME(B2;B3)", "25,5")])
def test_formules(formule, attendu):
    assert feuille("#scrinium-tableur\n| a | b |\n| --- | --- |\n| x | 12,5 |\n| y | 13 |\n").affichage(0, 0) == "a"   # garde-fou
    f = lg.Feuille([["a", "b"], ["x", "12,5"], ["y", "13"], [formule, ""]])
    assert f.affichage(3, 0) == attendu


def test_cycles_et_erreurs_en_cascade():
    f = lg.Feuille([["=B1", "=A1"], ["=A1+1", "=1/0"], ["=B2+1", ""]])
    assert f.affichage(0, 0) == f.affichage(0, 1) == "#CYCLE!" and f.affichage(1, 0) == "#CYCLE!" and f.affichage(2, 0) == "#DIV/0!"
    assert lg.Feuille([["=A1"]]).affichage(0, 0) == "#CYCLE!"


@pytest.mark.parametrize("formule", ["=__import__('os')", "=open('x')", "=[1][0]", "='a'*3", "=(lambda: 1)()", "=x.y", "=2**100000", "=9" * 1,
                                     "=A1.__class__", "=SOMME(__import__)"])
def test_aucun_code_execute(formule):
    f = lg.Feuille([[formule]])
    assert f.affichage(0, 0).startswith("#") or f.affichage(0, 0) == "9"


def test_nombres_et_formats():
    assert lg.nombre("12,5") == 12.5 and lg.nombre("1 200.5") == 1200.5 and lg.nombre("8%") == 0.08 and lg.nombre("abc") is None
    assert lg.nombre("") is None and lg.nombre("1,2.3") is None and lg.nombre("2026-11-06") is None and lg.nombre("-3") == -3
    assert lg.formater(0.1 + 0.2) == "0,3" and lg.formater(5.0) == "5" and lg.formater(12.5) == "12,5"
    assert lg.nom_colonne(0) == "A" and lg.nom_colonne(25) == "Z" and lg.nom_colonne(26) == "AA" and lg.ref("B3") == (2, 1) and lg.ref("aa1") == (0, 26)


def test_aides_a_l_edition():
    lignes, _n = lg.lire(TEXTE)
    plus = lg.ajouter_ligne(lignes[:3], date(2026, 11, 8))
    assert plus[-1] == ["2026-11-08", "", ""] and len(plus) == 4
    assert lg.ajouter_ligne([["Nom", "Qté"]], date(2026, 1, 1))[-1] == ["", ""]                      # pas de « Date » : pas de date
    tot = lg.ligne_de_totaux(lignes[:3], "MOYENNE", "Moyenne")
    assert tot[-1] == ["Moyenne", "=MOYENNE(B1:B3)", "=MOYENNE(C1:C3)"] and feuille(lg.ecrire(tot)).affichage(3, 1) == "12,75"
    # grille vide : les totaux vont dans la première ligne vide sous les données (ici la 3e, sans agrandir la grille)
    grille = lg.vide(3, 6)
    grille[0][1], grille[1][1] = "4", "6"
    tot = lg.ligne_de_totaux(grille, "SOMME")
    assert len(tot) == 6 and tot[2] == ["Somme", "=SOMME(B1:B2)", "=SOMME(C1:C2)"] and lg.Feuille(tot).affichage(2, 1) == "10"


def test_rendu_impression_avec_les_resultats():
    t = lg.en_markdown("#scrinium-tableur\n| a | b |\n| --- | --- |\n| 1 | =A2+1 |\n")
    assert "| 1 | 2 |" in t and "=" not in t and "scrinium-calc" not in t


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "tableur")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("tableur"), w.plugins.infos["tableur"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _nouvelle(fen):
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == "Tableur").trigger()
    return fen.vues_types["tableur"]


def test_nouvelle_fiche_grille_vide_formules_et_barre(fen):
    vue = _nouvelle(fen)
    assert fen.pile.currentWidget() is vue and fen.fiche.texte.startswith("#scrinium-tableur")
    assert vue.table.rowCount() == 12 and vue.table.columnCount() == 6 and vue.table.item(0, 0).text() == "" and vue.nom_cellule.text() == "A1"
    vue.modifier_cellule(0, 0, "10")
    vue.modifier_cellule(1, 0, "12,5")
    vue.modifier_cellule(2, 0, "=SOMME(A1:A2)")
    assert vue.table.item(2, 0).text() == "22,5" and vue.table.item(2, 0).data(0x0100) == "=SOMME(A1:A2)"      # affiché / brut
    fen.sauver()
    assert "=SOMME(A1:A2)" in fen.fiche.texte and "| 12,5 |" in fen.fiche.texte
    vue.table.setCurrentCell(2, 0)                                                 # la barre de formule montre la FORMULE, pas le résultat
    assert vue.nom_cellule.text() == "A3" and vue.barre.text() == "=SOMME(A1:A2)"
    vue.barre.setText("=A1*A2")
    vue.barre.returnPressed.emit()
    assert vue.table.item(2, 0).text() == "125" and vue.table.currentRow() == 3     # Entrée valide et descend d'une cellule
    vue.modifier_cellule(2, 0, "=1/0")
    assert vue.table.item(2, 0).text() == "#DIV/0!"


def test_lignes_colonnes_totaux_et_date(fen):
    vue = _nouvelle(fen)
    vue.modifier_cellule(0, 0, "Date")
    vue.modifier_cellule(0, 1, "Valeur")
    vue.modifier_cellule(1, 1, "4")
    vue.totaux("SOMME", "Somme")
    assert vue.table.item(2, 0).text() == "Somme" and vue.table.item(2, 1).text() == "4"      # dans la première ligne vide sous les données
    assert vue.table.rowCount() == 12
    vue.supprimer_lignes([2])
    assert vue.table.rowCount() == 11
    vue.ajouter_ligne()
    assert vue.table.rowCount() == 12 and vue.table.item(11, 0).text() == date.today().isoformat()
    vue.ajouter_colonne()
    assert vue.table.columnCount() == 7
    vue.inserer_ligne(5)
    vue.supprimer_lignes([5])
    vue.inserer_ligne(1)
    assert vue.table.rowCount() == 13
    vue.supprimer_colonnes([6])
    vue.inserer_colonne(0)
    assert vue.table.columnCount() == 7
    assert vue.lignes[2][2] == "4"                                                 # la colonne insérée à gauche a décalé les données
    vue.vider([(2, 2)])
    assert vue.lignes[2][2] == ""


def test_copier_coller_depuis_un_autre_tableur(fen):
    vue = _nouvelle(fen)
    QApplication.clipboard().setText("a\tb\tc\n1\t2\t3")
    vue.table.setCurrentCell(1, 0)
    vue.table.selectRow(1)
    vue.table.setCurrentCell(1, 0)
    vue.coller()
    assert vue.lignes[1][:3] == ["a", "b", "c"] and vue.lignes[2][:3] == ["1", "2", "3"] and vue.table.columnCount() == 6
    vue.table.clearSelection()
    vue.table.setRangeSelected(QTableWidgetSelectionRange(1, 0, 2, 1), True)
    vue.copier()
    assert QApplication.clipboard().text() == "a\tb\n1\t2"


def test_csv_exporte_les_resultats_et_importe_en_devinant_le_separateur():
    lignes, _n = lg.lire(TEXTE)
    csv_ = lg.vers_csv(lignes)
    assert csv_.splitlines()[0] == "Date;Valeur;Double" and csv_.splitlines()[1] == "2026-11-06;12,5;25" and csv_.splitlines()[3].startswith("Somme;25,5;")
    assert lg.depuis_csv(csv_) == [[c for c in l] for l in [["Date", "Valeur", "Double"], ["2026-11-06", "12,5", "25"], ["2026-11-07", "13", "26"],
                                                            ["Somme", "25,5", "51"]]]
    assert lg.depuis_csv("a,b\n1,2\n\n") == [["a", "b"], ["1", "2"]] and lg.depuis_csv("a\tb\n1\t2") == [["a", "b"], ["1", "2"]]
    assert lg.depuis_csv("\ufeffa;b\n\"x;y\";2") == [["a", "b"], ["x;y", "2"]] and lg.depuis_csv("") == []


def test_export_import_csv_dans_la_fenetre(fen, tmp_path, monkeypatch):
    import sys
    vue = _nouvelle(fen)
    vue.modifier_cellule(1, 1, "10")
    vue.modifier_cellule(2, 1, "=B2*2")
    mod = sys.modules["scrinium_plugin_tableur"]
    cible = tmp_path / "t.csv"
    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cible), "")))
    vue.exporter_csv()
    assert cible.read_text(encoding="utf-8-sig").splitlines()[2] == ";20"
    src = tmp_path / "s.csv"
    src.write_text("x;y\n1;2\n", encoding="utf-8")
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    monkeypatch.setattr(mod.QMessageBox, "question", staticmethod(lambda *a, **k: mod.QMessageBox.StandardButton.Yes))
    vue.importer_csv()
    assert vue.lignes == [["x", "y"], ["1", "2"]] and vue.table.rowCount() == 2


def test_documentation_dans_le_guide(fen):
    fen.guide()
    assert any("Tableur" in f.titre for f in fen.store.theme("Guide").fiches)
