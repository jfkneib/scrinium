<?php
// Copier en config.php (hors du dossier web si possible, sinon variable SCRINIUM_CONFIG) puis adapter.
return [
    // Adresse publique du serveur, sans « / » final : sert aux liens d'invitation.
    'base_url' => 'https://scrinium.exemple.org',

    // Dossier des données (images). Hors du dossier web, inscriptible par Apache.
    'donnees' => '/srv/scrinium/donnees',

    // Base de données : SQLite (rien à installer) ou MariaDB/MySQL.
    'db' => ['type' => 'sqlite', 'chemin' => '/srv/scrinium/donnees/scrinium.sqlite'],
    // 'db' => ['type' => 'mysql', 'hote' => '127.0.0.1', 'nom' => 'scrinium', 'utilisateur' => 'scrinium', 'mot_de_passe' => '…'],

    // Accepter une invitation sans compte en crée un (false : l'administrateur crée d'abord les comptes).
    'invitations_creent_des_comptes' => true,
    'max_invitations_en_attente' => 20,
];
