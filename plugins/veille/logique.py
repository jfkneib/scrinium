# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Veille : sources RSS / Atom, nouveautés, « lu » (sans interface).

Sûreté : http et https seulement, délai de 10 s, 2 Mo au plus par flux, rien n'est exécuté ni téléchargé en dehors du flux, un flux qui déclare
des entités XML est refusé. La fiche est de type exécutable (elle fait des requêtes réseau) : inerte tant que l'utilisateur ne l'a pas validée."""
import hashlib
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-veille"
MAX_SOURCES = 40
MAX_LUS = 3000
MAX_ARTICLES = 60                                          # par source
DELAI = 10
MAX_OCTETS = 2_000_000
_LIGNE = re.compile(r"^\|(.*)\|\s*$")


@dataclass
class Source:
    nom: str
    adresse: str
    mot: str = ""                                          # ne garder que les articles qui contiennent ce mot (titre ou résumé)
    afficher: bool = True                                  # case cochée : les articles de cette source sont montrés (sinon masqués, et non comptés)


@dataclass
class Document:
    sources: list = field(default_factory=list)
    lus: list = field(default_factory=list)                # empreintes d'articles lus (les plus récents en dernier)


@dataclass
class Article:
    source: str
    titre: str
    lien: str
    date: str                                              # ISO ; vide si inconnue
    empreinte: str


def adresse_valide(a: str) -> bool:
    m = re.fullmatch(r"https?://[^\s<>\"']{3,500}", (a or "").strip(), re.I)
    return bool(m)


def lire(texte: str | None) -> Document:
    doc, section = Document(), "sources"
    for brut in (texte or "").lstrip("﻿").splitlines():
        ligne = brut.strip()
        if ligne.startswith("## "):
            section = "lus" if ligne[3:].strip().lower().startswith("lu") else "sources"
            continue
        if section == "lus":
            if re.fullmatch(r"[0-9a-f]{10}", ligne) and len(doc.lus) < MAX_LUS:
                doc.lus.append(ligne)
            continue
        m = _LIGNE.match(ligne)
        if not m:
            continue
        c = [x.strip() for x in m[1].split("|")]
        if len(c) >= 2 and adresse_valide(c[1]) and len(doc.sources) < MAX_SOURCES:
            doc.sources.append(Source(" ".join(c[0].split())[:60] or c[1][:60], c[1], " ".join((c[2] if len(c) > 2 else "").split())[:40],
                                      (c[3].strip().lower() if len(c) > 3 else "oui") not in ("non", "no", "0", "faux")))
    return doc


def ecrire(doc: Document) -> str:
    sortie = [MARQUE, "", "| Source | Adresse du flux | Mot-clé | Affiché |", "|---|---|---|---|"]
    for s in doc.sources[:MAX_SOURCES]:
        sortie.append("| %s | %s | %s | %s |" % (s.nom.replace("|", "/"), s.adresse.replace("|", "%7C"), s.mot.replace("|", "/"), "oui" if s.afficher else "non"))
    if doc.lus:
        sortie += ["", "## Lus"] + doc.lus[-MAX_LUS:]
    return "\n".join(sortie) + "\n"


def empreinte(source: str, cle: str) -> str:
    return hashlib.sha256((source + "\n" + cle).encode("utf-8")).hexdigest()[:10]


def _jour(texte: str) -> str:
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


def analyser(source: Source, contenu: bytes) -> list:
    """Articles d'un flux RSS 2.0 ou Atom (liste vide si le contenu n'en est pas un ou déclare des entités)."""
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
        resume = _texte(e, "description", "summary", "content")
        if source.mot and source.mot.casefold() not in (titre + " " + resume + " " + lien).casefold():
            continue
        cle = _texte(e, "guid", "id") or lien
        res.append(Article(source.nom, titre[:300], lien, _jour(_texte(e, "pubDate", "updated", "published", "date")), empreinte(source.nom, cle)))
        if len(res) >= MAX_ARTICLES:
            break
    return res


def telecharger(source: Source) -> bytes:
    """Contenu du flux (2 Mo au plus). Lève OSError / ValueError : l'appelant montre l'erreur."""
    if not adresse_valide(source.adresse):
        raise ValueError(_("adresse refusée (http ou https seulement)"))
    req = urllib.request.Request(source.adresse, headers={"User-Agent": "Scrinium", "Accept": "application/rss+xml, application/atom+xml, application/xml, */*"})
    with urllib.request.urlopen(req, timeout=DELAI) as r:                      # noqa: S310 (schéma vérifié ci-dessus)
        if not r.geturl().lower().startswith(("http://", "https://")):
            raise ValueError(_("redirection refusée"))
        return r.read(MAX_OCTETS)


def recuperer(source: Source, ouvrir=telecharger) -> tuple:
    """(articles, erreur) : jamais d'exception."""
    try:
        return analyser(source, ouvrir(source)), ""
    except Exception as ex:                                # réseau, adresse, flux illisible : montré, pas bloquant
        return [], str(ex)[:120]


def visibles(articles: list, doc: Document) -> list:
    """Articles des sources dont la case est cochée."""
    cochees = {s.nom for s in doc.sources if s.afficher}
    return [a for a in articles if a.source in cochees]


def non_lus(articles: list, doc: Document) -> list:
    """Articles non lus des sources cochées."""
    lus = set(doc.lus)
    return [a for a in visibles(articles, doc) if a.empreinte not in lus]


def marquer_lus(doc: Document, articles: list) -> None:
    lus = set(doc.lus)
    for a in articles:
        if a.empreinte not in lus:
            doc.lus.append(a.empreinte)
            lus.add(a.empreinte)
    del doc.lus[:-MAX_LUS]


# Nombre de non lus connu par fiche (empreinte de la liste de sources) : rempli par l'extension après chaque relève, lu par la pastille.
NON_LUS: dict = {}


def cle_sources(doc: Document) -> str:
    return hashlib.sha256("\n".join(s.adresse + "|" + s.mot for s in doc.sources).encode("utf-8")).hexdigest()[:16]


def a_faire(texte: str) -> str | None:
    doc = lire(texte)
    n = NON_LUS.get(cle_sources(doc), 0) if doc.sources else 0
    return _("%d nouveauté(s) à lire") % n if n else None


def texte_neuf() -> str:
    return ecrire(Document())


def exemples() -> list:
    doc = Document([Source("Scrinium (versions)", "https://github.com/jfkneib/scrinium/releases.atom")])
    return [(_("Veille (exemples)"), _("Exemple · Ma veille"), ecrire(doc))]


TYPE = TypeFiche("veille", N_("Veille"), "news-subscribe", executable=True, modele=texte_neuf, a_faire=a_faire)
