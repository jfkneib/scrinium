# Scrinium

[English](README.md) · **Français**

*Scrinium* : en latin, le coffret où l'on rangeait livres et papiers précieux.

Des **fiches** (titre + note) rangées par **thème**, enregistrées automatiquement dans de simples fichiers texte.
Chaque fiche peut être **verrouillée par un mot de passe** (AES-256-GCM, clé dérivée par scrypt). Une **clé de secours**
facultative, créée par vous au premier lancement, permet de rouvrir une fiche dont le mot de passe est oublié.

Interface Qt (PyQt6) : Linux, Windows, macOS (paquets Windows/macOS : à venir).

**[⬇ Télécharger la dernière version (paquet .deb)](https://github.com/jfkneib/scrinium/releases/latest)** · [Installation](#installation)

## Installation

**Debian / Ubuntu** : téléchargez `scrinium_0.4.1_all.deb` sur la [**page des versions (Releases)**](https://github.com/jfkneib/scrinium/releases/latest) (section *Assets*, tout en bas), ou directement :

```bash
wget https://github.com/jfkneib/scrinium/releases/download/v0.4.1/scrinium_0.4.1_all.deb
```

puis installez-le :

```bash
sudo apt install ./scrinium_0.4.1_all.deb
```

Pour vérifier le téléchargement, récupérez aussi `SHA256SUMS` sur la même page et lancez `sha256sum -c SHA256SUMS`.

**Windows** : téléchargez `Scrinium-0.4.1-setup.exe` sur la [page des versions](https://github.com/jfkneib/scrinium/releases/latest) (*Assets*) et double-cliquez dessus. Aucun droit administrateur n'est nécessaire (installation pour votre utilisateur, dans `%LOCALAPPDATA%\Programs\Scrinium`, avec un raccourci du menu Démarrer et une entrée dans *Paramètres → Applications* pour le désinstaller). Le programme d'installation n'est **pas signé** : Windows affiche « Windows a protégé votre ordinateur » au premier lancement ; cliquez sur *Informations complémentaires*, puis *Exécuter quand même*. Vos fiches (`%APPDATA%\scrinium`) ne sont jamais supprimées. Les extensions qui demandent des outils Linux (dictée, lecture à voix haute, capture et console) sont grisées sous Windows.

**Autres distributions** (sans root, depuis ce dépôt) :

```bash
./install.sh              # installe dans ~/.local (environnement Python isolé + lanceur + icône)
./install.sh --uninstall  # désinstalle (vos fiches sont conservées)
```

Prérequis de `install.sh` : Python ≥ 3.10 avec `venv`. PyQt6 et cryptography sont installés par pip.

## Utilisation

Au premier lancement, Scrinium crée un thème **Bienvenue** (5 fiches qui expliquent l'outil, dont une fiche verrouillée à essayer) et quelques thèmes modèles à compléter (Perso, Maison, Informatique, Voyages). Supprimez-les quand vous voulez.

- `scrinium` ouvre la fenêtre : thèmes à gauche, fiches au milieu, éditeur à droite.
- **Fiche** (Ctrl+N) / **Thème** : création. Clic droit ou boutons sous la liste pour renommer, changer l'icône, supprimer un thème.
- Enregistrement **automatique** (Ctrl+S pour forcer). Recherche : Ctrl+F, dans tous les thèmes.
- **Supprimer = corbeille** (`corbeille/` à côté des fiches) : rien n'est effacé.
- **Zone de notification** : fermer ou réduire la fenêtre la range dans la zone de notification (clic sur l'icône = afficher/cacher, clic droit = menu). Option *Fichier → Réduire dans la zone de notification* pour désactiver ; sans zone de notification sur le bureau (GNOME sans extension AppIndicator), la fenêtre se comporte normalement. En se cachant, Scrinium **referme les fiches verrouillées** : le mot de passe est redemandé.
- **Instance unique** : relancer `scrinium` réveille la fenêtre déjà ouverte. `scrinium --minimise` démarre caché dans la zone de notification. La case *Fichier → Lancer au démarrage de la session* l'active pour vous (fichier XDG autostart sous Linux, clé Run sous Windows, LaunchAgent sous macOS).
- **Capture rapide** : `scrinium --rapide` (aussi *Fichier → Capture rapide…*, Ctrl+Alt+N, et le menu de la zone de notification) n'ouvre qu'une petite fenêtre « note rapide » ; Ctrl+Entrée ajoute le texte (daté) à la fiche de votre choix, retenue d'une fois sur l'autre. Le thème peut être tapé : un nom qui n'existe pas encore le crée (proposé par défaut : « Sous le coude »). Pour l'utiliser de partout, liez `scrinium --rapide` à un raccourci clavier dans les réglages du bureau (KDE : *Configuration du système → Raccourcis → Ajouter une commande*). Scrinium lancé dans la zone de notification, elle apparaît aussitôt ; une fiche verrouillée n'est jamais écrite.
- **Ajouter depuis un navigateur ou un autre programme** : le lien `scrinium://ajouter?titre=…&texte=…&theme=…` ouvre une petite fenêtre qui montre la fiche proposée ; **rien n'est enregistré avant votre clic sur « Ajouter »**, et une fiche existante n'est jamais modifiée (elle crée toujours une fiche neuve). Exemple de **signet de navigateur** (« envoyer cette page à Scrinium » : titre, adresse et texte sélectionné) :
  `javascript:(()=>{location.href='scrinium://ajouter?titre='+encodeURIComponent(document.title)+'&texte='+encodeURIComponent(location.href+'\n\n'+getSelection())})()`
  Le lien est reconnu par le système une fois Scrinium installé (Linux : `.deb` ou `install.sh` ; Windows : l'installateur) ; 64 Ko de texte au plus (au-delà, `scrinium ajouter` avec un tube). Lancer `scrinium "scrinium://ajouter?texte=bonjour"` dans un terminal fait la même chose.
- **Intégrations facultatives** : rien ne vous oblige à installer un service tiers. Le dossier `exemples/` propose, pour qui les utilise, des exemples d'intégration (par exemple un outil Open WebUI qui laisse un modèle de langage créer une fiche) ; ils ne sont pas livrés avec le programme.
- **Inviter quelqu'un** : *Fichier → Inviter à installer Scrinium…* crée (ou rouvre, sans jamais écraser vos modifications) une fiche prête à envoyer dans un thème « Invitations » : liens de téléchargement, installation selon le système, extensions. Avec l'extension Courriel active, la fenêtre d'envoi s'ouvre aussitôt.
- Options : `--theme NOM` (ouvre sur ce thème), `--nouvelle` (ouvre avec une fiche vide prête à saisir).

## Données

| Système | Dossier |
|---|---|
| Linux | `~/.config/scrinium/` |
| Windows | `%APPDATA%\scrinium\` |
| macOS | `~/Library/Application Support/scrinium/` |

`SCRINIUM_HOME` force un autre dossier. Dedans : `fiches/<Thème>/<titre>.md` (ou `.lock`), `corbeille/`, `settings.json`.
Les `.md` se lisent et se modifient avec n'importe quel éditeur ; sauvegardez simplement ce dossier.

## Verrouillage et clé de secours

- **Verrouiller…** chiffre le texte de la fiche ; le titre reste visible, la recherche ne lit pas le contenu d'une fiche verrouillée.
  Aucun texte en clair n'est écrit sur disque, même pendant l'édition. Le mot de passe n'est jamais stocké.
- **Fichier de secours** : si vous oubliez le mot de passe d'une fiche, il permet de la rouvrir. Scrinium le propose au
  **premier verrouillage** (ou plus tard : menu *Sécurité → Fichier de secours…*). Vous choisissez son nom (par défaut
  *Scrinium-secours-<utilisateur>-<date>*) et son dossier (par défaut *Documents*), avec un mot de passe de protection
  facultatif. Techniquement : une paire RSA générée **chez vous** ; la clé publique (`recovery.pub`) enveloppe la clé de
  chaque fiche verrouillée ensuite, le fichier de secours est la clé privée (PEM). **Gardez-le hors de l'ordinateur** :
  Scrinium n'en garde aucune copie. Un nouveau fichier peut être créé à tout moment ; il ne vaut que pour les fiches
  verrouillées après sa création (les autres ne s'ouvrent qu'avec l'ancien). Les fiches verrouillées *avant* la création
  du tout premier fichier le reçoivent au prochain déverrouillage.
- Récupération : menu *Sécurité → Rouvrir une fiche avec le fichier de secours…*, ou en ligne de commande :

```bash
scrinium secours lister
scrinium secours ouvrir "titre" --cle ~/cle-de-secours.pem
scrinium secours deverrouiller "titre" --cle ~/cle-de-secours.pem
# alias anglais : scrinium rescue list|open|unlock
```

## Extensions

Scrinium peut être étendu par des plugins. Huit sont livrés avec lui (et avec le `.deb`) : **lecture à voix haute** (une fiche, la sélection ou tout un thème, en français ou en anglais : voix Piper ou espeak-ng ; une fiche verrouillée n'est jamais lue), **agenda** (rappels datés, liés ou non à une fiche), **applications** (panneau d'icônes pour lancer Thunderbird, KWrite, LibreOffice…), **OCR** (Tesseract, texte des images jointes), **dictée** (faster-whisper local), **courriel** (envoi d'une fiche par SMTP), **capture et console** (sortie d'une commande dans la fiche, sélection envoyée à Konsole) et **traduction** (TranslateGemma via llama.cpp, sans Ollama). Ils sont
**désactivés par défaut** : *Extensions → Gérer les extensions…* les liste et les active un par un, après un
avertissement (une extension est du code Python qui s'exécute avec les mêmes droits que Scrinium : n'activez que celles
que vous connaissez). Déposez le dossier d'une extension dans `<dossier de données>/plugins/`, ou installez un paquet qui
en fournit une. Chacune indique les programmes facultatifs dont elle a besoin (Tesseract, faster-whisper, llama.cpp…) et demande avant d'installer ou de télécharger quoi que ce soit ; rien ne quitte votre machine, hors le courriel que vous envoyez. Un exemple fonctionnel est dans [`plugins/hello`](plugins/hello) ; l'API est décrite dans
[`docs/plugins.md`](docs/plugins.md) (en anglais). Une extension défaillante n'empêche jamais Scrinium de démarrer et
est désactivée automatiquement après des erreurs répétées.

## Intégration (facultatif)

Si un exécutable `~/.config/scrinium/hooks/themes-changed` existe, il est appelé à chaque création, renommage,
suppression ou changement d'icône de thème, avec sur l'entrée standard la liste JSON `[{"nom","icone","fiches"}]`.
Utile pour générer des lanceurs, un tableau de bord, etc.

## Développement

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest
dpkg-buildpackage -us -uc -b    # construit le .deb (dans le dossier parent)
```

Le code est séparé : `core/` (stockage, chiffrement, clé de secours, sans aucune dépendance graphique) et `ui/` (PyQt6).

## Nom et icône

*Scrinium* est un mot latin (le coffret où l'on rangeait livres et papiers). Plusieurs projets sans rapport portent le
même nom (par exemple une infrastructure de recherche pour agents IA sur PyPI, et un mapper objet-document) ; aucun n'est
lié à celui-ci. L'icône a été dessinée pour ce projet à partir de formes simples.

Je n'ai connaissance d'aucun conflit, mais **si vous pensez que le nom ou l'icône porte atteinte à un droit ou prête à
confusion, [ouvrez un ticket](https://github.com/jfkneib/scrinium/issues) ou écrivez-moi : je les changerai de bonne foi.**
Si vous distribuez une version modifiée, merci d'indiquer clairement qu'il ne s'agit pas de l'original (par exemple en la renommant).

## Principes du projet

Scrinium est un logiciel libre pour n'importe qui : cœur sans dépendance à un service tiers, intégrations facultatives, sécurité par défaut, rien de personnel dans le dépôt. Voir [`docs/principes.md`](docs/principes.md).

## Licence

GPL-3.0-or-later (voir [`LICENSE`](LICENSE)). Icônes : thème Breeze (KDE), LGPL-3.0-or-later (voir `src/scrinium/icons/NOTICE`).

Les extensions s'exécutent dans le processus de Scrinium : celles distribuées avec lui devraient avoir une licence compatible GPL.

L'interface existe en français et en anglais (gettext, `po/`) : langue automatique, ou menu *Aide → Langue*. Pour ajouter une langue, copier `po/scrinium.pot` en `po/<code>.po` et traduire (les textes sources sont en français).
