# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export et import d'UNE fiche en fichier Markdown (.md), avec ses images.

Export : `Titre.md` (« # Titre », puis le texte) ; les images jointes vont dans `Titre_images/` à côté, et sont rappelées à la fin
du fichier sous « ## Images ». Une fiche typée (tableau, Veille…) est exportée telle quelle, marqueur compris.
Import : un fichier .md devient une NOUVELLE fiche (le premier « # titre » en est le titre) ; les images locales qu'il cite
(dans son dossier, PNG/JPEG/WebP…) sont jointes à la fiche. Rien n'est jamais validé : une fiche d'un type exécutable importée
reste inerte jusqu'à ce que l'utilisateur la valide."""
import re
from pathlib import Path
from urllib.parse import quote, unquote

from . import types_fiche
from .store import TYPE_PIECE, Fiche, Store, Theme, propre

TAILLE_MAX = 5 * 1024 * 1024                         # un fichier .md plus gros n'est pas une fiche
IMAGE_MAX = 20 * 1024 * 1024
IMAGES_MAX = 50
SUFFIXES_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_TITRE = re.compile(r"\A\s*#[ \t]+(.+?)[ \t]*\n")


def texte_simple(texte: str) -> str:
    """Texte d'une fiche pour un AUTRE outil que Scrinium : le rendu Markdown du type s'il en a un (un tableur ou un répertoire
    devient des tableaux Markdown), sinon le texte sans sa marque de type (`#scrinium-…`). Un texte libre reste tel quel."""
    if types_fiche.type_de(texte) is None:
        return texte
    rendu = types_fiche.en_markdown(texte)
    if rendu != texte:
        return rendu
    premiere, _sep, reste = texte.partition("\n")
    return reste.lstrip("\n") if types_fiche.marque(premiere) else texte


def texte_exporte(titre: str, texte: str, images: list) -> str:
    """Contenu du .md. `images` : [(nom du fichier image, texte alternatif)] dans le dossier d'images (déjà écrit)."""
    out = f"# {titre}\n\n{texte.rstrip()}\n"
    if images:
        out += "\n## Images\n\n" + "\n\n".join(f"![{alt.replace('[', '(').replace(']', ')')}]({quote(nom, safe='/')})"
                                                  for nom, alt in images) + "\n"
    return out


def exporter(store: Store, f: Fiche, chemin: Path, titre: str, texte: str, simple: bool = False) -> int:
    """Écrit la fiche (`titre`, `texte` : ce qui est à l'écran) dans `chemin` (.md) ; ses images dans « <nom>_images/ » à côté.
    `simple` : Markdown pour un autre outil (voir `texte_simple`). Retourne le nombre d'images. ValueError si la fiche est fermée (verrouillée, mot de passe non saisi)."""
    if f.fermee:
        raise ValueError("fiche verrouillée : déverrouillez-la d'abord")
    chemin = Path(chemin)
    pieces = store.lister_pieces(f)
    liste = []
    if pieces:
        dossier = chemin.with_name(chemin.stem + "_images")
        k = 2
        while dossier.exists():
            dossier = chemin.with_name(f"{chemin.stem}_images ({k})")
            k += 1
        dossier.mkdir(parents=True)
        for i, p in enumerate(pieces, 1):
            ext = ".jpg" if p.type == "image/jpeg" else ".png"
            base = propre(Path(p.nom).stem, "image")
            nom = f"{i:02d}-{base}{ext}"
            (dossier / nom).write_bytes(store.lire_piece(f, p))
            liste.append((f"{dossier.name}/{nom}", p.nom))
    chemin.write_text(texte_exporte(titre, texte_simple(texte) if simple else texte, liste), encoding="utf-8")
    return len(liste)


def _separer_titre(contenu: str, defaut: str) -> tuple[str, str]:
    contenu = contenu.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    m = _TITRE.match(contenu)
    if m:
        return m.group(1).strip() or defaut, contenu[m.end():].lstrip("\n")
    return defaut, contenu


def analyser(contenu: str, defaut: str) -> tuple[str, str, list]:
    """(titre, texte, références d'images locales) d'un fichier Markdown. Les lignes réduites à une image sont retirées du texte
    (l'image sera jointe à la fiche) ; une section « ## Images » devenue vide disparaît. Les liens http(s) sont laissés."""
    titre, corps = _separer_titre(contenu, defaut)
    refs, lignes = [], []
    for ligne in corps.split("\n"):
        ms = list(_IMAGE.finditer(ligne))
        locales = [m for m in ms if "://" not in m.group(2) and not m.group(2).startswith(("data:", "/", "#"))]
        if locales and not _IMAGE.sub("", ligne).strip():
            refs += [(m.group(1), unquote(m.group(2))) for m in locales]
            continue
        lignes.append(ligne)
    texte = "\n".join(lignes)
    texte = re.sub(r"\n+## Images[ \t]*\n*\Z", "\n", texte)
    return titre, texte.strip("\n") + "\n" if texte.strip() else "", refs


def importer(store: Store, th: Theme, chemin: Path, preparer) -> tuple[Fiche, int, list]:
    """Crée une fiche dans `th` à partir du .md `chemin`. `preparer(chemin_image) -> (type MIME, octets)` réencode une image
    (voir ui/images.preparer). Retourne (fiche, nombre d'images jointes, [images ignorées : raison]).
    ValueError si le fichier n'est pas un texte raisonnable."""
    chemin = Path(chemin)
    if chemin.stat().st_size > TAILLE_MAX:
        raise ValueError("fichier trop gros (plus de 5 Mo)")
    brut = chemin.read_bytes()
    if b"\x00" in brut:
        raise ValueError("ce n'est pas un fichier texte")
    try:
        contenu = brut.decode("utf-8")
    except UnicodeDecodeError:
        contenu = brut.decode("latin-1")
    titre, texte, refs = analyser(contenu, chemin.stem)
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, titre, texte)                   # jamais validée : une fiche exécutable reste inerte
    base = chemin.resolve().parent
    jointes, ignorees = 0, []
    for alt, rel in refs[:IMAGES_MAX]:
        try:
            src = (base / rel).resolve()
            src.relative_to(base)                             # reste dans le dossier du fichier (pas de « ../ »)
            if src.suffix.lower() not in SUFFIXES_IMAGE or not src.is_file() or src.stat().st_size > IMAGE_MAX:
                raise ValueError("introuvable ou non pris en charge")
            type_, donnees = preparer(src)
            if type_ not in TYPE_PIECE.values():
                raise ValueError("format non pris en charge")
            store.ajouter_piece(f, alt or src.name, type_, donnees)
            jointes += 1
        except Exception as ex:        # une image qui ne passe pas ne bloque pas la fiche
            ignorees.append(f"{rel} : {ex}")
    for rel in refs[IMAGES_MAX:]:
        ignorees.append(f"{rel[1]} : trop d'images")
    return f, jointes, ignorees
