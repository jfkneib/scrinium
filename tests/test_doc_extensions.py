# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Thème « Doc » (comment écrire une extension) : contenu exact, exemples de code valides, création sans écrasement."""
import json
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium import i18n  # noqa: E402
from scrinium.core import doc_extensions  # noqa: E402
from scrinium.core.plugins import EVENEMENTS  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811

DOSSIER = Path("/home/x/.local/share/scrinium/plugins")


@pytest.fixture
def langue_remise():
    avant = i18n.langue()
    yield
    i18n.init(avant)


def _blocs(texte, langage):
    return re.findall(r"```" + langage + r"\n(.*?)```", texte, re.S)


def test_sept_fiches_avec_le_dossier_des_extensions():
    fiches = doc_extensions.fiches(DOSSIER)
    assert [t[:12] for t, _x in fiches] == [f"Extensions {i}" for i in range(1, 8)]
    assert str(DOSSIER) in fiches[0][1] and "%s" not in fiches[0][1]


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_les_exemples_de_code_sont_valides(langue, langue_remise):
    i18n.init(langue)
    for titre, texte in doc_extensions.fiches(DOSSIER):
        for code in _blocs(texte, "python"):
            compile(code, titre, "exec")                                     # syntaxe correcte
        for brut in _blocs(texte, "json"):
            meta = json.loads(brut)
            assert meta["api"] == 1 and meta["classe"] == "BonjourPlugin"


def test_le_premier_plugin_fonctionne_vraiment(tmp_path):
    """Le plugin de la fiche 2 est copié tel quel et doit se charger et s'activer."""
    from scrinium.core.paths import Paths
    from scrinium.core.plugins import Gestionnaire
    from scrinium.core.store import Store
    fiche = doc_extensions.fiches(DOSSIER)[1][1]
    json_p, code = _blocs(fiche, "json")[0], _blocs(fiche, "python")[0]
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    d = s.paths.base / "plugins" / "bonjour"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json_p, encoding="utf-8")
    (d / "__init__.py").write_text(code, encoding="utf-8")
    g = Gestionnaire(s, officiels=[])
    g.decouvrir()
    assert g.activer("bonjour", persister=False), g.infos["bonjour"].erreur


def test_la_doc_cite_les_vrais_evenements_et_methodes():
    tout = "\n".join(t for _x, t in doc_extensions.fiches(DOSSIER))
    for evt in EVENEMENTS:
        assert evt in tout, evt
    for nom in ("ajouter_action", "ajouter_bouton", "ajouter_panneau", "ajouter_action_image", "notifier", "planifier",
                "inserer_texte", "texte_selectionne", "remplacer_tout", "ajouter_a_la_fin", "afficher_fiche",
                "assurer_identifiant", "maj_meta", "lire_piece", "dossier_donnees", "reglages"):
        assert nom in tout, nom


def test_present_au_premier_lancement(fen):  # noqa: F811
    th = fen.store.theme("Doc")
    assert th is not None and len(th.fiches) == 7 and th.icone == "preferences-plugin"


def test_menu_aide_cree_rouvre_sans_ecraser(fen):  # noqa: F811
    for t in list(fen.store.themes):
        if t.nom == "Doc":
            fen.store.supprimer_theme(t)
    fen.maj_themes()
    fen.doc_extensions()
    th = fen.store.theme("Doc")
    assert len(th.fiches) == 7 and fen.theme == "Doc" and fen.fiche.titre.startswith("Extensions 1")
    f = next(x for x in th.fiches if x.titre.startswith("Extensions 3"))
    fen.store.enregistrer(th, f, f.titre, "ma version personnelle")           # l'utilisateur a modifié une fiche
    f2 = next(x for x in th.fiches if x.titre.startswith("Extensions 6"))
    fen.store.supprimer_fiche(th, f2)                                          # et en a supprimé une
    fen.doc_extensions()
    th = fen.store.theme("Doc")
    assert len(th.fiches) == 7                                                 # la supprimée est recréée, rien n'est doublé
    assert next(x for x in th.fiches if x.titre.startswith("Extensions 3")).texte == "ma version personnelle"
