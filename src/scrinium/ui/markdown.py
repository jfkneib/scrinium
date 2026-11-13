# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Mise en forme Markdown des fiches : petits boutons qui écrivent la syntaxe, et aperçu rendu.

Le fichier de la fiche reste du texte Markdown ordinaire (lisible partout) : les boutons ne font qu'insérer
`**gras**`, `# titre`, etc. dans l'éditeur ; l'aperçu n'écrit jamais rien."""
import re
import shlex
import shutil
import subprocess
from urllib.parse import unquote

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QImage, QTextCursor
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QTextBrowser,
                             QToolButton, QVBoxLayout, QWidget)

from ..core import images_texte, liens_fiches
from ..i18n import _
from .entrees_menu import remplir
from .icons import icone

LIENS_AUTORISES = ("http", "https", "mailto")
NAVIGATEURS = ("firefox", "google-chrome", "chromium", "chromium-browser", "brave-browser", "opera", "vivaldi", "microsoft-edge")


def navigateurs_installes() -> list:
    """Commandes de navigateurs courants trouvées dans le PATH."""
    return [n for n in NAVIGATEURS if shutil.which(n)]


def ouvrir_url(url: QUrl, commande: str = "") -> bool:
    """Ouvre l'adresse avec `commande` (ex. « firefox » ou « brave-browser --incognito »), sinon avec le navigateur du système.
    Repli sur le système si la commande est introuvable ou échoue."""
    if commande.strip():
        try:
            argv = shlex.split(commande)
            if argv and shutil.which(argv[0]):
                subprocess.Popen(argv + [url.toString()], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
        except (OSError, ValueError):
            pass
    return QDesktopServices.openUrl(url)


# ---------- opérations sur l'éditeur (une seule étape d'annulation chacune) ----------
def entourer(ed: QPlainTextEdit, marque: str, exemple: str) -> None:
    """Met la sélection entre deux marques (les retire si elles y sont déjà) ; sans sélection, insère un exemple sélectionné."""
    c = ed.textCursor()
    c.beginEditBlock()
    n = len(marque)
    if c.hasSelection():
        t = c.selectedText()
        d, f = c.selectionStart(), c.selectionEnd()
        brut = c.document().toPlainText()
        if len(t) >= 2 * n and t.startswith(marque) and t.endswith(marque):
            c.insertText(t[n:-n])
        elif brut[max(0, d - n):d] == marque and brut[f:f + n] == marque:       # marques juste autour de la sélection
            c.setPosition(f + n)
            c.setPosition(d - n, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(t)
        else:
            c.insertText(marque + t + marque)
    else:
        debut = c.position() + n
        c.insertText(marque + exemple + marque)
        c.setPosition(debut)
        c.setPosition(debut + len(exemple), QTextCursor.MoveMode.KeepAnchor)
    c.endEditBlock()
    ed.setTextCursor(c)


def _lignes_visees(c: QTextCursor) -> tuple:
    d, f = sorted((c.anchor(), c.position()))
    doc = c.document()
    return doc.findBlock(d).blockNumber(), doc.findBlock(f).blockNumber()


def prefixer(ed: QPlainTextEdit, prefixe: str) -> None:
    """Ajoute `prefixe` au début de chaque ligne visée ; le retire si toutes l'ont déjà."""
    c = ed.textCursor()
    premiere, derniere = _lignes_visees(c)
    doc = ed.document()
    blocs = [doc.findBlockByNumber(i) for i in range(premiere, derniere + 1)]
    retirer = all(b.text().startswith(prefixe) for b in blocs)
    c.beginEditBlock()
    for b in blocs:
        k = QTextCursor(b)
        if retirer:
            k.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(prefixe))
            k.removeSelectedText()
        else:
            k.insertText(prefixe)
    c.endEditBlock()


def titre(ed: QPlainTextEdit) -> None:
    """Fait tourner le niveau de titre de la ligne courante : rien -> # -> ## -> ### -> rien."""
    c = ed.textCursor()
    b = c.block()
    m = re.match(r"(#{1,6}) ", b.text())
    niveau = len(m[1]) if m else 0
    k = QTextCursor(b)
    k.beginEditBlock()
    if m:
        k.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, m.end())
        k.removeSelectedText()
    if niveau < 3:
        k.insertText("#" * (niveau + 1) + " ")
    k.endEditBlock()


ADRESSE = re.compile(r"^(?:https?://|mailto:|www\.)\S+$", re.I)


def lien(ed: QPlainTextEdit) -> None:
    """Sélection = adresse (http, https, mailto, www.) : devient `<adresse>` (retiré si déjà ainsi) ; autre sélection ou rien :
    `[texte](https://)`, l'adresse est prête à être remplacée."""
    c = ed.textCursor()
    if c.hasSelection():
        t = c.selectedText().strip()
        if ADRESSE.match(t):
            c.beginEditBlock()
            c.insertText("<" + ("https://" + t if t.lower().startswith("www.") else t) + ">")
            c.endEditBlock()
            ed.setTextCursor(c)
            return
        if len(t) > 2 and t[0] == "<" and t[-1] == ">" and ADRESSE.match(t[1:-1]):      # second clic : on retire
            c.insertText(t[1:-1])
            ed.setTextCursor(c)
            return
    texte = c.selectedText() if c.hasSelection() else _("texte")
    c.beginEditBlock()
    c.insertText(f"[{texte}](https://)")
    fin_url = c.position() - 1
    c.setPosition(fin_url - len("https://"))
    c.setPosition(fin_url, QTextCursor.MoveMode.KeepAnchor)
    c.endEditBlock()
    ed.setTextCursor(c)


def bloc_code(ed: QPlainTextEdit) -> None:
    """Entoure la sélection (ou une ligne vide) de clôtures ``` sur leurs propres lignes."""
    c = ed.textCursor()
    t = c.selectedText().replace(" ", "\n") if c.hasSelection() else ""
    c.beginEditBlock()
    c.insertText("```\n" + t + "\n```")
    if not t:
        c.movePosition(QTextCursor.MoveOperation.Up)
        c.movePosition(QTextCursor.MoveOperation.EndOfLine)
    c.endEditBlock()
    ed.setTextCursor(c)


_FENCE = re.compile(r"^[ \t]*```.*\n?", re.M)
_PREFIXE = re.compile(r"^([ \t]*)(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|>[ \t]?)", re.M)
_LIEN = re.compile(r"(?<!!)\[([^\]\n]*)\]\([^)\n]*\)")
_GRAS = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_ITALIQUE = re.compile(r"(?<![*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![*\w])|(?<![_\w])_(?![\s_])(.+?)(?<![\s_])_(?![_\w])")
_CODE = re.compile(r"`([^`\n]+)`")


def sans_format(texte: str) -> str:
    """Le texte sans syntaxe Markdown : titres, listes, citations, gras, italique, code, liens, clôtures (le contenu reste)."""
    texte = _FENCE.sub("", texte)
    texte = _PREFIXE.sub(r"\1", texte)
    texte = _LIEN.sub(r"\1", texte)
    texte = re.sub(r"<((?:https?://|mailto:)[^\s<>]+)>", r"\1", texte)
    texte = _GRAS.sub(lambda m: m[1] or m[2], texte)
    texte = _ITALIQUE.sub(lambda m: m[1] or m[2], texte)
    return _CODE.sub(r"\1", texte)


def effacer_format(ed: QPlainTextEdit) -> None:
    """Retire la mise en forme de la sélection, ou de la ligne courante s'il n'y a pas de sélection."""
    c = ed.textCursor()
    c.beginEditBlock()
    if not c.hasSelection():
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
    t = c.selectedText().replace("\u2029", "\n")
    c.insertText(sans_format(t))
    c.endEditBlock()
    ed.setTextCursor(c)


# ---------- interface ----------
def lien_fiche(ed: QPlainTextEdit, theme: str, titre: str, doublon: bool = False) -> str:
    """Écrit un lien `[[Titre]]` vers une autre fiche (ou `[[Thème/Titre]]` si deux fiches portent ce titre) ; la sélection, s'il y en a
    une, devient le texte affiché : `[[Titre|sélection]]`. Retourne le texte inséré."""
    c = ed.textCursor()
    cible = f"{theme}/{titre}" if doublon else titre
    sel = " ".join(c.selectedText().replace("\u2029", " ").split()) if c.hasSelection() else ""
    texte = f"[[{cible}|{sel}]]" if sel and sel != titre else f"[[{cible}]]"
    c.insertText(texte)
    ed.setTextCursor(c)
    return texte


def choisir_fiche(parent, cibles: list):
    """Boîte « lien vers une fiche » : liste filtrable des fiches ; retourne (thème, titre) ou None."""
    d = QDialog(parent)
    d.setWindowTitle(_("Lien vers une fiche"))
    d.resize(420, 380)
    lay = QVBoxLayout(d)
    lay.addWidget(QLabel(_("Choisissez la fiche vers laquelle pointer :")))
    filtre = QLineEdit()
    filtre.setPlaceholderText(_("Chercher une fiche"))
    filtre.setClearButtonEnabled(True)
    lay.addWidget(filtre)
    liste = QListWidget()
    lay.addWidget(liste, 1)
    for th, ti in cibles:
        liste.addItem(f"{th} / {ti}")

    def maj(*_a):
        q = filtre.text().strip().casefold()
        premier = None
        for i, (th, ti) in enumerate(cibles):
            visible = q in f"{th} {ti}".casefold()
            liste.item(i).setHidden(not visible)
            if visible and premier is None:
                premier = i
        if premier is not None:
            liste.setCurrentRow(premier)
    filtre.textChanged.connect(maj)
    filtre.returnPressed.connect(d.accept)
    liste.itemDoubleClicked.connect(lambda *_a: d.accept())
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    maj()
    filtre.setFocus()
    if d.exec() != QDialog.DialogCode.Accepted or liste.currentRow() < 0 or liste.currentItem().isHidden():
        return None
    return cibles[liste.currentRow()]


class BarreFormat(QWidget):
    """Rangée de petits boutons de mise en forme + bouton « Aperçu » (bascule édition / lecture)."""
    apercu_demande = pyqtSignal(bool)

    def __init__(self, editeur: QPlainTextEdit, parent=None):
        super().__init__(parent)
        self.ed = editeur
        self.fiches_cibles = lambda: []            # [(thème, titre)] des fiches qu'un lien peut viser (donné par la fenêtre)
        self.choisir_image = lambda: None          # ouvre le choix d'une image (donné par la fenêtre)
        self.lecture_seule = False                 # vrai : les boutons d'écriture restent grisés, même hors aperçu
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.boutons = []
        for texte, astuce, fn, style in (
                ("B", _("Gras (Ctrl+B)"), lambda: entourer(self.ed, "**", _("gras")), "font-weight: bold;"),
                ("I", _("Italique (Ctrl+I)"), lambda: entourer(self.ed, "*", _("italique")), "font-style: italic;"),
                ("H", _("Titre (clics successifs : #, ##, ###, aucun)"), lambda: titre(self.ed), "font-weight: bold;"),
                ("•", _("Liste à puces"), lambda: prefixer(self.ed, "- "), ""),
                ("1.", _("Liste numérotée"), lambda: prefixer(self.ed, "1. "), ""),
                ("❝", _("Citation"), lambda: prefixer(self.ed, "> "), ""),
                ("</>", _("Code (dans la ligne)"), lambda: entourer(self.ed, "`", _("code")), "font-family: monospace;"),
                ("{ }", _("Bloc de code"), lambda: bloc_code(self.ed), "font-family: monospace;"),
                ("🔗", _("Lien web (http, https, mailto)"), lambda: lien(self.ed), ""),
                ("[[ ]]", _("Lien vers une autre fiche"), lambda: self._lien_fiche(), "font-family: monospace;"),
                ("🖼", _("Insérer une image dans le texte"), lambda: self.choisir_image(), ""),
                ("Tx", _("Effacer la mise en forme (sélection ou ligne)"), lambda: effacer_format(self.ed), "")):
            b = QToolButton()
            b.setText(texte)
            b.setToolTip(astuce)
            b.setAutoRaise(True)
            if style:
                b.setStyleSheet(style)
            b.clicked.connect(lambda _c=False, f=fn: f())
            lay.addWidget(b)
            self.boutons.append(b)
        lay.addStretch()
        self.b_apercu = QToolButton()
        self.b_apercu.setText(_("Aperçu"))
        self.b_apercu.setToolTip(_("Afficher la fiche mise en forme (Ctrl+E) ; ne modifie rien"))
        self.b_apercu.setCheckable(True)
        self.b_apercu.toggled.connect(self.apercu_demande.emit)
        lay.addWidget(self.b_apercu)

    def _lien_fiche(self) -> None:
        cibles = list(self.fiches_cibles())
        if not cibles:
            QMessageBox.information(self, _("Lien vers une fiche"), _("Il n'y a pas d'autre fiche vers laquelle pointer."))
            return
        choix = choisir_fiche(self, cibles)
        if choix is not None:
            theme, titre = choix
            lien_fiche(self.ed, theme, titre, sum(1 for _t, x in cibles if x.casefold() == titre.casefold()) > 1)
            self.ed.setFocus()

    def definir_apercu(self, actif: bool) -> None:
        """Pendant l'aperçu, les boutons d'écriture sont grisés."""
        for b in self.boutons:
            b.setEnabled(not actif and not self.lecture_seule)
        if self.b_apercu.isChecked() != actif:
            self.b_apercu.setChecked(actif)


class Apercu(QTextBrowser):
    """Rendu en lecture seule. Seuls les liens http, https et mailto s'ouvrent (dans le navigateur du système)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.navigateur = lambda: ""             # renvoie la commande choisie (réglage « navigateur »), vide = système
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._lien)
        self.fiche_existe = None                 # cible -> bool : une fiche porte ce titre (sinon le lien est marqué ✚)
        self.image_piece = lambda n: None        # n° de pièce -> octets de l'image (donné par la fenêtre) ; pour ![](pj:N)

    pdf_demande = pyqtSignal()
    impression_demandee = pyqtSignal()
    fiche_demandee = pyqtSignal(str)             # clic sur un lien [[fiche]] : la cible (titre ou « Thème/Titre »)
    complements = staticmethod(lambda: [])       # voir images.Editeur

    def contextMenuEvent(self, ev):
        m = self.createStandardContextMenu()
        m.addSeparator()
        remplir(m, self.complements())
        m.addAction(icone("document-print"), _("Imprimer…"), self.impression_demandee.emit)
        m.addAction(_("Exporter la fiche en PDF…"), self.pdf_demande.emit)
        m.exec(ev.globalPos())
        m.deleteLater()

    def _lien(self, url: QUrl) -> None:
        if url.scheme().lower() == liens_fiches.SCHEMA:
            self.fiche_demandee.emit(unquote(url.toString().partition(":")[2]))
            return
        if url.scheme().lower() not in LIENS_AUTORISES:
            return
        ouvrir_url(url, self.navigateur() if url.scheme().lower() != "mailto" else "")

    def loadResource(self, type_, url):
        """Seules les images `pj:N` (pièces de la fiche) sont chargées, réduites à la largeur visible ; rien d'autre (ni disque, ni réseau)."""
        if url.scheme().lower() != images_texte.SCHEMA:
            return None
        try:
            donnees = self.image_piece(int(url.path()))
        except (ValueError, OSError):
            donnees = None
        img = QImage.fromData(donnees) if donnees else QImage()
        if img.isNull():
            return None
        largeur = max(self.viewport().width() - 30, 100)
        if img.width() > largeur:
            img = img.scaledToWidth(largeur, Qt.TransformationMode.SmoothTransformation)
        return img

    def afficher(self, texte: str) -> None:
        barre = self.verticalScrollBar().value()
        self.setMarkdown(liens_fiches.vers_markdown(texte, self.fiche_existe))
        self.verticalScrollBar().setValue(barre)
