# Spécification : pièces jointes (images) dans les fiches

Statut : **validé le 2026-10-20** ; couche « cœur » implémentée (`core/crypto.py`, `core/store.py`, `tests/test_pieces.py`) ; interface, import d'image, `rescue` et API des extensions restent à faire. Cible : Scrinium 0.2. Choix d'interface retenu : **option B** (le texte
reste un texte simple ; les images sont listées sous la fiche en vignettes, pas au milieu du texte).

## 1. Principes

1. **Le fichier de la fiche ne change pas.** `titre.md` et `titre.lock` (AMLOCK2) gardent leur format actuel. Une fiche
   avec pièces jointes reste lisible, texte compris, par Scrinium 0.1.0 et par l'ancien outil Tk.
2. **Les pièces jointes vivent à côté**, dans un dossier `titre.pj/`. Rien n'est ajouté au texte : pas de balise,
   pas de métadonnée. La liste des pièces = le contenu du dossier.
3. **Une fiche verrouillée chiffre aussi ses pièces jointes**, avec la même clé que son texte. Un plugin ne peut pas
   affaiblir ce point (le stockage et le chiffrement restent dans le cœur).
4. **Rien n'est supprimé en silence** : corbeille, dossiers orphelins signalés mais jamais effacés automatiquement.
5. Fichiers ordinaires, écrits de façon atomique : compatibles avec la synchronisation par dossier (section 3 quater du TODO).

## 2. Disposition sur le disque

```
<base>/fiches/<Thème>/
    Ma fiche.md                 fiche en clair (inchangé)
    Ma fiche.pj/
        1.png        1.json     image + fiche descriptive (en clair)
        2.jpg        2.json
    Autre fiche.lock            fiche verrouillée (AMLOCK2, inchangé)
    Autre fiche.pj/
        1.lock                  pièce jointe chiffrée (AMLOCK3) ; tout (type, nom d'origine, texte OCR) est à l'intérieur
```

- Dossier `.pj` : mêmes droits que les fiches (`0700`, fichiers `0600` sous POSIX). Nom = celui du fichier de la fiche
  sans l'extension, plus `.pj`. Il n'existe que si la fiche a au moins une pièce jointe (supprimé quand la dernière part).
- **Numéro** `n` : entier ≥ 1, égal au plus grand numéro présent + 1 (un numéro supprimé est à la corbeille, qui garde le nom
  d'origine : pas de collision). L'ordre d'affichage est l'ordre des numéros.
- Fiche en clair : `n.<ext>` avec `ext` ∈ `png`, `jpg`, `webp`. Le fichier est une image ordinaire, ouvrable par n'importe
  quel logiciel. Fichier descriptif facultatif `n.json` :
  `{"nom": "capture.png", "ajoute": "2026-10-20 14:03", "ocr": "texte extrait", "ocr_moteur": "tesseract"}`.
  Champs inconnus conservés à la réécriture.
- Fiche verrouillée : `n.lock` seulement (pas d'`.json` : il serait en clair).

## 3. Format `AMLOCK3` (pièce jointe verrouillée)

Même enveloppe que `AMLOCK2` (voir `core/crypto.py`), pour réutiliser le code, la clé de secours et l'outil `rescue` :

```
AMLOCK3\n | sel(16) | nonce(12) | taille clé enveloppée(2) | clé enveloppée | AES-256-GCM( en-tête + données )
en-tête + données = taille de l'en-tête (4 octets, grand-boutiste) | en-tête JSON UTF-8 | octets de l'image
en-tête JSON      = {"nom", "type" (image/png…), "ajoute", "ocr", "ocr_moteur"}   (champs facultatifs sauf "type")
données associées authentifiées (AAD) = AMLOCK3\n | sel | taille clé enveloppée | clé enveloppée
```

- `sel` et `clé enveloppée` sont **ceux de la fiche** : la clé AES est la même, dérivée du mot de passe de la fiche.
  Chaque fichier a son propre `nonce` aléatoire (96 bits ; la limite de GCM est très loin de 50 fichiers par fiche).
- Chaque pièce est **autonome** : la clé de secours (RSA) ouvre une pièce seule, sans la fiche.
- Mauvais mot de passe ou fichier modifié (en-tête compris) : `InvalidTag`, comme pour le texte.
- `MAGIC` inconnu : ValueError « format plus récent, mettez Scrinium à jour » (jamais d'écriture dessus).

**Fuite assumée** : un observateur du disque voit, pour une fiche verrouillée, le **nombre** de pièces et leur **taille
approximative**. Ni le contenu, ni le nom, ni le type, ni le texte OCR. (Un remplissage à taille fixe est possible plus tard.)

## 4. Import d'une image

- Entrées : coller depuis le presse-papiers, glisser-déposer, bouton « Ajouter une image… ».
- Formats acceptés : ceux que Qt décode (PNG, JPEG, WebP, BMP, GIF fixe) ; **enregistrés en PNG ou JPEG** (WebP
  accepté en lecture aussi).
- **Réencodage obligatoire à l'import** : supprime les métadonnées EXIF (position GPS, appareil, date).
- Réduction : plus grand côté ≤ **2560 px** ; poids final ≤ **8 Mo** (sinon qualité JPEG réduite, puis refus avec message).
  PNG d'origine conservé en PNG si sous la limite, sinon converti en JPEG (avertissement).
- Limites par fiche : 50 pièces, 100 Mo ; au-delà, refus avec message.
- Valeurs ajustables dans `settings.json` (clé `pieces_jointes`).

## 5. Opérations du cœur (toutes à rendre atomiques)

| Opération | Comportement |
|---|---|
| Ajouter | écrire `n.<ext>` (+ `n.json`) ou `n.lock` ; création du dossier si besoin (`0700`) |
| Supprimer une pièce | **corbeille** (`corbeille/<horodatage>-Ma fiche.pj-n.png`), jamais d'effacement direct |
| Renommer la fiche (titre) | renommer `.pj` **avant** de supprimer l'ancien fichier de fiche (à tout instant un des deux chemins est valide) |
| Renommer un thème | déplace le dossier du thème : les `.pj` suivent |
| Supprimer la fiche | `Ma fiche.pj` va à la corbeille avec **le même horodatage** que la fiche |
| **Verrouiller** | 1) construire `Ma fiche.pj.new/` avec toutes les pièces chiffrées (`n.lock`) ; 2) écrire `Ma fiche.lock` ; 3) échange de dossiers : `.pj` → `.pj.old`, `.pj.new` → `.pj` ; 4) supprimer `.old` puis l'ancien `.md` |
| **Retirer le verrou** | l'inverse : déchiffrer vers `.pj.new` (`n.<ext>` + `n.json`), écrire `.md`, échange, suppression |
| Changer de mot de passe (si ajouté) | même procédure que « verrouiller » : tout est rechiffré |
| Chargement (`_reparer_pj`) | `.pj.new` contenant le marqueur `.pret` **et** dont la fiche (`.lock` si ce sont des `n.lock`, sinon `.md`) existe → promu (l'échange est terminé) ; sinon supprimé (jamais valide). Puis `.pj.old` sans `.pj` → restauré ; `.pj.old` avec `.pj` → supprimé. Le marqueur `.pret` est retiré une fois l'échange fini |
| Dossier `.pj` sans fiche | **orphelin** : signalé dans le journal, jamais supprimé ni affiché comme fiche |

Une version de Scrinium **< 0.2** ignore les `.pj` : renommer, verrouiller ou supprimer une fiche avec pièces jointes
depuis une ancienne version laisse un dossier orphelin (rien n'est perdu). À écrire dans les notes de version.

## 6. Interface (option B)

- Sous l'éditeur : bande de **vignettes** (96 px, générées en mémoire à l'ouverture, **jamais mises en cache sur le disque**).
- Ctrl+V avec une image dans le presse-papiers → pièce jointe (le texte collé continue d'aller dans l'éditeur).
- Double-clic : visionneuse (zoom, flèches précédent/suivant). Clic droit : *Enregistrer sous…*, *Copier*, *Supprimer*.
- Fiche verrouillée fermée : aucune vignette, aucun nombre affiché. Ouverte : vignettes déchiffrées en mémoire seulement ;
  « Enregistrer sous… » écrit une copie **en clair** après avertissement.
- Fermeture/réduction de la fenêtre : les données déchiffrées sont libérées avec la fiche (comme le texte).
- Recherche : le texte OCR des fiches en clair est indexé ; celui d'une fiche verrouillée seulement quand elle est ouverte.

## 7. API des extensions (ajouts, `API_VERSION` inchangée)

- `FicheVue.pieces` : liste de `PieceVue` (`id`, `nom`, `type`, `taille`, `ocr`) ; vide pour une fiche verrouillée fermée.
- `ctx.lire_piece(piece) -> bytes` (fiche ouverte seulement), `ctx.maj_piece(piece, ocr=…, ocr_moteur=…)`,
  `ctx.ajouter_piece(vue, nom, donnees)`.
- Événements : `piece_jointe_ajoutee(fiche, piece)`, `piece_jointe_supprimee(fiche, piece)`.
- L'extension OCR s'appuie dessus ; l'extension courriel pourra joindre les images (fiches en clair ou ouvertes).

## 8. Tests de compatibilité à écrire AVANT le code

1. Fiche `.md` et `.lock` (AMLOCK1/2) existantes : lues et réécrites à l'identique, sans créer de `.pj`.
2. AMLOCK3 : aller-retour ; mauvais mot de passe ; en-tête ou données modifiés → `InvalidTag` ; magic inconnu → erreur claire.
3. Clé de secours : ouvre une `n.lock` seule (étendre `scrinium rescue open`).
4. Verrouiller / retirer le verrou avec 3 pièces ; **interruption simulée à chaque étape** (chargement : état cohérent).
5. Renommer la fiche et le thème, supprimer la fiche : les `.pj` suivent ; paires dans la corbeille.
6. Import : EXIF supprimé, réduction à 2560 px, poids maximal, refus au-delà des limites.
7. Une copie du dossier lue par le code 0.1.0 : texte intact, `.pj` ignoré sans erreur.
8. Noms de fichiers valides sous Windows/macOS ; titres ne différant que par la casse.

## 9. Décisions à valider

- Dossier `titre.pj/` à côté de la fiche (et non un dossier caché par thème) : simple à sauvegarder et à inspecter,
  au prix d'un renommage à deux étapes (traité en section 5).
- Une pièce = un fichier (et non un conteneur unique avec le texte) : l'enregistrement automatique du texte ne réécrit
  pas des mégaoctets d'images ; en échange, le nombre et la taille des pièces d'une fiche verrouillée sont visibles.
- Limites (2560 px, 8 Mo, 50 pièces, 100 Mo) et formats de sortie (PNG/JPEG).
