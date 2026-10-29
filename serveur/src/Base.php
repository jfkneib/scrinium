<?php
declare(strict_types=1);

namespace Scrinium\Serveur;

use PDO;
use PDOStatement;

/** Accès à la base : SQLite (par défaut) ou MariaDB/MySQL, même SQL portable (voir schema.sql). */
final class Base
{
    private function __construct(public readonly PDO $pdo, public readonly bool $sqlite)
    {
    }

    /** @param array<string,mixed> $db */
    public static function depuisConfig(array $db): self
    {
        $type = $db['type'] ?? 'sqlite';
        if ($type === 'sqlite') {
            return self::sqlite('sqlite:' . $db['chemin']);
        }
        if ($type === 'mysql') {
            $dsn = sprintf(
                'mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4',
                $db['hote'] ?? 'localhost',
                (int) ($db['port'] ?? 3306),
                $db['nom'],
            );
            $pdo = new PDO($dsn, $db['utilisateur'], $db['mot_de_passe'], [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);
            return new self($pdo, false);
        }
        throw new \InvalidArgumentException("Type de base inconnu : $type");
    }

    public static function memoire(): self
    {
        return self::sqlite('sqlite::memory:');
    }

    private static function sqlite(string $dsn): self
    {
        $pdo = new PDO($dsn, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $pdo->exec('PRAGMA busy_timeout = 5000');
        if (!str_contains($dsn, ':memory:')) {
            $pdo->exec('PRAGMA journal_mode = WAL');
        }
        return new self($pdo, true);
    }

    public function initialiser(): void
    {
        $sql = (string) file_get_contents(__DIR__ . '/../schema.sql');
        foreach (explode(';', $sql) as $instruction) {
            if (trim($instruction) !== '') {
                $this->pdo->exec($instruction);
            }
        }
    }

    /** @param list<mixed> $p */
    public function requete(string $sql, array $p = []): PDOStatement
    {
        $r = $this->pdo->prepare($sql);
        $r->execute($p);
        return $r;
    }

    /** @param list<mixed> $p @return array<string,mixed>|null */
    public function ligne(string $sql, array $p = []): ?array
    {
        $l = $this->requete($sql, $p)->fetch();
        return $l === false ? null : $l;
    }

    /** @param list<mixed> $p @return list<array<string,mixed>> */
    public function lignes(string $sql, array $p = []): array
    {
        return $this->requete($sql, $p)->fetchAll();
    }

    /** @param list<mixed> $p */
    public function valeur(string $sql, array $p = []): mixed
    {
        $v = $this->requete($sql, $p)->fetchColumn();
        return $v === false ? null : $v;
    }

    public function transaction(callable $f): mixed
    {
        $this->pdo->beginTransaction();
        try {
            $r = $f();
            $this->pdo->commit();
            return $r;
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }
    }

    public function journal(int $instant, ?string $compte, string $action, string $detail = ''): void
    {
        $this->requete(
            'INSERT INTO journal (instant, compte, action, detail) VALUES (?, ?, ?, ?)',
            [$instant, $compte, $action, mb_substr($detail, 0, 500)],
        );
    }
}
