"""Barre Chercher / Remplacer (Ctrl+H) dans le texte de la fiche."""
from PyQt6.QtWidgets import QPlainTextEdit

from scrinium.ui.chercher_remplacer import BarreChercherRemplacer, occurrences


def test_occurrences():
    assert occurrences("Stéphane stéphane", "stéphane") == 2
    assert occurrences("Stéphane stéphane", "stéphane", True) == 1
    assert occurrences("abc", "") == 0


def test_barre(qtbot=None, app=None):
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    e = QPlainTextEdit("un chat, un Chat, un chien")
    b = BarreChercherRemplacer(e)
    b.ouvrir()
    b.chercher.setText("chat")
    b.remplacer.setText("lion")
    assert b.compte.text() == "2 trouvé(s)" or "2" in b.compte.text()
    b.remplacer_un()                                  # sélectionne la première occurrence, la remplace
    assert e.toPlainText().startswith("un lion,")
    assert b.remplacer_tout() == 1                    # reste « Chat »
    assert e.toPlainText() == "un lion, un lion, un chien"
    e.undo()
    assert e.toPlainText() == "un lion, un Chat, un chien"        # un seul Ctrl+Z annule tout le « Tout remplacer »
    b.casse.setChecked(True)
    b.chercher.setText("CHAT")
    assert not b.b_tout.isEnabled()
