<?php
declare(strict_types=1);

namespace Scrinium\Serveur;

/** Comptes, mots de passe et sessions (jetons stockés hachés). */
final class Comptes
{
    private ?string $hashFactice = null;

    /** @param callable():int $horloge */
    public function __construct(private Base $base, private array $config, private $horloge)
    {
    }

    private function maintenant(): int
    {
        return ($this->horloge)();
    }

    private function hasher(string $mdp): string
    {
        return password_hash($mdp, PASSWORD_BCRYPT, ['cost' => (int) ($this->config['cout_hash'] ?? 12)]);
    }

    public function existe(string $nom): bool
    {
        return $this->base->valeur('SELECT 1 FROM comptes WHERE nom = ?', [$nom]) !== null;
    }

    public function creer(string $nom, string $mdp, ?string $email = null, bool $admin = false): void
    {
        if (!preg_match('/^[a-z0-9][a-z0-9_.-]{1,31}$/', $nom)) {
            throw new ErreurHttp(422, 'Nom de compte : 2 à 32 caractères parmi a-z, 0-9, « _ », « . » et « - ».');
        }
        if (mb_strlen($mdp) < 10) {
            throw new ErreurHttp(422, 'Le mot de passe doit faire au moins 10 caractères.');
        }
        if ($this->existe($nom)) {
            throw new ErreurHttp(422, 'Ce nom de compte est déjà pris.');
        }
        $this->base->requete(
            'INSERT INTO comptes (nom, email, hash, admin, cree_le) VALUES (?, ?, ?, ?, ?)',
            [$nom, $email, $this->hasher($mdp), $admin ? 1 : 0, $this->maintenant()],
        );
    }

    public function changerMotDePasse(string $nom, string $mdp): void
    {
        if (mb_strlen($mdp) < 10) {
            throw new ErreurHttp(422, 'Le mot de passe doit faire au moins 10 caractères.');
        }
        $this->base->requete('UPDATE comptes SET hash = ? WHERE nom = ?', [$this->hasher($mdp), $nom]);
        $this->base->requete('DELETE FROM sessions WHERE compte = ?', [$nom]);
    }

    /** Même durée de calcul que le compte existe ou non. */
    public function verifier(string $nom, string $mdp): bool
    {
        $hash = $this->base->valeur('SELECT hash FROM comptes WHERE nom = ?', [$nom]);
        if ($hash === null) {
            $this->hashFactice ??= $this->hasher('compte-inexistant');
            password_verify($mdp, $this->hashFactice);
            return false;
        }
        return password_verify($mdp, (string) $hash);
    }

    /** @return array{jeton:string, expire_le:int} */
    public function ouvrirSession(string $nom): array
    {
        $jeton = bin2hex(random_bytes(32));
        $expire = $this->maintenant() + (int) ($this->config['duree_session'] ?? 30 * 86400);
        $this->base->requete(
            'INSERT INTO sessions (hash, compte, expire_le) VALUES (?, ?, ?)',
            [hash('sha256', $jeton), $nom, $expire],
        );
        $this->base->requete('DELETE FROM sessions WHERE expire_le < ?', [$this->maintenant()]);
        return ['jeton' => $jeton, 'expire_le' => $expire];
    }

    public function compteDuJeton(string $jeton): ?string
    {
        $c = $this->base->valeur(
            'SELECT compte FROM sessions WHERE hash = ? AND expire_le >= ?',
            [hash('sha256', $jeton), $this->maintenant()],
        );
        return $c === null ? null : (string) $c;
    }

    public function fermerSession(string $jeton): void
    {
        $this->base->requete('DELETE FROM sessions WHERE hash = ?', [hash('sha256', $jeton)]);
    }
}
