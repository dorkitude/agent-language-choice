<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use App\Http\Controllers;
use App\Routing\Router;
use App\Storage\GameStorage;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;

$storage = new GameStorage(__DIR__ . '/game.db', __DIR__);
$controllers = new Controllers($storage);

$context = new RequestContext();
$context->fromRequest(Request::createFromGlobals());
$matcher = new UrlMatcher(Router::build($controllers), $context);

$request = Request::createFromGlobals();

try {
    $parameters = $matcher->matchRequest($request);
    $controller = $parameters['_controller'];
    unset($parameters['_controller'], $parameters['_route']);
    $response = $controller($request, $parameters);
} catch (ResourceNotFoundException) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();
