"""Barre « Chercher / Remplacer » dans le texte de la fiche affichée (Ctrl+H). Tout est annulable avec Ctrl+Z."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from ..i18n import _


def occurrences(texte: str, motif: str, casse: bool = False) -> int:
    """Nombre d'occurrences (sans chevauchement) de `motif` dans `texte`."""
    if not motif:
        return 0
    return (texte if casse else texte.lower()).count(motif if casse else motif.lower())


class BarreChercherRemplacer(QWidget):
    def __init__(self, editeur: QPlainTextEdit, parent=None):
        super().__init__(parent)
        self.editeur = editeur
        self.chercher = QLineEdit()
        self.chercher.setPlaceholderText(_("Chercher dans la fiche"))
        self.chercher.setClearButtonEnabled(True)
        self.remplacer = QLineEdit()
        self.remplacer.setPlaceholderText(_("Remplacer par"))
        self.remplacer.setClearButtonEnabled(True)
        self.casse = QCheckBox(_("Aa"))
        self.casse.setToolTip(_("Respecter les majuscules et minuscules"))
        self.compte = QLabel("")
        self.b_prec = QPushButton("◀")
        self.b_prec.setToolTip(_("Précédent (Maj+Entrée)"))
        self.b_suiv = QPushButton("▶")
        self.b_suiv.setToolTip(_("Suivant (Entrée)"))
        self.b_un = QPushButton(_("Remplacer"))
        self.b_tout = QPushButton(_("Tout remplacer"))
        b_ferme = QPushButton("✕")
        b_ferme.setToolTip(_("Fermer (Échap)"))
        for b in (self.b_prec, self.b_suiv, b_ferme):
            b.setMaximumWidth(34)
        l1 = QHBoxLayout()
        for w in (self.chercher, self.b_prec, self.b_suiv, self.casse, self.compte):
            l1.addWidget(w, 1 if w is self.chercher else 0)
        l1.addWidget(b_ferme)
        l2 = QHBoxLayout()
        l2.addWidget(self.remplacer, 1)
        l2.addWidget(self.b_un)
        l2.addWidget(self.b_tout)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 2)
        v.addLayout(l1)
        v.addLayout(l2)
        self.setVisible(False)
        self.chercher.textChanged.connect(self._maj)
        self.casse.toggled.connect(self._maj)
        self.chercher.returnPressed.connect(self.suivant)
        self.remplacer.returnPressed.connect(self.remplacer_un)
        self.b_suiv.clicked.connect(self.suivant)
        self.b_prec.clicked.connect(self.precedent)
        self.b_un.clicked.connect(self.remplacer_un)
        self.b_tout.clicked.connect(self.remplacer_tout)
        b_ferme.clicked.connect(self.fermer)
        self.editeur.textChanged.connect(self._maj)

    # ---------- affichage ----------
    def ouvrir(self):
        sel = self.editeur.textCursor().selectedText()
        if sel and " " not in sel:
            self.chercher.setText(sel)
        self.setVisible(True)
        self.chercher.setFocus()
        self.chercher.selectAll()
        self._maj()

    def fermer(self):
        self.setVisible(False)
        self.editeur.setExtraSelections([])
        self.editeur.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.fermer()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.precedent()
        else:
            super().keyPressEvent(e)

    # ---------- recherche ----------
    def _options(self, arriere: bool = False):
        o = QTextDocument.FindFlag(0)
        if self.casse.isChecked():
            o |= QTextDocument.FindFlag.FindCaseSensitively
        if arriere:
            o |= QTextDocument.FindFlag.FindBackward
        return o

    def _maj(self, *_a):
        """Compteur et surlignage de toutes les occurrences."""
        if not self.isVisible():
            return
        motif = self.chercher.text()
        n = occurrences(self.editeur.toPlainText(), motif, self.casse.isChecked())
        self.compte.setText(_("%d trouvé(s)") % n if motif else "")
        for b in (self.b_prec, self.b_suiv):
            b.setEnabled(bool(motif) and n > 0)
        for b in (self.b_un, self.b_tout, self.remplacer):
            b.setEnabled(bool(motif) and n > 0 and not self.editeur.isReadOnly())
        sels = []
        if motif and n <= 2000:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#ffe58a"))
            fmt.setForeground(QColor("#000000"))
            doc = self.editeur.document()
            c = doc.find(motif, 0, self._options())
            while not c.isNull():
                s = QTextEdit.ExtraSelection()
                s.cursor, s.format = c, fmt
                sels.append(s)
                c = doc.find(motif, c, self._options())
        self.editeur.setExtraSelections(sels)

    def _aller(self, arriere: bool) -> bool:
        motif = self.chercher.text()
        if not motif:
            return False
        c = self.editeur.document().find(motif, self.editeur.textCursor(), self._options(arriere))
        if c.isNull():                                                      # on reboucle au début (ou à la fin)
            depart = QTextCursor(self.editeur.document())
            if arriere:
                depart.movePosition(QTextCursor.MoveOperation.End)
            c = self.editeur.document().find(motif, depart, self._options(arriere))
        if c.isNull():
            return False
        self.editeur.setTextCursor(c)
        self.editeur.ensureCursorVisible()
        return True

    def suivant(self):
        self._aller(False)

    def precedent(self):
        self._aller(True)

    # ---------- remplacement ----------
    def _selection_correspond(self) -> bool:
        sel = self.editeur.textCursor().selectedText()
        motif = self.chercher.text()
        return bool(motif) and (sel == motif if self.casse.isChecked() else sel.lower() == motif.lower())

    def remplacer_un(self):
        if not self.chercher.text() or self.editeur.isReadOnly():
            return
        if not self._selection_correspond() and not self._aller(False):
            return
        if self._selection_correspond():
            self.editeur.textCursor().insertText(self.remplacer.text())
        self._aller(False)

    def remplacer_tout(self) -> int:
        motif = self.chercher.text()
        if not motif or self.editeur.isReadOnly():
            return 0
        doc = self.editeur.document()
        curseur = QTextCursor(doc)
        curseur.beginEditBlock()                                            # un seul Ctrl+Z annule tout
        n = 0
        c = doc.find(motif, 0, self._options())
        while not c.isNull():
            c.insertText(self.remplacer.text())
            n += 1
            c = doc.find(motif, c, self._options())
        curseur.endEditBlock()
        self.compte.setText(_("%d remplacé(s)") % n)
        return n
