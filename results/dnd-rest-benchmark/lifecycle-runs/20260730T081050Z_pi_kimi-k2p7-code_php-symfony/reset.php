<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use App\Http\ServiceMode;
use App\Storage\GameStorage;

/**
 * Reset application state before starting the server.
 *
 * This script centralises the truncation list so it stays in sync with
 * GameStorage::reset(). It is intentionally separate from index.php so that
 * the foreground server only needs to start after state has been cleared.
 */
$storage = new GameStorage(__DIR__ . '/game.db', __DIR__);
$storage->reset();
ServiceMode::setStateFile(__DIR__ . '/.service_mode');
ServiceMode::reset();
