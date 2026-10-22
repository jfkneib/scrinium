# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
import json
import pytest

from scrinium.core.paths import Paths
from scrinium.core.plugins import API_VERSION, EVENEMENTS, Gestionnaire, MAX_ERREURS, Plugin
from scrinium.core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def faire_plugin(store, nom, code, api=API_VERSION, manifeste=None):
    d = store.paths.base / "plugins" / nom
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"titre": nom.title(), "version": "1.0", "description": "test",
                                                "auteur": "t", "classe": "P", "api": api, **(manifeste or {})}))
    (d / "__init__.py").write_text(code)
    return d


CODE_OK = '''
from scrinium.core.plugins import Plugin
VUES = []
class P(Plugin):
    def activer(self, ctx):
        self.ctx = ctx
        ctx.on("fiche_enregistree", lambda fiche, origine=None: VUES.append(fiche.titre))
    def desactiver(self):
        VUES.append("fin")
'''


def test_decouverte_sans_executer_le_code(store, tmp_path):
    marque = tmp_path / "execute"
    faire_plugin(store, "piege", f"open({str(marque)!r}, 'w').write('x')\nclass P: api = 1")
    g = Gestionnaire(store)
    g.decouvrir()
    assert "piege" in g.infos and g.infos["piege"].titre == "Piege"
    assert not marque.exists()           # rien n'est importé tant que l'utilisateur n'active pas


def test_desactive_par_defaut_et_persistance(store):
    faire_plugin(store, "ok", CODE_OK)
    g = Gestionnaire(store)
    g.demarrer()
    assert not g.actifs and g.actifs_reglage() == []
    assert g.activer("ok") and "ok" in g.actifs
    g2 = Gestionnaire(store)             # nouveau démarrage : l'extension revient
    g2.demarrer()
    assert "ok" in g2.actifs
    g2.desactiver("ok")
    assert Gestionnaire(store).actifs_reglage() == []


def test_evenements_et_vue_sans_cle(store):
    faire_plugin(store, "ok", CODE_OK)
    g = Gestionnaire(store)
    g.demarrer()
    g.activer("ok")
    th = store.theme("Perso")
    f = th.fiches[0]
    from scrinium.core.plugins import FicheVue
    vue = FicheVue(th, f)
    assert not hasattr(vue, "cle") and not hasattr(vue, "path") and vue.texte == f.texte
    g.emettre("fiche_enregistree", fiche=vue)
    import sys
    assert vue.titre in sys.modules["scrinium_plugin_ok"].VUES
    g.desactiver("ok")
    assert "fin" in sys.modules["scrinium_plugin_ok"].VUES


def test_vue_fiche_verrouillee_fermee(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "S", "secret")
    store.maj_meta(th, f, rappel="2026-01-01")
    store.verrouiller(th, f, "motdepasse")
    g = Gestionnaire(store)
    g.decouvrir()
    from scrinium.core.plugins import Contexte, FicheVue, InfoPlugin
    store.charger()
    th = store.theme("Perso")
    f2 = next(x for x in th.fiches if x.titre == "S")
    vue = FicheVue(th, f2)
    assert vue.fermee and vue.texte is None and vue.meta == {}
    ctx = Contexte(g, InfoPlugin("x", "x", "1", "", "", "dossier", lambda: None))
    with pytest.raises(ValueError):
        ctx.maj_meta(vue, rappel="x")


def test_api_incompatible_refusee(store):
    faire_plugin(store, "vieux", "from scrinium.core.plugins import Plugin\nclass P(Plugin):\n    api = 99\n")
    g = Gestionnaire(store)
    g.decouvrir()
    assert not g.activer("vieux")
    assert "API 99" in g.infos["vieux"].erreur and "vieux" not in g.actifs
    assert g.actifs_reglage() == []


def test_plugin_qui_plante_a_l_activation(store):
    faire_plugin(store, "casse", "from scrinium.core.plugins import Plugin\nclass P(Plugin):\n    def activer(self, ctx):\n        raise RuntimeError('boum')\n")
    g = Gestionnaire(store)
    g.decouvrir()
    assert not g.activer("casse")
    assert "boum" in g.infos["casse"].erreur and not g.actifs


def test_plugin_qui_plante_en_evenement_est_desactive(store):
    faire_plugin(store, "fragile", '''
from scrinium.core.plugins import Plugin
class P(Plugin):
    def activer(self, ctx):
        ctx.on("themes_modifies", self.mal)
    def mal(self, **kw):
        raise ValueError("oups")
''')
    vus = []
    g = Gestionnaire(store, sur_desactivation_auto=lambda nom, err: vus.append((nom, err)))
    g.decouvrir()
    g.activer("fragile")
    for _ in range(MAX_ERREURS):
        assert "fragile" in g.actifs
        g.emettre("themes_modifies")
    assert "fragile" not in g.actifs and vus and vus[0][0] == "fragile"
    assert "fragile" not in g.actifs_reglage()
    g.emettre("themes_modifies")          # l'application continue


def test_reglages_par_plugin(store):
    from scrinium.core.plugins import ReglagesPlugin
    a, b = ReglagesPlugin(store, "a"), ReglagesPlugin(store, "b")
    a.set("x", 1)
    b.set("x", 2)
    assert a.get("x") == 1 and b.get("x") == 2 and a.get("absent", 7) == 7


def test_evenement_inconnu_refuse(store):
    faire_plugin(store, "ev", "from scrinium.core.plugins import Plugin\nclass P(Plugin):\n    def activer(self, ctx):\n        ctx.on('nimporte', print)\n")
    g = Gestionnaire(store)
    g.decouvrir()
    assert not g.activer("ev") and "inconnu" in g.infos["ev"].erreur


def test_nom_de_dossier_invalide_ignore(store):
    faire_plugin(store, "Mauvais Nom", "class P: api = 1")
    faire_plugin(store, "bon", "from scrinium.core.plugins import Plugin\nclass P(Plugin): pass")
    g = Gestionnaire(store)
    assert list(g.decouvrir()) == ["bon"]


def test_dossier_donnees_propre_a_l_extension(store):
    faire_plugin(store, "ok", CODE_OK)
    g = Gestionnaire(store)
    g.demarrer()
    g.activer("ok")
    d = g.actifs["ok"][1].dossier_donnees
    assert d == store.paths.base / "plugins-donnees" / "ok" and not d.exists()   # créé seulement à la demande


def test_api_pieces_jointes(store):
    code = '''
from scrinium.core.plugins import Plugin
EVTS = []
class P(Plugin):
    def activer(self, ctx):
        self.ctx = ctx
        for e in ("piece_jointe_ajoutee", "piece_jointe_supprimee", "piece_jointe_modifiee"):
            ctx.on(e, lambda e=e, **kw: EVTS.append((e, kw["piece"].id, kw.get("origine"))))
'''
    faire_plugin(store, "ocr", code)
    th = store.nouveau_theme("T")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Fiche", "x")
    store.ajouter_piece(f, "a.png", "image/png", b"\x89PNG-xx")
    g = Gestionnaire(store)
    g.demarrer()
    assert g.activer("ocr")
    ctx = g.actifs["ocr"][1]
    vue = next(v for v in ctx.fiches() if v.titre == "Fiche")
    (pv,) = ctx.pieces(vue)
    assert (pv.id, pv.nom, pv.type, pv.ocr) == (1, "a.png", "image/png", "")
    assert ctx.lire_piece(vue, pv) == b"\x89PNG-xx" and ctx.lire_piece(vue, 1) == b"\x89PNG-xx"
    ctx.maj_piece(vue, pv, ocr="texte lu", ocr_moteur="tesseract")
    assert ctx.pieces(vue)[0].ocr == "texte lu" and ctx.pieces(vue)[0].ocr_moteur == "tesseract"
    import sys
    assert ("piece_jointe_modifiee", 1, "ocr") in sys.modules["scrinium_plugin_ocr"].EVTS
    with pytest.raises(ValueError):
        ctx.lire_piece(vue, 99)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    f.texte = f.cle = f.salt = None                       # fiche verrouillée fermée : rien n'est accessible
    assert ctx.pieces(vue) == []
    with pytest.raises(ValueError):
        ctx.lire_piece(vue, 1)
    with pytest.raises(ValueError):
        ctx.maj_piece(vue, 1, ocr="x")


# ---------- extensions officielles (livrées avec Scrinium) ----------
def faire_officiel(racine, nom, titre="Officielle", code="from scrinium.core.plugins import Plugin\nclass P(Plugin): api = 1\n"):
    d = racine / nom
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"titre": titre, "version": "9", "description": "livrée", "auteur": "Scrinium", "classe": "P", "api": 1}))
    (d / "__init__.py").write_text(code)
    return d


def test_extensions_officielles_decouvertes_mais_desactivees(store, tmp_path):
    off = tmp_path / "off"
    faire_officiel(off, "dictee", "Dictée")
    faire_officiel(off, "hello", "Exemple")                                   # un exemple n'est jamais proposé
    g = Gestionnaire(store, officiels=[off])
    g.demarrer()
    assert list(g.infos) == ["dictee"] and g.infos["dictee"].source == "officielle" and g.infos["dictee"].titre == "Dictée"
    assert not g.actifs and g.actifs_reglage() == []                           # désactivée tant que l'utilisateur ne l'a pas activée
    assert g.activer("dictee") and "dictee" in g.actifs


def test_decouverte_officielle_n_execute_rien(store, tmp_path):
    marque = tmp_path / "execute"
    faire_officiel(tmp_path / "off", "piege", code=f"open({str(marque)!r}, 'w').write('x')\nclass P: api = 1")
    Gestionnaire(store, officiels=[tmp_path / "off"]).decouvrir()
    assert not marque.exists()                                                  # lister ≠ importer


def test_le_dossier_utilisateur_prime_sur_l_officielle(store, tmp_path):
    faire_officiel(tmp_path / "off", "ocr", "Version fournie")
    faire_plugin(store, "ocr", CODE_OK, manifeste={"titre": "Ma copie"})
    g = Gestionnaire(store, officiels=[tmp_path / "off"])
    g.decouvrir()
    assert g.infos["ocr"].source == "dossier" and g.infos["ocr"].titre == "Ma copie"      # la copie de l'utilisateur remplace la version fournie


def test_officielles_sans_manifeste_ou_nom_invalide_ignorees(store, tmp_path):
    off = tmp_path / "off"
    (off / "sans-manifeste").mkdir(parents=True)
    faire_officiel(off, "Mauvais Nom")
    faire_officiel(off, "bon")
    (off / "casse").mkdir()
    (off / "casse" / "plugin.json").write_text("{pas du json")
    g = Gestionnaire(store, officiels=[off])
    g.decouvrir()
    assert list(g.infos) == ["bon"]
    assert Gestionnaire(store, officiels=[tmp_path / "inexistant"]).decouvrir() == {}


def test_dossiers_officiels_reels_du_depot():
    from scrinium.core import plugins
    dossiers = plugins.dossiers_officiels_reels()
    noms = {p.name for d in dossiers for p in d.iterdir() if (p / "plugin.json").is_file()}
    assert {"capture", "courriel", "dictee", "ocr", "traduction"} <= noms
    assert all((p / "plugin.json").is_file() for d in dossiers for p in d.iterdir() if p.is_dir() and p.name in noms)


def test_les_cinq_extensions_du_depot_se_decouvrent_et_se_chargent(store):
    from scrinium.core import plugins
    g = Gestionnaire(store, officiels=plugins.dossiers_officiels_reels())
    g.decouvrir()
    assert {"capture", "courriel", "dictee", "ocr", "traduction"} <= set(g.infos) and "hello" not in g.infos
    for nom in ("capture", "courriel", "dictee", "ocr", "traduction"):
        info = g.infos[nom]
        assert info.source == "officielle" and info.api == 1 and info.titre and info.description and info.version     # manifestes complets


# ---------- extensions réservées à certains systèmes ----------
def test_plateformes_lues_sans_executer_le_code(store, tmp_path, monkeypatch):
    marque = tmp_path / "execute"
    faire_plugin(store, "linuxseul", f"open({str(marque)!r}, 'w').write('x')\n" + CODE_OK, manifeste={"plateformes": ["Linux"]})
    faire_plugin(store, "partout", CODE_OK)
    g = Gestionnaire(store)
    g.decouvrir()
    assert g.infos["linuxseul"].plateformes == ("linux",) and g.infos["partout"].plateformes == ()
    assert not marque.exists()                                                    # la découverte ne charge rien


def test_extension_linux_seulement_refusee_sous_windows_sans_importer_son_code(store, tmp_path, monkeypatch):
    marque = tmp_path / "execute"
    faire_plugin(store, "linuxseul", f"open({str(marque)!r}, 'w').write('x')\n" + CODE_OK, manifeste={"plateformes": ["linux"]})
    g = Gestionnaire(store)
    g.decouvrir()
    monkeypatch.setattr("scrinium.core.plugins.systeme_courant", lambda: "windows")
    info = g.infos["linuxseul"]
    assert not info.disponible and "Windows" in info.indisponibilite() and "Linux" in info.indisponibilite()
    assert g.activer("linuxseul") is False and "Windows" in info.erreur
    assert not marque.exists() and "linuxseul" not in g.actifs                    # son code n'a jamais été importé
    assert "linuxseul" not in g.actifs_reglage()                                  # et le choix n'est pas enregistré comme actif
    monkeypatch.setattr("scrinium.core.plugins.systeme_courant", lambda: "linux")
    assert info.disponible and g.activer("linuxseul") is True and marque.exists()


def test_extension_sans_plateformes_marche_partout(store, monkeypatch):
    faire_plugin(store, "partout", CODE_OK)
    g = Gestionnaire(store)
    g.decouvrir()
    for systeme in ("linux", "windows", "macos"):
        monkeypatch.setattr("scrinium.core.plugins.systeme_courant", lambda s=systeme: s)
        assert g.infos["partout"].disponible and g.infos["partout"].indisponibilite() == ""


def test_choix_enregistre_d_une_extension_indisponible_ignore_au_demarrage(store, monkeypatch):
    faire_plugin(store, "linuxseul", CODE_OK, manifeste={"plateformes": ["linux"]})
    store.sauver_reglages(plugins_actifs=["linuxseul"])                           # ex. réglages copiés depuis un ordinateur Linux
    monkeypatch.setattr("scrinium.core.plugins.systeme_courant", lambda: "windows")
    g = Gestionnaire(store)
    g.demarrer()
    assert "linuxseul" not in g.actifs and g.infos["linuxseul"].erreur             # ignorée sans bruit, avec la raison
    assert store.reglages()["plugins_actifs"] == ["linuxseul"]                     # le choix reste noté pour un retour sous Linux


def test_extensions_officielles_linux_seulement_declarees():
    import json
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent / "plugins"
    for nom in ("dictee", "lecture", "capture"):                                    # enregistrement audio / Konsole : Linux
        assert json.loads((racine / nom / "plugin.json").read_text(encoding="utf-8"))["plateformes"] == ["linux"]
    for nom in ("agenda", "applications", "courriel", "ocr", "traduction"):
        assert "plateformes" not in json.loads((racine / nom / "plugin.json").read_text(encoding="utf-8"))
