# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Conflits de synchronisation : table de décision, mise de côté de la version locale, reprise de la version distante,
rien de perdu, rien d'envoyé en lecture seule."""
import pytest

from scrinium.core import conflits, synchro
from scrinium.core.conflits import ContenuDistant, decider
from scrinium.core.paths import Paths
from scrinium.core.store import Store

PNG_A = b"\x89PNG\r\n\x1a\n" + b"A" * 80
PNG_B = b"\x89PNG\r\n\x1a\n" + b"B" * 80


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def suivie(store, titre="Plan", texte="Texte de départ.", version=1):
    th = store.nouveau_theme("Partage")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, titre, texte)
    e = synchro.EtatSynchro(synchro.chemin_etat(store, "serveur")).charger()
    e.valider(store, th, f, version)
    return th, f, e


def test_table_de_decision():
    base = {"version": 5}
    assert decider(base, False, 5, "ecriture") == "rien"
    assert decider(base, False, 6, "lecture") == "recevoir"                     # distant plus récent, rien de local
    assert decider(base, True, 5, "proprietaire") == "envoyer"
    assert decider(base, True, 5, "ecriture") == "envoyer"
    assert decider(base, True, 5, "lecture") == "ecarter"                       # lecture seule : jamais envoyé
    assert decider(base, True, 6, "ecriture") == "conflit"
    assert decider(base, True, 6, "lecture") == "conflit"
    assert decider(base, True, 6, "ecriture", "abc", "abc") == "aligner"       # modifiées à l'identique des deux côtés
    assert decider(base, True, 6, "ecriture", "abc", "def") == "conflit"
    assert decider({}, False, 1, "ecriture") == "recevoir"                      # entrée sans version : tout est plus récent


def test_conflit_garde_les_deux_versions(store):
    th, f, e = suivie(store)
    store.ajouter_piece(f, "local.png", "image/png", PNG_A)
    e.valider(store, th, f, 1)                                                  # base : texte de départ + une image
    store.enregistrer(th, f, f.titre, "Ma version locale.")                     # je modifie ...
    store.ajouter_piece(f, "locale2.png", "image/png", PNG_B)
    distant = ContenuDistant(version=2, titre="Plan (révisé)", texte="La version de Dédé.", pieces=[("dede.png", "image/png", PNG_B)])
    action = decider(e.entrees[Store.id_fiche(f)], True, distant.version, "ecriture")
    assert action == "conflit"
    th_c, copie = conflits.resoudre(store, e, th, f, distant, maintenant="2026-10-27 15:00")
    # la fiche d'origine a repris la version distante (même identifiant, même suivi)
    assert (f.titre, f.texte) == ("Plan (révisé)", "La version de Dédé.")
    assert [p.nom for p in store.lister_pieces(f)] == ["dede.png"] and store.lire_piece(f, store.lister_pieces(f)[0]) == PNG_B
    assert e.entrees[Store.id_fiche(f)]["version"] == 2 and synchro.detecter(store, e) == []      # à jour : plus rien à envoyer
    # ma version est intacte dans une fiche à part, non partagée
    assert copie.titre == "Plan (conflit 2026-10-27 15:00)" and copie.texte == "Ma version locale."
    assert sorted(p.nom for p in store.lister_pieces(copie)) == ["local.png", "locale2.png"]
    assert Store.id_fiche(copie) is None and not e.suivi(Store.id_fiche(copie) or "")
    assert store.ids_en_double() == {}


def test_lecture_seule_met_la_modification_locale_de_cote(store):
    th, f, e = suivie(store)
    store.enregistrer(th, f, f.titre, "Je n'ai pas le droit d'écrire ici.")
    assert decider(e.entrees[Store.id_fiche(f)], True, 1, "lecture") == "ecarter"
    th_c, copie = conflits.resoudre(store, e, th, f, ContenuDistant(1, "Plan", "Texte de départ."), motif="copie locale",
                                    maintenant="2026-10-27 15:01")
    assert f.texte == "Texte de départ." and copie.titre == "Plan (copie locale 2026-10-27 15:01)"
    assert copie.texte == "Je n'ai pas le droit d'écrire ici."                  # rien n'est perdu
    assert synchro.detecter(store, e) == []


def test_reception_simple(store):
    th, f, e = suivie(store)
    avant = len(th.fiches)
    ident = conflits.appliquer_distant(store, e, th, f, ContenuDistant(2, "Plan v2", "Mis à jour ailleurs."))
    assert (f.titre, f.texte) == ("Plan v2", "Mis à jour ailleurs.") and ident == Store.id_fiche(f)
    assert len(th.fiches) == avant and e.entrees[ident]["version"] == 2 and synchro.detecter(store, e) == []


def test_anciennes_images_a_la_corbeille(store):
    th, f, e = suivie(store)
    store.ajouter_piece(f, "ancienne.png", "image/png", PNG_A)
    conflits.appliquer_distant(store, e, th, f, ContenuDistant(2, f.titre, f.texte))
    assert store.lister_pieces(f) == []
    noms = [x.name for x in store.paths.corbeille.iterdir()]
    assert any(n.endswith("-Plan.pj-1.png") for n in noms)                      # l'image remplacée est à la corbeille, pas effacée


def test_fiche_verrouillee_refusee(store):
    th, f, e = suivie(store)
    store.verrouiller(th, f, "secret", sans_secours=True)
    for appel in (lambda: conflits.mettre_de_cote(store, th, f), lambda: conflits.appliquer_distant(store, e, th, f, ContenuDistant(2, "t", "x")),
                  lambda: conflits.resoudre(store, e, th, f, ContenuDistant(2, "t", "x"))):
        with pytest.raises(ValueError):
            appel()
    assert f.verrou and len(th.fiches) == 1                                     # rien n'a été créé


def test_echec_de_la_copie_laisse_l_original_intact(store, monkeypatch):
    th, f, e = suivie(store)
    store.enregistrer(th, f, f.titre, "Ma version.")
    monkeypatch.setattr(store, "nouvelle_fiche", lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein")))
    with pytest.raises(OSError):
        conflits.resoudre(store, e, th, f, ContenuDistant(2, "Plan", "Distante."))
    assert f.texte == "Ma version." and e.entrees[Store.id_fiche(f)]["version"] == 1       # ni écrasée, ni marquée à jour
