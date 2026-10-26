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
    """Texte générique et poli (vouvoiement, aucune formule personnelle) : l'expéditeur y ajoute lui-même son mot."""
    v = {"v": version, "depot": DEPOT}
    blocs = [
        _("Bonjour,"),
        _("Scrinium est un logiciel libre et gratuit (GPL-3.0) de prise de notes : des fiches rangées par thème (numéros, "
          "procédures, codes), que l'on peut verrouiller avec un mot de passe (chiffrement AES-256). Tout reste sur votre "
          "ordinateur, dans de simples fichiers texte.\n\nPage du projet : %(depot)s\n\n"
          "Voici comment l'installer selon votre système.") % v,
        _("— Linux Debian ou Ubuntu —\n\nDans un terminal :\n\n"
          "    cd /tmp\n"
          "    wget %(depot)s/releases/download/v%(v)s/scrinium_%(v)s_all.deb\n"
          "    wget %(depot)s/releases/download/v%(v)s/SHA256SUMS\n"
          "    sha256sum -c SHA256SUMS\n"
          "    sudo apt install ./scrinium_%(v)s_all.deb\n\n"
          "La commande sha256sum vérifie que le fichier est intact : elle doit répondre « OK ». Ensuite : menu des "
          "applications → Scrinium, ou la commande « scrinium ». Une version plus récente existe peut-être : "
          "%(depot)s/releases/latest") % v,
        _("— Autres Linux (sans droits administrateur) —\n\nIl faut Python 3.10 ou plus. Téléchargez le dossier du projet "
          "(bouton vert « Code », puis « Download ZIP » sur la page du projet), décompressez-le, puis dans ce dossier :\n\n"
          "    ./install.sh\n\nPour désinstaller : ./install.sh --uninstall (vos fiches sont conservées)."),
        _("— Windows —\n\n"
          "  1. Téléchargez le programme d'installation :\n"
          "     %(depot)s/releases/download/v%(v)s/Scrinium-%(v)s-setup.exe\n"
          "  2. Double-cliquez dessus. Windows peut afficher « Windows a protégé votre ordinateur » : le programme "
          "n'est pas signé. Cliquez sur « Informations complémentaires », puis sur « Exécuter quand même ».\n"
          "  3. Suivez l'assistant (aucun droit administrateur n'est nécessaire). Scrinium apparaît dans le menu "
          "Démarrer.\n\n"
          "Pour le désinstaller : Paramètres → Applications. Vos fiches ne sont jamais supprimées.") % v,
        _("— macOS —\n\nIl n'existe pas encore de programme d'installation pour macOS. En attendant, l'installation passe "
          "par Python (méthode non testée sous macOS) :\n\n"
          "    python3 -m venv ~/scrinium-venv\n"
          "    ~/scrinium-venv/bin/pip install %(depot)s/archive/refs/tags/v%(v)s.zip\n"
          "    ~/scrinium-venv/bin/scrinium") % v,
        _("— Premier lancement —\n\nScrinium crée un thème « Bienvenue » (fiches qui expliquent le fonctionnement) et "
          "propose de créer un fichier de secours : conservez-le précieusement, il permet de rouvrir une fiche verrouillée "
          "dont le mot de passe aurait été oublié."),
        _("— Les extensions —\n\nMenu « Extensions », puis « Gérer les extensions… » : elles sont toutes désactivées au "
          "départ, vous activez celles qui vous intéressent. Aucune n'installe ni ne télécharge quoi que ce soit sans vous "
          "le demander d'abord.\n\n"
          "Pour commencer (rien à installer) :\n"
          "  • Agenda : des rappels avec notification et son, qui peuvent se répéter (chaque jour, semaine, mois, année : "
          "pratique pour les anniversaires), liés ou non à une fiche.\n"
          "  • Courriel : envoie une fiche par courriel.\n"
          "  • Applications : un panneau d'icônes pour lancer vos applications préférées.\n\n"
          "Plus gourmandes (elles proposent d'installer ce qu'il faut, avec votre accord) :\n"
          "  • Lecture à voix haute : lit une fiche ou tout un thème, en français ou en anglais (Linux uniquement).\n"
          "  • OCR : extrait le texte des images collées dans une fiche (demande Tesseract).\n"
          "  • Dictée : le texte se dicte à voix haute et s'écrit dans la fiche, sans rien envoyer sur Internet "
          "(Linux uniquement).\n"
          "  • Traduction : traduit une fiche avec un modèle qui fonctionne sur votre ordinateur ; gros téléchargement "
          "(plusieurs Go), pour un ordinateur puissant.\n"
          "  • Capture et console : insère dans une fiche le résultat d'une commande (Linux uniquement)."),
        _("Pour toute question ou suggestion, rendez-vous sur la page du projet : %(depot)s") % v,
        _("Bonne découverte !"),
    ]
    return "\n\n".join(blocs) + "\n"
