# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Veille : sources RSS / Atom, nouveautés, « lu » (sans interface).

Sûreté : http et https seulement, délai de 10 s, 2 Mo au plus par flux, rien n'est exécuté ni téléchargé en dehors du flux, un flux qui déclare
des entités XML est refusé. La fiche est de type exécutable (elle fait des requêtes réseau) : inerte tant que l'utilisateur ne l'a pas validée."""
import hashlib
import re
from dataclasses import dataclass, field

from scrinium.core import flux
from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-veille"
MAX_SOURCES = 100
MAX_LUS = 3000
MAX_ARTICLES = 60                                          # par source
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


adresse_valide = flux.adresse_valide


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


def analyser(source: Source, contenu: bytes) -> list:
    """Articles d'un flux RSS 2.0 ou Atom (liste vide si le contenu n'en est pas un ou déclare des entités)."""
    res = []
    for e in flux.entrees(contenu):
        if source.mot and source.mot.casefold() not in (e.titre + " " + e.resume + " " + e.lien).casefold():
            continue
        res.append(Article(source.nom, e.titre, e.lien, e.date, empreinte(source.nom, e.cle)))
        if len(res) >= MAX_ARTICLES:
            break
    return res


def telecharger(source: Source) -> bytes:
    """Contenu du flux (2 Mo au plus). Lève OSError / ValueError : l'appelant montre l'erreur."""
    try:
        return flux.telecharger(source.adresse)
    except ValueError:
        raise ValueError(_("adresse refusée (http ou https seulement)")) from None


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


def marquer_non_lus(doc: Document, articles: list) -> None:
    """Remet des articles à « non lu » (retire leur empreinte de la liste des lus)."""
    retirer = {a.empreinte for a in articles}
    doc.lus = [e for e in doc.lus if e not in retirer]


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


# Flux publics d'informatique : un exemple de départ. Seuls quelques-uns sont cochés (colonne « Afficher ») : on coche ce que l'on veut voir.
EXEMPLES = [
    ("slixmpp (Codeberg)", "https://codeberg.org/poezio/slixmpp/releases.rss", False),
    ("ejabberd", "https://github.com/processone/ejabberd/releases.atom", False),
    ("Prosody (tags)", "https://github.com/bjc/prosody/tags.atom", False),
    ("XMPP Standards Foundation", "https://xmpp.org/feeds/all.atom.xml", False),
    ("GLPI", "https://github.com/glpi-project/glpi/releases.atom", False),
    ("Microsoft Security Update Guide", "https://api.msrc.microsoft.com/update-guide/rss", False),
    ("CERT-FR (ANSSI)", "https://www.cert.ssi.gouv.fr/feed/", True),
    ("Debian Security Advisories", "https://www.debian.org/security/dsa-long", True),
    ("Ubuntu Security Notices", "https://ubuntu.com/security/notices/rss.xml", False),
    ("libvirt (tags)", "https://gitlab.com/libvirt/libvirt/-/tags?format=atom", False),
    ("QEMU (tags)", "https://gitlab.com/qemu-project/qemu/-/tags?format=atom", False),
    ("Kubernetes blog", "https://kubernetes.io/feed.xml", False),
    ("Ollama", "https://github.com/ollama/ollama/releases.atom", False),
    ("llama.cpp", "https://github.com/ggml-org/llama.cpp/releases.atom", False),
    ("Continue", "https://github.com/continuedev/continue/releases.atom", False),
    ("MCP Python SDK", "https://github.com/modelcontextprotocol/python-sdk/releases.atom", False),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", False),
    ("Django weblog", "https://www.djangoproject.com/rss/weblog/", False),
    ("Python Insider", "https://blog.python.org/feeds/posts/default", False),
    ("LinuxFr.org", "https://linuxfr.org/news.atom", True),
    ("LWN.net", "https://lwn.net/headlines/rss", True),
    ("Hacker News (200+ points)", "https://hnrss.org/frontpage?points=200", False),
]


def exemples() -> list:
    doc = Document([Source(nom, adresse, "", coche) for nom, adresse, coche in EXEMPLES])
    return [(_("Veille (exemples)"), _("Exemple · Veille informatique"), ecrire(doc))]


TYPE = TypeFiche("veille", N_("Veille"), "news-subscribe", executable=True, modele=texte_neuf, a_faire=a_faire)
