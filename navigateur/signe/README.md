# Module Firefox signé

Déposez ici le `.xpi` **signé par Mozilla** (voir `../README.md`, « Fabriquer le .xpi ») : `scrinium-ajouter-<version>.xpi`.
Le workflow « Paquet .deb » le joint à la release de chaque tag `v…` (avec son empreinte dans `SHA256SUMS`).
Ne mettez jamais ici un `.xpi` non signé (`outils/xpi.sh` écrit dans `dist/`, ignoré par git) : Firefox le refuserait.
Quand le module change, augmentez `version` dans `../manifest.json`, refaites signer, et remplacez le fichier.
