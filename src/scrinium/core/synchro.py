# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""État de synchronisation et détection des changements d'un dépôt partagé (aucun accès réseau ici).

Principe : pour chaque fiche SUIVIE (partagée), on garde ce qui était vrai à la dernière synchronisation réussie : la version connue
du serveur, l'empreinte (SHA-256) du contenu et l'endroit (thème, fichier). `detecter` compare cet état à l'état actuel et dit ce
qui a changé localement ; il ne modifie jamais rien. Une fiche qu'on ne suit pas n'est jamais lue ni modifiée par ce module.

Contenu synchronisé = titre + texte + pièces jointes (nom et empreinte de chaque image). Les métadonnées des extensions et le texte
OCR n'en font pas partie. Fiches verrouillées : pas de synchronisation de leur contenu à ce stade (étape 3 du plan) ; on sait
seulement les reconnaître (fermées : « inaccessible » ; ouvertes : « verrouillée »)."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .store import Fiche, Store, Theme, _ecrire, mkdir_prive

FORMAT = 1


def chemin_etat(store: Store, depot: str = "personnel") -> Path:
    """Fichier d'état d'un dépôt : <données>/synchro/<dépôt>.json (jamais dans le dossier des fiches)."""
    sur = "".join(c for c in depot if c.isalnum() or c in "-_.") or "depot"
    return store.paths.base / "synchro" / f"{sur}.json"


def empreinte(store: Store, f: Fiche) -> str | None:
    """SHA-256 du contenu synchronisable de la fiche ; None si elle est verrouillée (pas synchronisée à ce stade)."""
    if f.verrou:
        return None
    pieces = sorted([p.nom, hashlib.sha256(store.lire_piece(f, p)).hexdigest()] for p in store.lister_pieces(f))
    corps = json.dumps({"titre": f.titre, "texte": f.texte or "", "pieces": pieces}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()


@dataclass
class Changement:
    id: str
    titre: str                      # titre connu à la dernière synchronisation
    theme: str                      # thème connu à la dernière synchronisation
    etat: str = "modifiee"          # « modifiee » | « supprimee » | « inaccessible » (verrouillée fermée) | « verrouillee »
    contenu: bool = False           # le titre, le texte ou les pièces jointes ont changé
    deplacee: bool = False          # changement de thème ou de fichier


class EtatSynchro:
    """Fichier JSON d'un dépôt : {« format », « fiches » : {identifiant : {version, empreinte, theme, fichier, titre}}}."""

    def __init__(self, chemin: Path):
        self.chemin = chemin
        self.entrees: dict = {}

    def charger(self) -> "EtatSynchro":
        """Lit le fichier ; absent ou illisible = état vide (on resynchronisera : jamais d'écrasement sans comparaison)."""
        try:
            d = json.loads(self.chemin.read_text(encoding="utf-8"))
            ok = d.get("format") == FORMAT and isinstance(d.get("fiches"), dict)
            self.entrees = {str(k): dict(v) for k, v in d["fiches"].items() if isinstance(v, dict)} if ok else {}
        except (OSError, ValueError, AttributeError, TypeError):
            self.entrees = {}
        return self

    def sauver(self) -> None:
        mkdir_prive(self.chemin.parent)
        _ecrire(self.chemin, json.dumps({"format": FORMAT, "fiches": self.entrees}, ensure_ascii=False, indent=1,
                                        sort_keys=True).encode("utf-8"))

    def suivi(self, ident: str) -> bool:
        return ident in self.entrees

    def valider(self, store: Store, th: Theme, f: Fiche, version: int) -> str:
        """À appeler quand la fiche vient d'être synchronisée avec succès (envoyée ou reçue) : mémorise la version du serveur et
        l'état local actuel. Donne l'identifiant (créé au besoin : c'est le premier moment où une fiche devient « suivie »).
        ValueError pour une fiche verrouillée."""
        if f.verrou:
            raise ValueError("fiche verrouillée : pas synchronisée à ce stade")
        ident = store.assurer_id(th, f)
        self.entrees[ident] = {"version": int(version), "empreinte": empreinte(store, f), "theme": th.nom,
                               "fichier": f.path.stem, "titre": f.titre}
        return ident

    def oublier(self, ident: str) -> None:
        self.entrees.pop(ident, None)


def detecter(store: Store, etat: EtatSynchro) -> list:
    """Changements LOCAUX depuis la dernière synchronisation, pour les seules fiches suivies. Ne modifie rien."""
    parmi = {}
    for th in store.themes:
        for f in th.fiches:
            ident = store.id_fiche(f)
            if ident and ident in etat.entrees:
                parmi[ident] = (th, f)
    res = []
    for ident, e in sorted(etat.entrees.items()):
        base = dict(id=ident, titre=e.get("titre", ""), theme=e.get("theme", ""))
        if ident in parmi:
            th, f = parmi[ident]
            if f.verrou:                                  # fiche suivie puis verrouillée : ne se synchronise plus tant qu'elle l'est
                res.append(Changement(etat="verrouillee", **base))
                continue
            contenu = empreinte(store, f) != e.get("empreinte")
            deplacee = th.nom != e.get("theme") or f.path.stem != e.get("fichier")
            if contenu or deplacee:
                res.append(Changement(contenu=contenu, deplacee=deplacee, **base))
            continue
        # introuvable par identifiant : supprimée, ou verrouillée et fermée (son identifiant est alors invisible)
        stem = e.get("fichier", "")
        fermee_la = any(x.verrou and x.fermee and x.path.stem == stem for th in store.themes if th.nom == e.get("theme")
                        for x in th.fiches)
        res.append(Changement(etat="inaccessible" if fermee_la else "supprimee", **base))
    return res
