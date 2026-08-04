#!/usr/bin/env bash
set -euo pipefail
rm -f .combat-state.json .users.json
php -r '
$pdo = new PDO("sqlite:game.db");
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec("PRAGMA foreign_keys = ON");
$tables = [
    "quest_milestones",
    "quests",
    "combat_conditions",
    "combat_sessions",
    "users",
    "compendium_items",
    "compendium_monsters",
    "campaign_events",
    "campaign_inventory",
    "downtime_crafting",
    "campaign_characters",
    "campaign_npcs",
    "campaign_factions",
    "session_attendance",
    "campaign_sessions",
    "campaigns",
];
foreach ($tables as $table) {
    try {
        $pdo->exec("DELETE FROM $table");
    } catch (PDOException $e) {
        // Table may not exist yet; index.php will initialize schema.
    }
}
' || true
php -S 127.0.0.1:"$PORT" index.php
