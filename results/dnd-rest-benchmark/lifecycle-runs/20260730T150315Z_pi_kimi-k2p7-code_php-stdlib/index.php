<?php

declare(strict_types=1);

header('Content-Type: application/json');

define('ROOT_DIR', __DIR__);

require ROOT_DIR . '/src/Http.php';
require ROOT_DIR . '/src/Database.php';
require ROOT_DIR . '/src/Utils.php';
require ROOT_DIR . '/src/Combat.php';
require ROOT_DIR . '/src/Auth.php';
require ROOT_DIR . '/src/Compendium.php';
require ROOT_DIR . '/src/Campaigns.php';
require ROOT_DIR . '/src/Quests.php';
require ROOT_DIR . '/src/PlayerHandbook.php';
require ROOT_DIR . '/src/DmTools.php';
require ROOT_DIR . '/src/Crafting.php';
require ROOT_DIR . '/src/Sessions.php';
require ROOT_DIR . '/src/Play.php';
require ROOT_DIR . '/src/Router.php';
