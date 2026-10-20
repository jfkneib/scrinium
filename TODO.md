# TODO Scrinium

Légende : ☐ à faire · ◐ en cours · ✔ fait. Ordre = priorité proposée.

## 0. Avant de publier
- ✔ Dépôt `jfkneib/scrinium` créé et poussé
- ✔ Release `v0.1.0` publiée avec le `.deb` et `SHA256SUMS`
- ☐ GitHub Actions : construire le `.deb` et publier la release automatiquement à chaque tag
- ✔ `.deb` et `install.sh` testés sur Debian 13 (VM neuve) ; `.deb` installé sur Ubuntu 26.04 (2 machines)
- ☐ Tester sur Ubuntu 24.04 LTS et Debian 12
- ☐ Capture d'écran dans le README
- ✔ Page `man scrinium` · ☐ à compléter : sous-commande `ajouter`, option `rescue open --images`
- ☐ README (FR/EN) : la section « Extensions » dit encore que rappels/OCR/dictée sont « prévus » ; documenter images, OCR, dictée, courriel, capture, `scrinium ajouter`, workflow `dev` → `main`
- ☐ Livrer les 4 plugins (`dictee`, `courriel`, `ocr`, `capture`) dans le `.deb` (dossier d'exemples) : aujourd'hui `plugins/` n'est qu'une copie à faire à la main
- ☐ Traductions anglaises (`po/en.po`) des textes ajoutés : images, OCR, dictée, courriel, capture (les plugins affichent le français si la traduction manque)

## 0 bis. Système de plugins (avant les images, v0.2)
Le cœur reste petit ; calendrier/alarmes et OCR sont des plugins. Les **pièces jointes** (images) restent dans le cœur :
leur stockage et leur chiffrement avec la fiche font partie du format de fichier, un plugin ne doit pas pouvoir l'affaiblir.
- ✔ **Fait et testé** (`core/plugins.py`, `tests/test_plugins.py`, `docs/plugins.md`, exemple `plugins/hello`) : API versionnée (`API_VERSION`, refus propre d'une extension d'une autre version), découverte sans exécuter de code (dossier utilisateur + *entry points* `scrinium.plugins`), désactivées par défaut avec avertissement à l'activation, cycle de vie `activer(ctx)` / `desactiver()`, isolation des pannes (désactivation après 5 erreurs), réglages par extension, métadonnées de fiche, minuteries, UI (action de menu, bouton de barre, panneau, notification), événements (dont `piece_jointe_*`), `ctx.dossier_donnees`, `ctx.pieces/lire_piece/maj_piece`
- ☐ **Permissions déclarées et affichées** à l'activation (aujourd'hui : seulement l'avertissement général « code arbitraire »)
- ☐ **Métadonnées d'une fiche verrouillée** : décision prise = tout est chiffré avec le texte (rien en clair) ; à revoir pour les rappels (une fiche verrouillée fermée n'a pas de date lisible)
- ☐ Page de réglages commune aux extensions (chacune ouvre aujourd'hui ses propres fenêtres)
- ☐ Point d'accroche pour le menu clic droit des vignettes (OCR « Extraire le texte »)
- ☐ Publier les plugins en paquets séparés (`scrinium-rappels`, `scrinium-ocr`…) : décision à prendre, ou les embarquer tous dans le `.deb`
- ➜ Abandonné : `ctx.ajouter_commande_cli` (sous-commandes ajoutées par les plugins) : `scrinium ajouter` vit dans le cœur

## 1. Images dans les fiches (v0.2, dans le cœur)
Une fiche peut contenir une ou plusieurs images, en plus du texte ou à sa place.
- ✔ **Fait et testé** (spécification : `docs/format-pieces-jointes.md`, option B : vignettes sous la fiche, texte simple) :
  - cœur : `titre.md`/`titre.lock` inchangés, pièces dans `titre.pj/`, `AMLOCK3` pour les fiches verrouillées (même clé, clé de secours incluse), reprise après interruption, `Store.ajouter/lister/lire/maj/remplacer/supprimer_piece` (`tests/test_pieces.py`)
  - import : réencodage PNG/JPEG, métadonnées supprimées (EXIF, commentaires PNG), 2560 px, 8 Mo, 50 pièces / 100 Mo par fiche
  - interface : Ctrl+V, glisser-déposer, bouton « Ajouter une image », bande de vignettes, visionneuse, enregistrer sous, copier, supprimer (corbeille), **recadrage** (nouvelle image ou remplacement, ancienne version à la corbeille)
  - fiche verrouillée : images chiffrées, bande cachée tant qu'elle est fermée ; renommer / supprimer la fiche : les `.pj` suivent (corbeille avec même horodatage)
  - `scrinium rescue list/open --images/unlock` pour les pièces ; recherche dans le texte OCR (fiches en clair ou ouvertes)
- ☐ Traductions anglaises (voir section 0) · ☐ rotation, annotation de l'image · ☐ option de réglage des limites (2560 px, 8 Mo…) dans `settings.json` (clé `pieces_jointes`, prévue dans la spécification)
- ☐ Essai réel avec une vraie photo JPEG avec EXIF (test automatique limité aux commentaires PNG) · ☐ tests sous Windows/macOS (noms de fichiers, titres ne différant que par la casse)

## 2. Plugin `rappels` : rappels et petit calendrier (pas commencé)
Ne pas faire un agenda complet : des **fiches avec une date**. Repose sur l'API plugins (métadonnées, planificateur, notifications).
- ☐ Date/heure facultative sur une fiche (ligne en tête du `.md`, ex. `@rappel: 2026-11-03 09:00`)
- ☐ Alarme simple : notification du bureau à l'heure (zone de notification déjà là, lancement automatique déjà là) ; répétition simple (quotidien, hebdo, mensuel, annuel pour les anniversaires)
- ☐ Fiche verrouillée avec rappel : seul le **titre** (déjà visible) est affiché dans la notification, jamais le contenu
- ☐ Petit calendrier (QCalendarWidget) : jours avec fiches/rappels en gras, clic = liste du jour
- ☐ « Repousser de 10 min » / « Fait »
- ☐ Rappels manqués (PC éteint) : les afficher au démarrage
- ☐ Import des anniversaires du thème « Anniversaires » (idée)

## 3. Plugin `ocr` : texte des images (fait ; reste : Ollama, clic droit)
✔ **Fait et testé** (`plugins/ocr/`, `tests/test_ocr.py`, essai réel avec Tesseract 5.5 et `fra`) : menu *Extensions* (extraire le texte des images de la fiche, voir/corriger le texte, réglages : chemin, langue, automatique à l'ajout). Image donnée à Tesseract sur son entrée standard (aucun fichier temporaire, même pour une fiche verrouillée ouverte) ; texte enregistré avec l'image (chiffré si la fiche est verrouillée) et cherché par la recherche.
- ☐ Clic droit « Extraire le texte » sur une vignette (point d'accroche à ajouter à l'API)
- ☐ Moteur 2 facultatif (« OCR intelligent ») : modèle vision local via **Ollama** (ex. `qwen2.5vl:3b`, 3,2 Go) par `http://127.0.0.1:11434`
  - réglages : activer, adresse, nom du modèle ; test de connexion
  - **local uniquement** par défaut : refuser une adresse distante sans avertissement explicite (les images peuvent être privées)
  - ne jamais envoyer le contenu d'une fiche verrouillée sans demande explicite de l'utilisateur
  - penser au partage de la mémoire graphique avec d'autres modèles (`OLLAMA_KEEP_ALIVE`, un seul modèle chargé à la fois)
- ☐ Essai sur photos et captures floues ; plusieurs langues par image ; macOS/Windows (chemins usuels de `tesseract` prévus, non testés)

## 3 bis. Plugin `dictee` : dictée vocale (fait ; reste : appui-pour-parler…)
✔ **Fait et testé de bout en bout sur l'Inspiron** (`plugins/dictee/`) : reconnaissance locale `faster-whisper` (modèles `base`/`small`/`medium`, repli CPU si CUDA échoue), accord demandé avant d'installer le paquet (`pip --target` dans `ctx.dossier_donnees`) puis avant de télécharger le modèle (taille affichée), micro par `parecord`/`pw-record`/`arecord` (aucune bibliothèque audio), bouton enfoncé pendant l'enregistrement, Ctrl+Alt+D, langue auto/fr/en.
- ☐ Appui-pour-parler (aujourd'hui : un clic démarre, un clic arrête) · ☐ ponctuation · ☐ choix « ajouter » / « remplacer la sélection » (aujourd'hui le texte remplace la sélection)
- ☐ Documenter les dépendances Python propres au plugin (pas de paquet Debian officiel pour `faster-whisper`) et l'option du système en attendant (KDE/GNOME, Windows `Win+H`, macOS) · ☐ alternative légère Vosk · ☐ tests sous Windows/macOS (enregistreur audio à adapter)

## 3 bis-b. Plugin `courriel` : envoi d'une fiche par courriel
✔ Première version dans `plugins/courriel/` (testée en vrai avec un compte Free ; Gmail exige un mot de passe d'application) : bouton + menu *Envoyer par courriel*, carnet d'adresses, choix multiple des destinataires + adresses libres, formulaire serveur SMTP (STARTTLS/SSL, test de connexion), récapitulatif avant envoi. Fiche verrouillée fermée : jamais envoyée ; ouverte : avertissement (part en clair). Mot de passe : trousseau (`keyring`) si présent, sinon session, ou fichier 0600 sur demande.
- ☐ Joindre les images de la fiche (elles existent maintenant ; fiche en clair ou ouverte) · ☐ pièce jointe `.md` · ☐ plusieurs comptes d'envoi · ☐ groupes de contacts · ☐ import du carnet (vCard/CSV) · ☐ envoi chiffré de bout en bout (PGP) pour les fiches verrouillées

## 3 ter. Plugin `capture` et `scrinium ajouter` : commande ↔ fiche (fait ; reste : groupes, tmux…)
✔ **Fait et testé** :
- **Tube vers fiche, dans le cœur** (`core/capture.py`, `scrinium ajouter/add`, `tests/test_capture.py`) : `ip a | scrinium ajouter -t Thème -f Fiche [-c commande] [--remplacer] [--brut]` ; l'instance ouverte écrit elle-même (l'éditeur reste cohérent) par le canal d'instance (protocole `add`, réponse ok/err, socket réservée à l'utilisateur), sinon écriture directe ; fiche créée si absente ; bloc daté avec la commande entre barrières ; fiche verrouillée fermée refusée ; entrée vide refusée ; texte tronqué à 256 Ko. Chaque `SCRINIUM_HOME` a son propre canal d'instance (la version de test cohabite avec l'habituelle).
- **Plugin `plugins/capture/`** (`tests/test_capture_plugin.py`) :
  - « Exécuter une commande et insérer la sortie… » : jamais sans clic, délai 30 s, sortie limitée, bloc daté inséré au curseur
  - bouton « Console » : texte sélectionné tapé **sans valider** dans une Konsole (D-Bus ; caractères de contrôle retirés, collage « bracketed » si plusieurs lignes) ; l'extension ouvre **sa propre Konsole**, la réutilise, la rouvre si on la ferme ; « Choisir la console cible… » ; console mise **au premier plan** (script KWin, vérifié sur X11/KWin 6.6) ; repli presse-papiers
  - **panneau d'actions préparées** : boutons-icônes avec infobulle, 3 modes au clic (taper / exécuter après confirmation / copier), `{selection}` et `{fiche}` protégés pour le shell, éditeur, réordonnancement, exemples, export/import JSON ; interrupteur « Actions » dans la barre d'outils et le menu
- ⚠ Konsole désactive par défaut l'envoi de texte par D-Bus (option « Enable the security sensitive parts of the DBus API ») : le refus est reconnu et expliqué ; **l'envoi direct avec l'option activée n'a pas été testé** contre un vrai Konsole
- ☐ Groupes d'actions (onglets) · ☐ action « valider (Entrée) » explicite, action par action · ☐ clic droit sur une action
- ☐ **Portabilité** : l'envoi direct est Konsole/D-Bus (Linux/KDE) ; Windows et macOS = presse-papiers seulement ; adaptateurs possibles : tmux `send-keys` (le plus rentable : Linux, macOS, WSL), kitty `@ send-text`, WezTerm, iTerm2 (AppleScript) ; Windows Terminal : aucune API connue · ☐ autres terminaux Linux (gnome-terminal…) · ☐ le tube `scrinium ajouter` n'a été testé que sous Linux
- ☐ Option : lancer la commande sur une machine distante (`ssh machine commande`), en réutilisant la config SSH (à étudier : prudence)

## 3 quinquies. Plugin `traduction` : bouton « Traduire » (écrit le 2026-10-20 ; llama.cpp seul, essai réel fait ; Argos retiré)
Traduire la sélection (ou toute la fiche) ; fenêtre de résultat : **insérer sous le texte / remplacer / copier** ; langues mémorisées, détection de la langue source.
- Moteur 1 : **TranslateGemma 4B via llama.cpp** (`llama-server`), **sans Ollama** (choix de l'utilisateur). Test fait avec Ollama sur l'XPS : fr→en et en→fr corrects (paragraphes, accents, code entre accents graves conservés) ; 45 s au premier appel (chargement), 0,4 s ensuite.
  - prompt de TranslateGemma à fournir soi-même (le modèle de Ollama n'ajoute rien) : « You are a professional {SRC} ({code}) to {DST} ({code}) translator. Your goal is to accurately convey the meaning and nuances of the original {SRC} text while adhering to {DST} grammar, vocabulary, and cultural sensitivities. Produce only the {DST} translation, without any additional explanations or commentary. Please translate the following {SRC} text into {DST}: » puis deux lignes vides et le texte
  - gabarit de chat Gemma observé : `<start_of_turn>user\n…<end_of_turn>\n<start_of_turn>model\n` ; arrêt sur `<end_of_turn>` ; température 0 → privilégier `POST /completion` du serveur avec ce gabarit écrit à la main (à confirmer avec le vrai binaire)
  - le plugin lance `llama-server` à la demande (`--host 127.0.0.1`, port libre, `--api-key` aléatoire, `-m modèle.gguf`), le garde tant que Scrinium tourne ou jusqu'à inactivité, l'arrête proprement ; ou se connecte à un serveur déjà lancé (adresse dans les réglages)
  - **choix de l'installation laissé à l'utilisateur**, jamais automatique : le plugin montre les options par système et vérifie ensuite que le programme répond. ⚠ La page officielle propose `curl … | sh` / `irm … | iex` (script distant exécuté sans relecture) : à ne pas lancer depuis le plugin ; préférer les binaires de la page des versions (somme de contrôle) ou un gestionnaire de paquets
  - ⚠ à vérifier avec un vrai binaire : nom du programme (`llama-server` ou, dans le README récent, `llama serve` / `llama cli`), port par défaut, options exactes ; le plugin doit accepter les deux noms
  - modèle : fichier `.gguf` choisi par l'utilisateur (parcourir) ou téléchargé à la demande (taille affichée, accord). **Le fichier d'Ollama n'est PAS utilisable par llama.cpp : confirmé le 2026-10-20** avec `llama-server` b11669 : « error loading model hyperparameters: key not found in model: gemma3.attention.layer_norm_rms_epsilon » (fichier groupé texte + vision, métadonnées au format Ollama ; `/media/jfk/Ollama/MODEL_OLLAMA/blobs/sha256-bdbf…`). Réécrire une copie texte seul est écarté (métadonnées et conventions différentes : rabbit hole). Source retenue : GGUF fait pour llama.cpp, quantifié depuis les poids officiels de Google : `mradermacher/translategemma-4b-it-GGUF` (Q4_K_M 2,49 Go, Q5_K_M 2,83 Go, Q8_0 4,13 Go ; licence Gemma) ; le dépôt `anilb/translategemma-gguf` n'est qu'une recopie de ces mêmes fichiers. `llama-server -hf <dépôt>:<quant>` sait télécharger lui-même.
  - **Essai réel (XPS, 2026-10-20), modèle `translategemma-4b-it.Q4_K_M.gguf` (2,49 Go, SHA-256 vérifié) dans `~/.local/opt/llama.cpp/modeles/`** : chargé par `llama-server` Vulkan (`-ngl 99 -c 4096`) en 8 s ; 1re requête 17 s (préparation Vulkan), puis 0,3–0,4 s (~106 tok/s) ; en CPU seul (16 threads) : prêt en 4 s, ~10 tok/s, 3–5 s pour un court paragraphe, 4,4 Go de mémoire. L'Inspiron (i7-7500U, 2 cœurs/4 threads, 15 Go) sera nettement plus lent (non mesuré) : pour lui, Argos ou patience. **Conclusions : utiliser `POST /completion` avec le gabarit Gemma écrit à la main (sortie propre : mise en forme, listes, code conservés) ; ne PAS utiliser `/v1/chat/completions` (le gabarit du serveur fait répéter la consigne et ajoute du gras).** Le plugin doit prévoir le délai de la 1re requête (message « préparation… »).
  - installation de llama.cpp vérifiée à la main sur l'XPS : binaires `llama-b11669-bin-ubuntu-x64` (CPU, 18 Mo) et `…-ubuntu-vulkan-x64` (30 Mo, voit la RTX 3070) dans `~/.local/opt/llama.cpp/b11669/`, somme de contrôle SHA-256 vérifiée ; le programme s'appelle bien `llama-server`, port par défaut 9931, options `--host --port --api-key -m -ngl -c -hf --no-webui` présentes. Les binaires officiels sont dans les versions `bNNNNN` marquées « préversion » (la version « v0.7.0 » ne contient qu'un fichier `nightly-tag.txt` donnant le numéro de build `b11669`).
- Moteur 2 : **Argos Translate** (hors ligne, `pip --target` dans `ctx.dossier_donnees` après accord comme la dictée, CPU suffisant) ; **le modèle de la paire de langues est proposé quand il manque** (taille affichée, accord, stocké dans les données du plugin)
- Moteurs en ligne (DeepL…) : facultatifs, désactivés par défaut, avertissement explicite ; **jamais** de fiche verrouillée envoyée sans accord à chaque fois (les moteurs locaux : rien ne quitte la machine)
- ✔ **Plugin écrit et testé** (`plugins/traduction/`, `tests/test_traduction.py`, 74 tests dont 1 essai réel facultatif) : bouton « Traduire » + menu, fenêtre (texte modifiable, détection de la langue source, échange des langues, moteur au choix, progression, arrêt, résultat modifiable : **insérer sous le texte / remplacer / copier**), texte long découpé en morceaux, serveur `llama-server` lancé à la demande (127.0.0.1, port libre, clé aléatoire, arrêt après inactivité ou à la fermeture), serveur déjà lancé possible (non local : refusé sans case cochée, accord à chaque fois pour une fiche verrouillée), téléchargement du modèle avec accord + taille + provenance + SHA-256 + reprise, aide à l'installation de llama.cpp par système (aucun script distant), réglages, test de connexion. Nouvelle API de l'éditeur : `ctx.ui.texte_complet()`, `remplacer_tout()`, `ajouter_a_la_fin()`.
- ✔ **Essai réel** (XPS, CPU, `SCRINIUM_TEST_LLAMA=1 pytest -k vrai_llama`) : vrai `llama-server` b11669 + vrai modèle, traduction fr→en et en→fr correctes, code et listes conservés, 9 s.
- ✔ **Deux modèles au choix, assistant à la première activation** (2026-10-20) : « Rapide (4B) » 2,49 Go et « Meilleur (12B) » 7,30 Go (`mradermacher/translategemma-{4b,12b}-it-GGUF`, Q4_K_M, SHA-256 épinglés). Une demi-seconde après la première activation, une fenêtre explique les **avantages et inconvénients** (chiffres mesurés ci-dessous), donne le matériel détecté (mémoire, cœurs, carte NVIDIA via `nvidia-smi`, Apple Silicon) et un conseil ; « Plus tard » ne retient rien (la question revient à la première traduction). **Pas de question quand le choix est évident** : carte NVIDIA de 12 Go ou plus, ou Mac Apple Silicon avec 16 Go ou plus → 12B choisi d'office, avec une notification ; le téléchargement demande TOUJOURS l'accord (taille, source, destination, SHA-256). Une carte de 8 Go n'est pas « évidente » (le 12B n'y tient pas entièrement) : on demande. Choix rapide du modèle dans la fenêtre de traduction (le serveur redémarre avec l'autre fichier) ; réglages : modèle, fichier personnel, bouton « Avantages et inconvénients… ». Ancienne configuration (simple chemin de fichier) reprise comme « fichier personnel ».
- ✔ **Mesures réelles** (XPS : RTX 3070 8 Go, i7 16 threads ; texte littéraire de 2 phrases, llama.cpp b11669) : 4B ≈ 106 jetons/s sur la carte (< 1 s), ≈ 10/s sur le processeur (3–5 s) ; **12B ≈ 7,4–8,3 jetons/s sur la carte (≈ 9–10 s ; modèle réparti carte/processeur, 6,8 Go libres), ≈ 3,2/s sur le processeur seul (≈ 20 s), ≈ 4/s si une autre application occupe la moitié de la carte**. Qualité : le 12B traduit correctement la phrase d'essai (« un frisson d'incompréhension », « assuré », « n'était plus utile »), le 4B fait une faute d'accord (« son détresse ») et trahit « shiver of incomprehension » (« vague de confusion »). À vérifier : mémoire exacte du 12B, vitesse sur une carte de 12 Go et plus, sur Apple Silicon, qualité sur d'autres langues.
- ✔ **Mesures sur trois machines, 4B, processeur seul, même texte de 2 phrases (63 jetons)** (2026-10-20, llama.cpp b11669 version CPU, copié dans `~/.local/opt/llama.cpp/` sur chaque machine) : XPS (i7-11700, 16 threads) ≈ 10 jetons/s, 4,4 Go de mémoire maximale ; **Inspiron (i7-7500U de 2017, 4 threads, 15 Go) ≈ 7 jetons/s, 15 s, 4,6 Go** ; **OptiPlex (i5-3570 de 2012, SANS AVX2, 4 threads, 7 Go dont 4 disponibles, bureau + Firefox ouverts) ≈ 7,9 jetons/s, 13,5 s, 3,1 Go** (lancé sous `systemd-run --user --pipe -p OOMScoreAdjust=1000 -p MemoryMax=4300M -p MemorySwapMax=0` : le test aurait été tué avant Firefox ; aucun manque de mémoire, Firefox intact). La génération dépend surtout de la vitesse de la mémoire, pas du nombre de cœurs : les vieilles machines s'en sortent. Les builds officiels contiennent des variantes CPU (sandybridge, ivybridge, haswell, skylakex…) choisies à l'exécution : un processeur sans AVX2 fonctionne. Le 12B n'a PAS été mesuré sur ces machines (il ne tiendrait pas dans 7 Go de l'OptiPlex ; sur l'Inspiron il tiendrait mais serait lent : à mesurer si besoin).
- ✔ L'assistant signale les machines trop justes : « Meilleur (12B) » avec moins de 11 Go de mémoire et sans carte de 8 Go ou plus → ⚠ en rouge + confirmation « Choisir quand même ? » ; « Rapide (4B) » avec moins de 5 Go → ⚠ aussi.
- ✔ **Téléchargement du modèle : on sait toujours où on en est** (corrigé le 2026-10-20 après un essai réel sur l'Inspiron : fenêtre figée, aucun chiffre) : deux causes trouvées — la barre de Qt n'accepte que des entiers 32 bits (4B = 2,49 Go et 12B = 7,30 Go dépassent 2,15 Go : `OverflowError`) et les signaux `pyqtSignal(int, int)` DÉFORMENT silencieusement les grandes valeurs (7,3 Go arrivait négatif et était ignoré). Maintenant : signaux `object`, barre en Mo, étapes annoncées (« Connexion au serveur… », « reprise d'un téléchargement interrompu », « Vérification de la somme de contrôle (SHA-256)… » en barre d'attente), pourcentage, débit réel (hors reprise), temps restant, notification à la fin. Test de régression qui fait tourner la VRAIE fenêtre (les tests précédents la remplaçaient par une fausse, d'où le bug passé inaperçu). Leçon : ne jamais « simuler » ce qu'on veut vérifier.
- ✔ **Vérification de la mémoire LIBRE avant de lancer le moteur** (2026-10-20, après avoir constaté que l'Inspiron n'avait que 6 Go libres alors que le 12B en demande davantage, sans swap) : mémoire du serveur MESURÉE (Mo ; anonyme = non récupérable, seule cause d'arrêts forcés / fichier = récupérable mais ralentit si évincé) — **4B processeur : 2 100 + 2 387 = 4 488** ; **12B processeur : 6 583 + 6 975 = 13 558** (mon estimation « 8–9 Go » était fausse) ; **12B avec carte de 8 Go (6,7 Go libres) : 749 + 4 045 = 7 954** ; sans AVX2 (OptiPlex) le 4B ne prend que 3,1 Go (les poids ne sont pas réarrangés : facteur 0,7). Trois niveaux : « ok » ; « juste » (dispo < résidente : ça tient mais plus lent) ; « danger » (dispo < anonyme : arrêts forcés possibles). Fenêtre avec trois boutons : « Utiliser le modèle rapide (4B) » (choix par défaut en cas de danger), « Continuer quand même », « Annuler » ; mention du manque de swap. Aucune vérification si le serveur tourne déjà avec ce modèle, ni si la mémoire disponible est inconnue (on ne bloque rien). Une carte graphique libre réduit le besoin (formule calée sur la mesure : 12B 13,6 -> 7,7 Go prévus pour 7,8 mesurés). Lecture : `/proc/meminfo` (MemAvailable, SwapTotal), `/proc/cpuinfo` (avx2) ; Windows : `GlobalMemoryStatusEx` ; macOS : `vm_stat` — **non testés hors Linux**. L'avertissement de l'assistant se base maintenant sur ces mêmes besoins (mémoire totale de la machine).
- ✔ **Essayé par l'utilisateur sur les trois machines (2026-10-20), « ok » partout** : XPS (carte RTX 3070), Inspiron (processeur seul, téléchargement du 12B observé puis vérifié), OptiPlex (i5 de 2012, 7 Go, modèle rapide). Restent à surveiller : qualité sur d'autres langues, 12B sur grosse carte, lecture de la mémoire sous Windows/macOS.
- ➜ **Argos Translate RETIRÉ** (2026-10-20, constaté sur l'XPS) : la version 1.11.0 fait `import stanza` sans condition (`argostranslate/sbd.py`, ligne 12), et `stanza` tire PyTorch (plusieurs Go) ; avec un module vide à sa place l'import réussit mais le code lit encore `settings.stanza_available`, réglage qui n'existe plus : contournement bancal, écarté. Le plugin n'a plus aucune installation de paquet ; un ancien réglage `moteur: argos` retombe sur llama.cpp. Restes supprimés le 2026-10-20 à la demande de l'utilisateur : `deps` (296 Mo, 17 paquets pip) et les trois dossiers vides créés par Argos dans le `HOME` (aucun modèle de langue n'avait été téléchargé).
- ☐ **Piste si on veut un moteur léger (processeur seul, ex. Inspiron)** : notre propre moteur sur **CTranslate2 + SentencePiece** (sans la bibliothèque Argos) avec les modèles de l'index public d'Argos (`argospm-index` : 100 paquets, ex. fr→en et en→fr à `argos-net.com`, ~100 Mo chacun, format CTranslate2 + SentencePiece) ; CTranslate2 s'installe sans PyTorch. À faire : découpage en phrases, appel du modèle, tests, essai réel (demande un téléchargement, donc l'accord de l'utilisateur). Décider après avoir **mesuré llama.cpp sur l'Inspiron** (CPU i7-7500U, 2 cœurs).
- ☐ Moteurs en ligne facultatifs (DeepL…) : pas faits · ☐ nom `llama` (README récent) à côté de `llama-server` · ☐ téléchargement du binaire llama.cpp par le plugin (aujourd'hui : aide seulement) · ☐ qualité sur le vocabulaire technique et les textes longs · ☐ essai sur l'Inspiron (CPU lent) · ☐ traductions anglaises (po/en.po) de l'interface du plugin


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
- ✔ `TODO.md` (ce fichier, remis à jour le 2026-10-20)
- ✔ Workflow git : branche `dev` puis `main`, sans pull request (dépôt perso) ; tests : `python3 -m pytest` (227 + 2 facultatifs) ; les tests tournent TOUJOURS hors écran (`tests/conftest.py` impose `offscreen`, retire `DISPLAY` et interdit toute boîte de dialogue modale non prévue)
- ✔ `~/scripts/scrinium/dev.sh` (XPS + Inspiron) : lance les sources avec des données de test séparées
