# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Partage dans la vraie fenêtre : menu, refus des fiches verrouillées, et le scénario d'invitation de bout en bout
(propriétaire invite, la personne colle le lien, crée son compte, reçoit la fiche) contre le vrai serveur PHP."""
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from scrinium.core.depots import Depot, enregistrer_depot, lire_depots  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "partage"


@pytest.fixture
def messages(monkeypatch):
    """Aucune boîte de dialogue bloquante : on note ce qui aurait été affiché."""
    vus = []
    for nom in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, nom, staticmethod(lambda p, titre, texte, *a, _n=nom, **k: vus.append((_n, texte))))
    return vus


def _fenetre(tmp_path, monkeypatch, nom):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setitem(sys.modules, "keyring", None)
    s = Store(Paths(tmp_path / nom))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "partage")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("partage"), w.plugins.infos["partage"].erreur
    return w, w.plugins.actifs["partage"][0]


def test_menu_et_fiche_verrouillee(tmp_path, monkeypatch, messages):
    w, p = _fenetre(tmp_path, monkeypatch, "a")
    textes = [a.text() for a in w.menu_ext.actions()]
    for attendu in ("Partager la fiche…", "Rejoindre un partage…", "Synchroniser les partages", "Serveurs de partage…"):
        assert attendu in textes
    p.synchroniser_tout()                                           # aucun serveur : explication, pas d'erreur
    assert messages and "Aucun serveur" in messages[-1][1]
    w.close()


def test_rejoindre_lien_invalide(tmp_path, monkeypatch, messages):
    from importlib import import_module  # noqa: F401
    w, p = _fenetre(tmp_path, monkeypatch, "a")
    d = sys.modules[type(p).__module__].DialogueRejoindre(p)
    d.lien.setText("bonjour")
    d._verifier()
    assert "lien d'invitation" in d.info.text() and not d.ok.isEnabled()
    w.close()


def test_scenario_invitation(php, tmp_path, monkeypatch, messages):
    mod = None
    wa, pa = _fenetre(tmp_path, monkeypatch, "jfk-poste")
    mod = sys.modules[type(pa).__module__]
    pa.secret.ecrire(f"jfk@{php}", "motdepasse-jfk", False)
    enregistrer_depot(pa.store, Depot("srv", php, "jfk"))
    th = pa.store.nouveau_theme("Travail")
    f = pa.store.nouvelle_fiche(th)
    pa.store.enregistrer(th, f, "Liste", "pain, lait")
    vue = pa.ctx.fiches("Travail")[0]

    # le propriétaire invite : le message contient le lien
    d = mod.DialoguePartager(pa, vue)
    capture = {}
    monkeypatch.setattr(mod.DialogueCourriel, "exec", lambda self: capture.update(email=self.email, texte=self.texte.toPlainText()) or 0)
    d.email.setText("dede@example.org")
    d.role.setCurrentIndex(1)
    d._inviter()
    assert capture["email"] == "dede@example.org" and "« Liste »" in capture["texte"] and "lire et modifier" in capture["texte"]
    lien = next(l for l in capture["texte"].splitlines() if "/inviter/" in l)
    d._rafraichir()
    assert d.invitations.count() == 1 and "en attente" in d.invitations.item(0).text()
    assert d.droits.count() == 1 and "propriétaire" in d.droits.item(0).text()

    # la personne invitée colle le lien et crée son compte
    wb, pb = _fenetre(tmp_path, monkeypatch, "dede-poste")
    r = mod.DialogueRejoindre(pb)
    r.lien.setText(lien)
    r._verifier()
    assert r.ok.isEnabled() and "jfk vous invite à lire et modifier" in r.info.text()
    r.compte.setText("dede2")
    r.mdp.setText("un-mot-de-passe-solide")
    r._rejoindre()
    assert [x.nom for x in lire_depots(pb.store)] and lire_depots(pb.store)[0].compte == "dede2"
    th_b = pb.store.theme("Partagées")
    assert th_b is not None and [x.titre for x in th_b.fiches] == ["Liste"]
    assert "pain, lait" in th_b.fiches[0].texte

    # le droit d'écriture marche dans les deux sens
    pb.store.enregistrer(th_b, th_b.fiches[0], "Liste", "pain, lait, thé")
    pb.synchroniser_depot(lire_depots(pb.store)[0])
    pa.synchroniser_depot(lire_depots(pa.store)[0])
    assert "thé" in f.texte

    # le lien ne sert qu'une fois
    wc, pc = _fenetre(tmp_path, monkeypatch, "autre-poste")
    r2 = mod.DialogueRejoindre(pc)
    r2.lien.setText(lien)
    r2._verifier()
    assert not r2.ok.isEnabled() and "introuvable" in r2.info.text().lower()
    for w in (wa, wb, wc):
        w.close()


def test_invitation_envoyee_par_le_plugin_courriel(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    appels = []

    class FauxCourriel:
        def envoyer_message(self, dest, sujet, corps):
            appels.append((dest, sujet, corps))
            return True

    class G:
        actifs = {"courriel": (FauxCourriel(), None)}

    class Ctx:
        _g = G()

    class P:
        ctx = Ctx()

    QApplication.instance() or QApplication([])
    import importlib.util
    spec = importlib.util.spec_from_file_location("scrinium_plugin_partage_test", RACINE / "__init__.py",
                                                  submodule_search_locations=[str(RACINE)])
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    d = mod.DialogueCourriel(P(), "a@b.fr", "Objet", "Corps")
    assert d.envoyer.isEnabled()
    d._envoyer()
    assert appels == [("a@b.fr", "Objet", "Corps")] and d.result() == 1
    G.actifs = {}
    assert not mod.DialogueCourriel(P(), "a@b.fr", "O", "C").envoyer.isEnabled()
