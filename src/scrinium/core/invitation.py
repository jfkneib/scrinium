# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fiche « Inviter à installer Scrinium » : texte prêt à relire puis à envoyer (liens et marche à suivre selon le système).
Le texte est écrit pour être lu aussi en texte brut dans un courriel ; les liens pointent vers la version de Scrinium
qui l'a créé (toujours valides une fois la version publiée)."""
from .. import __version__
from ..i18n import _

DEPOT = "https://github.com/jfkneib/scrinium"


def titre_fiche() -> str:
    return _("Invitation à essayer Scrinium")        # devient l'objet du courriel : il doit se lire bien chez le destinataire


def nom_theme() -> str:
    return _("Invitations")


def texte(version: str = __version__) -> str:
    v = {"v": version, "depot": DEPOT}
    blocs = [
        _("Bonjour,"),
        _("je t'invite à essayer Scrinium, un petit logiciel de notes que j'ai écrit : des fiches rangées par thème "
          "(numéros, procédures, codes), que l'on peut verrouiller avec un mot de passe (chiffrement AES-256). Tout reste "
          "sur ton ordinateur, dans de simples fichiers texte. Libre et gratuit (GPL-3.0).\n\nPage du projet : %(depot)s") % v,
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
        _("— Windows —\n\n"
          "  1. Télécharge le programme d'installation :\n"
          "     %(depot)s/releases/download/v%(v)s/Scrinium-%(v)s-setup.exe\n"
          "  2. Double-clique dessus. Windows peut afficher « Windows a protégé votre ordinateur » : le programme n'est "
          "pas signé (c'est payant). Clique sur « Informations complémentaires », puis « Exécuter quand même ».\n"
          "  3. Suis l'assistant (aucun droit administrateur nécessaire). Scrinium apparaît dans le menu Démarrer.\n\n"
          "Pour le désinstaller : Paramètres → Applications. Tes fiches ne sont jamais supprimées. Dis-moi si ça "
          "coince.") % v,
        _("— macOS —\n\nPas encore de programme d'installation. En attendant, par Python (je ne l'ai pas encore essayé sous "
          "macOS, dis-moi si ça coince) :\n\n"
          "    python3 -m venv ~/scrinium-venv\n"
          "    ~/scrinium-venv/bin/pip install %(depot)s/archive/refs/tags/v%(v)s.zip\n"
          "    ~/scrinium-venv/bin/scrinium") % v,
        _("— Premier lancement —\n\nScrinium crée un thème « Bienvenue » (fiches qui expliquent tout) et propose de créer un "
          "fichier de secours : garde-le précieusement, il permet de rouvrir une fiche verrouillée dont tu aurais oublié le "
          "mot de passe."),
        _("— Les extensions —\n\nMenu « Extensions », puis « Gérer les extensions… » : elles sont toutes désactivées au "
          "départ, tu actives celles qui t'intéressent. Aucune n'installe ni ne télécharge quoi que ce soit sans te le "
          "demander d'abord.\n\n"
          "Pour commencer (rien à installer) :\n"
          "  • Agenda : des rappels avec notification et son, qui se répètent (chaque jour, semaine, mois, année : "
          "pratique pour les anniversaires), liés ou non à une fiche.\n"
          "  • Courriel : envoie une fiche par courriel (c'est comme ça que je t'ai envoyé celle-ci).\n"
          "  • Applications : un panneau d'icônes pour lancer tes applications préférées.\n\n"
          "Plus gourmandes (elles proposent d'installer ce qu'il faut, avec ton accord) :\n"
          "  • Lecture à voix haute : lit une fiche ou tout un thème, en français ou en anglais (Linux).\n"
          "  • OCR : extrait le texte des images collées dans une fiche (demande Tesseract).\n"
          "  • Dictée : tu parles, le texte s'écrit dans la fiche, sans rien envoyer sur Internet (Linux).\n"
          "  • Traduction : traduit une fiche avec un modèle qui tourne chez toi ; gros téléchargement "
          "(plusieurs Go), pour un ordinateur costaud.\n"
          "  • Capture et console : insère dans une fiche le résultat d'une commande (Linux)."),
        _("Bonne découverte, et n'hésite pas à me dire ce qui te manque."),
    ]
    return "\n\n".join(blocs) + "\n"
