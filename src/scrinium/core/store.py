# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Stockage des fiches : un dossier par thème, un fichier par fiche.

  <base>/fiches/<Thème>/<titre>.md    ligne `# titre`, puis le texte
  <base>/fiches/<Thème>/<titre>.lock  fiche verrouillée (voir crypto.py)
  <base>/corbeille/                   suppression = déplacement ici
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import crypto, exemples
from ..i18n import _
from .paths import Paths

ICONE_DEFAUT = "view-pim-notes"
POSIX = os.name == "posix"

# Pièces jointes (docs/format-pieces-jointes.md)
EXT_PIECE = {"image/png": ".png", "image/jpeg": ".jpg"}
TYPE_PIECE = {v: k for k, v in EXT_PIECE.items()}
LIMITES_PIECES = {"nombre": 50, "octets_piece": 8 * 1024 * 1024, "octets_total": 100 * 1024 * 1024}
_NOM_PIECE = re.compile(r"(\d+)\.(png|jpg|lock)\Z")


_META = re.compile(r"\A<!-- scrinium: (\{.*?\}) -->\n?", re.S)


def separer_meta(brut: str):
    """(texte, meta) : une ligne `<!-- scrinium: {...} -->` en tête du texte porte les métadonnées de la fiche
    (invisibles dans un rendu Markdown, chiffrées avec le texte d'une fiche verrouillée)."""
    m = _META.match(brut)
    if not m:
        return brut, {}
    try:
        meta = json.loads(m.group(1))
        if isinstance(meta, dict):
            return brut[m.end():], {str(k): str(v) for k, v in meta.items()}
    except ValueError:
        pass
    return brut, {}


def joindre_meta(meta: dict, texte: str) -> str:
    if not meta:
        return texte
    corps = json.dumps(meta, ensure_ascii=False, sort_keys=True).replace("-->", "--\\u003e")
    return f"<!-- scrinium: {corps} -->\n{texte}"


def propre(nom: str, defaut: str = "sans titre") -> str:
    """Nom utilisable comme fichier ou dossier."""
    n = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", nom).strip().lstrip(".").strip()
    return n[:100].strip() or defaut


def _chmod(p: Path, mode: int) -> None:
    if POSIX:
        os.chmod(p, mode)


def mkdir_prive(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    _chmod(p, 0o700)


def _ecrire(p: Path, data: bytes) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    _chmod(tmp, 0o600)
    os.replace(tmp, p)


@dataclass
class Piece:
    id: int
    nom: str
    type: str
    taille: int
    chemin: Path
    ajoute: str = ""
    ocr: str = ""
    ocr_moteur: str = ""


class Fiche:
    def __init__(self, path: Path, titre: str, texte: str | None, verrou: bool = False):
        self.path, self.titre, self.texte, self.verrou = path, titre, texte, verrou
        self.cle = self.salt = None
        self.wrap = b""
        self.meta: dict = {}
        self.ocr_cache = None    # (signature des fichiers, texte OCR) : voir Store.texte_ocr
        self.maj = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)) if path.exists() \
            else time.strftime("%Y-%m-%d %H:%M")

    @property
    def fermee(self) -> bool:
        """Fiche verrouillée dont le mot de passe n'a pas encore été donné."""
        return self.verrou and self.texte is None


class Theme:
    def __init__(self, path: Path, icone: str = ICONE_DEFAUT):
        self.path, self.icone = path, icone
        self.fiches: list[Fiche] = []

    @property
    def nom(self) -> str:
        return self.path.name


class Store:
    def __init__(self, paths: Paths | None = None):
        self.paths = paths or Paths()
        self.themes: list[Theme] = []
        self.premier_lancement = False

    # ---------- lecture ----------
    def charger(self) -> list[Theme]:
        fiches = self.paths.fiches
        premier = not fiches.exists()
        mkdir_prive(fiches)
        if premier:
            self.premier_lancement = True
            self._exemples()
        self.themes = []
        for d in sorted((d for d in fiches.iterdir() if d.is_dir() and not d.name.startswith(".")),
                        key=lambda d: d.name.lower()):
            self._reparer_pj(d)
            th = Theme(d)
            fi = d / ".icone"
            if fi.exists():
                th.icone = fi.read_text(encoding="utf-8").strip() or ICONE_DEFAUT
            for p in sorted(list(d.glob("*.md")) + list(d.glob("*.lock")), key=lambda p: p.name.lower()):
                th.fiches.append(self._lire(p))
            self.themes.append(th)
        return self.themes

    def _exemples(self) -> None:
        """Premier lancement : thèmes et fiches modèles, dont une fiche verrouillée de démonstration."""
        for nom, icone, fiches in exemples.themes(self.paths.fiches):
            d = self.paths.fiches / propre(nom, "thème")
            mkdir_prive(d)
            _ecrire(d / ".icone", (icone + "\n").encode("utf-8"))
            for titre, texte in fiches:
                self._ecrire_md(self.libre(d, titre), titre, texte)
        demo = self.paths.fiches / propre(_("Bienvenue"), "thème")
        titre = _("Exemple verrouillé")
        f = Fiche(self.libre(demo, titre), titre, _(
            "Bravo, vous avez déverrouillé la fiche !\n\nCe texte n'existe en clair nulle part sur le disque. "
            "« Retirer le mot de passe » la remettrait en clair."))
        th = Theme(demo)
        self.verrouiller(th, f, exemples.MOT_DE_PASSE_DEMO, sans_secours=True)

    @staticmethod
    def _lire(p: Path) -> Fiche:
        if p.suffix == ".lock":   # texte non lu tant que le mot de passe n'est pas donné
            return Fiche(p, p.stem, None, True)
        brut = p.read_text(encoding="utf-8", errors="replace")
        titre, texte = p.stem, brut
        if brut.startswith("# "):
            premiere, _, reste = brut.partition("\n")
            titre = premiere[2:].strip()
            texte = reste[1:] if reste.startswith("\n") else reste
        texte, meta = separer_meta(texte)
        f = Fiche(p, titre, texte)
        f.meta = meta
        return f

    def theme(self, nom: str) -> Theme | None:
        return next((t for t in self.themes if t.nom == nom), None)

    # ---------- écriture ----------
    @staticmethod
    def _ecrire_md(p: Path, titre: str, texte: str) -> None:
        _ecrire(p, f"# {titre}\n\n{texte}".encode("utf-8"))

    @staticmethod
    def libre(dossier: Path, titre: str, actuel: Path | None = None, ext: str = ".md") -> Path:
        """Chemin libre pour ce titre (ajoute « (2) »… si pris par une autre fiche)."""
        base = propre(titre)
        nom, k = base, 2
        while any((dossier / f"{nom}{e}").exists() and (dossier / f"{nom}{e}") != actuel for e in (".md", ".lock")) \
                or ((dossier / f"{nom}.pj").exists() and (actuel is None or actuel.stem != nom)):
            nom = f"{base} ({k})"
            k += 1
        return dossier / f"{nom}{ext}"

    def a_la_corbeille(self, p: Path, nom: str | None = None, stamp: str | None = None) -> None:
        mkdir_prive(self.paths.corbeille)
        shutil.move(str(p), str(self.paths.corbeille / f'{stamp or time.strftime("%Y%m%d-%H%M%S")}-{nom or p.name}'))

    # ---------- thèmes ----------
    def nouveau_theme(self, nom: str) -> Theme:
        p = self.paths.fiches / propre(nom, "thème")
        mkdir_prive(p)
        th = Theme(p)
        self.themes.append(th)
        self.themes.sort(key=lambda t: t.nom.lower())
        self._hook()
        return th

    def renommer_theme(self, th: Theme, nom: str) -> None:
        nouveau = self.paths.fiches / propre(nom, "thème")
        os.rename(th.path, nouveau)
        th.path = nouveau
        for f in th.fiches:
            f.path = nouveau / f.path.name
        self.themes.sort(key=lambda t: t.nom.lower())
        self._hook()

    def icone_theme(self, th: Theme, icone: str) -> None:
        th.icone = icone.strip() or ICONE_DEFAUT
        _ecrire(th.path / ".icone", (th.icone + "\n").encode("utf-8"))
        self._hook()

    def supprimer_theme(self, th: Theme) -> None:
        self.a_la_corbeille(th.path)
        self.themes.remove(th)
        self._hook()   # après le retrait : le hook doit voir la liste à jour

    # ---------- fiches ----------
    def nouvelle_fiche(self, th: Theme) -> Fiche:
        p = self.libre(th.path, "")
        self._ecrire_md(p, "", "")
        f = Fiche(p, "", "")
        th.fiches.append(f)
        return f

    def supprimer_fiche(self, th: Theme, f: Fiche) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        pj = self.dossier_pj(f)
        self.a_la_corbeille(f.path, stamp=stamp)
        if pj.is_dir():
            self.a_la_corbeille(pj, stamp=stamp)
        th.fiches.remove(f)

    def jeter_si_vide(self, th: Theme, f: Fiche) -> bool:
        """Une fiche restée entièrement vide est supprimée sans passer par la corbeille."""
        if not f.verrou and not f.titre and not (f.texte or "").strip() and not self._numeros(self.dossier_pj(f)):
            try:
                f.path.unlink()
            except OSError:
                pass
            th.fiches.remove(f)
            return True
        return False

    def enregistrer(self, th: Theme, f: Fiche, titre: str, texte: str, force: bool = False) -> bool:
        """Écrit la fiche si elle a changé. Une fiche verrouillée n'est jamais écrite en clair."""
        if f.fermee or (not force and titre == f.titre and texte == f.texte):
            return False
        ancien = f.path
        ext = ".lock" if f.verrou else ".md"
        nouveau = ancien if ancien.exists() and propre(titre) == propre(f.titre) \
            else self.libre(th.path, titre, ancien, ext)
        if f.verrou:
            if not f.wrap:   # verrouillée avant la clé de secours : on l'ajoute à l'enregistrement
                f.wrap = crypto.envelopper(f.cle, self.paths.recovery_pub)
            _ecrire(nouveau, crypto.chiffrer(joindre_meta(f.meta, texte), f.cle, f.salt, f.wrap))
        else:
            self._ecrire_md(nouveau, titre, joindre_meta(f.meta, texte))
        if nouveau != ancien and ancien.exists():
            self._deplacer_pj(ancien, nouveau)   # à tout instant, l'un des deux chemins reste valide
            ancien.unlink()
        f.titre, f.texte, f.path = titre, texte, nouveau
        f.maj = time.strftime("%Y-%m-%d %H:%M")
        return True

    def maj_meta(self, th: Theme, f: Fiche, **valeurs) -> None:
        """Ajoute/modifie des métadonnées (valeur None ou "" = suppression) et enregistre. Fiche verrouillée fermée : refusé."""
        if f.fermee:
            raise ValueError("fiche verrouillée : déverrouillez-la d'abord")
        for k, v in valeurs.items():
            if v is None or v == "":
                f.meta.pop(k, None)
            else:
                f.meta[k] = str(v)
        self.enregistrer(th, f, f.titre, f.texte, force=True)

    # ---------- verrou ----------
    @property
    def a_cle_de_secours(self) -> bool:
        return self.paths.recovery_pub.exists()

    def verrouiller(self, th: Theme, f: Fiche, mdp: str, sans_secours: bool = False) -> None:
        salt = os.urandom(16)
        cle = crypto.deriver(mdp, salt)
        wrap = b"" if sans_secours else crypto.envelopper(cle, self.paths.recovery_pub)
        ancien = f.path
        nouveau = self.libre(th.path, f.titre, ancien, ".lock")
        nouveau_pj = self._preparer_pj(f, nouveau, cle, salt, wrap)     # 1) pièces chiffrées dans X.pj.new
        _ecrire(nouveau, crypto.chiffrer(joindre_meta(f.meta, f.texte), cle, salt, wrap))   # 2) la fiche
        self._echanger_pj(nouveau_pj, ancien, nouveau)                  # 3) échange des dossiers
        if ancien.exists():
            ancien.unlink()
        f.path, f.verrou, f.cle, f.salt, f.wrap = nouveau, True, cle, salt, wrap

    def deverrouiller(self, f: Fiche, mdp: str) -> None:
        """Lève crypto.InvalidTag (mauvais mot de passe) ou ValueError/OSError."""
        brut, cle, salt, wrap = crypto.dechiffrer(f.path.read_bytes(), mdp)
        if not wrap and self.a_cle_de_secours:   # ancienne fiche : on lui ajoute la clé de secours
            wrap = crypto.envelopper(cle, self.paths.recovery_pub)
            _ecrire(f.path, crypto.chiffrer(brut, cle, salt, wrap))
        f.texte, f.meta = separer_meta(brut)
        f.cle, f.salt, f.wrap = cle, salt, wrap

    def retirer_verrou(self, th: Theme, f: Fiche) -> None:
        ancien = f.path
        nouveau = self.libre(th.path, f.titre, ancien, ".md")
        nouveau_pj = self._preparer_pj(f, nouveau, None, None, b"")
        self._ecrire_md(nouveau, f.titre, joindre_meta(f.meta, f.texte))
        self._echanger_pj(nouveau_pj, ancien, nouveau)
        ancien.unlink()
        f.path, f.verrou, f.cle, f.salt, f.wrap = nouveau, False, None, None, b""

    def ouvrir_avec_cle_privee(self, f: Fiche, pem: bytes, phrase: str | None) -> str:
        """Texte de la fiche rouverte avec la clé de secours. La clé de la fiche est gardée en mémoire (pour pouvoir
        convertir aussi ses pièces jointes si on retire le verrou) : l'appelant la remet à None s'il renonce."""
        data = f.path.read_bytes()
        f.cle, f.salt, f.wrap = crypto.cle_depuis_cle_privee(data, pem, phrase)
        texte, f.meta = separer_meta(crypto.ouvrir_avec_cle_privee(data, pem, phrase))
        return texte

    def chemins_pieces(self, f: Fiche) -> list:
        """[(numéro, chemin)] des pièces présentes sur le disque (sans les déchiffrer)."""
        return self._numeros(self.dossier_pj(f))

    def texte_ocr(self, f: Fiche) -> str:
        """Texte extrait (OCR) des pièces, pour la recherche. Vide pour une fiche verrouillée fermée. En cache tant que
        les fichiers ne changent pas ; jamais écrit sur le disque (pour une fiche verrouillée : mémoire seulement)."""
        if f.fermee or (f.verrou and f.cle is None):
            f.ocr_cache = None
            return ""
        d = self.dossier_pj(f)
        if not d.is_dir():
            return ""
        signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(d.iterdir()))
        if f.ocr_cache and f.ocr_cache[0] == signature:
            return f.ocr_cache[1]
        texte = "\n".join(p.ocr for p in self.lister_pieces(f) if p.ocr)
        f.ocr_cache = (signature, texte)
        return texte

    # ---------- pièces jointes ----------
    @staticmethod
    def dossier_pj(f: Fiche) -> Path:
        return f.path.with_name(f.path.stem + ".pj")

    @staticmethod
    def _numeros(d: Path) -> list:
        """[(numéro, chemin)] des pièces d'un dossier .pj (sans les fichiers descriptifs .json)."""
        if not d.is_dir():
            return []
        return sorted((int(m[1]), p) for p in d.iterdir() if (m := _NOM_PIECE.match(p.name)))

    def lister_pieces(self, f: Fiche) -> list:
        """Pièces de la fiche. Fiche verrouillée : seulement si elle est ouverte (clé connue)."""
        if f.fermee or (f.verrou and f.cle is None):
            return []
        res = []
        for n, p in self._numeros(self.dossier_pj(f)):
            if p.suffix == ".lock":
                if not f.verrou:
                    continue
                try:
                    ent, donnees = crypto.dechiffrer_piece(p.read_bytes(), f.cle)
                except (crypto.InvalidTag, ValueError, OSError):
                    continue
                res.append(Piece(n, str(ent.get("nom", p.name)), str(ent.get("type", "image/png")), len(donnees), p,
                                 str(ent.get("ajoute", "")), str(ent.get("ocr", "")), str(ent.get("ocr_moteur", ""))))
            elif not f.verrou:
                try:
                    d = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    d = {}
                d = d if isinstance(d, dict) else {}
                res.append(Piece(n, str(d.get("nom", p.name)), TYPE_PIECE[p.suffix], p.stat().st_size, p,
                                 str(d.get("ajoute", "")), str(d.get("ocr", "")), str(d.get("ocr_moteur", ""))))
        return res

    @staticmethod
    def _entete(piece: Piece) -> dict:
        return {k: v for k, v in (("nom", piece.nom), ("type", piece.type), ("ajoute", piece.ajoute), ("ocr", piece.ocr),
                                  ("ocr_moteur", piece.ocr_moteur)) if v != ""}

    def ajouter_piece(self, f: Fiche, nom: str, type_: str, donnees: bytes) -> Piece:
        """Ajoute une image déjà réencodée (PNG ou JPEG). ValueError si fiche fermée, type ou limites non respectés."""
        if f.fermee or (f.verrou and f.cle is None):
            raise ValueError("fiche verrouillée : déverrouillez-la d'abord")
        if type_ not in EXT_PIECE:
            raise ValueError(f"type de pièce jointe non pris en charge : {type_}")
        if len(donnees) > LIMITES_PIECES["octets_piece"]:
            raise ValueError("image trop lourde")
        d = self.dossier_pj(f)
        existantes = self._numeros(d)
        if len(existantes) >= LIMITES_PIECES["nombre"]:
            raise ValueError("trop de pièces jointes pour cette fiche")
        if sum(p.stat().st_size for _n, p in existantes) + len(donnees) > LIMITES_PIECES["octets_total"]:
            raise ValueError("pièces jointes trop volumineuses pour cette fiche")
        n = max((n for n, _p in existantes), default=0) + 1
        piece = Piece(n, nom or f"image-{n}", type_, len(donnees), d, time.strftime("%Y-%m-%d %H:%M"))
        mkdir_prive(d)
        if f.verrou:
            piece.chemin = d / f"{n}.lock"
            _ecrire(piece.chemin, crypto.chiffrer_piece(self._entete(piece), donnees, f.cle, f.salt, f.wrap))
        else:
            piece.chemin = d / f"{n}{EXT_PIECE[type_]}"
            _ecrire(piece.chemin, donnees)
            _ecrire(d / f"{n}.json", json.dumps(self._entete(piece), ensure_ascii=False).encode("utf-8"))
        return piece

    def lire_piece(self, f: Fiche, piece: Piece) -> bytes:
        if f.verrou:
            return crypto.dechiffrer_piece(piece.chemin.read_bytes(), f.cle)[1]
        return piece.chemin.read_bytes()

    def maj_piece(self, f: Fiche, piece: Piece, **champs) -> None:
        """Change `ocr` et/ou `ocr_moteur` d'une pièce (texte extrait ; chiffré avec elle si la fiche est verrouillée)."""
        for k, v in champs.items():
            if k not in ("ocr", "ocr_moteur"):
                raise ValueError(f"champ inconnu : {k}")
            setattr(piece, k, str(v or ""))
        if f.verrou:
            donnees = crypto.dechiffrer_piece(piece.chemin.read_bytes(), f.cle)[1]
            _ecrire(piece.chemin, crypto.chiffrer_piece(self._entete(piece), donnees, f.cle, f.salt, f.wrap))
        else:
            sidecar = piece.chemin.with_suffix(".json")
            try:
                ancien = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                ancien = {}
            ancien = ancien if isinstance(ancien, dict) else {}
            ancien.update(self._entete(piece))
            for k in ("ocr", "ocr_moteur"):
                if not getattr(piece, k):
                    ancien.pop(k, None)
            _ecrire(sidecar, json.dumps(ancien, ensure_ascii=False).encode("utf-8"))

    def supprimer_piece(self, f: Fiche, piece: Piece) -> None:
        """À la corbeille (jamais d'effacement direct) ; le dossier .pj disparaît avec sa dernière pièce."""
        d = piece.chemin.parent
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.a_la_corbeille(piece.chemin, nom=f"{d.name}-{piece.chemin.name}", stamp=stamp)
        sidecar = piece.chemin.with_suffix(".json")
        if sidecar.exists():
            self.a_la_corbeille(sidecar, nom=f"{d.name}-{sidecar.name}", stamp=stamp)
        if not self._numeros(d):
            shutil.rmtree(d, ignore_errors=True)

    # échanges de dossiers : X.pj.new (complet, marqué .pret) -> X.pj ; l'ancien passe par X.pj.old
    def _preparer_pj(self, f: Fiche, nouveau: Path, cle, salt, wrap) -> Path | None:
        """Construit X.pj.new avec les pièces converties (chiffrées si `cle`, en clair sinon). None s'il n'y a rien."""
        d = self.dossier_pj(f)
        presents = self._numeros(d)
        if not presents:
            return None
        pieces = self.lister_pieces(f)
        if len(pieces) != len(presents):
            raise ValueError("pièces jointes illisibles : opération annulée (rien n'a été modifié)")
        dest = nouveau.with_name(nouveau.stem + ".pj.new")
        shutil.rmtree(dest, ignore_errors=True)
        mkdir_prive(dest)
        for p in pieces:
            donnees = self.lire_piece(f, p)
            if cle is not None:
                _ecrire(dest / f"{p.id}.lock", crypto.chiffrer_piece(self._entete(p), donnees, cle, salt, wrap))
            else:
                _ecrire(dest / f"{p.id}{EXT_PIECE[p.type]}", donnees)
                _ecrire(dest / f"{p.id}.json", json.dumps(self._entete(p), ensure_ascii=False).encode("utf-8"))
        _ecrire(dest / ".pret", b"")
        return dest

    def _echanger_pj(self, nouveau_pj: Path | None, ancien: Path, nouveau: Path) -> None:
        da = ancien.with_name(ancien.stem + ".pj")
        dn = nouveau.with_name(nouveau.stem + ".pj")
        if nouveau_pj is None:
            return
        old = dn.with_name(dn.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if dn.exists():
            os.rename(dn, old)
        os.rename(nouveau_pj, dn)
        (dn / ".pret").unlink(missing_ok=True)      # le marqueur reste jusqu'au bout : il prouve que .new est complet
        shutil.rmtree(old, ignore_errors=True)
        if da != dn:
            shutil.rmtree(da, ignore_errors=True)

    def _deplacer_pj(self, ancien: Path, nouveau: Path) -> None:
        da = ancien.with_name(ancien.stem + ".pj")
        dn = nouveau.with_name(nouveau.stem + ".pj")
        if da.is_dir() and da != dn:
            os.rename(da, dn)

    @staticmethod
    def _reparer_pj(theme: Path) -> None:
        """Reprise après interruption d'un échange de dossiers .pj (jamais de perte : .old restauré, .new valide promu)."""
        for new in theme.glob("*.pj.new"):
            pj = new.with_suffix("")
            nom = pj.stem
            genre = ".lock" if any(new.glob("*.lock")) else ".md"
            if (new / ".pret").exists() and (theme / f"{nom}{genre}").exists():
                old = pj.with_name(pj.name + ".old")
                if pj.exists():
                    shutil.rmtree(old, ignore_errors=True)
                    os.rename(pj, old)
                (new / ".pret").unlink(missing_ok=True)
                os.rename(new, pj)
            else:
                shutil.rmtree(new, ignore_errors=True)
        for old in theme.glob("*.pj.old"):
            pj = old.with_suffix("")
            if pj.exists():
                shutil.rmtree(old, ignore_errors=True)
            else:
                os.rename(old, pj)

    # ---------- réglages et hook ----------
    def reglages(self) -> dict:
        try:
            return json.loads(self.paths.settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def sauver_reglages(self, **kw) -> None:
        d = self.reglages()
        d.update(kw)
        mkdir_prive(self.paths.base)
        _ecrire(self.paths.settings, json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8"))

    def _hook(self) -> None:
        """Si `<base>/hooks/themes-changed` existe et est exécutable, l'appelle avec la liste des thèmes en JSON sur stdin."""
        h = self.paths.hooks / "themes-changed"
        if not (h.is_file() and os.access(h, os.X_OK)):
            return
        données = json.dumps([{"nom": t.nom, "icone": t.icone, "fiches": len(t.fiches)} for t in self.themes])
        try:
            subprocess.run([str(h)], input=données.encode("utf-8"), timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as ex:
            print(f"hook themes-changed : {ex}", file=sys.stderr)
