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


# Flux officiels français (Service-public, CNIL, Sénat, Légifrance...) : aucun n'est coché au départ.
EXEMPLES_GOUV = [
    ('Service-public.fr · actualités particuliers', 'https://www.service-public.fr/abonnements/rss/actu-actualites-particuliers.rss', False),
    ('Service-public.fr · actualités professionnels', 'https://www.service-public.fr/abonnements/rss/actu-actu-pro.rss', False),
    ('CNIL · actualités', 'https://www.cnil.fr/fr/rss.xml', False),
    ('CERT-FR (ANSSI)', 'https://www.cert.ssi.gouv.fr/feed/', False),
    ('Sénat · textes', 'https://www.senat.fr/rss/textes.rss', False),
    ('Sénat · rapports', 'https://www.senat.fr/rss/rapports.rss', False),
    ('Légifrance (legifrss) · lois', 'https://legifrss.org/latest?nature=loi', False),
    ('Sénat · Affaires étrangères et coopération', 'https://www.senat.fr/themes/rss/therss4.rss', False),
    ('Sénat · Agriculture et pêche', 'https://www.senat.fr/themes/rss/therss2.rss', False),
    ('Sénat · Aménagement du territoire', 'https://www.senat.fr/themes/rss/therss30.rss', False),
    ('Sénat · Anciens combattants', 'https://www.senat.fr/themes/rss/therss23.rss', False),
    ('Sénat · Budget', 'https://www.senat.fr/themes/rss/therss10.rss', False),
    ('Sénat · Collectivités territoriales', 'https://www.senat.fr/themes/rss/therss1.rss', False),
    ('Sénat · Culture', 'https://www.senat.fr/themes/rss/therss12.rss', False),
    ('Sénat · Défense', 'https://www.senat.fr/themes/rss/therss29.rss', False),
    ('Sénat · Économie et finances, fiscalité', 'https://www.senat.fr/themes/rss/therss17.rss', False),
    ('Sénat · Éducation', 'https://www.senat.fr/themes/rss/therss24.rss', False),
    ('Sénat · Énergie', 'https://www.senat.fr/themes/rss/therss32.rss', False),
    ('Sénat · Entreprises', 'https://www.senat.fr/themes/rss/therss33.rss', False),
    ('Sénat · Environnement', 'https://www.senat.fr/themes/rss/therss7.rss', False),
    ('Sénat · Famille', 'https://www.senat.fr/themes/rss/therss13.rss', False),
    ('Sénat · Fonction publique', 'https://www.senat.fr/themes/rss/therss19.rss', False),
    ('Sénat · Justice', 'https://www.senat.fr/themes/rss/therss14.rss', False),
    ('Sénat · Logement et urbanisme', 'https://www.senat.fr/themes/rss/therss16.rss', False),
    ('Sénat · Outre-mer', 'https://www.senat.fr/themes/rss/therss18.rss', False),
    ('Sénat · PME, commerce et artisanat', 'https://www.senat.fr/themes/rss/therss28.rss', False),
    ('Sénat · Police et sécurité', 'https://www.senat.fr/themes/rss/therss5.rss', False),
    ('Sénat · Pouvoirs publics et Constitution', 'https://www.senat.fr/themes/rss/therss9.rss', False),
    ('Sénat · Questions sociales et santé', 'https://www.senat.fr/themes/rss/therss20.rss', False),
    ('Sénat · Recherches, sciences et techniques', 'https://www.senat.fr/themes/rss/therss15.rss', False),
    ('Sénat · Sécurité sociale', 'https://www.senat.fr/themes/rss/therss25.rss', False),
    ('Sénat · Société', 'https://www.senat.fr/themes/rss/therss3.rss', False),
    ('Sénat · Sports', 'https://www.senat.fr/themes/rss/therss31.rss', False),
    ('Sénat · Traités et conventions', 'https://www.senat.fr/themes/rss/therss11.rss', False),
    ('Sénat · Transports', 'https://www.senat.fr/themes/rss/therss21.rss', False),
    ('Sénat · Travail', 'https://www.senat.fr/themes/rss/therss22.rss', False),
    ('Sénat · Union européenne', 'https://www.senat.fr/themes/rss/therss8.rss', False),
    ("Conseil d'État · actualités", 'https://www.conseil-etat.fr/rss/actualites-rss', False),
    ("Conseil d'État · colloques, séminaires et conférences", 'https://www.conseil-etat.fr/rss/colloques-seminaires-et-conferences-rss', False),
    ("Conseil d'État · avis", 'https://www.conseil-etat.fr/rss/avis-rss', False),
    ("Conseil d'État · études", 'https://www.conseil-etat.fr/rss/etudes-rss', False),
    ("Conseil d'État · rapports d'activité", 'https://www.conseil-etat.fr/rss/rapports-d-activite-rss', False),
    ("Conseil d'État · analyses de jurisprudence", 'https://www.conseil-etat.fr/rss/analyses-de-jurisprudence-rss', False),
    ("Conseil d'État · discours et interventions", 'https://www.conseil-etat.fr/rss/discours-et-interventions-rss', False),
    ("Conseil d'État · LJA", 'https://www.conseil-etat.fr/rss/lja-rss', False),
    ('Fonction publique · la DGAFP', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-la-dgafp', False),
    ('Fonction publique · être agent public', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-etre-agent-public', False),
    ('Fonction publique · droit de la fonction publique', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-droit-de-la-fonction-publique', False),
    ('Fonction publique · publications', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-publications-globales', False),
    ('Fonction publique · publications de la DGAFP', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-publication-dgafp', False),
    ('Fonction publique · études et statistiques', 'https://www.fonction-publique.gouv.fr/flux-rss-rubrique-etudes-et-statistiques', False),
    ('Fonction publique · rapport annuel', 'https://www.fonction-publique.gouv.fr/flux-rss-collection-etudes-et-statistiques-rapport-annuel', False),
    ('Fonction publique · Point Stat', 'https://www.fonction-publique.gouv.fr/flux-rss-collection-etudes-et-statistiques-point-stat', False),
    ('Fonction publique · Stats rapides', 'https://www.fonction-publique.gouv.fr/flux-rss-collection-etudes-et-statistiques-stats-rapides', False),
    ('Fonction publique · études, recherche, débats', 'https://www.fonction-publique.gouv.fr/flux-rss-collection-etudes-et-statistiques-etudes-recherche-debats', False),
]


def exemples() -> list:
    def fiche(liste):
        return ecrire(Document([Source(nom, adresse, "", coche) for nom, adresse, coche in liste]))
    return [(_("Veille (exemples)"), _("Exemple · Veille informatique"), fiche(EXEMPLES)),
            (_("Veille (exemples)"), _("Exemple · Veille gouvernement et droit"), fiche(EXEMPLES_GOUV))]


TYPE = TypeFiche("veille", N_("Veille"), "news-subscribe", executable=True, modele=texte_neuf, a_faire=a_faire)
