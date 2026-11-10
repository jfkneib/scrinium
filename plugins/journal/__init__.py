# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Journal » : une entrée par jour avec humeur, calendrier, « il y a un an » (voir `logique.py`). Type non exécutable."""
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCharFormat
from PyQt6.QtWidgets import QCalendarWidget, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


class VueJournal(QWidget):
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True
        self._remplit = False
        self.j = logique.Journal()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        gauche = QVBoxLayout()
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setMaximumWidth(330)
        self.cal.selectionChanged.connect(self._jour_change)
        self.cal.currentPageChanged.connect(lambda *_a: self._marquer())
        gauche.addWidget(self.cal)
        self.b_auj = QPushButton(icone("go-jump-today"), _("Aujourd'hui"))
        self.b_auj.clicked.connect(lambda: self.cal.setSelectedDate(QDate.currentDate()))
        gauche.addWidget(self.b_auj)
        self.l_bilan = QLabel()
        self.l_bilan.setWordWrap(True)
        gauche.addWidget(self.l_bilan)
        gauche.addStretch(1)
        lay.addLayout(gauche)
        droite = QVBoxLayout()
        ligne = QHBoxLayout()
        self.l_jour = QLabel()
        ligne.addWidget(self.l_jour, 1)
        ligne.addWidget(QLabel(_("Humeur")))
        self.humeur = QComboBox()
        self.humeur.addItem("—", 0)
        for n in range(1, 6):
            self.humeur.addItem(logique.HUMEURS[n], n)
        self.humeur.currentIndexChanged.connect(self._ecrit)
        ligne.addWidget(self.humeur)
        droite.addLayout(ligne)
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText(_("Écrivez ici votre journée…"))
        self.texte.textChanged.connect(self._ecrit)
        droite.addWidget(self.texte, 3)
        self.l_passe = QLabel()
        self.l_passe.setWordWrap(True)
        self.l_passe.setTextFormat(Qt.TextFormat.RichText)
        droite.addWidget(self.l_passe, 1)
        lay.addLayout(droite, 1)

    def _jour(self) -> date:
        d = self.cal.selectedDate()
        return date(d.year(), d.month(), d.day())

    def charger(self, texte: str):
        self.j = logique.lire(texte)
        self._afficher_jour()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._marquer()

    def _marquer(self):
        """Jours écrits en gras et soulignés dans le mois affiché."""
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())
        gras = QTextCharFormat()
        gras.setFontWeight(QFont.Weight.Bold)
        gras.setFontUnderline(True)
        for k, e in self.j.entrees.items():
            if e.texte.strip() or e.humeur:
                d = QDate.fromString(k, "yyyy-MM-dd")
                self.cal.setDateTextFormat(d, gras)

    def _jour_change(self):
        self._afficher_jour()

    def _afficher_jour(self):
        jour = self._jour()
        e = self.j.entrees.get(jour.isoformat(), logique.Entree())
        self._remplit = True
        try:
            self.humeur.setCurrentIndex(max(0, self.humeur.findData(e.humeur)))
            self.texte.setPlainText(e.texte)
        finally:
            self._remplit = False
        self.l_jour.setText("<b>%s</b>" % self.cal.selectedDate().toString("dddd d MMMM yyyy"))
        self._bilan(jour)

    def _bilan(self, jour: date):
        auj = date.today()
        s = logique.serie(self.j, auj)
        m = logique.humeur_moyenne(self.j, auj)
        lignes = [_("Jours écrits : %d") % sum(1 for e in self.j.entrees.values() if e.texte.strip())]
        if s:
            lignes.append(_("Série en cours : %d jour(s)") % s)
        if m:
            lignes.append(_("Humeur moyenne (30 jours) : %s sur 5") % str(m).replace(".", ","))
        self.l_bilan.setText("<br>".join(lignes))
        passes = logique.il_y_a(self.j, jour)
        self.l_passe.setText("".join("<p><i>%s</i> %s<br>%s</p>" % (_("Il y a %d an(s), le %s :") % (a, d), logique.HUMEURS[e.humeur],
                                                                  e.texte.strip().replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")[:600])
                                     for a, d, e in passes[:3]))
        self._marquer()

    def _ecrit(self, *_a):
        if self._remplit:
            return
        jour = self._jour()
        logique.definir(self.j, jour.isoformat(), self.humeur.currentData() or 0, self.texte.toPlainText())
        self.modifie.emit(logique.ecrire(self.j))
        self._bilan(jour)


DOC = _(
    "Un journal dans une seule fiche : une entrée par jour, avec une humeur de 1 à 5.\n"
    "\n"
    "• Nouvelle fiche > « Journal » : choisissez un jour dans le calendrier (les jours déjà écrits sont en gras et soulignés), notez votre humeur "
    "et écrivez. « Aujourd'hui » revient au jour courant.\n"
    "• En dessous : « Il y a N an(s) » montre ce que vous écriviez à la même date les années précédentes. À gauche : le nombre de jours écrits, "
    "la série de jours consécutifs et l'humeur moyenne des 30 derniers jours.\n"
    "• Après 18 h, une pastille rouge sur l'icône de la fiche rappelle qu'il n'y a encore rien pour aujourd'hui.\n"
    "• C'est personnel : verrouillez la fiche (bouton « Verrouiller… »). Le texte reste lisible en Markdown, entrée la plus récente en premier.")


class JournalPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Journal"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "view-calendar-day")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueJournal())
