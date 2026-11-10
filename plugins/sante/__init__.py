# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Santé » : tension (courbe, moyennes, repères) et traitement (prises à cocher, pastille si une prise est oubliée) — voir `logique.py`.
Un carnet, pas un avis médical. Type non exécutable : la fiche ne lance rien."""
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, QPointF, QRectF, Qt, QTime, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                             QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


class Courbe(QWidget):
    """Haute et basse au fil des jours, avec les repères 140 et 90 (pointillés), dessinées à la main."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mesures: list = []
        self.setMinimumHeight(150)

    def definir(self, mesures: list):
        self.mesures = mesures
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        texte = self.palette().color(QPalette.ColorRole.WindowText)
        gris = QColor(texte)
        gris.setAlpha(70)
        g, d, h, b = 40, 12, 20, 20
        zone = QRectF(g, h, max(10, self.width() - g - d), max(10, self.height() - h - b))
        p.setPen(texte)
        p.drawText(QPointF(4, 14), _("Tension (haute et basse)"))
        if len(self.mesures) < 1:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("Pas encore de mesures"))
            return
        ms = sorted(self.mesures, key=lambda m: (m.jour, m.heure))
        xs = [date.fromisoformat(m.jour).toordinal() + (int(m.heure[:2]) / 24 if m.heure else 0.5) for m in ms]
        x0, x1 = min(xs), max(xs)
        if x1 == x0:
            x0, x1 = x0 - 1, x1 + 1
        y0 = max(40, min(min(m.basse for m in ms), 70) - 10)
        y1 = max(max(m.haute for m in ms), 150) + 10

        def X(v):
            return zone.left() + 6 + (v - x0) / (x1 - x0) * (zone.width() - 12)

        def Y(v):
            return zone.bottom() - (v - y0) / (y1 - y0) * zone.height()
        fm = QFontMetrics(self.font())
        for v in range(int(y0 // 20 + 1) * 20, int(y1), 20):
            p.setPen(QPen(gris, 1))
            p.drawLine(QPointF(zone.left(), Y(v)), QPointF(zone.right(), Y(v)))
            p.setPen(texte)
            p.drawText(QPointF(zone.left() - fm.horizontalAdvance(str(v)) - 4, Y(v) + fm.ascent() / 2 - 1), str(v))
        p.setPen(QPen(QColor("#c0392b"), 1.2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(zone.left(), Y(140)), QPointF(zone.right(), Y(140)))
        p.drawLine(QPointF(zone.left(), Y(90)), QPointF(zone.right(), Y(90)))
        p.setPen(texte)
        for v, alig in ((x0, 0), (x1, 1)):
            e = date.fromordinal(int(v)).strftime("%d/%m")
            p.drawText(QPointF(X(v) - (fm.horizontalAdvance(e) if alig else 0), self.height() - 5), e)
        for valeurs, couleur in (([m.haute for m in ms], "#2f6fdb"), ([m.basse for m in ms], "#e67e22")):
            pts = [QPointF(X(x), Y(v)) for x, v in zip(xs, valeurs)]
            p.setPen(QPen(QColor(couleur), 2))
            for a, c in zip(pts, pts[1:]):
                p.drawLine(a, c)
            p.setBrush(QColor(couleur))
            for pt in pts:
                p.drawEllipse(pt, 3, 3)


class DialogueMedicament(QDialog):
    def __init__(self, x=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Médicament"))
        self.resize(420, 260)
        f = QFormLayout(self)
        self.nom = QLineEdit(x.nom if x else "")
        self.dose = QLineEdit(x.dose if x else "")
        self.dose.setPlaceholderText(_("1 comprimé"))
        self.horaires = QLineEdit(", ".join(x.horaires) if x else "08:00")
        self.horaires.setPlaceholderText("08:00, 20:00")
        self.debut = self._date(x.debut if x else "")
        self.fin = self._date(x.fin if x else "")
        self.note = QLineEdit(x.note if x else "")
        for t, w in ((_("Médicament :"), self.nom), (_("Dose :"), self.dose), (_("Horaires :"), self.horaires), (_("Du :"), self.debut),
                     (_("Au (facultatif) :"), self.fin), (_("Note :"), self.note)):
            f.addRow(t, w)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    @staticmethod
    def _date(v: str) -> QDateEdit:
        w = QDateEdit(QDate.fromString(v, "yyyy-MM-dd") if v else QDate(1900, 1, 1))
        w.setMinimumDate(QDate(1900, 1, 1))
        w.setSpecialValueText(" ")
        w.setCalendarPopup(True)
        return w

    def _valider(self):
        if self.nom.text().strip():
            self.accept()
        else:
            self.nom.setFocus()
            QMessageBox.warning(self, self.windowTitle(), _("Le nom est vide : saisissez-le avant de valider."))

    def resultat(self):
        j = lambda w: "" if w.date() <= QDate(1900, 1, 1) else w.date().toString("yyyy-MM-dd")          # noqa: E731
        return logique.Medicament(" ".join(self.nom.text().split())[:80], self.dose.text().strip()[:40], logique.lire_horaires(self.horaires.text()),
                                  j(self.debut), j(self.fin), self.note.text().strip()[:200])


class VueSante(QWidget):
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True
        self.d = logique.Document()
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.onglets = QTabWidget()
        lay.addWidget(self.onglets, 1)
        self.onglets.addTab(self._onglet_tension(), icone("health"), _("Tension"))
        self.onglets.addTab(self._onglet_traitement(), icone("view-task"), _("Traitement"))
        av = QLabel(_("Un carnet, pas un avis médical : les couleurs sont des repères indicatifs. Données de santé : verrouillez la fiche."))
        av.setWordWrap(True)
        lay.addWidget(av)

    # ---------- tension ----------
    def _onglet_tension(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        ligne = QHBoxLayout()
        self.jour = QDateEdit(QDate.currentDate())
        self.jour.setCalendarPopup(True)
        self.heure = QTimeEdit(QTime.currentTime())
        self.heure.setDisplayFormat("HH:mm")
        self.haute = QSpinBox()
        self.haute.setRange(0, 300)
        self.haute.setSpecialValueText(" ")
        self.basse = QSpinBox()
        self.basse.setRange(0, 200)
        self.basse.setSpecialValueText(" ")
        self.pouls = QSpinBox()
        self.pouls.setRange(0, 250)
        self.pouls.setSpecialValueText(" ")
        self.note_t = QLineEdit()
        self.note_t.setPlaceholderText(_("note (facultatif)"))
        for t, x in ((_("Le"), self.jour), (_("à"), self.heure), (_("Haute"), self.haute), (_("Basse"), self.basse), (_("Pouls"), self.pouls)):
            ligne.addWidget(QLabel(t))
            ligne.addWidget(x)
        ligne.addWidget(self.note_t, 1)
        self.b_mesure = QPushButton(icone("list-add"), _("Mesure"))
        self.b_mesure.clicked.connect(self._ajouter_mesure)
        ligne.addWidget(self.b_mesure)
        lay.addLayout(ligne)
        self.l_bilan_t = QLabel()
        self.l_bilan_t.setWordWrap(True)
        self.l_bilan_t.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_bilan_t)
        self.courbe = Courbe()
        lay.addWidget(self.courbe, 1)
        self.t_mesures = QTableWidget(0, 7)
        self.t_mesures.setHorizontalHeaderLabels([_("Date"), _("Heure"), _("Haute"), _("Basse"), _("Pouls"), _("Repère"), _("Note")])
        self.t_mesures.verticalHeader().setVisible(False)
        self.t_mesures.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.t_mesures.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_mesures.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_mesures.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_mesures.customContextMenuRequested.connect(self._menu_mesure)
        lay.addWidget(self.t_mesures, 1)
        return w

    def _ajouter_mesure(self):
        h, b = self.haute.value(), self.basse.value()
        if not logique.mesure_valide(h, b):
            QMessageBox.warning(self, _("Mesure"), _("Saisissez une tension plausible : la haute (50 à 300) doit dépasser la basse (30 à 200)."))
            return
        self.d.mesures.append(logique.Mesure(self.jour.date().toString("yyyy-MM-dd"), self.heure.time().toString("HH:mm"), h, b, self.pouls.value(),
                                             self.note_t.text().strip()[:200]))
        self.haute.setValue(0)
        self.basse.setValue(0)
        self.pouls.setValue(0)
        self.note_t.clear()
        self._enregistrer()

    def _menu_mesure(self, pos):
        i = self.t_mesures.rowAt(pos.y())
        if i >= 0:
            m = QMenu(self)
            m.addAction(icone("edit-delete"), _("Supprimer cette mesure"), lambda: self._supprimer_mesure(i))
            m.exec(self.t_mesures.viewport().mapToGlobal(pos))

    def _supprimer_mesure(self, i: int):
        if 0 <= i < len(self._mesures_triees):
            cible = self._mesures_triees[i]
            self.d.mesures = [x for x in self.d.mesures if x is not cible]
            self._enregistrer()

    # ---------- traitement ----------
    def _onglet_traitement(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.l_jour = QLabel()
        lay.addWidget(self.l_jour)
        self.t_prises = QTableWidget(0, 4)
        self.t_prises.setHorizontalHeaderLabels([_("Pris"), _("Heure"), _("Médicament"), _("Dose")])
        self.t_prises.verticalHeader().setVisible(False)
        self.t_prises.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.t_prises.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_prises.itemChanged.connect(self._prise_cochee)
        lay.addWidget(self.t_prises, 1)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("<b>%s</b>" % _("Médicaments")), 1)
        b = QPushButton(icone("list-add"), _("Ajouter un médicament…"))
        b.clicked.connect(self._ajouter_med)
        ligne.addWidget(b)
        lay.addLayout(ligne)
        self.t_meds = QTableWidget(0, 6)
        self.t_meds.setHorizontalHeaderLabels([_("Médicament"), _("Dose"), _("Horaires"), _("Du"), _("Au"), _("Note")])
        self.t_meds.verticalHeader().setVisible(False)
        self.t_meds.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.t_meds.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_meds.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_meds.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_meds.customContextMenuRequested.connect(self._menu_med)
        self.t_meds.doubleClicked.connect(lambda i: self._modifier_med(i.row()))
        lay.addWidget(self.t_meds, 1)
        return w

    def _prise_cochee(self, it):
        if self._remplit or it.column() != 0:
            return
        h, nom = self.t_prises.item(it.row(), 1).text(), self.t_prises.item(it.row(), 2).text()
        pris = it.checkState() == Qt.CheckState.Checked
        courant = (date.today().isoformat(), h, nom) in self.d.prises
        if pris != courant:
            logique.basculer_prise(self.d, date.today(), h, nom)
            self._enregistrer()

    def _ajouter_med(self):
        d = DialogueMedicament(None, self)
        if d.exec() and len(self.d.medicaments) < logique.MAX_MEDICAMENTS:
            self.d.medicaments.append(d.resultat())
            self._enregistrer()

    def _modifier_med(self, i: int):
        if 0 <= i < len(self.d.medicaments):
            d = DialogueMedicament(self.d.medicaments[i], self)
            if d.exec():
                self.d.medicaments[i] = d.resultat()
                self._enregistrer()

    def _supprimer_med(self, i: int):
        if 0 <= i < len(self.d.medicaments):
            del self.d.medicaments[i]
            self._enregistrer()

    def _menu_med(self, pos):
        i = self.t_meds.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _("Ajouter un médicament…"), self._ajouter_med)
        if i >= 0:
            m.addAction(icone("document-edit"), _("Modifier…"), lambda: self._modifier_med(i))
            m.addAction(icone("edit-delete"), _("Supprimer"), lambda: self._supprimer_med(i))
        m.exec(self.t_meds.viewport().mapToGlobal(pos))

    # ---------- commun ----------
    def charger(self, texte: str):
        self.d = logique.lire(texte)
        self._afficher()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._afficher()                                   # le jour a pu changer

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.d))
        self._afficher()

    def _afficher(self):
        auj = date.today()
        self._remplit = True
        try:
            self._mesures_triees = sorted(self.d.mesures, key=lambda m: (m.jour, m.heure), reverse=True)
            self.t_mesures.setRowCount(len(self._mesures_triees))
            for i, m in enumerate(self._mesures_triees):
                cat = logique.categorie(m.haute, m.basse)
                for c, v in enumerate((QDate.fromString(m.jour, "yyyy-MM-dd").toString("dd/MM/yyyy"), m.heure, str(m.haute), str(m.basse),
                                       str(m.pouls or ""), _(logique.LIBELLES[cat]), m.note)):
                    it = QTableWidgetItem(v)
                    if c in (2, 3, 5):
                        it.setBackground(QBrush(QColor(logique.COULEURS[cat])))
                        it.setForeground(QBrush(QColor("#1b1b1b")))
                    self.t_mesures.setItem(i, c, it)
            self.t_mesures.resizeColumnsToContents()
            self.t_mesures.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
            self.courbe.definir([m for m in self.d.mesures if (auj - date.fromisoformat(m.jour)).days < 90])
            if self._mesures_triees:
                m = self._mesures_triees[0]
                txt = _("Dernière mesure : <b>%(h)d/%(b)d</b> (%(c)s)") % {"h": m.haute, "b": m.basse, "c": _(logique.LIBELLES[logique.categorie(m.haute, m.basse)])}
                moy = logique.moyenne(self.d.mesures, auj)
                if moy:
                    txt += " · " + _("moyenne sur 30 jours : <b>%(h)d/%(b)d</b>") % {"h": moy[0], "b": moy[1]} + (_(", pouls %d") % moy[2] if moy[2] else "")
            else:
                txt = _("Saisissez une première mesure ci-dessus.")
            self.l_bilan_t.setText(txt)
            prises = logique.prises_du_jour(self.d, auj)
            self.l_jour.setText("<b>%s</b>" % (_("Aujourd'hui : %s") % QDate.currentDate().toString("dddd d MMMM")) +
                                ("" if prises else " — " + _("aucune prise prévue (ajoutez un médicament avec ses horaires).")))
            self.t_prises.setRowCount(len(prises))
            retard = {(h, n) for h, n, _d in logique.en_retard(self.d, datetime.now())}
            for i, (h, nom, dose, pris) in enumerate(prises):
                case = QTableWidgetItem()
                case.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                case.setCheckState(Qt.CheckState.Checked if pris else Qt.CheckState.Unchecked)
                self.t_prises.setItem(i, 0, case)
                for c, v in enumerate((h, nom, dose), 1):
                    it = QTableWidgetItem(v)
                    if (h, nom) in retard:
                        it.setBackground(QBrush(QColor("#ffb3a0")))
                        it.setForeground(QBrush(QColor("#1b1b1b")))
                    self.t_prises.setItem(i, c, it)
            self.t_prises.resizeColumnsToContents()
            self.t_prises.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.t_meds.setRowCount(len(self.d.medicaments))
            for i, x in enumerate(self.d.medicaments):
                for c, v in enumerate((x.nom, x.dose, ", ".join(x.horaires), x.debut, x.fin, x.note)):
                    self.t_meds.setItem(i, c, QTableWidgetItem(v))
            self.t_meds.resizeColumnsToContents()
            self.t_meds.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        finally:
            self._remplit = False


DOC = _(
    "Un carnet de tension et de traitement dans une fiche. Ce n'est pas un avis médical.\n"
    "\n"
    "• Onglet « Tension » : saisissez la date, l'heure, la haute, la basse et le pouls, puis « Mesure ». La courbe montre les 90 derniers jours "
    "(pointillés rouges : 140 et 90) ; la moyenne des 30 jours est en haut. Chaque mesure reçoit un repère de couleur (optimale, normale, normale haute, "
    "élevée grade 1, 2, 3) d'après les classes usuelles : indicatif, à discuter avec votre médecin.\n"
    "• Onglet « Traitement » : ajoutez chaque médicament avec sa dose et ses horaires (08:00, 20:00), éventuellement des dates de début et de fin. "
    "La liste du jour affiche une case « Pris » par prise ; une prise non cochée 30 minutes après son heure passe en rouge.\n"
    "• Une pastille rouge sur l'icône de la fiche signale une prise oubliée.\n"
    "• Ce sont des données de santé : verrouillez la fiche (bouton « Verrouiller… »). Le texte reste lisible en Markdown, rien n'est exécuté.")


class SantePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Santé"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "health")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueSante())
