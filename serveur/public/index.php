<?php
declare(strict_types=1);

// Point d'entrée unique. Configuration et données restent HORS du dossier web (voir README).
require __DIR__ . '/../src/autoload.php';

use Scrinium\Serveur\Application;
use Scrinium\Serveur\Base;

$fichierConfig = getenv('SCRINIUM_CONFIG') ?: __DIR__ . '/../config.php';
if (!is_file($fichierConfig)) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo '{"erreur":"interne","message":"Serveur non configuré (config.php absent)."}';
    exit;
}
/** @var array<string,mixed> $config */
$config = require $fichierConfig;

$entetes = function_exists('getallheaders') ? getallheaders() : [];
if (!isset($entetes['Authorization']) && isset($_SERVER['HTTP_AUTHORIZATION'])) {
    $entetes['Authorization'] = $_SERVER['HTTP_AUTHORIZATION'];
}
$chemin = rawurldecode((string) parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH));
$corps = (string) file_get_contents('php://input');

$app = new Application(Base::depuisConfig($config['db']), $config);
$ip = Application::adresseClient($_SERVER, (array) ($config['proxies_de_confiance'] ?? []));
$r = $app->traiter($_SERVER['REQUEST_METHOD'] ?? 'GET', $chemin, $entetes, $corps, $ip);

http_response_code($r['statut']);
foreach ($r['entetes'] as $nom => $valeur) {
    header("$nom: $valeur");
}
echo $r['corps'];
