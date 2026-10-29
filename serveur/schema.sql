-- Schéma portable SQLite / MariaDB (types simples, pas de syntaxe propre à un moteur).
-- Les instructions sont séparées par des points-virgules : pas de point-virgule dans les commentaires.

CREATE TABLE IF NOT EXISTS comptes (
    nom VARCHAR(64) NOT NULL PRIMARY KEY,
    email VARCHAR(255) NULL,
    hash VARCHAR(255) NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    cree_le INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    hash VARCHAR(64) NOT NULL PRIMARY KEY,
    compte VARCHAR(64) NOT NULL,
    expire_le INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fiches (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    version INTEGER NOT NULL,
    titre VARCHAR(500) NOT NULL,
    texte LONGTEXT NOT NULL,
    pieces LONGTEXT NOT NULL,
    proprietaire VARCHAR(64) NOT NULL,
    modifie_le INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS droits (
    fiche_id VARCHAR(32) NOT NULL,
    compte VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    PRIMARY KEY (fiche_id, compte)
);

CREATE TABLE IF NOT EXISTS blobs (
    sha256 VARCHAR(64) NOT NULL PRIMARY KEY,
    taille INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fiche_blobs (
    fiche_id VARCHAR(32) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    PRIMARY KEY (fiche_id, sha256)
);

CREATE TABLE IF NOT EXISTS invitations (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    jeton_hash VARCHAR(64) NOT NULL UNIQUE,
    fiche_id VARCHAR(32) NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL,
    par VARCHAR(64) NOT NULL,
    etat VARCHAR(16) NOT NULL,
    cree_le INTEGER NOT NULL,
    expire_le INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS essais (
    cle VARCHAR(190) NOT NULL,
    instant INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    instant INTEGER NOT NULL,
    compte VARCHAR(64) NULL,
    action VARCHAR(64) NOT NULL,
    detail VARCHAR(500) NOT NULL
);
