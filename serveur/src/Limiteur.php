<?php
declare(strict_types=1);

namespace Scrinium\Serveur;

/** Limitation des essais : au plus $max échecs par fenêtre glissante, par clé (compte, adresse…). */
final class Limiteur
{
    /** @param callable():int $horloge */
    public function __construct(private Base $base, private $horloge)
    {
    }

    public function verifier(string $cle, int $max, int $fenetre): void
    {
        $depuis = ($this->horloge)() - $fenetre;
        $this->base->requete('DELETE FROM essais WHERE instant < ?', [$depuis]);
        $n = (int) $this->base->valeur('SELECT COUNT(*) FROM essais WHERE cle = ? AND instant >= ?', [hash('sha256', $cle), $depuis]);
        if ($n >= $max) {
            throw new ErreurHttp(429, 'Trop d’essais, réessayez plus tard.', [], ['Retry-After' => (string) $fenetre]);
        }
    }

    public function echec(string $cle): void
    {
        $this->base->requete('INSERT INTO essais (cle, instant) VALUES (?, ?)', [hash('sha256', $cle), ($this->horloge)()]);
    }
}
