# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extensions (plugins), API v1. Aucune dépendance graphique : l'interface fournit `ui_factory`.

Découverte SANS exécuter de code :
  - dossier `<données>/plugins/<nom>/plugin.json` (+ `__init__.py`) ;
  - paquets installés déclarant l'entry point `scrinium.plugins`.
Le code d'une extension n'est importé qu'à son activation, décidée par l'utilisateur (désactivées par défaut).

Une extension est du code Python complet dans le processus : ce n'est PAS un bac à sable. `Contexte` offre une API propre
(jamais la clé d'une fiche), pas une barrière de sécurité.
"""
import importlib.metadata
import importlib.util
import json
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

API_VERSION = 1
MAX_ERREURS = 5     # au-delà, l'extension est désactivée automatiquement
EVENEMENTS = ("demarrage", "arret", "fiche_ouverte", "fiche_enregistree", "fiche_fermee", "themes_modifies",
              "fenetre_cachee", "fenetre_montree")
_NOM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class Plugin:
    """Classe de base d'une extension. `api` : version d'API visée (doit égaler API_VERSION)."""
    api = API_VERSION

    def activer(self, ctx: "Contexte") -> None:
        pass

    def desactiver(self) -> None:
        pass


class PluginIncompatible(Exception):
    pass


@dataclass
class InfoPlugin:
    nom: str
    titre: str
    version: str
    description: str
    auteur: str
    source: str                 # "dossier" ou "paquet"
    charger: Callable           # retourne la classe du plugin (importe le code : seulement à l'activation)
    api: int | None = None
    erreur: str = ""


class FicheVue:
    """Vue en lecture d'une fiche, donnée aux extensions (ni clé, ni chemin ; texte absent si fiche verrouillée fermée)."""
    __slots__ = ("_th", "_f")

    def __init__(self, theme, fiche):
        self._th, self._f = theme, fiche

    id = property(lambda s: f"{s._th.nom}/{s._f.path.name}")
    titre = property(lambda s: s._f.titre)
    theme = property(lambda s: s._th.nom)
    verrou = property(lambda s: s._f.verrou)
    fermee = property(lambda s: s._f.fermee)
    texte = property(lambda s: None if s._f.fermee else s._f.texte)
    meta = property(lambda s: {} if s._f.fermee else dict(s._f.meta))

    def __repr__(self):
        return f"<FicheVue {self.id}{' (verrouillée)' if self.verrou else ''}>"


class ReglagesPlugin:
    """Réglages propres à une extension, dans settings.json (clé « plugins » / nom)."""

    def __init__(self, store, nom):
        self._store, self._nom = store, nom

    def tous(self) -> dict:
        return dict(self._store.reglages().get("plugins", {}).get(self._nom, {}))

    def get(self, cle, defaut=None):
        return self.tous().get(cle, defaut)

    def set(self, cle, valeur) -> None:
        d = self._store.reglages().get("plugins", {})
        d.setdefault(self._nom, {})[cle] = valeur
        self._store.sauver_reglages(plugins=d)


class Contexte:
    """Ce que reçoit une extension dans `activer(ctx)`."""
    api = API_VERSION

    def __init__(self, gestionnaire: "Gestionnaire", info: InfoPlugin):
        self._g, self.info = gestionnaire, info
        self.reglages = ReglagesPlugin(gestionnaire.store, info.nom)
        self.ui = None   # fourni par l'interface (None sans fenêtre)
        self.dossier_donnees = gestionnaire.store.paths.base / "plugins-donnees" / info.nom   # propre à l'extension, créé à la demande

    def on(self, evenement: str, fn: Callable) -> None:
        """S'abonne à un événement (voir EVENEMENTS). `fn(**arguments)` ; les exceptions sont interceptées."""
        if evenement not in EVENEMENTS:
            raise ValueError(f"événement inconnu : {evenement}")
        self._g._abonner(self.info.nom, evenement, fn)

    def themes(self) -> list:
        return [t.nom for t in self._g.store.themes]

    def fiches(self, theme: str | None = None) -> list:
        return [FicheVue(t, f) for t in self._g.store.themes if theme in (None, t.nom) for f in t.fiches]

    def fiche_courante(self):
        return self._g.fiche_courante() if self._g.fiche_courante else None

    def _trouver(self, vue: FicheVue):
        for t in self._g.store.themes:
            for f in t.fiches:
                if t is vue._th and f is vue._f:
                    return t, f
        raise ValueError("fiche inconnue (supprimée ?)")

    def maj_meta(self, vue: FicheVue, **valeurs) -> None:
        """Ajoute/modifie/supprime (valeur None) des métadonnées. ValueError si la fiche est verrouillée fermée."""
        t, f = self._trouver(vue)
        self._g.store.maj_meta(t, f, **valeurs)
        self._g.emettre("fiche_enregistree", fiche=FicheVue(t, f), origine=self.info.nom)

    def modifier(self, vue: FicheVue, titre: str | None = None, texte: str | None = None) -> None:
        t, f = self._trouver(vue)
        if f.fermee:
            raise ValueError("fiche verrouillée : déverrouillez-la d'abord")
        self._g.store.enregistrer(t, f, f.titre if titre is None else titre, f.texte if texte is None else texte)
        self._g.emettre("fiche_enregistree", fiche=FicheVue(t, f), origine=self.info.nom)


class Gestionnaire:
    def __init__(self, store, ui_factory: Callable | None = None, dossier: Path | None = None,
                 fiche_courante: Callable | None = None, sur_desactivation_auto: Callable | None = None):
        self.store = store
        self.ui_factory = ui_factory
        self.dossier = dossier or store.paths.base / "plugins"
        self.fiche_courante = fiche_courante
        self.sur_desactivation_auto = sur_desactivation_auto
        self.infos: dict[str, InfoPlugin] = {}
        self.actifs: dict[str, tuple] = {}              # nom -> (instance, contexte)
        self._abonnements: dict[str, list] = {}         # événement -> [(nom, fn)]
        self.erreurs: dict[str, int] = {}

    # ---------- découverte (sans exécuter le code des extensions) ----------
    def decouvrir(self) -> dict:
        self.infos = {}
        try:
            eps = importlib.metadata.entry_points(group="scrinium.plugins")
        except Exception:
            eps = []
        for ep in eps:
            if not _NOM.match(ep.name):
                continue
            dist = getattr(ep, "dist", None)
            meta = dist.metadata if dist else {}
            self.infos[ep.name] = InfoPlugin(
                ep.name, ep.name, getattr(dist, "version", "?") if dist else "?", meta.get("Summary", "") if dist else "",
                meta.get("Author", "") if dist else "", "paquet", ep.load)
        if self.dossier.is_dir():
            for sub in sorted(self.dossier.iterdir()):
                man = sub / "plugin.json"
                if not (sub.is_dir() and man.is_file() and _NOM.match(sub.name)) or sub.name in self.infos:
                    continue
                try:
                    m = json.loads(man.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                self.infos[sub.name] = InfoPlugin(
                    sub.name, str(m.get("titre", sub.name)), str(m.get("version", "?")), str(m.get("description", "")),
                    str(m.get("auteur", "")), "dossier", self._chargeur_dossier(sub, str(m.get("classe", "Plugin"))),
                    api=m.get("api") if isinstance(m.get("api"), int) else None)
        return self.infos

    @staticmethod
    def _chargeur_dossier(sub: Path, classe: str) -> Callable:
        def charger():
            nom_module = f"scrinium_plugin_{sub.name.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(nom_module, sub / "__init__.py",
                                                          submodule_search_locations=[str(sub)])
            mod = importlib.util.module_from_spec(spec)
            sys.modules[nom_module] = mod
            spec.loader.exec_module(mod)
            return getattr(mod, classe)
        return charger

    # ---------- activation ----------
    def actifs_reglage(self) -> list:
        return list(self.store.reglages().get("plugins_actifs", []))

    def _persister(self, nom: str, actif: bool) -> None:
        liste = [n for n in self.actifs_reglage() if n != nom]
        if actif:
            liste.append(nom)
        self.store.sauver_reglages(plugins_actifs=liste)

    def demarrer(self) -> None:
        """Active les extensions choisies par l'utilisateur, puis émet « demarrage »."""
        self.decouvrir()
        for nom in self.actifs_reglage():
            if nom in self.infos:
                self.activer(nom, persister=False)
        self.emettre("demarrage")

    def activer(self, nom: str, persister: bool = True) -> bool:
        info = self.infos.get(nom)
        if info is None or nom in self.actifs:
            return nom in self.actifs
        try:
            classe = info.charger()
            api = getattr(classe, "api", None)
            if api != API_VERSION:
                raise PluginIncompatible(f"API {api} (ce Scrinium fournit l'API {API_VERSION})")
            instance = classe()
            ctx = Contexte(self, info)
            ctx.ui = self.ui_factory(info) if self.ui_factory else None
            self.actifs[nom] = (instance, ctx)
            instance.activer(ctx)
        except Exception as ex:   # une extension défaillante ne doit jamais empêcher Scrinium de démarrer
            info.erreur = f"{type(ex).__name__}: {ex}"
            print(f"extension {nom} : {info.erreur}", file=sys.stderr)
            self._retirer(nom)
            return False
        info.erreur = ""
        self.erreurs[nom] = 0
        if persister:
            self._persister(nom, True)
        return True

    def _retirer(self, nom: str) -> None:
        pair = self.actifs.pop(nom, None)
        for evt in list(self._abonnements):
            self._abonnements[evt] = [(n, f) for n, f in self._abonnements[evt] if n != nom]
        if pair:
            instance, ctx = pair
            try:
                instance.desactiver()
            except Exception:
                traceback.print_exc()
            try:
                if ctx.ui is not None:
                    ctx.ui.retirer_tout()
            except Exception:
                traceback.print_exc()

    def desactiver(self, nom: str, persister: bool = True) -> None:
        self._retirer(nom)
        if persister:
            self._persister(nom, False)

    def arreter(self) -> None:
        self.emettre("arret")
        for nom in list(self.actifs):
            self._retirer(nom)

    # ---------- événements et isolation des pannes ----------
    def _abonner(self, nom: str, evenement: str, fn: Callable) -> None:
        self._abonnements.setdefault(evenement, []).append((nom, fn))

    def emettre(self, evenement: str, **kw) -> None:
        for nom, fn in list(self._abonnements.get(evenement, [])):
            self.appeler(nom, fn, **kw)

    def appeler(self, nom: str, fn: Callable, *a, **kw):
        """Appelle du code d'extension : toute exception est journalisée ; après MAX_ERREURS, l'extension est désactivée."""
        try:
            return fn(*a, **kw)
        except Exception as ex:
            traceback.print_exc()
            self.erreurs[nom] = self.erreurs.get(nom, 0) + 1
            if nom in self.infos:
                self.infos[nom].erreur = f"{type(ex).__name__}: {ex}"
            if self.erreurs[nom] >= MAX_ERREURS and nom in self.actifs:
                self.desactiver(nom)
                if self.sur_desactivation_auto:
                    self.sur_desactivation_auto(nom, self.infos[nom].erreur)
        return None
