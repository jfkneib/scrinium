# Scrinium

[English](README.md) · **Français**

*Scrinium* : en latin, le coffret où l'on rangeait livres et papiers précieux.

Des **fiches** (titre + note) rangées par **thème**, enregistrées automatiquement dans de simples fichiers texte.
Chaque fiche peut être **verrouillée par un mot de passe** (AES-256-GCM, clé dérivée par scrypt). Une **clé de secours**
facultative, créée par vous au premier lancement, permet de rouvrir une fiche dont le mot de passe est oublié.

Interface Qt (PyQt6) : Linux, Windows, macOS (paquets Windows/macOS : à venir).

## Installation

**Debian / Ubuntu** (paquet `.deb` de la page *Releases*) :

```bash
sudo apt install ./scrinium_0.1.0_all.deb
```

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

Scrinium peut être étendu par des plugins (rappels, OCR, dictée… sont prévus sous forme de plugins). Ils sont
**désactivés par défaut** : *Extensions → Gérer les extensions…* les liste et les active un par un, après un
avertissement (une extension est du code Python qui s'exécute avec les mêmes droits que Scrinium : n'activez que celles
que vous connaissez). Déposez le dossier d'une extension dans `<dossier de données>/plugins/`, ou installez un paquet qui
en fournit une. Un exemple fonctionnel est dans [`plugins/hello`](plugins/hello) ; l'API est décrite dans
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

## Licence

GPL-3.0-or-later. Icônes : thème Breeze (KDE), LGPL-3.0-or-later.

L'interface existe en français et en anglais (gettext, `po/`) : langue automatique, ou menu *Aide → Langue*. Pour ajouter une langue, copier `po/scrinium.pot` en `po/<code>.po` et traduire (les textes sources sont en français).
