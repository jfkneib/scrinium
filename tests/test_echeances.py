# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Échéances » : fiche, prochaine date, statuts, totaux, rappels (une seule fois) et vue dans la vraie fenêtre."""
import importlib.util
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "echeances"
_spec = importlib.util.spec_from_file_location("echeances_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

AUJ = date(2026, 11, 10)


def E(nom, jours, mois=0, montant=None, rappel=30, note=""):
    return lg.Echeance(nom, (AUJ + timedelta(days=jours)).isoformat(), mois, montant, rappel, note)


def test_texte_aller_retour_et_tolerance():
    doc = lg.Document("€", [E("Assurance | auto", 25, 12, 612.0, 30, "contrat | 123"), E("Garantie", 40, 0, None, 60)])
    t = lg.ecrire(doc)
    assert t.startswith("#scrinium-echeances\ndevise: €\n\n| Échéance | Date |") and "| Assurance / auto | 2026-12-05 | annuel | 612 | 30 | contrat / 123 |" in t
    assert lg.ecrire(lg.lire(t)) == t
    assert lg.lire("").echeances == [] and lg.lire("texte libre").echeances == [] and lg.lire(None).devise == "€"
    d = lg.lire("devise: $\n| Loyer | 10/12/2026 | chaque mois | 1 200,50 € | abc | x |\n| Sans date | pas | | | | |\n| | 2026-01-01 | | | | |")
    e = d.echeances[0]
    assert d.devise == "$" and len(d.echeances) == 1 and e.date == "2026-12-10" and e.mois == 1 and e.montant == 1200.5 and e.rappel == 30
    assert lg.lire_repetition("Chaque année") == 12 and lg.lire_repetition("tous les 2 ans") == 24 and lg.lire_repetition("trimestriel") == 3
    assert lg.lire_repetition("n'importe quoi") == 0 and lg.lire_repetition("") == 0
    assert lg.formater_montant(1200.5) == "1 200,50 €" and lg.formater_montant(612.0) == "612 €" and lg.formater_montant(None) == ""


def test_prochaine_date_des_echeances_qui_se_repetent():
    assert lg.ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28) and lg.ajouter_mois(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert lg.ajouter_mois(date(2026, 11, 15), 3) == date(2027, 2, 15) and lg.ajouter_mois(date(2026, 12, 15), 12) == date(2027, 12, 15)
    assert lg.prochaine(E("a", 5, 12), AUJ) == date(2026, 11, 15)                             # à venir : telle quelle
    assert lg.prochaine(E("b", -20, 12), AUJ) == date(2027, 10, 21)                           # annuelle passée : l'an prochain
    assert lg.prochaine(E("c", -100, 1), AUJ) == date(2026, 12, 2)                           # mensuelle depuis le 2 août : le 2 décembre
    mensuelle = lg.Echeance("m", "2026-01-31", 1)
    assert lg.prochaine(mensuelle, date(2026, 3, 1)) == date(2026, 3, 31) and lg.prochaine(mensuelle, date(2026, 2, 28)) == date(2026, 2, 28)
    assert lg.prochaine(lg.Echeance("t", "2020-02-29", 24), AUJ) == date(2028, 2, 29)
    assert lg.prochaine(E("une fois", -3, 0), AUJ) == AUJ - timedelta(days=3)               # une fois : ne bouge pas
    assert lg.occurrences(lg.Echeance("m", "2026-11-15", 1), AUJ, AUJ + timedelta(days=60)) == [date(2026, 11, 15), date(2026, 12, 15)]
    assert lg.occurrences(lg.Echeance("u", "2026-11-15", 0), AUJ, AUJ + timedelta(days=3)) == []


def test_statuts_et_tri_et_resume():
    doc = lg.Document("€", [E("loin", 100, 12, 12.0), E("bientot", 20, 12, 600.0), E("urgent", 3, 1, 14.0, 7), E("retard", -4, 0, 80.0, 30),
                            E("aujourdhui", 0, 0, None, 5)])
    assert [lg.statut(e, AUJ) for e in doc.echeances] == ["ok", "bientot", "urgent", "retard", "urgent"]
    assert [e.nom for e in lg.trier(doc.echeances, AUJ)] == ["retard", "aujourdhui", "urgent", "bientot", "loin"]
    assert lg.statut(E("rappel zéro", 5, 0, None, 0), AUJ) == "ok" and lg.statut(E("rappel zéro", 0, 0, None, 0), AUJ) == "urgent"
    r = lg.resume(doc, AUJ)
    assert r["retards"] == 1 and r["sous30"] == 3 and round(r["montant30"], 2) == 614.0                 # 600 + 14 (une seule occurrence du mensuel dans 30 jours)
    assert round(r["montant365"], 2) == round(12 + 600 + 14 * 12, 2)                                    # le retard « une fois » est hors des 12 mois à venir
    assert lg.resume(lg.Document(), AUJ) == {"retards": 0, "sous30": 0, "montant30": 0, "montant365": 0}


def test_rappels_une_seule_fois_par_date():
    doc = lg.Document("€", [E("proche", 5, 12, 100.0, 30), E("loin", 90, 12), E("passe", -2, 0)])
    deja = {}
    a = lg.a_notifier(doc, AUJ, deja, "f1")
    assert sorted(e.nom for _c, e, _j in a) == ["passe", "proche"]
    assert lg.a_notifier(doc, AUJ, deja, "f1") == [] and lg.a_notifier(doc, AUJ + timedelta(days=1), deja, "f1") == []        # pas de répétition
    assert sorted(e.nom for _c, e, _j in lg.a_notifier(doc, AUJ, deja, "f2")) == ["passe", "proche"]       # une autre fiche : ses propres rappels
    assert lg.a_notifier(lg.Document("€", [lg.Echeance("proche", "2026-11-15", 12, 100.0, 30)]), date(2027, 11, 12), deja, "f1")                                                      # l'an d'après : une nouvelle notification
    anciennes = {"x|y|2020-01-01|rappel": "2020-01-01"}
    lg.a_notifier(lg.Document(), AUJ, anciennes, "f1")
    assert anciennes == {}                                                                  # les vieilles entrées sont oubliées
    m = lg.message(E("Assurance", 12, 12, 612.0), 12, AUJ)
    assert "Assurance" in m and "12 jour" in m and "22/11/2026" in m and "612 €" in m
    assert "dépassée depuis 2 jour" in lg.message(E("x", -2), -2, AUJ) and "aujourd'hui" in lg.message(E("x", 0), 0, AUJ)


def test_exemple_valide():
    (_t, _ti, texte), = lg.exemples(AUJ)
    d = lg.lire(texte)
    assert len(d.echeances) == 6 and lg.ecrire(d) == texte


# ---------- dans la vraie fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "echeances")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("echeances"), w.plugins.infos["echeances"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def test_vue_tableau_trie_colore_et_resume(fen):
    vue = fen.vues_types["echeances"]
    auj = date.today()
    f = lambda n: (auj + timedelta(days=n)).isoformat()                                       # noqa: E731
    textes = []
    vue.modifie.connect(textes.append)
    vue.charger(lg.ecrire(lg.Document("€", [lg.Echeance("Loin", f(200), 12, 12.0, 30), lg.Echeance("Retard", f(-3), 0, None, 30),
                                            lg.Echeance("Urgent", f(2), 12, 100.0, 30)])))
    assert [vue.table.item(i, 1).text() for i in range(3)] == ["Retard", "Urgent", "Loin"]
    assert vue.table.item(0, 0).text() == "En retard" and vue.table.item(0, 0).background().color().hue() == 0
    assert vue.table.item(1, 0).text() == "Urgent" and vue.table.item(2, 0).background().color().hue() == 120
    assert "il y a 3 j" in vue.table.item(0, 3).text() and vue.table.item(1, 3).text() == "2 j"
    assert "1 en retard" in vue.l_resume.text() and "100 €" in vue.l_resume.text()
    vue._supprimer(0)
    assert "Retard" not in textes[-1] and vue.table.rowCount() == 2
    vue.e_devise.setText("$")
    vue._devise()
    assert "devise: $" in textes[-1] and "100 $" in vue.l_resume.text()


def test_notifications_au_demarrage_une_seule_fois(fen, monkeypatch):
    p = fen.plugins.actifs["echeances"][0]
    auj = date.today()
    p.ctx.creer_fiche("Papiers", "Mes échéances", lg.ecrire(lg.Document("€", [
        lg.Echeance("Assurance", (auj + timedelta(days=6)).isoformat(), 12, 612.0, 30), lg.Echeance("Plus tard", (auj + timedelta(days=200)).isoformat(), 12)])))
    p.ctx.creer_fiche("Papiers", "Autre note", "du texte libre : sans rien")
    notes = []
    monkeypatch.setattr(p.ctx.ui, "notifier", lambda t, m: notes.append((t, m)))
    p.verifier()
    assert len(notes) == 1 and "Assurance" in notes[0][1] and "Plus tard" not in notes[0][1] and notes[0][0] == "Échéances"
    p.verifier()
    assert len(notes) == 1                                                                    # déjà signalée : rien de plus
    assert p.ctx.reglages.get("notifie")                                                      # mémorisé pour le prochain démarrage


def test_dialogue_ok_sans_nom_previent(monkeypatch, fen):
    """Clic sur OK avec un nom vide : un message explique (au lieu de ne rien faire)."""
    from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox
    vus = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: vus.append(a))
    import sys
    import scrinium.core.plugins  # noqa: F401
    mod = sys.modules["scrinium_plugin_echeances"]
    d = mod.DialogueEcheance(None)
    d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    assert vus and d.result() == 0
    d.nom.setText("Assurance")
    d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    assert d.result() == 1 and d.resultat().nom == "Assurance"
