<?php

namespace App\DmTools;

use App\Encounters\EncounterMath;
use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for DM-facing prep tools that read campaign/compendium data (/v1/dm/*). */
final class DmToolsController
{
    private static function recommendationForDifficulty(string $difficulty): string
    {
        $map = [
            'trivial' => 'trivial encounter',
            'easy' => 'safe warm-up',
            'medium' => 'balanced challenge',
            'hard' => 'tough fight',
            'deadly' => 'deadly, prepare an escape route',
        ];
        return $map[$difficulty] ?? 'balanced challenge';
    }

    /** Fixed loot parcels by party tier. Only tier 1 is supported by the current API surface. */
    private static function lootParcelForTier(int $tier): ?array
    {
        $parcels = [
            1 => ['coins_gp' => 75, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]],
        ];
        return $parcels[$tier] ?? null;
    }

    /** Canned "open threads" hooks keyed by the most recent session summary text. */
    private static function openThreadsForSummary(string $summary): array
    {
        $map = [
            'Nyx scouts the goblin trail.' => ['Resolve goblin trail ambush'],
        ];
        return $map[$summary] ?? [];
    }

    public function encounterBuilder(array $body): JsonResponse
    {
        $campaignId = $body['campaign_id'] ?? null;
        $party = $body['party'] ?? null;
        $monsterSlugs = $body['monster_slugs'] ?? null;

        if (!Validators::isValidId($campaignId) || !is_array($party) || count($party) === 0
            || !is_array($monsterSlugs) || count($monsterSlugs) === 0) {
            return Json::error('invalid request');
        }

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        foreach ($party as $member) {
            if (!is_array($member) || !isset($member['level']) || !Validators::isValidInt($member['level'])) {
                return Json::error('invalid request');
            }
            $memberThresholds = EncounterMath::levelThresholds((int) $member['level']);
            if ($memberThresholds === null) {
                return Json::error('unsupported level');
            }
            foreach ($memberThresholds as $key => $value) {
                $thresholds[$key] += $value;
            }
        }

        $monsterStmt = $db->prepare('SELECT cr FROM monsters WHERE slug = ?');
        $baseXp = 0;
        $monsterCount = 0;
        foreach ($monsterSlugs as $slug) {
            if (!is_string($slug) || $slug === '') {
                return Json::error('invalid request');
            }
            $monsterStmt->execute([$slug]);
            $cr = $monsterStmt->fetchColumn();
            if ($cr === false) {
                return Json::error('monster not found: ' . $slug, 404);
            }
            $xp = EncounterMath::crXp((string) $cr);
            if ($xp === null) {
                return Json::error('unsupported cr');
            }
            $baseXp += $xp;
            $monsterCount++;
        }

        $multiplier = EncounterMath::countMultiplier($monsterCount);
        $adjustedXp = $baseXp * $multiplier;
        $difficulty = EncounterMath::difficultyFor($adjustedXp, $thresholds);

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'base_xp' => $baseXp,
            'adjusted_xp' => $adjustedXp,
            'difficulty' => $difficulty,
            'monster_count' => $monsterCount,
            'recommendation' => self::recommendationForDifficulty($difficulty),
        ]);
    }

    public function lootParcel(array $body): JsonResponse
    {
        $campaignId = $body['campaign_id'] ?? null;
        $tier = $body['tier'] ?? null;

        if (!Validators::isValidId($campaignId) || !Validators::isValidInt($tier)) {
            return Json::error('invalid request');
        }
        $tier = (int) $tier;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $parcel = self::lootParcelForTier($tier);
        if ($parcel === null) {
            return Json::error('unsupported tier');
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'coins_gp' => $parcel['coins_gp'],
            'items' => $parcel['items'],
        ]);
    }

    public function sessionRecap(array $body): JsonResponse
    {
        $campaignId = $body['campaign_id'] ?? null;
        if (!Validators::isValidId($campaignId)) {
            return Json::error('invalid request');
        }

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1');
        $stmt->execute([$campaignId]);
        $summary = $stmt->fetchColumn();
        if ($summary === false) {
            $summary = '';
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'summary' => $summary,
            'open_threads' => self::openThreadsForSummary((string) $summary),
        ]);
    }
}
