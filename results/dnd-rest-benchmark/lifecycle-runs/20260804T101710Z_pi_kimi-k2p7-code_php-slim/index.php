<?php

declare(strict_types=1);

/**
 * Entry point for the D&D helper API.
 *
 * This file is intentionally thin: it bootstraps the database, wires route
 * handlers into the Slim application, and starts the server. All business
 * logic lives in the src/ classes.
 */

require __DIR__ . '/vendor/autoload.php';
require __DIR__ . '/src/ResponseHelper.php';
require __DIR__ . '/src/GameDatabase.php';
require __DIR__ . '/src/GameEngine.php';
require __DIR__ . '/src/Handlers/HasCampaign.php';
require __DIR__ . '/src/Handlers/CoreHandler.php';
require __DIR__ . '/src/Handlers/CharacterHandler.php';
require __DIR__ . '/src/Handlers/CombatHandler.php';
require __DIR__ . '/src/Handlers/AuthHandler.php';
require __DIR__ . '/src/Handlers/StorageHandler.php';
require __DIR__ . '/src/Handlers/CompendiumHandler.php';
require __DIR__ . '/src/Handlers/CampaignHandler.php';
require __DIR__ . '/src/Handlers/PhbHandler.php';
require __DIR__ . '/src/Handlers/DmHandler.php';
require __DIR__ . '/src/Handlers/DowntimeHandler.php';
require __DIR__ . '/src/Handlers/CampaignSessionHandler.php';
require __DIR__ . '/src/Handlers/AnalyticsHandler.php';
require __DIR__ . '/src/Handlers/PlayHandler.php';

use Slim\Factory\AppFactory;

$dbFile = __DIR__ . '/game.db';
$db = new GameDatabase($dbFile);
$db->initializeSchema();

// When run from the CLI with INIT_DB=1, only create the schema and exit.
// run.sh uses this to initialize the database before starting the web server.
if (PHP_SAPI === 'cli' && getenv('INIT_DB')) {
    exit(0);
}

$engine = new GameEngine();

$app = AppFactory::create();
$app->addBodyParsingMiddleware();
$app->addRoutingMiddleware();
$app->addErrorMiddleware(false, false, false);

(new CoreHandler($engine, $db))->register($app);
(new CharacterHandler($engine))->register($app);
(new CombatHandler($db, $engine))->register($app);
(new AuthHandler($db))->register($app);
(new StorageHandler($db))->register($app);
(new CompendiumHandler($db))->register($app);
(new CampaignHandler($db))->register($app);
(new PhbHandler())->register($app);
(new DmHandler($db, $engine))->register($app);
(new DowntimeHandler($db))->register($app);
(new CampaignSessionHandler($db))->register($app);
(new AnalyticsHandler($db))->register($app);
(new PlayHandler($db, $engine))->register($app);

$app->run();
