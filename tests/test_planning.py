# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Planning » : format, états, bilan, dépendances, calcul des dates (avant et à rebours), exemples, vue et diagramme."""
import importlib.util
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "planning"
_spec = importlib.util.spec_from_file_location("planning_logique_t", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

AJD = date(2026, 11, 9)
TEXTE = """#scrinium-planning
fin: 2026-12-20
couleur Logistique: #E67E22

| Tâche | Début | Fin | % | Qui | Catégorie | Après |
| --- | --- | --- | --- | --- | --- | --- |
| Camion | 2026-11-02 | 2026-11-04 | 100 | Marie | Logistique | |
| Cartons | 2026-11-05 | 2026-11-12 | 40 | | Logistique | Camion |
| Jour J | 2026-12-20 | | | | | Cartons ; Camion |
| À planifier | | | | | | Cartons |

Notes libres.
"""


def test_lecture_ecriture():
    p = lg.lire(TEXTE)
    assert p.fin == "2026-12-20" and p.couleurs == {"Logistique": "#e67e22"} and p.notes == "Notes libres."
    assert [t.nom for t in p.taches] == ["Camion", "Cartons", "Jour J", "À planifier"]
    camion, cartons, jour, plan = p.taches
    assert (camion.debut, camion.fin, camion.pourcent, camion.qui) == ("2026-11-02", "2026-11-04", 100, "Marie")
    assert jour.jalon and jour.apres == ["Cartons", "Camion"] and not plan.planifiee
    assert lg.lire(lg.ecrire(p)) == p
    assert lg.ecrire(lg.lire(lg.ecrire(p))) == lg.ecrire(p)


def test_lecture_tolerante():
    assert lg.lire("").taches == [] and lg.lire(None).taches == []
    p = lg.lire("#scrinium-planning\n| Tâche | Début | Fin |\n| a | pas une date | 2026-01-02 |\n| b | 2026-01-05 | 2026-01-01 | 250 |\n||x|\n")
    assert p.taches[0].debut == "" and p.taches[0].fin == ""             # fin sans début : ignorée
    assert p.taches[1].fin == "2026-01-05" and p.taches[1].pourcent == 100  # fin avant début ramenée au début ; % plafonné
    assert len(p.taches) == 2


def test_duree_etat_et_bilan():
    p = lg.lire(TEXTE)
    camion, cartons, jour, plan = p.taches
    assert lg.duree(camion) == 3 and lg.duree(jour) == 1 and lg.duree(plan) == 1
    assert [lg.etat(t, AJD) for t in p.taches] == ["fini", "en_cours", "a_venir", "non_planifie"]
    en_retard = lg.Tache("x", "2026-11-01", "2026-11-05", 30)
    assert lg.etat(en_retard, AJD) == "retard"
    assert lg.etat(lg.Tache("j", "2026-11-05"), AJD) == "retard"        # un jalon passé non fini
    b = lg.bilan(p, AJD)
    assert (b["total"], b["fini"], b["en_cours"], b["a_venir"], b["non_planifie"]) == (4, 1, 1, 1, 1)
    assert b["debut"] == "2026-11-02" and b["fin"] == "2026-12-20"
    assert b["avancement"] == round((3 * 100 + 8 * 40) / (3 + 8 + 1 + 1))
    assert lg.bilan(lg.Planning(), AJD)["avancement"] == 0


def test_couleurs():
    p = lg.lire(TEXTE)
    assert lg.couleur(p, "Logistique") == "#e67e22"
    assert lg.couleur(p, "Autre") == lg.couleur(p, "autre") and lg.couleur(p, "Autre") in lg.PALETTE
    assert lg.couleur(p, "") == lg.PALETTE[0]


def test_dependances_et_boucle():
    p = lg.lire(TEXTE)
    assert sorted(lg.dependances(p)) == [(0, 1), (0, 2), (1, 2), (1, 3)]
    o = lg.ordre(p)
    assert o.index(0) < o.index(1) < o.index(2)
    p.taches[0].apres = ["Jour J"]
    with pytest.raises(ValueError):
        lg.ordre(p)
    p.taches[0].apres = ["Camion", "inconnue"]                         # soi-même et noms inconnus : ignorés
    assert lg.ordre(p)


def test_recaler_a_rebours():
    p = lg.Planning(taches=[lg.tache_neuve("A", "2026-01-01", 3), lg.tache_neuve("B", "2026-01-01", 5, apres="A"),
                            lg.tache_neuve("C", "2026-01-01", 2, apres="A"), lg.tache_neuve("Fin", "2026-01-01", 0, apres="B ; C")])
    lg.recaler_arriere(p, date(2026, 3, 31))
    a, b, c, f = p.taches
    assert (f.debut, f.fin) == ("2026-03-31", "") and f.jalon                       # le jalon est le jour J
    assert (b.debut, b.fin) == ("2026-03-26", "2026-03-30") and (c.debut, c.fin) == ("2026-03-29", "2026-03-30")
    assert (a.debut, a.fin) == ("2026-03-23", "2026-03-25")                         # finit la veille du plus précoce (B)
    assert p.fin == "2026-03-31"


def test_recaler_en_avant_et_taches_finies():
    p = lg.Planning(taches=[lg.tache_neuve("A", "2026-01-01", 3), lg.tache_neuve("B", "2026-01-01", 2, apres="A"),
                            lg.tache_neuve("C", "2026-02-10", 4)])
    p.taches[0].pourcent = 100
    lg.recaler_avant(p, date(2026, 6, 1))
    a, b, c = p.taches
    assert (a.debut, a.fin) == ("2026-01-01", "2026-01-03")                         # finie : ne bouge pas
    assert (b.debut, b.fin) == ("2026-06-01", "2026-06-02")                         # son prédécesseur est fini depuis longtemps
    assert (c.debut, c.fin) == ("2026-06-01", "2026-06-04")
    nouvelle = lg.Planning(taches=[lg.Tache("x"), lg.Tache("y", apres=["x"])])      # sans dates : durée 1 jour
    lg.recaler_avant(nouvelle, date(2026, 6, 1))
    assert nouvelle.taches[1].debut == "2026-06-02"
    boucle = lg.Planning(taches=[lg.Tache("a", apres=["b"]), lg.Tache("b", apres=["a"])])
    with pytest.raises(ValueError):
        lg.recaler_arriere(boucle, date(2026, 6, 1))


def test_tache_neuve_csv_et_exemples():
    t = lg.tache_neuve(" Essai ", "2026-11-09", 3, " Cat ", apres="a ; b")
    assert (t.nom, t.fin, t.categorie, t.apres) == ("Essai", "2026-11-11", "Cat", ["a", "b"])
    assert lg.tache_neuve("j", "2026-11-09", 0).jalon and not lg.tache_neuve("x", "pas une date", 2).planifiee
    assert lg.vers_csv(lg.lire(TEXTE)).splitlines()[0] == "Tâche;Début;Fin;%;Qui;Catégorie;Après"
    ex = lg.exemples(AJD)
    assert len(ex) == 3 and ex[2][2].startswith(lg.MARQUE_RESULTAT)
    demenagement = lg.lire(ex[0][2])
    assert demenagement.fin and not any(not t.planifiee for t in demenagement.taches)
    assert demenagement.taches[-1].jalon and demenagement.taches[-1].debut == demenagement.fin    # le jour J est le dernier
    assert lg.bilan(lg.lire(ex[1][2]), AJD)["retard"] == 1                                         # l'exemple montre un retard


def test_resultat_de_plusieurs_plannings():
    ex = [lg.lire(x[2]) for x in lg.exemples(AJD)[:2]]
    r = lg.resultat([("Déménagement", ex[0]), ("Projet", ex[1])], AJD)
    assert [n for n, _b in r["lignes"]] == ["Déménagement", "Projet"]
    t = r["total"]
    assert t["total"] == 11 and t["retard"] == 1 and t["fini"] == 3 and t["total"] == t["fini"] + t["retard"] + t["en_cours"] + t["a_venir"]
    assert t["debut"] == "2026-10-28" and t["fin"] == lg.lire(lg.exemples(AJD)[0][2]).fin
    assert r["retards"] == [("Projet", "Maquette", "2026-11-06", 60)]
    assert lg.resultat([], AJD)["total"]["avancement"] == 0
    assert lg.est_planning(TEXTE) and not lg.est_planning(lg.MARQUE_RESULTAT + "\n") and not lg.est_planning("autre") and not lg.est_planning(None)
    assert lg.portee_de(None) == "theme" and lg.portee_de("#x\nportée: tous\n") == "tous"
    t2 = lg.texte_resultat("tous", lg.MARQUE_RESULTAT + "\n\nMes notes\n")
    assert t2 == lg.MARQUE_RESULTAT + "\nportée: tous\n\nMes notes\n"
    assert lg.texte_resultat("theme", t2) == lg.MARQUE_RESULTAT + "\n\nMes notes\n"


# ---------- interface ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "planning")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("planning"), w.plugins.infos["planning"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _vue(fen):
    v = fen.vues_types["planning"]
    v.aujourdhui = AJD
    return v


def test_vue_saisie_edition_et_calcul(fen):
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == "Planning").trigger()
    v = _vue(fen)
    sorties = []
    v.modifie.connect(sorties.append)
    v.charger(TEXTE)
    assert v.table.rowCount() == 4 and "4 tâche" in v.l_bilan.text()
    v.e_nom.setText("Peindre")
    v.e_debut.setText("2026-11-20")
    v.e_jours.setValue(2)
    v.c_cat.setCurrentText("Travaux")
    v.ajouter()
    t = v.p.taches[-1]
    assert (t.nom, t.debut, t.fin, t.categorie) == ("Peindre", "2026-11-20", "2026-11-21", "Travaux")
    assert lg.lire(sorties[-1]).taches[-1].nom == "Peindre" and v.e_nom.text() == ""
    # modifier une cellule : l'avancement, un nom (les « Après » suivent), une date invalide
    v.table.item(1, 3).setText("75")
    assert v.p.taches[1].pourcent == 75
    v.table.item(0, 0).setText("Camion loué")
    assert v.p.taches[2].apres == ["Cartons", "Camion loué"]
    n = len(sorties)
    v.table.item(1, 1).setText("demain")
    assert len(sorties) == n and "invalide" in v.statut.text() and v.p.taches[1].debut == "2026-11-05"
    # glisser / tirer une barre
    v.decaler(1, 3)
    assert (v.p.taches[1].debut, v.p.taches[1].fin) == ("2026-11-08", "2026-11-15")
    v.rallonger(1, -20)
    assert v.p.taches[1].fin == v.p.taches[1].debut
    # rétroplanning, boucle, terminer, supprimer
    assert v.recaler("arriere", date(2026, 12, 31)) and v.p.taches[2].debut == "2026-12-31" and v.p.fin == "2026-12-31"
    v.p.taches[0].apres = ["Jour J"]
    assert not v.recaler("avant", AJD) and "Boucle" in v.statut.text()
    v.p.taches[0].apres = []
    v.terminer([1])
    assert v.p.taches[1].pourcent == 100
    v.supprimer([1])
    assert "Cartons" not in [t.nom for t in v.p.taches] and v.p.taches[1].apres == ["Camion loué"]
    v.choisir_couleur("Logistique", "#112233")
    assert lg.lire(sorties[-1]).couleurs["Logistique"] == "#112233"


def test_diagramme_souris_et_dessin(fen, tmp_path):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    v = _vue(fen)
    v.charger(TEXTE)
    v.resize(1000, 700)
    v.show()
    g = v.gantt
    assert not v.grab().isNull()
    for px in (26, 9, 3):                                     # jours, semaines, mois
        g.zoomer(px)
        assert not g.grab().isNull()
    g.zoomer(26)
    g.grab()                                                  # remplit les rectangles des barres
    r = g._geom[1]
    avant = v.p.taches[1].debut
    pos = QPointF(r.center().x(), r.center().y())
    def evt(type_, p):
        return QMouseEvent(type_, p, p, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    g.mousePressEvent(evt(QMouseEvent.Type.MouseButtonPress, pos))
    g.mouseMoveEvent(evt(QMouseEvent.Type.MouseMove, QPointF(pos.x() + 2 * g.px + 3, pos.y())))
    g.mouseReleaseEvent(evt(QMouseEvent.Type.MouseButtonRelease, QPointF(pos.x() + 2 * g.px + 3, pos.y())))
    assert v.p.taches[1].debut != avant and (lg._d(v.p.taches[1].debut) - lg._d(avant)).days == 2
    assert v.table.selectedIndexes() and v.table.selectedIndexes()[0].row() == 1
    g.grab()
    r = g._geom[1]                                            # tirer le bord droit
    droite = QPointF(r.right() - 2, r.center().y())
    fin = v.p.taches[1].fin
    g.mousePressEvent(evt(QMouseEvent.Type.MouseButtonPress, droite))
    g.mouseMoveEvent(evt(QMouseEvent.Type.MouseMove, QPointF(droite.x() + g.px, droite.y())))
    g.mouseReleaseEvent(evt(QMouseEvent.Type.MouseButtonRelease, QPointF(droite.x() + g.px, droite.y())))
    assert (lg._d(v.p.taches[1].fin) - lg._d(fin)).days == 1
    # un clic sans glisser ne modifie rien
    sorties = []
    v.modifie.connect(sorties.append)
    g.mousePressEvent(evt(QMouseEvent.Type.MouseButtonPress, pos))
    g.mouseReleaseEvent(evt(QMouseEvent.Type.MouseButtonRelease, pos))
    assert sorties == []


def _fiche(fen, theme, titre, texte):
    th = fen.store.theme(theme) or fen.store.nouveau_theme(theme)
    f = fen.store.nouvelle_fiche(th)
    fen.store.enregistrer(th, f, titre, texte)
    fen.maj_themes()


def test_fiche_resultat_par_theme(fen):
    _fiche(fen, "Maison", "Déménagement", lg.exemples(AJD)[0][2])
    _fiche(fen, "Travail", "Projet", lg.exemples(AJD)[1][2])
    _fiche(fen, "Travail", "Notes", "pas un planning")
    fen.montrer(theme="Maison")
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == "Planning — résultat").trigger()
    vr = fen.vues_types["planning-resultat"]
    vr.aujourdhui = AJD
    assert fen.pile.currentWidget() is vr
    vr.charger(vr._texte)
    assert [vr.table.item(i, 0).text() for i in range(vr.table.rowCount())] == ["Déménagement"]      # le thème de la fiche seulement
    vr.c_portee.setCurrentIndex(vr.c_portee.findData("tous"))
    assert [vr.table.item(i, 0).text() for i in range(vr.table.rowCount())] == ["Déménagement  (Maison)", "Projet  (Travail)", "Total"]
    assert vr.retards.rowCount() == 1 and vr.retards.item(0, 1).text() == "Maquette"
    fen.sauver()
    assert lg.portee_de(fen.fiche.texte) == "tous"                                                       # le choix est gardé dans la fiche
