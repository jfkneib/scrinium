# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Thèmes et fiches proposés au premier lancement : de quoi comprendre l'outil en l'utilisant."""
from ..i18n import _
from . import doc_extensions

MOT_DE_PASSE_DEMO = "scrinium"

# (nom du thème, icône, [(titre, texte)]). Les textes sont des modèles à compléter : aucune donnée personnelle.
def themes(dossier_fiches) -> list:
    return [
        (_("Bienvenue"), "help-about", [
            (_("1 · Bienvenue dans Scrinium"), _(
                "Scrinium range vos petites notes : numéros, codes, procédures, listes…\n\n"
                "Trois colonnes :\n"
                "  • à gauche, les THÈMES (les tiroirs) ;\n"
                "  • au milieu, les FICHES du thème choisi ;\n"
                "  • à droite, le contenu de la fiche : un titre et une note.\n\n"
                "Tout s'enregistre tout seul pendant que vous écrivez : il n'y a pas de bouton « Enregistrer ».\n\n"
                "Ces fiches de bienvenue sont là pour apprendre. Lisez-les dans l'ordre, puis supprimez le thème "
                "« Bienvenue » quand vous n'en avez plus besoin (clic droit sur le thème, « Supprimer » : il va à la "
                "corbeille, rien n'est perdu).")),
            (_("2 · Créer, modifier, ranger"), _(
                "  • Nouvelle fiche : bouton « Fiche » en haut, ou Ctrl+N. Tapez le titre, puis la note.\n"
                "  • Nouveau thème : bouton « Thème ».\n"
                "  • Renommer un thème, changer son icône, le supprimer : clic droit sur le thème, ou les trois petits "
                "boutons sous la liste des thèmes.\n"
                "  • Supprimer une fiche : bouton « Supprimer la fiche ». Elle va à la corbeille, elle n'est pas détruite.\n"
                "  • Une fiche laissée entièrement vide disparaît d'elle-même.\n\n"
                "Essayez : cliquez sur « Fiche », donnez-lui un titre, écrivez quelques mots.")),
            (_("3 · Chercher et copier"), _(
                "  • Ctrl+F : la recherche regarde dans les titres, les notes et les noms de thèmes, tous thèmes confondus.\n"
                "  • « Copier la note » met tout le texte dans le presse-papiers, prêt à coller ailleurs "
                "(un numéro, une adresse…).\n"
                "  • Le thème « ★ Toutes les fiches » montre tout d'un coup.")),
            (_("4 · Verrouiller une fiche"), _(
                "Pour une information sensible (code, mot de passe, numéro de carte…), cliquez sur « Verrouiller… » : "
                "le texte est chiffré (AES-256) avec un mot de passe que vous choisissez. Le titre reste visible, "
                "le contenu non.\n\n"
                "Essayez : la fiche « Exemple verrouillé » de ce thème a pour mot de passe : %s\n\n"
                "Filet de sécurité : si vous oubliez le mot de passe d'une fiche, elle est perdue, sauf si vous avez un "
                "FICHIER DE SECOURS. Scrinium vous le propose au premier verrouillage (ou plus tard : menu Sécurité > "
                "Fichier de secours…). Donnez-lui un nom que vous reconnaîtrez et gardez-le hors de cet ordinateur "
                "(clé USB, gestionnaire de mots de passe).") % MOT_DE_PASSE_DEMO),
            (_("5 · Où sont mes fiches ?"), _(
                "Chaque fiche est un simple fichier texte (.md) et chaque thème un dossier :\n\n    %s\n\n"
                "Vous pouvez les lire avec n'importe quel éditeur de texte. Pour les sauvegarder, copiez ce dossier. "
                "Les fiches verrouillées sont des fichiers .lock, illisibles sans leur mot de passe.") % dossier_fiches),
                    (_("6 · Inviter quelqu'un"), _(
                "Pour faire connaître Scrinium à quelqu'un : menu Fichier > « Inviter à installer Scrinium… ». Scrinium "
                "prépare une fiche (liens de téléchargement, installation selon le système, extensions) que vous pouvez "
                "relire et adapter, puis envoyer par courriel avec l'extension Courriel (menu Extensions > Gérer les "
                "extensions…).")),
        ]),
        (_("Perso"), "emblem-favorite", [
            (_("Numéros d'urgence"), _(
                "Europe : 112 (urgences)\n"
                "France : 15 SAMU · 17 police · 18 pompiers · 114 urgences par SMS (sourds et malentendants) · "
                "3114 prévention du suicide\n\n"
                "À compléter : médecin traitant, pharmacie de garde, personne à prévenir…")),
            (_("Anniversaires"), _("Prénom — date — idée de cadeau\n\n")),
            (_("Cartes, mutuelle, assurances"), _(
                "Mutuelle : n° d'adhérent …\nAssurance habitation : contrat n° … / téléphone sinistres …\n"
                "Carte vitale : …\n\nAstuce : pour des numéros sensibles, cliquez sur « Verrouiller… ».")),
        ]),
        (_("Maison"), "user-home", [
            (_("Wifi de la maison"), _(
                "Nom du réseau (SSID) : \nMot de passe : \n\n"
                "Astuce : cette fiche est une bonne candidate au verrouillage.")),
            (_("Artisans et dépannage"), _(
                "Plombier : nom — téléphone\nÉlectricien : …\nChauffagiste : …\nMaintenance chaudière : …")),
            (_("Entretien de la maison"), _(
                "Chaudière : dernier entretien le …\nRamonage : …\nPiles des détecteurs de fumée : …")),
        ]),
        (_("Informatique"), "network-wired", [
            (_("Mon réseau"), _(
                "Box / routeur : adresse …\nAdresse de l'imprimante : …\nNom des ordinateurs : …")),
            (_("Mes comptes : où j'ai quoi"), _(
                "Messagerie : …\nBanque en ligne : …\nCloud : …\n\n"
                "Notez ici OÙ se trouvent vos comptes, pas leurs mots de passe en clair. "
                "Pour un mot de passe, verrouillez la fiche.")),
        ]),
        (doc_extensions.nom_theme(), doc_extensions.icone(), doc_extensions.fiches(dossier_fiches.parent / "plugins")),
        (_("Voyages"), "applications-internet", [
            (_("Check-list valise"), _(
                "☐ Papiers d'identité / passeport\n☐ Billets, réservations\n☐ Carte bancaire, un peu d'espèces\n"
                "☐ Médicaments, ordonnance\n☐ Chargeurs, adaptateur de prise\n☐ Vêtements, trousse de toilette")),
            (_("Documents à emporter"), _(
                "Assurance voyage : n° de contrat …\nAssistance (numéro à appeler) : …\nAdresse de l'hébergement : …")),
        ]),
    ]
