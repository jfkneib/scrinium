# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export et import d'un THÈME entier en archive zip.

Contenu de l'archive (lisible sans Scrinium : dézippez, ce sont des fichiers Markdown et des images) :
    scrinium-theme.json      nom, icône et ordre des fiches (facultatif à la lecture)
    <Thème>/<Fiche>.md       une fiche en clair, comme l'export d'une fiche (voir echange_md)
    <Thème>/<Fiche>_images/  ses images
    <Thème>/<Fiche>.lock     une fiche VERROUILLÉE, copiée telle quelle (toujours chiffrée) ; ses pièces dans <Fiche>.pj/*.lock
Choix (voir l'issue n° 4) : un seul fichier ; les fiches verrouillées ne sortent jamais en clair ; l'import crée TOUJOURS un nouveau
thème (jamais de fusion ni d'écrasement) ; rien d'exécutable n'est validé ; l'archive est relue avec des limites strictes."""
import json
import re
import tempfile
import zipfile
from pathlib import Path

from . import echange_md
from .store import Fiche, Store, Theme, propre

FORMAT = "scrinium-theme"
MANIFESTE = "scrinium-theme.json"
ENTREES_MAX = 5000
TOTAL_MAX = 300 * 1024 * 1024
FICHIER_MAX = 25 * 1024 * 1024


def exporter(store: Store, th: Theme, chemin: Path) -> dict:
    """Écrit l'archive `chemin` (.zip). Retourne {"fiches", "verrouillees", "images"}. Les fiches verrouillées (ouvertes ou non) sont
    copiées chiffrées ; il faut avoir enregistré les modifications en cours avant l'appel."""
    chemin = Path(chemin)
    racine = propre(th.nom, "theme")
    rapport = {"fiches": 0, "verrouillees": 0, "images": 0}
    ordre = []
    tmp = chemin.with_name(chemin.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in store.fiches_triees(th):
                stem = f.path.stem
                if f.verrou:
                    z.writestr(f"{racine}/{f.path.name}", f.path.read_bytes())
                    pj = store.dossier_pj(f)
                    if pj.is_dir():
                        for p in sorted(pj.glob("*.lock")):
                            z.writestr(f"{racine}/{pj.name}/{p.name}", p.read_bytes())
                    rapport["verrouillees"] += 1
                else:
                    liste = []
                    for i, piece in enumerate(store.lister_pieces(f), 1):
                        ext = ".jpg" if piece.type == "image/jpeg" else ".png"
                        nom = f"{i:02d}-{propre(Path(piece.nom).stem, 'image')}{ext}"
                        z.writestr(f"{racine}/{stem}_images/{nom}", store.lire_piece(f, piece))
                        liste.append((f"{stem}_images/{nom}", piece.nom))
                        rapport["images"] += 1
                    z.writestr(f"{racine}/{stem}.md", echange_md.texte_exporte(f.titre, f.texte or "", liste))
                    rapport["fiches"] += 1
                ordre.append(f.path.name)
            z.writestr(MANIFESTE, json.dumps({"format": FORMAT, "version": 1, "theme": th.nom, "icone": th.icone, "ordre": ordre},
                                             ensure_ascii=False, indent=1))
        tmp.replace(chemin)
    finally:
        tmp.unlink(missing_ok=True)
    return rapport


def _nom_sur(nom: str) -> str | None:
    """Nom d'un élément de l'archive, ou None s'il est dangereux (chemin absolu, « .. », lecteur Windows…)."""
    n = nom.replace("\\", "/")
    if n.startswith("/") or re.match(r"[A-Za-z]:", n) or any(x in ("..", "") for x in n.rstrip("/").split("/")) or "\x00" in n:
        return None
    return n


def importer(store: Store, chemin: Path, preparer) -> tuple[Theme, dict]:
    """Crée un NOUVEAU thème à partir de l'archive. `preparer` : voir echange_md.importer. Retourne (thème, rapport) avec
    {"fiches", "verrouillees", "images", "ignores": [raison]}. ValueError si l'archive est illisible ou démesurée."""
    try:
        z = zipfile.ZipFile(chemin)
    except (zipfile.BadZipFile, OSError) as ex:
        raise ValueError(f"archive illisible : {ex}")
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > ENTREES_MAX or sum(i.file_size for i in infos) > TOTAL_MAX:
            raise ValueError("archive démesurée")
        manifeste = {}
        if MANIFESTE in z.namelist():
            try:
                brut = json.loads(z.read(MANIFESTE)[:200_000].decode("utf-8"))
                manifeste = brut if isinstance(brut, dict) and brut.get("format") == FORMAT else {}
            except (ValueError, UnicodeDecodeError):
                manifeste = {}
        ignores, mds, images, locks, pj, racines = [], {}, {}, {}, {}, set()
        for i in infos:
            n = _nom_sur(i.filename)
            if n is None:
                ignores.append(f"{i.filename} : nom refusé")
                continue
            if n == MANIFESTE or i.file_size > FICHIER_MAX:
                if n != MANIFESTE:
                    ignores.append(f"{n} : trop gros")
                continue
            parts = n.split("/")
            if len(parts) >= 2:
                racines.add(parts[0])
            rel = parts[1:] if len(parts) >= 2 else parts           # on retire le dossier racine (nom du thème)
            if len(rel) == 1 and rel[0].lower().endswith(".md"):
                mds[rel[0]] = i
            elif len(rel) == 1 and rel[0].endswith(".lock"):
                locks[rel[0]] = i
            elif len(rel) == 2 and rel[0].endswith("_images") and Path(rel[1]).suffix.lower() in echange_md.SUFFIXES_IMAGE:
                images.setdefault(rel[0], {})[rel[1]] = i
            elif len(rel) == 2 and rel[0].endswith(".pj") and re.fullmatch(r"\d+\.lock", rel[1]):
                pj.setdefault(rel[0], {})[rel[1]] = i
            else:
                ignores.append(f"{n} : élément non reconnu")
        racine = next(iter(racines)) if len(racines) == 1 else Path(chemin).stem
        nom = propre(str(manifeste.get("theme") or racine), "thème")
        base, k = nom, 2
        while store.theme(nom) is not None or (store.paths.fiches / nom).exists():
            nom = f"{base} ({k})"
            k += 1
        th = store.nouveau_theme(nom)
        icone = manifeste.get("icone")
        if isinstance(icone, str) and re.fullmatch(r"[\w.-]{1,60}", icone):
            store.icone_theme(th, icone)
        rapport = {"fiches": 0, "verrouillees": 0, "images": 0, "ignores": ignores}
        cree = {}                                                     # nom de fichier d'origine -> fiche créée
        with tempfile.TemporaryDirectory(prefix="scrinium-import-") as tmp:
            tmp = Path(tmp)
            for fichier, info in sorted(mds.items()):
                (tmp / fichier).write_bytes(z.read(info))
                for nom_img, ii in images.get(fichier[:-3] + "_images", {}).items():
                    d = tmp / (fichier[:-3] + "_images")
                    d.mkdir(exist_ok=True)
                    (d / nom_img).write_bytes(z.read(ii))
                try:
                    f, n, ign = echange_md.importer(store, th, tmp / fichier, preparer)
                except (OSError, ValueError) as ex:
                    ignores.append(f"{fichier} : {ex}")
                    continue
                cree[fichier] = f
                rapport["fiches"] += 1
                rapport["images"] += n
                ignores += [f"{fichier} → {x}" for x in ign]
        for fichier, info in sorted(locks.items()):
            try:
                pieces = {k2: z.read(v) for k2, v in pj.get(fichier[:-5] + ".pj", {}).items()}
                cree[fichier] = store.ajouter_fiche_verrouillee(th, fichier[:-5], z.read(info), pieces)
                rapport["verrouillees"] += 1
            except (OSError, ValueError) as ex:
                ignores.append(f"{fichier} : {ex}")
        ordre = manifeste.get("ordre")
        if isinstance(ordre, list) and cree:
            voulus = [cree[x].path.name for x in ordre if isinstance(x, str) and x in cree]
            if voulus:
                store.ordonner_fiches(th, voulus)
        return th, rapport
