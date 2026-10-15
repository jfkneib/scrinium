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
from pathlib import Path

from . import crypto, exemples
from ..i18n import _
from .paths import Paths

ICONE_DEFAUT = "view-pim-notes"
POSIX = os.name == "posix"


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


class Fiche:
    def __init__(self, path: Path, titre: str, texte: str | None, verrou: bool = False):
        self.path, self.titre, self.texte, self.verrou = path, titre, texte, verrou
        self.cle = self.salt = None
        self.wrap = b""
        self.meta: dict = {}
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
        while any((dossier / f"{nom}{e}").exists() and (dossier / f"{nom}{e}") != actuel for e in (".md", ".lock")):
            nom = f"{base} ({k})"
            k += 1
        return dossier / f"{nom}{ext}"

    def a_la_corbeille(self, p: Path) -> None:
        mkdir_prive(self.paths.corbeille)
        shutil.move(str(p), str(self.paths.corbeille / f'{time.strftime("%Y%m%d-%H%M%S")}-{p.name}'))

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
        self.a_la_corbeille(f.path)
        th.fiches.remove(f)

    def jeter_si_vide(self, th: Theme, f: Fiche) -> bool:
        """Une fiche restée entièrement vide est supprimée sans passer par la corbeille."""
        if not f.verrou and not f.titre and not (f.texte or "").strip():
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
        _ecrire(nouveau, crypto.chiffrer(joindre_meta(f.meta, f.texte), cle, salt, wrap))
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
        self._ecrire_md(nouveau, f.titre, joindre_meta(f.meta, f.texte))
        ancien.unlink()
        f.path, f.verrou, f.cle, f.salt, f.wrap = nouveau, False, None, None, b""

    def ouvrir_avec_cle_privee(self, f: Fiche, pem: bytes, phrase: str | None) -> str:
        texte, f.meta = separer_meta(crypto.ouvrir_avec_cle_privee(f.path.read_bytes(), pem, phrase))
        return texte

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
