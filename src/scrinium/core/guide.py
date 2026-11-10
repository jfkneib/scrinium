# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Thème « Guide » : fiches qui présentent Scrinium en entier (principes, types de fiches, extensions, sécurité, sauvegarde).

Proposé à la demande (menu Aide > « Guide de Scrinium »), sans jamais écraser une fiche que l'utilisateur aurait modifiée : seules
les fiches absentes sont ajoutées. Ce sont des fiches comme les autres (cherchables, modifiables, partageables)."""
from ..i18n import _


def nom_theme() -> str:
    return _("Guide")


def icone() -> str:
    return "help-contents"


def fiches(dossier_fiches) -> list:
    """[(titre, texte)] des fiches du guide ; `dossier_fiches` : dossier où Scrinium range les fiches de l'utilisateur."""
    return [
        (_("Guide 1 · Le principe"), _(
            "Scrinium range vos petites notes (codes, procédures, listes, numéros…) en FICHES, classées par THÈMES.\n"
            "\n"
            "• Tout est fiche : une note, mais aussi une liste d'applications, un dossier de photos, des actions de terminal. "
            "Une fiche peut avoir un TYPE (voir « Guide 3 »).\n"
            "• Tout s'enregistre tout seul. Chaque fiche est un fichier texte (.md) dans un dossier de thème : vous pouvez les lire "
            "avec n'importe quel éditeur.\n"
            "• Rien ne quitte votre ordinateur sans votre action : pas de compte, pas de nuage. Le partage, la traduction, la dictée… "
            "sont des EXTENSIONS facultatives, désactivées tant que vous ne les activez pas.\n"
            "• Une fiche sensible se VERROUILLE par mot de passe (chiffrement AES-256).")),
        (_("Guide 2 · Gestes utiles"), _(
            "• Nouvelle fiche : Ctrl+N ou le bouton « Fiche ». Nouveau thème : bouton « Thème ».\n"
            "• Chercher : Ctrl+F (titres, notes et thèmes, tous thèmes confondus). Le thème « ★ Toutes les fiches » montre tout.\n"
            "• Déplacer une fiche vers un autre thème : glissez-la sur le thème (ou clic droit sur la fiche > « Déplacer vers le thème »).\n"
            "• Ranger : glissez les fiches pour changer leur ordre, mettez-les en favoris.\n"
            "• Images : on peut joindre des images à une fiche ; le clic droit sur une image propose l'OCR si l'extension est activée.\n"
            "• Supprimer : la fiche ou le thème va à la corbeille, rien n'est détruit tout de suite.\n"
            "• Langue : menu Aide > Langue (automatique, français, anglais).")),
        (_("Guide 3 · Les types de fiches"), _(
            "Un type change l'AFFICHAGE d'une fiche. Il se choisit à la création : flèche du bouton « Fiche » > « Nouvelle fiche » > type.\n"
            "\n"
            "• Note (par défaut) : du texte.\n"
            "• Applications : une grille d'icônes pour lancer vos logiciels sans quitter Scrinium (extension Applications).\n"
            "• Photos : un dossier d'images montré en vignettes ; les images restent dans leur dossier (extension Photos).\n"
            "• Actions CLI : des commandes à lancer d'un clic (extension Capture).\n"
            "• Agenda : des rappels et échéances (extension Agenda).\n"
            "• Calc : un petit éditeur de listes avec des totaux par colonne et l'export CSV, pour suivre des relevés (extension Calc).\n"
            "• Budget : de petits comptes (courses, argent de poche…) avec colonnes Débit et Crédit, un onglet par mois, un bilan, et une fiche « Budget — résultat » qui totalise tous les budgets (extension Budget).\n"
            "• Supervision : l'état de vos machines (ping, ports, page web, disque, mémoire et charge par SSH) dans une fiche, avec une notification quand l'une tombe (extension Supervision).\n"
            "• Planning : des tâches en couleurs sur un diagramme de Gantt, avec l'avancement, les retards et un rétroplanning à partir d'une date de fin (extension Planning).\n"
            "• Tableur : des cellules et des formules comme =SOMME(B2:B10), avec export et import CSV (extension Tableur).\n"
            "\n"
            "Sécurité : un type qui LANCE des commandes (Applications, Actions CLI) reste inerte tant que vous n'avez pas validé la "
            "fiche vous-même. Une fiche reçue d'un autre n'exécute donc jamais rien toute seule.")),
        (_("Guide 4 · Les extensions"), _(
            "Menu Extensions > Gérer les extensions… : cochez celles qui vous servent. Livrées avec Scrinium :\n"
            "\n"
            "• Courriel : envoie la fiche affichée.\n"
            "• OCR : extrait le texte des images jointes (Tesseract, en local) ; le texte devient cherchable. "
            "Clic droit sur l'image : « Texte de l'image → nouvelle fiche » ou « → dans la fiche, au curseur ».\n"
            "• Partage : partage des fiches avec d'autres via un serveur Scrinium (voir « Guide 6 »).\n"
            "• Traduction et Dictée : en local (modèles téléchargés seulement avec votre accord).\n"
            "• Lecture : lit une fiche à voix haute.\n"
            "• Agenda, Applications, Photos, Calc, Tableur, Budget, Planning : types de fiches ; Calculatrice : une mini calculatrice flottante (voir « Guide 3 »).\n"
            "• Capture : insère la sortie d'une commande dans la fiche, ou envoie du texte vers une console (voir « Guide 5 »).\n"
            "\n"
            "Écrire la vôtre : menu Aide > « Documentation des extensions ».")),
        (_("Guide 5 · Console et commandes"), _(
            "L'extension Capture relie vos fiches au terminal, sans jamais rien valider à votre place.\n"
            "\n"
            "• Bouton « Console » : sélectionnez du texte dans la fiche (par exemple « ls -al »), cliquez. Le texte est TAPÉ dans une "
            "Konsole « Scrinium », SANS Entrée : vous relisez, puis vous validez. Le résultat apparaît dans la console, pas dans la fiche.\n"
            "• Pour que Scrinium puisse taper dans Konsole : Konsole > Configuration > Configurer Konsole > Général > cocher « Enable the "
            "security sensitive parts of the DBus API ». Sinon, le texte est seulement copié dans le presse-papiers : collez-le avec "
            "Ctrl+Maj+V. (Cette option est désactivée par défaut car elle permet à un programme d'envoyer du texte à vos terminaux : "
            "c'est votre choix.)\n"
            "• Extensions > « Exécuter une commande et insérer la sortie… » : le contraire, la commande est lancée après confirmation "
            "et sa sortie est insérée dans la fiche, au curseur.\n"
            "• Depuis un terminal : « ls -al | scrinium ajouter -t Thème -f Fiche » ajoute la sortie à une fiche.")),
        (_("Guide 6 · Verrouillage, secours et partage"), _(
            "• Verrouiller : bouton « Verrouiller… ». Le titre reste visible, le contenu est chiffré. Mot de passe oublié = fiche perdue, "
            "sauf avec le FICHIER DE SECOURS (menu Sécurité > Fichier de secours…) : faites-le dès le premier verrouillage, gardez-le "
            "hors de cet ordinateur.\n"
            "• Une fiche verrouillée n'est jamais envoyée, lue, traduite ni partagée tant qu'elle est fermée.\n"
            "• Partage : l'extension Partage synchronise des fiches avec un serveur Scrinium. Une invitation par courriel (valable 48 h) "
            "donne un accès en lecture ou en écriture ; en cas de conflit, les deux versions sont gardées.\n"
            "• Inviter quelqu'un à INSTALLER Scrinium : menu Fichier > « Inviter à installer Scrinium… ».")),
        (_("Guide 7 · Où sont mes données, sauvegarde"), _(
            "• Vos fiches : un dossier par thème, un fichier .md par fiche (.lock si verrouillée), avec un sous-dossier .pj pour les images "
            "jointes :\n"
            "\n"
            "    %s\n"
            "\n"
            "• Sauvegarder : copiez ce dossier, et votre fichier de secours à part. Restaurer : remettez-le en place, Scrinium fermé.\n"
            "• Scrinium ne recharge pas les fiches modifiées pendant qu'il tourne : fermez-le avant de changer des fichiers à la main.\n"
            "• Aucune télémétrie. Logiciel libre (GPL-3.0-or-later) : le code est sur github.com/jfkneib/scrinium.") % dossier_fiches),
    ]


def fiches_extensions(docs) -> list:
    """[(titre, texte)] à la suite du guide : la documentation que chaque extension ACTIVE a déclarée (`ctx.ajouter_doc`)."""
    return [(f"{_('Guide')} · {titre}", texte) for titre, texte in docs]
