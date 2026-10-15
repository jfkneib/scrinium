# TODO Scrinium

Légende : ☐ à faire · ◐ en cours · ✔ fait. Ordre = priorité proposée.

## 0. Avant de publier
- ☐ Créer le dépôt `jfkneib/scrinium` sur GitHub (vide), pousser (`git remote add origin git@github.com:jfkneib/scrinium.git`)
- ☐ Release `v0.1.0` avec le `.deb` en pièce jointe (GitHub Actions : build du `.deb` à chaque tag)
- ☐ Tester `install.sh` sur `debian13-test` (revenir au snapshot `propre` avant) et sur Ubuntu 24.04/26.04
- ☐ Capture d'écran dans le README
- ☐ Page `man scrinium`

## 1. Images dans les fiches (v0.2)
Une fiche peut contenir une ou plusieurs images, en plus du texte ou à sa place.
- ☐ Format : une fiche = `titre.md` + dossier `titre.pj/` (pièces jointes) ; le `.md` référence les images (`![](titre.pj/1.png)`)
- ☐ **Fiches verrouillées** : les images doivent être chiffrées aussi (même clé, AES-GCM). Nouveau format `.lock` v3 (conteneur : texte + pièces jointes), l'ancien format reste lisible. À spécifier AVANT de coder (tests de compatibilité).
- ☐ Coller une image depuis le presse-papiers (Ctrl+V), glisser-déposer, bouton « Ajouter une image »
- ☐ Affichage dans l'éditeur (vignette cliquable, plein écran), suppression, export
- ☐ Redimensionnement/compression à l'import (limiter le poids du dossier de données)
- ☐ Corbeille : les pièces jointes suivent la fiche

## 2. Rappels et petit calendrier (v0.3)
Ne pas faire un agenda complet : des **fiches avec une date**.
- ☐ Date/heure facultative sur une fiche (ligne en tête du `.md`, ex. `@rappel: 2026-11-03 09:00`)
- ☐ Alarme simple : notification du bureau à l'heure (zone de notification déjà là, lancement automatique déjà là) ; répétition simple (quotidien, hebdo, mensuel, annuel pour les anniversaires)
- ☐ Fiche verrouillée avec rappel : seul le **titre** (déjà visible) est affiché dans la notification, jamais le contenu
- ☐ Petit calendrier (QCalendarWidget) : jours avec fiches/rappels en gras, clic = liste du jour
- ☐ « Repousser de 10 min » / « Fait »
- ☐ Rappels manqués (PC éteint) : les afficher au démarrage
- ☐ Import des anniversaires du thème « Anniversaires » (idée)

## 3. OCR optionnel (v0.4)
Extraire le texte d'une image de fiche pour pouvoir la chercher/copier.
- ☐ Moteur 1 (par défaut, léger) : **Tesseract** (`apt install tesseract-ocr tesseract-ocr-fra`), rien à télécharger de plus
- ☐ Moteur 2 (facultatif, « OCR intelligent ») : modèle vision local via **Ollama** (ex. `qwen2.5vl:3b`, 3,2 Go) par l'API `http://127.0.0.1:11434`
  - réglages : activer, adresse, nom du modèle ; test de connexion
  - **local uniquement** par défaut : refuser une adresse distante sans avertissement explicite (les images peuvent être privées)
  - ne jamais envoyer le contenu d'une fiche verrouillée sans demande explicite de l'utilisateur
  - penser au partage de la VRAM (8 Go) avec ComfyUI/autres modèles (`OLLAMA_KEEP_ALIVE`, un seul modèle chargé)
- ☐ Texte extrait stocké avec la fiche (et **chiffré** si la fiche est verrouillée), indexé par la recherche (sauf fiches verrouillées fermées)
- ☐ Bouton « Extraire le texte » sur une image, résultat modifiable avant enregistrement

## 4. Multi-plateforme
- ☐ Builds Windows (PyInstaller + Inno Setup) et macOS (`.dmg`) par GitHub Actions
- ☐ Vérifier sous Windows et macOS : lancement automatique, zone de notification, droits des fichiers (chmod sans effet sous Windows)
- ☐ Flatpak (en dernier : le sandbox complique le fichier de secours et l'accès à Ollama)
- ☐ Android : réécriture à part, lecture du même format ; nécessite la synchronisation (Syncthing/Nextcloud), voir plus bas

## 5. Améliorations diverses
- ☐ Sources du code en anglais (aujourd'hui en français, `po/en.po` traduit du français)
- ☐ Autres langues (de, es, it…)
- ☐ Synchronisation entre machines (dossier partagé : verrous de fichiers, conflits)
- ☐ Export/import (zip, Markdown)
- ☐ Thèmes : couleur par thème, tri personnalisé
- ☐ Migration de l'outil perso `~/scripts/aide-memoire/` vers Scrinium (clé root commune → `recovery.pub`, tuiles dashboard via le hook `themes-changed`)
- ☐ Verrouillage automatique après X minutes d'inactivité

## Fait
- ✔ Cœur indépendant de l'interface, interface Qt, fiches verrouillables (AES-256-GCM)
- ✔ Fichier de secours par utilisateur, proposé au premier verrouillage
- ✔ Thème « Bienvenue » + thèmes modèles au premier lancement
- ✔ Zone de notification, instance unique, lancement au démarrage, reverrouillage en se cachant
- ✔ Français / anglais (gettext)
- ✔ `install.sh`, paquet `.deb`, README FR/EN
