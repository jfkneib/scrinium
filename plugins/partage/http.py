# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Transport HTTP vers le serveur Scrinium (contrat : docs/api-partage.md). Bibliothèque standard seule.

Certificat : par défaut, vérification normale (autorités du système). Un serveur à certificat auto-signé s'utilise en
« épinglant » son empreinte SHA-256 (`empreinte`) : la connexion n'est alors acceptée que si le certificat présenté a EXACTEMENT
cette empreinte (nom et chaîne ne sont plus vérifiés, c'est l'empreinte qui fait foi)."""
import hashlib
import http.client
import json
import socket
import ssl
from urllib.parse import quote, urlparse

from scrinium.core.conflits import ContenuDistant
from scrinium.core.transport import (ConflitDeVersion, ErreurTransport, Injoignable, Introuvable, NonAuthentifie, Refuse, Resume,
                                     Transport)

DELAI = 10          # secondes
API_ATTENDUE = 1


class CertificatInconnu(ErreurTransport):
    """Certificat non reconnu (auto-signé, expiré, autre nom…) et aucune empreinte épinglée qui le couvre."""


class ServeurIncompatible(ErreurTransport):
    """Le serveur parle une autre version majeure de l'API."""


def normaliser_empreinte(texte: str) -> str:
    return "".join(c for c in texte.lower() if c in "0123456789abcdef")


def formater_empreinte(hexa: str) -> str:
    return ":".join(hexa[i:i + 2] for i in range(0, len(hexa), 2))


def empreinte_serveur(url: str, delai: float = DELAI) -> str:
    """Empreinte SHA-256 du certificat présenté par le serveur (sans le vérifier) : à montrer à l'utilisateur avant de l'épingler."""
    u = urlparse(url)
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with socket.create_connection((u.hostname, u.port or 443), timeout=delai) as brut, \
                ctx.wrap_socket(brut, server_hostname=u.hostname) as s:
            return hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest()
    except (OSError, ssl.SSLError) as ex:
        raise Injoignable(str(ex)) from ex


def _extraire_id(u: str) -> str:
    return u.rsplit("/", 1)[-1]


class TransportHttp(Transport):
    def __init__(self, url: str, compte: str, mot_de_passe=None, empreinte: str | None = None, delai: float = DELAI):
        """`mot_de_passe` : texte, ou fonction sans argument qui le donne (appelée à la connexion seulement)."""
        self.url = url.rstrip("/")
        self.u = urlparse(self.url)
        self.compte = compte
        self._mdp = mot_de_passe
        self.empreinte = normaliser_empreinte(empreinte) if empreinte else None
        self.delai = delai
        self.jeton: str | None = None

    # ---------- bas niveau ----------
    def _connexion(self) -> http.client.HTTPConnection:
        port = self.u.port
        if self.u.scheme == "http":
            return http.client.HTTPConnection(self.u.hostname, port or 80, timeout=self.delai)
        ctx = ssl.create_default_context()
        if self.empreinte:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        return http.client.HTTPSConnection(self.u.hostname, port or 443, timeout=self.delai, context=ctx)

    def _brut(self, methode: str, chemin: str, corps: bytes | None = None, type_: str = "application/json",
              jeton: bool = True) -> tuple:
        """(statut, octets, entêtes) ; erreurs réseau -> Injoignable / CertificatInconnu."""
        entetes = {"Accept": "application/json", "User-Agent": "Scrinium-Partage/0.1"}
        if corps is not None:
            entetes["Content-Type"] = type_
        if jeton and self.jeton:
            entetes["Authorization"] = f"Bearer {self.jeton}"
        c = self._connexion()
        try:
            c.connect()
            if self.empreinte and isinstance(c.sock, ssl.SSLSocket):
                recu = hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest()
                if recu != self.empreinte:
                    raise CertificatInconnu(f"Le certificat du serveur a changé (empreinte {formater_empreinte(recu)}).")
            prefixe = self.u.path.rstrip("/")                  # serveur derrière un proxy : https://hote/scrinium
            c.request(methode, prefixe + (chemin if chemin == "/api" else "/api/v1" + chemin), body=corps, headers=entetes)
            r = c.getresponse()
            return r.status, r.read(), dict(r.getheaders())
        except ssl.SSLCertVerificationError as ex:
            raise CertificatInconnu(f"Certificat du serveur non reconnu : {ex.verify_message}") from ex
        except (OSError, http.client.HTTPException) as ex:
            raise Injoignable(str(ex) or type(ex).__name__) from ex
        finally:
            c.close()

    @staticmethod
    def _message(octets: bytes) -> str:
        try:
            return str(json.loads(octets).get("message", ""))
        except (ValueError, AttributeError):
            return ""

    def _lever(self, statut: int, octets: bytes, ressource: str = "") -> None:
        msg = self._message(octets) or ressource
        if statut == 401:
            raise NonAuthentifie(msg)
        if statut == 403:
            raise Refuse(msg)
        if statut == 404:
            raise Introuvable(msg)
        if statut == 409:
            try:
                v = int(json.loads(octets).get("version_serveur", 0))
            except (ValueError, AttributeError, TypeError):
                v = 0
            raise ConflitDeVersion(v)
        if statut in (413, 422, 429):
            raise Refuse(msg or f"HTTP {statut}")
        if statut >= 500 or statut >= 400:
            raise Injoignable(f"HTTP {statut}")

    def _json(self, methode: str, chemin: str, donnees=None, ok=(200, 201, 204), jeton: bool = True, reconnecter: bool = True):
        corps = None if donnees is None else json.dumps(donnees).encode("utf-8")
        if jeton and self.jeton is None and chemin != "/session":
            self.connecter()
        statut, octets, _e = self._brut(methode, chemin, corps, jeton=jeton)
        if statut == 401 and jeton and reconnecter and chemin != "/session":
            self.jeton = None
            self.connecter()
            statut, octets, _e = self._brut(methode, chemin, corps, jeton=jeton)
        if statut not in ok:
            self._lever(statut, octets, chemin)
        return json.loads(octets) if octets else None

    # ---------- session et découverte ----------
    def decouverte(self) -> dict:
        statut, octets, _e = self._brut("GET", "/api", jeton=False)
        if statut != 200:
            raise Injoignable(f"HTTP {statut}")
        d = json.loads(octets)
        if d.get("api") != API_ATTENDUE:
            raise ServeurIncompatible(f"API {d.get('api')} non prise en charge (attendue : {API_ATTENDUE}).")
        return d

    def connecter(self) -> None:
        mdp = self._mdp() if callable(self._mdp) else self._mdp
        if mdp is None:
            raise NonAuthentifie("mot de passe absent")
        d = self._json("POST", "/session", {"compte": self.compte, "mot_de_passe": mdp}, jeton=False)
        self.jeton = d["jeton"]

    def deconnecter(self) -> None:
        if self.jeton:
            try:
                self._json("DELETE", "/session", reconnecter=False)
            finally:
                self.jeton = None

    # ---------- Transport ----------
    def lister(self) -> list:
        return [Resume(r["id"], int(r["version"]), r["titre"], r["role"], r["proprietaire"]) for r in self._json("GET", "/fiches")]

    def lire(self, ident: str) -> ContenuDistant:
        f = self._json("GET", f"/fiches/{ident}")
        pieces = []
        for p in f.get("pieces", []):
            statut, octets, _e = self._brut("GET", f"/blobs/{p['sha256']}")
            if statut != 200:
                self._lever(statut, octets, p["nom"])
            if hashlib.sha256(octets).hexdigest() != p["sha256"]:
                raise Injoignable("image corrompue en transit")
            pieces.append((p["nom"], p["type"], octets))
        return ContenuDistant(int(f["version"]), f["titre"], f["texte"], pieces)

    def ecrire(self, ident: str, contenu: ContenuDistant, version_depart: int) -> int:
        meta = []
        for nom, type_, octets in contenu.pieces:
            sha = hashlib.sha256(octets).hexdigest()
            statut, rep, _e = self._brut("PUT", f"/blobs/{sha}", octets, "application/octet-stream")
            if statut == 401:
                self.jeton = None
                self.connecter()
                statut, rep, _e = self._brut("PUT", f"/blobs/{sha}", octets, "application/octet-stream")
            if statut != 204:
                self._lever(statut, rep, nom)
            meta.append({"nom": nom, "type": type_, "taille": len(octets), "sha256": sha})
        r = self._json("PUT", f"/fiches/{ident}", {"titre": contenu.titre, "texte": contenu.texte, "pieces": meta,
                                                  "version_depart": version_depart})
        return int(r["version"])

    def droits(self, ident: str) -> dict:
        return self._json("GET", f"/fiches/{ident}/droits")

    def partager(self, ident: str, compte: str, role: str) -> None:
        self._json("PUT", f"/fiches/{ident}/droits/{quote(compte, safe='')}", {"role": role})

    def retirer_droit(self, ident: str, compte: str) -> None:
        self._json("DELETE", f"/fiches/{ident}/droits/{quote(compte, safe='')}")

    def supprimer(self, ident: str) -> None:
        self._json("DELETE", f"/fiches/{ident}")

    # ---------- invitations (voir docs/api-partage.md, § 5) ----------
    def inviter(self, ident: str, email: str, role: str) -> dict:
        """{id, url, expire_le, role}"""
        return self._json("POST", f"/fiches/{ident}/invitations", {"email": email, "role": role})

    def inviter_groupe(self, idents: list, email: str, role: str) -> dict:
        """Une invitation pour plusieurs fiches (thème entier). {id, url, expire_le, role}"""
        return self._json("POST", "/invitations", {"email": email, "role": role, "fiches": list(idents)})

    def invitations(self, ident: str) -> list:
        return self._json("GET", f"/fiches/{ident}/invitations")

    def annuler(self, invitation: str) -> None:
        self._json("DELETE", f"/invitations/{invitation}")

    def decrire_invitation(self, jeton: str) -> dict:
        """{invite_par, role, expire_le, fiches} ; Introuvable si expirée, utilisée ou inconnue."""
        return self._json("GET", f"/invitations/{jeton}", jeton=False)

    def rejoindre(self, jeton: str, compte: str | None = None, mot_de_passe: str | None = None) -> None:
        """Accepte une invitation. Déjà connecté : ajoute le droit à ce compte. Sinon crée le compte `compte` (mot de passe d'au
        moins 10 caractères) et ouvre la session."""
        if self.jeton is None and compte is None:
            self.connecter()
        if self.jeton is not None:
            self._json("POST", f"/invitations/{jeton}/accepter", {})
            return
        d = self._json("POST", f"/invitations/{jeton}/accepter", {"compte": compte, "mot_de_passe": mot_de_passe}, jeton=False)
        self.compte, self.jeton = d["compte"], d["jeton"]
