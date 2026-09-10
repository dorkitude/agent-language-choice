<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use App\Http\Controllers;
use App\Http\HttpException;
use App\Http\ServiceMode;
use App\Routing\Router;
use App\Storage\GameStorage;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;

ServiceMode::setStateFile(__DIR__ . '/.service_mode');

$storage = new GameStorage(__DIR__ . '/game.db', __DIR__);
$controllers = new Controllers($storage);

$request = Request::createFromGlobals();


$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher(Router::build($controllers), $context);

try {
    $parameters = $matcher->matchRequest($request);
    $controller = $parameters['_controller'];
    unset($parameters['_controller'], $parameters['_route']);
    $response = $controller($request, $parameters);
} catch (HttpException $e) {
    $response = new JsonResponse(['error' => $e->getMessage()], $e->getStatus());
} catch (ResourceNotFoundException) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();
