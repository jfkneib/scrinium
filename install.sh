#!/usr/bin/env bash
# Installation d'Scrinium pour l'utilisateur courant (sans root) : environnement isolé + lanceur + icône.
# Usage : ./install.sh [--uninstall]
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/scrinium/venv"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$(dirname "$VENV")" "$BIN/scrinium" "$APPS/scrinium.desktop" "$ICONS/scrinium.svg"
    echo "Désinstallé. Vos fiches (~/.config/scrinium) sont conservées."
    exit 0
fi

command -v python3 >/dev/null || { echo "python3 est requis." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10 ou plus récent requis." >&2; exit 1; }
python3 -m venv --help >/dev/null 2>&1 || { echo "Module venv absent (Debian/Ubuntu : sudo apt install python3-venv)." >&2; exit 1; }

echo "→ Environnement : $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$SRC"

mkdir -p "$BIN" "$APPS" "$ICONS"
ln -sf "$VENV/bin/scrinium" "$BIN/scrinium"
install -m 644 "$SRC/packaging/scrinium.desktop" "$APPS/scrinium.desktop"
install -m 644 "$SRC/src/scrinium/icons/scrinium.svg" "$ICONS/scrinium.svg"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
command -v xdg-mime >/dev/null && xdg-mime default scrinium.desktop x-scheme-handler/scrinium 2>/dev/null || true   # liens scrinium://

echo "✔ Installé. Lancez « scrinium » ou cherchez « Scrinium » dans le menu."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  (ajoutez $BIN à votre PATH si la commande est introuvable)";; esac
