# Partage de fiches : le cœur (étape 1)

Statut : **en cours** (branche `feat/partage`). Contexte et décisions : `TODO.md`, section « 3 quater-a ».

Le partage repose sur un **serveur Scrinium** (PHP, dossier `serveur/` à venir) et un **plugin « Partage »** côté client. Les plugins
n'ont volontairement pas accès au stockage ni au chiffrement : ce qui suit doit donc être dans **le cœur**, utilisable par le plugin.
Une personne qui n'active jamais le partage garde **exactement** le Scrinium d'aujourd'hui (aucun fichier modifié).

## 1. Identifiant stable d'une fiche — FAIT
- Une fiche reconnue sur le serveur doit garder son identité quand on la **renomme**, la **déplace** de thème ou la **verrouille**.
  Son chemin et son titre ne conviennent donc pas.
- L'identifiant (`uuid4().hex`, 32 caractères) est une **métadonnée de la fiche** (clé `id`, ligne invisible `<!-- scrinium: {...} -->`
  déjà utilisée par les plugins) : chiffrée avec le texte pour une fiche verrouillée, donc **invisible tant qu'elle est fermée**.
- Il est créé **à la demande** (`Store.assurer_id`), jamais à l'enregistrement : une fiche non partagée n'est pas modifiée.
- `Store.id_fiche`, `Store.trouver_par_id`, `Store.ids_en_double` (une fiche copiée à la main porte le même identifiant),
  `Store.renouveler_id`. Côté extensions : `FicheVue.identifiant` et `ctx.assurer_identifiant(vue)`.

## 2. Détection des changements — FAIT (`core/synchro.py`)
Pour synchroniser, il faut savoir ce qui a changé **depuis la dernière synchronisation**, sans rien envoyer inutilement.
- **État de synchronisation** par dépôt : `<données>/synchro/<dépôt>.json` (créé en mode privé, jamais dans le dossier des fiches).
  Pour chaque fiche **suivie** (partagée) : identifiant → {version du serveur, empreinte SHA-256 du contenu, thème, fichier, titre}.
  Un fichier absent, abîmé ou d'un format inconnu donne un état vide (on compare et on resynchronise, on n'écrase jamais).
- **Contenu synchronisé** = titre + texte + pièces jointes (nom et empreinte de chaque image) ; pas les métadonnées des extensions
  ni le texte OCR.
- `EtatSynchro.valider(store, th, f, version)` : à appeler après une synchronisation **réussie** ; c'est le moment où la fiche
  devient « suivie » (son identifiant est alors créé). `detecter(store, etat)` compare et rend la liste des **changements locaux**
  (`modifiee` avec `contenu` et/ou `deplacee`, `supprimee`, `verrouillee`, `inaccessible`) **sans rien modifier**.
- Une fiche **suivie puis verrouillée** n'est pas prise pour supprimée : ouverte → `verrouillee`, fermée (identifiant invisible) →
  `inaccessible` (retrouvée par son thème et son nom de fichier). Le contenu verrouillé ne se synchronise qu'à l'étape 3.
- Une fiche non suivie n'est jamais lue ni modifiée par ce module.
- Reste (étape 2) : déclencher le calcul (démarrage, enregistrement, demande), et les changements **distants**.

## 3. Conflits — À FAIRE
- Chaque enregistrement envoyé au serveur indique la **version de départ**. Si elle n'est plus la dernière (quelqu'un d'autre a
  enregistré entre-temps), le serveur **refuse**.
- Le client ne choisit jamais en silence : il garde les **deux** versions (la sienne devient « titre (conflit <date>) », la distante
  est reprise) et prévient l'utilisateur. Une fiche en lecture seule ne produit jamais d'envoi.

## 4. Dépôts et transport — À FAIRE
- Aujourd'hui `Store` a un seul dossier racine. On introduit la notion de **dépôt** : le dépôt personnel (comme aujourd'hui) et
  des dépôts **partagés** (un par serveur), chacun avec son état de synchronisation.
- Le cœur ne connaît qu'une **interface de transport** (lister, lire, écrire avec version, partager, retirer un droit) ;
  le plugin « Partage » en fournit l'implémentation HTTP vers le serveur.

## 5. Ce qui vient après
Étape 2 : serveur minimal (comptes, trois rôles propriétaire / écriture / lecture) et plugin. Étape 3 : fiches verrouillées
partagées (clé de contenu enveloppée une fois par membre). Étape 4 : invitations, historique, administration.
