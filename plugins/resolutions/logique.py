# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Résolutions » : la fiche, les taux de réussite, les séries, la note automatique et les encouragements.

Texte d'une fiche (lisible et modifiable à la main) :

    #scrinium-resolutions
    ## Marcher 30 minutes
    cible: jour                  (ou « 3 par semaine »)
    debut: 2026-11-01
    fait: 2026-11-01, 2026-11-02, 2026-11-04

Une résolution est cochée ou non pour chaque jour. La note (sur 100) est la moyenne des taux de réussite des 14 derniers jours.
Le jour en cours, s'il n'est pas encore coché, n'est PAS compté contre vous : la journée n'est pas finie."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-resolutions"
MAX_RESOLUTIONS = 30
FENETRE = 14                                            # jours pris en compte pour le taux et la note
_PAR_SEMAINE = re.compile(r"(\d)\s*(?:fois)?\s*(?:par|/)\s*semaine", re.I)


def lire_jour(texte) -> str:
    t = str(texte or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


@dataclass
class Resolution:
    nom: str
    par_semaine: int = 0                                 # 0 = chaque jour ; 1 à 6 = autant de fois par semaine
    debut: str = ""                                      # premier jour compté (« 2026-11-01 »)
    fin: str = ""                                        # dernier jour compté (facultatif)
    faits: set = field(default_factory=set)              # jours cochés

    def cible_texte(self) -> str:
        return "jour" if not self.par_semaine else f"{self.par_semaine} par semaine"


def lire_cible(texte) -> int:
    m = _PAR_SEMAINE.search(str(texte or ""))
    return min(6, max(1, int(m[1]))) if m and int(m[1]) else 0


def normaliser(r: Resolution, aujourdhui: date | None = None) -> Resolution | None:
    nom = " ".join(str(r.nom).split())[:80]
    if not nom:
        return None
    auj = aujourdhui or date.today()
    debut = lire_jour(r.debut) or auj.isoformat()
    fin = lire_jour(r.fin)
    return Resolution(nom, r.par_semaine if 0 <= r.par_semaine <= 6 else 0, debut, fin if fin >= debut else "",
                      {j for j in (lire_jour(x) for x in r.faits) if j})


# ---------- le texte de la fiche ----------
def lire(texte: str | None, aujourdhui: date | None = None) -> list:
    res, courante = [], None
    lignes = (texte or "").lstrip("﻿").splitlines()
    for ligne in lignes[1:] if lignes and lignes[0].startswith(MARQUE) else lignes:
        if ligne.startswith("## "):
            courante = Resolution(ligne[3:])
            res.append(courante)
        elif courante is not None and ":" in ligne:
            cle, _sep, valeur = ligne.partition(":")
            cle = cle.strip().lower()
            if cle == "cible":
                courante.par_semaine = lire_cible(valeur)
            elif cle == "debut":
                courante.debut = valeur.strip()
            elif cle == "fin":
                courante.fin = valeur.strip()
            elif cle == "fait":
                courante.faits |= {x.strip() for x in valeur.split(",") if x.strip()}
    return [r for r in (normaliser(x, aujourdhui) for x in res) if r][:MAX_RESOLUTIONS]


def ecrire(resolutions: list) -> str:
    sortie = [MARQUE]
    for r in resolutions[:MAX_RESOLUTIONS]:
        sortie += ["", "## " + r.nom, "cible: " + r.cible_texte(), "debut: " + r.debut]
        if r.fin:
            sortie.append("fin: " + r.fin)
        faits = sorted(r.faits)
        for i in range(0, len(faits), 8):                 # des lignes courtes, faciles à relire
            sortie.append("fait: " + ", ".join(faits[i:i + 8]))
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return MARQUE + "\n"


def a_faire(texte: str, aujourdhui: date | None = None) -> str | None:
    """Pastille de la liste : des résolutions en cours qui ne sont pas encore cochées aujourd'hui (celles « n par semaine » seulement si
    la semaine n'est pas déjà remplie)."""
    auj = aujourdhui or date.today()
    jour = auj.isoformat()
    lundi = (auj - timedelta(days=auj.weekday())).isoformat()
    n = 0
    for r in lire(texte, auj):
        if r.debut > jour or (r.fin and r.fin < jour) or jour in r.faits:
            continue
        if r.par_semaine and sum(1 for j in r.faits if lundi <= j <= jour) >= r.par_semaine:
            continue
        n += 1
    return _("%d résolution(s) à cocher aujourd'hui") % n if n else None


TYPE = TypeFiche("resolutions", N_("Résolutions"), "task-complete", modele=texte_neuf, a_faire=a_faire)


# ---------- jours et semaines ----------
def _jours(du: date, au: date):
    d = du
    while d <= au:
        yield d
        d += timedelta(days=1)


def _lundi(d: date) -> date:
    return d - timedelta(days=d.weekday())


def est_fait(r: Resolution, jour: date) -> bool:
    return jour.isoformat() in r.faits


def basculer(r: Resolution, jour: date) -> bool:
    """Coche ou décoche un jour ; renvoie le nouvel état. Un jour avant le début recule le début (on peut cocher dans le passé)."""
    j = jour.isoformat()
    if j in r.faits:
        r.faits.discard(j)
        return False
    r.faits.add(j)
    if j < r.debut:
        r.debut = j
    return True


def _plage(r: Resolution, jusqu_a: date, fenetre: int) -> tuple | None:
    """(début, fin) des jours comptés : la fenêtre, limitée par le début et la fin de la résolution ; le jour en cours non coché n'est pas compté."""
    fin = jusqu_a if est_fait(r, jusqu_a) else jusqu_a - timedelta(days=1)
    if r.fin:
        fin = min(fin, date.fromisoformat(r.fin))
    debut = max(jusqu_a - timedelta(days=fenetre - 1), date.fromisoformat(r.debut))
    return (debut, fin) if debut <= fin else None


def taux(r: Resolution, jusqu_a: date, fenetre: int = FENETRE) -> float | None:
    """Taux de réussite (0 à 1) sur les `fenetre` derniers jours ; None s'il n'y a encore rien à compter."""
    plage = _plage(r, jusqu_a, fenetre)
    if plage is None:
        return None
    debut, fin = plage
    if not r.par_semaine:
        jours = list(_jours(debut, fin))
        return sum(1 for d in jours if est_fait(r, d)) / len(jours)
    # Par semaine : des semaines entières (la fenêtre est ramenée au lundi), chacune plafonnée à sa cible. La semaine en cours n'est jamais
    # comptée contre vous (elle n'est pas finie) : elle ne peut qu'améliorer le taux.
    fait_total = attendu_total = 0.0
    lundi = max(_lundi(debut), _lundi(date.fromisoformat(r.debut)))
    while lundi <= fin:
        jours = list(_jours(max(lundi, date.fromisoformat(r.debut)), min(lundi + timedelta(days=6), fin)))
        faits = min(sum(1 for d in jours if est_fait(r, d)), r.par_semaine)
        en_cours = lundi + timedelta(days=6) >= jusqu_a
        attendu = faits if en_cours else r.par_semaine * len(jours) / 7
        fait_total += min(faits, attendu)
        attendu_total += attendu
        lundi += timedelta(days=7)
    return fait_total / attendu_total if attendu_total else None


def _semaine_ok(r: Resolution, lundi: date) -> bool:
    return sum(1 for d in _jours(lundi, lundi + timedelta(days=6)) if est_fait(r, d)) >= r.par_semaine


def serie(r: Resolution, jusqu_a: date) -> int:
    """Jours d'affilée (chaque jour) ou semaines d'affilée (N par semaine) réussis, jusqu'à aujourd'hui. Le jour ou la semaine en cours, pas encore
    réussi, ne casse pas la série : il reste du temps."""
    debut = date.fromisoformat(r.debut)
    n = 0
    if not r.par_semaine:
        d = jusqu_a if est_fait(r, jusqu_a) else jusqu_a - timedelta(days=1)
        while d >= debut and est_fait(r, d):
            n += 1
            d -= timedelta(days=1)
        return n
    lundi = _lundi(jusqu_a)
    if not _semaine_ok(r, lundi):
        lundi -= timedelta(days=7)
    while lundi + timedelta(days=6) >= debut and _semaine_ok(r, lundi):
        n += 1
        lundi -= timedelta(days=7)
    return n


def meilleure_serie(r: Resolution, jusqu_a: date) -> int:
    debut, meilleure, courante = date.fromisoformat(r.debut), 0, 0
    if not r.par_semaine:
        for d in _jours(debut, jusqu_a):
            courante = courante + 1 if est_fait(r, d) else 0
            meilleure = max(meilleure, courante)
        return meilleure
    lundi = _lundi(debut)
    while lundi <= jusqu_a:
        courante = courante + 1 if _semaine_ok(r, lundi) else 0
        meilleure = max(meilleure, courante)
        lundi += timedelta(days=7)
    return meilleure


# ---------- note, étoiles, encouragements ----------
def score(resolutions: list, jusqu_a: date, fenetre: int = FENETRE) -> int | None:
    """Note sur 100 : moyenne des taux de réussite de toutes les résolutions sur la fenêtre ; None s'il n'y a encore rien à compter."""
    taux_ = [t for t in (taux(r, jusqu_a, fenetre) for r in resolutions) if t is not None]
    return round(100 * sum(taux_) / len(taux_)) if taux_ else None


def etoiles(note: int | None) -> str:
    n = 0 if note is None else min(5, max(0, round(note / 20)))
    return "★" * n + "☆" * (5 - n)


def tendance(resolutions: list, jusqu_a: date, fenetre: int = FENETRE) -> int | None:
    """Points de note gagnés ou perdus par rapport à la fenêtre précédente ; None sans les deux notes."""
    a, b = score(resolutions, jusqu_a, fenetre), score(resolutions, jusqu_a - timedelta(days=fenetre), fenetre)
    return None if a is None or b is None else a - b


def encouragement(resolutions: list, jusqu_a: date) -> list:
    """Messages d'encouragement (dans la langue de l'interface) : selon la note, la tendance et la plus belle série en cours."""
    note = score(resolutions, jusqu_a)
    if not resolutions:
        return [_("Ajoutez une première résolution : une petite, que vous pouvez tenir tous les jours.")]
    if note is None:
        return [_("C'est parti ! Cochez votre première résolution : le premier jour est le plus important.")]
    if note >= 90:
        msgs = [_("Excellent ! Vous tenez vos résolutions presque sans faute. Continuez comme ça.")]
    elif note >= 70:
        msgs = [_("Très bien ! Vous êtes sur le bon rythme, il ne manque pas grand-chose.")]
    elif note >= 50:
        msgs = [_("Un bon début : plus de la moitié est tenue. Un petit effort et la série démarre.")]
    elif note >= 25:
        msgs = [_("Ce n'est pas grave : chaque jour est une nouvelle chance. Une petite victoire aujourd'hui relance tout.")]
    else:
        msgs = [_("Recommencez doucement, sans vous juger : cochez une seule résolution aujourd'hui, c'est déjà gagné.")]
    t = tendance(resolutions, jusqu_a)
    if t is not None and t >= 5:
        msgs.append(_("En hausse de %d points sur 14 jours : vos efforts paient.") % t)
    elif t is not None and t <= -5:
        msgs.append(_("En baisse de %d points : un petit effort aujourd'hui et la courbe repart.") % -t)
    meilleure = max(((serie(r, jusqu_a), r) for r in resolutions), key=lambda x: x[0])
    if meilleure[0] >= 3:
        modele = _("Série de %(n)d semaines sur « %(nom)s » : bravo !") if meilleure[1].par_semaine else _("Série de %(n)d jours sur « %(nom)s » : bravo !")
        msgs.append(modele % {"n": meilleure[0], "nom": meilleure[1].nom})
    return msgs


def exemples(aujourdhui: date | None = None) -> list:
    """[(thème, titre, texte)] : un exemple de trois résolutions sur trois semaines (valeurs inventées)."""
    auj = aujourdhui or date.today()
    debut = auj - timedelta(days=20)
    marche = {(debut + timedelta(days=i)).isoformat() for i in range(21) if i % 7 not in (3, 6)}
    lecture = {(debut + timedelta(days=i)).isoformat() for i in range(21) if i % 7 in (0, 2, 5)}
    eau = {(debut + timedelta(days=i)).isoformat() for i in range(21) if i % 5 != 4}
    rs = [Resolution(_("Marcher 30 minutes"), 0, debut.isoformat(), "", marche),
          Resolution(_("Lire 3 fois par semaine"), 3, debut.isoformat(), "", lecture),
          Resolution(_("Boire de l'eau"), 0, debut.isoformat(), "", eau)]
    return [(_("Résolutions (exemples)"), _("Exemple · Mes résolutions"), ecrire(rs))]
