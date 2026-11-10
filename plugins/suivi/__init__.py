# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Suivi » : le poids et les calories au jour le jour, avec des courbes (voir `logique.py`).

- Une fiche « Suivi poids et calories » : saisie rapide (date, poids, calories à AJOUTER au total du jour, note), tableau des jours (cellules
  modifiables, clic droit : supprimer), objectifs et taille (facultatifs), bilan (dernier poids, variation sur 7 et 30 jours, moyenne des calories
  sur 7 jours, reste du jour, indice de masse corporelle) et deux graphiques : poids (avec l'objectif) et calories (barres du vert au rouge selon l'objectif).
- Le texte reste un tableau Markdown ; type non exécutable. Données de santé : verrouillez la fiche. Ce n'est pas un avis médical."""
import math
from datetime import date, timedelta

from PyQt6.QtCore import QDate, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPalette
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QProgressBar,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

PERIODES = (("30", 30), ("90", 90), ("365", 365), ("0", 0))


def couleur_ratio(r: float) -> QColor:
    """Calories / objectif -> vert (peu), jaune (à l'objectif), rouge (au-delà de 130 %)."""
    r = max(0.0, r)
    teinte = 120 - 60 * min(max((r - 0.6) / 0.4, 0), 1) if r <= 1 else 60 - 60 * min((r - 1) / 0.3, 1)
    return QColor.fromHsv(int(teinte), 170, 215)


def graduations(mini: float, maxi: float, n: int = 4) -> list:
    """Valeurs rondes (1, 2, 5 x 10^k) entre mini et maxi pour la grille d'un graphique."""
    ecart = max(maxi - mini, 1e-9)
    brut = ecart / n
    puissance = 10 ** math.floor(math.log10(brut))
    pas = next(m * puissance for m in (1, 2, 5, 10) if m * puissance >= brut)
    debut = math.ceil(mini / pas - 1e-9) * pas
    valeurs, v = [], debut
    while v <= maxi + 1e-9:
        valeurs.append(round(v, 6))
        v += pas
    return valeurs


class Graphique(QWidget):
    """Courbe (poids) ou barres (calories) dessinées à la main : pas de bibliothèque de graphiques."""

    def __init__(self, titre: str, barres: bool = False, parent=None):
        super().__init__(parent)
        self.titre, self.barres = titre, barres
        self.points: list = []
        self.objectif = None
        self.setMinimumHeight(150)

    def definir(self, points: list, objectif=None):
        self.points, self.objectif = points, objectif
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        texte = self.palette().color(QPalette.ColorRole.WindowText)
        gris = QColor(texte)
        gris.setAlpha(70)
        g, d, h, b = 50, 14, 22, 20
        zone = QRectF(g, h, max(10, self.width() - g - d), max(10, self.height() - h - b))
        p.setPen(texte)
        p.drawText(QPointF(4, 14), self.titre)
        if not self.points:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("Pas encore de données"))
            return
        jours = [date.fromisoformat(j).toordinal() for j, _v in self.points]
        valeurs = [v for _j, v in self.points] + ([self.objectif] if self.objectif else [])
        x0, x1 = min(jours), max(jours)
        if x1 == x0:
            x0, x1 = x0 - 1, x1 + 1
        y0, y1 = (0.0 if self.barres else min(valeurs)), max(valeurs)
        marge = (y1 - y0) * 0.08 or 1.0
        y0, y1 = (y0 if self.barres else y0 - marge), y1 + marge

        marge_x = 14.0 if self.barres else 6.0              # les barres et les points ne recouvrent pas les graduations

        def X(o):
            return zone.left() + marge_x + (o - x0) / (x1 - x0) * (zone.width() - 2 * marge_x)

        def Y(v):
            return zone.bottom() - (v - y0) / (y1 - y0) * zone.height()
        fm = QFontMetrics(self.font())
        for v in graduations(y0, y1):                      # grille et graduations rondes
            p.setPen(QPen(gris, 1))
            p.drawLine(QPointF(zone.left(), Y(v)), QPointF(zone.right(), Y(v)))
            p.setPen(texte)
            etiquette = "%d" % round(v) if abs(v - round(v)) < 1e-6 else "%.1f" % v
            p.drawText(QPointF(zone.left() - fm.horizontalAdvance(etiquette) - 4, Y(v) + fm.ascent() / 2 - 1), etiquette)
        for o, alignement in ((x0, "g"), (x1, "d")):      # première et dernière date
            e = date.fromordinal(o).strftime("%d/%m")
            p.drawText(QPointF(X(o) - (0 if alignement == "g" else fm.horizontalAdvance(e)), self.height() - 5), e)
        if self.objectif:                                 # ligne d'objectif en pointillés
            p.setPen(QPen(QColor("#2e7d32"), 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(zone.left(), Y(self.objectif)), QPointF(zone.right(), Y(self.objectif)))
        if self.barres:
            largeur = max(2.0, min(24.0, (zone.width() - 28) / max(1, (x1 - x0 + 1)) * 0.7))
            for (j, v), o in zip(self.points, jours):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(couleur_ratio(v / self.objectif) if self.objectif else QColor("#5b8def"))
                p.drawRect(QRectF(X(o) - largeur / 2, Y(v), largeur, max(1.0, zone.bottom() - Y(v))))
        else:
            couleur = QColor("#2f6fdb")
            pts = [QPointF(X(o), Y(v)) for o, (_j, v) in zip(jours, self.points)]
            p.setPen(QPen(couleur, 2))
            for a, c in zip(pts, pts[1:]):
                p.drawLine(a, c)
            p.setBrush(couleur)
            for pt in pts:
                p.drawEllipse(pt, 3, 3)


class VueSuivi(QWidget):
    """Vue du type « suivi » : saisie rapide, bilan, graphiques et tableau des jours."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                                  # type non exécutable : toujours utilisable
        self.s = logique.Suivi()
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        # réglages (taille et objectifs)
        reg = QHBoxLayout()
        self.e_taille, self.e_obj_poids, self.e_obj_cal = QLineEdit(), QLineEdit(), QLineEdit()
        for champ, etiquette, marque in ((self.e_taille, _("Taille (cm)"), "175"), (self.e_obj_poids, _("Objectif poids (kg)"), "72"),
                                         (self.e_obj_cal, _("Objectif calories / jour"), "2000")):
            champ.setFixedWidth(80)
            champ.setPlaceholderText(marque)
            champ.editingFinished.connect(self._reglages)
            reg.addWidget(QLabel(etiquette))
            reg.addWidget(champ)
        reg.addStretch(1)
        lay.addLayout(reg)
        # saisie rapide
        saisie = QHBoxLayout()
        self.e_jour = QDateEdit(QDate.currentDate())
        self.e_jour.setCalendarPopup(True)
        self.e_poids, self.e_cal, self.e_note = QLineEdit(), QLineEdit(), QLineEdit()
        self.e_poids.setPlaceholderText(_("poids en kg"))
        self.e_cal.setPlaceholderText(_("calories à ajouter"))
        self.e_note.setPlaceholderText(_("note (facultatif)"))
        for champ, large in ((self.e_poids, 90), (self.e_cal, 130)):
            champ.setFixedWidth(large)
        self.b_poids = QPushButton(icone("list-add"), _("Poids"))
        self.b_cal = QPushButton(icone("list-add"), _("Calories"))
        self.b_poids.clicked.connect(self._poids)
        self.b_cal.clicked.connect(self._calories)
        self.e_poids.returnPressed.connect(self._poids)
        self.e_cal.returnPressed.connect(self._calories)
        for w in (self.e_jour, self.e_poids, self.b_poids, self.e_cal, self.b_cal):
            saisie.addWidget(w)
        saisie.addWidget(self.e_note, 1)
        lay.addLayout(saisie)
        # bilan
        self.bilan = QLabel()
        self.bilan.setWordWrap(True)
        self.bilan.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.bilan)
        self.barre = QProgressBar()
        self.barre.setTextVisible(True)
        lay.addWidget(self.barre)
        # graphiques
        hp = QHBoxLayout()
        hp.addWidget(QLabel(_("Période")))
        self.c_periode = QComboBox()
        for cle, jours in PERIODES:
            self.c_periode.addItem({"30": _("30 jours"), "90": _("90 jours"), "365": _("1 an"), "0": _("Tout")}[cle], jours)
        self.c_periode.currentIndexChanged.connect(self._afficher)
        hp.addWidget(self.c_periode)
        hp.addStretch(1)
        lay.addLayout(hp)
        self.g_poids = Graphique(_("Poids (kg)"))
        self.g_cal = Graphique(_("Calories par jour"), barres=True)
        lay.addWidget(self.g_poids, 1)
        lay.addWidget(self.g_cal, 1)
        # tableau
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("Date"), _("Poids (kg)"), _("Calories"), _("Note")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setMinimumHeight(120)
        self.table.cellChanged.connect(self._cellule)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.note = QLabel(_("Un carnet, pas un avis médical. Données de santé : verrouillez la fiche."))
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    # ---------- données ----------
    def charger(self, texte: str):
        self.s = logique.lire(texte)
        self._afficher()

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.s))
        self._afficher()

    def _jour(self) -> str:
        return self.e_jour.date().toString("yyyy-MM-dd")

    def _poser_note(self):
        if self.e_note.text().strip():
            self.s.poser_note(self._jour(), self.e_note.text())
            self.e_note.clear()

    def _poids(self):
        if self.s.poser_poids(self._jour(), self.e_poids.text()) and self.e_poids.text().strip():
            self.e_poids.clear()
            self._poser_note()
            self._enregistrer()
        else:
            self.bilan.setText(_("Poids non reconnu : entre 20 et 400 kg (virgule ou point)."))

    def _calories(self):
        if self.s.ajouter_calories(self._jour(), self.e_cal.text()):
            self.e_cal.clear()
            self._poser_note()
            self._enregistrer()
        else:
            self.bilan.setText(_("Calories non reconnues : un nombre (négatif pour corriger)."))

    def _reglages(self):
        avant = (self.s.taille, self.s.objectif_poids, self.s.objectif_calories)
        self.s.taille = logique.nombre(self.e_taille.text(), *logique.LIMITES["taille"])
        self.s.objectif_poids = logique.lire_poids(self.e_obj_poids.text())
        self.s.objectif_calories = logique.lire_calories(self.e_obj_cal.text()) or None
        if avant != (self.s.taille, self.s.objectif_poids, self.s.objectif_calories):
            self._enregistrer()

    def _cellule(self, ligne: int, colonne: int):
        if self._remplit:
            return
        jour = self.table.item(ligne, 0).text()
        valeur = self.table.item(ligne, colonne).text()
        if colonne == 1:
            self.s.poser_poids(jour, valeur)
        elif colonne == 2:
            self.s.poser_calories(jour, valeur)
        elif colonne == 3:
            self.s.poser_note(jour, valeur)
        self._enregistrer()

    def _menu(self, pos):
        lignes = sorted({i.row() for i in self.table.selectedIndexes()})
        if not lignes:
            return
        m = QMenu(self)
        m.addAction(icone("edit-delete"), _("Supprimer ces jours"), lambda: self._supprimer(lignes))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _supprimer(self, lignes: list):
        for i in lignes:
            self.s.supprimer(self.table.item(i, 0).text())
        self._enregistrer()

    # ---------- affichage ----------
    def _afficher(self):
        s, auj = self.s, date.today()
        self._remplit = True
        for champ, v in ((self.e_taille, s.taille), (self.e_obj_poids, s.objectif_poids), (self.e_obj_cal, s.objectif_calories)):
            if not champ.hasFocus():
                champ.setText(logique._n(v) if v else "")
        jours = sorted(s.jours, reverse=True)
        self.table.setRowCount(len(jours))
        for i, j in enumerate(jours):
            d = s.jours[j]
            cases = [j, logique._n(d["poids"]) if d["poids"] is not None else "", str(d["calories"]) if d["calories"] is not None else "", d["note"]]
            for c, t in enumerate(cases):
                it = QTableWidgetItem(t)
                if c == 0:
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                elif c in (1, 2):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._remplit = False
        # bilan
        lignes = []
        dp = logique.dernier_poids(s)
        if dp:
            ligne = _("Dernier poids : <b>%(kg)s kg</b> (%(jour)s)") % {"kg": logique._n(dp[1]), "jour": date.fromisoformat(dp[0]).strftime("%d/%m")}
            for n in (7, 30):
                v = logique.variation(s, n)
                if v is not None:
                    ligne += " · " + _("%(n)d j : %(v)+.1f kg") % {"n": n, "v": v}
            lignes.append(ligne)
            ecart = logique.ecart_objectif(s)
            if ecart is not None:
                lignes.append(_("Objectif %(obj)s kg : il reste %(e).1f kg à perdre.") % {"obj": logique._n(s.objectif_poids), "e": ecart} if ecart > 0 else
                              _("Objectif %(obj)s kg atteint (%(e).1f kg sous l'objectif).") % {"obj": logique._n(s.objectif_poids), "e": -ecart})
            i = logique.imc(dp[1], s.taille)
            if i is not None:
                lignes.append(_("Indice de masse corporelle : %.1f") % i)
        m7 = logique.moyenne_calories(s, 7, auj)
        if m7 is not None:
            lignes.append(_("Moyenne des calories sur 7 jours : %d par jour") % m7)
        self.bilan.setText("<br>".join(lignes) if lignes else _("Saisissez un poids ou des calories pour commencer."))
        # calories du jour
        cal = s.jours.get(auj.isoformat(), {}).get("calories") or 0
        self.barre.setVisible(bool(s.objectif_calories))
        if s.objectif_calories:
            self.barre.setRange(0, max(s.objectif_calories, cal))
            self.barre.setValue(cal)
            self.barre.setFormat(_("Aujourd'hui : %(c)d / %(o)d kcal") % {"c": cal, "o": s.objectif_calories})
            self.barre.setStyleSheet("QProgressBar::chunk { background: %s; }" % couleur_ratio(cal / s.objectif_calories).name())
        # graphiques
        n = self.c_periode.currentData()
        depuis = (auj - timedelta(days=n - 1)).isoformat() if n else None
        self.g_poids.definir(s.serie("poids", depuis), s.objectif_poids)
        self.g_cal.definir(s.serie("calories", depuis), s.objectif_calories)


class SuiviPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Suivi"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "office-chart-line")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueSuivi())


DOC = _(
    "Le poids et les calories au jour le jour, avec des courbes.\n"
    "\n"
    "• Nouvelle fiche > « Suivi poids et calories » : une fiche = un suivi. Saisie rapide en haut : la date (aujourd'hui par défaut), le poids, "
    "les calories, une note facultative.\n"
    "• Les calories s'AJOUTENT au total du jour (petit-déjeuner, déjeuner, en-cas…) ; un nombre négatif corrige. Le poids du jour est remplacé. "
    "Les cellules du tableau se modifient directement ; clic droit : supprimer des jours.\n"
    "• Taille et objectifs (poids, calories par jour) sont facultatifs. Le bilan donne le dernier poids, sa variation sur 7 et 30 jours, ce qu'il reste "
    "pour atteindre l'objectif, l'indice de masse corporelle et la moyenne des calories sur 7 jours.\n"
    "• Deux graphiques : le poids (avec la ligne d'objectif en pointillés) et les calories (barres du vert au rouge selon l'objectif). La période se choisit.\n"
    "• C'est un carnet, pas un avis médical. Ce sont des données de santé : verrouillez la fiche (clic droit > Verrouiller). Le texte reste un tableau "
    "Markdown lisible, cherchable et partageable ; rien n'est exécuté.")
