#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Envoie un fichier texte à Scrinium (fenêtre « Ajouter », rien n'est enregistré sans validation). Utilisé par le menu Dolphin.
[ -r "$1" ] || exit 1
lien=$(F="$1" python3 -c 'import os,urllib.parse as u; f=os.environ["F"]; t=open(f,errors="replace").read()[:20000]; print("scrinium://ajouter?titre="+u.quote(os.path.basename(f),safe="")+"&texte="+u.quote(t,safe=""))')
exec scrinium "$lien"
