# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Calculatrice » : calcul sûr, format de la fiche, vue du type et mini calculatrice dans la vraie fenêtre."""
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.plugins import FicheVue  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "calculatrice"
_spec = importlib.util.spec_from_file_location("calc_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


@pytest.mark.parametrize("expr,attendu", [
    ("2+3*4", "14"), ("(2+3)*4", "20"), ("10/4", "2.5"), ("10/5", "2"), ("2^10", "1024"), ("7 % 3", "1"), ("7//2", "3"),
    ("sqrt(16)", "4"), ("max(1,5)", "5"), ("3×4÷2", "6"), ("1,5+1", "2.5"), ("200*20%", "40"), ("20%", "0.2"), ("2(3+1)", "8"),
    ("-3+5", "2"), ("0.1+0.2", "0.3"), ("pi*2", "6.28318530718"), ("√9", "3"), ("5²", "25"), ("2**3**2", "512")])
def test_calculs(expr, attendu):
    assert lg.calcul_texte(expr) == attendu


@pytest.mark.parametrize("expr", ["", "   ", "1/0", "(1+2", "1+", "abc", "__import__('os').system('x')", "open('x')", "[1][0]",
                                  "2**100000", "'a'*3", "(lambda: 1)()", "sqrt(-1)", "x=1", "1; 2", "a.b", "9" * 600])
def test_refus_et_securite(expr):
    with pytest.raises(lg.ErreurCalcul):
        lg.calculer(expr)


@pytest.mark.parametrize("expr,degres,attendu", [
    ("sin(30)", True, "0.5"), ("sin(180)", True, "0"), ("cos(60)", True, "0.5"), ("tan(45)", True, "1"), ("asin(1)", True, "90"),
    ("acos(0.5)", True, "60"), ("sin(pi/2)", False, "1"), ("atan(1)", False, "0.785398163397"), ("5!", False, "120"), ("(2+3)!", False, "120"),
    ("0!", False, "1"), ("ln(e)", False, "1"), ("log(1000)", False, "3"), ("log2(8)", False, "3"), ("exp(0)", False, "1"), ("cbrt(27)", False, "3"),
    ("sinh(0)", False, "0"), ("deg(pi)", False, "180"), ("rad(180)", False, "3.14159265359"), ("2^0.5", False, "1.41421356237"), ("1/(4)", False, "0.25")])
def test_fonctions_scientifiques(expr, degres, attendu):
    assert lg.calcul_texte(expr, degres) == attendu


@pytest.mark.parametrize("expr", ["tan(90)", "sqrt(-1)", "ln(0)", "asin(2)", "171!", "0.5!", "(-1)!", "fact(1,2)", "sin()", "log(0)"])
def test_scientifique_hors_domaine(expr):
    with pytest.raises(lg.ErreurCalcul):
        lg.calculer(expr, True)


def test_aucun_code_execute(tmp_path):
    marque = tmp_path / "pwn"
    with pytest.raises(lg.ErreurCalcul):
        lg.calculer(f"__import__('pathlib').Path('{marque}').touch()")
    assert not marque.exists()


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "calculatrice")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("calculatrice"), w.plugins.infos["calculatrice"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _fiche_note(fen, texte):
    th = fen.store.nouveau_theme("T")
    f = fen.store.nouvelle_fiche(th)
    fen.store.enregistrer(th, f, "note", texte)
    fen.maj_themes()
    fen.montrer(theme="T")
    th = fen.store.theme("T")
    fen.selectionner_fiche(FicheVue(th, next(x for x in th.fiches if x.titre == "note")))


def test_mini_calculatrice_insere_au_curseur(fen):
    _fiche_note(fen, "total : ")
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.End)
    instance = fen.plugins.actifs["calculatrice"][0]
    instance.ouvrir_mini()
    mini = instance.mini
    assert mini.isVisible()
    for t in "12*8":
        mini.touche(t)
    assert mini.resultat.text() == "= 96"
    mini.inserer()
    assert fen.texte.toPlainText() == "total : 96" and "inséré" in mini.statut.text()
    mini.touche("C")
    assert mini.saisie.text() == "" and mini.valeur() is None
    mini.inserer()
    assert "Rien" in mini.statut.text()
    mini.saisie.setText("2+2")
    mini.touche("=")
    assert mini.saisie.text() == "4"                                       # on peut enchaîner avec le résultat
    mini.saisie.setText("1/0")
    mini.touche("=")
    assert "zéro" in mini.resultat.text() and mini.saisie.text() == "1/0"
    mini.close()


def test_mode_scientifique_et_unite_des_angles(fen):
    instance = fen.plugins.actifs["calculatrice"][0]
    instance.ouvrir_mini()
    mini = instance.mini
    assert mini.zone_sci.isHidden() and mini.degres and mini.b_angle.text() == "Deg"
    mini.b_scientifique.setChecked(True)
    assert not mini.zone_sci.isHidden()
    for t in ("sin(", "30", ")"):
        mini.touche(t)
    assert mini.resultat.text() == "= 0.5"                                    # degrés par défaut
    mini.b_angle.setChecked(False)
    assert mini.b_angle.text() == "Rad" and mini.resultat.text() != "= 0.5"   # l'aperçu suit l'unité
    mini.touche("C")
    for t in ("5", "!"):
        mini.touche(t)
    assert mini.resultat.text() == "= 120"
    assert fen.plugins.actifs["calculatrice"][1].reglages.get("scientifique") is True
    mini.close()


def test_mini_calculatrice_reprend_la_selection(fen):
    _fiche_note(fen, "12*8")
    fen.texte.selectAll()
    instance = fen.plugins.actifs["calculatrice"][0]
    instance.ouvrir_mini()
    assert instance.mini.saisie.text() == "12*8"
    instance.mini.close()


def test_documentation_ajoutee_au_guide(fen):
    docs = fen.plugins.actifs["calculatrice"][1].docs()
    assert docs and "Calculatrice" in docs[0][0]
    fen.guide()
    titres = [f.titre for f in fen.store.theme("Guide").fiches]
    assert any("Calculatrice" in t for t in titres)
    fen.plugins.desactiver("calculatrice")
    assert fen.plugins._docs == []


def test_bouton_et_menu(fen):
    a = next(a for a in fen.barre.actions() if a.text() == "Mini calculatrice")
    w = fen.barre.widgetForAction(a)
    assert w.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly and a.toolTip() == "Mini calculatrice"   # icône seule, nom en infobulle
    assert any(a.text() == "Mini calculatrice" for a in fen.menu_ext.actions())
    fen.plugins.desactiver("calculatrice")
    assert not any(a.text() == "Mini calculatrice" for a in fen.barre.actions())
