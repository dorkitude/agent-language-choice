<?php
declare(strict_types=1);

// Shared GM delegation helpers, used both by the play campaign narration
// route and by the delegation grant/revoke/audit routes below it.
// ---------------------------------------------------------------------------

const VALID_DELEGATION_POWERS = ['narrate'];

function load_delegation(PDO $db, string $campaignId, string $username): ?array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $username]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

// True if the given user currently holds an active delegation with the given power.
function has_delegated_power(PDO $db, string $campaignId, string $username, string $power): bool {
    $delegation = load_delegation($db, $campaignId, $username);
    if ($delegation === null || $delegation['active'] !== true) {
        return false;
    }
    return in_array($power, $delegation['powers'], true);
}
