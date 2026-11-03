# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Agenda et rappels » : événements, échéances, rappels à notifier.

Un événement : {"id", "titre", "quand" ("AAAA-MM-JJ HH:MM", heure locale), "fiche" ({"theme", "titre"} ou None), "notifie" (bool),
"fait" (bool), "son" (bool), "repete" ("", "jour", "semaine", "mois" ou "annee"), "ancre" (date de départ de la série ; "quand" est
alors la prochaine occurrence)}.

« Tout est fiche » : les événements sont décrits dans des fiches `#scrinium-agenda` (type NON exécutable : rien n'y lance de commande) :

    #scrinium-agenda

    ## Appeler le notaire
    id: 3f9a1c0b7d2e
    quand: 2026-10-21 09:00
    repete: semaine            (facultatif : jour, semaine, mois, annee ; « quand » est alors la date de départ)
    son: non                   (facultatif)
    fait: oui                  (facultatif, événement unique)
    fiche-theme: Perso         (facultatif : fiche liée, jamais une fiche verrouillée)
    fiche-titre: Dossier notaire

La fiche ne porte que la DÉFINITION. L'état « déjà annoncé » et la prochaine occurrence d'une série restent propres à chaque machine
(réglages de l'extension, clé « etat ») : une fiche synchronisée n'est pas réécrite à chaque alerte, et chaque PC annonce pour lui.
Le champ `id` rend la fusion événement par événement possible quand deux machines modifient la fiche."""
import os
import shutil
import subprocess
import sys
import calendar
import hashlib
import uuid
from datetime import datetime, timedelta

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_

FORMAT = "%Y-%m-%d %H:%M"
REPETITIONS = {"": N_("Jamais"), "jour": N_("Chaque jour"), "semaine": N_("Chaque semaine"), "mois": N_("Chaque mois"),
               "annee": N_("Chaque année")}
MAX_EVENEMENTS = 2000
MARQUE = "#scrinium-agenda"
TYPE = TypeFiche("agenda", N_("Agenda"), "view-calendar")
_CLES = ("id", "quand", "repete", "son", "fait", "fiche-theme", "fiche-titre")


def en_date(texte: str) -> datetime | None:
    try:
        return datetime.strptime(str(texte), FORMAT)
    except ValueError:
        return None


def en_texte(d: datetime) -> str:
    return d.strftime(FORMAT)


def normaliser(e) -> dict | None:
    """Événement valide (champs nettoyés) ou None s'il n'a ni titre ni date lisible."""
    if not isinstance(e, dict):
        return None
    titre = " ".join(str(e.get("titre", "")).split())
    quand = en_date(e.get("quand", ""))
    if not titre or quand is None:
        return None
    fiche = e.get("fiche")
    if isinstance(fiche, dict) and fiche.get("theme") and fiche.get("titre"):
        fiche = {"theme": str(fiche["theme"]), "titre": str(fiche["titre"])}
    else:
        fiche = None
    repete = e.get("repete") if e.get("repete") in REPETITIONS else ""
    ancre = en_date(e.get("ancre", "")) or quand
    return {"id": str(e.get("id") or uuid.uuid4().hex[:12]), "titre": titre[:200], "quand": en_texte(quand), "fiche": fiche,
            "notifie": bool(e.get("notifie")), "fait": bool(e.get("fait")), "son": e.get("son", True) is not False,
            "repete": repete, "ancre": en_texte(ancre if repete else quand)}


def definition(e: dict) -> dict:
    """La définition d'un événement (ce qui va dans la fiche) : « quand » est la date de départ, sans état d'annonce."""
    depart = e["ancre"] if e.get("repete") else e["quand"]
    return dict(e, quand=depart, ancre=depart, notifie=False)


def _non(valeur) -> bool:
    return str(valeur).lower() in ("non", "no", "false", "0")


def fiche_depuis_texte(texte: str | None) -> list:
    """Définitions lues dans le texte d'une fiche « agenda » (valides seulement ; un événement sans id en reçoit un, stable)."""
    bruts, courant = [], None
    lignes = (texte or "").lstrip("\ufeff").splitlines()
    for ligne in lignes[1:] if lignes and lignes[0].startswith(MARQUE) else lignes:
        if ligne.startswith("## "):
            courant = {"titre": ligne[3:]}
            bruts.append(courant)
        elif courant is not None and ":" in ligne:
            cle, _sep, valeur = ligne.partition(":")
            if cle.strip().lower() in _CLES:
                courant[cle.strip().lower()] = valeur.strip()
    res = []
    for b in bruts:
        ident = b.get("id") or hashlib.sha1(f"{b.get('titre')}|{b.get('quand')}".encode()).hexdigest()[:12]
        e = normaliser({"id": ident, "titre": b["titre"], "quand": b.get("quand", ""), "ancre": b.get("quand", ""),
                        "repete": b.get("repete", ""), "son": not _non(b.get("son", "oui")),
                        "fait": str(b.get("fait", "")).lower() in ("oui", "yes", "true", "1"),
                        "fiche": {"theme": b.get("fiche-theme"), "titre": b.get("fiche-titre")}})
        if e is not None:
            res.append(e)
    return res


def fiche_en_texte(definitions: list) -> str:
    """Texte d'une fiche « agenda » pour ces définitions."""
    sortie = [MARQUE]
    for e in sorted((x for x in map(normaliser, definitions) if x), key=lambda x: x["ancre"]):
        sortie += ["", "## " + e["titre"], "id: " + e["id"], "quand: " + e["ancre"]]
        if e["repete"]:
            sortie.append("repete: " + e["repete"])
        if not e["son"]:
            sortie.append("son: non")
        if e["fait"] and not e["repete"]:
            sortie.append("fait: oui")
        if e["fiche"]:
            sortie += ["fiche-theme: " + e["fiche"]["theme"], "fiche-titre: " + e["fiche"]["titre"]]
    return "\n".join(sortie) + "\n"


def signature(d: dict) -> str:
    """Ce qui, dans la définition, remet l'état d'annonce à zéro quand l'utilisateur le change (date de départ, répétition, fait)."""
    return f"{d['ancre']}|{d['repete']}|{int(d['fait'])}"


def evenements_depuis(definitions: list, etat, maintenant: datetime, premier: bool = False) -> list:
    """Événements (définition + état de CETTE machine), triés par date. Sans état connu : une série passée reçoit sa prochaine occurrence
    sans alerte ; `premier` (aucun état encore sur cette machine) tient pour déjà annoncés les événements uniques passés, pour ne pas
    rejouer tout l'historique d'une fiche reçue."""
    vus, res = set(), []
    for d in definitions:
        if d["id"] in vus:
            continue
        vus.add(d["id"])
        e = dict(d)
        st = etat.get(d["id"]) if isinstance(etat, dict) else None
        if isinstance(st, dict) and st.get("sig") == signature(d) and en_date(st.get("quand", "")):
            e["quand"], e["notifie"] = st["quand"], bool(st.get("notifie"))
        else:
            depart = en_date(d["ancre"])
            if d["repete"] and depart <= maintenant:
                e["quand"] = en_texte(prochaine(depart, d["repete"], maintenant))
            e["notifie"] = bool(premier and not d["repete"] and depart <= maintenant)
        res.append(e)
    return sorted(res, key=lambda x: x["quand"])[:MAX_EVENEMENTS]


def etat_de(evenements: list) -> dict:
    """L'état à garder sur cette machine : {id: {sig, quand, notifie}}."""
    return {e["id"]: {"sig": signature(definition(e)), "quand": e["quand"], "notifie": e["notifie"]} for e in evenements}


def charger(brut) -> list:
    """Liste d'événements valides, triés par date, sans doublon d'identifiant."""
    vus, res = set(), []
    for e in brut if isinstance(brut, list) else []:
        n = normaliser(e)
        if n and n["id"] not in vus:
            vus.add(n["id"])
            res.append(n)
    return sorted(res, key=lambda x: x["quand"])[:MAX_EVENEMENTS]


def occurrence(ancre: datetime, repete: str, n: int) -> datetime:
    """n-ième occurrence (n = 0 : la date de départ). Fin de mois : le 31 devient le 30, le 28 ou le 29 ; le 29 février, le 28."""
    if repete == "jour":
        return ancre + timedelta(days=n)
    if repete == "semaine":
        return ancre + timedelta(weeks=n)
    if repete in ("mois", "annee"):
        mois = ancre.month - 1 + n * (12 if repete == "annee" else 1)
        annee, mois = ancre.year + mois // 12, mois % 12 + 1
        return ancre.replace(year=annee, month=mois, day=min(ancre.day, calendar.monthrange(annee, mois)[1]))
    return ancre


def prochaine(ancre: datetime, repete: str, apres: datetime) -> datetime:
    """Première occurrence STRICTEMENT après `apres` (une série manquée longtemps ne produit qu'une seule alerte)."""
    if repete not in ("jour", "semaine", "mois", "annee"):
        return ancre
    if apres < ancre:
        return ancre
    if repete in ("jour", "semaine"):
        pas = timedelta(days=1 if repete == "jour" else 7)
        n = max(0, int((apres - ancre) / pas) - 1)
    else:
        mois = (apres.year - ancre.year) * 12 + apres.month - ancre.month
        n = max(0, mois // (12 if repete == "annee" else 1) - 1)
    while occurrence(ancre, repete, n) <= apres:
        n += 1
    return occurrence(ancre, repete, n)


def ajouter(evenements: list, titre: str, quand: datetime, fiche: dict | None = None, id_: str | None = None,
            son: bool = True, repete: str = "", maintenant: datetime | None = None) -> dict:
    """Ajoute un événement (ValueError si le titre est vide ou la liste pleine) ; renvoie l'événement créé.
    Une série dont la date de départ est passée (anniversaire…) reçoit tout de suite sa prochaine occurrence, sans alerte."""
    if len(evenements) >= MAX_EVENEMENTS:
        raise ValueError("trop d'événements")
    n = normaliser({"titre": titre, "quand": en_texte(quand), "fiche": fiche, "id": id_, "son": son, "repete": repete,
                    "ancre": en_texte(quand)})
    if n is None:
        raise ValueError("titre vide")
    if n["repete"] and quand <= (maintenant or datetime.now()):
        n["quand"] = en_texte(prochaine(quand, n["repete"], maintenant or datetime.now()))
    evenements.append(n)
    evenements.sort(key=lambda x: x["quand"])
    return n


def a_notifier(evenements: list, maintenant: datetime) -> list:
    """Événements dont l'heure est venue et qui n'ont pas encore été annoncés."""
    return [e for e in evenements if not e["notifie"] and not e["fait"] and en_date(e["quand"]) <= maintenant]


def avancer(e: dict, maintenant: datetime) -> None:
    """Après l'alerte d'une série : la prochaine occurrence devient l'échéance de l'événement (qui n'est plus « notifié »)."""
    d = prochaine(en_date(e["ancre"]) or en_date(e["quand"]), e["repete"], maintenant)
    e["quand"], e["notifie"], e["fait"] = en_texte(d), False, False


def a_venir(evenements: list, maintenant: datetime) -> list:
    return [e for e in evenements if not e["fait"] and en_date(e["quand"]) > maintenant]


def repousser(e: dict, minutes: int, maintenant: datetime) -> None:
    """Nouvelle échéance `minutes` après maintenant ; l'événement sera annoncé de nouveau."""
    e["quand"] = en_texte((maintenant + timedelta(minutes=minutes)).replace(second=0, microsecond=0))
    e["notifie"] = e["fait"] = False


def commande_son() -> list | None:
    """Commande qui joue un son d'alerte sur ce système, ou None (l'interface retombe alors sur le bip de Qt)."""
    if sys.platform.startswith("linux"):
        for fichier in ("/usr/share/sounds/freedesktop/stereo/message.oga", "/usr/share/sounds/freedesktop/stereo/bell.oga"):
            for lecteur in ("paplay", "pw-play"):
                if shutil.which(lecteur) and os.path.exists(fichier):
                    return [lecteur, fichier]
        if shutil.which("canberra-gtk-play"):
            return ["canberra-gtk-play", "-i", "message"]
    return None


def jouer_son() -> bool:
    """Joue le son d'alerte sans attendre ; False si aucun lecteur n'est disponible."""
    cmd = commande_son()
    if cmd is None:
        return False
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def delai_texte(quand: datetime, maintenant: datetime) -> str:
    """« dans 3 h », « demain 09:00 », « il y a 2 j »… (court, pour une liste)."""
    from scrinium.i18n import _
    ecart = quand - maintenant
    if ecart < timedelta(0):
        retard = -ecart
        if retard < timedelta(hours=1):
            return _("en retard de %d min") % max(1, retard.seconds // 60)
        if retard < timedelta(days=1):
            return _("en retard de %d h") % (retard.seconds // 3600)
        return _("en retard de %d j") % retard.days
    if ecart < timedelta(hours=1):
        return _("dans %d min") % max(1, ecart.seconds // 60)
    if ecart < timedelta(days=1):
        return _("dans %d h") % (ecart.seconds // 3600)
    return _("dans %d j") % ecart.days
