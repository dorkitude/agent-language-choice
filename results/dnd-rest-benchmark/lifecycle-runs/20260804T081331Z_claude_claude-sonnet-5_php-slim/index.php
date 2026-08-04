<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use App\Routes\AuthRoutes;
use App\Routes\CampaignRoutes;
use App\Routes\CharacterRoutes;
use App\Routes\CombatRoutes;
use App\Routes\CompendiumRoutes;
use App\Routes\CoreRoutes;
use App\Routes\DmRoutes;
use App\Routes\DowntimeRoutes;
use App\Routes\EncounterRoutes;
use App\Routes\PhbRoutes;
use App\Routes\PlayRoutes;
use App\Routes\StorageRoutes;
use App\Storage\Database;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

$dbFile = getenv('GAME_DB_FILE') ?: __DIR__ . '/game.db';

CoreRoutes::register($app);
EncounterRoutes::register($app);
CharacterRoutes::register($app);
PhbRoutes::register($app);
CombatRoutes::register($app, $dbFile);
AuthRoutes::register($app, $dbFile);
StorageRoutes::register($app, $dbFile);
CompendiumRoutes::register($app, $dbFile);
CampaignRoutes::register($app, $dbFile);
DmRoutes::register($app, $dbFile);
DowntimeRoutes::register($app, $dbFile);
PlayRoutes::register($app, $dbFile);

// Ensure the database and schema exist before the first request is served.
Database::connect($dbFile);

$app->run();
