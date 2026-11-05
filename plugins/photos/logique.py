# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) du type de fiche « photos » (`#scrinium-photos`) : une fiche garde le CHEMIN d'un dossier d'images.

    #scrinium-photos
    dossier: ~/Images/vacances

    Notes libres : tout ce qui n'est pas la ligne « dossier: » est conservé tel quel.

Type NON exécutable : la fiche ne lance rien, elle ne fait que lister les images d'un dossier (par extension) pour les montrer en vignettes.
Les images ne sont pas copiées dans la fiche. Le chemin n'a de sens que sur la machine où le dossier existe : sur une autre machine (fiche
partagée ou synchronisée), la vue dit « dossier introuvable » et propose d'en choisir un. Le début du chemin égal au dossier personnel
est écrit `~`, pour que la fiche suive d'un ordinateur à l'autre quand l'arborescence est la même."""
import re
from pathlib import Path

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_

MARQUE = "#scrinium-photos"
TYPE = TypeFiche("photos", N_("Photos"), "folder-pictures")
SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MAX_IMAGES = 3000                                  # au-delà, la vue le dit et n'en montre pas plus
_LIGNE = re.compile(r"^dossier[ \t]*:[ \t]*(.*?)[ \t]*$", re.IGNORECASE)


def depuis_texte(texte: str | None) -> str:
    """Le chemin écrit dans la fiche (tel quel, avec son éventuel `~`) ; chaîne vide s'il n'y en a pas."""
    for ligne in (texte or "").replace("\r\n", "\n").split("\n")[1:]:
        m = _LIGNE.match(ligne)
        if m:
            return m.group(1)
    return ""


def en_texte(chemin: str, ancien: str | None = None) -> str:
    """Texte de la fiche pour ce dossier. Avec `ancien` (le texte actuel), seule la ligne « dossier: » change : les notes sont gardées."""
    chemin = raccourcir(chemin) if chemin else ""
    lignes = (ancien or "").replace("\r\n", "\n").split("\n")
    if not lignes or not lignes[0].startswith(MARQUE):
        lignes = [MARQUE, ""]
    reste, vu = [lignes[0]], False
    for ligne in lignes[1:]:
        if _LIGNE.match(ligne):
            if not vu:
                reste.append("dossier: " + chemin)
                vu = True
            continue
        reste.append(ligne)
    if not vu:
        reste.insert(1, "dossier: " + chemin)
    return "\n".join(reste).rstrip("\n") + "\n"


def raccourcir(chemin: str) -> str:
    """`/home/moi/Images` -> `~/Images` (le dossier personnel de cette machine)."""
    p = Path(chemin).expanduser()
    try:
        return "~/" + p.relative_to(Path.home()).as_posix() if p != Path.home() else "~"
    except ValueError:
        return str(p)


def dossier(chemin: str) -> Path | None:
    """Le dossier désigné (`~` développé), ou None s'il est vide, absent ou n'est pas un dossier."""
    if not chemin.strip():
        return None
    p = Path(chemin.strip()).expanduser()
    return p if p.is_dir() else None


def _cle_naturelle(p: Path) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def images(d: Path, maximum: int = MAX_IMAGES) -> tuple:
    """([images du dossier, triées par nom « naturel » (img2 avant img10)], nombre total). Sans descendre dans les sous-dossiers."""
    try:
        toutes = sorted((p for p in d.iterdir() if p.suffix.lower() in SUFFIXES and p.is_file()), key=_cle_naturelle)
    except OSError:
        return [], 0
    return toutes[:maximum], len(toutes)
