# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fiche « Inviter à installer Scrinium » : texte prêt à relire puis à envoyer (liens et marche à suivre selon le système).
Le texte est écrit pour être lu aussi en texte brut dans un courriel ; les liens pointent vers la version de Scrinium
qui l'a créé (toujours valides une fois la version publiée)."""
from .. import __version__
from ..i18n import _

DEPOT = "https://github.com/jfkneib/scrinium"


def titre_fiche() -> str:
    return _("Inviter à installer Scrinium")


def nom_theme() -> str:
    return _("Invitations")


def texte(version: str = __version__) -> str:
    v = {"v": version, "depot": DEPOT}
    blocs = [
        _("Bonjour,"),
        _("je t'invite à essayer Scrinium : des fiches rangées par thème (numéros, procédures, codes), que l'on peut "
          "verrouiller avec un mot de passe (chiffrement AES-256). Tout reste sur ton ordinateur, dans de simples fichiers "
          "texte. Libre et gratuit (GPL-3.0).\n\nPage du projet : %(depot)s") % v,
        _("— Linux Debian ou Ubuntu —\n\nDans un terminal :\n\n"
          "    cd /tmp\n"
          "    wget %(depot)s/releases/download/v%(v)s/scrinium_%(v)s_all.deb\n"
          "    wget %(depot)s/releases/download/v%(v)s/SHA256SUMS\n"
          "    sha256sum -c SHA256SUMS\n"
          "    sudo apt install ./scrinium_%(v)s_all.deb\n\n"
          "La commande sha256sum vérifie que le fichier est intact : elle doit répondre « OK ». Ensuite : menu des "
          "applications → Scrinium, ou la commande « scrinium ». Une version plus récente existe peut-être : "
          "%(depot)s/releases/latest") % v,
        _("— Autres Linux (sans droits administrateur) —\n\nIl faut Python 3.10 ou plus. Télécharge le dossier du projet "
          "(bouton vert « Code » puis « Download ZIP » sur la page ci-dessus), décompresse-le, puis dans ce dossier :\n\n"
          "    ./install.sh\n\nPour désinstaller : ./install.sh --uninstall (tes fiches sont conservées)."),
        _("— Windows et macOS —\n\nPas encore de programme d'installation. Dis-moi quel système tu utilises : je te "
          "préparerai la marche à suivre."),
        _("— Premier lancement —\n\nScrinium crée un thème « Bienvenue » (fiches qui expliquent tout) et propose de créer un "
          "fichier de secours : garde-le précieusement, il permet de rouvrir une fiche verrouillée dont tu aurais oublié le "
          "mot de passe."),
        _("— Les extensions (facultatif) —\n\nMenu « Extensions », puis « Gérer les extensions… » : elles sont toutes "
          "désactivées au départ, tu actives celles qui t'intéressent. Aucune n'installe ni ne télécharge quoi que ce soit "
          "sans te le demander d'abord : agenda (rappels, répétitions), lecture à voix haute, OCR (texte des images), "
          "dictée, traduction, courriel, capture et console, applications."),
        _("Bonne découverte, et n'hésite pas à me dire ce qui te manque."),
    ]
    return "\n\n".join(blocs) + "\n"
