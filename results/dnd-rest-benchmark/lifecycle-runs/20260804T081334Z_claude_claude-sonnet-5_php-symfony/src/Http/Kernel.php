<?php

namespace App\Http;

use App\Support\Json;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;

/**
 * Matches the incoming request against RouteFactory's route table and
 * invokes the matched controller. Any request that matches no route, or
 * matches a path with the wrong HTTP method, becomes a uniform 404 - the
 * API never distinguishes "wrong method" from "unknown path".
 */
final class Kernel
{
    public function handle(Request $request): JsonResponse
    {
        $context = (new RequestContext())->fromRequest($request);
        $matcher = new UrlMatcher(RouteFactory::build(), $context);

        try {
            $match = $matcher->match($request->getPathInfo());
        } catch (ResourceNotFoundException|MethodNotAllowedException) {
            return Json::error('not found', 404);
        }

        $controller = $match['_controller'];
        $needsBody = $match['_needsBody'];
        $needsAuth = $match['_needsAuth'] ?? false;

        $args = [];
        if ($needsAuth) {
            $args[] = $request;
        }
        if ($needsBody) {
            $body = Json::parseBody($request);
            if ($body === null) {
                return Json::error('invalid json');
            }
            $args[] = $body;
        }

        foreach ($match as $key => $value) {
            if ($key === '' || $key[0] === '_') {
                continue;
            }
            $args[] = $value;
        }

        return $controller(...$args);
    }
}
