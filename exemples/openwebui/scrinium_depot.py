"""
title: Scrinium · créer une fiche
author: jfk
author_url: https://github.com/jfkneib/scrinium
version: 0.1.0
license: GPL-3.0-or-later
description: Permet au modèle de créer une fiche dans Scrinium (résumé, tâche, idée…) par le serveur de partage. L'outil ne sait qu'AJOUTER des fiches : il ne lit, ne modifie ni ne supprime rien.
"""
import hashlib
import http.client
import json
import ssl
from urllib.parse import urlparse

from pydantic import BaseModel, Field


def _normaliser(empreinte: str) -> str:
    return "".join(c for c in empreinte.lower() if c in "0123456789abcdef")


class Tools:
    class Valves(BaseModel):
        serveur: str = Field(default="https://scrinium.exemple.org",
                             description="Adresse de votre serveur de partage Scrinium (depuis Docker, préférer l'adresse IP à un nom en .local, non résolu dans un conteneur)")
        jeton: str = Field(default="", description="Jeton de dépôt (commande « creer-jeton » du serveur) : il ne permet que d'ajouter des fiches")
        empreinte: str = Field(default="",
                               description="Empreinte SHA-256 du certificat du serveur, s'il est auto-signé (vide : certificat vérifié normalement)")
        prefixe_titre: str = Field(default="[IA] ", description="Début ajouté au titre de chaque fiche, pour retrouver ce qui vient d'un modèle")
        delai: int = Field(default=15, description="Délai maximal d'attente du serveur, en secondes")

    def __init__(self):
        self.valves = self.Valves()

    def creer_fiche(self, titre: str, texte: str) -> str:
        """
        Crée une nouvelle fiche dans Scrinium, le carnet de fiches de l'utilisateur.
        À utiliser seulement quand l'utilisateur demande de noter, enregistrer ou sauvegarder quelque chose dans Scrinium.
        Ne jamais y mettre de mot de passe ni d'information secrète.
        :param titre: titre court de la fiche (quelques mots)
        :param texte: contenu de la fiche, en texte simple ou en Markdown
        :return: un message qui dit si la fiche a été créée
        """
        v = self.valves
        if not isinstance(titre, str) or not isinstance(texte, str) or not (titre.strip() or texte.strip()):
            return "Rien à enregistrer : il faut un titre ou un texte."
        if not v.jeton.strip():
            return ("Le jeton de dépôt Scrinium n'est pas renseigné : l'utilisateur doit l'ajouter dans les réglages de l'outil "
                    "(Espace de travail > Outils > Scrinium > réglages).")
        titre = titre.strip()
        if v.prefixe_titre and not titre.startswith(v.prefixe_titre):
            titre = v.prefixe_titre + titre
        try:
            statut, corps = self._poster({"titre": titre, "texte": texte})
        except PermissionError as ex:
            return f"Connexion refusée par prudence : {ex}"
        except (OSError, http.client.HTTPException, ssl.SSLError) as ex:
            return f"Serveur Scrinium injoignable : {ex}. Rien n'a été enregistré."
        if statut == 201:
            return (f"Fiche créée dans Scrinium : « {corps.get('titre', titre)} ». "
                    "Elle apparaîtra dans Scrinium à la prochaine synchronisation des partages.")
        if statut == 401:
            return "Le serveur Scrinium refuse le jeton de dépôt (révoqué ou incorrect). Rien n'a été enregistré."
        if statut == 429:
            return "Trop de fiches créées récemment : le serveur limite les dépôts. Réessayer plus tard."
        return f"Le serveur Scrinium a refusé la fiche (code {statut}) : {corps.get('message', 'raison inconnue')}"

    # ---------- réseau ----------
    def _poster(self, donnees: dict) -> tuple:
        v = self.valves
        u = urlparse(v.serveur.strip().rstrip("/"))
        if u.scheme not in ("https", "http") or not u.hostname:
            raise PermissionError("adresse du serveur invalide (https://hôte:port attendu)")
        if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1") and not u.hostname.startswith("192.168."):
            raise PermissionError("http n'est accepté que sur le réseau local : utiliser https")
        if u.scheme == "https":
            ctx = ssl.create_default_context()
            if v.empreinte.strip():
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE          # certificat auto-signé : on vérifie l'empreinte
            c = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=v.delai, context=ctx)
        else:
            c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=v.delai)
        try:
            c.connect()
            if u.scheme == "https" and v.empreinte.strip():
                recu = hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest()
                if recu != _normaliser(v.empreinte):
                    raise PermissionError("le certificat du serveur ne correspond pas à l'empreinte attendue")
            c.request("POST", u.path.rstrip("/") + "/api/v1/depot", body=json.dumps(donnees).encode("utf-8"),
                      headers={"Authorization": f"Bearer {v.jeton.strip()}", "Content-Type": "application/json",
                               "Accept": "application/json", "User-Agent": "Scrinium-OpenWebUI/0.1"})
            r = c.getresponse()
            brut = r.read()
            try:
                corps = json.loads(brut) if brut else {}
            except ValueError:
                corps = {}
            return r.status, corps if isinstance(corps, dict) else {}
        finally:
            c.close()
