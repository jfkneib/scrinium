# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Calc » (mini tableur) : format Markdown, formules sûres, vue de la grille dans la vraie fenêtre."""
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

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "calc"
_spec = importlib.util.spec_from_file_location("calc_logique_t", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

TEXTE = """#scrinium-calc
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
    assert lg.lire("") == ([], "") and lg.lire(None) == ([], "") and lg.lire("#scrinium-calc\n") == ([], "")
    assert lg.lire(lg.ecrire([["a|b", "c"], ["1", "2"]]))[0] == [["a|b", "c"], ["1", "2"]]         # la barre verticale est protégée
    assert lg.TYPE.nom == "calc" and not lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE and lg.lire(lg.TYPE.texte_neuf())[0]


def test_lignes_inegales_deviennent_rectangulaires():
    lignes, _n = lg.lire("#scrinium-calc\n| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 | 4 |\n")
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
    assert feuille("#scrinium-calc\n| a | b |\n| --- | --- |\n| x | 12,5 |\n| y | 13 |\n").affichage(0, 0) == "a"   # garde-fou
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
    assert tot[-1] == ["Moyenne", "=MOYENNE(B2:B3)", "=MOYENNE(C2:C3)"] and feuille(lg.ecrire(tot)).affichage(3, 1) == "12,75"


def test_rendu_impression_avec_les_resultats():
    t = lg.en_markdown("#scrinium-calc\n| a | b |\n| --- | --- |\n| 1 | =A2+1 |\n")
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


def test_nouvelle_fiche_grille_formules_et_sauvegarde(fen):
    vue = _nouvelle(fen)
    assert fen.pile.currentWidget() is vue and fen.fiche.texte.startswith("#scrinium-calc") and vue.table.columnCount() == 2
    assert vue.table.rowCount() == 6 and vue.table.item(0, 0).text() == "Date"
    vue.modifier_cellule(1, 1, "10")
    vue.modifier_cellule(2, 1, "12,5")
    vue.modifier_cellule(3, 1, "=SOMME(B2:B3)")
    assert vue.table.item(3, 1).text() == "22,5" and vue.table.item(3, 1).data(0x0100) == "=SOMME(B2:B3)"      # affiché / brut
    fen.sauver()
    assert "=SOMME(B2:B3)" in fen.fiche.texte and "| 12,5 |" in fen.fiche.texte
    vue.modifier_cellule(3, 1, "=1/0")
    assert vue.table.item(3, 1).text() == "#DIV/0!"


def test_lignes_colonnes_totaux_et_date(fen, monkeypatch):
    vue = _nouvelle(fen)
    vue.modifier_cellule(1, 1, "4")
    vue.ajouter_ligne()
    assert vue.table.rowCount() == 7 and vue.table.item(6, 0).text() == date.today().isoformat()
    vue.ajouter_colonne()
    assert vue.table.columnCount() == 3
    vue.totaux("SOMME", "Somme")
    assert vue.table.item(7, 0).text() == "Somme" and vue.table.item(7, 1).text() == "4"
    vue.supprimer_lignes([0, 7])                                                   # l'en-tête reste
    assert vue.table.rowCount() == 7 and vue.table.item(0, 0).text() == "Date"
    vue.inserer_ligne(1)
    assert vue.table.rowCount() == 8
    vue.supprimer_colonnes([2])
    vue.inserer_colonne(0)
    assert vue.table.columnCount() == 3
    vue.vider([(1, 1)])
    assert vue.lignes[1][1] == ""


def test_copier_coller_depuis_un_autre_tableur(fen):
    vue = _nouvelle(fen)
    QApplication.clipboard().setText("a\tb\tc\n1\t2\t3")
    vue.table.setCurrentCell(1, 0)
    vue.table.selectRow(1)
    vue.table.setCurrentCell(1, 0)
    vue.coller()
    assert vue.lignes[1][:3] == ["a", "b", "c"] and vue.lignes[2][:3] == ["1", "2", "3"] and vue.table.columnCount() == 3
    vue.table.clearSelection()
    vue.table.setRangeSelected(QTableWidgetSelectionRange(1, 0, 2, 1), True)
    vue.copier()
    assert QApplication.clipboard().text() == "a\tb\n1\t2"


def test_documentation_dans_le_guide(fen):
    fen.guide()
    assert any("Calc" in f.titre for f in fen.store.theme("Guide").fiches)
