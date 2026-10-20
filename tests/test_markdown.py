# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Mise en forme Markdown : boutons (écrivent la syntaxe), aperçu (n'écrit rien), liens limités."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPlainTextEdit  # noqa: E402

from scrinium.ui import markdown as md  # noqa: E402
from tests.test_ui import fen  # noqa: E402,F401,F811  (fixture de la fenêtre)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def editeur(texte="", debut=0, fin=None):
    e = QPlainTextEdit()
    e.setPlainText(texte)
    c = e.textCursor()
    c.setPosition(debut)
    if fin is not None:
        c.setPosition(fin, QTextCursor.MoveMode.KeepAnchor)
    e.setTextCursor(c)
    return e


def test_gras_sur_selection_puis_retrait(app):
    e = editeur("un mot ici", 3, 6)
    md.entourer(e, "**", "gras")
    assert e.toPlainText() == "un **mot** ici"
    c = e.textCursor()                        # sélectionne « **mot** » puis rebascule
    c.setPosition(3)
    c.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
    e.setTextCursor(c)
    md.entourer(e, "**", "gras")
    assert e.toPlainText() == "un mot ici"


def test_sans_selection_insere_un_exemple_selectionne(app):
    e = editeur("", 0)
    md.entourer(e, "*", "italique")
    assert e.toPlainText() == "*italique*" and e.textCursor().selectedText() == "italique"


def test_une_seule_annulation(app):
    e = editeur("abc", 0, 3)
    md.entourer(e, "`", "code")
    e.undo()
    assert e.toPlainText() == "abc"


def test_listes_et_citation_sur_plusieurs_lignes(app):
    e = editeur("a\nb\nc", 0, 3)              # lignes a et b
    md.prefixer(e, "- ")
    assert e.toPlainText() == "- a\n- b\nc"
    md.prefixer(e, "- ")                      # toutes déjà préfixées : on retire
    assert e.toPlainText() == "a\nb\nc"


def test_titre_tourne(app):
    e = editeur("Sujet", 2)
    suite = []
    for _i in range(4):
        md.titre(e)
        suite.append(e.toPlainText())
    assert suite == ["# Sujet", "## Sujet", "### Sujet", "Sujet"]


def test_lien_et_bloc_de_code(app):
    e = editeur("voir ici", 5, 8)
    md.lien(e)
    assert e.toPlainText() == "voir [ici](https://)" and e.textCursor().selectedText() == "https://"
    e = editeur("ls -l", 0, 5)
    md.bloc_code(e)
    assert e.toPlainText() == "```\nls -l\n```"


def test_apercu_rend_sans_rien_ecrire(fen):  # noqa: F811
    fen.texte.setPlainText("# Titre\n\n**gras** et `code`\n\n- a\n- b")
    avant = fen.texte.toPlainText()
    fen.format.b_apercu.setChecked(True)
    rendu = fen.apercu.toPlainText()
    assert fen.pile.currentWidget() is fen.apercu and "Titre" in rendu and "#" not in rendu and "**" not in rendu
    assert not fen.format.boutons[0].isEnabled()                    # boutons d'écriture grisés pendant l'aperçu
    fen.texte.setPlainText(avant + "\n\najout")                     # un plugin peut écrire : l'aperçu suit
    assert "ajout" in fen.apercu.toPlainText()
    fen.format.b_apercu.setChecked(False)
    assert fen.pile.currentWidget() is fen.texte and fen.format.boutons[0].isEnabled()
    assert fen.texte.toPlainText() == avant + "\n\najout"


def test_aucune_fiche_ou_fermee_sort_de_l_apercu(fen):  # noqa: F811
    fen.format.b_apercu.setChecked(True)
    fen._etat_editeur(False)
    assert not fen.format.b_apercu.isChecked() and fen.pile.currentWidget() is fen.texte


def test_liens_seulement_http_https_mailto(app, monkeypatch):
    ouverts = []
    monkeypatch.setattr(md.QDesktopServices, "openUrl", staticmethod(lambda u: ouverts.append(u.toString())))
    a = md.Apercu()
    for u in ("https://exemple.fr/", "http://x.fr", "mailto:a@x.fr", "file:///etc/passwd", "javascript:alert(1)", "smb://serveur/x"):
        a._lien(QUrl(u))
    assert ouverts == ["https://exemple.fr/", "http://x.fr", "mailto:a@x.fr"]


def test_sans_format():
    sf = md.sans_format
    assert sf("## Titre") == "Titre" and sf("- a\n* b\n1. c\n> d") == "a\nb\nc\nd"
    assert sf("**gras** et *italique* et `code`") == "gras et italique et code"
    assert sf("voir [ici](https://x.fr) ok") == "voir ici ok"
    assert sf("```\nls -l\n```") == "ls -l\n"
    assert sf("snake_case_nom et 2*3*4") == "snake_case_nom et 2*3*4"          # pas de faux positifs
    assert sf("texte simple") == "texte simple"
    assert sf("![img](a.png)") == "![img](a.png)"


def test_effacer_la_mise_en_forme_ligne_et_selection(app):
    e = editeur("# Titre\n- **un** mot\nfin", 10)                  # curseur dans la ligne 2, sans sélection
    md.effacer_format(e)
    assert e.toPlainText() == "# Titre\nun mot\nfin"
    e.undo()
    assert e.toPlainText() == "# Titre\n- **un** mot\nfin"
    e = editeur("# Titre\n- **un** mot\nfin", 0, 20)
    md.effacer_format(e)
    assert e.toPlainText() == "Titre\nun mot\nfin"


def test_second_clic_retire_les_marques_autour_de_la_selection(app):
    e = editeur("a **mot** b", 4, 7)                             # « mot » seul, marques autour
    md.entourer(e, "**", "gras")
    assert e.toPlainText() == "a mot b"


def test_lien_sur_une_adresse_selectionnee(app):
    u = "https://spo.medulla-tech.io/mmc/index.php?sessionexpired=1"
    e = editeur("ouvrir " + u + " ici", 7, 7 + len(u))
    md.lien(e)
    assert e.toPlainText() == "ouvrir <" + u + "> ici"
    c = e.textCursor()
    c.setPosition(7)
    c.setPosition(7 + len(u) + 2, QTextCursor.MoveMode.KeepAnchor)
    e.setTextCursor(c)
    md.lien(e)                                                       # second clic : on retire les chevrons
    assert e.toPlainText() == "ouvrir " + u + " ici"
    e = editeur("www.exemple.fr", 0, 14)
    md.lien(e)
    assert e.toPlainText() == "<https://www.exemple.fr>"
    assert md.sans_format("<https://x.fr/a?b=1>") == "https://x.fr/a?b=1"


def test_apercu_rend_une_adresse_cliquable(app):
    a = md.Apercu()
    for texte in ("<https://x.fr/a?b=1>", "https://x.fr/a?b=1", "[x](https://x.fr/a?b=1)"):
        a.afficher(texte)
        assert 'href="https://x.fr/a?b=1"' in a.toHtml(), texte
