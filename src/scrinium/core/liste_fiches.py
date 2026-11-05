# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Une liste d'éléments (applications, actions CLI…) tenue par des fiches d'un type exécutable (« tout est fiche », voir types_fiche.py).

Ce que fait ce module, une fois pour toutes les extensions de ce genre (sans interface) :
- les éléments sont ceux des fiches du type qui sont **validées** par l'utilisateur (une fiche reçue ou modifiée ailleurs reste inerte) ;
- tant qu'aucune fiche n'est validée, les réglages d'avant « tout est fiche » servent (puis, à défaut, des exemples) ;
- création, une seule fois, de la fiche : à partir des réglages d'avant (qui restent comme copie) ou, sans réglage, des exemples ; elle est
  créée inerte (l'utilisateur la valide) et jamais recréée si elle est supprimée ensuite ;
- la fiche à ouvrir pour modifier la liste (créée à partir de la liste actuelle s'il n'y en a pas)."""
from . import types_fiche


class ListeDeFiches:
    def __init__(self, ctx, type_fiche, normaliser_liste, depuis_texte, en_texte, cle_reglage: str, par_defaut,
                 titre: str, theme: str = "Outils", maximum: int = 200):
        """`depuis_texte(texte) -> liste`, `en_texte(liste) -> texte`, `normaliser_liste(brut) -> liste`, `par_defaut() -> liste`
        (exemples, quand il n'y a ni fiche validée ni réglage), `cle_reglage` : la clé des réglages d'avant."""
        self.ctx, self.type, self.maximum = ctx, type_fiche, maximum
        self._norm, self._lire, self._ecrire = normaliser_liste, depuis_texte, en_texte
        self.cle_reglage, self._par_defaut, self.titre, self.theme = cle_reglage, par_defaut, titre, theme

    def fiches(self) -> list:
        """[(fiche, validée ?)] des fiches de ce type, par thème puis titre."""
        res = []
        for v in self.ctx.fiches():
            t = types_fiche.type_de(v.texte)
            if t is not None and t.nom == self.type.nom:
                res.append((v, self.ctx.fiche_active(v)))
        return sorted(res, key=lambda x: (x[0].theme.lower(), x[0].titre.lower()))

    def elements(self) -> list:
        """Éléments des fiches VALIDÉES (sans doublon nom+commande) ; sinon les réglages d'avant ; sinon les exemples."""
        actives = [v for v, ok in self.fiches() if ok]
        if actives:
            vus, res = set(), []
            for v in actives:
                for e in self._lire(v.texte):
                    cle = (e["nom"], e["commande"])
                    if cle not in vus:
                        vus.add(cle)
                        res.append(e)
            return res[:self.maximum]
        brut = self.ctx.reglages.get(self.cle_reglage)
        return self._par_defaut() if brut is None else self._norm(brut)

    def a_valider(self) -> int:
        """Nombre de fiches de ce type en attente de validation (reçues, ou modifiées ailleurs)."""
        return sum(1 for _v, ok in self.fiches() if not ok)

    def migrer(self):
        """Les réglages d'avant (ou, sans réglage, les exemples) deviennent une fiche, une seule fois. Retourne la fiche créée (inerte),
        sinon None."""
        brut = self.ctx.reglages.get(self.cle_reglage)
        if self.ctx.reglages.get("migrees"):
            return None
        self.ctx.reglages.set("migrees", True)
        elements = self._norm(brut) if isinstance(brut, list) else self._par_defaut()
        if elements and not self.fiches():
            return self.ctx.creer_fiche(self.theme, self.titre, self._ecrire(elements))
        return None

    def a_ouvrir(self):
        """(fiche, créée ?) : la fiche validée (sinon la première) ; sans fiche, une nouvelle à partir de la liste actuelle (inerte)."""
        fiches = self.fiches()
        if fiches:
            return next((v for v, ok in fiches if ok), fiches[0][0]), False
        return self.ctx.creer_fiche(self.theme, self.titre, self._ecrire(self.elements())), True
