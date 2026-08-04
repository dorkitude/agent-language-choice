<?php

namespace App\Inventory;

use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for campaign inventory/equipment endpoints (/v1/campaigns/{id}/inventory, .../equipment). */
final class InventoryController
{
    public function addItem(array $body, string $campaignId): JsonResponse
    {
        $itemSlug = $body['item_slug'] ?? null;
        $quantity = $body['quantity'] ?? null;
        $owner = $body['owner'] ?? null;

        if (!Validators::isValidSlug($itemSlug) || !Validators::isValidInt($quantity) || (int) $quantity <= 0
            || !is_string($owner) || $owner === '') {
            return Json::error('invalid request');
        }
        $quantity = (int) $quantity;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, $owner]);
        $existing = $stmt->fetchColumn();

        if ($existing === false) {
            $insert = $db->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)');
            $insert->execute([$campaignId, $itemSlug, $owner, $quantity]);
        } else {
            $update = $db->prepare('UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
            $update->execute([(int) $existing + $quantity, $campaignId, $itemSlug, $owner]);
        }

        return new JsonResponse(['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => $owner], 201);
    }

    public function assignEquipment(array $body, string $campaignId, string $characterId): JsonResponse
    {
        $itemSlug = $body['item_slug'] ?? null;
        $quantity = $body['quantity'] ?? null;

        if (!Validators::isValidSlug($itemSlug) || !Validators::isValidInt($quantity) || (int) $quantity <= 0) {
            return Json::error('invalid request');
        }
        $quantity = (int) $quantity;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$characterId, $campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('character not found', 404);
        }

        $stmt = $db->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, 'party']);
        $available = $stmt->fetchColumn();
        if ($available === false || (int) $available < $quantity) {
            return Json::error('insufficient party inventory', 409);
        }

        $update = $db->prepare('UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $update->execute([(int) $available - $quantity, $campaignId, $itemSlug, 'party']);

        $stmt = $db->prepare('SELECT quantity FROM campaign_equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
        $stmt->execute([$campaignId, $characterId, $itemSlug]);
        $existing = $stmt->fetchColumn();

        if ($existing === false) {
            $insert = $db->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)');
            $insert->execute([$campaignId, $characterId, $itemSlug, $quantity]);
        } else {
            $update = $db->prepare('UPDATE campaign_equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
            $update->execute([(int) $existing + $quantity, $campaignId, $characterId, $itemSlug]);
        }

        return new JsonResponse(['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity]);
    }

    public function summary(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare("SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
        $stmt->execute([$campaignId]);
        $partyItems = (int) $stmt->fetchColumn();

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_equipment WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $assignedItems = (int) $stmt->fetchColumn();

        $stmt = $db->prepare("SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'");
        $stmt->execute([$campaignId]);
        $healingPotions = $stmt->fetchColumn();
        $healingPotions = $healingPotions === false ? 0 : (int) $healingPotions;

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'party_items' => $partyItems,
            'assigned_items' => $assignedItems,
            'healing_potions_available' => $healingPotions,
        ]);
    }
}
