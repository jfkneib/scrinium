# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Budget » : format, centimes, soldes, bilan, CSV, vue (onglets, saisie, titres) et fiche « résultat » dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.plugins import FicheVue  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "budget"
_spec = importlib.util.spec_from_file_location("budget_logique_t", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

TEXTE = """#scrinium-budget
budget: 400
depart: 50
mois 2026-11: Rentrée

| Date | Libellé | Catégorie | Débit | Crédit |
| --- | --- | --- | --- | --- |
| 2026-10-30 | Marché | Courses | 30 | |
| 2026-11-03 | Carrefour | Courses | 45,30 | |
| 2026-11-05 | Poche | | | 10 |
| 2026-11-09 | Stylos | École | 12,50 | |

Notes libres.
"""


def test_montants_en_centimes():
    assert [lg.centimes(x) for x in ("45,30", "45.3", "1 200,50", "45 €", "0,5", "-3", "12", "")] == [4530, 4530, 120050, 4500, 50, -300, 1200, None]
    assert lg.centimes("abc") is None and lg.centimes("1,2.3") is None and lg.centimes("1,234") is None and lg.centimes(None) is None
    assert lg.formater(4530) == "45,30" and lg.formater(4500) == "45,00" and lg.formater(4500, False) == "45" and lg.formater(-5) == "-0,05"
    assert lg.centimes("0,1") + lg.centimes("0,2") == lg.centimes("0,3")                                # pas de dérive de virgule flottante


def test_lecture_ecriture():
    b = lg.lire(TEXTE)
    assert b.mensuel == 40000 and b.depart == 5000 and b.titres == {"2026-11": "Rentrée"} and len(b.operations) == 4 and b.notes == "Notes libres."
    assert b.operations[1] == lg.Operation("2026-11-03", "Carrefour", "Courses", 4530, 0)
    t = lg.ecrire(b)
    assert "| 2026-11-09 | Stylos | École | 12,50 |  |" in t and t.startswith("#scrinium-budget\nbudget: 400\ndepart: 50\nmois 2026-11: Rentrée\n")
    assert lg.lire(t) == b                                                                           # aller-retour sans perte
    assert lg.lire("") == lg.lire(None) == lg.lire("#scrinium-budget\n") == lg.Budget()
    assert "budget:" not in lg.ecrire(lg.Budget()) and lg.lire(lg.texte_neuf()) == lg.Budget() and lg.TYPE.nom == "budget" and not lg.TYPE.executable
    assert lg.lire("#scrinium-budget\n| 2026-13-01 | x | | 5 | |\n| pas une date | y | | 1 | |\n").operations == []   # lignes invalides ignorées
    assert lg.lire("#scrinium-budget\n| 2026-11-01 | x | a\\|b | 5 | |\n").operations[0].categorie == "a|b"
    assert lg.lire("#scrinium-budget\nbudget: -5\n").mensuel is None


def test_soldes_totaux_et_bilan():
    b = lg.lire(TEXTE)
    assert lg.mois_presents(b) == ["2026-10", "2026-11"] and lg.solde_avant(b, "2026-11") == 2000      # 50 - 30
    t = lg.totaux(b, "2026-11")
    assert t["debit"] == 5780 and t["credit"] == 1000 and t["solde_mois"] == -4780 and t["solde_fin"] == -2780 and t["reste"] == 34220
    assert lg.totaux(b)["solde_fin"] == -2780 and lg.totaux(b)["debit"] == 8780 and lg.totaux(b)["reste"] is None
    assert lg.par_categorie(b) == [("Courses", 7530), ("École", 1250)] and lg.categories(b) == ["Courses", "École"]
    assert [(m, t_) for m, t_, _x in lg.resume_par_mois(b)] == [("2026-10", ""), ("2026-11", "Rentrée")]
    assert [i for i, _o in lg.operations_du_mois(b, "2026-11")] == [1, 2, 3]


def test_mois_sans_trou_et_courant():
    b = lg.lire("#scrinium-budget\nmois 2026-12: x\n| 2026-10-05 | a | | 1 | |\n")
    assert lg.mois_presents(b) == ["2026-10", "2026-11", "2026-12"] and lg.mois_suivant("2026-12") == "2027-01"
    assert lg.mois_presents(lg.Budget(), date(2026, 5, 3)) == ["2026-05"] and lg.mois_valide("2026-11") and not lg.mois_valide("2026-13")


def test_csv_et_detection():
    c = lg.vers_csv(lg.lire(TEXTE)).splitlines()
    assert c[0] == "Date;Libellé;Catégorie;Débit;Crédit;Solde" and c[1] == "2026-10-30;Marché;Courses;30,00;;20,00" and c[-1].endswith(";-27,80")
    assert lg.est_budget(TEXTE) and not lg.est_budget("#scrinium-budget-resultat\n") and not lg.est_budget("#scrinium-calc\n") and not lg.est_budget(None)


def test_resultat_de_plusieurs_budgets():
    a, b = lg.lire(TEXTE), lg.lire("#scrinium-budget\nbudget: 100\n| 2026-11-02 | x | | 20 | |\n| 2026-11-03 | y | | | 5 |\n")
    r = lg.resultat([("Courses", a), ("Enfant", b)], "2026-11")
    assert r["total"]["debit"] == 5780 + 2000 and r["total"]["credit"] == 1000 + 500 and r["total"]["reste"] == 34220 + 8000
    assert lg.resultat([("Courses", a)], None)["total"]["reste"] is None and lg.mois_de_tous([("a", a), ("b", b)]) == ["2026-10", "2026-11"]


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "budget")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("budget"), w.plugins.infos["budget"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _nouvelle(fen, libelle="Budget"):
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == libelle).trigger()
    return fen.vues_types["budget" if libelle == "Budget" else "budget-resultat"]


def test_saisie_debit_credit_soldes_titre_et_onglets(fen):
    vue = _nouvelle(fen)
    mois = date.today().strftime("%Y-%m")
    assert fen.pile.currentWidget() is vue and fen.fiche.texte.startswith("#scrinium-budget") and vue.courant == mois
    vue.e_date.setText(mois + "-03")
    vue.e_libelle.setText("Carrefour")
    vue.c_categorie.setCurrentText("Courses")
    vue.e_montant.setText("45,30")
    vue.ajouter("debit")
    vue.e_montant.setText("100")
    vue.e_libelle.setText("Poche")
    vue.ajouter("credit")
    assert vue.table.rowCount() == 2 and vue.table.item(0, 3).text() == "45,30" and vue.table.item(1, 4).text() == "100,00"
    assert vue.table.item(0, 5).text() == "-45,30" and vue.table.item(1, 5).text() == "54,70" and "Solde du mois 54,70" in vue.totaux.text()
    vue.e_mensuel.setText("200")
    vue.e_mensuel.editingFinished.emit()
    assert "Reste sur le budget : 154,70" in vue.totaux.text()
    vue.e_titre.setText("Rentrée")
    vue.e_titre.editingFinished.emit()
    assert "Rentrée" in vue.onglets.tabText(vue.mois.index(mois))
    fen.sauver()
    assert f"mois {mois}: Rentrée" in fen.fiche.texte and "| Carrefour | Courses | 45,30 |  |" in fen.fiche.texte and "budget: 200" in fen.fiche.texte
    vue.e_montant.setText("abc")
    vue.ajouter("debit")
    assert "Montant invalide" in vue.statut.text() and vue.table.rowCount() == 2
    vue.e_date.setText("pas une date")
    vue.e_montant.setText("5")
    vue.ajouter("debit")
    assert "Date invalide" in vue.statut.text() and vue.table.rowCount() == 2


def test_modifier_supprimer_nouveau_mois_et_bilan(fen, tmp_path, monkeypatch):
    vue = _nouvelle(fen)
    mois = date.today().strftime("%Y-%m")
    for lib, mt in (("a", "10"), ("b", "20")):
        vue.e_date.setText(mois + "-01")
        vue.e_libelle.setText(lib)
        vue.e_montant.setText(mt)
        vue.ajouter("debit")
    vue.table.item(0, 3).setText("15")                                                 # modification directe d'une cellule
    assert vue.b.operations[0].debit == 1500 and vue.table.item(1, 5).text() == "-35,00"
    vue.table.item(0, 3).setText("oups")
    assert "Montant invalide" in vue.statut.text() and vue.b.operations[0].debit == 1500
    vue.supprimer_lignes([0])
    assert len(vue.b.operations) == 1 and vue.b.operations[0].libelle == "b"
    vue.nouveau_mois()
    suivant = lg.mois_suivant(mois)
    assert vue.courant == suivant and vue.table.rowCount() == 0 and suivant in vue.b.titres
    vue.onglets.setCurrentIndex(len(vue.mois))                                          # onglet Bilan
    assert vue.pile.currentIndex() == 1 and vue.courant is None and vue.t_mois.rowCount() == 3 and vue.t_mois.item(2, 2).text() == "20,00"
    import sys
    mod = sys.modules["scrinium_plugin_budget"]
    cible = tmp_path / "b.csv"
    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cible), "")))
    vue.exporter_csv()
    assert cible.read_text(encoding="utf-8-sig").splitlines()[1].startswith(mois + "-01;b;;20,00;;-20,00")


def test_fiche_resultat_totalise_tous_les_budgets(fen):
    th = fen.store.nouveau_theme("Comptes")
    for nom, ops in (("Courses", "| 2026-11-02 | a | | 20 | |\n| 2026-11-03 | b | | | 5 |\n"), ("Enfant", "budget: 50\n| 2026-11-04 | c | | 30 | |\n")):
        f = fen.store.nouvelle_fiche(th)
        fen.store.enregistrer(th, f, nom, "#scrinium-budget\n" + ops)
    f = fen.store.nouvelle_fiche(th)
    fen.store.enregistrer(th, f, "Note", "pas un budget")
    fen.maj_themes()
    vue = _nouvelle(fen, "Budget — résultat")
    assert fen.pile.currentWidget() is vue and len(vue._budgets) == 2
    assert vue.c_mois.count() == 2 and vue.c_mois.itemText(0) == "Tous les mois"
    vue.c_mois.setCurrentIndex(1)                                                       # 2026-11
    assert vue.table.rowCount() == 3 and vue.table.item(2, 0).text() == "Total"
    assert vue.table.item(2, 1).text() == "50,00" and vue.table.item(2, 2).text() == "5,00" and vue.table.item(2, 3).text() == "-45,00"
    assert vue.table.item(1, 4).text() == "20,00" and vue.table.item(0, 4).text() == ""      # reste du budget Enfant ; Courses sans budget
    assert "2 budget(s)" in vue.note.text()


def test_documentation_dans_le_guide(fen):
    fen.guide()
    assert any("Budget" in f.titre for f in fen.store.theme("Guide").fiches)
