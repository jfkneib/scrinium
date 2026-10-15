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
