<?php
// Copier en config.php (hors du dossier web si possible, sinon variable SCRINIUM_CONFIG) puis adapter.
return [
    // Adresse publique du serveur, sans « / » final : sert aux liens d'invitation. Elle peut porter un préfixe de chemin
    // quand un proxy inverse sert le serveur sous un sous-dossier (ex. 'https://exemple.org/scrinium', voir caddy/).
    'base_url' => 'https://scrinium.exemple.org',

    // Derrière un proxy inverse (Caddy, nginx…) : adresses des proxys dont on croit l'en-tête X-Forwarded-For. Sans cela, tous les
    // clients ont l'adresse du proxy et la limitation des essais de connexion les compte ensemble. Vide = pas de proxy.
    // 'proxies_de_confiance' => ['192.0.2.10'],           // (exemple : l'adresse de votre proxy, vue du serveur)

    // Dossier des données (images). Hors du dossier web, inscriptible par Apache.
    'donnees' => '/srv/scrinium/donnees',

    // Base de données : SQLite (rien à installer) ou MariaDB/MySQL.
    'db' => ['type' => 'sqlite', 'chemin' => '/srv/scrinium/donnees/scrinium.sqlite'],
    // 'db' => ['type' => 'mysql', 'hote' => '127.0.0.1', 'nom' => 'scrinium', 'utilisateur' => 'scrinium', 'mot_de_passe' => '…'],

    // Accepter une invitation sans compte en crée un (false : l'administrateur crée d'abord les comptes).
    'invitations_creent_des_comptes' => true,
    'max_invitations_en_attente' => 20,

    // Dépôt de fiches par une simple requête POST (voir README) : taille maximale du texte et nombre de dépôts par heure et par jeton.
    // 'depot_taille_max' => 262144,
    // 'depot_max_par_heure' => 60,
];
