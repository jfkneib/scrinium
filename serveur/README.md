# Serveur Scrinium

Petit serveur PHP qui permet de **partager des fiches** entre plusieurs Scrinium (extension « Partage »). Contrat : [`docs/api-partage.md`](../docs/api-partage.md).
Chacun garde son Scrinium personnel ; seules les fiches choisies passent par le serveur, avec les rôles propriétaire / écriture / lecture.

Prérequis : Apache (ou autre) + PHP ≥ 8.1 avec `pdo_sqlite` (ou `pdo_mysql`), `mbstring`, HTTPS.

## Installation (une seule personne, l'administrateur)
1. Copier le dossier `serveur/` sur la machine, p. ex. dans `/srv/scrinium/serveur`. **Seul `public/` est exposé par le web.**
2. Créer le dossier de données, inscriptible par Apache, hors du dossier web :
   `sudo install -d -o www-data -g www-data -m 750 /srv/scrinium/donnees`
3. `cp config.example.php config.php`, puis adapter `base_url`, `donnees` et `db` (SQLite par défaut ; MariaDB : voir le fichier). Garder `config.php` hors de `public/`.
4. Initialiser la base et créer le premier compte (en tant qu'utilisateur d'Apache, pour que les fichiers lui appartiennent) :
   ```bash
   sudo -u www-data bin/scrinium-serveur initialiser
   sudo -u www-data bin/scrinium-serveur creer-compte jfk --admin
   ```
5. Apache : un hôte virtuel HTTPS dont la racine est `public/`, avec la réécriture de tout vers `index.php` :
   ```apache
   DocumentRoot /srv/scrinium/serveur/public
   <Directory /srv/scrinium/serveur/public>
       Require all granted
       FallbackResource /index.php
       SetEnvIf Authorization "(.+)" HTTP_AUTHORIZATION=$1
   </Directory>
   ```
   (`FallbackResource` envoie `/api/...` et `/inviter/...` vers `index.php`.)
6. Vérifier : `curl https://votre-serveur/api` doit répondre `{"api":1,…}`.

## Administration
`bin/scrinium-serveur` : `initialiser`, `creer-compte NOM [--admin]`, `mot-de-passe NOM`, `comptes`.

**Mise à jour** : remplacez le dossier `serveur/` (sauf `config.php`), puis relancez `bin/scrinium-serveur initialiser` : il ne crée que les tables manquantes (v0.2 : `invitation_fiches`, invitations à plusieurs fiches).
Les invitations créent des comptes par défaut ; pour que seul l'administrateur en crée, mettre `'invitations_creent_des_comptes' => false`.

## Sauvegarde
Sauvegarder le dossier de données entier (base SQLite + `blobs/`) et `config.php`. Le serveur peut lire les fiches non verrouillées : à dire aux invités.

## Tests
`php tests/run.php` (sans dépendance ; exige `pdo_sqlite`). Sur MariaDB : `SCRINIUM_TEST_DB='{"type":"mysql",…}' php tests/run.php` (la base indiquée est **vidée**, prendre une base de test).

Après l'installation d'une extension PHP, **redémarrer** Apache (`restart`, pas `reload`) : mod_php ne la voit pas autrement.


## Derrière un proxy inverse (Caddy, nginx…)

Le serveur peut être publié sous un sous-dossier d'un site existant, par exemple `https://exemple.org/scrinium` :

1. Le proxy retire le préfixe `/scrinium` avant de passer la requête au serveur (voir [`caddy/Caddyfile.exemple`](caddy/Caddyfile.exemple)).
2. `config.php` : `'base_url' => 'https://exemple.org/scrinium'` (les liens d'invitation portent le préfixe) et
   `'proxies_de_confiance' => ['<adresse du proxy>']`. **Cette dernière ligne est importante** : sans elle, tous les clients
   ont l'adresse du proxy et la limitation des essais de connexion les compte ensemble (un seul attaquant bloquerait tout le monde).
   Le serveur ne croit `X-Forwarded-For` que si la connexion vient d'un proxy déclaré.
3. Dans Scrinium, l'adresse du serveur est celle avec le préfixe.
4. Le proxy ne doit pas demander d'authentification supplémentaire (Authelia…) sur ce chemin : le serveur gère ses comptes.


## Déposer une fiche depuis n'importe quel programme

Un **jeton de dépôt** permet d'ajouter des fiches à un compte, **sans rien pouvoir lire ni modifier** : on peut le mettre dans un script,
un raccourci de téléphone ou un outil d'automatisation sans exposer le mot de passe. Un jeton par usage, révocable.

```bash
# sur le serveur : créer un jeton (il n'est montré qu'une fois), lister, révoquer
sudo -u www-data php bin/scrinium-serveur creer-jeton jfk "raccourci du téléphone"
sudo -u www-data php bin/scrinium-serveur jetons
sudo -u www-data php bin/scrinium-serveur revoquer-jeton <id>

# depuis n'importe où : créer une fiche
curl -X POST https://serveur/api/v1/depot -H "Authorization: Bearer <jeton>" \
     -H "Content-Type: application/json" -d '{"titre": "Idée", "texte": "Penser au certificat"}'
# ou du texte brut (titre = première ligne, ou en-tête X-Titre)
df -h | curl -X POST https://serveur/api/v1/depot -H "Authorization: Bearer <jeton>" -H "X-Titre: Disque" --data-binary @-
```

La fiche arrive dans Scrinium à la prochaine synchronisation (*Extensions → Synchroniser les partages*). Limites : 256 Kio de texte,
60 dépôts par heure et par jeton. Les textes déposés ne sont **pas chiffrés** pour le serveur : rien de secret.
