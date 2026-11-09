# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Planning » : des tâches, un diagramme de Gantt, un rétroplanning.

    #scrinium-planning
    fin: 2026-12-20
    couleur Logistique: #e67e22

    | Tâche | Début | Fin | % | Qui | Catégorie | Après |
    | --- | --- | --- | --- | --- | --- | --- |
    | Trouver un camion | 2026-11-10 | 2026-11-12 | 100 | Marie | Logistique | |
    | Faire les cartons | 2026-11-13 | 2026-11-30 | 40 | | Logistique | Trouver un camion |
    | Jour J | 2026-12-20 | | | | | Faire les cartons |

- `fin:` date de fin du projet (facultative ; sert au rétroplanning) ; `couleur Catégorie: #rrggbb` (facultatif ; sinon une couleur stable
  est tirée de la catégorie).
- Début et Fin sont INCLUS (une tâche du 10 au 12 dure 3 jours). Une ligne SANS Fin est un jalon (un losange, à la date de Début).
  Une ligne sans Début n'est pas encore planifiée (« Recaler » lui donne des dates).
- `Après` : noms de tâches (séparés par « ; ») qui doivent être finies avant. Sert aux flèches et au calcul des dates.
- Type NON exécutable : la fiche ne lance rien. Le reste du texte (notes libres) est conservé.
- Une seconde fiche, `planning-resultat`, fait le point sur les plannings du même thème (ou de tous) : voir `resultat()`."""
import csv
import io
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-planning"
MARQUE_RESULTAT = "#scrinium-planning-resultat"
ENTETES = ["Tâche", "Début", "Fin", "%", "Qui", "Catégorie", "Après"]
MAX_TACHES = 5000
PALETTE = ["#3d85c6", "#e67e22", "#27ae60", "#9b59b6", "#c0392b", "#16a085", "#d4ac0d", "#d35498"]
COULEUR_DEFAUT = "#7f8c8d"


@dataclass
class Tache:
    nom: str
    debut: str = ""                     # AAAA-MM-JJ ; vide = pas encore planifiée
    fin: str = ""                       # AAAA-MM-JJ, inclus ; vide (avec un début) = jalon
    pourcent: int = 0                   # 0 à 100
    qui: str = ""
    categorie: str = ""
    apres: list = field(default_factory=list)       # noms de tâches à finir avant

    @property
    def jalon(self) -> bool:
        return bool(self.debut) and not self.fin

    @property
    def planifiee(self) -> bool:
        return bool(self.debut)


@dataclass
class Planning:
    taches: list = field(default_factory=list)
    fin: str = ""                                   # fin du projet (facultative)
    couleurs: dict = field(default_factory=dict)    # catégorie -> « #rrggbb »
    notes: str = ""


# ---------- dates ----------
def date_valide(texte: str) -> bool:
    try:
        date.fromisoformat((texte or "").strip())
        return True
    except ValueError:
        return False


def _d(texte: str) -> date:
    return date.fromisoformat(texte.strip())


def _s(d: date) -> str:
    return d.isoformat()


def duree(t: Tache) -> int:
    """Nombre de jours (début et fin inclus) ; 1 pour un jalon ou une tâche non planifiée."""
    if t.debut and t.fin and date_valide(t.debut) and date_valide(t.fin):
        return max(1, (_d(t.fin) - _d(t.debut)).days + 1)
    return 1


def fin_effective(t: Tache) -> str:
    return t.fin or t.debut


# ---------- le texte de la fiche ----------
def _decouper(ligne: str) -> list:
    s = ligne.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def _cellule(texte: str) -> str:
    return (texte or "").replace("|", "\\|").replace("\n", " ").strip()


def _pourcent(texte: str) -> int:
    m = re.search(r"\d+", texte or "")
    return min(100, int(m.group())) if m else 0


def _apres(texte: str) -> list:
    return [x.strip() for x in re.split(r"[;,]", texte or "") if x.strip()]


def lire(texte: str | None) -> Planning:
    p = Planning()
    corps = (texte or "").replace("\r\n", "\n").split("\n")
    if corps and corps[0].startswith(MARQUE):
        corps = corps[1:]
    notes = []
    for l in corps:
        s = l.strip()
        f = re.match(r"^fin[ \t]*:[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*$", s, re.IGNORECASE)
        c = re.match(r"^couleur[ \t]+(.+?)[ \t]*:[ \t]*(#[0-9a-fA-F]{6})[ \t]*$", s, re.IGNORECASE)
        if s.startswith("|"):
            cells = _decouper(l)
            if all(re.fullmatch(r":?-{3,}:?", x) for x in cells) or cells[:1] == ["Tâche"] or len(p.taches) >= MAX_TACHES:
                continue
            cells = (cells + [""] * 7)[:7]
            if not cells[0]:
                continue
            debut = cells[1] if date_valide(cells[1]) else ""
            fin = cells[2] if debut and date_valide(cells[2]) else ""
            if fin and fin < debut:
                fin = debut
            p.taches.append(Tache(cells[0], debut, fin, _pourcent(cells[3]), cells[4], cells[5], _apres(cells[6])))
        elif f and date_valide(f.group(1)):
            p.fin = f.group(1)
        elif c:
            p.couleurs[c.group(1)] = c.group(2).lower()
        else:
            notes.append(l)
    while notes and not notes[0].strip():
        notes.pop(0)
    while notes and not notes[-1].strip():
        notes.pop()
    p.notes = "\n".join(notes)
    return p


def ecrire(p: Planning) -> str:
    sortie = [MARQUE]
    if p.fin:
        sortie.append(f"fin: {p.fin}")
    for cat in sorted(p.couleurs):
        sortie.append(f"couleur {cat}: {p.couleurs[cat]}")
    sortie += ["", "| " + " | ".join(ENTETES) + " |", "| " + " | ".join(["---"] * len(ENTETES)) + " |"]
    for t in p.taches:
        sortie.append("| " + " | ".join([_cellule(t.nom), t.debut, t.fin, str(t.pourcent) if t.pourcent else "", _cellule(t.qui),
                                          _cellule(t.categorie), _cellule(" ; ".join(t.apres))]) + " |")
    if p.notes.strip():
        sortie += ["", p.notes.strip()]
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return ecrire(Planning())


def vers_csv(p: Planning) -> str:
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    w.writerow(ENTETES)
    for t in p.taches:
        w.writerow([t.nom, t.debut, t.fin, t.pourcent, t.qui, t.categorie, " ; ".join(t.apres)])
    return sortie.getvalue()


# ---------- couleurs ----------
def couleur(p: Planning, categorie: str) -> str:
    """Couleur choisie pour la catégorie, sinon une couleur stable tirée de son nom (la même d'une fiche à l'autre)."""
    if categorie in p.couleurs:
        return p.couleurs[categorie]
    if not categorie:
        return PALETTE[0]
    return PALETTE[zlib.crc32(categorie.lower().encode("utf-8")) % len(PALETTE)]


# ---------- état et bilan ----------
def etat(t: Tache, aujourdhui: date | None = None) -> str:
    """« fini », « retard », « en_cours », « a_venir » ou « non_planifie »."""
    ajd = aujourdhui or date.today()
    if t.pourcent >= 100:
        return "fini"
    if not t.planifiee:
        return "non_planifie"
    fin = _d(fin_effective(t))
    if fin < ajd:
        return "retard"
    if _d(t.debut) <= ajd or t.pourcent > 0:
        return "en_cours"
    return "a_venir"


def bilan(p: Planning, aujourdhui: date | None = None) -> dict:
    """Totaux : tâches par état, avancement global (pondéré par la durée), première et dernière date."""
    compte = {"fini": 0, "retard": 0, "en_cours": 0, "a_venir": 0, "non_planifie": 0}
    poids = fait = 0
    debuts, fins = [], []
    for t in p.taches:
        compte[etat(t, aujourdhui)] += 1
        d = duree(t)
        poids += d
        fait += d * t.pourcent
        if t.planifiee:
            debuts.append(t.debut)
            fins.append(fin_effective(t))
    return {"total": len(p.taches), **compte, "avancement": round(fait / poids) if poids else 0,
            "debut": min(debuts) if debuts else "", "fin": max(fins) if fins else ""}


# ---------- dépendances et calcul des dates ----------
def _cle(nom: str) -> str:
    return nom.strip().lower()


def _precedentes(p: Planning) -> dict:
    """indice d'une tâche -> indices des tâches qu'elle attend (les noms inconnus sont ignorés ; on ne s'attend pas soi-même)."""
    par_nom = {}
    for i, t in enumerate(p.taches):
        par_nom.setdefault(_cle(t.nom), i)
    return {i: sorted({par_nom[_cle(n)] for n in t.apres if _cle(n) in par_nom} - {i}) for i, t in enumerate(p.taches)}


def ordre(p: Planning) -> list:
    """Indices des tâches, chaque tâche après celles qu'elle attend. ValueError s'il y a une boucle (A après B après A)."""
    prec = _precedentes(p)
    vus, en_cours, sortie = set(), set(), []

    def visite(i):
        if i in vus:
            return
        if i in en_cours:
            raise ValueError(_("Boucle dans les dépendances autour de « %s »") % p.taches[i].nom)
        en_cours.add(i)
        for j in prec[i]:
            visite(j)
        en_cours.discard(i)
        vus.add(i)
        sortie.append(i)
    for i in range(len(p.taches)):
        visite(i)
    return sortie


def dependances(p: Planning) -> list:
    """[(indice de la tâche attendue, indice de la tâche qui attend)] pour dessiner les flèches."""
    return [(j, i) for i, js in _precedentes(p).items() for j in js]


def recaler_avant(p: Planning, depart: date) -> None:
    """Planifie en avant : une tâche commence le `depart` ou le lendemain de la fin de ce qu'elle attend, la plus tardive des deux.
    Les durées sont gardées ; les tâches finies (100 %) ne bougent pas. ValueError s'il y a une boucle."""
    prec = _precedentes(p)
    for i in ordre(p):
        t = p.taches[i]
        if t.pourcent >= 100 and t.planifiee:
            continue
        d, jalon = duree(t), t.jalon
        debut = depart
        for j in prec[i]:
            if p.taches[j].planifiee:
                debut = max(debut, _d(fin_effective(p.taches[j])) + timedelta(days=1))
        t.debut = _s(debut)
        t.fin = "" if jalon else _s(debut + timedelta(days=d - 1))


def recaler_arriere(p: Planning, fin: date) -> None:
    """Rétroplanning : en partant de la `fin` du projet, une tâche finit le `fin` ou la veille du début de ce qui l'attend, la plus
    précoce des deux. Les durées sont gardées ; les tâches finies (100 %) ne bougent pas. ValueError s'il y a une boucle."""
    prec = _precedentes(p)
    suivantes: dict = {i: [] for i in range(len(p.taches))}
    for i, js in prec.items():
        for j in js:
            suivantes[j].append(i)
    for i in reversed(ordre(p)):
        t = p.taches[i]
        if t.pourcent >= 100 and t.planifiee:
            continue
        d, jalon = duree(t), t.jalon
        bout = fin
        for k in suivantes[i]:
            if p.taches[k].planifiee:
                bout = min(bout, _d(p.taches[k].debut) - timedelta(days=1))
        t.debut = _s(bout - timedelta(days=d - 1))
        t.fin = "" if jalon else _s(bout)
    p.fin = _s(fin)


def tache_neuve(nom: str, debut: str, jours: int, categorie: str = "", qui: str = "", apres: str = "") -> Tache:
    """Une tâche de `jours` jours à partir de `debut` (1 jour = ce jour-là) ; 0 jour = un jalon."""
    t = Tache(nom.strip(), categorie=categorie.strip(), qui=qui.strip(), apres=_apres(apres))
    if date_valide(debut):
        t.debut = debut.strip()
        t.fin = "" if jours <= 0 else _s(_d(debut) + timedelta(days=jours - 1))
    return t


# ---------- la fiche « résultat » : plusieurs plannings ----------
def est_planning(texte: str | None) -> bool:
    t = (texte or "").lstrip("\ufeff")
    return t.startswith(MARQUE) and not t.startswith(MARQUE_RESULTAT) and (len(t) == len(MARQUE) or t[len(MARQUE)] in " \t\r\n")


def portee_de(texte: str | None) -> str:
    """Portée de la fiche « résultat » : « theme » (les plannings du même thème, par défaut) ou « tous » (tous les thèmes)."""
    m = re.search(r"^portée[ \t]*:[ \t]*(\w+)[ \t]*$|^portee[ \t]*:[ \t]*(\w+)[ \t]*$", texte or "", re.IGNORECASE | re.MULTILINE)
    v = ((m.group(1) or m.group(2)) if m else "theme").lower()
    return "tous" if v == "tous" else "theme"


def texte_resultat(portee: str, ancien: str | None = None) -> str:
    """Texte de la fiche « résultat » avec cette portée ; le reste du texte (notes libres) est conservé."""
    reste = [l for l in (ancien or "").replace("\r\n", "\n").split("\n")[1:] if not re.match(r"^(portée|portee)[ \t]*:", l.strip(), re.IGNORECASE)]
    while reste and not reste[0].strip():
        reste.pop(0)
    return "\n".join([MARQUE_RESULTAT] + (["portée: tous"] if portee == "tous" else []) + ([""] + reste if reste else [])).rstrip("\n") + "\n"


def resultat(plannings: list, aujourdhui: date | None = None) -> dict:
    """Synthèse de plusieurs plannings : `plannings` = [(nom, Planning)].
    {lignes: [(nom, bilan)], total: bilan cumulé, retards: [(nom du planning, tâche, fin, %)] triés par date}."""
    lignes, retards = [], []
    poids = fait = 0
    total = {"total": 0, "fini": 0, "retard": 0, "en_cours": 0, "a_venir": 0, "non_planifie": 0, "debut": "", "fin": ""}
    for nom, p in plannings:
        b = bilan(p, aujourdhui)
        lignes.append((nom, b))
        for k in ("total", "fini", "retard", "en_cours", "a_venir", "non_planifie"):
            total[k] += b[k]
        total["debut"] = min([x for x in (total["debut"], b["debut"]) if x], default="")
        total["fin"] = max(total["fin"], b["fin"])
        for t in p.taches:
            poids += duree(t)
            fait += duree(t) * t.pourcent
            if etat(t, aujourdhui) == "retard":
                retards.append((nom, t.nom, fin_effective(t), t.pourcent))
    total["avancement"] = round(fait / poids) if poids else 0
    retards.sort(key=lambda r: (r[2], r[0], r[1]))
    return {"lignes": lignes, "total": total, "retards": retards}


# ---------- exemples ----------
def exemples(aujourdhui: date | None = None) -> list:
    """[(thème, titre, texte)] : des fiches d'exemple, créées à la première activation de l'extension."""
    ajd = aujourdhui or date.today()
    demenagement = Planning(notes=_("Exemple de rétroplanning : on a fixé le jour du déménagement (« fin: » en haut), et les dates sont "
                                    "calculées à rebours à partir des durées et des tâches « Après ». Changez la date de fin puis "
                                    "cliquez sur « Calculer les dates > À rebours d'une date de fin » : tout se décale. Supprimez cette "
                                    "fiche quand vous voulez."))
    def t(nom, jours, cat, apres="", pct=0):
        x = tache_neuve(nom, _s(ajd), jours, cat, apres=apres)
        x.pourcent = pct
        return x
    c_admin, c_log, c_fin = _("Démarches"), _("Logistique"), _("Jour J")
    demenagement.taches = [
        t(_("Donner son préavis"), 1, c_admin, pct=100),
        t(_("Réserver le camion"), 1, c_log, _("Donner son préavis"), 100),
        t(_("Acheter des cartons"), 2, c_log, _("Donner son préavis")),
        t(_("Faire les cartons"), 14, c_log, _("Acheter des cartons")),
        t(_("Changer d'adresse (banque, assurance…)"), 5, c_admin, _("Donner son préavis")),
        t(_("Nettoyer l'ancien logement"), 3, c_log, _("Faire les cartons")),
        t(_("Déménagement"), 0, c_fin, _("Nettoyer l'ancien logement ; Réserver le camion")),
    ]
    try:
        recaler_arriere(demenagement, ajd + timedelta(days=45))
    except ValueError:
        pass
    projet = Planning(notes=_("Exemple : un petit projet planifié en avant. Les barres sont colorées par catégorie ; le remplissage montre "
                              "l'avancement (colonne « % »). Une tâche dont la date de fin est passée et qui n'est pas à 100 % est en "
                              "retard (en rouge)."))
    p1 = tache_neuve(_("Cahier des charges"), _s(ajd - timedelta(days=12)), 5, _("Étude"))
    p1.pourcent = 100
    p2 = tache_neuve(_("Maquette"), _s(ajd - timedelta(days=6)), 4, _("Étude"), apres=_("Cahier des charges"))
    p2.pourcent = 60
    p3 = tache_neuve(_("Réalisation"), _s(ajd + timedelta(days=1)), 10, _("Travaux"), apres=_("Maquette"))
    p4 = tache_neuve(_("Livraison"), _s(ajd + timedelta(days=12)), 0, _("Étude"), apres=_("Réalisation"))
    projet.taches = [p1, p2, p3, p4]
    return [(_("Planning (exemples)"), _("Exemple · Déménagement (rétroplanning)"), ecrire(demenagement)),
            (_("Planning (exemples)"), _("Exemple · Petit projet"), ecrire(projet)),
            (_("Planning (exemples)"), _("Exemple · Résultat de mes plannings"),
             MARQUE_RESULTAT + "\n\n" + _("Cette fiche fait le point sur les plannings (fiches « Planning ») du même thème que celle-ci, ou sur tous si "
                                          "vous le choisissez en haut : avancement, retards, dates. Elle se met à jour quand on l'ouvre ou qu'on "
                                          "clique sur « Actualiser ».") + "\n")]


TYPE = TypeFiche("planning", N_("Planning"), "view-calendar-timeline", modele=texte_neuf)
TYPE_RESULTAT = TypeFiche("planning-resultat", N_("Planning — résultat"), "view-statistics", modele=lambda: MARQUE_RESULTAT + "\n")
