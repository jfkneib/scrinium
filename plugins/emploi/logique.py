# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Recherche d'emploi : listes de mots-clés, lien fort ou faible avec une annonce, suivi des candidatures, demande à préparer pour une IA (sans interface).

Texte de la fiche : réglages (`jours`, `indispensables`, `souhaites`, `exclus`), `## Profil` (texte libre), `## Sources` (tableau : nom, adresse, affiché),
`## Suivi` (tableau : statut, titre, lien, date du dernier changement, note) et `## Vus` (empreintes des annonces déjà vues ou écartées).

Le lien d'une annonce se décide sur les mots-clés, trouvés dans son titre, son résumé ou son adresse (sans tenir compte des majuscules ni des accents) :
  · « exclue »  : un mot à exclure est présent (l'annonce est écartée) ;
  · « fort »    : tous les mots indispensables sont présents (sans liste d'indispensables : au moins deux mots souhaités, ou le seul mot souhaité) ;
  · « faible »  : une partie seulement des mots est présente ;
  · « aucun »   : aucun mot présent (l'annonce n'est pas proposée).
Un mot peut avoir des variantes séparées par « | » (« admin système | sysadmin ») : une seule suffit. Rien n'est envoyé nulle part : la « demande pour une IA » est un
texte que l'utilisateur copie et relit."""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from scrinium.core import flux
from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-emploi"
MAX_SOURCES = 60
MAX_SUIVI = 500
MAX_VUS = 4000
MAX_MOTS = 40
MAX_PROFIL = 4000
JOURS_PAR_DEFAUT = 14
RELANCE_APRES = 7                                          # jours sans nouvelle après une candidature : la pastille rappelle de relancer
STATUTS = ("retenue", "postulée", "relancée", "entretien", "refus", "abandon")
LIBELLES_STATUTS = {"retenue": N_("retenue"), "postulée": N_("postulée"), "relancée": N_("relancée"), "entretien": N_("entretien"),
                    "refus": N_("refus"), "abandon": N_("abandon")}
_LIGNE = re.compile(r"^\|(.*)\|\s*$")


@dataclass
class Source:
    nom: str
    adresse: str
    afficher: bool = True


@dataclass
class Suivi:
    statut: str
    titre: str
    lien: str
    date: str                                              # jour du dernier changement de statut
    note: str = ""


@dataclass
class Profil:
    jours: int = JOURS_PAR_DEFAUT
    indispensables: list = field(default_factory=list)
    souhaites: list = field(default_factory=list)
    exclus: list = field(default_factory=list)
    profil: str = ""
    sources: list = field(default_factory=list)
    suivi: list = field(default_factory=list)
    vus: list = field(default_factory=list)


@dataclass
class Annonce:
    titre: str
    lien: str
    date: str
    resume: str
    source: str
    empreinte: str


@dataclass
class Lien:
    niveau: str                                            # fort · faible · aucun · exclue
    trouves: list
    manquants: list                                        # mots indispensables absents
    exclus: list                                           # mots à exclure présents
    score: int                                             # 0 à 100, pour trier à l'intérieur d'un niveau


# ---------- mots-clés ----------
def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.casefold()) if unicodedata.category(c) != "Mn")


def lire_mots(texte) -> list:
    """« python, django ; admin système | sysadmin » -> ["python", "django", "admin système | sysadmin"] (sans doublon, borné)."""
    res, vus = [], set()
    for x in re.split(r"[,;\n]+", str(texte or "")):
        x = " | ".join(" ".join(v.split()) for v in x.split("|") if v.strip())
        if x and sans_accents(x) not in vus and len(res) < MAX_MOTS:
            vus.add(sans_accents(x))
            res.append(x[:80])
    return res


def _present(mot: str, haystack: str) -> bool:
    """`haystack` est déjà sans accents et en minuscules. Un mot = mot entier ; « c++ » et « c# » marchent ; une variante suffit."""
    for variante in mot.split("|"):
        v = sans_accents(variante.strip())
        if v and re.search(r"(?<![\w+#])" + re.escape(v) + r"(?![\w+#])", haystack):
            return True
    return False


def evaluer(a: Annonce, p: Profil) -> Lien:
    h = sans_accents(a.titre + " " + a.resume + " " + a.lien)
    exclus = [m for m in p.exclus if _present(m, h)]
    if exclus:
        return Lien("exclue", [], [], exclus, 0)
    ind = [m for m in p.indispensables if _present(m, h)]
    sou = [m for m in p.souhaites if _present(m, h)]
    manquants = [m for m in p.indispensables if m not in ind]
    trouves = ind + sou
    if not trouves:
        return Lien("aucun", [], manquants, [], 0)
    if p.indispensables:
        fort = not manquants
    else:
        fort = len(sou) >= min(2, len(p.souhaites))
    pi = len(ind) / len(p.indispensables) if p.indispensables else None
    ps = len(sou) / len(p.souhaites) if p.souhaites else None
    if pi is None:
        score = ps or 0
    elif ps is None:
        score = pi
    else:
        score = 0.7 * pi + 0.3 * ps
    return Lien("fort" if fort else "faible", trouves, manquants, [], round(100 * score))


def empreinte(source: str, cle: str) -> str:
    return hashlib.sha256((source + "\n" + cle).encode("utf-8")).hexdigest()[:10]


def recentes(annonces: list, jours: int, aujourdhui: date | None = None) -> list:
    """Annonces publiées depuis `jours` jours (celles dont la date est inconnue sont gardées : mieux vaut les voir que les perdre)."""
    limite = ((aujourdhui or date.today()) - timedelta(days=max(1, jours))).isoformat()
    return [a for a in annonces if not a.date or a.date[:10] >= limite]


def proposees(annonces: list, p: Profil, faibles: bool = True, aujourdhui: date | None = None) -> list:
    """[(annonce, lien)] à montrer : récentes, ni exclues ni sans rapport, ni déjà vues ou écartées, les plus fortes d'abord puis les plus récentes."""
    vus = set(p.vus)
    res = []
    for a in recentes(annonces, p.jours, aujourdhui):
        if a.empreinte in vus:
            continue
        lien = evaluer(a, p)
        if lien.niveau == "fort" or (faibles and lien.niveau == "faible"):
            res.append((a, lien))
    res.sort(key=lambda x: (x[1].niveau != "fort", -x[1].score, _inverse(x[0].date)))
    return res


def _inverse(d: str) -> str:
    """Clé pour trier les dates de la plus récente à la plus ancienne (inconnue en dernier)."""
    return "".join(chr(0x10FFFF - ord(c)) for c in d) if d else "\U0010ffff"


def vue(p: Profil, a: Annonce) -> None:
    if a.empreinte not in p.vus:
        p.vus.append(a.empreinte)
        del p.vus[:-MAX_VUS]


# ---------- suivi ----------
def retenir(p: Profil, a: Annonce, aujourdhui: date | None = None) -> bool:
    """Met l'annonce dans le suivi (« retenue ») ; False si elle y est déjà ou si le suivi est plein."""
    if any(s.lien == a.lien for s in p.suivi) or len(p.suivi) >= MAX_SUIVI:
        return False
    p.suivi.append(Suivi("retenue", a.titre[:200], a.lien, (aujourdhui or date.today()).isoformat()))
    vue(p, a)
    return True


def changer_statut(s: Suivi, statut: str, aujourdhui: date | None = None) -> None:
    if statut in STATUTS:
        s.statut, s.date = statut, (aujourdhui or date.today()).isoformat()


def relances(p: Profil, aujourdhui: date | None = None) -> list:
    """Candidatures (postulée ou relancée) sans nouvelle depuis `RELANCE_APRES` jours."""
    limite = ((aujourdhui or date.today()) - timedelta(days=RELANCE_APRES)).isoformat()
    return [s for s in p.suivi if s.statut in ("postulée", "relancée") and s.date and s.date <= limite]


# ---------- texte de la fiche ----------
def lire_jour(t) -> str:
    t = str(t or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def lire(texte: str | None) -> Profil:
    p, section, profil = Profil(), "", []
    for brut in (texte or "").lstrip("﻿").splitlines():
        ligne = brut.strip()
        if ligne.startswith(MARQUE):
            continue
        if ligne.startswith("## "):
            t = ligne[3:].strip().lower()
            section = "profil" if t.startswith("profil") else ("sources" if t.startswith("source") else ("suivi" if t.startswith("suivi") else
                                                                                                          ("vus" if t.startswith("vu") else "")))
            continue
        if section == "profil":
            profil.append(brut.rstrip())
        elif section == "vus":
            if re.fullmatch(r"[0-9a-f]{10}", ligne) and len(p.vus) < MAX_VUS:
                p.vus.append(ligne)
        elif section in ("sources", "suivi"):
            m = _LIGNE.match(ligne)
            if not m:
                continue
            c = [x.strip() for x in m[1].split("|")]
            if all(re.fullmatch(r":?-{2,}:?", x) for x in c if x):
                continue
            if section == "sources" and len(c) >= 2 and flux.adresse_valide(c[1]) and len(p.sources) < MAX_SOURCES:
                p.sources.append(Source(" ".join(c[0].split())[:60] or c[1][:60], c[1], (c[2].lower() if len(c) > 2 else "oui") not in ("non", "no", "0")))
            elif section == "suivi" and len(c) >= 3 and c[0] in STATUTS and flux.adresse_valide(c[2]) and len(p.suivi) < MAX_SUIVI:
                p.suivi.append(Suivi(c[0], " ".join(c[1].split())[:200], c[2], lire_jour(c[3] if len(c) > 3 else ""), (c[4] if len(c) > 4 else "")[:200]))
        elif ":" in ligne:
            cle, _s, v = ligne.partition(":")
            cle = cle.strip().lower()
            if cle == "jours":
                m = re.search(r"\d+", v)
                p.jours = min(90, max(1, int(m[0]))) if m else JOURS_PAR_DEFAUT
            elif cle in ("indispensables", "souhaites", "souhaités", "exclus"):
                setattr(p, "souhaites" if cle.startswith("souhait") else cle, lire_mots(v))
    p.profil = "\n".join(profil).strip()[:MAX_PROFIL]
    return p


def ecrire(p: Profil) -> str:
    s = [MARQUE, f"jours: {p.jours}", "indispensables: " + ", ".join(p.indispensables), "souhaites: " + ", ".join(p.souhaites), "exclus: " + ", ".join(p.exclus),
         "", "## Profil"] + [ligne if not ligne.startswith("## ") else " " + ligne for ligne in p.profil.splitlines()]
    s += ["", "## Sources", "| Source | Adresse du flux | Affiché |", "|---|---|---|"]
    for x in p.sources[:MAX_SOURCES]:
        s.append("| %s | %s | %s |" % (x.nom.replace("|", "/"), x.adresse.replace("|", "%7C"), "oui" if x.afficher else "non"))
    s += ["", "## Suivi", "| Statut | Titre | Lien | Date | Note |", "|---|---|---|---|---|"]
    for x in p.suivi[:MAX_SUIVI]:
        s.append("| %s | %s | %s | %s | %s |" % (x.statut, x.titre.replace("|", "/"), x.lien.replace("|", "%7C"), x.date, x.note.replace("|", "/").replace("\n", " ")))
    if p.vus:
        s += ["", "## Vus"] + p.vus[-MAX_VUS:]
    return "\n".join(s) + "\n"


# ---------- relève ----------
def annonces_du_flux(source: Source, contenu: bytes) -> list:
    return [Annonce(e.titre, e.lien, e.date, e.resume, source.nom, empreinte(source.nom, e.cle)) for e in flux.entrees(contenu)]


def recuperer(source: Source, ouvrir=None) -> tuple:
    """(annonces, erreur) : jamais d'exception."""
    try:
        contenu = (ouvrir or (lambda s: flux.telecharger(s.adresse)))(source)
        return annonces_du_flux(source, contenu), ""
    except Exception as ex:                                # réseau, adresse, flux illisible : montré, pas bloquant
        return [], str(ex)[:120]


# Nombre de nouvelles annonces fortes connu par fiche (empreinte de la recherche) : rempli par l'extension après chaque relève, lu par la pastille.
NOUVELLES: dict = {}


def cle_recherche(p: Profil) -> str:
    base = "\n".join(s.adresse for s in p.sources if s.afficher) + "\n" + "|".join(p.indispensables + p.souhaites + p.exclus) + f"\n{p.jours}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def a_faire(texte: str, aujourdhui: date | None = None) -> str | None:
    """Pastille de la liste : nouvelles annonces à lien fort non vues, et candidatures à relancer."""
    p = lire(texte)
    morceaux = []
    n = NOUVELLES.get(cle_recherche(p), 0) if p.sources else 0
    if n:
        morceaux.append(_("%d nouvelle(s) annonce(s) à lien fort") % n)
    r = len(relances(p, aujourdhui))
    if r:
        morceaux.append(_("%d candidature(s) à relancer") % r)
    return " · ".join(morceaux) or None


# ---------- la demande à préparer pour une IA ----------
def demande_ia(p: Profil, a: Annonce, lien: Lien) -> str:
    """Texte à copier dans l'assistant de son choix. Il ne part nulle part tout seul ; l'utilisateur le relit et le complète."""
    profil = p.profil.strip() or _("(à compléter : mon parcours, mes compétences, ce que je cherche)")
    l = [_("Tu m'aides à préparer une candidature. Réponds en français."), "",
         _("## Mon profil"), profil, "",
         _("## L'annonce"), _("Titre : %s") % a.titre, _("Source : %s") % a.source, _("Lien : %s") % a.lien]
    if a.date:
        l.append(_("Publiée : %s") % a.date[:10])
    l += [_("Texte de l'annonce (extrait) :"), a.resume or _("(ouvre le lien pour le texte complet, je le collerai ici)"), "",
          _("## Correspondance avec mes mots-clés"), _("Trouvés : %s") % (", ".join(lien.trouves) or _("aucun")),
          _("Indispensables manquants : %s") % (", ".join(lien.manquants) or _("aucun")), "",
          _("## Ce que je te demande"),
          _("1. Une lettre de motivation courte (200 mots environ), sobre et précise."),
          _("2. Les cinq points de mon profil à mettre en avant pour cette annonce, et comment les formuler dans mon CV."),
          _("3. Les points faibles de ma candidature et les questions à préparer pour un entretien."), "",
          _("## Règles"),
          _("- N'invente aucune expérience, aucun diplôme ni aucune compétence : appuie-toi uniquement sur mon profil."),
          _("- S'il te manque une information, pose-moi la question avant d'écrire."),
          _("- Signale ce qui, dans l'annonce, ne correspond pas à mon profil.")]
    return "\n".join(l)


def texte_neuf() -> str:
    return ecrire(Profil())


# Flux publics d'offres d'emploi (vérifiés le 2026-11-11 : ils répondent et contiennent des offres). Télétravail (en anglais) puis France et Luxembourg.
SOURCES_EXEMPLE = [
    ("Remotive (télétravail)", "https://remotive.com/remote-jobs/feed"),
    ("We Work Remotely · programmation", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("We Work Remotely · devops et sysadmin", "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"),
    ("Python.org · offres", "https://www.python.org/jobs/feed/rss/"),
    ("Hacker News · offres", "https://hnrss.org/jobs"),
    ("Jobicy (télétravail)", "https://jobicy.com/feed/job_feed"),
    ("Himalayas (télétravail)", "https://himalayas.app/jobs/rss"),
    ("Emploi Territorial (collectivités, France)", "https://www.emploi-territorial.fr/rss"),
    ("Cadremploi (France)", "http://services.cadremploi.fr/services/search/rss"),
    ("Codeur (freelance, France)", "https://www.codeur.com/?format=rss"),
    ("Emploi Collectivités (France)", "https://www.emploi-collectivites.fr/rss.asp"),
    ("Emploi Environnement (France)", "https://www.emploi-environnement.com/rss.xml"),
    ("CNRS (recherche, France)", "https://emploi.cnrs.fr/Rss/Offres.ashx"),
    ("Choisir le service public (France)", "https://place-ep-recrute.talent-soft.com/handlers/offerRss.ashx?LCID=1036"),
    ("Banque de Luxembourg", "https://jobs.banquedeluxembourg.com/handlers/offerRss.ashx?LCID=1036"),
    ("Emploi LR (Occitanie)", "https://www.emploilr.com/rss/offre_emploi_lr.xml"),
    ("Passerelles (ministère de l'Économie)", "https://passerelles.economie.gouv.fr/handlers/offerRss.ashx?LCID=1036"),
    ("Air France", "https://recrutement.airfrance.com/handlers/offerRss.ashx?LCID=1036"),
]


def exemples() -> list:
    p = Profil(14, ["python", "linux"], ["xmpp", "remote | télétravail | teletravail", "devops | sysadmin"], ["stage", "alternance", "internship"],
               _("Développeur Python, dix ans d'expérience, administration Linux, intérêt pour les messageries (XMPP)."),
               [Source(nom, adresse, True) for nom, adresse in SOURCES_EXEMPLE])
    return [(_("Emploi (exemples)"), _("Exemple · Ma recherche d'emploi"), ecrire(p))]


TYPE = TypeFiche("emploi", N_("Recherche d'emploi"), "user-identity", executable=True, modele=texte_neuf, a_faire=a_faire)
