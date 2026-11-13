#!/usr/bin/env bash
# Construit le module Firefox (.xpi) de navigateur/ : un simple zip dont manifest.json est à la racine.
# Le fichier produit n'est PAS signé : Firefox (version standard) ne l'installe durablement qu'une fois signé par Mozilla
# (addons.mozilla.org, « distribuer par moi-même »). Voir navigateur/README.md.
set -euo pipefail
cd "$(dirname "$0")/../navigateur"
version=$(python3 -c 'import json; print(json.load(open("manifest.json"))["version"])')
sortie="../dist/scrinium-ajouter-${version}.xpi"
mkdir -p ../dist
rm -f "$sortie"
zip -X -D -r -q "$sortie" manifest.json background.js icon.png _locales
echo "$sortie"
unzip -l "$sortie" | tail -n +4 | head -n -2
