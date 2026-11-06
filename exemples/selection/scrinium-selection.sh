#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Envoie le texte sélectionné (sélection primaire, sans Ctrl+C) à Scrinium : une fenêtre « Ajouter » s'ouvre,
# rien n'est enregistré sans validation. À lier à un raccourci clavier global (voir README.md).
# Linux : wl-paste (Wayland) ou xclip / xsel (X11).
if [ -n "$WAYLAND_DISPLAY" ] && command -v wl-paste >/dev/null; then
    texte=$(wl-paste --primary --no-newline 2>/dev/null)
elif command -v xclip >/dev/null; then
    texte=$(xclip -o -selection primary 2>/dev/null)
elif command -v xsel >/dev/null; then
    texte=$(xsel -o -p 2>/dev/null)
fi
if [ -z "$texte" ]; then
    command -v notify-send >/dev/null && notify-send -a Scrinium "Scrinium" "Aucun texte sélectionné."
    exit 1
fi
lien=$(SEL="${texte:0:20000}" python3 -c 'import os,urllib.parse as u; print("scrinium://ajouter?texte="+u.quote(os.environ["SEL"], safe=""))')
exec scrinium "$lien"
