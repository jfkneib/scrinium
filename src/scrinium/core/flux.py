# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Lecture de flux RSS 2.0 / Atom (sans interface), partagée par les extensions qui suivent des sources (Veille, Emploi…).

Sûreté : http et https seulement, délai de 10 s, 2 Mo au plus par flux, un flux qui déclare des entités XML est refusé, aucun lien qui ne soit
http(s) n'est gardé, rien n'est exécuté ni téléchargé en dehors du flux lui-même."""
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DELAI = 10
MAX_OCTETS = 2_000_000
MAX_ENTREES = 200
MAX_RESUME = 1500


@dataclass
class Entree:
    titre: str
    lien: str
    date: str                                              # « 2026-11-10 10:00 » (UTC) ; vide si inconnue
    resume: str                                            # texte brut, sans balises
    cle: str                                               # identifiant donné par le flux (guid / id), à défaut le lien


def adresse_valide(a: str) -> bool:
    return bool(re.fullmatch(r"https?://[^\s<>\"']{3,500}", (a or "").strip(), re.I))


def jour(texte: str) -> str:
    texte = (texte or "").strip()
    if not texte:
        return ""
    try:
        d = parsedate_to_datetime(texte)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(texte.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M")


def _nom(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _texte(e, *noms) -> str:
    for enfant in e:
        if _nom(enfant) in noms and (enfant.text or "").strip():
            return " ".join(enfant.text.split())
    return ""


def nettoyer(t: str) -> str:
    """Résumé en texte brut : balises retirées, entités décodées, espaces réduits, longueur bornée."""
    t = html.unescape(re.sub(r"<[^>]*>", " ", html.unescape(t or "")))
    return " ".join(t.split())[:MAX_RESUME]


def entrees(contenu: bytes) -> list:
    """Entrées d'un flux RSS 2.0 ou Atom (liste vide si le contenu n'en est pas un ou déclare des entités XML)."""
    if b"<!ENTITY" in contenu[:20000] or b"<!entity" in contenu[:20000]:
        return []
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError:
        return []
    res = []
    for e in racine.iter():
        if _nom(e) not in ("item", "entry"):
            continue
        titre = _texte(e, "title")
        lien = _texte(e, "link")
        if not lien:                                       # Atom : <link href="…" />
            for enfant in e:
                if _nom(enfant) == "link" and enfant.get("href") and enfant.get("rel", "alternate") == "alternate":
                    lien = enfant.get("href", "").strip()
                    break
        if not titre or not adresse_valide(lien):
            continue
        resume = nettoyer(_texte(e, "description", "summary", "content"))
        res.append(Entree(titre[:300], lien, jour(_texte(e, "pubDate", "updated", "published", "date")), resume, _texte(e, "guid", "id") or lien))
        if len(res) >= MAX_ENTREES:
            break
    return res


def telecharger(adresse: str) -> bytes:
    """Contenu du flux (2 Mo au plus). Lève OSError / ValueError : l'appelant montre l'erreur."""
    if not adresse_valide(adresse):
        raise ValueError("adresse refusée (http ou https seulement)")
    req = urllib.request.Request(adresse, headers={"User-Agent": "Scrinium", "Accept": "application/rss+xml, application/atom+xml, application/xml, */*"})
    with urllib.request.urlopen(req, timeout=DELAI) as r:                      # noqa: S310 (schéma vérifié ci-dessus)
        if not r.geturl().lower().startswith(("http://", "https://")):
            raise ValueError("redirection refusée")
        return r.read(MAX_OCTETS)
