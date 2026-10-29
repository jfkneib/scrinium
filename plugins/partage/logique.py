# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Partage » : adresses d'invitation, texte du courriel, nom de dépôt, mot de passe."""
import re
from urllib.parse import parse_qs, quote, urlparse

from scrinium.i18n import _

JETON = re.compile(r"^[0-9a-f]{64}$")
ROLES_LIBELLES = {"lecture": "lecture seule", "ecriture": "lecture et écriture"}      # traduits à l'affichage
SERVICE = "scrinium-partage"
ADRESSE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")


def adresse_valide(a: str) -> bool:
    return bool(ADRESSE.match(a.strip()))


def analyser_invitation(texte: str) -> tuple[str, str]:
    """(adresse du serveur, jeton) d'un lien d'invitation : `https://serveur/inviter/<jeton>` (celui du courriel) ou
    `scrinium://rejoindre?serveur=…&jeton=…`. ValueError si le texte n'en est pas un."""
    t = texte.strip()
    u = urlparse(t)
    if u.scheme == "scrinium" and u.netloc == "rejoindre":
        q = parse_qs(u.query)
        serveur, jeton = (q.get("serveur") or [""])[0], (q.get("jeton") or [""])[0]
    elif u.scheme in ("https", "http") and u.hostname:
        m = re.match(r"^(.*)/inviter/([^/?#]+)/?$", u.path)
        if not m:
            raise ValueError("ce n'est pas un lien d'invitation")
        serveur, jeton = f"{u.scheme}://{u.netloc}{m.group(1)}", m.group(2)
    else:
        raise ValueError("ce n'est pas un lien d'invitation")
    if not JETON.match(jeton) or urlparse(serveur).scheme not in ("https", "http"):
        raise ValueError("lien d'invitation incomplet ou abîmé")
    return serveur.rstrip("/"), jeton


def lien_application(serveur: str, jeton: str) -> str:
    return f"scrinium://rejoindre?serveur={quote(serveur, safe='')}&jeton={jeton}"


def texte_invitation(titre: str, role: str, url: str, expire: str, de: str = "") -> tuple[str, str]:
    """(objet, message) du courriel d'invitation. Générique et poli : aucune donnée personnelle de l'expéditeur."""
    objet = _("Invitation à partager une fiche Scrinium")
    droit = _("lire et modifier") if role == "ecriture" else _("lire")
    message = _("Bonjour,\n\nJe vous invite à {droit} la fiche « {titre} » avec Scrinium.\n\n"
                "Pour accepter, ouvrez ce lien (valable jusqu'au {expire}, à usage unique) :\n{url}\n\n"
                "Si vous n'avez pas Scrinium, la page du lien vous explique comment l'obtenir.\n\n"
                "Cordialement").format(droit=droit, titre=titre, expire=expire, url=url)
    return objet, message


def texte_invitation_theme(theme: str, nombre: int, role: str, url: str, expire: str) -> tuple[str, str]:
    """(objet, message) de l'invitation à tout un thème (un seul lien pour les `nombre` fiches)."""
    objet = _("Invitation à partager des fiches Scrinium")
    droit = _("lire et modifier") if role == "ecriture" else _("lire")
    message = _("Bonjour,\n\nJe vous invite à {droit} les {nombre} fiches du thème « {theme} » avec Scrinium.\n\n"
                "Pour accepter, ouvrez ce lien (valable jusqu'au {expire}, à usage unique) :\n{url}\n\n"
                "Si vous n'avez pas Scrinium, la page du lien vous explique comment l'obtenir.\n\n"
                "Cordialement").format(droit=droit, nombre=nombre, theme=theme, expire=expire, url=url)
    return objet, message


def nom_depot(url: str, existants=()) -> str:
    """Nom de dépôt tiré de l'adresse du serveur, unique parmi `existants`."""
    u = urlparse(url)
    base = "".join(c if c.isalnum() or c in "-_." else "-" for c in (u.hostname or "serveur")) + (f"-{u.port}" if u.port else "")
    nom, n = base, 2
    while nom in existants:
        nom, n = f"{base}-{n}", n + 1
    return nom


class Secret:
    """Mot de passe d'un compte de partage : trousseau du système (`keyring`) si présent et si demandé, sinon mémoire de la session."""

    def __init__(self):
        self.session: dict = {}

    def lire(self, cle: str):
        if cle in self.session:
            return self.session[cle]
        try:
            import keyring
            return keyring.get_password(SERVICE, cle)
        except Exception:
            return None

    def ecrire(self, cle: str, mdp: str, retenir: bool) -> bool:
        """True si le mot de passe est dans le trousseau ; sinon il n'est gardé que pour cette session."""
        self.session[cle] = mdp
        if retenir:
            try:
                import keyring
                keyring.set_password(SERVICE, cle, mdp)
                return True
            except Exception:
                return False
        return False

    def effacer(self, cle: str) -> None:
        self.session.pop(cle, None)
        try:
            import keyring
            keyring.delete_password(SERVICE, cle)
        except Exception:
            pass
