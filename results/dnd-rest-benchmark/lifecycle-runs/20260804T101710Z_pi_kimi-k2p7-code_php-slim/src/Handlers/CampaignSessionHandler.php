<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Campaign session scheduling and attendance endpoints.
 */
final class CampaignSessionHandler
{
    use HasCampaign;

    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/campaigns/{id}/sessions', $this->scheduleSession(...));
        $app->post('/v1/campaigns/{id}/sessions/{session_id}/attendance', $this->recordAttendance(...));
        $app->get('/v1/campaigns/{id}/sessions/next', $this->nextSession(...));
    }

    private function scheduleSession(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['starts_at']) || (!is_string($body['starts_at']) && !is_numeric($body['starts_at']))
            || !isset($body['duration_minutes']) || !is_numeric($body['duration_minutes'])
            || !isset($body['agenda']) || !is_array($body['agenda'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $startsAt = (string) $body['starts_at'];
        $durationMinutes = (int) $body['duration_minutes'];
        if ($id === '' || $startsAt === '' || $durationMinutes <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $agenda = [];
        foreach ($body['agenda'] as $item) {
            if (!is_string($item) && !is_numeric($item) || (string) $item === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $agenda[] = (string) $item;
        }

        if ($this->db->findCampaignSession($id) !== null) {
            return respondJson($response, 409, ['error' => 'session id already exists']);
        }

        $session = [
            'id' => $id,
            'campaign_id' => $campaignId,
            'starts_at' => $startsAt,
            'duration_minutes' => $durationMinutes,
            'agenda' => $agenda,
        ];
        $this->db->createCampaignSession($session);

        return respondJson($response, 201, [
            'id' => $id,
            'starts_at' => $startsAt,
            'duration_minutes' => $durationMinutes,
            'agenda_count' => count($agenda),
        ]);
    }

    private function recordAttendance(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $sessionId = (string) $args['session_id'];

        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $session = $this->db->findCampaignSession($sessionId);
        if ($session === null || $session['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'session not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['present']) || !is_array($body['present'])
            || !isset($body['absent']) || !is_array($body['absent'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach (['present', 'absent'] as $key) {
            foreach ($body[$key] as $char) {
                if (!is_string($char) && !is_numeric($char) || (string) $char === '') {
                    return respondJson($response, 400, ['error' => 'invalid request']);
                }
                $this->db->recordSessionAttendance($sessionId, (string) $char, $key);
            }
        }

        $counts = $this->db->countSessionAttendance($sessionId);
        return respondJson($response, 200, [
            'session_id' => $sessionId,
            'present_count' => $counts['present'],
            'absent_count' => $counts['absent'],
        ]);
    }

    private function nextSession(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $sessions = $this->db->findCampaignSessions($campaignId);
        if ($sessions === []) {
            return respondJson($response, 404, ['error' => 'session not found']);
        }

        $next = $sessions[0];
        return respondJson($response, 200, [
            'id' => $next['id'],
            'starts_at' => $next['starts_at'],
            'agenda_count' => count($next['agenda']),
        ]);
    }
}
