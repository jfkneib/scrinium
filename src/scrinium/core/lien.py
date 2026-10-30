# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Liens `scrinium://…` reçus du système (navigateur, autre programme) : analyse et validation, sans aucune écriture.

  scrinium://ajouter?titre=…&texte=…&theme=…   propose d'ajouter une NOUVELLE fiche (l'utilisateur voit et valide avant tout)
  scrinium://rejoindre?serveur=…&jeton=…        invitation à un partage (traitée par l'extension Partage)

Un lien est une entrée non fiable : cette partie ne fait que lire et nettoyer ; rien n'est écrit sans un clic de l'utilisateur."""
import re
from urllib.parse import parse_qs, urlparse

from ..i18n import _

MAX_URL = 200_000
MAX_TITRE = 200
MAX_THEME = 80
MAX_TEXTE = 64 * 1024
_CONTROLES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")      # contrôles et marques de sens d'écriture


def nettoyer(valeur: str, long_ligne: bool = False) -> str:
    """Texte sans caractères de contrôle ni marques bidirectionnelles (qui peuvent faire lire autre chose que ce qui est écrit)."""
    v = _CONTROLES.sub("", valeur.replace("\r\n", "\n").replace("\r", "\n"))
    return " ".join(v.split()) if long_ligne else v.strip("\n")


def analyser(url: str) -> dict:
    """{"action": "ajouter", "theme", "titre", "texte"} ou {"action": "rejoindre"}. ValueError (message pour l'utilisateur) sinon."""
    if len(url) > MAX_URL:
        raise ValueError(_("lien trop long"))
    u = urlparse(url.strip())
    if u.scheme.lower() != "scrinium":
        raise ValueError(_("ce n'est pas un lien Scrinium"))
    action = (u.netloc or u.path.strip("/")).lower().split("?")[0]
    if action == "rejoindre":
        return {"action": "rejoindre"}
    if action != "ajouter":
        raise ValueError(_("lien Scrinium non reconnu : « %s »") % action[:40])
    q = parse_qs(u.query, keep_blank_values=True, max_num_fields=20)
    un = lambda cle: (q.get(cle) or [""])[0]                   # noqa: E731  (première valeur)
    titre, theme = nettoyer(un("titre"), True), nettoyer(un("theme"), True)
    texte = nettoyer(un("texte"))
    if len(texte.encode("utf-8")) > MAX_TEXTE:
        raise ValueError(_("texte trop long pour un lien (64 Ko au plus) : utilisez « scrinium ajouter » pour un gros texte"))
    if not titre and not texte.strip():
        raise ValueError(_("lien vide : ni titre ni texte à ajouter"))
    return {"action": "ajouter", "titre": titre[:MAX_TITRE], "texte": texte, "theme": theme[:MAX_THEME]}


def titre_par_defaut(titre: str, texte: str, maintenant: str) -> str:
    """Titre à utiliser : celui du lien, sinon la première ligne du texte, sinon la date."""
    if titre.strip():
        return titre.strip()
    for ligne in texte.splitlines():
        ligne = ligne.strip().lstrip("#").strip()
        if ligne:
            return ligne[:MAX_TITRE]
    return maintenant
