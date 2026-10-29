<?php
declare(strict_types=1);

// Tests du serveur, sans dépendance : `php tests/run.php` (extension pdo_sqlite requise, ou SCRINIUM_TEST_DB pour MariaDB).
require __DIR__ . '/../src/autoload.php';

use Scrinium\Serveur\Application;
use Scrinium\Serveur\Base;

$ok = 0;
$echecs = [];
$tests = [];
function test(string $nom, callable $f): void { global $tests; $tests[$nom] = $f; }
function verifie(mixed $reel, mixed $attendu, string $msg = ''): void
{
    if ($reel !== $attendu) {
        throw new RuntimeException(sprintf('%s attendu %s, reçu %s', $msg, var_export($attendu, true), var_export($reel, true)));
    }
}

final class Ctx
{
    public int $t = 1_800_000_000;
    public Application $app;
    public string $dossier;

    /** @param array<string,mixed> $plus */
    public function __construct(array $plus = [])
    {
        $this->dossier = sys_get_temp_dir() . '/scrinium-test-' . bin2hex(random_bytes(4));
        // SCRINIUM_TEST_DB='{"type":"mysql",…}' : mêmes tests sur MariaDB (la base indiquée est vidée !).
        $db = getenv('SCRINIUM_TEST_DB');
        $base = $db ? Base::depuisConfig(json_decode($db, true)) : Base::memoire();
        $base->initialiser();
        if ($db) {
            foreach (['comptes', 'sessions', 'fiches', 'droits', 'blobs', 'fiche_blobs', 'invitations', 'invitation_fiches', 'essais', 'journal'] as $t) {
                $base->pdo->exec("DELETE FROM $t");
            }
        }
        $this->app = new Application($base, $plus + ['base_url' => 'https://s.test', 'donnees' => $this->dossier,
            'cout_hash' => 4], fn (): int => $this->t);
    }

    /** @return array{statut:int, entetes:array<string,string>, corps:string, json:mixed} */
    public function appel(string $m, string $chemin, mixed $corps = null, ?string $jeton = null, string $ip = '1.1.1.1'): array
    {
        $h = $jeton ? ['Authorization' => "Bearer $jeton"] : [];
        $brut = is_string($corps) ? $corps : ($corps === null ? '' : json_encode($corps));
        $r = $this->app->traiter($m, $chemin, $h, $brut, $ip);
        $r['json'] = json_decode($r['corps'], true);
        return $r;
    }

    public function compte(string $nom): string
    {
        $this->app->comptes()->creer($nom, 'motdepasse-' . $nom);
        return $this->connecter($nom);
    }

    public function connecter(string $nom): string
    {
        return $this->appel('POST', '/api/v1/session', ['compte' => $nom, 'mot_de_passe' => 'motdepasse-' . $nom])['json']['jeton'];
    }

    public function fiche(string $jeton, string $id, string $titre = 'T', string $texte = 'x'): array
    {
        return $this->appel('PUT', "/api/v1/fiches/$id", ['titre' => $titre, 'texte' => $texte, 'pieces' => [], 'version_depart' => 0], $jeton);
    }

    public function nettoyer(): void
    {
        if (is_dir($this->dossier)) {
            foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($this->dossier, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST) as $f) {
                $f->isDir() ? rmdir($f->getPathname()) : unlink($f->getPathname());
            }
            rmdir($this->dossier);
        }
    }
}

const ID = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const ID2 = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

test('découverte et en-têtes', function () {
    $c = new Ctx();
    $r = $c->appel('GET', '/api');
    verifie($r['statut'], 200);
    verifie($r['json']['api'], 1);
    verifie($r['json']['inscription'], 'invitation');
    verifie($r['entetes']['Cache-Control'], 'no-store');
    verifie($c->appel('GET', '/n-importe-quoi')['statut'], 404);
});

test('connexion : mauvais mot de passe et compte inconnu donnent la même réponse', function () {
    $c = new Ctx();
    $c->app->comptes()->creer('jfk', 'motdepasse-jfk');
    $a = $c->appel('POST', '/api/v1/session', ['compte' => 'jfk', 'mot_de_passe' => 'faux']);
    $b = $c->appel('POST', '/api/v1/session', ['compte' => 'inconnu', 'mot_de_passe' => 'faux']);
    verifie($a['statut'], 401);
    verifie($a['json'], $b['json']);
});

test('limitation des essais de connexion', function () {
    $c = new Ctx();
    $c->app->comptes()->creer('jfk', 'motdepasse-jfk');
    for ($i = 0; $i < 10; $i++) {
        verifie($c->appel('POST', '/api/v1/session', ['compte' => 'jfk', 'mot_de_passe' => 'faux'], null, "9.9.9.$i")['statut'], 401);
    }
    $r = $c->appel('POST', '/api/v1/session', ['compte' => 'jfk', 'mot_de_passe' => 'motdepasse-jfk'], null, '8.8.8.8');
    verifie($r['statut'], 429);
    verifie(isset($r['entetes']['Retry-After']), true);
    $c->t += 901;
    verifie($c->appel('POST', '/api/v1/session', ['compte' => 'jfk', 'mot_de_passe' => 'motdepasse-jfk'], null, '8.8.8.8')['statut'], 200);
});

test('session : jeton requis, expiration, déconnexion', function () {
    $c = new Ctx();
    $j = $c->compte('jfk');
    verifie($c->appel('GET', '/api/v1/fiches')['statut'], 401);
    verifie($c->appel('GET', '/api/v1/fiches', null, $j)['statut'], 200);
    verifie($c->appel('DELETE', '/api/v1/session', null, $j)['statut'], 204);
    verifie($c->appel('GET', '/api/v1/fiches', null, $j)['statut'], 401);
    $j2 = $c->connecter('jfk');
    $c->t += 31 * 86400;
    verifie($c->appel('GET', '/api/v1/fiches', null, $j2)['statut'], 401);
});

test('fiche : création, lecture, mise à jour, conflit de version', function () {
    $c = new Ctx();
    $j = $c->compte('jfk');
    $r = $c->fiche($j, ID, 'Titre', 'Texte é');
    verifie([$r['statut'], $r['json']['version']], [201, 1]);
    verifie($c->fiche($j, ID)['statut'], 409);
    $r = $c->appel('GET', '/api/v1/fiches/' . ID, null, $j);
    verifie([$r['json']['titre'], $r['json']['texte'], $r['json']['version']], ['Titre', 'Texte é', 1]);
    $r = $c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 'T2', 'texte' => 'b', 'pieces' => [], 'version_depart' => 1], $j);
    verifie([$r['statut'], $r['json']['version']], [200, 2]);
    $r = $c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 'T3', 'texte' => 'c', 'pieces' => [], 'version_depart' => 1], $j);
    verifie([$r['statut'], $r['json']['erreur'], $r['json']['version_serveur']], [409, 'version', 2]);
    $l = $c->appel('GET', '/api/v1/fiches', null, $j)['json'];
    verifie([count($l), $l[0]['role'], $l[0]['proprietaire'], $l[0]['version']], [1, 'proprietaire', 'jfk', 2]);
});

test('fiche : validation des entrées', function () {
    $c = new Ctx(['limite_texte' => 10]);
    $j = $c->compte('jfk');
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, 'pas du json', $j)['statut'], 422);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => '', 'texte' => 'x', 'version_depart' => 0], $j)['statut'], 422);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 'a', 'texte' => 'x'], $j)['statut'], 422);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 'a', 'texte' => str_repeat('x', 11), 'version_depart' => 0], $j)['statut'], 413);
    verifie($c->appel('GET', '/api/v1/fiches/pas-un-id', null, $j)['statut'], 404);
});

test('fiche invisible sans droit (404), droit insuffisant (403)', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $dede = $c->compte('dede');
    $c->fiche($jfk, ID);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $dede)['statut'], 404);
    verifie($c->appel('GET', '/api/v1/fiches', null, $dede)['json'], []);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID . '/droits/dede', ['role' => 'lecture'], $jfk)['statut'], 204);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $dede)['statut'], 200);
    $maj = ['titre' => 'x', 'texte' => 'y', 'pieces' => [], 'version_depart' => 1];
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, $maj, $dede)['statut'], 403);
    verifie($c->appel('DELETE', '/api/v1/fiches/' . ID, null, $dede)['statut'], 403);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID . '/droits', null, $dede)['statut'], 403);
    $c->appel('PUT', '/api/v1/fiches/' . ID . '/droits/dede', ['role' => 'ecriture'], $jfk);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, $maj, $dede)['statut'], 200);
});

test('droits : validation et propriétaire intouchable', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $c->compte('dede');
    $c->fiche($jfk, ID);
    $d = '/api/v1/fiches/' . ID . '/droits';
    verifie($c->appel('PUT', "$d/inconnu", ['role' => 'lecture'], $jfk)['statut'], 422);
    verifie($c->appel('PUT', "$d/dede", ['role' => 'proprietaire'], $jfk)['statut'], 422);
    verifie($c->appel('PUT', "$d/dede", ['role' => 'nimporte'], $jfk)['statut'], 422);
    verifie($c->appel('PUT', "$d/jfk", ['role' => 'lecture'], $jfk)['statut'], 403);
    verifie($c->appel('DELETE', "$d/jfk", null, $jfk)['statut'], 403);
    $c->appel('PUT', "$d/dede", ['role' => 'lecture'], $jfk);
    verifie($c->appel('GET', $d, null, $jfk)['json'], ['dede' => 'lecture', 'jfk' => 'proprietaire']);
    verifie($c->appel('DELETE', "$d/dede", null, $jfk)['statut'], 204);
    verifie($c->appel('DELETE', "$d/dede", null, $jfk)['statut'], 204);
    verifie($c->appel('GET', $d, null, $jfk)['json'], ['jfk' => 'proprietaire']);
});

test('suppression de fiche : propriétaire seulement, et tout part avec', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $c->compte('dede');
    $c->fiche($jfk, ID);
    $c->appel('PUT', '/api/v1/fiches/' . ID . '/droits/dede', ['role' => 'ecriture'], $jfk);
    verifie($c->appel('DELETE', '/api/v1/fiches/' . ID, null, $c->connecter('dede'))['statut'], 403);
    verifie($c->appel('DELETE', '/api/v1/fiches/' . ID, null, $jfk)['statut'], 204);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $jfk)['statut'], 404);
    verifie($c->appel('GET', '/api/v1/fiches', null, $c->connecter('dede'))['json'], []);
});

test('images : empreinte vérifiée, accès par les fiches', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $dede = $c->compte('dede');
    $octets = "\x89PNG\r\n" . random_bytes(50);
    $sha = hash('sha256', $octets);
    verifie($c->appel('PUT', '/api/v1/blobs/' . str_repeat('0', 64), $octets, $jfk)['statut'], 422);
    verifie($c->appel('PUT', "/api/v1/blobs/$sha", $octets, null)['statut'], 401);
    verifie($c->appel('PUT', "/api/v1/blobs/$sha", $octets, $jfk)['statut'], 204);
    verifie($c->appel('PUT', "/api/v1/blobs/$sha", $octets, $jfk)['statut'], 204);
    $piece = ['nom' => 'a.png', 'type' => 'image/png', 'taille' => strlen($octets), 'sha256' => $sha];
    $absente = ['sha256' => str_repeat('1', 64)] + $piece;
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 't', 'texte' => '', 'pieces' => [$absente], 'version_depart' => 0], $jfk)['statut'], 422);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 't', 'texte' => '', 'pieces' => [$piece], 'version_depart' => 0], $jfk)['statut'], 201);
    $r = $c->appel('GET', "/api/v1/blobs/$sha", null, $jfk);
    verifie([$r['statut'], $r['corps']], [200, $octets]);
    verifie($c->appel('GET', "/api/v1/blobs/$sha", null, $dede)['statut'], 404);
    $c->appel('PUT', '/api/v1/fiches/' . ID . '/droits/dede', ['role' => 'lecture'], $jfk);
    verifie($c->appel('GET', "/api/v1/blobs/$sha", null, $dede)['corps'], $octets);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $dede)['json']['pieces'][0]['sha256'], $sha);
    $c->nettoyer();
});

test('images : taille maximale', function () {
    $c = new Ctx(['limite_image' => 10]);
    $j = $c->compte('jfk');
    $o = str_repeat('a', 11);
    verifie($c->appel('PUT', '/api/v1/blobs/' . hash('sha256', $o), $o, $j)['statut'], 413);
});

test('invitation : scénario complet (nouvelle personne, 48 h, usage unique)', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $c->fiche($jfk, ID);
    $r = $c->appel('POST', '/api/v1/fiches/' . ID . '/invitations', ['email' => 'dede@example.org', 'role' => 'ecriture'], $jfk);
    verifie($r['statut'], 201);
    verifie(str_starts_with($r['json']['url'], 'https://s.test/inviter/'), true);
    $jeton = substr($r['json']['url'], strlen('https://s.test/inviter/'));
    verifie($r['json']['expire_le'], gmdate('Y-m-d\TH:i:s\Z', $c->t + 48 * 3600));

    $page = $c->appel('GET', "/inviter/$jeton");
    verifie($page['statut'], 200);
    verifie(str_contains($page['corps'], 'scrinium://rejoindre?serveur=https%3A%2F%2Fs.test&amp;jeton=' . $jeton), true);
    verifie(str_contains($page['corps'], 'peut les lire'), true);
    $d = $c->appel('GET', "/api/v1/invitations/$jeton");
    verifie([$d['json']['invite_par'], $d['json']['role']], ['jfk', 'ecriture']);
    verifie(count($c->appel('GET', '/api/v1/fiches/' . ID . '/invitations', null, $jfk)['json']), 1);

    $a = $c->appel('POST', "/api/v1/invitations/$jeton/accepter", ['compte' => 'dede', 'mot_de_passe' => 'court']);
    verifie($a['statut'], 422);
    $a = $c->appel('POST', "/api/v1/invitations/$jeton/accepter", ['compte' => 'dede', 'mot_de_passe' => 'un-bon-mot-de-passe']);
    verifie($a['statut'], 201);
    $dede = $a['json']['jeton'];
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $dede)['statut'], 200);
    verifie($c->appel('GET', '/api/v1/fiches', null, $dede)['json'][0]['role'], 'ecriture');
    verifie($c->appel('POST', "/api/v1/invitations/$jeton/accepter", ['compte' => 'autre', 'mot_de_passe' => 'un-bon-mot-de-passe'])['statut'], 404);
    verifie($c->appel('GET', "/api/v1/invitations/$jeton")['statut'], 404);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID . '/invitations', null, $jfk)['json'][0]['etat'], 'acceptee');
});

test('invitation : thème entier (plusieurs fiches, une seule invitation)', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $c->fiche($jfk, ID);
    $ids = [ID, str_repeat('b', 32), str_repeat('c', 32)];
    foreach (array_slice($ids, 1) as $i) {
        $c->fiche($jfk, $i);
    }
    verifie($c->appel('POST', '/api/v1/invitations', ['email' => 'a@b.fr', 'role' => 'lecture', 'fiches' => [ID, str_repeat('d', 32)]], $jfk)['statut'], 404);
    verifie($c->appel('POST', '/api/v1/invitations', ['email' => 'a@b.fr', 'role' => 'lecture', 'fiches' => []], $jfk)['statut'], 422);
    $r = $c->appel('POST', '/api/v1/invitations', ['email' => 'a@b.fr', 'role' => 'lecture', 'fiches' => $ids], $jfk);
    verifie($r['statut'], 201);
    $jeton = substr($r['json']['url'], strrpos($r['json']['url'], '/') + 1);
    verifie($c->appel('GET', "/api/v1/invitations/$jeton")['json']['fiches'], 3);
    $a = $c->appel('POST', "/api/v1/invitations/$jeton/accepter", ['compte' => 'dede', 'mot_de_passe' => 'un-bon-mot-de-passe']);
    verifie($a['statut'], 201);
    $dede = $a['json']['jeton'];
    verifie(count($c->appel('GET', '/api/v1/fiches', null, $dede)['json']), 3);
    verifie($c->appel('PUT', '/api/v1/fiches/' . ID, ['titre' => 'T', 'texte' => 'y', 'pieces' => [], 'version_depart' => 1], $dede)['statut'], 403);
});

test('invitation : expirée après 48 h, le droit déjà acquis reste', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $c->fiche($jfk, ID);
    $mk = fn () => substr($c->appel('POST', '/api/v1/fiches/' . ID . '/invitations', ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk)['json']['url'], 23);
    $vieux = $mk();
    $c->t += 48 * 3600 + 1;
    verifie($c->appel('GET', "/api/v1/invitations/$vieux")['statut'], 404);
    verifie($c->appel('GET', "/inviter/$vieux")['statut'], 404);
    verifie($c->appel('GET', '/api/v1/fiches/' . ID . '/invitations', null, $jfk)['json'][0]['etat'], 'expiree');
    $frais = $mk();
    $a = $c->appel('POST', "/api/v1/invitations/$frais/accepter", ['compte' => 'dede', 'mot_de_passe' => 'un-bon-mot-de-passe']);
    $c->t += 10 * 86400;
    verifie($c->appel('GET', '/api/v1/fiches/' . ID, null, $a['json']['jeton'])['statut'], 200);
});

test('invitation : annulation, connecté sans rétrogradation, mauvais jeton', function () {
    $c = new Ctx();
    $jfk = $c->compte('jfk');
    $dede = $c->compte('dede');
    $c->fiche($jfk, ID);
    $l = '/api/v1/fiches/' . ID . '/invitations';
    $r = $c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk)['json'];
    $jeton = substr($r['url'], 23);
    verifie($c->appel('DELETE', '/api/v1/invitations/' . $r['id'], null, $dede)['statut'], 404);
    verifie($c->appel('DELETE', '/api/v1/invitations/' . $r['id'], null, $jfk)['statut'], 204);
    verifie($c->appel('GET', "/api/v1/invitations/$jeton")['statut'], 404);

    $c->appel('PUT', '/api/v1/fiches/' . ID . '/droits/dede', ['role' => 'ecriture'], $jfk);
    $r = $c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk)['json'];
    verifie($c->appel('POST', '/api/v1/invitations/' . substr($r['url'], 23) . '/accepter', null, $dede)['statut'], 204);
    verifie($c->appel('GET', '/api/v1/fiches', null, $dede)['json'][0]['role'], 'ecriture');
    verifie($c->appel('GET', '/api/v1/invitations/' . str_repeat('0', 64))['statut'], 404);
    verifie($c->appel('POST', $l, ['email' => 'pas-un-courriel', 'role' => 'lecture'], $jfk)['statut'], 422);
    verifie($c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'proprietaire'], $jfk)['statut'], 422);
    verifie($c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $dede)['statut'], 403);
});

test('invitation : création de comptes refusée si le réglage est coupé', function () {
    $c = new Ctx(['invitations_creent_des_comptes' => false]);
    $jfk = $c->compte('jfk');
    $c->fiche($jfk, ID);
    verifie($c->appel('GET', '/api')['json']['inscription'], 'administrateur');
    $jeton = substr($c->appel('POST', '/api/v1/fiches/' . ID . '/invitations', ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk)['json']['url'], 23);
    verifie($c->appel('POST', "/api/v1/invitations/$jeton/accepter", ['compte' => 'dede', 'mot_de_passe' => 'un-bon-mot-de-passe'])['statut'], 403);
    $dede = $c->compte('dede');
    verifie($c->appel('POST', "/api/v1/invitations/$jeton/accepter", null, $dede)['statut'], 204);
});

test('invitation : quota et limitation des essais de jetons', function () {
    $c = new Ctx(['max_invitations_en_attente' => 2]);
    $jfk = $c->compte('jfk');
    $c->fiche($jfk, ID);
    $l = '/api/v1/fiches/' . ID . '/invitations';
    $c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk);
    $c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk);
    verifie($c->appel('POST', $l, ['email' => 'a@b.fr', 'role' => 'lecture'], $jfk)['statut'], 429);
    for ($i = 0; $i < 30; $i++) {
        verifie($c->appel('GET', '/api/v1/invitations/' . str_repeat('0', 64), null, null, '7.7.7.7')['statut'], 404);
    }
    verifie($c->appel('GET', '/api/v1/invitations/' . str_repeat('0', 64), null, null, '7.7.7.7')['statut'], 429);
});

test('comptes : nom et mot de passe validés, doublon refusé', function () {
    $c = new Ctx();
    $cs = $c->app->comptes();
    foreach ([['A', 'motdepasse-long'], ['x y', 'motdepasse-long'], ['ok', 'court']] as [$n, $m]) {
        try { $cs->creer($n, $m); throw new RuntimeException("accepté : $n"); } catch (Scrinium\Serveur\ErreurHttp $e) { verifie($e->statut, 422); }
    }
    $cs->creer('ok', 'motdepasse-long');
    try { $cs->creer('ok', 'motdepasse-long'); throw new RuntimeException('doublon'); } catch (Scrinium\Serveur\ErreurHttp $e) { verifie($e->statut, 422); }
    $cs->changerMotDePasse('ok', 'nouveau-mot-de-passe');
    verifie($cs->verifier('ok', 'nouveau-mot-de-passe'), true);
    verifie($cs->verifier('ok', 'motdepasse-long'), false);
});

foreach ($tests as $nom => $f) {
    try {
        $f();
        $ok++;
        echo "  ok   $nom\n";
    } catch (Throwable $e) {
        $echecs[$nom] = $e->getMessage() . ' (' . basename($e->getFile()) . ':' . $e->getLine() . ')';
        echo "  ECHEC $nom\n";
    }
}
foreach ($echecs as $nom => $msg) {
    echo "\n$nom :\n  $msg\n";
}
echo sprintf("\n%d réussis, %d échecs\n", $ok, count($echecs));
exit($echecs === [] ? 0 : 1);
