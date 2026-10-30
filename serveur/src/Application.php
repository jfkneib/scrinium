<?php
declare(strict_types=1);

namespace Scrinium\Serveur;

/**
 * Serveur Scrinium : routes de l'API v1 (voir docs/api-partage.md).
 * `traiter()` ne touche ni à $_SERVER ni à la sortie : public/index.php et les tests l'appellent de la même façon.
 */
final class Application
{
    public const VERSION = '0.3.0';

    /**
     * Adresse du client. Derrière un proxy inverse (Caddy, nginx…), REMOTE_ADDR est celle du proxy : on lit alors l'en-tête
     * X-Forwarded-For, mais SEULEMENT si la connexion vient d'un proxy déclaré (`proxies_de_confiance`), en remontant la chaîne
     * depuis la droite jusqu'à la première adresse qui n'est pas un proxy de confiance. Sinon l'en-tête est ignoré (il se falsifie).
     *
     * @param array<string,mixed> $serveur $_SERVER @param list<string> $proxies
     */
    public static function adresseClient(array $serveur, array $proxies): string
    {
        $direct = (string) ($serveur['REMOTE_ADDR'] ?? '-');
        $transmis = (string) ($serveur['HTTP_X_FORWARDED_FOR'] ?? '');
        if ($proxies === [] || !in_array($direct, $proxies, true) || $transmis === '') {
            return $direct;
        }
        $chaine = array_map('trim', explode(',', $transmis));
        for ($i = count($chaine) - 1; $i >= 0; $i--) {
            $a = $chaine[$i];
            if (filter_var($a, FILTER_VALIDATE_IP) === false) {
                return $direct;                                   // chaîne illisible : on ne se fie à rien
            }
            if (!in_array($a, $proxies, true)) {
                return $a;
            }
        }
        return $direct;
    }
    private const ROLES = ['lecture' => 1, 'ecriture' => 2, 'proprietaire' => 3];

    private Comptes $comptes;
    private Limiteur $limiteur;
    /** @var callable():int */
    private $horloge;
    /** @var array<string,mixed> */
    private array $cfg;

    /** @param array<string,mixed> $config @param (callable():int)|null $horloge */
    public function __construct(private Base $base, array $config, ?callable $horloge = null)
    {
        $this->horloge = $horloge ?? static fn (): int => time();
        $this->cfg = $config + [
            'base_url' => '',
            'donnees' => sys_get_temp_dir() . '/scrinium-donnees',
            'invitations_creent_des_comptes' => true,
            'max_invitations_en_attente' => 20,
            'duree_session' => 30 * 86400,
            'duree_invitation' => 48 * 3600,
            'cout_hash' => 12,
            'limite_image' => 8 * 1024 * 1024,
            'limite_pieces' => 50,
            'limite_fiche' => 100 * 1024 * 1024,
            'limite_texte' => 1024 * 1024,
            'depot_taille_max' => 256 * 1024,        // octets de texte par dépôt
            'depot_max_par_heure' => 60,             // dépôts par heure et par jeton (ou compte)
        ];
        $this->comptes = new Comptes($base, $this->cfg, $this->horloge);
        $this->limiteur = new Limiteur($base, $this->horloge);
    }

    public function comptes(): Comptes
    {
        return $this->comptes;
    }

    private function maintenant(): int
    {
        return ($this->horloge)();
    }

    private static function iso(int $t): string
    {
        return gmdate('Y-m-d\TH:i:s\Z', $t);
    }

    /**
     * @param array<string,string> $entetes
     * @return array{statut:int, entetes:array<string,string>, corps:string}
     */
    public function traiter(string $methode, string $chemin, array $entetes, string $corps, string $ip = '-'): array
    {
        $entetes = array_change_key_case($entetes, CASE_LOWER);
        $base = [
            'Cache-Control' => 'no-store',
            'X-Content-Type-Options' => 'nosniff',
            'Referrer-Policy' => 'no-referrer',
        ];
        try {
            $max = max($this->cfg['limite_image'], 2 * $this->cfg['limite_texte']) + 4096;
            if (strlen($corps) > $max) {
                throw new ErreurHttp(413, 'Requête trop volumineuse.');
            }
            [$statut, $data, $type, $plus] = $this->router($methode, $chemin, $entetes, $corps, $ip);
        } catch (ErreurHttp $e) {
            $data = ['erreur' => $e->code(), 'message' => $e->getMessage()] + $e->extra;
            return $this->reponse($e->statut, $data, 'application/json; charset=utf-8', $base + $e->entetes);
        } catch (\Throwable $e) {
            error_log('scrinium-serveur : ' . $e);
            return $this->reponse(500, ['erreur' => 'interne', 'message' => 'Erreur interne du serveur.'],
                'application/json; charset=utf-8', $base);
        }
        return $this->reponse($statut, $data, $type, $base + $plus);
    }

    /** @param array<string,string> $entetes @return array{int,mixed,string,array<string,string>} */
    private function reponse(int $statut, mixed $data, string $type, array $entetes): array
    {
        $json = str_starts_with($type, 'application/json');
        $corps = $data === null ? '' : ($json ? json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : (string) $data);
        if ($statut !== 204 && $corps !== '') {
            $entetes['Content-Type'] = $type;
        }
        return ['statut' => $statut, 'entetes' => $entetes, 'corps' => $corps];
    }

    /** @param array<string,string> $e @return array{int,mixed,string,array<string,string>} */
    private function router(string $m, string $chemin, array $e, string $corps, string $ip): array
    {
        $json = 'application/json; charset=utf-8';
        $chemin = '/' . trim($chemin, '/');

        if ($m === 'GET' && $chemin === '/api') {
            return [200, $this->decouverte(), $json, []];
        }
        if ($m === 'GET' && preg_match('#^/inviter/([0-9a-f]{64})$#', $chemin, $r)) {
            return $this->pageInvitation($r[1], $ip);
        }
        if (!str_starts_with($chemin, '/api/v1')) {
            throw new ErreurHttp(404, 'Introuvable.');
        }
        $chemin = substr($chemin, 7) ?: '/';
        $jeton = null;
        if (preg_match('/^Bearer ([0-9a-f]{64})$/', $e['authorization'] ?? '', $r)) {
            $jeton = $r[1];
        }
        $compte = $jeton !== null ? $this->comptes->compteDuJeton($jeton) : null;
        $requis = static function () use (&$compte): string {
            if ($compte === null) {
                throw new ErreurHttp(401, 'Connexion requise.');
            }
            return $compte;
        };
        $ok = static fn (int $s, mixed $d = null): array => [$s, $d, 'application/json; charset=utf-8', []];

        // Session
        if ($chemin === '/session' && $m === 'POST') {
            return $ok(200, $this->ouvrirSession($this->corpsJson($corps), $ip));
        }
        if ($chemin === '/session' && $m === 'DELETE') {
            $requis();
            $this->comptes->fermerSession((string) $jeton);
            return $ok(204);
        }
        // Invitations publiques
        if (preg_match('#^/invitations/([0-9a-f]{64})$#', $chemin, $r) && $m === 'GET') {
            return $ok(200, $this->decrireInvitation($r[1], $ip));
        }
        if (preg_match('#^/invitations/([0-9a-f]{64})/accepter$#', $chemin, $r) && $m === 'POST') {
            return $this->accepterInvitation($r[1], $compte, $this->corpsJson($corps, true), $ip);
        }
        // Dépôt : un jeton de dépôt (ajout seulement) ou une session de ce compte
        if ($chemin === '/depot' && $m === 'POST') {
            $jd = $jeton !== null ? $this->comptes->jetonDepot($jeton) : null;
            if ($jd === null && $compte === null) {
                throw new ErreurHttp(401, 'Jeton de dépôt ou connexion requis.');
            }
            return $this->deposer($jd['compte'] ?? (string) $compte, $jd['id'] ?? 'session:' . $compte, $e, $corps);
        }
        // Reste : connecté
        if ($chemin === '/fiches' && $m === 'GET') {
            return $ok(200, $this->listerFiches($requis()));
        }
        if (preg_match('#^/fiches/([0-9a-f]{32})$#', $chemin, $r)) {
            $id = $r[1];
            return match ($m) {
                'GET' => $ok(200, $this->lireFiche($requis(), $id)),
                'PUT' => $this->ecrireFiche($requis(), $id, $this->corpsJson($corps)),
                'DELETE' => $this->supprimerFiche($requis(), $id),
                default => throw new ErreurHttp(405, 'Méthode non permise.'),
            };
        }
        if (preg_match('#^/blobs/([0-9a-f]{64})$#', $chemin, $r)) {
            $sha = $r[1];
            if ($m === 'PUT') {
                $this->deposerBlob($requis(), $sha, $corps);
                return $ok(204);
            }
            if ($m === 'GET') {
                return [200, $this->lireBlob($requis(), $sha), 'application/octet-stream', []];
            }
        }
        if (preg_match('#^/fiches/([0-9a-f]{32})/droits(?:/([a-z0-9][a-z0-9_.-]{1,31}))?$#', $chemin, $r)) {
            $id = $r[1];
            $cible = $r[2] ?? null;
            if ($cible === null && $m === 'GET') {
                return $ok(200, $this->listerDroits($requis(), $id));
            }
            if ($cible !== null && $m === 'PUT') {
                $this->fixerDroit($requis(), $id, $cible, $this->corpsJson($corps));
                return $ok(204);
            }
            if ($cible !== null && $m === 'DELETE') {
                $this->retirerDroit($requis(), $id, $cible);
                return $ok(204);
            }
        }
        if (preg_match('#^/fiches/([0-9a-f]{32})/invitations$#', $chemin, $r)) {
            if ($m === 'POST') {
                return $ok(201, $this->creerInvitation($requis(), $r[1], $this->corpsJson($corps)));
            }
            if ($m === 'GET') {
                return $ok(200, $this->listerInvitations($requis(), $r[1]));
            }
        }
        if ($chemin === '/invitations' && $m === 'POST') {
            return $ok(201, $this->creerInvitationGroupe($requis(), $this->corpsJson($corps)));
        }
        if (preg_match('#^/invitations/([0-9a-f]{32})$#', $chemin, $r) && $m === 'DELETE') {
            $this->annulerInvitation($requis(), $r[1]);
            return $ok(204);
        }
        throw new ErreurHttp(404, 'Introuvable.');
    }

    /** @return array<string,mixed> */
    private function corpsJson(string $corps, bool $vide_ok = false): array
    {
        if (trim($corps) === '' && $vide_ok) {
            return [];
        }
        $d = json_decode($corps, true);
        if (!is_array($d) || array_is_list($d) && $d !== []) {
            throw new ErreurHttp(422, 'Corps JSON attendu (objet).');
        }
        return $d;
    }

    /** @return array<string,mixed> */
    private function decouverte(): array
    {
        return [
            'api' => 1,
            'serveur' => self::VERSION,
            'inscription' => $this->cfg['invitations_creent_des_comptes'] ? 'invitation' : 'administrateur',
            'limites' => ['image' => $this->cfg['limite_image'], 'pieces' => $this->cfg['limite_pieces']],
        ];
    }

    // --- Session -----------------------------------------------------------------------------------------------

    /** @param array<string,mixed> $c @return array<string,mixed> */
    private function ouvrirSession(array $c, string $ip): array
    {
        $nom = is_string($c['compte'] ?? null) ? $c['compte'] : '';
        $mdp = is_string($c['mot_de_passe'] ?? null) ? $c['mot_de_passe'] : '';
        $this->limiteur->verifier('connexion-ip:' . $ip, 30, 900);
        $this->limiteur->verifier('connexion-compte:' . $nom, 10, 900);
        if ($nom === '' || !$this->comptes->verifier($nom, $mdp)) {
            $this->limiteur->echec('connexion-ip:' . $ip);
            $this->limiteur->echec('connexion-compte:' . $nom);
            $this->base->journal($this->maintenant(), null, 'connexion_refusee', $nom);
            throw new ErreurHttp(401, 'Compte ou mot de passe incorrect.');
        }
        $s = $this->comptes->ouvrirSession($nom);
        $this->base->journal($this->maintenant(), $nom, 'connexion');
        return ['jeton' => $s['jeton'], 'expire_le' => self::iso($s['expire_le']), 'compte' => $nom];
    }

    // --- Droits ------------------------------------------------------------------------------------------------

    /** Rôle du compte sur la fiche ; 404 si aucun accès, 403 si inférieur au minimum. */
    private function exiger(string $compte, string $id, string $minimum): string
    {
        $role = $this->base->valeur('SELECT role FROM droits WHERE fiche_id = ? AND compte = ?', [$id, $compte]);
        if ($role === null) {
            throw new ErreurHttp(404, 'Fiche introuvable.');
        }
        if (self::ROLES[$role] < self::ROLES[$minimum]) {
            throw new ErreurHttp(403, 'Droit insuffisant sur cette fiche.');
        }
        return (string) $role;
    }

    /** @return array<string,string> */
    private function listerDroits(string $compte, string $id): array
    {
        $this->exiger($compte, $id, 'proprietaire');
        $out = [];
        foreach ($this->base->lignes('SELECT compte, role FROM droits WHERE fiche_id = ? ORDER BY compte', [$id]) as $l) {
            $out[$l['compte']] = $l['role'];
        }
        return $out;
    }

    /** @param array<string,mixed> $c */
    private function fixerDroit(string $compte, string $id, string $cible, array $c): void
    {
        $this->exiger($compte, $id, 'proprietaire');
        $role = $c['role'] ?? null;
        if (!is_string($role) || !in_array($role, ['lecture', 'ecriture'], true)) {
            throw new ErreurHttp(422, 'Rôle invalide (lecture ou ecriture).');
        }
        if (!$this->comptes->existe($cible)) {
            throw new ErreurHttp(422, 'Compte inconnu.');
        }
        $this->accorder($id, $cible, $role);
        $this->base->journal($this->maintenant(), $compte, 'droit', "$id $cible $role");
    }

    /** Ajoute ou remplace un droit, sans jamais toucher à celui du propriétaire. */
    private function accorder(string $id, string $cible, string $role): void
    {
        $actuel = $this->base->valeur('SELECT role FROM droits WHERE fiche_id = ? AND compte = ?', [$id, $cible]);
        if ($actuel === 'proprietaire') {
            throw new ErreurHttp(403, 'Le droit du propriétaire ne se change pas.');
        }
        if ($actuel === null) {
            $this->base->requete('INSERT INTO droits (fiche_id, compte, role) VALUES (?, ?, ?)', [$id, $cible, $role]);
        } else {
            $this->base->requete('UPDATE droits SET role = ? WHERE fiche_id = ? AND compte = ?', [$role, $id, $cible]);
        }
    }

    private function retirerDroit(string $compte, string $id, string $cible): void
    {
        $this->exiger($compte, $id, 'proprietaire');
        $role = $this->base->valeur('SELECT role FROM droits WHERE fiche_id = ? AND compte = ?', [$id, $cible]);
        if ($role === 'proprietaire') {
            throw new ErreurHttp(403, 'Le propriétaire ne peut pas se retirer.');
        }
        $this->base->requete('DELETE FROM droits WHERE fiche_id = ? AND compte = ?', [$id, $cible]);
        $this->base->journal($this->maintenant(), $compte, 'droit_retire', "$id $cible");
    }

    // --- Fiches ------------------------------------------------------------------------------------------------

    /** @return list<array<string,mixed>> */
    private function listerFiches(string $compte): array
    {
        $out = [];
        $sql = 'SELECT f.id, f.version, f.titre, f.proprietaire, f.modifie_le, d.role FROM fiches f '
            . 'JOIN droits d ON d.fiche_id = f.id WHERE d.compte = ? ORDER BY f.modifie_le DESC, f.id';
        foreach ($this->base->lignes($sql, [$compte]) as $l) {
            $out[] = ['id' => $l['id'], 'version' => (int) $l['version'], 'titre' => $l['titre'], 'role' => $l['role'],
                'proprietaire' => $l['proprietaire'], 'modifie_le' => self::iso((int) $l['modifie_le'])];
        }
        return $out;
    }

    /** @return array<string,mixed> */
    private function lireFiche(string $compte, string $id): array
    {
        $this->exiger($compte, $id, 'lecture');
        $f = $this->base->ligne('SELECT id, version, titre, texte, pieces FROM fiches WHERE id = ?', [$id]);
        if ($f === null) {
            throw new ErreurHttp(404, 'Fiche introuvable.');
        }
        return ['id' => $f['id'], 'version' => (int) $f['version'], 'titre' => $f['titre'], 'texte' => $f['texte'],
            'pieces' => json_decode((string) $f['pieces'], true) ?: []];
    }

    /** @param array<string,mixed> $c @return array{int,mixed,string,array<string,string>} */
    private function ecrireFiche(string $compte, string $id, array $c): array
    {
        $depart = $c['version_depart'] ?? null;
        if (!is_int($depart) || $depart < 0) {
            throw new ErreurHttp(422, 'version_depart (entier ≥ 0) requise.');
        }
        $titre = $c['titre'] ?? null;
        $texte = $c['texte'] ?? null;
        if (!is_string($titre) || $titre === '' || mb_strlen($titre) > 500 || !is_string($texte)) {
            throw new ErreurHttp(422, 'Titre (1 à 500 caractères) et texte requis.');
        }
        if (strlen($texte) > $this->cfg['limite_texte']) {
            throw new ErreurHttp(413, 'Texte trop long.');
        }
        $pieces = $this->validerPieces($c['pieces'] ?? []);
        $json = json_encode($pieces, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        $t = $this->maintenant();
        $type = 'application/json; charset=utf-8';

        $version = $this->base->transaction(function () use ($compte, $id, $depart, $titre, $texte, $pieces, $json, $t): int {
            $actuelle = $this->base->valeur('SELECT version FROM fiches WHERE id = ?', [$id]);
            if ($depart === 0) {
                if ($actuelle !== null) {
                    throw new ErreurHttp(409, 'Cette fiche existe déjà.', ['version_serveur' => (int) $actuelle]);
                }
                $this->base->requete(
                    'INSERT INTO fiches (id, version, titre, texte, pieces, proprietaire, modifie_le) VALUES (?, 1, ?, ?, ?, ?, ?)',
                    [$id, $titre, $texte, $json, $compte, $t],
                );
                $this->base->requete('INSERT INTO droits (fiche_id, compte, role) VALUES (?, ?, ?)', [$id, $compte, 'proprietaire']);
                $nouvelle = 1;
            } else {
                $this->exiger($compte, $id, 'ecriture');
                if ((int) $actuelle !== $depart) {
                    throw new ErreurHttp(409, 'La fiche a changé sur le serveur.', ['version_serveur' => (int) $actuelle]);
                }
                $nouvelle = $depart + 1;
                $n = $this->base->requete(
                    'UPDATE fiches SET version = ?, titre = ?, texte = ?, pieces = ?, modifie_le = ? WHERE id = ? AND version = ?',
                    [$nouvelle, $titre, $texte, $json, $t, $id, $depart],
                )->rowCount();
                if ($n !== 1) {
                    throw new ErreurHttp(409, 'La fiche a changé sur le serveur.', ['version_serveur' => $depart + 1]);
                }
            }
            $this->base->requete('DELETE FROM fiche_blobs WHERE fiche_id = ?', [$id]);
            foreach (array_unique(array_column($pieces, 'sha256')) as $sha) {
                $this->base->requete('INSERT INTO fiche_blobs (fiche_id, sha256) VALUES (?, ?)', [$id, $sha]);
            }
            return $nouvelle;
        });
        $this->base->journal($t, $compte, $depart === 0 ? 'fiche_creee' : 'fiche_ecrite', "$id v$version");
        return [$depart === 0 ? 201 : 200, ['version' => $version], $type, []];
    }

    /** @return list<array{nom:string,type:string,taille:int,sha256:string}> */
    private function validerPieces(mixed $pieces): array
    {
        if (!is_array($pieces) || !array_is_list($pieces) || count($pieces) > $this->cfg['limite_pieces']) {
            throw new ErreurHttp(422, 'Pièces invalides ou trop nombreuses.');
        }
        $out = [];
        $total = 0;
        foreach ($pieces as $p) {
            if (!is_array($p) || !is_string($p['nom'] ?? null) || !is_string($p['type'] ?? null)
                || !is_int($p['taille'] ?? null) || !is_string($p['sha256'] ?? null)
                || $p['nom'] === '' || mb_strlen($p['nom']) > 255 || mb_strlen($p['type']) > 100
                || !preg_match('/^[0-9a-f]{64}$/', $p['sha256']) || $p['taille'] < 0) {
                throw new ErreurHttp(422, 'Pièce invalide.');
            }
            if ($p['taille'] > $this->cfg['limite_image']) {
                throw new ErreurHttp(413, 'Image trop grosse.');
            }
            $total += $p['taille'];
            if ($this->base->valeur('SELECT 1 FROM blobs WHERE sha256 = ?', [$p['sha256']]) === null) {
                throw new ErreurHttp(422, 'Une image n’a pas été déposée avant la fiche.');
            }
            $out[] = ['nom' => $p['nom'], 'type' => $p['type'], 'taille' => $p['taille'], 'sha256' => $p['sha256']];
        }
        if ($total > $this->cfg['limite_fiche']) {
            throw new ErreurHttp(413, 'Fiche trop volumineuse.');
        }
        return $out;
    }

    private function supprimerFiche(string $compte, string $id): array
    {
        $this->exiger($compte, $id, 'proprietaire');
        $this->base->transaction(function () use ($id): void {
            foreach (['droits', 'fiche_blobs', 'invitations', 'invitation_fiches'] as $t) {
                $this->base->requete("DELETE FROM $t WHERE fiche_id = ?", [$id]);
            }
            $this->base->requete('DELETE FROM fiches WHERE id = ?', [$id]);
        });
        $this->base->journal($this->maintenant(), $compte, 'fiche_supprimee', $id);
        return [204, null, 'application/json; charset=utf-8', []];
    }

    // --- Dépôt (boîte de réception) ----------------------------------------------------------------------------

    /**
     * POST /depot : crée une fiche dans le compte, sans rien lire ni modifier d'autre. Corps JSON {"titre"?, "texte"} ou texte brut
     * (titre = en-tête X-Titre, sinon première ligne). Le client Scrinium la reçoit à sa prochaine synchronisation.
     *
     * @param array<string,string> $e @return array{int,mixed,string,array<string,string>}
     */
    private function deposer(string $compte, string $cleLimite, array $e, string $corps): array
    {
        $this->limiteur->verifier('depot:' . $cleLimite, (int) $this->cfg['depot_max_par_heure'], 3600);
        $type = strtolower((string) ($e['content-type'] ?? ''));
        if (str_contains($type, 'json') || str_starts_with(ltrim($corps), '{')) {
            $c = $this->corpsJson($corps);
            $texte = $c['texte'] ?? '';
            $titre = $c['titre'] ?? '';
            if (!is_string($texte) || !is_string($titre)) {
                throw new ErreurHttp(422, 'titre et texte doivent être du texte.');
            }
        } else {
            $texte = $corps;
            $titre = (string) ($e['x-titre'] ?? '');
        }
        $texte = str_replace("\0", '', $texte);
        $titre = trim(str_replace(["\0", "\r", "\n"], ' ', $titre));
        if (strlen($texte) > (int) $this->cfg['depot_taille_max']) {
            throw new ErreurHttp(413, 'Texte trop long pour un dépôt.');
        }
        if (!mb_check_encoding($texte, 'UTF-8') || !mb_check_encoding($titre, 'UTF-8')) {
            throw new ErreurHttp(422, 'Texte en UTF-8 attendu.');
        }
        if (trim($texte) === '' && $titre === '') {
            throw new ErreurHttp(422, 'Rien à déposer : titre ou texte requis.');
        }
        if ($titre === '') {                                                    // titre déduit : première ligne non vide du texte
            foreach (preg_split('/\R/u', $texte) ?: [] as $ligne) {
                $ligne = trim(ltrim(trim($ligne), '#'));
                if ($ligne !== '') {
                    $titre = $ligne;
                    break;
                }
            }
        }
        $titre = mb_substr($titre, 0, 80);
        if ($titre === '') {
            $titre = 'Dépôt du ' . gmdate('Y-m-d H:i', $this->maintenant());
        }
        $id = bin2hex(random_bytes(16));
        $t = $this->maintenant();
        $this->base->transaction(function () use ($id, $titre, $texte, $compte, $t): void {
            $this->base->requete(
                'INSERT INTO fiches (id, version, titre, texte, pieces, proprietaire, modifie_le) VALUES (?, 1, ?, ?, ?, ?, ?)',
                [$id, $titre, $texte, '[]', $compte, $t],
            );
            $this->base->requete('INSERT INTO droits (fiche_id, compte, role) VALUES (?, ?, ?)', [$id, $compte, 'proprietaire']);
        });
        $this->limiteur->echec('depot:' . $cleLimite);                          // (le limiteur compte simplement les événements)
        $this->base->journal($t, $compte, 'depot', $id);
        return [201, ['id' => $id, 'titre' => $titre, 'version' => 1], 'application/json; charset=utf-8', []];
    }

    // --- Pièces jointes ----------------------------------------------------------------------------------------

    private function cheminBlob(string $sha): string
    {
        return rtrim((string) $this->cfg['donnees'], '/') . '/blobs/' . substr($sha, 0, 2) . '/' . $sha;
    }

    private function deposerBlob(string $compte, string $sha, string $octets): void
    {
        if (strlen($octets) > $this->cfg['limite_image']) {
            throw new ErreurHttp(413, 'Image trop grosse.');
        }
        if (!hash_equals($sha, hash('sha256', $octets))) {
            throw new ErreurHttp(422, 'L’empreinte ne correspond pas au contenu.');
        }
        $chemin = $this->cheminBlob($sha);
        if (!is_file($chemin)) {
            if (!is_dir(dirname($chemin)) && !mkdir(dirname($chemin), 0750, true) && !is_dir(dirname($chemin))) {
                throw new \RuntimeException('Dossier de données non inscriptible.');
            }
            $tmp = $chemin . '.' . bin2hex(random_bytes(6)) . '.tmp';
            file_put_contents($tmp, $octets);
            rename($tmp, $chemin);
        }
        if ($this->base->valeur('SELECT 1 FROM blobs WHERE sha256 = ?', [$sha]) === null) {
            try {
                $this->base->requete('INSERT INTO blobs (sha256, taille) VALUES (?, ?)', [$sha, strlen($octets)]);
            } catch (\PDOException) {
                // déposée en même temps par une autre requête : identique, rien à faire
            }
        }
    }

    private function lireBlob(string $compte, string $sha): string
    {
        $ok = $this->base->valeur(
            'SELECT 1 FROM fiche_blobs b JOIN droits d ON d.fiche_id = b.fiche_id WHERE b.sha256 = ? AND d.compte = ?',
            [$sha, $compte],
        );
        $chemin = $this->cheminBlob($sha);
        if ($ok === null || !is_file($chemin)) {
            throw new ErreurHttp(404, 'Image introuvable.');
        }
        return (string) file_get_contents($chemin);
    }

    // --- Invitations -------------------------------------------------------------------------------------------

    /** @param array<string,mixed> $c @return array<string,mixed> */
    private function creerInvitation(string $compte, string $id, array $c): array
    {
        return $this->inviter($compte, [$id], $c);
    }

    /** Invitation à plusieurs fiches à la fois (partage d'un thème entier) : `{"email","role","fiches":[id,…]}`.
     * @param array<string,mixed> $c @return array<string,mixed> */
    private function creerInvitationGroupe(string $compte, array $c): array
    {
        $ids = $c['fiches'] ?? null;
        if (!is_array($ids) || $ids === [] || count($ids) > 500) {
            throw new ErreurHttp(422, 'Liste de fiches invalide (1 à 500).');
        }
        $propres = [];
        foreach ($ids as $i) {
            if (!is_string($i) || !preg_match('/^[0-9a-f]{32}$/', $i)) {
                throw new ErreurHttp(422, 'Identifiant de fiche invalide.');
            }
            $propres[$i] = $i;
        }
        return $this->inviter($compte, array_values($propres), $c);
    }

    /** @param list<string> $ids @param array<string,mixed> $c @return array<string,mixed> */
    private function inviter(string $compte, array $ids, array $c): array
    {
        $id = $ids[0];
        foreach ($ids as $i) {
            $this->exiger($compte, $i, 'proprietaire');
        }
        $email = $c['email'] ?? null;
        $role = $c['role'] ?? null;
        if (!is_string($email) || strlen($email) > 255 || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new ErreurHttp(422, 'Adresse de courriel invalide.');
        }
        if (!is_string($role) || !in_array($role, ['lecture', 'ecriture'], true)) {
            throw new ErreurHttp(422, 'Rôle invalide (lecture ou ecriture).');
        }
        $t = $this->maintenant();
        $this->base->requete("UPDATE invitations SET etat = 'expiree' WHERE etat = 'en_attente' AND expire_le < ?", [$t]);
        $n = (int) $this->base->valeur("SELECT COUNT(*) FROM invitations WHERE par = ? AND etat = 'en_attente'", [$compte]);
        if ($n >= $this->cfg['max_invitations_en_attente']) {
            throw new ErreurHttp(429, 'Trop d’invitations en attente : annulez-en ou attendez leur expiration.');
        }
        $jeton = bin2hex(random_bytes(32));
        $inv = bin2hex(random_bytes(16));
        $expire = $t + (int) $this->cfg['duree_invitation'];
        $this->base->requete(
            'INSERT INTO invitations (id, jeton_hash, fiche_id, email, role, par, etat, cree_le, expire_le) '
            . "VALUES (?, ?, ?, ?, ?, ?, 'en_attente', ?, ?)",
            [$inv, hash('sha256', $jeton), $id, $email, $role, $compte, $t, $expire],
        );
        foreach (array_slice($ids, 1) as $autre) {
            $this->base->requete('INSERT INTO invitation_fiches (invitation_id, fiche_id) VALUES (?, ?)', [$inv, $autre]);
        }
        $this->base->journal($t, $compte, 'invitation', "$id $role" . (count($ids) > 1 ? ' (+' . (count($ids) - 1) . ')' : ''));
        return ['id' => $inv, 'url' => rtrim((string) $this->cfg['base_url'], '/') . '/inviter/' . $jeton,
            'expire_le' => self::iso($expire), 'role' => $role];
    }

    /** @return list<array<string,mixed>> */
    private function listerInvitations(string $compte, string $id): array
    {
        $this->exiger($compte, $id, 'proprietaire');
        $t = $this->maintenant();
        $out = [];
        foreach ($this->base->lignes(
            'SELECT id, email, role, etat, expire_le FROM invitations WHERE fiche_id = ? ORDER BY cree_le DESC', [$id]) as $l) {
            $etat = $l['etat'] === 'en_attente' && (int) $l['expire_le'] < $t ? 'expiree' : $l['etat'];
            $out[] = ['id' => $l['id'], 'email' => $l['email'], 'role' => $l['role'],
                'expire_le' => self::iso((int) $l['expire_le']), 'etat' => $etat];
        }
        return $out;
    }

    private function annulerInvitation(string $compte, string $inv): void
    {
        $l = $this->base->ligne('SELECT fiche_id FROM invitations WHERE id = ?', [$inv]);
        if ($l === null) {
            throw new ErreurHttp(404, 'Invitation introuvable.');
        }
        $this->exiger($compte, (string) $l['fiche_id'], 'proprietaire');
        $this->base->requete("UPDATE invitations SET etat = 'annulee' WHERE id = ? AND etat = 'en_attente'", [$inv]);
        $this->base->journal($this->maintenant(), $compte, 'invitation_annulee', $inv);
    }

    /** Invitation valable (en attente, non expirée) ou 404 identique dans tous les autres cas. @return array<string,mixed> */
    private function invitationValable(string $jeton, string $ip): array
    {
        $this->limiteur->verifier('invitation-ip:' . $ip, 30, 900);
        $l = $this->base->ligne(
            "SELECT * FROM invitations WHERE jeton_hash = ? AND etat = 'en_attente' AND expire_le >= ?",
            [hash('sha256', $jeton), $this->maintenant()],
        );
        if ($l === null) {
            $this->limiteur->echec('invitation-ip:' . $ip);
            throw new ErreurHttp(404, 'Invitation introuvable, expirée ou déjà utilisée.');
        }
        return $l;
    }

    /** @return array<string,mixed> */
    private function decrireInvitation(string $jeton, string $ip): array
    {
        $l = $this->invitationValable($jeton, $ip);
        return ['invite_par' => $l['par'], 'role' => $l['role'], 'expire_le' => self::iso((int) $l['expire_le']),
            'fiches' => $this->nombreFiches($l)];
    }

    /** @param array<string,mixed> $inv */
    private function nombreFiches(array $inv): int
    {
        return 1 + (int) $this->base->valeur('SELECT COUNT(*) FROM invitation_fiches WHERE invitation_id = ?', [$inv['id']]);
    }

    /** @param array<string,mixed> $c @return array{int,mixed,string,array<string,string>} */
    private function accepterInvitation(string $jeton, ?string $compte, array $c, string $ip): array
    {
        $inv = $this->invitationValable($jeton, $ip);
        $json = 'application/json; charset=utf-8';
        $nom = $compte;
        $mdp = '';
        if ($compte === null) {
            if (!$this->cfg['invitations_creent_des_comptes']) {
                throw new ErreurHttp(403, 'La création de compte est réservée à l’administrateur : connectez-vous avec un compte existant.');
            }
            $nom = is_string($c['compte'] ?? null) ? $c['compte'] : '';
            $mdp = is_string($c['mot_de_passe'] ?? null) ? $c['mot_de_passe'] : '';
        }
        $this->base->transaction(function () use ($inv, $compte, $nom, $mdp): void {
            $n = $this->base->requete(
                "UPDATE invitations SET etat = 'acceptee' WHERE id = ? AND etat = 'en_attente'", [$inv['id']],
            )->rowCount();
            if ($n !== 1) {
                throw new ErreurHttp(404, 'Invitation introuvable, expirée ou déjà utilisée.');
            }
            if ($compte === null) {
                $this->comptes->creer($nom, $mdp ?? '', (string) $inv['email']);
            }
            $fiches = [(string) $inv['fiche_id']];
            foreach ($this->base->lignes('SELECT fiche_id FROM invitation_fiches WHERE invitation_id = ?', [$inv['id']]) as $l) {
                $fiches[] = (string) $l['fiche_id'];
            }
            foreach ($fiches as $fiche) {
                $actuel = $this->base->valeur('SELECT role FROM droits WHERE fiche_id = ? AND compte = ?', [$fiche, $nom]);
                if ($actuel === null && $this->base->valeur('SELECT 1 FROM fiches WHERE id = ?', [$fiche]) === null) {
                    continue;                                     // fiche supprimée depuis l'invitation
                }
                if ($actuel === null || ($actuel !== 'proprietaire' && self::ROLES[$inv['role']] > self::ROLES[$actuel])) {
                    $this->accorder($fiche, (string) $nom, (string) $inv['role']);
                }
            }
        });
        $this->base->journal($this->maintenant(), $nom, 'invitation_acceptee', (string) $inv['fiche_id']);
        if ($compte !== null) {
            return [204, null, $json, []];
        }
        $s = $this->comptes->ouvrirSession((string) $nom);
        return [201, ['jeton' => $s['jeton'], 'expire_le' => self::iso($s['expire_le']), 'compte' => $nom], $json, []];
    }

    /** Page d'explication ouverte depuis le courriel (ne consomme pas le jeton). @return array{int,mixed,string,array<string,string>} */
    private function pageInvitation(string $jeton, string $ip): array
    {
        $e = static fn (string $s): string => htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
        $l = $this->invitationValable($jeton, $ip);
        $role = $l['role'] === 'ecriture' ? 'lire et modifier' : 'lire';
        $n = $this->nombreFiches($l);
        $objet = $n > 1 ? "$n fiches" : 'une fiche';
        $serveur = rtrim((string) $this->cfg['base_url'], '/');
        $lien = 'scrinium://rejoindre?serveur=' . rawurlencode($serveur) . '&jeton=' . rawurlencode($jeton);
        $html = '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            . '<meta name="robots" content="noindex"><title>Invitation Scrinium</title>'
            . '<style>body{font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem}'
            . 'a.b{display:inline-block;padding:.6rem 1.2rem;background:#2d6cdf;color:#fff;border-radius:.4rem;text-decoration:none}'
            . 'code{background:#eee;padding:.1rem .3rem;word-break:break-all}</style></head><body>'
            . '<h1>Invitation à partager ' . $objet . '</h1>'
            . '<p><strong>' . $e((string) $l['par']) . '</strong> vous invite à ' . $role . ' ' . $objet . ' sur ce serveur Scrinium.</p>'
            . '<p>Valable jusqu’au ' . $e(gmdate('d/m/Y à H:i', (int) $l['expire_le'])) . ' (UTC), à usage unique.</p>'
            . '<p><a class="b" href="' . $e($lien) . '">Ouvrir dans Scrinium</a></p>'
            . '<p>Dans Scrinium, vous pouvez aussi choisir <em>Rejoindre un partage…</em> et coller l’adresse de cette page.</p>'
            . '<p><small>Bon à savoir : les fiches partagées sont stockées sur ce serveur et son administrateur peut les lire '
            . '(les fiches verrouillées ne sont jamais partagées de cette façon). Serveur : <code>' . $e($serveur) . '</code></small></p>'
            . '</body></html>';
        return [200, $html, 'text/html; charset=utf-8', ['Content-Security-Policy' => "default-src 'none'; style-src 'unsafe-inline'"]];
    }
}
