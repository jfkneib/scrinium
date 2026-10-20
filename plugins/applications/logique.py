# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Applications » : applications installées (fichiers .desktop), liste préparée,
construction de la commande (jamais par un shell : les valeurs passées sont des arguments, donc sans injection)."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from scrinium.i18n import N_, _, langue

MAX_APPLICATIONS = 100
EXEMPLES = (
    {"nom": "Thunderbird", "icone": "thunderbird", "commande": "thunderbird", "description": N_("Courrier électronique.")},
    {"nom": "KWrite", "icone": "kwrite", "commande": "kwrite", "description": N_("Éditeur de texte simple.")},
    {"nom": "LibreOffice Writer", "icone": "libreoffice-writer", "commande": "libreoffice --writer",
     "description": N_("Traitement de texte.")},
    {"nom": "Dolphin", "icone": "system-file-manager", "commande": "dolphin", "description": N_("Gestionnaire de fichiers.")},
    {"nom": "Firefox", "icone": "firefox", "commande": "firefox", "description": N_("Navigateur web.")},
)
_VARIABLE = re.compile(r"\{(selection|fiche)\}")
_CODES_EXEC = re.compile(r"%[fFuUdDnNickvm]")


def normaliser(a) -> dict | None:
    """Application valide (champs nettoyés) ou None si elle n'a ni nom ni commande."""
    if not isinstance(a, dict):
        return None
    nom, commande = " ".join(str(a.get("nom", "")).split()), str(a.get("commande", "")).strip()
    if not nom or not commande:
        return None
    return {"nom": nom[:80], "icone": str(a.get("icone", "")).strip()[:300], "commande": commande[:1000],
            "description": " ".join(str(a.get("description", "")).split())[:300]}


def normaliser_liste(liste) -> list:
    if not isinstance(liste, list):
        return []
    return [a for a in (normaliser(x) for x in liste) if a][:MAX_APPLICATIONS]


def premier_mot(commande: str) -> str:
    try:
        return shlex.split(commande)[0]
    except (ValueError, IndexError):
        return ""


def installee(commande: str) -> bool:
    mot = premier_mot(commande)
    return bool(mot) and shutil.which(mot) is not None


def exemples_installes() -> list:
    """Exemples dont le programme est présent sur cette machine."""
    return [dict(a) for a in EXEMPLES if installee(a["commande"])]


def utilise_selection(commande: str) -> bool:
    return "{selection}" in commande


def construire(commande: str, selection: str = "", titre: str = "") -> list:
    """Arguments à lancer : la commande découpée (guillemets respectés), puis {selection} et {fiche} remplacés DANS chaque
    argument. Aucun shell n'intervient : le texte sélectionné ne peut pas ajouter de commande. ValueError si la commande est vide."""
    try:
        argv = shlex.split(commande)
    except ValueError as ex:
        raise ValueError(str(ex)) from ex
    if not argv:
        raise ValueError(_("commande vide"))
    valeurs = {"selection": selection, "fiche": titre}
    return [_VARIABLE.sub(lambda m: valeurs[m[1]], mot) for mot in argv]


def lancer(argv: list) -> None:
    """Démarre le programme, détaché de Scrinium. OSError s'il est introuvable ou ne démarre pas."""
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0)}
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)


# ---------- applications installées (Linux : fichiers .desktop) ----------
def dossiers_desktop() -> list:
    base = [Path(p) / "applications" for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    perso = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    extra = [perso / "applications", Path("/var/lib/flatpak/exports/share/applications"),
             perso / "flatpak" / "exports" / "share" / "applications", Path("/var/lib/snapd/desktop/applications")]
    vus, res = set(), []
    for d in extra + base:
        if d not in vus and d.is_dir():
            vus.add(d)
            res.append(d)
    return res


def lire_desktop(chemin: Path, lang: str = "") -> dict | None:
    """Application décrite par un fichier .desktop, ou None (caché, pas une application, sans commande)."""
    try:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    entree, champs = False, {}
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("["):
            entree = ligne == "[Desktop Entry]"
        elif entree and "=" in ligne and not ligne.startswith("#"):
            cle, _sep, val = ligne.partition("=")
            champs[cle.strip()] = val.strip()
    if champs.get("Type") != "Application" or champs.get("NoDisplay", "").lower() == "true" \
            or champs.get("Hidden", "").lower() == "true":
        return None
    nom = (champs.get(f"Name[{lang}]") if lang else None) or champs.get("Name", "")
    commande = _CODES_EXEC.sub("", champs.get("Exec", "")).replace("%%", "%")
    commande = " ".join(commande.split())
    if not nom or not commande:
        return None
    return normaliser({"nom": nom, "icone": champs.get("Icon", ""), "commande": commande,
                       "description": (champs.get(f"Comment[{lang}]") if lang else None) or champs.get("Comment", "")})


def applications_installees() -> list:
    """Applications des menus du système, triées par nom, sans doublon de commande."""
    if not sys.platform.startswith("linux"):
        return []
    lang, vues, res = langue() or "", set(), []
    for d in dossiers_desktop():
        for f in sorted(d.glob("*.desktop")):
            a = lire_desktop(f, lang)
            if a and a["commande"] not in vues:
                vues.add(a["commande"])
                res.append(a)
    return sorted(res, key=lambda a: a["nom"].lower())


def exporter(applications: list) -> str:
    return json.dumps({"scrinium_applications": 1, "applications": normaliser_liste(applications)}, ensure_ascii=False, indent=2)


def importer(texte: str) -> list:
    """Applications lues dans un fichier d'export. ValueError si ce n'en est pas un."""
    try:
        d = json.loads(texte)
    except ValueError as ex:
        raise ValueError(_("fichier illisible")) from ex
    if not isinstance(d, dict) or d.get("scrinium_applications") != 1 or not isinstance(d.get("applications"), list):
        raise ValueError(_("ce n'est pas un export d'applications de Scrinium"))
    return normaliser_liste(d["applications"])
