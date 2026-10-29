# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Interface de transport : ce qu'un serveur de partage doit savoir faire, vu du cœur de Scrinium.

Le cœur ne connaît AUCUN protocole : le plugin « Partage » fournit une implémentation (HTTP vers le serveur PHP). Cette interface
fixe aussi les règles que tout serveur doit respecter :
  - trois rôles : « proprietaire », « ecriture », « lecture » ;
  - écrire demande la VERSION DE DÉPART ; si elle n'est plus la dernière, le serveur refuse (`ConflitDeVersion`) ;
  - seul le propriétaire partage, retire un droit ou supprime ; lire demande un droit, écrire un droit d'écriture.
`ServeurMemoire` applique ces règles en mémoire : référence exécutable de l'interface, et serveur de test (aucun réseau)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .conflits import ContenuDistant

ROLES = ("proprietaire", "ecriture", "lecture")


class ErreurTransport(Exception):
    pass


class Injoignable(ErreurTransport):
    """Réseau ou serveur indisponible : on réessaiera plus tard, rien n'est perdu."""


class NonAuthentifie(ErreurTransport):
    """Compte ou mot de passe refusé."""


class Refuse(ErreurTransport):
    """Droits insuffisants pour cette opération."""


class Introuvable(ErreurTransport):
    """Fiche inconnue du serveur, ou non partagée avec ce compte."""


class ConflitDeVersion(ErreurTransport):
    """L'enregistrement part d'une version qui n'est plus la dernière du serveur."""

    def __init__(self, version_serveur: int):
        super().__init__(f"version du serveur : {version_serveur}")
        self.version_serveur = version_serveur


@dataclass
class Resume:
    """Une fiche partagée avec moi, telle que la liste le serveur."""
    id: str
    version: int
    titre: str
    role: str
    proprietaire: str


class Transport(ABC):
    @abstractmethod
    def lister(self) -> list:
        """[Resume] des fiches auxquelles ce compte a accès (les siennes et celles partagées avec lui)."""

    @abstractmethod
    def lire(self, ident: str) -> ContenuDistant:
        """Dernière version d'une fiche. Introuvable / Refuse."""

    @abstractmethod
    def ecrire(self, ident: str, contenu: ContenuDistant, version_depart: int) -> int:
        """Enregistre et retourne la NOUVELLE version. `version_depart` = 0 : création (le compte en devient propriétaire).
        ConflitDeVersion si `version_depart` n'est plus la dernière ; Refuse sans droit d'écriture."""

    @abstractmethod
    def droits(self, ident: str) -> dict:
        """{compte: rôle} d'une fiche (propriétaire seulement)."""

    @abstractmethod
    def partager(self, ident: str, compte: str, role: str) -> None:
        """Donne (ou change) un droit : « ecriture » ou « lecture » (propriétaire seulement)."""

    @abstractmethod
    def retirer_droit(self, ident: str, compte: str) -> None:
        """Retire l'accès d'un compte (propriétaire seulement)."""

    @abstractmethod
    def supprimer(self, ident: str) -> None:
        """Supprime la fiche du serveur (propriétaire seulement)."""


class ServeurMemoire:
    """Serveur de référence en mémoire : mêmes règles que le vrai, pour les tests. Un `Transport` par compte (voir `.pour`)."""

    def __init__(self, comptes=()):
        self.comptes = set(comptes)
        self.fiches: dict = {}          # id -> {version, titre, texte, pieces, proprietaire, droits {compte: rôle}}
        self.ecritures = 0              # nombre d'enregistrements acceptés (les tests s'en servent pour vérifier l'idempotence)

    def pour(self, compte: str) -> "TransportMemoire":
        return TransportMemoire(self, compte)


class TransportMemoire(Transport):
    def __init__(self, serveur: ServeurMemoire, compte: str):
        self.s, self.compte = serveur, compte

    def _role(self, ident: str) -> str | None:
        if self.compte not in self.s.comptes:
            raise NonAuthentifie(self.compte)
        f = self.s.fiches.get(ident)
        return f["droits"].get(self.compte) if f else None

    def lister(self) -> list:
        if self.compte not in self.s.comptes:
            raise NonAuthentifie(self.compte)
        return [Resume(i, f["version"], f["titre"], f["droits"][self.compte], f["proprietaire"])
                for i, f in sorted(self.s.fiches.items()) if self.compte in f["droits"]]

    def lire(self, ident: str) -> ContenuDistant:
        if self._role(ident) is None:
            raise Introuvable(ident)
        f = self.s.fiches[ident]
        return ContenuDistant(f["version"], f["titre"], f["texte"], list(f["pieces"]))

    def ecrire(self, ident: str, contenu: ContenuDistant, version_depart: int) -> int:
        role = self._role(ident)
        if ident not in self.s.fiches:
            if version_depart != 0:
                raise Introuvable(ident)
            self.s.fiches[ident] = {"version": 0, "titre": "", "texte": "", "pieces": [], "proprietaire": self.compte,
                                    "droits": {self.compte: "proprietaire"}}
        elif role not in ("proprietaire", "ecriture"):
            raise Refuse(ident) if role else Introuvable(ident)
        f = self.s.fiches[ident]
        if f["version"] != version_depart:
            raise ConflitDeVersion(f["version"])
        f.update(version=f["version"] + 1, titre=contenu.titre, texte=contenu.texte, pieces=list(contenu.pieces))
        self.s.ecritures += 1
        return f["version"]

    def _proprietaire(self, ident: str) -> dict:
        role = self._role(ident)
        if role is None:
            raise Introuvable(ident)
        if role != "proprietaire":
            raise Refuse(ident)
        return self.s.fiches[ident]

    def droits(self, ident: str) -> dict:
        return dict(self._proprietaire(ident)["droits"])

    def partager(self, ident: str, compte: str, role: str) -> None:
        f = self._proprietaire(ident)
        if role not in ("ecriture", "lecture") or compte not in self.s.comptes or compte == f["proprietaire"]:
            raise Refuse(f"{compte}/{role}")
        f["droits"][compte] = role

    def retirer_droit(self, ident: str, compte: str) -> None:
        f = self._proprietaire(ident)
        if compte == f["proprietaire"]:
            raise Refuse(compte)
        f["droits"].pop(compte, None)

    def supprimer(self, ident: str) -> None:
        self._proprietaire(ident)
        del self.s.fiches[ident]
