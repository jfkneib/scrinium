# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Planning » : des tâches en couleurs sur un diagramme de Gantt, l'avancement, un rétroplanning (voir `logique.py`).

- Une fiche « Planning » = un planning. En haut, le diagramme : une barre par tâche (couleur = catégorie, remplissage = avancement), un
  losange pour un jalon, des flèches pour les dépendances (« Après »), un trait rouge pour aujourd'hui, un trait pointillé pour la fin du projet.
  On déplace une barre à la souris (glisser) ou on la rallonge en tirant son bord droit. En dessous, le tableau des tâches (cellules modifiables).
- « Calculer les dates » : en avant d'une date de début, ou À REBOURS d'une date de fin (rétroplanning). Les durées et les dépendances sont gardées.
- Le texte reste un tableau Markdown ; type non exécutable : la fiche ne lance rien."""
from datetime import date, timedelta

from PyQt6.QtCore import QLocale, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                             QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTableWidget,
                             QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

ROUGE = QColor("#c0392b")
ZOOMS = [("jour", 26), ("semaine", 9), ("mois", 3)]          # (nom, pixels par jour)
LARGEUR_NOMS, HAUT_ENTETE, HAUT_LIGNE = 210, 40, 28


def _nom_mois(d: date) -> str:
    n = QLocale().monthName(d.month, QLocale.FormatType.LongFormat)
    return f"{n[:1].upper()}{n[1:]} {d.year}"


class Gantt(QWidget):
    """Le diagramme. Il ne modifie rien lui-même : il émet `choisie(i)`, `deplacee(i, jours)` ou `redimensionnee(i, jours)`."""
    choisie = pyqtSignal(int)
    deplacee = pyqtSignal(int, int)
    redimensionnee = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.p = logique.Planning()
        self.px = ZOOMS[1][1]
        self.aujourdhui = date.today()
        self.selection = -1
        self.decalage = 0                        # défilement horizontal : la colonne des noms reste visible
        self._geom: dict = {}                    # indice de tâche -> rectangle de sa barre (hors décalage de la colonne des noms)
        self._drag = None                        # (mode, indice, x de départ, jours)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._recalculer()

    # ---------- géométrie ----------
    def _bornes(self) -> tuple:
        ds = [logique._d(t.debut) for t in self.p.taches if t.planifiee]
        fs = [logique._d(logique.fin_effective(t)) for t in self.p.taches if t.planifiee]
        if self.p.fin:
            fs.append(logique._d(self.p.fin))
        ds.append(self.aujourdhui)
        fs.append(self.aujourdhui)
        return min(ds) - timedelta(days=7), max(fs) + timedelta(days=14)

    def _recalculer(self):
        self.d0, self.d1 = self._bornes()
        self.jours = (self.d1 - self.d0).days + 1
        self.setMinimumSize(LARGEUR_NOMS + self.jours * self.px + 20, HAUT_ENTETE + max(1, len(self.p.taches)) * HAUT_LIGNE + 10)
        self.update()

    def definir(self, p: logique.Planning, aujourdhui: date | None = None, selection: int = -1):
        self.p, self.selection = p, selection
        self.aujourdhui = aujourdhui or date.today()
        self._recalculer()

    def zoomer(self, px: int):
        self.px = px
        self._recalculer()

    def _x(self, d: date) -> float:
        return LARGEUR_NOMS + (d - self.d0).days * self.px

    def _rect(self, i: int):
        t = self.p.taches[i]
        if not t.planifiee:
            return None
        y = HAUT_ENTETE + i * HAUT_LIGNE
        a = self._x(logique._d(t.debut))
        b = self._x(logique._d(logique.fin_effective(t))) + self.px
        return QRectF(a, y + 5, max(b - a, 6), HAUT_LIGNE - 10)

    # ---------- dessin ----------
    def paintEvent(self, _ev):
        g = QPainter(self)
        g.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        fond, texte, gris = pal.base().color(), pal.text().color(), pal.mid().color()
        alt = pal.alternateBase().color()
        g.fillRect(self.rect(), fond)
        n = len(self.p.taches)
        for i in range(n):
            if i % 2:
                g.fillRect(QRectF(0, HAUT_ENTETE + i * HAUT_LIGNE, self.width(), HAUT_LIGNE), alt)
        # week-ends et graduations
        police = g.font()
        for k in range(self.jours):
            d = self.d0 + timedelta(days=k)
            x = self._x(d)
            if self.px >= 9 and d.weekday() >= 5:
                c = QColor(gris)
                c.setAlpha(40)
                g.fillRect(QRectF(x, HAUT_ENTETE, self.px, n * HAUT_LIGNE), c)
            if d.day == 1 or k == 0:
                if d.day == 1:
                    g.setPen(QPen(gris, 1))
                    g.drawLine(QPointF(x, 0), QPointF(x, HAUT_ENTETE + n * HAUT_LIGNE))
                g.setPen(texte)
                g.drawText(QRectF(x + 3, 0, 200, 18), Qt.AlignmentFlag.AlignVCenter, _nom_mois(d))
            elif (self.px >= 20) or (self.px >= 8 and d.weekday() == 0):
                c = QColor(gris)
                c.setAlpha(90)
                g.setPen(QPen(c, 1))
                g.drawLine(QPointF(x, 18), QPointF(x, HAUT_ENTETE + n * HAUT_LIGNE))
            if self.px >= 20:
                g.setPen(texte)
                g.drawText(QRectF(x, 18, self.px, 20), Qt.AlignmentFlag.AlignCenter, str(d.day))
            elif self.px >= 8 and d.weekday() == 0:
                g.setPen(texte)
                g.drawText(QRectF(x + 2, 18, 40, 20), Qt.AlignmentFlag.AlignVCenter, str(d.day))
        g.setPen(QPen(gris, 1))
        g.drawLine(QPointF(0, HAUT_ENTETE), QPointF(self.width(), HAUT_ENTETE))
        # fin du projet et aujourd'hui
        if self.p.fin:
            x = self._x(logique._d(self.p.fin)) + self.px
            g.setPen(QPen(QColor("#2c3e50") if fond.lightness() > 128 else QColor("#ecf0f1"), 1.5, Qt.PenStyle.DashLine))
            g.drawLine(QPointF(x, 0), QPointF(x, HAUT_ENTETE + n * HAUT_LIGNE))
            g.drawText(QRectF(x + 3, 0, 120, 18), Qt.AlignmentFlag.AlignVCenter, _("Fin"))
        xa = self._x(self.aujourdhui) + self.px / 2
        g.setPen(QPen(ROUGE, 1.5))
        g.drawLine(QPointF(xa, 16), QPointF(xa, HAUT_ENTETE + n * HAUT_LIGNE))
        # barres
        self._geom = {}
        for i, t in enumerate(self.p.taches):
            r = self._rect(i)
            if r is None:
                continue
            dx = 0
            if self._drag and self._drag[1] == i:
                dx = self._drag[3] * self.px
                r = QRectF(r.x() + dx, r.y(), r.width(), r.height()) if self._drag[0] == "deplace" else \
                    QRectF(r.x(), r.y(), max(self.px, r.width() + dx), r.height())
            self._geom[i] = r
            self._barre(g, i, t, r, i == self.selection)
        # dépendances
        g.setPen(QPen(gris, 1.2))
        for j, i in logique.dependances(self.p):
            a, b = self._geom.get(j), self._geom.get(i)
            if a is None or b is None:
                continue
            x1, y1, x2, y2 = a.right(), a.center().y(), b.left(), b.center().y()
            xm = max(x1 + 6, min(x2 - 6, x1 + 6))
            g.drawPolyline(QPolygonF([QPointF(x1, y1), QPointF(xm, y1), QPointF(xm, y2), QPointF(x2 - 1, y2)]))
            g.setBrush(gris)
            g.drawPolygon(QPolygonF([QPointF(x2, y2), QPointF(x2 - 5, y2 - 3), QPointF(x2 - 5, y2 + 3)]))
            g.setBrush(Qt.BrushStyle.NoBrush)
        # colonne des noms (fixe : suit le défilement)
        x0 = self.decalage
        g.fillRect(QRectF(x0, 0, LARGEUR_NOMS, self.height()), fond)
        g.setPen(QPen(gris, 1))
        g.drawLine(QPointF(x0 + LARGEUR_NOMS, 0), QPointF(x0 + LARGEUR_NOMS, self.height()))
        g.drawLine(QPointF(x0, HAUT_ENTETE), QPointF(x0 + LARGEUR_NOMS, HAUT_ENTETE))
        fm = QFontMetrics(police)
        for i, t in enumerate(self.p.taches):
            y = HAUT_ENTETE + i * HAUT_LIGNE
            if i == self.selection:
                c = QColor(pal.highlight().color())
                c.setAlpha(60)
                g.fillRect(QRectF(x0, y, LARGEUR_NOMS, HAUT_LIGNE), c)
            elif i % 2:
                g.fillRect(QRectF(x0, y, LARGEUR_NOMS, HAUT_LIGNE), alt)
            g.setPen(ROUGE if logique.etat(t, self.aujourdhui) == "retard" else texte)
            g.drawText(QRectF(x0 + 6, y, LARGEUR_NOMS - 12, HAUT_LIGNE), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(t.nom, Qt.TextElideMode.ElideRight, LARGEUR_NOMS - 12))
        g.end()

    def _barre(self, g: QPainter, i: int, t: logique.Tache, r: QRectF, choisie: bool):
        coul = QColor(logique.couleur(self.p, t.categorie))
        etat = logique.etat(t, self.aujourdhui)
        if t.jalon:
            c = r.center()
            h = (r.height() - 2) / 2
            g.setBrush(coul)
            g.setPen(QPen(ROUGE if etat == "retard" else coul.darker(150), 2 if (etat == "retard" or choisie) else 1))
            g.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - h), QPointF(c.x() + h, c.y()), QPointF(c.x(), c.y() + h), QPointF(c.x() - h, c.y())]))
            return
        clair = QColor(coul)
        clair.setAlpha(70)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(clair)
        g.drawRoundedRect(r, 4, 4)
        if t.pourcent > 0:
            g.setBrush(coul)
            g.drawRoundedRect(QRectF(r.x(), r.y(), r.width() * min(100, t.pourcent) / 100, r.height()), 4, 4)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(QPen(ROUGE if etat == "retard" else coul.darker(130), 2 if (etat == "retard" or choisie) else 1))
        g.drawRoundedRect(r, 4, 4)
        if t.pourcent and r.width() > 38:
            g.setPen(QColor("white") if t.pourcent >= 55 else self.palette().text().color())
            g.drawText(r.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{t.pourcent} %")

    # ---------- souris ----------
    def _sous(self, pos) -> tuple:
        """(indice, zone) sous le curseur : zone « bord » (bord droit d'une barre), « barre » ou « ligne »."""
        i = int((pos.y() - HAUT_ENTETE) // HAUT_LIGNE)
        if not 0 <= i < len(self.p.taches) or pos.y() < HAUT_ENTETE:
            return -1, ""
        r = self._geom.get(i)
        if r is not None and pos.x() > self.decalage + LARGEUR_NOMS and r.adjusted(-2, -3, 2, 3).contains(QPointF(pos)):
            if not self.p.taches[i].jalon and pos.x() >= r.right() - 6:
                return i, "bord"
            return i, "barre"
        return i, "ligne"

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        i, zone = self._sous(ev.position())
        if i < 0:
            return
        self.selection = i
        self.choisie.emit(i)
        if zone in ("barre", "bord"):
            self._drag = ("deplace" if zone == "barre" else "etire", i, ev.position().x(), 0)
        self.update()

    def mouseMoveEvent(self, ev):
        if self._drag:
            mode, i, x0, _j = self._drag
            self._drag = (mode, i, x0, round((ev.position().x() - x0) / self.px))
            self.update()
            return
        _i, zone = self._sous(ev.position())
        self.setCursor(QCursor({"bord": Qt.CursorShape.SizeHorCursor, "barre": Qt.CursorShape.OpenHandCursor}.get(zone, Qt.CursorShape.ArrowCursor)))

    def mouseReleaseEvent(self, ev):
        if self._drag and ev.button() == Qt.MouseButton.LeftButton:
            mode, i, _x, jours = self._drag
            self._drag = None
            self.update()
            if jours:
                (self.deplacee if mode == "deplace" else self.redimensionnee).emit(i, jours)


class VuePlanning(QWidget):
    """Vue du type « planning » : saisie rapide, diagramme de Gantt, tableau des tâches, bilan."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                        # type non exécutable : toujours utilisable
        self.p = logique.Planning()
        self.aujourdhui = date.today()
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        # saisie rapide
        saisie = QHBoxLayout()
        self.e_nom = QLineEdit()
        self.e_nom.setPlaceholderText(_("Nouvelle tâche"))
        self.e_nom.returnPressed.connect(self.ajouter)
        self.e_debut = QLineEdit()
        self.e_debut.setFixedWidth(95)
        self.e_debut.setPlaceholderText(_("Début"))
        self.e_jours = QSpinBox()
        self.e_jours.setRange(0, 3650)
        self.e_jours.setValue(1)
        self.e_jours.setSuffix(" " + _("j"))
        self.e_jours.setToolTip(_("Durée en jours (0 = un jalon, une date sans durée)"))
        self.c_cat = QComboBox()
        self.c_cat.setEditable(True)
        self.c_cat.setMinimumWidth(110)
        self.c_cat.lineEdit().setPlaceholderText(_("Catégorie"))
        self.b_ajouter = QPushButton(icone("list-add"), _("Ajouter"))
        self.b_ajouter.clicked.connect(lambda *_a: self.ajouter())
        for w, etire in ((self.e_nom, 1), (self.e_debut, 0), (self.e_jours, 0), (self.c_cat, 0), (self.b_ajouter, 0)):
            saisie.addWidget(w, etire)
        lay.addLayout(saisie)
        # barre d'outils
        outils = QHBoxLayout()
        outils.addWidget(QLabel(_("Fin du projet")))
        self.e_fin = QLineEdit()
        self.e_fin.setFixedWidth(95)
        self.e_fin.setPlaceholderText(_("aucune"))
        self.e_fin.editingFinished.connect(self._fin_projet)
        outils.addWidget(self.e_fin)
        self.b_calcul = QToolButton()
        self.b_calcul.setText(_("Calculer les dates"))
        self.b_calcul.setIcon(icone("view-calendar-timeline"))
        self.b_calcul.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_calcul.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.b_calcul)
        m.addAction(_("En avant d'une date de début…"), self.demander_avant)
        m.addAction(_("À rebours d'une date de fin…"), self.demander_arriere)
        self.b_calcul.setMenu(m)
        outils.addWidget(self.b_calcul)
        outils.addStretch(1)
        outils.addWidget(QLabel(_("Échelle")))
        self.c_zoom = QComboBox()
        for nom, _px in ZOOMS:
            self.c_zoom.addItem({"jour": _("Jours"), "semaine": _("Semaines"), "mois": _("Mois")}[nom])
        self.c_zoom.setCurrentIndex(1)
        self.c_zoom.currentIndexChanged.connect(lambda i: self.gantt.zoomer(ZOOMS[i][1]))
        outils.addWidget(self.c_zoom)
        self.b_export = QPushButton(icone("document-export"), _("Exporter en CSV…"))
        self.b_export.clicked.connect(lambda *_a: self.exporter_csv())
        outils.addWidget(self.b_export)
        lay.addLayout(outils)
        self.l_bilan = QLabel()
        self.l_bilan.setWordWrap(True)
        lay.addWidget(self.l_bilan)
        # diagramme + tableau
        sep = QSplitter(Qt.Orientation.Vertical)
        self.gantt = Gantt()
        self.gantt.choisie.connect(self._choisie)
        self.gantt.deplacee.connect(self.decaler)
        self.gantt.redimensionnee.connect(self.rallonger)
        self.zone = QScrollArea()
        self.zone.setWidgetResizable(True)
        self.zone.setWidget(self.gantt)
        self.zone.horizontalScrollBar().valueChanged.connect(self._defile)
        sep.addWidget(self.zone)
        self.table = QTableWidget(0, len(logique.ENTETES))
        self.table.setHorizontalHeaderLabels([_("Tâche"), _("Début"), _("Fin"), "%", _("Qui"), _("Catégorie"), _("Après")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemChanged.connect(self._cellule)
        self.table.itemSelectionChanged.connect(self._ligne_choisie)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        sep.addWidget(self.table)
        sep.setSizes([260, 200])
        lay.addWidget(sep, 1)
        self.statut = QLabel()
        lay.addWidget(self.statut)

    # ---------- affichage ----------
    def charger(self, texte: str):
        self.p = logique.lire(texte)
        self._tout_afficher()

    def _defile(self, v: int):
        self.gantt.decalage = v
        self.gantt.update()

    def _tout_afficher(self):
        self._remplit = True
        sel = self._ligne_courante()
        self.e_fin.setText(self.p.fin)
        if not self.e_debut.text():
            self.e_debut.setText(self.aujourdhui.isoformat())
        cats = sorted({t.categorie for t in self.p.taches if t.categorie})
        courant = self.c_cat.currentText()
        self.c_cat.clear()
        self.c_cat.addItems(cats)
        self.c_cat.setCurrentText(courant)
        self.table.setRowCount(len(self.p.taches))
        for i, t in enumerate(self.p.taches):
            etat = logique.etat(t, self.aujourdhui)
            valeurs = [t.nom, t.debut, t.fin, str(t.pourcent) if t.pourcent else "", t.qui, t.categorie, " ; ".join(t.apres)]
            for c, v in enumerate(valeurs):
                it = self.table.item(i, c)
                neuf = it is None
                if neuf:
                    it = QTableWidgetItem()
                it.setText(v)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setForeground(ROUGE if etat == "retard" else self.palette().text().color())
                if c == 5:
                    it.setBackground(QColor(logique.couleur(self.p, t.categorie)).lighter(165) if t.categorie else self.palette().base())
                    it.setForeground(QColor("#222222") if t.categorie else it.foreground())
                if neuf:
                    self.table.setItem(i, c, it)
        if 0 <= sel < len(self.p.taches):
            self.table.selectRow(sel)
        self.gantt.definir(self.p, self.aujourdhui, sel if sel < len(self.p.taches) else -1)
        b = logique.bilan(self.p, self.aujourdhui)
        if not b["total"]:
            self.l_bilan.setText(_("Aucune tâche : écrivez-en une en haut, puis « Ajouter »."))
        else:
            self.l_bilan.setText(_("%(total)d tâche(s) : %(fini)d finie(s), %(en_cours)d en cours, %(retard)d en retard, %(a_venir)d à venir — "
                                   "avancement %(av)d %%") % {"total": b["total"], "fini": b["fini"], "en_cours": b["en_cours"],
                                                              "retard": b["retard"], "a_venir": b["a_venir"], "av": b["avancement"]}
                                 + ((" — " + _("du %(d)s au %(f)s") % {"d": b["debut"], "f": b["fin"]}) if b["debut"] else ""))
        self._remplit = False

    def _ligne_courante(self) -> int:
        lignes = sorted({i.row() for i in self.table.selectedIndexes()})
        return lignes[0] if lignes else -1

    def _ligne_choisie(self):
        if self._remplit:
            return
        self.gantt.selection = self._ligne_courante()
        self.gantt.update()

    def _choisie(self, i: int):
        if 0 <= i < self.table.rowCount():
            self._remplit = True
            self.table.selectRow(i)
            self._remplit = False

    # ---------- modifications ----------
    def _enregistrer(self, statut: str = ""):
        self.modifie.emit(logique.ecrire(self.p))
        self._tout_afficher()
        self.statut.setText(statut)

    def ajouter(self):
        nom = self.e_nom.text().strip()
        if not nom:
            self.statut.setText(_("Donnez un nom à la tâche."))
            return
        debut = self.e_debut.text().strip()
        if debut and not logique.date_valide(debut):
            self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
            return
        t = logique.tache_neuve(nom, debut, self.e_jours.value(), self.c_cat.currentText())
        self.p.taches.append(t)
        self.e_nom.clear()
        self._enregistrer(_("Ajoutée : %s") % nom)
        self.e_nom.setFocus()

    def _cellule(self, it):
        if self._remplit or not 0 <= it.row() < len(self.p.taches):
            return
        t, v, c = self.p.taches[it.row()], it.text().strip(), it.column()
        if c == 0:
            if not v:
                self.statut.setText(_("Le nom d'une tâche ne peut pas être vide."))
                return self._tout_afficher()
            ancien, t.nom = t.nom, v
            for autre in self.p.taches:                         # les « Après » qui citaient l'ancien nom suivent
                autre.apres = [v if logique._cle(n) == logique._cle(ancien) else n for n in autre.apres]
        elif c in (1, 2):
            if v and not logique.date_valide(v):
                self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
                return self._tout_afficher()
            if c == 1:
                t.debut = v
                if not v:
                    t.fin = ""
                elif t.fin and t.fin < v:
                    t.fin = v
            elif v and not t.debut:
                t.debut, t.fin = v, v
            else:
                t.fin = max(v, t.debut) if v else ""
        elif c == 3:
            t.pourcent = logique._pourcent(v)
        elif c == 4:
            t.qui = v
        elif c == 5:
            t.categorie = v
        elif c == 6:
            t.apres = logique._apres(v)
        self._enregistrer()

    def _fin_projet(self):
        if self._remplit:
            return
        v = self.e_fin.text().strip()
        if v and not logique.date_valide(v):
            self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
            self.e_fin.setText(self.p.fin)
            return
        if v != self.p.fin:
            self.p.fin = v
            self._enregistrer()

    def decaler(self, i: int, jours: int):
        """Déplace la tâche `i` de `jours` jours (glisser de la barre)."""
        t = self.p.taches[i]
        t.debut = logique._s(logique._d(t.debut) + timedelta(days=jours))
        if t.fin:
            t.fin = logique._s(logique._d(t.fin) + timedelta(days=jours))
        self._enregistrer()

    def rallonger(self, i: int, jours: int):
        """Allonge (ou raccourcit) la tâche `i` de `jours` jours par sa fin (tirer le bord droit)."""
        t = self.p.taches[i]
        fin = logique._d(logique.fin_effective(t)) + timedelta(days=jours)
        t.fin = logique._s(max(fin, logique._d(t.debut)))
        self._enregistrer()

    def recaler(self, sens: str, jour: date):
        """Calcule les dates : `sens` « avant » (à partir d'un début) ou « arriere » (à rebours d'une fin)."""
        try:
            (logique.recaler_avant if sens == "avant" else logique.recaler_arriere)(self.p, jour)
        except ValueError as e:
            self.statut.setText(str(e))
            return False
        self._enregistrer(_("Dates calculées."))
        return True

    def _demander(self, titre: str, defaut: str) -> date | None:
        v, ok = QInputDialog.getText(self, titre, _("Date (AAAA-MM-JJ) :"), text=defaut)
        if not ok:
            return None
        if not logique.date_valide(v):
            self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
            return None
        return logique._d(v)

    def demander_avant(self):
        d = self._demander(_("Calculer les dates en avant"), self.aujourdhui.isoformat())
        if d:
            self.recaler("avant", d)

    def demander_arriere(self):
        d = self._demander(_("Calculer les dates à rebours"), self.p.fin or (self.aujourdhui + timedelta(days=30)).isoformat())
        if d:
            self.recaler("arriere", d)

    def _menu(self, pos):
        lignes = sorted({i.row() for i in self.table.selectedIndexes()})
        it = self.table.itemAt(pos)
        if it is not None and it.row() not in lignes:
            lignes = [it.row()]
        if not lignes:
            return
        m = QMenu(self.table)
        m.addAction(icone("dialog-ok-apply"), _("Marquer comme terminée"), lambda: self.terminer(lignes))
        m.addAction(icone("go-up"), _("Monter"), lambda: self.deplacer(lignes, -1))
        m.addAction(icone("go-down"), _("Descendre"), lambda: self.deplacer(lignes, 1))
        cat = self.p.taches[lignes[0]].categorie
        if cat:
            m.addAction(icone("color-management"), _("Couleur de la catégorie « %s »…") % cat, lambda: self.choisir_couleur(cat))
        m.addSeparator()
        m.addAction(icone("edit-delete"), _("Supprimer la ligne"), lambda: self.supprimer(lignes))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def terminer(self, lignes):
        for r in lignes:
            if 0 <= r < len(self.p.taches):
                self.p.taches[r].pourcent = 100
        self._enregistrer()

    def deplacer(self, lignes, sens: int):
        i = lignes[0]
        j = i + sens
        if len(lignes) == 1 and 0 <= j < len(self.p.taches):
            self.p.taches[i], self.p.taches[j] = self.p.taches[j], self.p.taches[i]
            self._enregistrer()
            self.table.selectRow(j)

    def supprimer(self, lignes):
        noms = {logique._cle(self.p.taches[r].nom) for r in lignes if 0 <= r < len(self.p.taches)}
        for r in sorted({r for r in lignes if 0 <= r < len(self.p.taches)}, reverse=True):
            del self.p.taches[r]
        for t in self.p.taches:
            t.apres = [n for n in t.apres if logique._cle(n) not in noms]
        self._enregistrer()

    def choisir_couleur(self, cat: str, couleur: str | None = None):
        c = couleur or QColorDialog.getColor(QColor(logique.couleur(self.p, cat)), self, _("Couleur de la catégorie « %s »") % cat).name()
        if couleur is None and not QColor(c).isValid():
            return
        self.p.couleurs[cat] = c.lower()
        self._enregistrer()

    def exporter_csv(self):
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en CSV"), "planning.csv", _("Fichiers CSV (*.csv)"))
        if chemin:
            with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
                f.write(logique.vers_csv(self.p))
            self.statut.setText(_("Exporté : %s") % chemin)


class PlanningPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Planning"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "view-calendar-timeline")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VuePlanning())


DOC = _(
    "Un petit planning pour suivre des tâches : qui fait quoi, quand, et où on en est. Pas de la gestion de projet lourde.\n"
    "\n"
    "• Nouvelle fiche > « Planning ». En haut, le diagramme de Gantt : une barre par tâche, colorée selon sa catégorie ; le remplissage montre "
    "l'avancement. Un losange est un jalon (une date, sans durée). Une flèche relie une tâche à celle qui l'attend. Le trait rouge est "
    "aujourd'hui ; le trait pointillé, la fin du projet. Une tâche dont la fin est passée et qui n'est pas à 100 % est en retard (en rouge).\n"
    "• Ajouter une tâche : son nom, sa date de début (celle du jour), sa durée en jours (0 = un jalon) et sa catégorie, puis « Ajouter ». "
    "Les cellules du tableau en dessous se modifient directement : dates (AAAA-MM-JJ), « % » d'avancement, « Qui », catégorie, et « Après » "
    "(les noms des tâches à finir avant, séparés par « ; »). Clic droit : marquer comme terminée, monter, descendre, supprimer, "
    "changer la couleur d'une catégorie.\n"
    "• À la souris : glisser une barre pour la déplacer, tirer son bord droit pour la rallonger ou la raccourcir. « Échelle » : jours, semaines "
    "ou mois.\n"
    "• « Calculer les dates > À rebours d'une date de fin » : le rétroplanning. Vous donnez la date d'arrivée (jour J) ; chaque tâche est placée "
    "pour finir à temps, en tenant compte de sa durée et des tâches qui l'attendent. « En avant d'une date de début » fait l'inverse. Les "
    "tâches terminées (100 %) ne bougent pas. Une tâche sans date est planifiée par ce calcul.\n"
    "• Le bilan (sous la barre d'outils) compte les tâches finies, en cours, en retard et à venir, et donne l'avancement global.\n"
    "• « Exporter en CSV… » : Tâche, Début, Fin, %, Qui, Catégorie, Après (séparateur « ; »).\n"
    "• Un planning est un tableau Markdown : lisible partout, cherchable, partageable (extension Partage) et verrouillable. Rien n'est exécuté.")
