# TODO Scrinium

Légende : ☐ à faire · ◐ en cours · ✔ fait. Ordre = priorité proposée.

## 0. Avant de publier
- ✔ Dépôt `jfkneib/scrinium` créé et poussé
- ✔ Release `v0.1.0` publiée avec le `.deb` et `SHA256SUMS`
- ☐ GitHub Actions : construire le `.deb` et publier la release automatiquement à chaque tag
- ✔ `.deb` et `install.sh` testés sur Debian 13 (VM neuve) ; `.deb` installé sur Ubuntu 26.04 (2 machines)
- ☐ Tester sur Ubuntu 24.04 LTS et Debian 12
- ☐ Capture d'écran dans le README
- ✔ Page `man scrinium`

## 0 bis. Système de plugins (avant les images, v0.2)
Le cœur reste petit ; calendrier/alarmes et OCR sont des plugins. Les **pièces jointes** (images) restent dans le cœur :
leur stockage et leur chiffrement avec la fiche font partie du format de fichier, un plugin ne doit pas pouvoir l'affaiblir.
- ✔ Implémenté : API v1, découverte sans exécution de code, activation explicite, événements, isolation des pannes, menu *Extensions*, `docs/plugins.md`, plugin `hello`
- ☐ API v1 versionnée (`API_VERSION`) : un plugin déclare la version qu'il vise, refus propre si incompatible
- ☐ Découverte : *entry points* Python (`scrinium.plugins`, pour les paquets pip/deb comme `scrinium-ocr`) + dossier utilisateur `~/.config/scrinium/plugins/`
- ☐ Cycle de vie : `activer(ctx)` / `desactiver()` ; un plugin est **désactivé par défaut** tant que l'utilisateur ne l'a pas activé (menu *Fichier → Extensions…* : liste, version, auteur, activer/désactiver)
- ☐ Contexte donné au plugin (`ctx`) :
  - lecture/écriture des fiches **ouvertes** (jamais la clé de chiffrement, jamais une fiche verrouillée fermée)
  - signaux : fiche ouverte/enregistrée/fermée, thème modifié, fenêtre cachée, démarrage/arrêt
  - UI : ajouter une action de menu, un bouton de barre d'outils, un panneau latéral, une page de réglages, une notification de la zone de notification
  - planificateur (minuteries) et stockage de réglages par plugin (`settings.json`, clé au nom du plugin)
  - **métadonnées de fiche** (clé/valeur, ex. `rappel`) stockées en tête du `.md` ; fiche verrouillée : métadonnées non sensibles en clair, le reste chiffré (à décider : une date de rappel en clair est-elle acceptable ?)
- ☐ Isolation des pannes : toute exception d'un plugin est interceptée et journalisée ; après N erreurs le plugin est désactivé, l'application continue
- ☐ Sécurité : un plugin est du code arbitraire avec accès aux fiches ouvertes → avertissement clair à l'activation, plugins tiers jamais chargés sans accord, permissions déclarées affichées
- ☐ Documentation `docs/plugins.md` + plugin d'exemple (`hello`) + tests (chargement, version incompatible, plugin qui plante)
- ☐ Les plugins officiels vivent dans `plugins/` du dépôt et sont publiés en paquets séparés (`scrinium-rappels`, `scrinium-ocr`)

## 1. Images dans les fiches (v0.2, dans le cœur)
Une fiche peut contenir une ou plusieurs images, en plus du texte ou à sa place.
- ◐ **Spécification validée : `docs/format-pieces-jointes.md`** ; ✔ cœur fait (AMLOCK3, `Store.ajouter_piece`/`lister_pieces`/`lire_piece`/`maj_piece`/`supprimer_piece`, verrouillage et reprise après interruption, 19 tests) ; ✔ import d'image (`ui/images.py` : réencodage, métadonnées supprimées, 2560 px, 8 Mo) et interface (bande de vignettes, Ctrl+V, glisser-déposer, bouton, visionneuse, enregistrer sous, copier, supprimer) ; ✔ `scrinium rescue list/open --images/unlock` pour les pièces, recherche dans le texte OCR (fiches en clair ou ouvertes), API des extensions (`ctx.pieces/lire_piece/maj_piece`, 3 événements) ; ☐ traductions anglaises des nouveaux textes pour les pièces, recherche, API des extensions. Option B retenue (vignettes sous la fiche, texte simple). La fiche `.md`/`.lock` ne change pas ; pièces dans `titre.pj/`, verrouillées en `AMLOCK3` (affine la ligne « `.lock` v3 » ci-dessous)
- ☐ Format : une fiche = `titre.md` + dossier `titre.pj/` (pièces jointes) ; (le `.md` ne référence plus les images : option B)
- ☐ **Fiches verrouillées** : les images doivent être chiffrées aussi (même clé, AES-GCM). Nouveau format `.lock` v3 (conteneur : texte + pièces jointes), l'ancien format reste lisible. À spécifier AVANT de coder (tests de compatibilité).
- ☐ Coller une image depuis le presse-papiers (Ctrl+V), glisser-déposer, bouton « Ajouter une image »
- ☐ Affichage dans l'éditeur (vignette cliquable, plein écran), suppression, export
- ✔ Recadrage dans la visionneuse (rectangle à la souris ; « nouvelle image » ou « remplacer l'originale », l'ancienne version va à la corbeille, texte OCR effacé) · ☐ rotation, annotation
- ☐ Redimensionnement/compression à l'import (limiter le poids du dossier de données)
- ☐ Corbeille : les pièces jointes suivent la fiche

## 2. Plugin `scrinium-rappels` : rappels et petit calendrier (v0.3)
Ne pas faire un agenda complet : des **fiches avec une date**. Repose sur l'API plugins (métadonnées, planificateur, notifications).
- ☐ Date/heure facultative sur une fiche (ligne en tête du `.md`, ex. `@rappel: 2026-11-03 09:00`)
- ☐ Alarme simple : notification du bureau à l'heure (zone de notification déjà là, lancement automatique déjà là) ; répétition simple (quotidien, hebdo, mensuel, annuel pour les anniversaires)
- ☐ Fiche verrouillée avec rappel : seul le **titre** (déjà visible) est affiché dans la notification, jamais le contenu
- ☐ Petit calendrier (QCalendarWidget) : jours avec fiches/rappels en gras, clic = liste du jour
- ☐ « Repousser de 10 min » / « Fait »
- ☐ Rappels manqués (PC éteint) : les afficher au démarrage
- ☐ Import des anniversaires du thème « Anniversaires » (idée)

## 3. Plugin `scrinium-ocr` : OCR optionnel (v0.4)
✔ Première version dans `plugins/ocr/` (Tesseract seul, testée de bout en bout, 10 tests) : menu *Extensions* (extraire le texte des images de la fiche, voir/corriger le texte, réglages : chemin, langue `fra`, automatique à l'ajout). Image donnée à Tesseract sur son entrée standard (jamais de fichier temporaire, même pour une fiche verrouillée ouverte). Reste : clic droit sur une vignette (point d'accroche à ajouter à l'API), moteur Ollama facultatif, essai réel sur photos et captures floues, macOS/Windows.
Extraire le texte d'une image de fiche pour pouvoir la chercher/copier. Moteurs eux-mêmes enfichables (Tesseract, Ollama).
- ☐ Moteur 1 (par défaut, léger) : **Tesseract** (`apt install tesseract-ocr tesseract-ocr-fra`), rien à télécharger de plus
- ☐ Moteur 2 (facultatif, « OCR intelligent ») : modèle vision local via **Ollama** (ex. `qwen2.5vl:3b`, 3,2 Go) par l'API `http://127.0.0.1:11434`
  - réglages : activer, adresse, nom du modèle ; test de connexion
  - **local uniquement** par défaut : refuser une adresse distante sans avertissement explicite (les images peuvent être privées)
  - ne jamais envoyer le contenu d'une fiche verrouillée sans demande explicite de l'utilisateur
  - penser au partage de la mémoire graphique avec d'autres modèles (`OLLAMA_KEEP_ALIVE`, un seul modèle chargé à la fois)
- ☐ Texte extrait stocké avec la fiche (et **chiffré** si la fiche est verrouillée), indexé par la recherche (sauf fiches verrouillées fermées)
- ☐ Bouton « Extraire le texte » sur une image, résultat modifiable avant enregistrement

## 3 bis. Plugin `scrinium-dictee` : dictée vocale (v0.5)
✔ Première version dans `plugins/dictee/`, testée de bout en bout sur l'Inspiron (installation, modèle `small`, micro, insertion) : demande d'accord à l'activation pour installer `faster-whisper` (pip --target dans `ctx.dossier_donnees`), modèle téléchargé à la 1re dictée après accord, micro via parecord/pw-record/arecord, Ctrl+Alt+D, réglages modèle/langue. Reste : appui-pour-parler, ponctuation, mode « remplacer la sélection », paquet séparé.
Dicter une note au micro, le texte s'insère à la position du curseur (`ctx.ui.inserer_texte`, déjà dans l'API).
- ☐ Reconnaissance **locale** (aucun envoi sur Internet) : `faster-whisper` (modèles `base`/`small`, bon en français, CPU suffisant, GPU facultatif) ; alternative légère : Vosk. Ollama n'est pas l'outil pour la parole.
- ☐ Enregistrement micro (QtMultimedia ou `sounddevice`), bouton « Dicter » + raccourci appui-pour-parler, indicateur d'écoute
- ☐ Téléchargement du modèle **à la demande** (taille affichée, accord de l'utilisateur), stocké dans les données du plugin
- ☐ Choix de la langue (auto / fr / en), ponctuation, mode « ajouter » / « remplacer la sélection »
- ☐ Dépendances Python propres au plugin (`pip` dans le venv de `install.sh`) : à documenter, pas de paquet Debian officiel pour faster-whisper
- ☐ Option gratuite en attendant : la dictée du système (KDE/GNOME, Windows `Win+H`, macOS)

## 3 bis-b. Plugin `courriel` : envoi d'une fiche par courriel
✔ Première version dans `plugins/courriel/` (testée en vrai avec un compte Free ; Gmail exige un mot de passe d'application) : bouton + menu *Envoyer par courriel*, carnet d'adresses, choix multiple des destinataires + adresses libres, formulaire serveur SMTP (STARTTLS/SSL, test de connexion), récapitulatif avant envoi. Fiche verrouillée fermée : jamais envoyée ; ouverte : avertissement (part en clair). Mot de passe : trousseau (`keyring`) si présent, sinon session, ou fichier 0600 sur demande.
- ☐ Pièces jointes (fichier `.md`, images quand elles existeront) · ☐ plusieurs comptes d'envoi · ☐ groupes de contacts · ☐ import du carnet (vCard/CSV) · ☐ envoi chiffré de bout en bout (PGP) pour les fiches verrouillées

## 3 ter. Plugin `scrinium-capture` : résultat d'une commande dans une fiche
Envoyer la sortie d'une commande shell dans une fiche (notes d'administration : `df -h`, config réseau, etc.).
- ☐ En ligne de commande, par un tube : `ip a | scrinium ajouter --theme Informatique --fiche "Réseau"` (Scrinium ne lance rien : il reçoit le texte sur l'entrée standard)
- ☐ L'instance déjà ouverte reçoit le texte par le canal d'instance unique (sinon écriture directe dans les fichiers) ; fiche créée si elle n'existe pas, sinon ajout à la fin (option `--remplacer`)
- ☐ Bloc encadré avec la date et la commande (` ```bash ` ... ` ``` `), pour garder le contexte ; option `--brut`
- ☐ Dans la fenêtre : bouton « Exécuter une commande… » → affiche la sortie, puis l'insère à la position du curseur (`ctx.ui.inserer_texte`) ; **la commande est lancée uniquement sur demande explicite de l'utilisateur**, avec délai maximum et taille de sortie limitée
- ☐ Fiche **verrouillée** : refuser l'ajout sans déverrouillage (jamais d'écriture en clair), ou demander le mot de passe ; ne jamais passer un mot de passe en argument
- ☐ Option : lancer la commande sur une machine distante (`ssh machine commande`), en réutilisant la config SSH de l'utilisateur (à étudier : prudence)
- ☐ Nécessite dans l'API : `ctx.ajouter_commande_cli(nom, fn)` (sous-commandes ajoutées par les plugins) et réception de texte par l'instance unique

## 3 quater. Partage de fiches et synchronisation (à prévoir tôt : touche au cœur)
Partager des fiches entre machines et/ou personnes : dépôt sur le réseau local (SMB/NFS/dossier partagé), cloud (Nextcloud/WebDAV, Syncthing, Dropbox…) ou dépôt git.
- ☐ **Plusieurs dépôts de fiches** : aujourd'hui `Store` a un seul dossier racine. Prévoir une liste de « dépôts » (personnel + partagés), chacun avec son dossier, ses thèmes, son éventuel fichier de secours (`recovery.pub` par dépôt, pas global). À concevoir AVANT la v0.2 pour ne pas casser le format.
- ☐ Un thème (ou un dépôt) peut être **partagé** : indicateur dans la liste, réglage « dossier partagé » (chemin local d'un montage réseau, ou dossier synchronisé)
- ☐ Les fiches verrouillées (`.lock`) se synchronisent sans risque (chiffrées) ; les fiches en clair le sont **en clair** → avertissement clair à l'activation du partage, et proposition de verrouiller
- ☐ Sûreté des écritures partagées : écriture atomique (déjà en place), détection de modification externe (mtime/taille, surveillance de dossier), **conflits** : ne jamais écraser en silence (copie « fiche (conflit <machine>) », comparaison simple)
- ☐ Rechargement automatique quand un fichier change sur le disque (outil de synchro externe ou autre machine)
- ☐ Plusieurs utilisateurs sur un dépôt LAN : qui a modifié quoi (métadonnée `modifie_par`), droits laissés au système de fichiers ; clé de secours par utilisateur : une fiche verrouillée par A n'est pas rouvrable par B
- ☐ Plugins de transport (API) : `scrinium-sync-webdav` (Nextcloud), `scrinium-sync-git`, `scrinium-sync-lan` ; le cœur ne connaît que des dossiers
- ☐ Option d'inclure/exclure par thème, et état de synchro visible (en cours, à jour, conflit)
- ☐ Tests : deux instances sur le même dossier, modification simultanée, coupure réseau pendant l'écriture

## 4. Multi-plateforme
- ☐ Builds Windows (PyInstaller + Inno Setup) et macOS (`.dmg`) par GitHub Actions
- ☐ Vérifier sous Windows et macOS : lancement automatique, zone de notification, droits des fichiers (chmod sans effet sous Windows)
- ☐ Flatpak (en dernier : le sandbox complique le fichier de secours et l'accès à Ollama)
- ☐ Android : réécriture à part, lecture du même format ; nécessite la synchronisation (Syncthing/Nextcloud), voir plus bas

## 5. Améliorations diverses
- ☐ Sources du code en anglais (aujourd'hui en français, `po/en.po` traduit du français)
- ☐ Autres langues (de, es, it…)
- ☐ Export/import (zip, Markdown)
- ☐ Thèmes : couleur par thème, tri personnalisé
- ☐ Verrouillage automatique après X minutes d'inactivité

## Fait
- ✔ Cœur indépendant de l'interface, interface Qt, fiches verrouillables (AES-256-GCM)
- ✔ Fichier de secours par utilisateur, proposé au premier verrouillage
- ✔ Thème « Bienvenue » + thèmes modèles au premier lancement
- ✔ Zone de notification, instance unique, lancement au démarrage, reverrouillage en se cachant
- ✔ Français / anglais (gettext)
- ✔ `install.sh`, paquet `.deb`, README FR/EN
- ✔ `TODO.md` (ce fichier)
