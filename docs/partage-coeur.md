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

## 2. Détection des changements — À FAIRE
Pour synchroniser, il faut savoir ce qui a changé **depuis la dernière synchronisation**, sans rien envoyer inutilement.
- Un **état de synchronisation** par dépôt (fichier local, hors des fiches) : pour chaque identifiant, la dernière version connue du
  serveur, l'empreinte (SHA-256) du contenu synchronisé et le chemin local.
- Changement local = empreinte actuelle ≠ empreinte synchronisée ; création = fiche partagée sans entrée ; suppression = entrée sans
  fiche (la corbeille garde une copie) ; les **pièces jointes** (`.pj`) font partie du contenu.
- Le calcul se fait au démarrage, à l'enregistrement et à la demande ; jamais d'écriture sur une fiche non partagée.

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
