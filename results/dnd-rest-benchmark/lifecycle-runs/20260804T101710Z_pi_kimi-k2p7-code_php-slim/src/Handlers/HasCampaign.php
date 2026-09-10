<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;

/**
 * Shared helper for handlers that operate on a campaign resource.
 *
 * Provides requireCampaign() so that every campaign-scoped endpoint returns
 * the same 404 shape when the campaign does not exist.
 */
trait HasCampaign
{
    /**
     * Require a campaign to exist and return its row, or a 404 response.
     *
     * @return array<string, mixed>|Response
     */
    private function requireCampaign(Response $response, string $id): array|Response
    {
        $campaign = $this->db->findCampaign($id);
        if ($campaign === null) {
            return respondJson($response, 404, ['error' => 'campaign not found']);
        }
        return $campaign;
    }
}
