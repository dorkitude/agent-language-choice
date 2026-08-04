<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

$request = Request::createFromGlobals();
if ($request->getPathInfo() === '/health') {
    (new JsonResponse(['ok' => true]))->send();
    return;
}
(new JsonResponse(['error' => 'not found'], 404))->send();
?>
