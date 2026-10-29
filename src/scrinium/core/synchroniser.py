# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Synchronisation d'un dépôt partagé : met d'accord les fiches locales suivies et le serveur, par un `Transport`.

Un passage (`synchroniser`) :
  1. liste ce que le serveur me donne ; 2. reçoit les fiches nouvellement partagées avec moi (dans le thème d'arrivée) ;
  3. pour chaque fiche suivie, compare base / local / distant (voir `conflits.decider`) et envoie, reçoit, aligne ou résout un conflit ;
  4. enregistre l'état de synchronisation, même si un incident interrompt le passage (ce qui est fait reste fait).
Ce qu'on ne fait JAMAIS tout seul : supprimer une fiche locale parce qu'elle a disparu du serveur, supprimer une fiche du serveur
parce qu'elle a disparu d'ici, envoyer un contenu verrouillé, écrire sans en avoir le droit. Ces cas sont signalés dans le bilan.
Les pannes globales (serveur injoignable, compte refusé) interrompent le passage ; les incidents propres à une fiche sont notés
dans le bilan et le passage continue."""
from dataclasses import dataclass, field

from .conflits import ContenuDistant, decider, resoudre, appliquer_distant
from .store import Fiche, Store, Theme
from .synchro import EtatSynchro, detecter, empreinte, empreinte_contenu
from .transport import ConflitDeVersion, ErreurTransport, Injoignable, NonAuthentifie, Refuse, Transport


@dataclass
class Bilan:
    envoyees: list = field(default_factory=list)              # titres
    recues: list = field(default_factory=list)                # fiches déjà suivies, mises à jour depuis le serveur
    nouvelles: list = field(default_factory=list)             # fiches reçues pour la première fois
    alignees: list = field(default_factory=list)              # modifiées à l'identique des deux côtés
    conflits: list = field(default_factory=list)              # (titre, titre de la copie locale)
    ecartees: list = field(default_factory=list)              # (titre, titre de la copie locale) : modification locale en lecture seule
    disparues: list = field(default_factory=list)             # suivies mais absentes du serveur : conservées ici, plus suivies
    supprimees_ici: list = field(default_factory=list)        # supprimées localement : signalées, jamais propagées
    ignorees: list = field(default_factory=list)              # verrouillées (ouvertes ou fermées) : pas synchronisées à ce stade
    erreurs: list = field(default_factory=list)               # (titre, message)

    @property
    def vide(self) -> bool:
        return not any(vars(self).values())


def lire_contenu(store: Store, f: Fiche, version: int = 0) -> ContenuDistant:
    """Contenu synchronisable d'une fiche locale (titre, texte, images)."""
    if f.verrou:
        raise ValueError("fiche verrouillée : pas synchronisée à ce stade")
    return ContenuDistant(version, f.titre, f.texte or "", [(p.nom, p.type, store.lire_piece(f, p)) for p in store.lister_pieces(f)])


def _empreinte_distante(c: ContenuDistant) -> str:
    return empreinte_contenu(c.titre, c.texte, [(nom, octets) for nom, _t, octets in c.pieces])


def publier(store: Store, etat: EtatSynchro, transport: Transport, th: Theme, f: Fiche) -> int:
    """Première mise en ligne d'une fiche locale (le compte en devient propriétaire) ; elle est ensuite suivie.
    ValueError si elle est verrouillée. Retourne la version du serveur."""
    ident = store.assurer_id(th, f)
    if etat.suivi(ident):
        return int(etat.entrees[ident]["version"])
    version = transport.ecrire(ident, lire_contenu(store, f), 0)
    etat.valider(store, th, f, version)
    etat.sauver()
    return version


def partager(store: Store, etat: EtatSynchro, transport: Transport, th: Theme, f: Fiche, compte: str, role: str) -> None:
    """Donne (ou change) le droit d'un compte sur une fiche, après l'avoir mise en ligne si besoin (propriétaire seulement)."""
    ident = store.assurer_id(th, f)
    if not etat.suivi(ident):
        publier(store, etat, transport, th, f)
    transport.partager(ident, compte, role)


def _recevoir_nouvelle(store: Store, etat: EtatSynchro, transport: Transport, ident: str, theme: str) -> str:
    contenu = transport.lire(ident)
    th = store.theme(theme) or store.nouveau_theme(theme)
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, contenu.titre, contenu.texte)
    for nom, type_, octets in contenu.pieces:
        store.ajouter_piece(f, nom, type_, octets)
    store.maj_meta(th, f, **{Store.CLE_ID: ident})                 # la fiche porte l'identifiant du serveur
    etat.valider(store, th, f, contenu.version)
    return f.titre


def synchroniser(store: Store, etat: EtatSynchro, transport: Transport, theme_arrivee: str = "Partagées",
                 maintenant: str | None = None) -> Bilan:
    bilan = Bilan()
    try:
        distants = {r.id: r for r in transport.lister()}               # NonAuthentifie / Injoignable : le passage s'arrête ici
        # 1. fiches nouvellement partagées avec moi
        for ident, r in sorted(distants.items()):
            if etat.suivi(ident):
                continue
            trouvee = store.trouver_par_id(ident)
            if trouvee is not None:                                    # je l'ai déjà (état perdu) : on la rattache sans rien écraser
                th, f = trouvee
                etat.entrees[ident] = {"version": 0, "empreinte": None, "theme": th.nom, "fichier": f.path.stem, "titre": f.titre}
                continue
            try:
                bilan.nouvelles.append(_recevoir_nouvelle(store, etat, transport, ident, theme_arrivee))
            except (Refuse, ErreurTransport) as ex:
                if isinstance(ex, (Injoignable, NonAuthentifie)):
                    raise
                bilan.erreurs.append((r.titre, str(ex) or type(ex).__name__))
        # 2. fiches suivies
        changements = {c.id: c for c in detecter(store, etat)}
        for ident in sorted(etat.entrees):
            c = changements.get(ident)
            entree = etat.entrees[ident]
            titre = (c.titre if c else None) or entree.get("titre", ident)
            if c and c.etat in ("verrouillee", "inaccessible"):
                bilan.ignorees.append(titre)
                continue
            if c and c.etat == "supprimee":
                bilan.supprimees_ici.append(titre)
                continue
            if ident not in distants:
                bilan.disparues.append(titre)
                etat.oublier(ident)                                    # on arrête de la suivre ; la fiche locale reste
                continue
            try:
                _traiter(store, etat, transport, ident, entree, c, distants[ident], bilan, maintenant)
            except (Injoignable, NonAuthentifie):
                raise
            except ErreurTransport as ex:
                bilan.erreurs.append((titre, str(ex) or type(ex).__name__))
    finally:
        etat.sauver()
    return bilan


def _traiter(store, etat, transport, ident, entree, c, r, bilan, maintenant):
    th, f = store.trouver_par_id(ident)
    titre = f.titre
    modifiee = bool(c and c.contenu)
    distant = None
    emp_loc = emp_dist = None
    if modifiee and r.version > int(entree.get("version", 0)):
        distant = transport.lire(ident)                                # les deux ont bougé : sont-elles identiques ?
        emp_loc, emp_dist = empreinte(store, f), _empreinte_distante(distant)
    action = decider(entree, modifiee, r.version, r.role, emp_loc, emp_dist)
    if action == "rien":
        if c and c.deplacee:                                           # simple changement de thème ou de fichier : on met l'état à jour
            etat.valider(store, th, f, int(entree.get("version", 0)))
    elif action == "recevoir":
        appliquer_distant(store, etat, th, f, distant or transport.lire(ident))
        bilan.recues.append(titre)
    elif action == "aligner":
        etat.valider(store, th, f, r.version)
        bilan.alignees.append(titre)
    elif action == "envoyer":
        try:
            version = transport.ecrire(ident, lire_contenu(store, f), int(entree.get("version", 0)))
        except ConflitDeVersion:                                       # le serveur a une version plus récente que celle qu'on croyait
            _resoudre(store, etat, transport.lire(ident), th, f, "conflit", maintenant, bilan.conflits)
        except Refuse:                                                 # droit retiré entre-temps : jamais perdu, mis de côté
            _resoudre(store, etat, transport.lire(ident), th, f, "copie locale", maintenant, bilan.ecartees)
        else:
            etat.valider(store, th, f, version)
            bilan.envoyees.append(titre)
    elif action == "conflit":
        _resoudre(store, etat, distant or transport.lire(ident), th, f, "conflit", maintenant, bilan.conflits)
    elif action == "ecarter":
        _resoudre(store, etat, distant or transport.lire(ident), th, f, "copie locale", maintenant, bilan.ecartees)


def _resoudre(store, etat, distant, th, f, motif, maintenant, liste):
    titre = f.titre
    _th, copie = resoudre(store, etat, th, f, distant, motif=motif, maintenant=maintenant)
    liste.append((titre, copie.titre))
