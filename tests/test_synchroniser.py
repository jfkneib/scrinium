# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Synchronisation de bout en bout (sans réseau) : trois personnes (jfk propriétaire, dede en écriture, alphonse en lecture) avec
leur propre Scrinium, un serveur de référence en mémoire. Vérifie surtout que RIEN n'est perdu ni écrasé en silence."""
import pytest

from scrinium.core import synchro
from scrinium.core.paths import Paths
from scrinium.core.store import Store
from scrinium.core.synchroniser import lire_contenu, partager, publier, synchroniser
from scrinium.core.transport import ErreurTransport, Injoignable, ServeurMemoire

PNG = b"\x89PNG\r\n\x1a\n" + b"IMG" * 30
QUAND = "2026-10-29 10:00"


class Poste:
    """Le Scrinium d'une personne : ses fiches, son état de synchronisation, son accès au serveur."""

    def __init__(self, tmp_path, serveur, compte):
        self.compte = compte
        self.store = Store(Paths(tmp_path / compte))
        self.store.charger()
        self.etat = synchro.EtatSynchro(synchro.chemin_etat(self.store, "serveur")).charger()
        self.transport = serveur.pour(compte)

    def sync(self):
        return synchroniser(self.store, self.etat, self.transport, maintenant=QUAND)

    def fiche(self, titre, theme="Partagées"):
        for th in self.store.themes:
            for f in th.fiches:
                if f.titre == titre and th.nom == theme:
                    return th, f
        raise AssertionError(f"{self.compte} : fiche « {titre} » introuvable dans « {theme} » : "
                             f"{[(t.nom, f.titre) for t in self.store.themes for f in t.fiches]}")

    def tous_les_titres(self):
        """Titres des fiches de test (le premier lancement crée aussi des fiches d'exemple, qu'on laisse de côté)."""
        return sorted(f.titre for t in self.store.themes if t.nom in ("Partagées", "Travail", "Autre") for f in t.fiches)


@pytest.fixture
def monde(tmp_path):
    srv = ServeurMemoire(["jfk", "dede", "alphonse"])
    return srv, Poste(tmp_path, srv, "jfk"), Poste(tmp_path, srv, "dede"), Poste(tmp_path, srv, "alphonse")


def jfk_cree(jfk, titre="Plan", texte="Version de jfk."):
    th = jfk.store.nouveau_theme("Travail") if jfk.store.theme("Travail") is None else jfk.store.theme("Travail")
    f = jfk.store.nouvelle_fiche(th)
    jfk.store.enregistrer(th, f, titre, texte)
    return th, f


def partage_complet(jfk):
    th, f = jfk_cree(jfk)
    partager(jfk.store, jfk.etat, jfk.transport, th, f, "dede", "ecriture")
    partager(jfk.store, jfk.etat, jfk.transport, th, f, "alphonse", "lecture")
    return th, f


def test_publier_puis_recevoir(monde):
    srv, jfk, dede, alphonse = monde
    th, f = jfk_cree(jfk)
    assert dede.sync().vide                                                   # rien n'est partagé : rien ne arrive
    partager(jfk.store, jfk.etat, jfk.transport, th, f, "dede", "ecriture")
    assert Store.id_fiche(f) and jfk.etat.suivi(Store.id_fiche(f)) and srv.ecritures == 1
    b = dede.sync()
    assert b.nouvelles == ["Plan"] and not b.erreurs
    _, recue = dede.fiche("Plan")                                              # arrivée dans le thème « Partagées »
    assert recue.texte == "Version de jfk." and Store.id_fiche(recue) == Store.id_fiche(f)
    assert alphonse.sync().vide and alphonse.tous_les_titres() == []         # non partagée avec Alphonse : il ne voit rien


def test_aller_retour_ecriture_et_lecture_seule(monde):
    srv, jfk, dede, alphonse = monde
    th, f = partage_complet(jfk)
    dede.sync()
    alphonse.sync()
    # Dédé (écriture) modifie : le serveur passe à la version 2, jfk et Alphonse la reçoivent
    th_d, fd = dede.fiche("Plan")
    dede.store.enregistrer(th_d, fd, "Plan", "Version de dédé.")
    assert dede.sync().envoyees == ["Plan"]
    assert jfk.sync().recues == ["Plan"] and f.texte == "Version de dédé."
    assert alphonse.sync().recues == ["Plan"]
    # Alphonse (lecture seule) modifie : rien n'est envoyé, sa modification est gardée à part, la fiche revient à la version du serveur
    th_a, fa = alphonse.fiche("Plan")
    alphonse.store.enregistrer(th_a, fa, "Plan", "Je n'ai pas le droit.")
    ecritures = srv.ecritures
    b = alphonse.sync()
    assert b.ecartees == [("Plan", "Plan (copie locale 2026-10-29 10:00)")] and not b.envoyees
    assert srv.ecritures == ecritures and srv.fiches[Store.id_fiche(f)]["texte"] == "Version de dédé."    # le serveur n'a rien reçu
    assert fa.texte == "Version de dédé."
    assert alphonse.fiche("Plan (copie locale 2026-10-29 10:00)")[1].texte == "Je n'ai pas le droit."     # rien n'est perdu


def test_conflit_le_premier_a_enregistrer_gagne_l_autre_garde_sa_version(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    dede.sync()
    th_d, fd = dede.fiche("Plan")
    jfk.store.enregistrer(th, f, "Plan", "Modification de jfk.")             # tous deux modifient SANS se synchroniser
    dede.store.enregistrer(th_d, fd, "Plan", "Modification de dédé.")
    assert jfk.sync().envoyees == ["Plan"]                                    # jfk enregistre le premier : version 2
    b = dede.sync()
    assert b.conflits == [("Plan", "Plan (conflit 2026-10-29 10:00)")] and not b.envoyees
    assert fd.texte == "Modification de jfk."                                 # la fiche de dédé a repris la version du serveur
    assert dede.fiche("Plan (conflit 2026-10-29 10:00)")[1].texte == "Modification de dédé."       # et sa version est gardée
    assert srv.fiches[Store.id_fiche(f)]["texte"] == "Modification de jfk." and srv.fiches[Store.id_fiche(f)]["version"] == 2
    assert dede.sync().vide and jfk.sync().vide                                # puis plus rien : la copie de conflit n'est pas partagée


def test_version_perimee_detectee_a_l_envoi(monde, monkeypatch):
    """Le serveur fait foi : même si la liste est périmée, l'écriture est refusée et le conflit résolu sans perte."""
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    dede.sync()
    th_d, fd = dede.fiche("Plan")
    jfk.store.enregistrer(th, f, "Plan", "Version 2 de jfk.")
    jfk.sync()
    dede.store.enregistrer(th_d, fd, "Plan", "Ma version.")
    anciennes = dede.transport.lister()                                        # (la liste que dédé a vue avant la publication de jfk)
    anciennes = [type(r)(r.id, 1, r.titre, r.role, r.proprietaire) for r in anciennes]
    monkeypatch.setattr(dede.transport, "lister", lambda: anciennes)
    b = dede.sync()
    assert [c[0] for c in b.conflits] == ["Plan"] and fd.texte == "Version 2 de jfk."
    assert dede.fiche("Plan (conflit 2026-10-29 10:00)")[1].texte == "Ma version."


def test_les_deux_ont_modifie_a_l_identique(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    dede.sync()
    th_d, fd = dede.fiche("Plan")
    jfk.store.enregistrer(th, f, "Plan", "Texte commun.")
    dede.store.enregistrer(th_d, fd, "Plan", "Texte commun.")
    jfk.sync()
    b = dede.sync()
    assert b.alignees == ["Plan"] and not b.conflits and dede.tous_les_titres() == ["Plan"]


def test_images_jointes_voyagent(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    jfk.store.ajouter_piece(f, "schema.png", "image/png", PNG)
    assert jfk.sync().envoyees == ["Plan"]
    dede.sync()
    _, fd = dede.fiche("Plan")
    (p,) = dede.store.lister_pieces(fd)
    assert p.nom == "schema.png" and dede.store.lire_piece(fd, p) == PNG


def test_idempotent(monde):
    srv, jfk, dede, _ = monde
    partage_complet(jfk)
    dede.sync()
    avant = srv.ecritures
    for poste in (jfk, dede, jfk, dede):
        assert poste.sync().vide
    assert srv.ecritures == avant and srv.fiches[next(iter(srv.fiches))]["version"] == 1


def test_droit_retire_la_fiche_reste_mais_n_est_plus_suivie(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    dede.sync()
    jfk.transport.retirer_droit(Store.id_fiche(f), "dede")
    b = dede.sync()
    assert b.disparues == ["Plan"] and dede.fiche("Plan")[1].texte == "Version de jfk."                    # conservée localement
    assert not dede.etat.suivi(Store.id_fiche(f))
    assert dede.sync().vide                                                                               # signalée une seule fois
    jfk.transport.partager(Store.id_fiche(f), "dede", "lecture")                                          # le droit est rendu plus tard
    b = dede.sync()
    assert b.nouvelles == [] and b.erreurs == [] and dede.tous_les_titres() == ["Plan"]                  # rattachée, pas dupliquée


def test_suppression_locale_jamais_propagee(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    dede.sync()
    th_d, fd = dede.fiche("Plan")
    dede.store.a_la_corbeille(fd.path)
    relu = Store(dede.store.paths)
    relu.charger()
    dede.store = relu
    b = dede.sync()
    assert b.supprimees_ici == ["Plan"] and Store.id_fiche(f) in srv.fiches                              # le serveur n'a pas bougé
    assert jfk.sync().vide


def test_fiche_verrouillee_ignoree(monde):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    jfk.store.verrouiller(th, f, "secret", sans_secours=True)                                            # suivie, puis verrouillée
    ecritures = srv.ecritures
    assert jfk.sync().ignorees == ["Plan"] and srv.ecritures == ecritures
    relu = Store(jfk.store.paths)
    relu.charger()
    jfk.store = relu                                                                                      # fermée
    assert jfk.sync().ignorees == ["Plan"] and srv.ecritures == ecritures
    th2 = jfk.store.nouveau_theme("Autre")
    g = jfk.store.nouvelle_fiche(th2)
    jfk.store.enregistrer(th2, g, "Secrète", "x")
    jfk.store.verrouiller(th2, g, "secret", sans_secours=True)
    with pytest.raises(ValueError):
        publier(jfk.store, jfk.etat, jfk.transport, th2, g)                                               # jamais publiée


def test_panne_globale_interrompt_mais_conserve_ce_qui_est_fait(monde, monkeypatch):
    srv, jfk, dede, _ = monde
    partage_complet(jfk)
    dede.sync()
    th_d, fd = dede.fiche("Plan")
    dede.store.enregistrer(th_d, fd, "Plan", "Modif hors ligne.")
    monkeypatch.setattr(dede.transport, "lister", lambda: (_ for _ in ()).throw(Injoignable("réseau coupé")))
    with pytest.raises(Injoignable):
        dede.sync()
    assert fd.texte == "Modif hors ligne."                                                                # rien n'a été touché
    monkeypatch.undo()
    assert dede.sync().envoyees == ["Plan"]                                                               # au retour du réseau, tout part


def test_incident_propre_a_une_fiche_ne_bloque_pas_les_autres(monde, monkeypatch):
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    th2, g = jfk_cree(jfk, "Autre", "autre")
    partager(jfk.store, jfk.etat, jfk.transport, th2, g, "dede", "ecriture")
    dede.sync()
    for titre in ("Plan", "Autre"):
        t, x = dede.fiche(titre)
        dede.store.enregistrer(t, x, titre, "modifiée " + titre)
    reel = dede.transport.ecrire

    def capricieux(ident, contenu, version):
        if contenu.titre == "Plan":
            raise ErreurTransport("incident")
        return reel(ident, contenu, version)
    monkeypatch.setattr(dede.transport, "ecrire", capricieux)
    b = dede.sync()
    assert b.envoyees == ["Autre"] and b.erreurs == [("Plan", "incident")]


def test_rattachement_d_une_fiche_deja_locale_sans_ecraser(monde):
    """Mon état de synchronisation est perdu : la fiche locale et celle du serveur sont comparées, pas écrasées."""
    srv, jfk, dede, _ = monde
    th, f = partage_complet(jfk)
    jfk.store.enregistrer(th, f, "Plan", "Texte local différent.")
    jfk.etat.oublier(Store.id_fiche(f))                                                                   # état perdu
    b = jfk.sync()
    assert [c[0] for c in b.conflits] == ["Plan"] and f.texte == "Version de jfk."
    assert jfk.fiche("Plan (conflit 2026-10-29 10:00)", "Travail")[1].texte == "Texte local différent."


def test_contenu_local_lisible_et_etat_enregistre(monde):
    srv, jfk, dede, _ = monde
    th, f = jfk_cree(jfk)
    jfk.store.ajouter_piece(f, "a.png", "image/png", PNG)
    c = lire_contenu(jfk.store, f)
    assert (c.titre, c.texte, c.pieces) == ("Plan", "Version de jfk.", [("a.png", "image/png", PNG)])
    publier(jfk.store, jfk.etat, jfk.transport, th, f)
    relu = synchro.EtatSynchro(synchro.chemin_etat(jfk.store, "serveur")).charger()
    assert relu.entrees == jfk.etat.entrees and relu.entrees[Store.id_fiche(f)]["version"] == 1          # état écrit sur le disque
