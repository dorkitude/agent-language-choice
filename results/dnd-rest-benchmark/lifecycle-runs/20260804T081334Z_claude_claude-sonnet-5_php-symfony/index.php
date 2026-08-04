<?php

require __DIR__ . '/vendor/autoload.php';

use App\Http\Kernel;
use App\Storage\Database;
use Symfony\Component\HttpFoundation\Request;

Database::initSchema(Database::connection());

$request = Request::createFromGlobals();
(new Kernel())->handle($request)->send();
