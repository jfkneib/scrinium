<?php
declare(strict_types=1);

namespace Scrinium\Serveur;

/** Erreur renvoyée telle quelle au client (voir docs/api-partage.md, § 7). */
final class ErreurHttp extends \RuntimeException
{
    private const CODES = [
        401 => 'non_authentifie',
        403 => 'refuse',
        404 => 'introuvable',
        409 => 'version',
        413 => 'trop_gros',
        422 => 'invalide',
        429 => 'trop_de_requetes',
    ];

    /** @param array<string,mixed> $extra */
    public function __construct(
        public readonly int $statut,
        string $message = '',
        public readonly array $extra = [],
        public readonly array $entetes = [],
    ) {
        parent::__construct($message);
    }

    public function code(): string
    {
        return self::CODES[$this->statut] ?? 'erreur';
    }
}
