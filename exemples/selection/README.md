# Envoyer une sélection à Scrinium depuis n'importe quelle application (facultatif)

Dans tous les cas, Scrinium ouvre sa fenêtre « Ajouter » : **rien n'est enregistré sans votre validation**.
(Pour les navigateurs, voir plutôt `navigateur/`.)

## Linux (KDE, GNOME…) : `scrinium-selection.sh`
Envoie la **sélection** (pas besoin de Ctrl+C) de n'importe quelle application. Il faut `xclip` ou `xsel` (X11), ou `wl-clipboard` (Wayland).
1. Copier le script dans un dossier du PATH (ex. `~/scripts/scrinium/`), `chmod +x`.
2. Le lier à un raccourci : KDE → *Configuration du système → Raccourcis → Ajouter une commande* (ex. Ctrl+Alt+S) ;
   GNOME → *Paramètres → Clavier → Raccourcis personnalisés*.

## Dolphin (KDE) : `scrinium-dolphin.desktop`
Clic droit sur un fichier texte → *Envoyer à Scrinium*. À copier dans `~/.local/share/kio/servicemenus/` (le rendre exécutable), avec `scrinium-fichier.sh` dans le PATH (ex. `~/scripts/scrinium/`).

## Windows : `scrinium-selection.ahk`
Avec [AutoHotkey v2](https://www.autohotkey.com/) : Ctrl+Alt+S envoie le texte sélectionné (jusqu'à 6000 caractères).

## macOS
Ouvrir *Automator → Nouveau → Action rapide* : « reçoit *du texte* dans *toutes les applications* », action *Exécuter un script shell* (entrée : *comme arguments*) :
```
open "scrinium://ajouter?texte=$(python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1][:6000], safe=""))' "$1")"
```
Elle apparaît ensuite dans le clic droit, sous *Services*. (macOS : méthode non testée.)
