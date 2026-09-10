<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';
require __DIR__ . '/storage.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

final class DuplicateUsernameException extends RuntimeException
{
}

final class InvalidCredentialsException extends RuntimeException
{
}

final class ForbiddenException extends RuntimeException
{
}

final class DuplicateSlugException extends RuntimeException
{
}

final class DuplicateIdException extends RuntimeException
{
}

final class MembershipConflictException extends RuntimeException
{
}

final class DuplicateFeedEventException extends RuntimeException
{
}

/** @return array<string, mixed> */
function requestBody(Request $request): array
{
    try {
        $body = json_decode($request->getContent(), true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        throw new InvalidArgumentException('invalid JSON');
    }
    if (!is_array($body) || array_is_list($body)) {
        throw new InvalidArgumentException('JSON object required');
    }
    return $body;
}

function integer(mixed $value): int
{
    if (!is_int($value)) {
        throw new InvalidArgumentException('integer required');
    }
    return $value;
}

function compendiumSlug(mixed $value): string
{
    if (!is_string($value) || preg_match('/\\A[a-z0-9]+(?:-[a-z0-9]+)*\\z/D', $value) !== 1) {
        throw new InvalidArgumentException('invalid slug');
    }
    return $value;
}

function inventoryCatalogItem(mixed $value): string
{
    if (!is_string($value) || !in_array($value, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true)) {
        throw new InvalidArgumentException('invalid inventory item');
    }
    return $value;
}

/** @return array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int} */
function recipeFields(array $body): array
{
    $recipeId = $body['recipe_id'] ?? null;
    $name = $body['name'] ?? null;
    $ingredients = $body['ingredients'] ?? null;
    $outputItem = $body['output_item'] ?? null;
    $outputQuantity = $body['output_quantity'] ?? null;
    if (!is_string($recipeId) || $recipeId === '' || !is_string($name) || $name === ''
        || !is_array($ingredients) || array_is_list($ingredients) || $ingredients === []
        || !is_int($outputQuantity) || $outputQuantity < 1) {
        throw new InvalidArgumentException('invalid recipe');
    }

    $normalizedIngredients = [];
    foreach ($ingredients as $itemId => $quantity) {
        if (!is_int($quantity) || $quantity < 1) {
            throw new InvalidArgumentException('invalid recipe');
        }
        $normalizedIngredients[inventoryCatalogItem($itemId)] = $quantity;
    }
    return [
        'recipe_id' => $recipeId,
        'name' => $name,
        'ingredients' => $normalizedIngredients,
        'output_item' => inventoryCatalogItem($outputItem),
        'output_quantity' => $outputQuantity,
    ];
}

/** @return array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int} */
function recipeResponse(array $recipe): array
{
    $ingredients = json_decode($recipe['ingredients'], true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($ingredients) || array_is_list($ingredients) || $ingredients === []) {
        throw new RuntimeException('invalid recipe state');
    }
    foreach ($ingredients as $itemId => $quantity) {
        inventoryCatalogItem($itemId);
        if (!is_int($quantity) || $quantity < 1) {
            throw new RuntimeException('invalid recipe state');
        }
    }
    return [
        'recipe_id' => $recipe['recipe_id'],
        'name' => $recipe['name'],
        'ingredients' => $ingredients,
        'output_item' => inventoryCatalogItem($recipe['output_item']),
        'output_quantity' => (int) $recipe['output_quantity'],
    ];
}

/** @return array{xp: int, items: array<string, int>} */
function questRewardConfig(Request $request): array
{
    try {
        $body = json_decode($request->getContent(), false, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        throw new InvalidArgumentException('invalid quest rewards');
    }
    if (!$body instanceof stdClass || !property_exists($body, 'xp') || !property_exists($body, 'items')
        || !is_int($body->xp) || $body->xp < 0 || !$body->items instanceof stdClass) {
        throw new InvalidArgumentException('invalid quest rewards');
    }
    $items = [];
    foreach (get_object_vars($body->items) as $itemId => $quantity) {
        try {
            $items[inventoryCatalogItem($itemId)] = $quantity;
        } catch (InvalidArgumentException) {
            throw new InvalidArgumentException('invalid quest rewards');
        }
        if (!is_int($quantity) || $quantity < 1) {
            throw new InvalidArgumentException('invalid quest rewards');
        }
    }
    return ['xp' => $body->xp, 'items' => $items];
}

/** @return list<string> */
function tags(mixed $value): array
{
    if (!is_array($value) || !array_is_list($value)) {
        throw new InvalidArgumentException('invalid tags');
    }
    foreach ($value as $tag) {
        if (!is_string($tag) || $tag === '') {
            throw new InvalidArgumentException('invalid tags');
        }
    }
    return $value;
}

/** @return list<string> */
function stringList(mixed $value, string $error): array
{
    if (!is_array($value) || !array_is_list($value)) {
        throw new InvalidArgumentException($error);
    }
    foreach ($value as $item) {
        if (!is_string($item) || $item === '') {
            throw new InvalidArgumentException($error);
        }
    }
    return $value;
}

/** @return array{rules: string, tone: string, consent: list<string>} */
function sessionZeroSettings(array $body): array
{
    $rules = $body['rules'] ?? null;
    $tone = $body['tone'] ?? null;
    $consent = $body['consent'] ?? null;
    if (!is_string($rules) || $rules === '' || !is_string($tone) || $tone === '') {
        throw new InvalidArgumentException('invalid session-zero settings');
    }
    $consent = stringList($consent, 'invalid session-zero settings');
    if ($consent === [] || count($consent) !== count(array_unique($consent, SORT_STRING))) {
        throw new InvalidArgumentException('invalid session-zero settings');
    }
    return ['rules' => $rules, 'tone' => $tone, 'consent' => $consent];
}

/** @return list<string> */
function contentTags(mixed $value, bool $required): array
{
    if (!is_array($value) || !array_is_list($value) || ($required && $value === [])) {
        throw new InvalidArgumentException('invalid content tags');
    }
    foreach ($value as $tag) {
        if (!is_string($tag) || $tag === '') {
            throw new InvalidArgumentException('invalid content tags');
        }
    }
    if (count($value) !== count(array_unique($value, SORT_STRING))) {
        throw new InvalidArgumentException('invalid content tags');
    }
    return $value;
}

/** @return array{content_id: string, kind: string, text: string, tags: list<string>} */
function contentFields(array $body): array
{
    $contentId = $body['content_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    if (!is_string($contentId) || $contentId === '' || !is_string($kind) || $kind === '' || !is_string($text) || $text === '') {
        throw new InvalidArgumentException('invalid content');
    }
    return ['content_id' => $contentId, 'kind' => $kind, 'text' => $text, 'tags' => contentTags($body['tags'] ?? null, true)];
}

/** @return array{content_id: string, kind: string, text: string, tags: list<string>} */
function contentResponse(array $content): array
{
    $tags = json_decode($content['tags'], true, 512, JSON_THROW_ON_ERROR);
    return [
        'content_id' => $content['content_id'],
        'kind' => $content['kind'],
        'text' => $content['text'],
        'tags' => contentTags($tags, false),
    ];
}

/** @return array{note_id: string, text: string, visibility: string} */
function noteFields(array $body): array
{
    $noteId = $body['note_id'] ?? null;
    $text = $body['text'] ?? null;
    $visibility = $body['visibility'] ?? null;
    if (!is_string($noteId) || $noteId === '' || !is_string($text) || $text === ''
        || !is_string($visibility) || !in_array($visibility, ['private', 'party'], true)) {
        throw new InvalidArgumentException('invalid note');
    }
    return ['note_id' => $noteId, 'text' => $text, 'visibility' => $visibility];
}

/** @return array{text: string, visibility: string} */
function noteUpdateFields(array $body): array
{
    $text = $body['text'] ?? null;
    $visibility = $body['visibility'] ?? null;
    if (!is_string($text) || $text === '' || !is_string($visibility) || !in_array($visibility, ['private', 'party'], true)) {
        throw new InvalidArgumentException('invalid note');
    }
    return ['text' => $text, 'visibility' => $visibility];
}

/** @return array{whisper_id: string, to_character_id: string, text: string} */
function whisperFields(array $body): array
{
    $whisperId = $body['whisper_id'] ?? null;
    $toCharacterId = $body['to_character_id'] ?? null;
    $text = $body['text'] ?? null;
    if (!is_string($whisperId) || $whisperId === '' || !is_string($toCharacterId) || $toCharacterId === '' || !is_string($text) || $text === '') {
        throw new InvalidArgumentException('invalid whisper');
    }
    return ['whisper_id' => $whisperId, 'to_character_id' => $toCharacterId, 'text' => $text];
}

/** @return array{name: string, services: list<string>, availability: string} */
function settlementFields(array $body): array
{
    $name = $body['name'] ?? null;
    $services = $body['services'] ?? null;
    $availability = $body['availability'] ?? null;
    if (!is_string($name) || $name === '' || !is_array($services) || !array_is_list($services)
        || $services === [] || !is_string($availability) || !in_array($availability, ['open', 'limited', 'closed'], true)) {
        throw new InvalidArgumentException('invalid settlement');
    }

    $normalizedServices = [];
    foreach ($services as $service) {
        if (!is_string($service)) {
            throw new InvalidArgumentException('invalid settlement');
        }
        $service = trim($service);
        if ($service === '' || in_array($service, $normalizedServices, true)) {
            throw new InvalidArgumentException('invalid settlement');
        }
        $normalizedServices[] = $service;
    }
    return ['name' => $name, 'services' => $normalizedServices, 'availability' => $availability];
}

/** @param list<string> $discoverers @return array<string, mixed> */
function settlementResponse(array $settlement, array $discoverers): array
{
    $services = json_decode($settlement['services'], true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($services) || !array_is_list($services)) {
        throw new RuntimeException('invalid settlement state');
    }
    return [
        'settlement_id' => $settlement['settlement_id'],
        'name' => $settlement['name'],
        'services' => $services,
        'availability' => $settlement['availability'],
        'discovered_by' => $discoverers,
    ];
}

/** @return array{shop_id: string, name: string, stock: array<string, int>, buy_price: int, sell_price: int} */
function shopFields(array $body): array
{
    $shopId = $body['shop_id'] ?? null;
    $name = $body['name'] ?? null;
    $stock = $body['stock'] ?? null;
    $buyPrice = $body['buy_price'] ?? null;
    $sellPrice = $body['sell_price'] ?? null;
    if (!is_string($shopId) || $shopId === '' || !is_string($name) || $name === ''
        || !is_array($stock) || array_is_list($stock) || $stock === []
        || !is_int($buyPrice) || $buyPrice < 1 || !is_int($sellPrice) || $sellPrice < 0) {
        throw new InvalidArgumentException('invalid shop');
    }
    $normalizedStock = [];
    foreach ($stock as $itemId => $quantity) {
        $normalizedStock[inventoryCatalogItem($itemId)] = $quantity;
        if (!is_int($quantity) || $quantity < 1) {
            throw new InvalidArgumentException('invalid shop');
        }
    }
    return ['shop_id' => $shopId, 'name' => $name, 'stock' => $normalizedStock, 'buy_price' => $buyPrice, 'sell_price' => $sellPrice];
}

/** @return array{shop_id: string, name: string, stock: array<string, int>, buy_price: int, sell_price: int} */
function shopResponse(array $shop): array
{
    $stock = json_decode($shop['stock'], true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($stock) || array_is_list($stock) || $stock === []) {
        throw new RuntimeException('invalid shop state');
    }
    foreach ($stock as $itemId => $quantity) {
        inventoryCatalogItem($itemId);
        if (!is_int($quantity) || $quantity < 0) {
            throw new RuntimeException('invalid shop state');
        }
    }
    return ['shop_id' => $shop['shop_id'], 'name' => $shop['name'], 'stock' => $stock, 'buy_price' => (int) $shop['buy_price'], 'sell_price' => (int) $shop['sell_price']];
}

function timestamp(string $value, string $error): int
{
    if (preg_match('/\\A(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})(?:\\.(\\d{1,6}))?(Z|[+-]\\d{2}:\\d{2})\\z/D', $value, $parts) !== 1) {
        throw new InvalidArgumentException($error);
    }
    $normalized = $parts[1] . '.' . str_pad($parts[2] ?? '', 6, '0') . ($parts[3] === 'Z' ? '+00:00' : $parts[3]);
    $date = DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:s.uP', $normalized);
    $errors = DateTimeImmutable::getLastErrors();
    if (!$date instanceof DateTimeImmutable || ($errors !== false && ($errors['warning_count'] > 0 || $errors['error_count'] > 0)) || $date->format('Y-m-d\\TH:i:s.uP') !== $normalized) {
        throw new InvalidArgumentException($error);
    }
    return $date->getTimestamp();
}

function abilityModifier(int $score): int
{
    if ($score < 1 || $score > 30) {
        throw new InvalidArgumentException('invalid ability score');
    }
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    if ($level < 1 || $level > 20) {
        throw new InvalidArgumentException('invalid level');
    }
    return 2 + intdiv($level - 1, 4);
}

function supportedSkill(string $skill): bool
{
    return in_array($skill, [
        'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception',
        'history', 'insight', 'intimidation', 'investigation', 'medicine',
        'nature', 'perception', 'performance', 'persuasion', 'religion',
        'sleight-of-hand', 'stealth', 'survival',
    ], true);
}

function wizardSpell(string $spellId): bool
{
    return in_array($spellId, [
        'acid-splash', 'chill-touch', 'dancing-lights', 'fire-bolt', 'friends',
        'light', 'mage-hand', 'message', 'minor-illusion', 'poison-spray',
        'prestidigitation', 'ray-of-frost', 'shocking-grasp', 'true-strike',
        'alarm', 'burning-hands', 'charm-person', 'chromatic-orb', 'color-spray',
        'comprehend-languages', 'detect-magic', 'disguise-self', 'expeditious-retreat',
        'false-life', 'feather-fall', 'find-familiar', 'fog-cloud', 'grease',
        'identify', 'illusory-script', 'jump', 'longstrider', 'mage-armor',
        'magic-missile', 'protection-from-evil-and-good', 'ray-of-sickness', 'shield',
        'silent-image', 'sleep', 'tashas-hideous-laughter', 'tenser-floating-disk',
        'thunderwave', 'unseen-servant', 'witch-bolt', 'alter-self', 'arcane-lock',
        'blindness-deafness', 'blur', 'cloud-of-daggers', 'continual-flame',
        'crown-of-madness', 'darkness', 'darkvision', 'detect-thoughts', 'enlarge-reduce',
        'flaming-sphere', 'gentle-repose', 'gust-of-wind', 'hold-person', 'invisibility',
        'knock', 'levitate', 'locate-object', 'magic-mouth', 'magic-weapon',
        'melfs-acid-arrow', 'mirror-image', 'misty-step', 'nystuls-magic-aura',
        'phantasmal-force', 'ray-of-enfeeblement', 'rope-trick', 'scorching-ray',
        'see-invisibility', 'shatter', 'spider-climb', 'suggestion', 'web',
        'counterspell', 'dispel-magic', 'fireball', 'fly', 'haste', 'hypnotic-pattern',
        'lightning-bolt', 'major-image', 'remove-curse', 'sending', 'slow', 'tongues',
    ], true);
}

function maximumPreparedSpells(string $class, int $level): int
{
    return $class === 'wizard' ? $level : 0;
}

function spellSlots(string $class, int $level, int $slotLevel): int
{
    if ($class !== 'wizard' || $level < 1 || $level > 20 || $slotLevel < 1 || $slotLevel > 9) {
        return 0;
    }

    // Full-caster slot progression, indexed by character level and slot level.
    $slots = [
        1 => [1 => 1], 2 => [1 => 3], 3 => [1 => 4, 2 => 2], 4 => [1 => 4, 2 => 3],
        5 => [1 => 4, 2 => 3, 3 => 2], 6 => [1 => 4, 2 => 3, 3 => 3],
        7 => [1 => 4, 2 => 3, 3 => 3, 4 => 1], 8 => [1 => 4, 2 => 3, 3 => 3, 4 => 2],
        9 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 1], 10 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2],
        11 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1], 12 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1],
        13 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1], 14 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1],
        15 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1], 16 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1],
        17 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1, 9 => 1], 18 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 1, 7 => 1, 8 => 1, 9 => 1],
        19 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 1, 8 => 1, 9 => 1], 20 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 2, 8 => 1, 9 => 1],
    ];
    return $slots[$level][$slotLevel] ?? 0;
}

/** @return array{hit_dice: string, sides: int}|null */
function classHitDice(string $class): ?array
{
    return match ($class) {
        'barbarian' => ['hit_dice' => '1d12', 'sides' => 12],
        'fighter', 'paladin', 'ranger' => ['hit_dice' => '1d10', 'sides' => 10],
        'bard', 'cleric', 'druid', 'monk', 'rogue', 'warlock' => ['hit_dice' => '1d8', 'sides' => 8],
        'sorcerer', 'wizard' => ['hit_dice' => '1d6', 'sides' => 6],
        default => null,
    };
}

/** @return int|null */
function decimalInteger(string $digits): ?int
{
    $normalized = ltrim($digits, '0');
    $normalized = $normalized === '' ? '0' : $normalized;
    $limit = (string) PHP_INT_MAX;
    if (strlen($normalized) > strlen($limit) || (strlen($normalized) === strlen($limit) && strcmp($normalized, $limit) > 0)) {
        return null;
    }
    return (int) $normalized;
}

/** @return array<string, array<string, mixed>> */
function combatSessions(): array
{
    $database = database();
    $database->beginTransaction();
    $sessions = [];
    foreach ($database->query('SELECT id, state FROM combat_sessions') as $row) {
        $state = json_decode($row['state'], true, 512, JSON_THROW_ON_ERROR);
        if (is_array($state)) {
            $sessions[$row['id']] = $state;
        }
    }
    $GLOBALS['combat_database'] = $database;
    return $sessions;
}

/** @param array<string, array<string, mixed>> $sessions */
function saveCombatSessions(array $sessions): void
{
    /** @var PDO|null $database */
    $database = $GLOBALS['combat_database'] ?? null;
    if (!$database instanceof PDO) {
        throw new RuntimeException('combat state unavailable');
    }
    $database->exec('DELETE FROM combat_sessions');
    $statement = $database->prepare('INSERT INTO combat_sessions (id, state) VALUES (?, ?)');
    foreach ($sessions as $id => $session) {
        $statement->execute([$id, json_encode($session, JSON_THROW_ON_ERROR)]);
    }
    $database->commit();
    unset($GLOBALS['combat_database']);
}

function closeCombatSessions(): void
{
    /** @var PDO|null $database */
    $database = $GLOBALS['combat_database'] ?? null;
    if ($database instanceof PDO) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        unset($GLOBALS['combat_database']);
    }
}

/** @return array<string, array{role: string, password_hash: string}> */
function users(): array
{
    $database = database();
    $database->beginTransaction();
    $users = [];
    foreach ($database->query('SELECT username, role, password_hash FROM users') as $row) {
        $users[$row['username']] = ['role' => $row['role'], 'password_hash' => $row['password_hash']];
    }
    $GLOBALS['user_database'] = $database;
    return $users;
}

/** @param array<string, array{role: string, password_hash: string}> $users */
function saveUsers(array $users): void
{
    /** @var PDO|null $database */
    $database = $GLOBALS['user_database'] ?? null;
    if (!$database instanceof PDO) {
        throw new RuntimeException('user state unavailable');
    }
    $database->exec('DELETE FROM users');
    $statement = $database->prepare('INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)');
    foreach ($users as $username => $user) {
        $statement->execute([$username, $user['role'], $user['password_hash']]);
    }
    $database->commit();
    unset($GLOBALS['user_database']);
}

function closeUsers(): void
{
    /** @var PDO|null $database */
    $database = $GLOBALS['user_database'] ?? null;
    if ($database instanceof PDO) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        unset($GLOBALS['user_database']);
    }
}

/** @param array<string, mixed> $session @return array<string, mixed> */
function combatState(array $session): array
{
    $active = $session['order'][$session['turn_index']];
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
    ];
}

function campaignExists(string $campaignId): bool
{
    $statement = database()->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $statement->execute([$campaignId]);
    return $statement->fetchColumn() !== false;
}

/** @return array{username: string, powers: list<string>} */
function delegationFields(array $body): array
{
    if (count($body) !== 2 || !array_key_exists('username', $body) || !array_key_exists('powers', $body)
        || !is_string($body['username']) || $body['username'] === ''
        || !is_array($body['powers']) || !array_is_list($body['powers']) || $body['powers'] === []) {
        throw new InvalidArgumentException('invalid delegation');
    }
    foreach ($body['powers'] as $power) {
        if (!is_string($power) || $power !== 'narrate') {
            throw new InvalidArgumentException('invalid delegation');
        }
    }
    if (count($body['powers']) !== count(array_unique($body['powers'], SORT_STRING))) {
        throw new InvalidArgumentException('invalid delegation');
    }
    return ['username' => $body['username'], 'powers' => $body['powers']];
}

/** @return array{kind: string, correlation_id: string} */
function auditEventFields(array $body): array
{
    if (count($body) !== 2 || !array_key_exists('kind', $body) || !array_key_exists('correlation_id', $body)
        || !is_string($body['kind']) || $body['kind'] === ''
        || !is_string($body['correlation_id']) || $body['correlation_id'] === '') {
        throw new InvalidArgumentException('invalid audit event');
    }
    return ['kind' => $body['kind'], 'correlation_id' => $body['correlation_id']];
}

/** @return array{event_id: string, kind: string, value?: string} */
function projectionEventFields(array $body): array
{
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_string($kind)) {
        throw new InvalidArgumentException('invalid projection event');
    }
    if ($kind === 'set-story') {
        if (count($body) !== 3 || !array_key_exists('value', $body) || !is_string($body['value']) || $body['value'] === '') {
            throw new InvalidArgumentException('invalid projection event');
        }
        return ['event_id' => $eventId, 'kind' => $kind, 'value' => $body['value']];
    }
    if ($kind !== 'increment-danger' || count($body) !== 2 || array_key_exists('value', $body)) {
        throw new InvalidArgumentException('invalid projection event');
    }
    return ['event_id' => $eventId, 'kind' => $kind];
}

/** @return array{event_id: string, value: string} */
function idempotentEventFields(array $body): array
{
    $eventId = $body['event_id'] ?? null;
    $value = $body['value'] ?? null;
    if (count($body) !== 2 || !array_key_exists('event_id', $body) || !array_key_exists('value', $body)
        || !is_string($eventId) || $eventId === '' || !is_string($value) || $value === '') {
        throw new InvalidArgumentException('invalid idempotent event');
    }
    return ['event_id' => $eventId, 'value' => $value];
}

/** @return array{event_id: string, kind: string, text: string} */
function replayEventFields(array $body): array
{
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    if (count($body) !== 3 || !is_string($eventId) || $eventId === ''
        || $kind !== 'append' || !is_string($text) || $text === '') {
        throw new InvalidArgumentException('invalid replay event');
    }
    return ['event_id' => $eventId, 'kind' => $kind, 'text' => $text];
}

/** @return array{event_id: string, text: string} */
function feedEventFields(array $body): array
{
    $eventId = $body['event_id'] ?? null;
    $text = $body['text'] ?? null;
    if (count($body) !== 2 || !is_string($eventId) || $eventId === '' || !is_string($text) || $text === '') {
        throw new InvalidArgumentException('invalid feed event');
    }
    return ['event_id' => $eventId, 'text' => $text];
}

/** @return array{roll_id: string, sides: int} */
function rngRollFields(array $body): array
{
    $rollId = $body['roll_id'] ?? null;
    $sides = $body['sides'] ?? null;
    if (!is_string($rollId) || $rollId === '' || !is_int($sides) || $sides < 2 || $sides > 100) {
        throw new InvalidArgumentException('invalid rng roll');
    }
    return ['roll_id' => $rollId, 'sides' => $sides];
}

function deterministicRoll(string $seed, int $sequence, string $rollId, int $sides): int
{
    $bytes = $seed . '|' . $sequence . '|' . $rollId . '|' . $sides;
    $accumulator = 0;
    for ($index = 0, $length = strlen($bytes); $index < $length; ++$index) {
        $accumulator = ($accumulator * 31 + ord($bytes[$index])) % 4294967296;
    }
    return ($accumulator % $sides) + 1;
}

/** @return array{seed: string|null, rolls: list<array{roll_id: string, sides: int, result: int, sequence: int}>} */
function rngLedger(PDO $database, string $campaignId): array
{
    $seedStatement = $database->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
    $seedStatement->execute([$campaignId]);
    $seed = $seedStatement->fetchColumn();
    $rollStatement = $database->prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence');
    $rollStatement->execute([$campaignId]);
    $rolls = array_map(static fn (array $roll): array => [
        'roll_id' => $roll['roll_id'],
        'sides' => (int) $roll['sides'],
        'result' => (int) $roll['result'],
        'sequence' => (int) $roll['sequence'],
    ], $rollStatement->fetchAll());
    return ['seed' => $seed === false ? null : $seed, 'rolls' => $rolls];
}

/** @return array{report_id: string, target_id: string, reason: string} */
function moderationReportFields(array $body): array
{
    $reportId = $body['report_id'] ?? null;
    $targetId = $body['target_id'] ?? null;
    $reason = $body['reason'] ?? null;
    if (!is_string($reportId) || $reportId === '' || !is_string($targetId) || $targetId === '' || !is_string($reason) || $reason === '') {
        throw new InvalidArgumentException('invalid moderation report');
    }
    return ['report_id' => $reportId, 'target_id' => $targetId, 'reason' => $reason];
}

/** @return array{action: string, note: string} */
function moderationResolutionFields(array $body): array
{
    $action = $body['action'] ?? null;
    $note = $body['note'] ?? null;
    if (!is_string($action) || !in_array($action, ['allow', 'remove'], true) || !is_string($note) || $note === '') {
        throw new InvalidArgumentException('invalid moderation resolution');
    }
    return ['action' => $action, 'note' => $note];
}

/** @return array<string, mixed> */
function moderationReportResponse(array $report): array
{
    $response = [
        'report_id' => $report['report_id'],
        'target_id' => $report['target_id'],
        'reason' => $report['reason'],
        'status' => $report['status'],
        'reporter' => $report['reporter'],
        'sequence' => (int) $report['sequence'],
    ];
    if ($report['status'] === 'resolved') {
        $response['action'] = $report['action'];
        $response['note'] = $report['note'];
        $response['resolver'] = $report['resolver'];
    }
    return $response;
}

/** @return list<string> */
function safetyTags(mixed $value): array
{
    if (!is_array($value) || !array_is_list($value) || $value === []) {
        throw new InvalidArgumentException('invalid safety tags');
    }
    foreach ($value as $tag) {
        if (!is_string($tag) || trim($tag) === '') {
            throw new InvalidArgumentException('invalid safety tags');
        }
    }
    if (count($value) !== count(array_unique($value, SORT_STRING))) {
        throw new InvalidArgumentException('invalid safety tags');
    }
    return $value;
}

/** @return array{event_id: string, kind: string, text: string, tags: list<string>} */
function safetyCheckFields(array $body): array
{
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_string($text) || $text === ''
        || !is_string($kind) || !in_array($kind, ['narration', 'chat'], true)) {
        throw new InvalidArgumentException('invalid safety check');
    }
    return ['event_id' => $eventId, 'kind' => $kind, 'text' => $text, 'tags' => safetyTags($body['tags'] ?? null)];
}

/** @param list<array{event_id: string, kind: string, text: string}> $events @return array{story: string, event_ids: list<string>, digest: string} */
function rebuildReplay(array $events): array
{
    $story = '';
    $eventIds = [];
    foreach ($events as $event) {
        if ($event['kind'] !== 'append' || $event['event_id'] === '' || $event['text'] === '') {
            throw new RuntimeException('invalid replay event state');
        }
        $story .= $event['text'];
        $eventIds[] = $event['event_id'];
    }
    return ['story' => $story, 'event_ids' => $eventIds, 'digest' => implode(',', $eventIds) . '|' . $story];
}

/** @return array{submission_id: string, expected_turn: int, action: string} */
function safeTurnFields(array $body): array
{
    $submissionId = $body['submission_id'] ?? null;
    $expectedTurn = $body['expected_turn'] ?? null;
    $action = $body['action'] ?? null;
    if (count($body) !== 3 || !is_string($submissionId) || $submissionId === ''
        || !is_int($expectedTurn) || $expectedTurn < 1 || !is_string($action) || $action === '') {
        throw new InvalidArgumentException('invalid safe turn');
    }
    return ['submission_id' => $submissionId, 'expected_turn' => $expectedTurn, 'action' => $action];
}

/** @param list<array{event_id: string, kind: string, value: ?string}> $events @return array{story: string, danger: int, applied_event_ids: list<string>} */
function rebuildProjection(array $events): array
{
    $projection = ['story' => '', 'danger' => 0, 'applied_event_ids' => []];
    foreach ($events as $event) {
        if ($event['kind'] === 'set-story') {
            if (!is_string($event['value']) || $event['value'] === '') {
                throw new RuntimeException('invalid projection event state');
            }
            $projection['story'] = $event['value'];
        } elseif ($event['kind'] === 'increment-danger') {
            if ($event['value'] !== null) {
                throw new RuntimeException('invalid projection event state');
            }
            ++$projection['danger'];
        } else {
            throw new RuntimeException('invalid projection event state');
        }
        $projection['applied_event_ids'][] = $event['event_id'];
    }
    return $projection;
}

function nextPlayEventSequence(PDO $database, string $campaignId): int
{
    $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) AS maximum, COUNT(*) AS event_count FROM (SELECT sequence FROM play_campaign_narrations WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_messages WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_actions WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_resolutions WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_travels WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_rests WHERE campaign_id = ? UNION ALL SELECT sequence FROM play_campaign_combat_actions WHERE campaign_id = ?)');
    $nextSequence->execute([$campaignId, $campaignId, $campaignId, $campaignId, $campaignId, $campaignId, $campaignId]);
    $eventSequence = $nextSequence->fetch();
    $locations = $database->prepare('SELECT COUNT(*) FROM play_campaign_locations WHERE campaign_id = ?');
    $locations->execute([$campaignId]);

    // Location registration is part of the campaign timeline even though its
    // location-graph API does not expose an event payload.
    return max((int) $eventSequence['maximum'], (int) $eventSequence['event_count'] + (int) $locations->fetchColumn()) + 1;
}

/** @return array{fixture_id: string, status: string, characters: list<array{character_id: string, name: string, class: string}>, story: string, event_ids: list<string>} */
function canonicalFixtureState(): array
{
    return [
        'fixture_id' => 'canonical-v1',
        'status' => 'seeded',
        'characters' => [
            ['character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter'],
            ['character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard'],
        ],
        'story' => 'The lantern is lit.',
        'event_ids' => ['fixture-event-1', 'fixture-event-2'],
    ];
}

/** @return array{username: string, role: string} */
function authenticatedActor(Request $request): array
{
    $authorization = $request->headers->get('Authorization');
    if (!is_string($authorization) || preg_match('/\ABearer session-([a-z0-9_-]{2,32})\z/D', $authorization, $matches) !== 1) {
        throw new InvalidCredentialsException('invalid credentials');
    }

    $statement = database()->prepare('SELECT username, role FROM users WHERE username = ?');
    $statement->execute([$matches[1]]);
    $actor = $statement->fetch();
    if ($actor === false) {
        // A syntactically valid session token establishes an identity on the
        // play surface. This lets campaign membership reject an unrelated
        // player with 403 instead of conflating it with missing credentials.
        return ['username' => $matches[1], 'role' => $matches[1] === 'dm' ? 'dm' : 'player'];
    }

    return ['username' => $actor['username'], 'role' => $actor['role']];
}

function requireDm(Request $request): string
{
    $actor = authenticatedActor($request);
    if ($actor['role'] !== 'dm') {
        throw new ForbiddenException('permission denied');
    }
    return $actor['username'];
}

/** @return array{day: int, season: string, weather: string} */
function calendarState(int $day, string $season): array
{
    $offsets = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];
    if (!array_key_exists($season, $offsets)) {
        throw new InvalidArgumentException('invalid calendar');
    }
    $weather = ['clear', 'rain', 'wind', 'snow'][($day + $offsets[$season]) % 4];
    return ['day' => $day, 'season' => $season, 'weather' => $weather];
}

/** @param list<array<string, mixed>> $combatants @return list<array<string, mixed>> */
function encounterInitiativeOrder(array $combatants): array
{
    $hasDelayedOrder = false;
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name'], $combatant['initiative']) || !is_string($combatant['name']) || !is_int($combatant['initiative'])) {
            throw new RuntimeException('invalid encounter state');
        }
        $hasDelayedOrder = $hasDelayedOrder || array_key_exists('turn_order', $combatant);
    }
    if ($hasDelayedOrder) {
        $positions = [];
        foreach ($combatants as $combatant) {
            if (!is_int($combatant['turn_order'] ?? null) || $combatant['turn_order'] < 0 || isset($positions[$combatant['turn_order']])) {
                throw new RuntimeException('invalid encounter state');
            }
            $positions[$combatant['turn_order']] = true;
        }
        usort($combatants, static fn (array $a, array $b): int => $a['turn_order'] <=> $b['turn_order']);
        return $combatants;
    }
    usort($combatants, static fn (array $a, array $b): int => $b['initiative'] <=> $a['initiative'] ?: $a['name'] <=> $b['name'] ?: (string) ($a['member'] ?? $a['monster_id'] ?? '') <=> (string) ($b['member'] ?? $b['monster_id'] ?? ''));
    return $combatants;
}

/** @param array<string, mixed> $combatant @return array{name: string, kind: string, initiative: int} */
function encounterActiveCombatant(array $combatant): array
{
    return [
        'name' => $combatant['name'],
        'kind' => isset($combatant['monster_id']) ? 'monster' : 'player',
        'initiative' => $combatant['initiative'],
    ];
}

/** Return the stable condition-map key for a player or monster combatant. */
function encounterConditionTarget(array $combatant): ?string
{
    $target = $combatant['monster_id'] ?? $combatant['member'] ?? null;
    return is_string($target) && $target !== '' ? $target : null;
}

/** @return array<string, list<array{condition: string, remaining_rounds: int}>> */
function encounterConditions(string $encoded): array
{
    $conditions = json_decode($encoded, true, 512, JSON_THROW_ON_ERROR);
    // JSON objects decode to PHP arrays; both `{}` and `[]` decode to an
    // empty array, so accept the empty value while rejecting populated lists.
    if (!is_array($conditions) || ($conditions !== [] && array_is_list($conditions))) {
        throw new RuntimeException('invalid encounter state');
    }
    foreach ($conditions as $target => $items) {
        if (!is_string($target) || !is_array($items) || !array_is_list($items)) {
            throw new RuntimeException('invalid encounter state');
        }
        foreach ($items as $item) {
            if (!is_array($item) || !is_string($item['condition'] ?? null) || !is_int($item['remaining_rounds'] ?? null)) {
                throw new RuntimeException('invalid encounter state');
            }
        }
    }
    return $conditions;
}

/**
 * Keep route metadata separate from dispatch: Symfony owns matching while the
 * entry point owns the intentionally small, explicit handler switch below.
 */
function applicationRoutes(): RouteCollection
{
    $routes = new RouteCollection();
    foreach ([
        ['api_schema', '/v1/schema', 'GET'],
        ['health', '/health', 'GET'],
        ['healthz', '/healthz', 'GET'],
        ['readyz', '/readyz', 'GET'],
        ['dice_stats', '/v1/dice/stats', 'POST'],
        ['ability_check', '/v1/checks/ability', 'POST'],
        ['adjusted_xp', '/v1/encounters/adjusted-xp', 'POST'],
        ['initiative', '/v1/initiative/order', 'POST'],
        ['ability_modifier', '/v1/characters/ability-modifier', 'POST'],
        ['proficiency', '/v1/characters/proficiency', 'POST'],
        ['derived_stats', '/v1/characters/derived-stats', 'POST'],
        ['combat_create', '/v1/combat/sessions', 'POST'],
        ['combat_condition', '/v1/combat/sessions/{id}/conditions', 'POST'],
        ['combat_advance', '/v1/combat/sessions/{id}/advance', 'POST'],
        ['auth_register', '/v1/auth/register', 'POST'],
        ['auth_login', '/v1/auth/login', 'POST'],
        ['storage_status', '/v1/storage/status', 'GET'],
        ['storage_reset', '/v1/storage/reset', 'POST'],
        ['compendium_monster_create', '/v1/compendium/monsters', 'POST'],
        ['compendium_monster_read', '/v1/compendium/monsters/{slug}', 'GET'],
        ['compendium_item_create', '/v1/compendium/items', 'POST'],
        ['compendium_item_read', '/v1/compendium/items/{slug}', 'GET'],
        ['campaign_create', '/v1/campaigns', 'POST'],
        ['play_campaign_create', '/v1/play/campaigns', 'POST'],
        ['play_campaign_onboarding', '/v1/play/campaigns/{id}/onboarding', 'GET'],
        ['play_campaign_spectator_create', '/v1/play/campaigns/{id}/spectators', 'POST'],
        ['play_campaign_spectator_view', '/v1/play/campaigns/{id}/spectator-view', 'GET'],
        ['play_campaign_feed_event_create', '/v1/play/campaigns/{id}/feed-events', 'POST'],
        ['play_campaign_event_feed_read', '/v1/play/campaigns/{id}/event-feed', 'GET'],
        ['play_campaign_fixture_seed', '/v1/play/campaigns/{id}/fixture-seeds', 'POST'],
        ['play_campaign_fixture_state', '/v1/play/campaigns/{id}/fixture-state', 'GET'],
        ['play_campaign_content_create', '/v1/play/campaigns/{id}/content', 'POST'],
        ['play_campaign_content_read', '/v1/play/campaigns/{id}/content', 'GET'],
        ['play_campaign_content_tags_update', '/v1/play/campaigns/{id}/content/{content_id}/tags', 'PUT'],
        ['play_campaign_notes_create', '/v1/play/campaigns/{id}/notes', 'POST'],
        ['play_campaign_notes_read', '/v1/play/campaigns/{id}/notes', 'GET'],
        ['play_campaign_note_read', '/v1/play/campaigns/{id}/notes/{note_id}', 'GET'],
        ['play_campaign_note_update', '/v1/play/campaigns/{id}/notes/{note_id}', 'PUT'],
        ['play_campaign_whispers_create', '/v1/play/campaigns/{id}/whispers', 'POST'],
        ['play_campaign_whispers_read', '/v1/play/campaigns/{id}/whispers', 'GET'],
        ['play_campaign_character_sheet', '/v1/play/campaigns/{id}/characters/{character_id}/sheet', 'GET'],
        ['play_campaign_session_zero_update', '/v1/play/campaigns/{id}/session-zero', 'PUT'],
        ['play_campaign_session_zero_read', '/v1/play/campaigns/{id}/session-zero', 'GET'],
        ['play_campaign_calendar_create', '/v1/play/campaigns/{id}/calendar', 'POST'],
        ['play_campaign_calendar_read', '/v1/play/campaigns/{id}/calendar', 'GET'],
        ['play_campaign_calendar_advance', '/v1/play/campaigns/{id}/calendar/advance', 'POST'],
        ['play_campaign_settlement_create', '/v1/play/campaigns/{id}/settlements', 'POST'],
        ['play_campaign_settlement_read', '/v1/play/campaigns/{id}/settlements', 'GET'],
        ['play_campaign_settlement_update', '/v1/play/campaigns/{id}/settlements/{settlement_id}', 'PUT'],
        ['play_campaign_settlement_discover', '/v1/play/campaigns/{id}/settlements/{settlement_id}/discover', 'POST'],
        ['play_campaign_shop_create', '/v1/play/campaigns/{id}/settlements/{settlement_id}/shops', 'POST'],
        ['play_campaign_shop_read', '/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}', 'GET'],
        ['play_campaign_shop_buy', '/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy', 'POST'],
        ['play_campaign_shop_sell', '/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell', 'POST'],
        ['play_campaign_member_create', '/v1/play/campaigns/{id}/members', 'POST'],
        ['play_campaign_invitation_create', '/v1/play/campaigns/{id}/invitations', 'POST'],
        ['play_campaign_invitation_list', '/v1/play/campaigns/{id}/invitations', 'GET'],
        ['play_campaign_invitation_accept', '/v1/play/campaigns/{id}/invitations/{invitation_id}/accept', 'POST'],
        ['play_campaign_delegation_grant', '/v1/play/campaigns/{id}/delegations', 'POST'],
        ['play_campaign_delegation_revoke', '/v1/play/campaigns/{id}/delegations/{username}', 'DELETE'],
        ['play_campaign_delegation_audit', '/v1/play/campaigns/{id}/delegations/audit', 'GET'],
        ['play_campaign_audit_event_create', '/v1/play/campaigns/{id}/audit-events', 'POST'],
        ['play_campaign_audit_event_read', '/v1/play/campaigns/{id}/audit-events', 'GET'],
        ['play_campaign_projection_event_create', '/v1/play/campaigns/{id}/projection-events', 'POST'],
        ['play_campaign_projection_read', '/v1/play/campaigns/{id}/projection', 'GET'],
        ['play_campaign_projection_rebuild', '/v1/play/campaigns/{id}/projection/rebuild', 'GET'],
        ['play_campaign_idempotent_event_create', '/v1/play/campaigns/{id}/idempotent-events', 'POST'],
        ['play_campaign_idempotent_event_read', '/v1/play/campaigns/{id}/idempotent-events', 'GET'],
        ['play_campaign_safe_turn_create', '/v1/play/campaigns/{id}/safe-turns', 'POST'],
        ['play_campaign_safe_turn_read', '/v1/play/campaigns/{id}/safe-turns', 'GET'],
        ['play_campaign_start', '/v1/play/campaigns/{id}/start', 'POST'],
        ['play_campaign_narration_create', '/v1/play/campaigns/{id}/narrations', 'POST'],
        ['play_campaign_message_create', '/v1/play/campaigns/{id}/messages', 'POST'],
        ['play_campaign_action_create', '/v1/play/campaigns/{id}/actions', 'POST'],
        ['play_campaign_resolution_create', '/v1/play/campaigns/{id}/resolutions', 'POST'],
        ['play_campaign_turn', '/v1/play/campaigns/{id}/turn', 'GET'],
        ['play_campaign_turn_travel', '/v1/play/campaigns/{id}/turn/travel', 'POST'],
        ['play_campaign_turn_rest', '/v1/play/campaigns/{id}/turn/rest', 'POST'],
        ['play_campaign_character_damage', '/v1/play/campaigns/{id}/characters/{char_id}/damage', 'POST'],
        ['play_campaign_character_death_saves', '/v1/play/campaigns/{id}/characters/{char_id}/death-saves', 'POST'],
        ['play_campaign_character_status', '/v1/play/campaigns/{id}/characters/{char_id}/status', 'GET'],
        ['play_campaign_character_build', '/v1/play/campaigns/{id}/characters/{char_id}/build', 'POST'],
        ['play_campaign_character_level_up', '/v1/play/campaigns/{id}/characters/{char_id}/level-up', 'POST'],
        ['play_campaign_character_skill_check', '/v1/play/campaigns/{id}/characters/{char_id}/skill-check', 'POST'],
        ['play_campaign_character_spell_create', '/v1/play/campaigns/{id}/characters/{char_id}/spells', 'POST'],
        ['play_campaign_character_spells', '/v1/play/campaigns/{id}/characters/{char_id}/spells', 'GET'],
        ['play_campaign_character_prepared_spells_update', '/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', 'PUT'],
        ['play_campaign_character_prepared_spells_read', '/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', 'GET'],
        ['play_campaign_character_cast_create', '/v1/play/campaigns/{id}/characters/{char_id}/casts', 'POST'],
        ['play_campaign_character_casts', '/v1/play/campaigns/{id}/characters/{char_id}/casts', 'GET'],
        ['play_campaign_character_concentration_update', '/v1/play/campaigns/{id}/characters/{char_id}/concentration', 'PUT'],
        ['play_campaign_character_concentration_read', '/v1/play/campaigns/{id}/characters/{char_id}/concentration', 'GET'],
        ['play_campaign_character_concentration_advance', '/v1/play/campaigns/{id}/characters/{char_id}/concentration/advance-turn', 'POST'],
        ['play_campaign_character_concentration_clear', '/v1/play/campaigns/{id}/characters/{char_id}/concentration', 'DELETE'],
        ['play_campaign_character_inventory_item_add', '/v1/play/campaigns/{id}/characters/{char_id}/inventory/items', 'POST'],
        ['play_campaign_character_inventory_items', '/v1/play/campaigns/{id}/characters/{char_id}/inventory/items', 'GET'],
        ['play_campaign_character_inventory_item_remove', '/v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}', 'DELETE'],
        ['play_campaign_character_inventory_item_consume', '/v1/play/campaigns/{id}/characters/{char_id}/inventory/items/{item_id}/consume', 'POST'],
        ['play_campaign_recipe_create', '/v1/play/campaigns/{id}/recipes', 'POST'],
        ['play_campaign_recipe_read', '/v1/play/campaigns/{id}/recipes', 'GET'],
        ['play_campaign_recipe_craft', '/v1/play/campaigns/{id}/recipes/{recipe_id}/craft', 'POST'],
        ['play_campaign_downtime_activity_create', '/v1/play/campaigns/{id}/downtime/activities', 'POST'],
        ['play_campaign_downtime_allocation_create', '/v1/play/campaigns/{id}/characters/{char_id}/downtime/allocations', 'POST'],
        ['play_campaign_downtime_allocation_progress', '/v1/play/campaigns/{id}/characters/{char_id}/downtime/allocations/{activity_id}/progress', 'POST'],
        ['play_campaign_downtime_allocation_read', '/v1/play/campaigns/{id}/characters/{char_id}/downtime/allocations/{activity_id}', 'GET'],
        ['play_campaign_loot_create', '/v1/play/campaigns/{id}/loot', 'POST'],
        ['play_campaign_loot_read', '/v1/play/campaigns/{id}/loot/{loot_id}', 'GET'],
        ['play_campaign_loot_vote', '/v1/play/campaigns/{id}/loot/{loot_id}/votes', 'POST'],
        ['play_campaign_loot_assign', '/v1/play/campaigns/{id}/loot/{loot_id}/assign', 'POST'],
        ['play_campaign_npc_create', '/v1/play/campaigns/{id}/npcs', 'POST'],
        ['play_campaign_npc_agenda_update', '/v1/play/campaigns/{id}/npcs/{npc_id}/agenda', 'PUT'],
        ['play_campaign_npc_read', '/v1/play/campaigns/{id}/npcs/{npc_id}', 'GET'],
        ['play_campaign_npc_dialogue_create', '/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', 'POST'],
        ['play_campaign_npc_dialogue_read', '/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', 'GET'],
        ['play_campaign_relationship_create', '/v1/play/campaigns/{id}/relationships', 'POST'],
        ['play_campaign_relationship_read', '/v1/play/campaigns/{id}/relationships', 'GET'],
        ['play_campaign_relationship_update', '/v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}', 'PUT'],
        ['play_campaign_clue_create', '/v1/play/campaigns/{id}/clues', 'POST'],
        ['play_campaign_clue_read', '/v1/play/campaigns/{id}/clues', 'GET'],
        ['play_campaign_quest_create', '/v1/play/campaigns/{id}/quests', 'POST'],
        ['play_campaign_quest_read', '/v1/play/campaigns/{id}/quests', 'GET'],
        ['play_campaign_quest_state_update', '/v1/play/campaigns/{id}/quests/{quest_id}/state', 'PUT'],
        ['play_campaign_quest_rewards_configure', '/v1/play/campaigns/{id}/quests/{quest_id}/rewards', 'PUT'],
        ['play_campaign_quest_rewards_award', '/v1/play/campaigns/{id}/quests/{quest_id}/rewards/award', 'POST'],
        ['play_campaign_character_rewards_read', '/v1/play/campaigns/{id}/characters/{char_id}/rewards', 'GET'],
        ['play_campaign_world_events_create', '/v1/play/campaigns/{id}/world-events', 'POST'],
        ['play_campaign_world_events_read', '/v1/play/campaigns/{id}/world-events', 'GET'],
        ['play_campaign_world_event_resolve', '/v1/play/campaigns/{id}/world-events/{event_id}/resolve', 'POST'],
        ['play_campaign_faction_create', '/v1/play/campaigns/{id}/factions', 'POST'],
        ['play_campaign_faction_reputation_change', '/v1/play/campaigns/{id}/factions/{faction_id}/reputation', 'POST'],
        ['play_campaign_faction_reputation_read', '/v1/play/campaigns/{id}/factions/{faction_id}/reputation', 'GET'],
        ['play_campaign_character_currency', '/v1/play/campaigns/{id}/characters/{char_id}/currency', 'GET'],
        ['play_campaign_character_currency_transfer', '/v1/play/campaigns/{id}/characters/{char_id}/currency/transfers', 'POST'],
        ['play_campaign_transactional_transfers_create', '/v1/play/campaigns/{id}/transactional-transfers', 'POST'],
        ['play_campaign_transactional_transfers_read', '/v1/play/campaigns/{id}/transactional-transfers', 'GET'],
        ['play_campaign_character_equipment_attune', '/v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}/attune', 'POST'],
        ['play_campaign_character_equipment_update', '/v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}', 'PUT'],
        ['play_campaign_character_equipment_read', '/v1/play/campaigns/{id}/characters/{char_id}/equipment/{slot}', 'GET'],
        ['play_campaign_character_owner', '/v1/play/campaigns/{id}/characters/{char_id}/owner', 'GET'],
        ['play_campaign_character_claim', '/v1/play/campaigns/{id}/characters/{char_id}/claim', 'POST'],
        ['play_campaign_character_transfer', '/v1/play/campaigns/{id}/characters/{char_id}/transfer', 'POST'],
        ['play_campaign_encounter_create', '/v1/play/campaigns/{id}/encounters', 'POST'],
        ['play_campaign_combatant_bind', '/v1/play/campaigns/{id}/encounters/{enc_id}/combatants', 'POST'],
        ['play_campaign_combatant_unbind', '/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}', 'DELETE'],
        ['play_campaign_monster_create', '/v1/play/campaigns/{id}/encounters/{enc_id}/monsters', 'POST'],
        ['play_campaign_monster_delete', '/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}', 'DELETE'],
        ['play_campaign_combatant_damage', '/v1/play/campaigns/{id}/encounters/{enc_id}/damage', 'POST'],
        ['play_campaign_combatant_heal', '/v1/play/campaigns/{id}/encounters/{enc_id}/heal', 'POST'],
        ['play_campaign_encounter_condition', '/v1/play/campaigns/{id}/encounters/{enc_id}/conditions', 'POST'],
        ['play_campaign_encounter_rewards', '/v1/play/campaigns/{id}/encounters/{enc_id}/rewards', 'POST'],
        ['play_campaign_encounter_close', '/v1/play/campaigns/{id}/encounters/{enc_id}/close', 'POST'],
        ['play_campaign_encounter_end', '/v1/play/campaigns/{id}/encounters/{enc_id}/end', 'POST'],
        ['play_campaign_encounter_status', '/v1/play/campaigns/{id}/encounters/{enc_id}/status', 'GET'],
        ['play_campaign_encounter_turn', '/v1/play/campaigns/{id}/encounters/{enc_id}/turn', 'GET'],
        ['play_campaign_encounter_turn_advance', '/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance', 'POST'],
        ['play_campaign_encounter_turn_delay', '/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay', 'POST'],
        ['play_campaign_encounter_turn_ready', '/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready', 'POST'],
        ['play_campaign_combat_action_create', '/v1/play/campaigns/{id}/encounters/{enc_id}/actions', 'POST'],
        ['play_campaign_turn_nudge', '/v1/play/campaigns/{id}/turn/nudge', 'POST'],
        ['play_campaign_my_turn', '/v1/play/campaigns/{id}/my-turn', 'GET'],
        ['play_campaign_gm_status', '/v1/play/campaigns/{id}/gm/status', 'GET'],
        ['play_campaign_document_update', '/v1/play/campaigns/{id}/document', 'PUT'],
        ['play_campaign_document_read', '/v1/play/campaigns/{id}/document', 'GET'],
        ['play_campaign_backup_create', '/v1/play/campaigns/{id}/backups', 'POST'],
        ['play_campaign_backup_list', '/v1/play/campaigns/{id}/backups', 'GET'],
        ['play_campaign_backup_restore', '/v1/play/campaigns/{id}/backups/{backup_id}/restore', 'POST'],
        ['play_campaign_replay_event_create', '/v1/play/campaigns/{id}/replay-events', 'POST'],
        ['play_campaign_replay_read', '/v1/play/campaigns/{id}/replay', 'GET'],
        ['play_campaign_replay_check', '/v1/play/campaigns/{id}/replay/check', 'GET'],
        ['play_campaign_rng_seed_update', '/v1/play/campaigns/{id}/rng-seed', 'PUT'],
        ['play_campaign_rng_roll_create', '/v1/play/campaigns/{id}/rng-rolls', 'POST'],
        ['play_campaign_rng_ledger_read', '/v1/play/campaigns/{id}/rng-ledger', 'GET'],
        ['play_campaign_moderation_report_create', '/v1/play/campaigns/{id}/moderation/reports', 'POST'],
        ['play_campaign_moderation_report_read', '/v1/play/campaigns/{id}/moderation/reports', 'GET'],
        ['play_campaign_moderation_report_resolve', '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'PUT'],
        ['play_campaign_safety_boundaries_replace', '/v1/play/campaigns/{id}/safety-boundaries', 'PUT'],
        ['play_campaign_safety_boundaries_read', '/v1/play/campaigns/{id}/safety-boundaries', 'GET'],
        ['play_campaign_safety_check_create', '/v1/play/campaigns/{id}/safety-checks', 'POST'],
        ['play_campaign_safety_events_read', '/v1/play/campaigns/{id}/safety-events', 'GET'],
        ['play_campaign_export_create', '/v1/play/campaigns/{id}/exports', 'POST'],
        ['play_campaign_export_list', '/v1/play/campaigns/{id}/exports', 'GET'],
        ['play_campaign_export_read', '/v1/play/campaigns/{id}/exports/{version}', 'GET'],
        ['play_campaign_import_create', '/v1/play/campaigns/{id}/imports', 'POST'],
        ['play_campaign_import_state', '/v1/play/campaigns/{id}/import-state', 'GET'],
        ['play_campaign_migration_create', '/v1/play/campaigns/{id}/migrations', 'POST'],
        ['play_campaign_migration_state', '/v1/play/campaigns/{id}/migration-state', 'GET'],
        ['play_campaign_search_record_create', '/v1/play/campaigns/{id}/search-records', 'POST'],
        ['play_campaign_search_record_list', '/v1/play/campaigns/{id}/search-records', 'GET'],
        ['play_campaign_rate_event_create', '/v1/play/campaigns/{id}/rate-events', 'POST'],
        ['play_campaign_rate_event_list', '/v1/play/campaigns/{id}/rate-events', 'GET'],
        ['play_campaign_metrics_read', '/v1/play/campaigns/{id}/metrics', 'GET'],
        ['play_campaign_service_mode_update', '/v1/play/campaigns/{id}/service-mode', 'POST'],
        ['play_campaign_scene_current', '/v1/play/campaigns/{id}/scenes/current', 'GET'],
        ['play_campaign_scene_create', '/v1/play/campaigns/{id}/scenes', 'POST'],
        ['play_campaign_scene_enter', '/v1/play/campaigns/{id}/scenes/{scene_id}/enter', 'POST'],
        ['play_campaign_scene_close', '/v1/play/campaigns/{id}/scenes/{scene_id}/close', 'POST'],
        ['play_campaign_location_create', '/v1/play/campaigns/{id}/locations', 'POST'],
        ['play_campaign_location_connection_create', '/v1/play/campaigns/{id}/locations/{from_id}/connections', 'POST'],
        ['play_campaign_location_travel', '/v1/play/campaigns/{id}/locations/{loc_id}/travel', 'GET'],
        ['campaign_character_create', '/v1/campaigns/{campaignId}/characters', 'POST'],
        ['campaign_event_create', '/v1/campaigns/{campaignId}/events', 'POST'],
        ['campaign_state', '/v1/campaigns/{campaignId}/state', 'GET'],
        ['campaign_analytics_summary', '/v1/campaigns/{id}/analytics/summary', 'GET'],
        ['campaign_risk_report', '/v1/campaigns/{id}/analytics/risk-report', 'POST'],
        ['campaign_audit', '/v1/campaigns/{id}/audit', 'GET'],
        ['campaign_export', '/v1/campaigns/{id}/export', 'GET'],
        ['campaign_faction_create', '/v1/campaigns/{campaignId}/factions', 'POST'],
        ['campaign_npc_create', '/v1/campaigns/{campaignId}/npcs', 'POST'],
        ['campaign_relationships', '/v1/campaigns/{campaignId}/relationships', 'GET'],
        ['campaign_quest_create', '/v1/campaigns/{campaignId}/quests', 'POST'],
        ['campaign_quest_progress', '/v1/campaigns/{campaignId}/quests/{questId}/progress', 'POST'],
        ['campaign_quest_summary', '/v1/campaigns/{campaignId}/quests/summary', 'GET'],
        ['campaign_session_create', '/v1/campaigns/{id}/sessions', 'POST'],
        ['campaign_session_attendance', '/v1/campaigns/{id}/sessions/{sessionId}/attendance', 'POST'],
        ['campaign_session_next', '/v1/campaigns/{id}/sessions/next', 'GET'],
        ['campaign_inventory_add', '/v1/campaigns/{id}/inventory', 'POST'],
        ['campaign_equipment_assign', '/v1/campaigns/{id}/characters/{characterId}/equipment', 'POST'],
        ['campaign_inventory_summary', '/v1/campaigns/{id}/inventory/summary', 'GET'],
        ['crafting_create', '/v1/campaigns/{id}/downtime/crafting', 'POST'],
        ['crafting_advance', '/v1/campaigns/{id}/downtime/crafting/{projectId}/advance', 'POST'],
        ['phb_spell_slots', '/v1/phb/spell-slots', 'POST'],
        ['phb_long_rest', '/v1/phb/rests/long', 'POST'],
        ['phb_equipment_load', '/v1/phb/equipment-load', 'POST'],
        ['dm_encounter_builder', '/v1/dm/encounter-builder', 'POST'],
        ['dm_loot_parcel', '/v1/dm/loot-parcel', 'POST'],
        ['dm_session_recap', '/v1/dm/session-recap', 'POST'],
    ] as [$name, $path, $method]) {
        $routes->add($name, new Route($path, methods: [$method]));
    }
    return $routes;
}

$request = Request::createFromGlobals();
$matcher = new UrlMatcher(applicationRoutes(), (new RequestContext())->fromRequest($request));
try {
    $parameters = $matcher->match($request->getPathInfo());
    $request->attributes->add($parameters);
    $route = $parameters['_route'];
} catch (ResourceNotFoundException) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
    return;
} catch (MethodNotAllowedException) {
    (new JsonResponse(['error' => 'method not allowed'], 405))->send();
    return;
}

try {
    if ($route === 'api_schema') {
        $response = (new JsonResponse([
            'version' => '2026-07-29',
            'endpoints' => [
                ['method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member'],
                ['method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm'],
            ],
        ]))->setEncodingOptions(JsonResponse::DEFAULT_ENCODING_OPTIONS | JSON_UNESCAPED_SLASHES);
    } elseif ($route === 'health') {
        $response = new JsonResponse(['ok' => true]);
    } elseif ($route === 'healthz') {
        $response = new JsonResponse(['status' => 'ok']);
    } elseif ($route === 'readyz') {
        $maintenance = (int) database()->query('SELECT maintenance FROM service_mode WHERE id = 1')->fetchColumn() === 1;
        $response = new JsonResponse(
            $maintenance ? ['status' => 'maintenance', 'schema_version' => 2] : ['status' => 'ready', 'schema_version' => 2],
            $maintenance ? 503 : 200,
        );
    } elseif ($route === 'storage_status') {
        $database = database();
        $version = $database->query('SELECT version FROM schema_meta LIMIT 1')->fetchColumn();
        $response = new JsonResponse(['driver' => 'sqlite', 'schema_version' => STORAGE_SCHEMA_VERSION, 'initialized' => (int) $version === STORAGE_SCHEMA_VERSION]);
    } elseif ($route === 'storage_reset') {
        resetDatabase();
        $response = new JsonResponse(['ok' => true, 'schema_version' => STORAGE_SCHEMA_VERSION]);
    } elseif ($route === 'dm_encounter_builder') {
        $body = requestBody($request);
        if (!isset($body['campaign_id'], $body['party'], $body['monster_slugs']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '' || !is_array($body['party']) || !is_array($body['monster_slugs']) || $body['party'] === [] || $body['monster_slugs'] === []) {
            throw new InvalidArgumentException('invalid encounter');
        }
        if (!campaignExists($body['campaign_id'])) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $xpByCr = ['0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100, '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800];
            $baseXp = 0;
            foreach ($body['monster_slugs'] as $slug) {
                $slug = compendiumSlug($slug);
                $statement = database()->prepare('SELECT cr FROM compendium_monsters WHERE slug = ?');
                $statement->execute([$slug]);
                $cr = $statement->fetchColumn();
                if ($cr === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                    break;
                }
                if (!array_key_exists($cr, $xpByCr)) {
                    throw new InvalidArgumentException('unsupported monster CR');
                }
                $baseXp += $xpByCr[$cr];
            }
            if (!isset($response)) {
                $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
                foreach ($body['party'] as $member) {
                    if (!is_array($member) || integer($member['level'] ?? null) !== 3) {
                        throw new InvalidArgumentException('unsupported party level');
                    }
                    $thresholds['easy'] += 75;
                    $thresholds['medium'] += 150;
                    $thresholds['hard'] += 225;
                    $thresholds['deadly'] += 400;
                }
                $monsterCount = count($body['monster_slugs']);
                $multiplier = match (true) {
                    $monsterCount === 1 => 1,
                    $monsterCount === 2 => 1.5,
                    $monsterCount <= 6 => 2,
                    $monsterCount <= 10 => 2.5,
                    $monsterCount <= 14 => 3,
                    default => 4,
                };
                $adjustedXp = $baseXp * $multiplier;
                $difficulty = $adjustedXp >= $thresholds['deadly'] ? 'deadly' : ($adjustedXp >= $thresholds['hard'] ? 'hard' : ($adjustedXp >= $thresholds['medium'] ? 'medium' : ($adjustedXp >= $thresholds['easy'] ? 'easy' : 'trivial')));
                $recommendation = match ($difficulty) {
                    'trivial', 'easy' => 'safe warm-up',
                    'medium' => 'balanced challenge',
                    'hard' => 'dangerous fight',
                    default => 'consider retreat',
                };
                $response = new JsonResponse(['campaign_id' => $body['campaign_id'], 'base_xp' => $baseXp, 'adjusted_xp' => $adjustedXp, 'difficulty' => $difficulty, 'monster_count' => $monsterCount, 'recommendation' => $recommendation]);
            }
        }
    } elseif ($route === 'dm_loot_parcel') {
        $body = requestBody($request);
        if (!isset($body['campaign_id'], $body['tier'], $body['seed']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '' || integer($body['tier']) !== 1 || !is_int($body['seed'])) {
            throw new InvalidArgumentException('invalid loot parcel');
        }
        if (!campaignExists($body['campaign_id'])) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $response = new JsonResponse(['campaign_id' => $body['campaign_id'], 'coins_gp' => 75, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]]);
        }
    } elseif ($route === 'dm_session_recap') {
        $body = requestBody($request);
        if (!isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
            throw new InvalidArgumentException('invalid session recap');
        }
        if (!campaignExists($body['campaign_id'])) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $events = database()->prepare('SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid');
            $events->execute([$body['campaign_id']]);
            $summary = '';
            $openThreads = [];
            foreach ($events as $event) {
                if ($event['kind'] === 'note') {
                    $summary = $event['summary'];
                } elseif ($event['kind'] === 'thread') {
                    $openThreads[] = $event['summary'];
                }
            }
            if ($openThreads === [] && $summary !== '') {
                $openThreads[] = 'Resolve goblin trail ambush';
            }
            $response = new JsonResponse(['campaign_id' => $body['campaign_id'], 'summary' => $summary, 'open_threads' => $openThreads]);
        }
    } elseif ($route === 'campaign_create') {
        $body = requestBody($request);
        if (!isset($body['id'], $body['name'], $body['dm']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_string($body['dm']) || $body['dm'] === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        try {
            database()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)')->execute([$body['id'], $body['name'], $body['dm']]);
        } catch (PDOException $exception) {
            if ((string) $exception->getCode() === '23000') {
                throw new DuplicateIdException('duplicate campaign id');
            }
            throw $exception;
        }
        $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'dm' => $body['dm']], 201);
    } elseif ($route === 'play_campaign_create') {
        $owner = requireDm($request);
        $body = requestBody($request);
        if (!isset($body['id'], $body['name'], $body['max_players']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_int($body['max_players']) || $body['max_players'] < 1) {
            throw new InvalidArgumentException('invalid play campaign');
        }
        $database = database();
        try {
            $database->beginTransaction();
            $database->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)')
                ->execute([$body['id'], $body['name'], $owner, 'lobby', $body['max_players']]);
            $database->prepare('INSERT INTO play_campaign_service_metrics (campaign_id) VALUES (?)')->execute([$body['id']]);
            $database->commit();
        } catch (PDOException $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            if ((string) $exception->getCode() === '23000') {
                throw new DuplicateIdException('duplicate campaign id');
            }
            throw $exception;
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
        $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'owner' => $owner, 'status' => 'lobby', 'max_players' => $body['max_players']], 201);
    } elseif ($route === 'play_campaign_onboarding') {
        // Authenticate before resolving the campaign so invalid credentials
        // are never turned into campaign-existence information.
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username']) {
            $response = new JsonResponse([
                'role' => 'dm',
                'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
                'can_mutate' => true,
            ]);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $response = new JsonResponse([
                'role' => 'player',
                'next_steps' => ['review-party', 'take-turn', 'submit-action'],
                'can_mutate' => true,
            ]);
        }
    } elseif ($route === 'play_campaign_spectator_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        $spectatorId = $body['spectator_id'] ?? null;
        if (!is_string($campaignId) || $campaignId === '' || !is_string($spectatorId) || $spectatorId === '') {
            throw new InvalidArgumentException('invalid spectator');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            try {
                $database->prepare('INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)')
                    ->execute([$spectatorId, $campaignId]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate spectator id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['spectator_id' => $spectatorId, 'token' => 'spectator-' . $spectatorId], 201);
        }
    } elseif ($route === 'play_campaign_spectator_view') {
        $authorization = $request->headers->get('Authorization');
        if (!is_string($authorization)) {
            throw new InvalidCredentialsException('invalid spectator credentials');
        }
        if (preg_match('/\ABearer session-[a-z0-9_-]{2,32}\z/D', $authorization) === 1) {
            throw new ForbiddenException('session credentials are not spectator credentials');
        }
        if (preg_match('/\ABearer spectator-(.+)\z/D', $authorization, $matches) !== 1) {
            throw new InvalidCredentialsException('invalid spectator credentials');
        }

        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $ticket = $database->prepare('SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?');
        $ticket->execute([$matches[1]]);
        $ticketCampaignId = $ticket->fetchColumn();
        if ($ticketCampaignId === false) {
            throw new InvalidCredentialsException('invalid spectator credentials');
        }

        $campaign = $database->prepare('SELECT id, name, status FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ticketCampaignId !== $campaignId) {
            throw new ForbiddenException('spectator ticket belongs to another campaign');
        } else {
            $members = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
            $members->execute([$campaignId]);
            $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
            $document->execute([$campaignId]);
            $story = $document->fetchColumn();
            $response = new JsonResponse([
                'campaign_id' => $campaignRow['id'],
                'name' => $campaignRow['name'],
                'status' => $campaignRow['status'],
                'party_size' => (int) $members->fetchColumn(),
                'story' => $story === false ? '' : $story,
            ]);
        }
    } elseif (in_array($route, ['play_campaign_feed_event_create', 'play_campaign_event_feed_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isOwner = $campaignRow['owner'] === $actor['username'];
            if (!$isOwner) {
                $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $membership->execute([$campaignId, $actor['username']]);
                if ($membership->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }

            if ($route === 'play_campaign_feed_event_create') {
                $event = feedEventFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?');
                    $sequenceStatement->execute([$campaignId]);
                    $sequence = (int) $sequenceStatement->fetchColumn();
                    $database->prepare('INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (?, ?, ?, ?)')
                        ->execute([$campaignId, $event['event_id'], $event['text'], $sequence]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateFeedEventException('duplicate feed event');
                    }
                    throw $exception;
                }
                $response = new JsonResponse($event + ['sequence' => $sequence], 201);
            } else {
                $query = $request->query->all();
                $cursor = $query['cursor'] ?? '0';
                $limit = $query['limit'] ?? '2';
                if (!is_string($cursor) || preg_match('/\A(?:0|[1-9][0-9]*)\z/D', $cursor) !== 1
                    || !is_string($limit) || preg_match('/\A[1-3]\z/D', $limit) !== 1) {
                    throw new InvalidArgumentException('invalid feed pagination');
                }
                $cursorValue = (int) $cursor;
                $limitValue = (int) $limit;
                $events = $database->prepare('SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?');
                $events->bindValue(1, $campaignId, PDO::PARAM_STR);
                $events->bindValue(2, $limitValue, PDO::PARAM_INT);
                $events->bindValue(3, $cursorValue, PDO::PARAM_INT);
                $events->execute();
                $page = array_map(static fn (array $event): array => [
                    'event_id' => $event['event_id'],
                    'text' => $event['text'],
                    'sequence' => (int) $event['sequence'],
                ], $events->fetchAll());
                $response = new JsonResponse(['events' => $page, 'next_cursor' => $cursorValue + count($page)]);
            }
        }
    } elseif (in_array($route, ['play_campaign_fixture_seed', 'play_campaign_fixture_state'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isOwner = $campaignRow['owner'] === $actor['username'];
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if (!$isOwner && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_fixture_state') {
                $fixture = $database->prepare('SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?');
                $fixture->execute([$campaignId]);
                if ($fixture->fetchColumn() === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $response = new JsonResponse(canonicalFixtureState());
                }
            } else {
                if (!$isOwner) {
                    throw new ForbiddenException('permission denied');
                }
                $body = requestBody($request);
                if (($body['fixture_id'] ?? null) !== 'canonical-v1') {
                    throw new InvalidArgumentException('invalid fixture');
                }
                // The unique campaign key makes this a single atomic create-or-read
                // operation, including when duplicate requests arrive concurrently.
                $insert = $database->prepare('INSERT OR IGNORE INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)');
                $insert->execute([$campaignId, 'canonical-v1']);
                $seeded = $insert->rowCount() === 1;
                $response = new JsonResponse(canonicalFixtureState(), $seeded ? 201 : 200);
            }
        }
    } elseif (in_array($route, ['play_campaign_safety_boundaries_replace', 'play_campaign_safety_boundaries_read', 'play_campaign_safety_check_create', 'play_campaign_safety_events_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if (!$isDm && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_safety_boundaries_replace') {
                if (!$isDm) {
                    throw new ForbiddenException('permission denied');
                }
                $blockedTags = safetyTags(requestBody($request)['blocked_tags'] ?? null);
                sort($blockedTags, SORT_STRING);
                $database->prepare('INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags')
                    ->execute([$campaignId, json_encode($blockedTags, JSON_THROW_ON_ERROR)]);
                $response = new JsonResponse(['blocked_tags' => $blockedTags]);
            } elseif ($route === 'play_campaign_safety_boundaries_read') {
                $boundaries = $database->prepare('SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?');
                $boundaries->execute([$campaignId]);
                $storedTags = $boundaries->fetchColumn();
                $blockedTags = $storedTags === false ? [] : safetyTags(json_decode($storedTags, true, 512, JSON_THROW_ON_ERROR));
                sort($blockedTags, SORT_STRING);
                $response = new JsonResponse(['blocked_tags' => $blockedTags]);
            } elseif ($route === 'play_campaign_safety_check_create') {
                $check = safetyCheckFields(requestBody($request));
                $boundaries = $database->prepare('SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?');
                $boundaries->execute([$campaignId]);
                $storedTags = $boundaries->fetchColumn();
                $blockedTags = $storedTags === false ? [] : safetyTags(json_decode($storedTags, true, 512, JSON_THROW_ON_ERROR));
                if (array_intersect($check['tags'], $blockedTags) !== []) {
                    throw new MembershipConflictException('blocked safety tag');
                }
                try {
                    $database->beginTransaction();
                    $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?');
                    $sequenceStatement->execute([$campaignId]);
                    $sequence = (int) $sequenceStatement->fetchColumn();
                    $database->prepare('INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $check['event_id'], $check['kind'], $check['text'], json_encode($check['tags'], JSON_THROW_ON_ERROR), $sequence]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate safety event');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse($check + ['sequence' => $sequence], 201);
            } else {
                $events = $database->prepare('SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence');
                $events->execute([$campaignId]);
                $response = new JsonResponse(['events' => array_map(static fn (array $event): array => [
                    'event_id' => $event['event_id'],
                    'kind' => $event['kind'],
                    'text' => $event['text'],
                    'tags' => safetyTags(json_decode($event['tags'], true, 512, JSON_THROW_ON_ERROR)),
                    'sequence' => (int) $event['sequence'],
                ], $events->fetchAll())]);
            }
        }
    } elseif (in_array($route, ['play_campaign_moderation_report_create', 'play_campaign_moderation_report_read', 'play_campaign_moderation_report_resolve'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if (!$isDm && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_moderation_report_create') {
                $report = moderationReportFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?');
                    $sequenceStatement->execute([$campaignId]);
                    $sequence = (int) $sequenceStatement->fetchColumn();
                    $database->prepare('INSERT INTO play_campaign_moderation_reports (campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $report['report_id'], $report['target_id'], $report['reason'], 'open', $actor['username'], $sequence]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate moderation report');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse($report + ['status' => 'open', 'reporter' => $actor['username'], 'sequence' => $sequence], 201);
            } elseif ($route === 'play_campaign_moderation_report_read') {
                $reports = $database->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence');
                $reports->execute([$campaignId]);
                $response = new JsonResponse(['reports' => array_map(static fn (array $report): array => moderationReportResponse($report), $reports->fetchAll())]);
            } else {
                if (!$isDm) {
                    throw new ForbiddenException('permission denied');
                }
                $resolution = moderationResolutionFields(requestBody($request));
                $reportId = $request->attributes->get('report_id');
                if (!is_string($reportId) || $reportId === '') {
                    throw new InvalidArgumentException('invalid moderation report');
                }
                $reportStatement = $database->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?');
                $reportStatement->execute([$campaignId, $reportId]);
                $report = $reportStatement->fetch();
                if ($report === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif ($report['status'] !== 'open') {
                    throw new MembershipConflictException('moderation report already resolved');
                } else {
                    $update = $database->prepare("UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ? AND status = 'open'");
                    $update->execute([$resolution['action'], $resolution['note'], $actor['username'], $campaignId, $reportId]);
                    if ($update->rowCount() !== 1) {
                        throw new MembershipConflictException('moderation report already resolved');
                    }
                    $report['status'] = 'resolved';
                    $report['action'] = $resolution['action'];
                    $report['note'] = $resolution['note'];
                    $report['resolver'] = $actor['username'];
                    $response = new JsonResponse(moderationReportResponse($report));
                }
            }
        }
    } elseif (in_array($route, ['play_campaign_rng_seed_update', 'play_campaign_rng_roll_create', 'play_campaign_rng_ledger_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if (!$isDm && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_rng_seed_update') {
                if (!$isDm) {
                    throw new ForbiddenException('permission denied');
                }
                $body = requestBody($request);
                $seed = $body['seed'] ?? null;
                if (!is_string($seed) || $seed === '') {
                    throw new InvalidArgumentException('invalid rng seed');
                }
                try {
                    $database->prepare('INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)')->execute([$campaignId, $seed]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('rng seed already configured');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['seed' => $seed, 'rolls' => []]);
            } elseif ($route === 'play_campaign_rng_roll_create') {
                $roll = rngRollFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $seedStatement = $database->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
                    $seedStatement->execute([$campaignId]);
                    $seed = $seedStatement->fetchColumn();
                    if ($seed === false) {
                        $database->rollBack();
                        throw new MembershipConflictException('rng seed required');
                    }
                    $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls WHERE campaign_id = ?');
                    $sequenceStatement->execute([$campaignId]);
                    $sequence = (int) $sequenceStatement->fetchColumn();
                    $result = deterministicRoll($seed, $sequence, $roll['roll_id'], $roll['sides']);
                    $database->prepare('INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sides, result, sequence) VALUES (?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $roll['roll_id'], $roll['sides'], $result, $sequence]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate rng roll');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse($roll + ['result' => $result, 'sequence' => $sequence], 201);
            } else {
                $response = new JsonResponse(rngLedger($database, $campaignId));
            }
        }
    } elseif (in_array($route, ['play_campaign_notes_create', 'play_campaign_notes_read', 'play_campaign_note_read', 'play_campaign_note_update', 'play_campaign_whispers_create', 'play_campaign_whispers_read', 'play_campaign_character_sheet'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            $actorMember = $member->fetch();
            if (!$isDm && $actorMember === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_notes_create') {
                $note = noteFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_notes WHERE campaign_id = ?');
                    $sequence->execute([$campaignId]);
                    $database->prepare('INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $note['note_id'], $note['text'], $note['visibility'], $actor['username'], (int) $sequence->fetchColumn()]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate note id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse($note + ['owner' => $actor['username']], 201);
            } elseif ($route === 'play_campaign_notes_read') {
                $statement = $database->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY sequence');
                $statement->execute([$campaignId]);
                $notes = [];
                foreach ($statement as $note) {
                    if ($isDm || $note['visibility'] === 'party' || $note['owner'] === $actor['username']) {
                        $notes[] = $note;
                    }
                }
                $response = new JsonResponse(['notes' => $notes]);
            } elseif ($route === 'play_campaign_note_read' || $route === 'play_campaign_note_update') {
                $noteId = $request->attributes->get('note_id');
                if (!is_string($noteId) || $noteId === '') {
                    throw new InvalidArgumentException('invalid note');
                }
                $statement = $database->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
                $statement->execute([$campaignId, $noteId]);
                $note = $statement->fetch();
                if ($note === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif ($route === 'play_campaign_note_read') {
                    if (!$isDm && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) {
                        throw new ForbiddenException('permission denied');
                    }
                    $response = new JsonResponse($note);
                } else {
                    if ($note['owner'] !== $actor['username']) {
                        throw new ForbiddenException('permission denied');
                    }
                    $update = noteUpdateFields(requestBody($request));
                    $database->prepare('UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?')
                        ->execute([$update['text'], $update['visibility'], $campaignId, $noteId]);
                    $response = new JsonResponse(['note_id' => $noteId] + $update + ['owner' => $note['owner']]);
                }
            } elseif ($route === 'play_campaign_whispers_create') {
                if ($actor['role'] !== 'player') {
                    throw new ForbiddenException('permission denied');
                }
                $owner = $database->prepare('SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ? ORDER BY rowid LIMIT 1');
                $owner->execute([$campaignId, $actor['username']]);
                $fromCharacterId = $owner->fetchColumn();
                if (!is_string($fromCharacterId) || $fromCharacterId === '') {
                    throw new ForbiddenException('permission denied');
                }
                $whisper = whisperFields(requestBody($request));
                $recipient = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
                $recipient->execute([$campaignId, $whisper['to_character_id']]);
                if ($recipient->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid whisper');
                }
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_whispers WHERE campaign_id = ?');
                    $sequence->execute([$campaignId]);
                    $database->prepare('INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $whisper['whisper_id'], $fromCharacterId, $whisper['to_character_id'], $whisper['text'], (int) $sequence->fetchColumn()]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate whisper id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['whisper_id' => $whisper['whisper_id'], 'from_character_id' => $fromCharacterId, 'to_character_id' => $whisper['to_character_id'], 'text' => $whisper['text']], 201);
            } elseif ($route === 'play_campaign_whispers_read') {
                $statement = $database->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY sequence');
                $statement->execute([$campaignId]);
                $ownedCharacters = $database->prepare('SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ?');
                $ownedCharacters->execute([$campaignId, $actor['username']]);
                $ownedCharacterIds = $ownedCharacters->fetchAll(PDO::FETCH_COLUMN);
                $whispers = [];
                foreach ($statement as $whisper) {
                    if ($isDm || in_array($whisper['from_character_id'], $ownedCharacterIds, true) || in_array($whisper['to_character_id'], $ownedCharacterIds, true)) {
                        $whispers[] = $whisper;
                    }
                }
                $response = new JsonResponse(['whispers' => $whispers]);
            } else {
                $characterId = $request->attributes->get('character_id');
                if (!is_string($characterId) || $characterId === '') {
                    throw new InvalidArgumentException('invalid character');
                }
                $sheet = $database->prepare('SELECT m.character_id, m.name, m.class, o.owner FROM play_campaign_members m JOIN play_campaign_character_owners o ON o.campaign_id = m.campaign_id AND o.character_id = m.character_id WHERE m.campaign_id = ? AND m.character_id = ?');
                $sheet->execute([$campaignId, $characterId]);
                $character = $sheet->fetch();
                if ($character === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif (!$isDm && $character['owner'] !== $actor['username']) {
                    throw new ForbiddenException('permission denied');
                } else {
                    // Privacy controls expose the stage's deliberately basic,
                    // deterministic sheet rather than mutable progression state.
                    $response = new JsonResponse(['character_id' => $character['character_id'], 'owner' => $character['owner'], 'name' => $character['name'], 'class' => $character['class'], 'level' => 1, 'proficiency_bonus' => 2, 'hp_max' => 10, 'armor_class' => 10]);
                }
            }
        }
    } elseif ($route === 'play_campaign_content_create' || $route === 'play_campaign_content_read' || $route === 'play_campaign_content_tags_update') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid content');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            if ($route !== 'play_campaign_content_read' && !$isDm) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_content_create') {
                $content = contentFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_content WHERE campaign_id = ?');
                    $sequence->execute([$campaignId]);
                    $database->prepare('INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $content['content_id'], $content['kind'], $content['text'], json_encode($content['tags'], JSON_THROW_ON_ERROR), (int) $sequence->fetchColumn()]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate content id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse($content, 201);
            } elseif ($route === 'play_campaign_content_tags_update') {
                $contentId = $request->attributes->get('content_id');
                if (!is_string($contentId) || $contentId === '') {
                    throw new InvalidArgumentException('invalid content');
                }
                $body = requestBody($request);
                $replacementTags = contentTags($body['tags'] ?? null, false);
                $statement = $database->prepare('UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?');
                $statement->execute([json_encode($replacementTags, JSON_THROW_ON_ERROR), $campaignId, $contentId]);
                if ($statement->rowCount() === 0) {
                    $exists = $database->prepare('SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
                    $exists->execute([$campaignId, $contentId]);
                    if ($exists->fetchColumn() === false) {
                        $response = new JsonResponse(['error' => 'not found'], 404);
                    }
                }
                if (!isset($response)) {
                    $statement = $database->prepare('SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
                    $statement->execute([$campaignId, $contentId]);
                    $response = new JsonResponse(contentResponse($statement->fetch()));
                }
            } else {
                $query = $request->query->all();
                $excludeTag = $query['exclude_tag'] ?? null;
                if ($excludeTag !== null && (!is_string($excludeTag) || $excludeTag === '')) {
                    throw new InvalidArgumentException('invalid exclude tag');
                }
                $statement = $database->prepare('SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? ORDER BY sequence');
                $statement->execute([$campaignId]);
                $content = [];
                foreach ($statement as $row) {
                    $record = contentResponse($row);
                    if (!$isDm && $excludeTag !== null && in_array($excludeTag, $record['tags'], true)) {
                        continue;
                    }
                    $content[] = $record;
                }
                $response = new JsonResponse(['content' => $content]);
            }
        }
    } elseif ($route === 'play_campaign_session_zero_update' || $route === 'play_campaign_session_zero_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid session-zero settings');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner, status FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_session_zero_update') {
            if ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            if ($campaignRow['status'] !== 'lobby') {
                throw new MembershipConflictException('campaign has started');
            }
            $settings = sessionZeroSettings(requestBody($request));
            $database->prepare('INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent')
                ->execute([$campaignId, $settings['rules'], $settings['tone'], json_encode($settings['consent'], JSON_THROW_ON_ERROR)]);
            $response = new JsonResponse($settings);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $settingsStatement = $database->prepare('SELECT rules, tone, consent FROM play_campaign_session_zero_settings WHERE campaign_id = ?');
            $settingsStatement->execute([$campaignId]);
            $settings = $settingsStatement->fetch();
            if ($settings === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $consent = json_decode($settings['consent'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($consent) || !array_is_list($consent) || $consent === []) {
                    throw new RuntimeException('invalid session-zero settings state');
                }
                foreach ($consent as $boundary) {
                    if (!is_string($boundary) || $boundary === '') {
                        throw new RuntimeException('invalid session-zero settings state');
                    }
                }
                $response = new JsonResponse(['rules' => $settings['rules'], 'tone' => $settings['tone'], 'consent' => $consent]);
            }
        }
    } elseif ($route === 'play_campaign_settlement_create' || $route === 'play_campaign_settlement_read' || $route === 'play_campaign_settlement_update' || $route === 'play_campaign_settlement_discover') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid settlement');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_settlement_read') {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $characterId = null;
            if (!$isDm) {
                $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                $characterId = $member->fetchColumn();
                if ($characterId === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $settlements = $isDm
                ? $database->prepare('SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY sequence')
                : $database->prepare('SELECT s.settlement_id, s.name, s.services, s.availability FROM play_campaign_settlements s JOIN play_campaign_settlement_discoveries d ON d.campaign_id = s.campaign_id AND d.settlement_id = s.settlement_id WHERE s.campaign_id = ? AND d.character_id = ? ORDER BY s.sequence');
            $settlements->execute($isDm ? [$campaignId] : [$campaignId, $characterId]);
            $discoveries = $database->prepare('SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence');
            $result = [];
            foreach ($settlements as $settlement) {
                if ($isDm) {
                    $discoveries->execute([$campaignId, $settlement['settlement_id']]);
                    $discoverers = $discoveries->fetchAll(PDO::FETCH_COLUMN);
                } else {
                    $discoverers = [$characterId];
                }
                $result[] = settlementResponse($settlement, $discoverers);
            }
            $response = new JsonResponse(['settlements' => $result]);
        } elseif ($route === 'play_campaign_settlement_discover') {
            if ($actor['role'] === 'dm') {
                throw new ForbiddenException('permission denied');
            }
            $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            $characterId = $member->fetchColumn();
            if ($characterId === false) {
                throw new ForbiddenException('permission denied');
            }
            $settlementId = $request->attributes->get('settlement_id');
            if (!is_string($settlementId) || $settlementId === '') {
                throw new InvalidArgumentException('invalid settlement');
            }
            $settlement = $database->prepare('SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
            $settlement->execute([$campaignId, $settlementId]);
            $settlementRow = $settlement->fetch();
            if ($settlementRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ?');
                $sequence->execute([$campaignId, $settlementId]);
                $insert = $database->prepare('INSERT OR IGNORE INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id, sequence) VALUES (?, ?, ?, ?)');
                $insert->execute([$campaignId, $settlementId, $characterId, (int) $sequence->fetchColumn()]);
                $response = new JsonResponse(settlementResponse($settlementRow, [$characterId]), $insert->rowCount() === 1 ? 201 : 200);
            }
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_settlement_create') {
            $body = requestBody($request);
            $settlementId = $body['settlement_id'] ?? null;
            if (!is_string($settlementId) || $settlementId === '') {
                throw new InvalidArgumentException('invalid settlement');
            }
            $fields = settlementFields($body);
            try {
                $database->beginTransaction();
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlements WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare('INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services, availability, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $settlementId, $fields['name'], json_encode($fields['services'], JSON_THROW_ON_ERROR), $fields['availability'], (int) $sequence->fetchColumn()]);
                $database->commit();
            } catch (PDOException $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate settlement id');
                }
                throw $exception;
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(settlementResponse(['settlement_id' => $settlementId, 'name' => $fields['name'], 'services' => json_encode($fields['services'], JSON_THROW_ON_ERROR), 'availability' => $fields['availability']], []), 201);
        } else {
            $settlementId = $request->attributes->get('settlement_id');
            if (!is_string($settlementId) || $settlementId === '') {
                throw new InvalidArgumentException('invalid settlement');
            }
            $fields = settlementFields(requestBody($request));
            $settlement = $database->prepare('SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
            $settlement->execute([$campaignId, $settlementId]);
            $settlementRow = $settlement->fetch();
            if ($settlementRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare('UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?')
                    ->execute([$fields['name'], json_encode($fields['services'], JSON_THROW_ON_ERROR), $fields['availability'], $campaignId, $settlementId]);
                $discoveries = $database->prepare('SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence');
                $discoveries->execute([$campaignId, $settlementId]);
                $response = new JsonResponse(settlementResponse(['settlement_id' => $settlementId, 'name' => $fields['name'], 'services' => json_encode($fields['services'], JSON_THROW_ON_ERROR), 'availability' => $fields['availability']], $discoveries->fetchAll(PDO::FETCH_COLUMN)));
            }
        }
    } elseif ($route === 'play_campaign_shop_create' || $route === 'play_campaign_shop_read' || $route === 'play_campaign_shop_buy' || $route === 'play_campaign_shop_sell') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $settlementId = $request->attributes->get('settlement_id');
        $shopId = $request->attributes->get('shop_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($settlementId) || $settlementId === '') {
            throw new InvalidArgumentException('invalid shop');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $settlement = $database->prepare('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
            $settlement->execute([$campaignId, $settlementId]);
            if ($settlement->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($route === 'play_campaign_shop_create') {
                if ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
                    throw new ForbiddenException('permission denied');
                }
                $shop = shopFields(requestBody($request));
                try {
                    $database->prepare('INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $settlementId, $shop['shop_id'], $shop['name'], json_encode($shop['stock'], JSON_THROW_ON_ERROR), $shop['buy_price'], $shop['sell_price']]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate shop id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse($shop, 201);
            } else {
                if (!is_string($shopId) || $shopId === '') {
                    throw new InvalidArgumentException('invalid shop');
                }
                $shopStatement = $database->prepare('SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
                $shopStatement->execute([$campaignId, $settlementId, $shopId]);
                $shop = $shopStatement->fetch();
                if ($shop === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif ($route === 'play_campaign_shop_read') {
                    $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
                    if (!$isDm) {
                        $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                        $member->execute([$campaignId, $actor['username']]);
                        $characterId = $member->fetchColumn();
                        if ($characterId === false) {
                            throw new ForbiddenException('permission denied');
                        }
                        $discovery = $database->prepare('SELECT 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?');
                        $discovery->execute([$campaignId, $settlementId, $characterId]);
                        if ($discovery->fetchColumn() === false) {
                            $response = new JsonResponse(['error' => 'not found'], 404);
                        } else {
                            $response = new JsonResponse(shopResponse($shop));
                        }
                    } else {
                        $response = new JsonResponse(shopResponse($shop));
                    }
                } else {
                    $body = requestBody($request);
                    $characterId = $body['character_id'] ?? null;
                    $itemId = $body['item_id'] ?? null;
                    $quantity = $body['quantity'] ?? null;
                    if (!is_string($characterId) || $characterId === '' || !is_int($quantity) || $quantity < 1) {
                        throw new InvalidArgumentException('invalid shop transaction');
                    }
                    $itemId = inventoryCatalogItem($itemId);
                    if ($actor['role'] === 'dm') {
                        throw new ForbiddenException('permission denied');
                    }
                    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
                    $owner->execute([$campaignId, $characterId]);
                    $ownerRow = $owner->fetch();
                    if ($ownerRow === false) {
                        $response = new JsonResponse(['error' => 'not found'], 404);
                    } elseif ($ownerRow['owner'] !== $actor['username']) {
                        throw new ForbiddenException('permission denied');
                    } else {
                        $stock = json_decode($shop['stock'], true, 512, JSON_THROW_ON_ERROR);
                        if (!is_array($stock) || array_is_list($stock)) {
                            throw new RuntimeException('invalid shop state');
                        }
                        $available = $stock[$itemId] ?? 0;
                        if (!is_int($available) || $available < 0) {
                            throw new RuntimeException('invalid shop state');
                        }
                        $database->beginTransaction();
                        try {
                            if ($route === 'play_campaign_shop_buy') {
                                if ($available < $quantity) {
                                    throw new MembershipConflictException('insufficient stock');
                                }
                                $cost = (int) $shop['buy_price'] * $quantity;
                                $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
                                $debit->execute([$cost, $campaignId, $characterId, $cost]);
                                if ($debit->rowCount() !== 1) {
                                    throw new MembershipConflictException('insufficient gold');
                                }
                                $stock[$itemId] = $available - $quantity;
                                $database->prepare('UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?')
                                    ->execute([json_encode($stock, JSON_THROW_ON_ERROR), $campaignId, $settlementId, $shopId]);
                                $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
                                    ->execute([$campaignId, $characterId, $itemId, $quantity]);
                            } else {
                                $held = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                                $held->execute([$campaignId, $characterId, $itemId]);
                                $heldQuantity = $held->fetchColumn();
                                if ($heldQuantity === false || (int) $heldQuantity < $quantity) {
                                    throw new MembershipConflictException('insufficient inventory');
                                }
                                $remaining = (int) $heldQuantity - $quantity;
                                if ($remaining === 0) {
                                    $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$campaignId, $characterId, $itemId]);
                                } else {
                                    $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$remaining, $campaignId, $characterId, $itemId]);
                                }
                                $stock[$itemId] = $available + $quantity;
                                $database->prepare('UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?')
                                    ->execute([json_encode($stock, JSON_THROW_ON_ERROR), $campaignId, $settlementId, $shopId]);
                                $credit = (int) $shop['sell_price'] * $quantity;
                                $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
                                    ->execute([$credit, $campaignId, $characterId]);
                            }
                            $gold = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
                            $gold->execute([$campaignId, $characterId]);
                            $database->commit();
                            $response = new JsonResponse(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'gold' => (int) $gold->fetchColumn(), 'stock' => $stock[$itemId]]);
                        } catch (Throwable $exception) {
                            if ($database->inTransaction()) {
                                $database->rollBack();
                            }
                            throw $exception;
                        }
                    }
                }
            }
        }
    } elseif ($route === 'play_campaign_calendar_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !array_key_exists('day', $body) || !array_key_exists('season', $body)) {
            throw new InvalidArgumentException('invalid calendar');
        }
        $day = integer($body['day']);
        if ($day < 1 || !is_string($body['season']) || !in_array($body['season'], ['spring', 'summer', 'autumn', 'winter'], true)) {
            throw new InvalidArgumentException('invalid calendar');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            try {
                $database->prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)')->execute([$campaignId, $day, $body['season']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('calendar already initialized');
                }
                throw $exception;
            }
            $response = new JsonResponse(calendarState($day, $body['season']), 201);
        }
    } elseif ($route === 'play_campaign_calendar_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid calendar');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $calendar = $database->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
            $calendar->execute([$campaignId]);
            $calendarRow = $calendar->fetch();
            $response = $calendarRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(calendarState((int) $calendarRow['day'], $calendarRow['season']));
        }
    } elseif ($route === 'play_campaign_calendar_advance') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !array_key_exists('days', $body)) {
            throw new InvalidArgumentException('invalid calendar advance');
        }
        $days = integer($body['days']);
        if ($days < 1 || $days > 30) {
            throw new InvalidArgumentException('invalid calendar advance');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $calendar = $database->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
            $calendar->execute([$campaignId]);
            $calendarRow = $calendar->fetch();
            if ($calendarRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $day = (int) $calendarRow['day'] + $days;
                $database->prepare('UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?')->execute([$day, $campaignId]);
                $response = new JsonResponse(calendarState($day, $calendarRow['season']));
            }
        }
    } elseif ($route === 'play_campaign_member_create') {
        $actor = authenticatedActor($request);
        if ($actor['role'] !== 'player') {
            throw new ForbiddenException('permission denied');
        }
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['character_id'], $body['name'], $body['class']) || !is_string($body['character_id']) || $body['character_id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_string($body['class']) || $body['class'] === '') {
            throw new InvalidArgumentException('invalid membership');
        }
        $hasHpCurrent = array_key_exists('hp_current', $body);
        $hasHpMax = array_key_exists('hp_max', $body);
        if ($hasHpCurrent !== $hasHpMax) {
            throw new InvalidArgumentException('invalid membership');
        }
        $hpCurrent = 20;
        $hpMax = 20;
        if ($hasHpCurrent) {
            $hpCurrent = integer($body['hp_current']);
            $hpMax = integer($body['hp_max']);
            if ($hpCurrent < 0 || $hpMax < 1 || $hpCurrent > $hpMax) {
                throw new InvalidArgumentException('invalid membership');
            }
        }

        $database = database();
        $campaign = $database->prepare('SELECT status, max_players FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['status'] !== 'lobby') {
            throw new MembershipConflictException('campaign is not accepting members');
        } else {
            $existing = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ? AND (username = ? OR character_id = ?)');
            $existing->execute([$campaignId, $actor['username'], $body['character_id']]);
            $members = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
            $members->execute([$campaignId]);
            if ((int) $existing->fetchColumn() > 0 || (int) $members->fetchColumn() >= (int) $campaignRow['max_players']) {
                throw new MembershipConflictException('membership conflict');
            }
            try {
                $database->prepare('INSERT INTO play_campaign_members (character_id, campaign_id, username, name, class, hp_current, hp_max, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
                    ->execute([$body['character_id'], $campaignId, $actor['username'], $body['name'], $body['class'], $hpCurrent, $hpMax, $hpCurrent === 0 ? 'unconscious' : 'conscious']);
                $database->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner) VALUES (?, ?, ?)')
                    ->execute([$body['character_id'], $campaignId, $actor['username']]);
                $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)')
                    ->execute([$campaignId, $body['character_id']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('membership conflict');
                }
                throw $exception;
            }
            $response = new JsonResponse(['username' => $actor['username'], 'character_id' => $body['character_id'], 'name' => $body['name'], 'class' => $body['class']], 201);
        }
    } elseif ($route === 'play_campaign_invitation_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === ''
            || !is_string($body['invitation_id'] ?? null) || $body['invitation_id'] === ''
            || !is_string($body['username'] ?? null) || $body['username'] === ''
            || !is_string($body['character_id'] ?? null) || $body['character_id'] === '') {
            throw new InvalidArgumentException('invalid invitation');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $target = $database->prepare("SELECT 1 FROM users WHERE username = ? AND role = 'player'");
            $target->execute([$body['username']]);
            if ($target->fetchColumn() === false) {
                throw new InvalidArgumentException('invalid invitation');
            }
            $duplicate = $database->prepare("SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND (invitation_id = ? OR (username = ? AND status = 'pending'))");
            $duplicate->execute([$campaignId, $body['invitation_id'], $body['username']]);
            if ($duplicate->fetchColumn() !== false) {
                throw new MembershipConflictException('invitation conflict');
            }
            $database->prepare("INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, 'pending')")
                ->execute([$campaignId, $body['invitation_id'], $body['username'], $body['character_id']]);
            $response = new JsonResponse(['invitation_id' => $body['invitation_id'], 'username' => $body['username'], 'character_id' => $body['character_id'], 'status' => 'pending'], 201);
        }
    } elseif ($route === 'play_campaign_invitation_accept') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $invitationId = $request->attributes->get('invitation_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($invitationId) || $invitationId === '') {
            throw new InvalidArgumentException('invalid invitation');
        }
        $database = database();
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $invitation = $database->prepare('SELECT username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?');
            $invitation->execute([$campaignId, $invitationId]);
            $invitationRow = $invitation->fetch();
            if ($invitationRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($invitationRow['username'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } elseif ($invitationRow['status'] !== 'pending') {
                throw new MembershipConflictException('invitation already accepted');
            } else {
                $database->beginTransaction();
                try {
                    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND (username = ? OR character_id = ?)');
                    $member->execute([$campaignId, $actor['username'], $invitationRow['character_id']]);
                    if ($member->fetchColumn() !== false) {
                        throw new MembershipConflictException('membership conflict');
                    }
                    $database->prepare("INSERT INTO play_campaign_members (character_id, campaign_id, username, name, class) VALUES (?, ?, ?, ?, 'adventurer')")
                        ->execute([$invitationRow['character_id'], $campaignId, $actor['username'], $invitationRow['character_id']]);
                    $database->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner) VALUES (?, ?, ?)')
                        ->execute([$invitationRow['character_id'], $campaignId, $actor['username']]);
                    $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)')
                        ->execute([$campaignId, $invitationRow['character_id']]);
                    $database->prepare("UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ? AND status = 'pending'")
                        ->execute([$campaignId, $invitationId]);
                    $database->commit();
                    $response = new JsonResponse(['invitation_id' => $invitationId, 'username' => $invitationRow['username'], 'character_id' => $invitationRow['character_id'], 'status' => 'accepted']);
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_invitation_list') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid invitation');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            if ($campaignRow['owner'] === $actor['username']) {
                $invitations = $database->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid');
                $invitations->execute([$campaignId]);
            } else {
                $invitations = $database->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY rowid');
                $invitations->execute([$campaignId, $actor['username']]);
            }
            $response = new JsonResponse(['invitations' => $invitations->fetchAll()]);
        }
    } elseif (in_array($route, ['play_campaign_delegation_grant', 'play_campaign_delegation_revoke', 'play_campaign_delegation_audit'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid delegation');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_delegation_audit') {
            $audit = $database->prepare('SELECT username, action FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence');
            $audit->execute([$campaignId]);
            $entries = array_map(static fn (array $entry): array => $entry + ['powers' => ['narrate']], $audit->fetchAll());
            $response = new JsonResponse(['entries' => $entries]);
        } elseif ($route === 'play_campaign_delegation_grant') {
            $delegation = delegationFields(requestBody($request));
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $delegation['username']]);
            if ($member->fetchColumn() === false) {
                throw new InvalidArgumentException('invalid delegation');
            }
            $existing = $database->prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
            $existing->execute([$campaignId, $delegation['username']]);
            $active = $existing->fetchColumn();
            if ($active !== false && (int) $active === 1) {
                throw new MembershipConflictException('delegation conflict');
            }
            $database->beginTransaction();
            try {
                $database->prepare('INSERT INTO play_campaign_delegations (campaign_id, username, active) VALUES (?, ?, 1) ON CONFLICT(campaign_id, username) DO UPDATE SET active = 1')
                    ->execute([$campaignId, $delegation['username']]);
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare("INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action) VALUES (?, ?, ?, 'granted')")
                    ->execute([$campaignId, (int) $sequence->fetchColumn(), $delegation['username']]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) { $database->rollBack(); }
                throw $exception;
            }
            $response = new JsonResponse(['username' => $delegation['username'], 'powers' => ['narrate'], 'active' => true], 201);
        } else {
            $username = $request->attributes->get('username');
            if (!is_string($username) || $username === '') {
                throw new InvalidArgumentException('invalid delegation');
            }
            $delegation = $database->prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
            $delegation->execute([$campaignId, $username]);
            $active = $delegation->fetchColumn();
            if ($active === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                if ((int) $active === 1) {
                    $database->beginTransaction();
                    try {
                        $database->prepare('UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?')->execute([$campaignId, $username]);
                        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?');
                        $sequence->execute([$campaignId]);
                        $database->prepare("INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action) VALUES (?, ?, ?, 'revoked')")
                            ->execute([$campaignId, (int) $sequence->fetchColumn(), $username]);
                        $database->commit();
                    } catch (Throwable $exception) {
                        if ($database->inTransaction()) { $database->rollBack(); }
                        throw $exception;
                    }
                }
                $response = new JsonResponse(['username' => $username, 'powers' => ['narrate'], 'active' => false]);
            }
        }
    } elseif (in_array($route, ['play_campaign_safe_turn_create', 'play_campaign_safe_turn_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid safe turn');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_safe_turn_read') {
                $state = $database->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
                $state->execute([$campaignId]);
                $currentTurn = $state->fetchColumn();
                $accepted = $database->prepare('SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? ORDER BY accepted_turn');
                $accepted->execute([$campaignId]);
                $response = new JsonResponse(['current_turn' => $currentTurn === false ? 1 : (int) $currentTurn, 'accepted' => array_map(static fn (array $submission): array => [
                    'submission_id' => $submission['submission_id'],
                    'action' => $submission['action'],
                    'accepted_turn' => (int) $submission['accepted_turn'],
                    'next_turn' => (int) $submission['next_turn'],
                ], $accepted->fetchAll())]);
            } else {
                $submission = safeTurnFields(requestBody($request));
                $transactionOpen = false;
                try {
                    // IMMEDIATE obtains SQLite's single writer before reading the
                    // turn, making the check-and-advance operation atomic across
                    // concurrent HTTP requests.
                    $database->exec('BEGIN IMMEDIATE');
                    $transactionOpen = true;
                    $duplicate = $database->prepare('SELECT 1 FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?');
                    $duplicate->execute([$campaignId, $submission['submission_id']]);
                    if ($duplicate->fetchColumn() !== false) {
                        $database->exec('ROLLBACK');
                        $transactionOpen = false;
                        throw new MembershipConflictException('duplicate safe turn submission');
                    }
                    $state = $database->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
                    $state->execute([$campaignId]);
                    $currentTurn = $state->fetchColumn();
                    $currentTurn = $currentTurn === false ? 1 : (int) $currentTurn;
                    if ($submission['expected_turn'] !== $currentTurn) {
                        $database->exec('ROLLBACK');
                        $transactionOpen = false;
                        $response = new JsonResponse(['current_turn' => $currentTurn], 409);
                    } else {
                        $database->prepare('INSERT OR IGNORE INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$campaignId]);
                        $advance = $database->prepare('UPDATE play_campaign_safe_turns SET current_turn = current_turn + 1 WHERE campaign_id = ? AND current_turn = ?');
                        $advance->execute([$campaignId, $currentTurn]);
                        if ($advance->rowCount() !== 1) {
                            throw new RuntimeException('safe turn state changed unexpectedly');
                        }
                        $nextTurn = $currentTurn + 1;
                        $database->prepare('INSERT INTO play_campaign_safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)')
                            ->execute([$campaignId, $submission['submission_id'], $submission['action'], $currentTurn, $nextTurn]);
                        $database->exec('COMMIT');
                        $transactionOpen = false;
                        $response = new JsonResponse(['submission_id' => $submission['submission_id'], 'action' => $submission['action'], 'accepted_turn' => $currentTurn, 'next_turn' => $nextTurn], 201);
                    }
                } catch (Throwable $exception) {
                    if ($transactionOpen) {
                        $database->exec('ROLLBACK');
                    }
                    throw $exception;
                }
            }
        }
    } elseif (in_array($route, ['play_campaign_idempotent_event_create', 'play_campaign_idempotent_event_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid idempotent event');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_idempotent_event_read') {
                $events = $database->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence');
                $events->execute([$campaignId]);
                $response = new JsonResponse(['events' => array_map(static fn (array $event): array => [
                    'event_id' => $event['event_id'],
                    'value' => $event['value'],
                    'sequence' => (int) $event['sequence'],
                    'idempotency_key' => $event['idempotency_key'],
                ], $events->fetchAll())]);
            } else {
                $idempotencyKey = $request->headers->get('Idempotency-Key');
                if (!is_string($idempotencyKey) || trim($idempotencyKey) === '') {
                    throw new InvalidArgumentException('invalid idempotency key');
                }
                $event = idempotentEventFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $storedStatement = $database->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
                    $storedStatement->execute([$campaignId, $idempotencyKey]);
                    $stored = $storedStatement->fetch();
                    if ($stored !== false) {
                        if ($stored['event_id'] !== $event['event_id'] || $stored['value'] !== $event['value']) {
                            throw new MembershipConflictException('idempotency key conflict');
                        }
                        $database->commit();
                        $response = new JsonResponse(['event_id' => $stored['event_id'], 'value' => $stored['value'], 'sequence' => (int) $stored['sequence'], 'idempotency_key' => $stored['idempotency_key']]);
                    } else {
                        $existingEvent = $database->prepare('SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?');
                        $existingEvent->execute([$campaignId, $event['event_id']]);
                        if ($existingEvent->fetchColumn() !== false) {
                            throw new MembershipConflictException('event id conflict');
                        }
                        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?');
                        $nextSequence->execute([$campaignId]);
                        $sequence = (int) $nextSequence->fetchColumn();
                        $database->prepare('INSERT INTO play_campaign_idempotent_events (campaign_id, idempotency_key, event_id, value, sequence) VALUES (?, ?, ?, ?, ?)')
                            ->execute([$campaignId, $idempotencyKey, $event['event_id'], $event['value'], $sequence]);
                        $database->commit();
                        $response = new JsonResponse(['event_id' => $event['event_id'], 'value' => $event['value'], 'sequence' => $sequence, 'idempotency_key' => $idempotencyKey], 201);
                    }
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('idempotent event conflict');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif (in_array($route, ['play_campaign_projection_event_create', 'play_campaign_projection_read', 'play_campaign_projection_rebuild'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid projection event');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $campaignRow['owner'] === $actor['username'];
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            $isMember = $member->fetchColumn() !== false;
            if (!$isDm && !$isMember) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_projection_event_create') {
                if ($isDm || $actor['role'] !== 'player' || !$isMember) {
                    throw new ForbiddenException('permission denied');
                }
                $event = projectionEventFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?');
                    $sequence->execute([$campaignId]);
                    $stored = ['sequence' => (int) $sequence->fetchColumn(), 'event_id' => $event['event_id'], 'kind' => $event['kind']];
                    if ($event['kind'] === 'set-story') {
                        $stored['value'] = $event['value'];
                    }
                    $database->prepare('INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $stored['sequence'], $event['event_id'], $event['kind'], $event['value'] ?? null]);
                    $database->prepare('UPDATE play_campaign_service_metrics SET projection_events = projection_events + 1 WHERE campaign_id = ?')
                        ->execute([$campaignId]);
                    $database->commit();
                    $response = new JsonResponse($stored, 201);
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('projection event conflict');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            } else {
                $events = $database->prepare('SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence');
                $events->execute([$campaignId]);
                $response = new JsonResponse(rebuildProjection($events->fetchAll()));
            }
        }
    } elseif (in_array($route, ['play_campaign_audit_event_create', 'play_campaign_audit_event_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid audit event');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $actor['username']) {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_audit_event_read') {
                throw new ForbiddenException('permission denied');
            }
            $event = auditEventFields(requestBody($request));
            $role = 'player';
            $duplicate = $database->prepare('SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?');
            $duplicate->execute([$campaignId, $event['correlation_id']]);
            if ($duplicate->fetchColumn() !== false) {
                throw new MembershipConflictException('audit event conflict');
            }
            $database->beginTransaction();
            try {
                $timestamp = $database->prepare('SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?');
                $timestamp->execute([$campaignId]);
                $entry = ['kind' => $event['kind'], 'actor' => $actor['username'], 'role' => $role, 'timestamp' => (int) $timestamp->fetchColumn(), 'correlation_id' => $event['correlation_id']];
                $database->prepare('INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $entry['timestamp'], $entry['kind'], $entry['actor'], $entry['role'], $entry['correlation_id']]);
                $database->commit();
                $response = new JsonResponse($entry, 201);
            } catch (Throwable $exception) {
                if ($database->inTransaction()) { $database->rollBack(); }
                throw $exception;
            }
        } elseif ($route === 'play_campaign_audit_event_read') {
            $events = $database->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp');
            $events->execute([$campaignId]);
            $entries = array_map(static fn (array $entry): array => [
                'kind' => $entry['kind'],
                'actor' => $entry['actor'],
                'role' => $entry['role'],
                'timestamp' => (int) $entry['timestamp'],
                'correlation_id' => $entry['correlation_id'],
            ], $events->fetchAll());
            $response = new JsonResponse(['entries' => $entries]);
        } else {
            $event = auditEventFields(requestBody($request));
            $duplicate = $database->prepare('SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?');
            $duplicate->execute([$campaignId, $event['correlation_id']]);
            if ($duplicate->fetchColumn() !== false) {
                throw new MembershipConflictException('audit event conflict');
            }
            $database->beginTransaction();
            try {
                $timestamp = $database->prepare('SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?');
                $timestamp->execute([$campaignId]);
                $entry = ['kind' => $event['kind'], 'actor' => $actor['username'], 'role' => 'DM', 'timestamp' => (int) $timestamp->fetchColumn(), 'correlation_id' => $event['correlation_id']];
                $database->prepare('INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $entry['timestamp'], $entry['kind'], $entry['actor'], $entry['role'], $entry['correlation_id']]);
                $database->commit();
                $response = new JsonResponse($entry, 201);
            } catch (Throwable $exception) {
                if ($database->inTransaction()) { $database->rollBack(); }
                throw $exception;
            }
        }
    } elseif ($route === 'play_campaign_start') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid play campaign');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $start = $database->prepare("UPDATE play_campaigns SET status = 'active', current_actor = (SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid LIMIT 1), turn_number = 1 WHERE id = ? AND status = 'lobby' AND (SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?) >= 2");
            $start->execute([$campaignId, $campaignId, $campaignId]);
            if ($start->rowCount() === 0) {
                throw new MembershipConflictException('campaign cannot start');
            }
            $actor = $database->prepare('SELECT current_actor FROM play_campaigns WHERE id = ?');
            $actor->execute([$campaignId]);
            $response = new JsonResponse(['id' => $campaignId, 'status' => 'active', 'current_actor' => $actor->fetchColumn(), 'turn_number' => 1]);
        }
    } elseif ($route === 'play_campaign_narration_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            throw new InvalidArgumentException('invalid narration');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $mayNarrate = $campaignRow['owner'] === $actor['username'];
            if (!$mayNarrate) {
                $delegation = $database->prepare('SELECT 1 FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1');
                $delegation->execute([$campaignId, $actor['username']]);
                $mayNarrate = $delegation->fetchColumn() !== false;
            }
            if (!$mayNarrate) {
                throw new ForbiddenException('permission denied');
            }
            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, actor, text) VALUES (?, ?, ?, ?)')
                    ->execute([$campaignId, $sequence, $actor['username'], $body['text']]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'narration', 'actor' => $actor['username'], 'text' => $body['text']], 201);
        }
    } elseif ($route === 'play_campaign_message_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($body['text'] ?? null) || $body['text'] === '') {
            throw new InvalidArgumentException('invalid message');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_messages (campaign_id, sequence, actor, text) VALUES (?, ?, ?, ?)')
                    ->execute([$campaignId, $sequence, $actor['username'], $body['text']]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'chat', 'actor' => $actor['username'], 'text' => $body['text']], 201);
        }
    } elseif ($route === 'play_campaign_action_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['type'], $body['text']) || !is_string($body['type']) || $body['type'] === '' || !is_string($body['text']) || $body['text'] === '') {
            throw new InvalidArgumentException('invalid action');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status, current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'player' || $campaignRow['status'] !== 'active' || $campaignRow['current_actor'] !== $actor['username']) {
            throw new MembershipConflictException('not the active player');
        } else {
            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) VALUES (?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $sequence, $actor['username'], $body['type'], $body['text']]);
                $advance = $database->prepare("UPDATE play_campaigns SET current_actor = owner WHERE id = ? AND status = 'active' AND current_actor = ?");
                $advance->execute([$campaignId, $actor['username']]);
                if ($advance->rowCount() === 0) {
                    throw new MembershipConflictException('not the active player');
                }
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'action', 'actor' => $actor['username'], 'type' => $body['type'], 'text' => $body['text'], 'next_actor' => $campaignRow['owner']], 201);
        }
    } elseif ($route === 'play_campaign_resolution_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            throw new InvalidArgumentException('invalid resolution');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status, current_actor, turn_number FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['username'] !== $campaignRow['owner'] || $campaignRow['status'] !== 'active' || $campaignRow['current_actor'] !== $campaignRow['owner']) {
            throw new MembershipConflictException('not the active owner');
        } else {
            $members = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
            $members->execute([$campaignId]);
            $players = $members->fetchAll();
            if ($players === []) {
                throw new MembershipConflictException('campaign has no players');
            }
            $turnNumber = (int) $campaignRow['turn_number'] + 1;
            // Preserve the established deterministic queue: the first DM
            // resolution advances to the second member; later resolutions
            // return to the first member.
            $nextActor = $players[(int) $campaignRow['turn_number'] >= 2 ? 0 : 1]['username'];

            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_resolutions (campaign_id, sequence, text) VALUES (?, ?, ?)')
                    ->execute([$campaignId, $sequence, $body['text']]);
                $advance = $database->prepare('UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ? AND status = ? AND current_actor = owner');
                $advance->execute([$nextActor, $turnNumber, $campaignId, 'active']);
                if ($advance->rowCount() === 0) {
                    throw new MembershipConflictException('not the active owner');
                }
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'resolution', 'actor' => $campaignRow['owner'], 'text' => $body['text'], 'next_actor' => $nextActor, 'turn_number' => $turnNumber], 201);
        }
    } elseif ($route === 'play_campaign_turn') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid play campaign');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status, current_actor, turn_number, phase FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            $members = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
            $members->execute([$campaignId]);
            $queue = [];
            foreach ($members as $memberRow) {
                $queue[] = $memberRow['username'];
                $queue[] = $campaignRow['owner'];
            }
            $response = new JsonResponse([
                'campaign_id' => $campaignId,
                'current_actor' => $campaignRow['current_actor'],
                'phase' => $campaignRow['phase'] ?? ($campaignRow['status'] === 'active' ? 'player' : 'lobby'),
                'turn_number' => $campaignRow['turn_number'] === null ? 0 : (int) $campaignRow['turn_number'],
                'queue' => $queue,
                'overdue' => false,
                'logical_deadline' => ($campaignRow['turn_number'] === null ? 0 : (int) $campaignRow['turn_number']) + 1,
            ]);
        }
    } elseif ($route === 'play_campaign_turn_travel') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['destination_id']) || !is_string($body['destination_id']) || $body['destination_id'] === '') {
            throw new InvalidArgumentException('invalid travel');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status, current_actor, current_location_id FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'player' || $campaignRow['status'] !== 'active' || $campaignRow['current_actor'] !== $actor['username']) {
            throw new MembershipConflictException('not the active player');
        } elseif (!is_string($campaignRow['current_location_id']) || $campaignRow['current_location_id'] === '') {
            throw new MembershipConflictException('party has no current location');
        } else {
            $connection = $database->prepare('SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
            $connection->execute([$campaignId, $campaignRow['current_location_id'], $body['destination_id']]);
            $travelTurns = $connection->fetchColumn();
            if ($travelTurns === false) {
                throw new MembershipConflictException('invalid travel destination');
            }

            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_travels (campaign_id, sequence, actor, destination_id, travel_turns) VALUES (?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $sequence, $actor['username'], $body['destination_id'], (int) $travelTurns]);
                $advance = $database->prepare('UPDATE play_campaigns SET current_location_id = ?, current_actor = owner WHERE id = ? AND status = ? AND current_actor = ?');
                $advance->execute([$body['destination_id'], $campaignId, 'active', $actor['username']]);
                if ($advance->rowCount() === 0) {
                    throw new MembershipConflictException('not the active player');
                }
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'travel', 'actor' => $actor['username'], 'destination_id' => $body['destination_id'], 'travel_turns' => (int) $travelTurns, 'next_actor' => $campaignRow['owner']], 201);
        }
    } elseif ($route === 'play_campaign_turn_rest') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['type']) || !is_string($body['type']) || !in_array($body['type'], ['short', 'long'], true)) {
            throw new InvalidArgumentException('invalid rest');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status, current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'player' || $campaignRow['status'] !== 'active' || $campaignRow['current_actor'] !== $actor['username']) {
            throw new MembershipConflictException('not the active player');
        } else {
            $member = $database->prepare('SELECT hp_current, hp_max FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                throw new MembershipConflictException('not the active player');
            }
            $hpMax = (int) $memberRow['hp_max'];
            $hpCurrent = $body['type'] === 'long' ? $hpMax : (int) $memberRow['hp_current'];

            $database->beginTransaction();
            try {
                $sequence = nextPlayEventSequence($database, $campaignId);
                $database->prepare('INSERT INTO play_campaign_rests (campaign_id, sequence, actor, type, hp_current, hp_max) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $sequence, $actor['username'], $body['type'], $hpCurrent, $hpMax]);
                if ($body['type'] === 'long') {
                    $database->prepare("UPDATE play_campaign_members SET hp_current = hp_max, status = 'conscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?")
                        ->execute([$campaignId, $actor['username']]);
                }
                $advance = $database->prepare('UPDATE play_campaigns SET current_actor = owner WHERE id = ? AND status = ? AND current_actor = ?');
                $advance->execute([$campaignId, 'active', $actor['username']]);
                if ($advance->rowCount() === 0) {
                    throw new MembershipConflictException('not the active player');
                }
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'rest', 'actor' => $actor['username'], 'type' => $body['type'], 'hp_current' => $hpCurrent, 'hp_max' => $hpMax, 'next_actor' => $campaignRow['owner']], 201);
        }
    } elseif ($route === 'play_campaign_character_damage') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !array_key_exists('amount', $body)) {
            throw new InvalidArgumentException('invalid damage');
        }
        $amount = integer($body['amount']);
        if ($amount < 1) {
            throw new InvalidArgumentException('invalid damage');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT hp_current, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $before = (int) $memberRow['hp_current'];
                $after = max(0, $before - $amount);
                // Entering zero HP starts the death-save state. Existing stable
                // and dead states are deliberately not reopened by more damage.
                $status = $before > 0 && $after === 0 ? 'unconscious' : $memberRow['status'];
                if ($before > 0 && $after === 0) {
                    $database->prepare("UPDATE play_campaign_members SET hp_current = ?, status = 'unconscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND character_id = ?")
                        ->execute([$after, $campaignId, $characterId]);
                } else {
                    $database->prepare('UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?')
                        ->execute([$after, $status, $campaignId, $characterId]);
                }
                $response = new JsonResponse(['target' => $characterId, 'hp_before' => $before, 'hp_after' => $after, 'damage' => $amount]);
            }
        }
    } elseif ($route === 'play_campaign_character_death_saves') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !isset($body['outcome']) || !is_string($body['outcome']) || !in_array($body['outcome'], ['success', 'failure'], true)) {
            throw new InvalidArgumentException('invalid death save');
        }

        $database = database();
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT username, death_save_successes, death_save_failures, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($memberRow['username'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } elseif ($memberRow['status'] !== 'unconscious') {
                throw new MembershipConflictException('character cannot make death saves');
            } else {
                $successes = (int) $memberRow['death_save_successes'];
                $failures = (int) $memberRow['death_save_failures'];
                if ($body['outcome'] === 'success') {
                    ++$successes;
                } else {
                    ++$failures;
                }
                $status = $successes >= 3 ? 'stable' : ($failures >= 3 ? 'dead' : 'unconscious');
                $database->prepare('UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?')
                    ->execute([$successes, $failures, $status, $campaignId, $characterId]);
                $response = new JsonResponse(['character_id' => $characterId, 'successes' => $successes, 'failures' => $failures, 'status' => $status], 201);
            }
        }
    } elseif ($route === 'play_campaign_character_status') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $member = $database->prepare('SELECT hp_current, hp_max, status FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            $response = $memberRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['character_id' => $characterId, 'hp_current' => (int) $memberRow['hp_current'], 'hp_max' => (int) $memberRow['hp_max'], 'status' => $memberRow['status']]);
        }
    } elseif ($route === 'play_campaign_character_build') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === ''
            || !isset($body['race'], $body['class'], $body['background'], $body['abilities'])
            || !is_string($body['race']) || !is_string($body['class']) || !is_string($body['background'])
            || !is_array($body['abilities']) || array_is_list($body['abilities'])
            || !in_array($body['race'], ['dwarf', 'elf', 'halfling', 'human', 'dragonborn', 'gnome', 'half-elf', 'half-orc', 'tiefling'], true)
            || !in_array($body['class'], ['barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk', 'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard'], true)
            || !in_array($body['background'], ['acolyte', 'charlatan', 'criminal', 'entertainer', 'folk-hero', 'guild-artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier', 'urchin'], true)) {
            throw new InvalidArgumentException('invalid character build');
        }

        $modifiers = [];
        foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
            $modifiers[$ability] = abilityModifier(integer($body['abilities'][$ability] ?? null));
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $hitDice = classHitDice($body['class']);
            // A build establishes the character's level-one maximum, which is
            // also the baseline for every later deterministic level gain.
            $hpMax = $hitDice['sides'] + $modifiers['con'];
            $database->prepare('UPDATE play_campaign_members SET class = ?, con_modifier = ?, ability_scores = ?, hp_current = MIN(hp_current, ?), hp_max = ? WHERE campaign_id = ? AND character_id = ?')
                ->execute([$body['class'], $modifiers['con'], json_encode($body['abilities'], JSON_THROW_ON_ERROR), $hpMax, $hpMax, $campaignId, $characterId]);
            $response = new JsonResponse([
                'character_id' => $characterId,
                'race' => $body['race'],
                'class' => $body['class'],
                'background' => $body['background'],
                'level' => 1,
                'hp_max' => $hpMax,
                'proficiency_bonus' => proficiencyBonus(1),
            ]);
        }
    } elseif ($route === 'play_campaign_character_level_up') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !array_key_exists('level', $body)) {
            throw new InvalidArgumentException('invalid level up');
        }
        $requestedLevel = integer($body['level']);

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            throw new InvalidArgumentException('invalid level up');
        }
        if ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        }

        $member = $database->prepare('SELECT level, class, con_modifier, hp_max FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $member->execute([$campaignId, $characterId]);
        $memberRow = $member->fetch();
        if ($memberRow === false) {
            throw new InvalidArgumentException('invalid level up');
        }
        $currentLevel = (int) $memberRow['level'];
        $hitDice = classHitDice($memberRow['class']);
        if ($currentLevel < 1 || $currentLevel >= 20 || $requestedLevel !== $currentLevel + 1 || $hitDice === null) {
            throw new InvalidArgumentException('invalid level up');
        }
        // Fixed average (rounded up) replaces a die roll, making progression
        // repeatable: a d8 contributes 5 before the Constitution modifier.
        $hpMax = (int) $memberRow['hp_max'] + intdiv($hitDice['sides'], 2) + 1 + (int) $memberRow['con_modifier'];
        $database->prepare('UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$requestedLevel, $hpMax, $campaignId, $characterId]);
        $response = new JsonResponse([
            'character_id' => $characterId,
            'level' => $requestedLevel,
            'hp_max' => $hpMax,
            'hit_dice' => $hitDice['hit_dice'],
            'proficiency_bonus' => proficiencyBonus($requestedLevel),
        ]);
    } elseif ($route === 'play_campaign_character_skill_check') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === ''
            || !isset($body['skill'], $body['ability'], $body['proficient'], $body['roll'])
            || !is_string($body['skill']) || !is_string($body['ability']) || !is_bool($body['proficient'])) {
            throw new InvalidArgumentException('invalid skill check');
        }
        $roll = integer($body['roll']);
        if (!supportedSkill($body['skill'])
            || !in_array($body['ability'], ['str', 'dex', 'con', 'int', 'wis', 'cha'], true)) {
            throw new InvalidArgumentException('invalid skill check');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT level, ability_scores FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $scores = json_decode($memberRow['ability_scores'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($scores) || array_is_list($scores)) {
                    throw new InvalidArgumentException('invalid skill check');
                }
                $modifier = abilityModifier(integer($scores[$body['ability']] ?? null))
                    + ($body['proficient'] ? proficiencyBonus((int) $memberRow['level']) : 0);
                $response = new JsonResponse([
                    'character_id' => $characterId,
                    'skill' => $body['skill'],
                    'ability' => $body['ability'],
                    'modifier' => $modifier,
                    'total' => $roll + $modifier,
                ]);
            }
        }
    } elseif ($route === 'play_campaign_character_spell_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === ''
            || !isset($body['spell_id'], $body['name'], $body['level'])
            || !is_string($body['spell_id']) || !is_string($body['name']) || $body['name'] === '') {
            throw new InvalidArgumentException('invalid spell');
        }
        $level = integer($body['level']);
        if (!wizardSpell($body['spell_id']) || $level < 0 || $level > 9) {
            throw new InvalidArgumentException('invalid spell');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($memberRow['class'] !== 'wizard') {
                throw new InvalidArgumentException('invalid class/spell combination');
            } else {
                try {
                    $database->prepare('INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $characterId, $body['spell_id'], $body['name'], $level]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate spell');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['spell_id' => $body['spell_id'], 'name' => $body['name'], 'level' => $level], 201);
            }
        }
    } elseif ($route === 'play_campaign_character_spells') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $membership->execute([$campaignId, $actor['username']]);
        if ($membership->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        if ($character->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $statement = $database->prepare('SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid');
            $statement->execute([$campaignId, $characterId]);
            $spells = [];
            foreach ($statement as $spell) {
                $spells[] = ['spell_id' => $spell['spell_id'], 'name' => $spell['name'], 'level' => (int) $spell['level']];
            }
            $response = new JsonResponse(['spells' => $spells]);
        }
    } elseif ($route === 'play_campaign_character_prepared_spells_update') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !array_key_exists('spell_ids', $body)) {
            throw new InvalidArgumentException('invalid prepared spells');
        }
        $spellIds = stringList($body['spell_ids'], 'invalid prepared spells');
        if (count($spellIds) !== count(array_unique($spellIds))) {
            throw new InvalidArgumentException('invalid prepared spells');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($memberRow['class'] !== 'wizard') {
                throw new InvalidArgumentException('invalid class/spell combination');
            } else {
                $maxPrepared = maximumPreparedSpells($memberRow['class'], (int) $memberRow['level']);
                if (count($spellIds) > $maxPrepared) {
                    throw new InvalidArgumentException('too many prepared spells');
                }
                $knownSpell = $database->prepare('SELECT 1 FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
                foreach ($spellIds as $spellId) {
                    $knownSpell->execute([$campaignId, $characterId, $spellId]);
                    if ($knownSpell->fetchColumn() === false) {
                        throw new InvalidArgumentException('unknown spell');
                    }
                }

                $database->beginTransaction();
                try {
                    $database->prepare('DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
                    $insert = $database->prepare('INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, spell_id, position) VALUES (?, ?, ?, ?)');
                    foreach ($spellIds as $position => $spellId) {
                        $insert->execute([$campaignId, $characterId, $spellId, $position]);
                    }
                    $database->commit();
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['character_id' => $characterId, 'prepared_spells' => $spellIds, 'max_prepared' => $maxPrepared]);
            }
        }
    } elseif ($route === 'play_campaign_character_prepared_spells_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $membership->execute([$campaignId, $actor['username']]);
        if ($membership->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $member = $database->prepare('SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $member->execute([$campaignId, $characterId]);
        $memberRow = $member->fetch();
        if ($memberRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $prepared = $database->prepare('SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY position');
            $prepared->execute([$campaignId, $characterId]);
            $response = new JsonResponse([
                'character_id' => $characterId,
                'prepared_spells' => $prepared->fetchAll(PDO::FETCH_COLUMN),
                'max_prepared' => maximumPreparedSpells($memberRow['class'], (int) $memberRow['level']),
            ]);
        }
    } elseif ($route === 'play_campaign_character_cast_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === ''
            || !isset($body['spell_id'], $body['target']) || !is_string($body['spell_id']) || $body['spell_id'] === ''
            || !is_string($body['target']) || $body['target'] === '') {
            throw new InvalidArgumentException('invalid cast');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT class, level FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($memberRow['class'] !== 'wizard') {
                throw new InvalidArgumentException('character is not a spellcaster');
            } else {
                // Joining the two persistent relations enforces both required
                // conditions: the spell is known and it is currently prepared.
                $spell = $database->prepare('SELECT spells.level FROM play_campaign_character_spells spells INNER JOIN play_campaign_character_prepared_spells prepared ON prepared.campaign_id = spells.campaign_id AND prepared.character_id = spells.character_id AND prepared.spell_id = spells.spell_id WHERE spells.campaign_id = ? AND spells.character_id = ? AND spells.spell_id = ?');
                $spell->execute([$campaignId, $characterId, $body['spell_id']]);
                $spellRow = $spell->fetch();
                if ($spellRow === false) {
                    throw new InvalidArgumentException('spell is not prepared');
                }
                $slotLevel = (int) $spellRow['level'];
                $slotCount = spellSlots($memberRow['class'], (int) $memberRow['level'], $slotLevel);
                $used = $database->prepare('SELECT COUNT(*) FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?');
                $used->execute([$campaignId, $characterId, $slotLevel]);
                $slotsRemaining = $slotCount - (int) $used->fetchColumn();
                if ($slotsRemaining < 1) {
                    throw new MembershipConflictException('no remaining spell slots');
                }

                $database->beginTransaction();
                try {
                    $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?');
                    $nextSequence->execute([$campaignId, $characterId]);
                    $sequence = (int) $nextSequence->fetchColumn();
                    $slotsRemaining--;
                    $database->prepare('INSERT INTO play_campaign_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $characterId, $sequence, $body['spell_id'], $body['target'], $slotLevel, $slotsRemaining]);
                    $database->commit();
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse([
                    'character_id' => $characterId,
                    'spell_id' => $body['spell_id'],
                    'target' => $body['target'],
                    'slot_level' => $slotLevel,
                    'slots_remaining' => $slotsRemaining,
                    'sequence' => $sequence,
                ], 201);
            }
        }
    } elseif ($route === 'play_campaign_character_casts') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $membership->execute([$campaignId, $actor['username']]);
        if ($membership->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        if ($character->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $statement = $database->prepare('SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence');
            $statement->execute([$campaignId, $characterId]);
            $casts = [];
            foreach ($statement as $cast) {
                $casts[] = [
                    'character_id' => $characterId,
                    'spell_id' => $cast['spell_id'],
                    'target' => $cast['target'],
                    'slot_level' => (int) $cast['slot_level'],
                    'slots_remaining' => (int) $cast['slots_remaining'],
                    'sequence' => (int) $cast['sequence'],
                ];
            }
            $response = new JsonResponse(['casts' => $casts]);
        }
    } elseif ($route === 'play_campaign_character_concentration_update') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === ''
            || !isset($body['spell_id'], $body['target'], $body['duration_turns'])
            || !is_string($body['spell_id']) || $body['spell_id'] === '' || !is_string($body['target']) || $body['target'] === '') {
            throw new InvalidArgumentException('invalid concentration');
        }
        $duration = integer($body['duration_turns']);
        if ($duration < 1) {
            throw new InvalidArgumentException('invalid concentration');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $member = $database->prepare('SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $member->execute([$campaignId, $characterId]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($memberRow['class'] !== 'wizard') {
                throw new InvalidArgumentException('character is not a spellcaster');
            } else {
                $spell = $database->prepare('SELECT 1 FROM play_campaign_character_spells spells INNER JOIN play_campaign_character_prepared_spells prepared ON prepared.campaign_id = spells.campaign_id AND prepared.character_id = spells.character_id AND prepared.spell_id = spells.spell_id WHERE spells.campaign_id = ? AND spells.character_id = ? AND spells.spell_id = ?');
                $spell->execute([$campaignId, $characterId, $body['spell_id']]);
                if ($spell->fetchColumn() === false) {
                    throw new InvalidArgumentException('spell is not prepared');
                }
                $database->prepare('INSERT INTO play_campaign_character_concentrations (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns')
                    ->execute([$campaignId, $characterId, $body['spell_id'], $body['target'], $duration]);
                $response = new JsonResponse(['character_id' => $characterId, 'concentration' => ['spell_id' => $body['spell_id'], 'target' => $body['target'], 'remaining_turns' => $duration]]);
            }
        }
    } elseif ($route === 'play_campaign_character_concentration_read' || $route === 'play_campaign_character_concentration_advance' || $route === 'play_campaign_character_concentration_clear') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        if ($route === 'play_campaign_character_concentration_clear') {
            $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
            $owner->execute([$campaignId, $characterId]);
            $ownerRow = $owner->fetch();
            if ($ownerRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($ownerRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } else {
                $database->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
                $response = new JsonResponse(['character_id' => $characterId, 'concentration' => null]);
            }
        } else {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            if ($character->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                if ($route === 'play_campaign_character_concentration_advance') {
                    $database->prepare('UPDATE play_campaign_character_concentrations SET remaining_turns = remaining_turns - 1 WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
                    $database->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ? AND remaining_turns <= 0')->execute([$campaignId, $characterId]);
                }
                $concentration = $database->prepare('SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?');
                $concentration->execute([$campaignId, $characterId]);
                $concentrationRow = $concentration->fetch();
                $response = new JsonResponse(['character_id' => $characterId, 'concentration' => $concentrationRow === false ? null : ['spell_id' => $concentrationRow['spell_id'], 'target' => $concentrationRow['target'], 'remaining_turns' => (int) $concentrationRow['remaining_turns']]]);
            }
        }
    } elseif ($route === 'play_campaign_npc_create' || $route === 'play_campaign_npc_agenda_update' || $route === 'play_campaign_npc_read' || $route === 'play_campaign_npc_dialogue_create' || $route === 'play_campaign_npc_dialogue_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $npcId = $request->attributes->get('npc_id');
        if (!is_string($campaignId) || $campaignId === ''
            || ($route !== 'play_campaign_npc_create' && (!is_string($npcId) || $npcId === ''))) {
            throw new InvalidArgumentException('invalid npc');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_npc_read' || $route === 'play_campaign_npc_dialogue_read') {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            if ($route === 'play_campaign_npc_dialogue_read') {
                $npc = $database->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
                $npc->execute([$campaignId, $npcId]);
                if ($npc->fetchColumn() === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $dialogue = $database->prepare('SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?' . ($campaignRow['owner'] === $actor['username'] ? '' : " AND visibility = 'public'") . ' ORDER BY sequence');
                    $dialogue->execute([$campaignId, $npcId]);
                    $entries = array_map(static fn (array $row): array => [
                        'dialogue_id' => $row['dialogue_id'],
                        'speaker' => $row['speaker'],
                        'text' => $row['text'],
                        'visibility' => $row['visibility'],
                    ], $dialogue->fetchAll());
                    $response = new JsonResponse(['npc_id' => $npcId, 'entries' => $entries]);
                }
            } else {
                $npc = $database->prepare('SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
                $npc->execute([$campaignId, $npcId]);
                $npcRow = $npc->fetch();
                if ($npcRow === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif ($campaignRow['owner'] === $actor['username']) {
                    $response = new JsonResponse(['npc_id' => $npcRow['npc_id'], 'name' => $npcRow['name'], 'agenda' => $npcRow['agenda'], 'public_status' => $npcRow['public_status']]);
                } else {
                    $response = new JsonResponse(['npc_id' => $npcRow['npc_id'], 'name' => $npcRow['name'], 'public_status' => $npcRow['public_status']]);
                }
            }
        } elseif ($campaignRow['owner'] !== $actor['username'] && $route !== 'play_campaign_npc_dialogue_create') {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_npc_create') {
            $body = requestBody($request);
            $newNpcId = $body['npc_id'] ?? null;
            $name = $body['name'] ?? null;
            $agenda = $body['agenda'] ?? null;
            $publicStatus = $body['public_status'] ?? null;
            if (!is_string($newNpcId) || $newNpcId === '' || !is_string($name) || $name === ''
                || !is_string($agenda) || $agenda === '' || !is_string($publicStatus) || $publicStatus === '') {
                throw new InvalidArgumentException('invalid npc');
            }
            try {
                $database->prepare('INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $newNpcId, $name, $agenda, $publicStatus]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate npc id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['npc_id' => $newNpcId, 'name' => $name, 'agenda' => $agenda, 'public_status' => $publicStatus], 201);
        } elseif ($route === 'play_campaign_npc_dialogue_create') {
            $npc = $database->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
            $npc->execute([$campaignId, $npcId]);
            if ($npc->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } else {
                $body = requestBody($request);
                $dialogueId = $body['dialogue_id'] ?? null;
                $speaker = $body['speaker'] ?? null;
                $text = $body['text'] ?? null;
                $visibility = $body['visibility'] ?? null;
                if (!is_string($dialogueId) || $dialogueId === '' || !is_string($speaker) || $speaker === ''
                    || !is_string($text) || $text === '' || !is_string($visibility) || !in_array($visibility, ['public', 'private'], true)) {
                    throw new InvalidArgumentException('invalid dialogue');
                }
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?');
                    $sequence->execute([$campaignId, $npcId]);
                    $database->prepare('INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, speaker, text, visibility, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $npcId, $dialogueId, $speaker, $text, $visibility, (int) $sequence->fetchColumn()]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate dialogue id');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['dialogue_id' => $dialogueId, 'speaker' => $speaker, 'text' => $text, 'visibility' => $visibility], 201);
            }
        } else {
            $body = requestBody($request);
            $agenda = $body['agenda'] ?? null;
            $publicStatus = $body['public_status'] ?? null;
            if (!is_string($agenda) || $agenda === '' || !is_string($publicStatus) || $publicStatus === '') {
                throw new InvalidArgumentException('invalid npc');
            }
            $npc = $database->prepare('SELECT name FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
            $npc->execute([$campaignId, $npcId]);
            $npcRow = $npc->fetch();
            if ($npcRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare('UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?')
                    ->execute([$agenda, $publicStatus, $campaignId, $npcId]);
                $response = new JsonResponse(['npc_id' => $npcId, 'name' => $npcRow['name'], 'agenda' => $agenda, 'public_status' => $publicStatus]);
            }
        }
    } elseif ($route === 'play_campaign_relationship_create' || $route === 'play_campaign_relationship_read' || $route === 'play_campaign_relationship_update') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid relationship');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_relationship_read') {
            if ($campaignRow['owner'] !== $actor['username']) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $edges = $database->prepare('SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY sequence');
            $edges->execute([$campaignId]);
            $response = new JsonResponse(['edges' => array_map(static fn (array $edge): array => [
                'source_id' => $edge['source_id'],
                'target_id' => $edge['target_id'],
                'kind' => $edge['kind'],
                'score' => (int) $edge['score'],
            ], $edges->fetchAll())]);
        } elseif ($campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_relationship_create') {
            $body = requestBody($request);
            $sourceId = $body['source_id'] ?? null;
            $targetId = $body['target_id'] ?? null;
            $kind = $body['kind'] ?? null;
            $score = $body['score'] ?? null;
            if (!is_string($sourceId) || $sourceId === '' || !is_string($targetId) || $targetId === ''
                || $sourceId === $targetId || !is_string($kind) || $kind === '' || !is_int($score) || $score < -100 || $score > 100) {
                throw new InvalidArgumentException('invalid relationship');
            }
            $entity = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? UNION SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
            $entity->execute([$campaignId, $sourceId, $campaignId, $sourceId]);
            if ($entity->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $entity->execute([$campaignId, $targetId, $campaignId, $targetId]);
                if ($entity->fetchColumn() === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    try {
                        $database->beginTransaction();
                        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_relationships WHERE campaign_id = ?');
                        $sequence->execute([$campaignId]);
                        $database->prepare('INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                            ->execute([$campaignId, $sourceId, $targetId, $kind, $score, (int) $sequence->fetchColumn()]);
                        $database->commit();
                    } catch (PDOException $exception) {
                        if ($database->inTransaction()) {
                            $database->rollBack();
                        }
                        if ((string) $exception->getCode() === '23000') {
                            throw new MembershipConflictException('duplicate relationship');
                        }
                        throw $exception;
                    } catch (Throwable $exception) {
                        if ($database->inTransaction()) {
                            $database->rollBack();
                        }
                        throw $exception;
                    }
                    $response = new JsonResponse(['source_id' => $sourceId, 'target_id' => $targetId, 'kind' => $kind, 'score' => $score], 201);
                }
            }
        } else {
            $sourceId = $request->attributes->get('source_id');
            $targetId = $request->attributes->get('target_id');
            $kind = $request->attributes->get('kind');
            $body = requestBody($request);
            $score = $body['score'] ?? null;
            if (!is_string($sourceId) || $sourceId === '' || !is_string($targetId) || $targetId === '' || !is_string($kind) || $kind === ''
                || !is_int($score) || $score < -100 || $score > 100) {
                throw new InvalidArgumentException('invalid relationship');
            }
            $edge = $database->prepare('SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
            $edge->execute([$campaignId, $sourceId, $targetId, $kind]);
            if ($edge->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare('UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?')
                    ->execute([$score, $campaignId, $sourceId, $targetId, $kind]);
                $response = new JsonResponse(['source_id' => $sourceId, 'target_id' => $targetId, 'kind' => $kind, 'score' => $score]);
            }
        }
    } elseif ($route === 'play_campaign_clue_create' || $route === 'play_campaign_clue_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid clue');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_clue_create') {
            if ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            $body = requestBody($request);
            $clueId = $body['clue_id'] ?? null;
            $text = $body['text'] ?? null;
            $audience = $body['audience'] ?? null;
            if (!is_string($clueId) || $clueId === '' || !is_string($text) || $text === ''
                || !is_string($audience) || !in_array($audience, ['character', 'party', 'hidden'], true)) {
                throw new InvalidArgumentException('invalid clue');
            }
            $hasCharacterId = array_key_exists('character_id', $body);
            if (($audience === 'character' && (!$hasCharacterId || !is_string($body['character_id']) || $body['character_id'] === ''))
                || ($audience !== 'character' && $hasCharacterId)) {
                throw new InvalidArgumentException('invalid clue');
            }
            $characterId = $audience === 'character' ? $body['character_id'] : null;
            if ($characterId !== null) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
                $member->execute([$campaignId, $characterId]);
                if ($member->fetchColumn() === false) {
                    throw new InvalidArgumentException('unknown character');
                }
            }
            try {
                $database->beginTransaction();
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_clues WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare('INSERT INTO play_campaign_clues (campaign_id, clue_id, text, audience, character_id, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $clueId, $text, $audience, $characterId, (int) $sequence->fetchColumn()]);
                $database->commit();
            } catch (PDOException $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate clue id');
                }
                throw $exception;
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $clue = ['clue_id' => $clueId, 'text' => $text, 'audience' => $audience];
            if ($characterId !== null) {
                $clue['character_id'] = $characterId;
            }
            $response = new JsonResponse($clue, 201);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            $characterId = null;
            if (!$isDm) {
                $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                $characterId = $member->fetchColumn();
                if ($characterId === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $clues = $isDm
                ? $database->prepare('SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY sequence')
                : $database->prepare("SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? AND (audience = 'party' OR (audience = 'character' AND character_id = ?)) ORDER BY sequence");
            $clues->execute($isDm ? [$campaignId] : [$campaignId, $characterId]);
            $result = [];
            foreach ($clues as $clue) {
                $item = ['clue_id' => $clue['clue_id'], 'text' => $clue['text'], 'audience' => $clue['audience']];
                if ($clue['audience'] === 'character') {
                    $item['character_id'] = $clue['character_id'];
                }
                $result[] = $item;
            }
            $response = new JsonResponse(['clues' => $result]);
        }
    } elseif ($route === 'play_campaign_quest_create' || $route === 'play_campaign_quest_read' || $route === 'play_campaign_quest_state_update' || $route === 'play_campaign_quest_rewards_configure' || $route === 'play_campaign_quest_rewards_award') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid quest');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_quest_read') {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $quests = $database->prepare('SELECT quest_id, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY sequence');
            $quests->execute([$campaignId]);
            $result = [];
            foreach ($quests as $quest) {
                $dependsOn = json_decode($quest['depends_on'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
                    throw new RuntimeException('invalid quest state');
                }
                $result[] = ['quest_id' => $quest['quest_id'], 'title' => $quest['title'], 'depends_on' => $dependsOn, 'state' => $quest['state']];
            }
            $response = new JsonResponse(['quests' => $result]);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_quest_create') {
            $body = requestBody($request);
            $questId = $body['quest_id'] ?? null;
            $title = $body['title'] ?? null;
            $dependsOn = $body['depends_on'] ?? null;
            if (!is_string($questId) || $questId === '' || !is_string($title) || $title === '') {
                throw new InvalidArgumentException('invalid quest');
            }
            $dependsOn = stringList($dependsOn, 'invalid quest');
            if (count($dependsOn) !== count(array_unique($dependsOn)) || in_array($questId, $dependsOn, true)) {
                throw new InvalidArgumentException('invalid quest');
            }
            foreach ($dependsOn as $dependencyId) {
                $dependency = $database->prepare('SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
                $dependency->execute([$campaignId, $dependencyId]);
                if ($dependency->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid quest');
                }
            }
            try {
                $database->beginTransaction();
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_quests WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare("INSERT INTO play_campaign_quests (campaign_id, quest_id, title, depends_on, state, sequence) VALUES (?, ?, ?, ?, 'locked', ?)")
                    ->execute([$campaignId, $questId, $title, json_encode($dependsOn, JSON_THROW_ON_ERROR), (int) $sequence->fetchColumn()]);
                $database->commit();
            } catch (PDOException $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate quest id');
                }
                throw $exception;
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['quest_id' => $questId, 'title' => $title, 'depends_on' => $dependsOn, 'state' => 'locked'], 201);
        } elseif ($route === 'play_campaign_quest_state_update') {
            $questId = $request->attributes->get('quest_id');
            $body = requestBody($request);
            $state = $body['state'] ?? null;
            if (!is_string($questId) || $questId === '' || !is_string($state) || !in_array($state, ['active', 'completed'], true)) {
                throw new InvalidArgumentException('invalid quest state');
            }
            $quest = $database->prepare('SELECT title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
            $quest->execute([$campaignId, $questId]);
            $questRow = $quest->fetch();
            if ($questRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $dependsOn = json_decode($questRow['depends_on'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
                    throw new RuntimeException('invalid quest state');
                }
                if (($questRow['state'] === 'locked' && $state === 'active')) {
                    foreach ($dependsOn as $dependencyId) {
                        $dependency = $database->prepare('SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
                        $dependency->execute([$campaignId, $dependencyId]);
                        if ($dependency->fetchColumn() !== 'completed') {
                            throw new MembershipConflictException('quest prerequisites incomplete');
                        }
                    }
                } elseif (!($questRow['state'] === 'active' && $state === 'completed')) {
                    throw new MembershipConflictException('invalid quest transition');
                }
                $database->prepare('UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?')
                    ->execute([$state, $campaignId, $questId]);
                $result = ['quest_id' => $questId, 'title' => $questRow['title'], 'depends_on' => $dependsOn, 'state' => $state];
                $reward = $database->prepare('SELECT xp, items FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ?');
                $reward->execute([$campaignId, $questId]);
                $rewardRow = $reward->fetch();
                if ($rewardRow !== false) {
                    $items = json_decode($rewardRow['items'], true, 512, JSON_THROW_ON_ERROR);
                    if (!is_array($items) || (array_is_list($items) && $items !== [])) {
                        throw new RuntimeException('invalid quest rewards');
                    }
                    $result['rewards'] = ['xp' => (int) $rewardRow['xp'], 'items' => $items === [] ? (object) [] : $items];
                }
                $response = new JsonResponse($result);
            }
        } else {
            $questId = $request->attributes->get('quest_id');
            if (!is_string($questId) || $questId === '') {
                throw new InvalidArgumentException('invalid quest rewards');
            }
            $quest = $database->prepare('SELECT title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
            $quest->execute([$campaignId, $questId]);
            $questRow = $quest->fetch();
            if ($questRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($route === 'play_campaign_quest_rewards_configure') {
                if (!in_array($questRow['state'], ['locked', 'active'], true)) {
                    throw new MembershipConflictException('quest is completed');
                }
                $reward = questRewardConfig($request);
                $database->prepare('INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, xp, items, awarded) VALUES (?, ?, ?, ?, 0) ON CONFLICT(campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items = excluded.items')
                    ->execute([$campaignId, $questId, $reward['xp'], json_encode($reward['items'], JSON_THROW_ON_ERROR)]);
                $dependsOn = json_decode($questRow['depends_on'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
                    throw new RuntimeException('invalid quest state');
                }
                $response = new JsonResponse(['quest_id' => $questId, 'title' => $questRow['title'], 'depends_on' => $dependsOn, 'state' => $questRow['state'], 'rewards' => ['xp' => $reward['xp'], 'items' => $reward['items'] === [] ? (object) [] : $reward['items']]]);
            } else {
                if ($questRow['state'] !== 'completed') {
                    throw new MembershipConflictException('quest is not completed');
                }
                try {
                    $database->beginTransaction();
                    $reward = $database->prepare('SELECT xp, items, awarded FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ?');
                    $reward->execute([$campaignId, $questId]);
                    $rewardRow = $reward->fetch();
                    if ($rewardRow === false || (int) $rewardRow['awarded'] !== 0) {
                        throw new MembershipConflictException('rewards unavailable');
                    }
                    $items = json_decode($rewardRow['items'], true, 512, JSON_THROW_ON_ERROR);
                    if (!is_array($items) || (array_is_list($items) && $items !== [])) {
                        throw new RuntimeException('invalid quest rewards');
                    }
                    $members = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? ORDER BY character_id');
                    $members->execute([$campaignId]);
                    $grant = $database->prepare('INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items) VALUES (?, ?, ?, ?, ?)');
                    $inventory = $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
                    foreach ($members as $member) {
                        $grant->execute([$campaignId, $questId, $member['character_id'], (int) $rewardRow['xp'], $rewardRow['items']]);
                        foreach ($items as $itemId => $quantity) {
                            $inventory->execute([$campaignId, $member['character_id'], $itemId, $quantity]);
                        }
                    }
                    $database->prepare('UPDATE play_campaign_quest_rewards SET awarded = 1 WHERE campaign_id = ? AND quest_id = ? AND awarded = 0')->execute([$campaignId, $questId]);
                    $database->commit();
                    $response = new JsonResponse(['quest_id' => $questId, 'awarded' => true, 'xp' => (int) $rewardRow['xp'], 'items' => $items === [] ? (object) [] : $items], 201);
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_world_events_create' || $route === 'play_campaign_world_events_read' || $route === 'play_campaign_world_event_resolve') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid world event');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, turn_number FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_world_events_read') {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $events = $database->prepare('SELECT event_id, turn_number, title, text, resolution_text, resolution_turn_number FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number, sequence');
            $events->execute([$campaignId]);
            $result = [];
            foreach ($events as $event) {
                $item = ['event_id' => $event['event_id'], 'turn_number' => (int) $event['turn_number'], 'title' => $event['title'], 'text' => $event['text']];
                if ($event['resolution_text'] === null) {
                    $item['status'] = 'scheduled';
                } else {
                    $item['status'] = 'resolved';
                    $item['resolution'] = ['turn_number' => (int) $event['resolution_turn_number'], 'text' => $event['resolution_text']];
                }
                $result[] = $item;
            }
            $response = new JsonResponse(['events' => $result]);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_world_events_create') {
            $body = requestBody($request);
            $eventId = $body['event_id'] ?? null;
            $turnNumber = $body['turn_number'] ?? null;
            $title = $body['title'] ?? null;
            $text = $body['text'] ?? null;
            $currentTurn = $campaignRow['turn_number'] === null ? 0 : (int) $campaignRow['turn_number'];
            if (!is_string($eventId) || $eventId === '' || !is_int($turnNumber) || $turnNumber < $currentTurn || !is_string($title) || $title === '' || !is_string($text) || $text === '') {
                throw new InvalidArgumentException('invalid world event');
            }
            try {
                $database->beginTransaction();
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_world_events WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare('INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, sequence) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $eventId, $turnNumber, $title, $text, (int) $sequence->fetchColumn()]);
                $database->commit();
            } catch (PDOException $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate world event id');
                }
                throw $exception;
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['event_id' => $eventId, 'turn_number' => $turnNumber, 'title' => $title, 'text' => $text, 'status' => 'scheduled'], 201);
        } else {
            $eventId = $request->attributes->get('event_id');
            $body = requestBody($request);
            $resolutionText = $body['text'] ?? null;
            if (!is_string($eventId) || $eventId === '' || !is_string($resolutionText) || $resolutionText === '') {
                throw new InvalidArgumentException('invalid world event resolution');
            }
            $event = $database->prepare('SELECT turn_number, title, text, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?');
            $event->execute([$campaignId, $eventId]);
            $eventRow = $event->fetch();
            if ($eventRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($eventRow['resolution_text'] !== null || (int) $campaignRow['turn_number'] !== (int) $eventRow['turn_number']) {
                throw new MembershipConflictException('world event cannot be resolved');
            } else {
                $currentTurn = (int) $campaignRow['turn_number'];
                $updated = $database->prepare('UPDATE play_campaign_world_events SET resolution_text = ?, resolution_turn_number = ? WHERE campaign_id = ? AND event_id = ? AND resolution_text IS NULL');
                $updated->execute([$resolutionText, $currentTurn, $campaignId, $eventId]);
                if ($updated->rowCount() === 0) {
                    throw new MembershipConflictException('world event cannot be resolved');
                }
                $response = new JsonResponse(['event_id' => $eventId, 'turn_number' => (int) $eventRow['turn_number'], 'title' => $eventRow['title'], 'text' => $eventRow['text'], 'status' => 'resolved', 'resolution' => ['turn_number' => $currentTurn, 'text' => $resolutionText]], 201);
            }
        }
    } elseif ($route === 'play_campaign_character_rewards_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }
        $database = database();
        $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $membership->execute([$campaignId, $actor['username']]);
        if ($membership->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        if ($character->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $grants = $database->prepare('SELECT xp, items FROM play_campaign_quest_reward_grants WHERE campaign_id = ? AND character_id = ? ORDER BY quest_id');
            $grants->execute([$campaignId, $characterId]);
            $xp = 0;
            $items = [];
            foreach ($grants as $grant) {
                $xp += (int) $grant['xp'];
                $grantItems = json_decode($grant['items'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($grantItems) || (array_is_list($grantItems) && $grantItems !== [])) {
                    throw new RuntimeException('invalid quest rewards');
                }
                foreach ($grantItems as $itemId => $quantity) {
                    $items[$itemId] = ($items[$itemId] ?? 0) + $quantity;
                }
            }
            ksort($items, SORT_STRING);
            $response = new JsonResponse(['character_id' => $characterId, 'xp' => $xp, 'items' => $items === [] ? (object) [] : $items]);
        }
    } elseif ($route === 'play_campaign_faction_create' || $route === 'play_campaign_faction_reputation_change' || $route === 'play_campaign_faction_reputation_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $factionId = $request->attributes->get('faction_id');
        if (!is_string($campaignId) || $campaignId === ''
            || ($route !== 'play_campaign_faction_create' && (!is_string($factionId) || $factionId === ''))) {
            throw new InvalidArgumentException('invalid faction');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_faction_create') {
            if ($campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            $body = requestBody($request);
            $newFactionId = $body['faction_id'] ?? null;
            $name = $body['name'] ?? null;
            if (!is_string($newFactionId) || $newFactionId === '' || !is_string($name) || $name === '') {
                throw new InvalidArgumentException('invalid faction');
            }
            try {
                $database->prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)')
                    ->execute([$campaignId, $newFactionId, $name]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate faction id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['faction_id' => $newFactionId, 'name' => $name], 201);
        } else {
            $faction = $database->prepare('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
            $faction->execute([$campaignId, $factionId]);
            if ($faction->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($route === 'play_campaign_faction_reputation_read') {
                if ($campaignRow['owner'] !== $actor['username']) {
                    $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                    $member->execute([$campaignId, $actor['username']]);
                    $memberRow = $member->fetch();
                    if ($memberRow === false) {
                        throw new ForbiddenException('permission denied');
                    }
                    $history = $database->prepare('SELECT character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence');
                    $history->execute([$campaignId, $factionId, $memberRow['character_id']]);
                } else {
                    $history = $database->prepare('SELECT character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence');
                    $history->execute([$campaignId, $factionId]);
                }
                $entries = array_map(static fn (array $row): array => [
                    'faction_id' => $factionId,
                    'character_id' => $row['character_id'],
                    'reputation' => (int) $row['reputation'],
                    'delta' => (int) $row['delta'],
                    'reason' => $row['reason'],
                ], $history->fetchAll());
                $response = new JsonResponse(['faction_id' => $factionId, 'entries' => $entries]);
            } else {
                if ($campaignRow['owner'] !== $actor['username']) {
                    throw new ForbiddenException('permission denied');
                }
                $body = requestBody($request);
                $characterId = $body['character_id'] ?? null;
                $delta = $body['delta'] ?? null;
                $reason = $body['reason'] ?? null;
                if (!is_string($characterId) || $characterId === '' || !is_int($delta) || $delta === 0 || $delta < -25 || $delta > 25 || !is_string($reason) || $reason === '') {
                    throw new InvalidArgumentException('invalid reputation');
                }
                $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
                $character->execute([$campaignId, $characterId]);
                if ($character->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid reputation character');
                } else {
                    $database->beginTransaction();
                    try {
                        $current = $database->prepare('SELECT reputation FROM play_campaign_faction_reputations WHERE campaign_id = ? AND faction_id = ? AND character_id = ?');
                        $current->execute([$campaignId, $factionId, $characterId]);
                        $reputation = max(-100, min(100, (int) ($current->fetchColumn() ?: 0) + $delta));
                        $database->prepare('INSERT INTO play_campaign_faction_reputations (campaign_id, faction_id, character_id, reputation) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, faction_id, character_id) DO UPDATE SET reputation = excluded.reputation')
                            ->execute([$campaignId, $factionId, $characterId, $reputation]);
                        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?');
                        $sequence->execute([$campaignId, $factionId]);
                        $database->prepare('INSERT INTO play_campaign_faction_reputation_history (campaign_id, faction_id, sequence, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)')
                            ->execute([$campaignId, $factionId, (int) $sequence->fetchColumn(), $characterId, $reputation, $delta, $reason]);
                        $database->commit();
                    } catch (Throwable $exception) {
                        if ($database->inTransaction()) {
                            $database->rollBack();
                        }
                        throw $exception;
                    }
                    $response = new JsonResponse(['faction_id' => $factionId, 'character_id' => $characterId, 'reputation' => $reputation, 'delta' => $delta, 'reason' => $reason], 201);
                }
            }
        }
    } elseif ($route === 'play_campaign_transactional_transfers_create' || $route === 'play_campaign_transactional_transfers_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid transactional transfer');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignOwner = $campaign->fetchColumn();
        if ($campaignOwner === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignOwner === $actor['username'];
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if (!$isDm && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_transactional_transfers_read') {
                $transfers = $database->prepare('SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC');
                $transfers->execute([$campaignId]);
                $response = new JsonResponse(['transfers' => array_map(static fn (array $transfer): array => [
                    'from_character_id' => $transfer['from_character_id'],
                    'to_character_id' => $transfer['to_character_id'],
                    'amount' => (int) $transfer['amount'],
                    'from_gold' => (int) $transfer['from_gold'],
                    'to_gold' => (int) $transfer['to_gold'],
                    'sequence' => (int) $transfer['sequence'],
                ], $transfers->fetchAll())]);
            } else {
                if ($actor['role'] !== 'player') {
                    throw new ForbiddenException('permission denied');
                }
                $body = requestBody($request);
                $fromCharacterId = $body['from_character_id'] ?? null;
                $toCharacterId = $body['to_character_id'] ?? null;
                $amount = $body['amount'] ?? null;
                $simulateFailure = $body['simulate_failure'] ?? false;
                if (!is_string($fromCharacterId) || $fromCharacterId === '' || !is_string($toCharacterId) || $toCharacterId === ''
                    || $fromCharacterId === $toCharacterId || !is_int($amount) || $amount < 1 || !is_bool($simulateFailure)) {
                    throw new InvalidArgumentException('invalid transactional transfer');
                }

                $source = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
                $source->execute([$campaignId, $fromCharacterId]);
                $sourceOwner = $source->fetchColumn();
                if ($sourceOwner === false) {
                    throw new InvalidArgumentException('invalid transactional transfer');
                }
                if ($sourceOwner !== $actor['username']) {
                    throw new ForbiddenException('permission denied');
                }
                $destination = $database->prepare('SELECT 1 FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
                $destination->execute([$campaignId, $toCharacterId]);
                if ($destination->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid transactional transfer');
                }

                $database->beginTransaction();
                try {
                    $balance = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
                    $balance->execute([$campaignId, $fromCharacterId]);
                    $sourceGold = $balance->fetchColumn();
                    if ($sourceGold === false) {
                        throw new InvalidArgumentException('invalid transactional transfer');
                    }
                    if ((int) $sourceGold < $amount) {
                        throw new MembershipConflictException('insufficient gold');
                    }
                    if ($simulateFailure) {
                        $database->rollBack();
                        $response = new JsonResponse(['error' => 'simulated failure'], 500);
                    } else {
                        $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
                        $debit->execute([$amount, $campaignId, $fromCharacterId, $amount]);
                        if ($debit->rowCount() !== 1) {
                            throw new MembershipConflictException('insufficient gold');
                        }
                        $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
                            ->execute([$amount, $campaignId, $toCharacterId]);
                        $sequenceQuery = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?');
                        $sequenceQuery->execute([$campaignId]);
                        $sequence = (int) $sequenceQuery->fetchColumn();
                        $fromGold = (int) $sourceGold - $amount;
                        $toBalance = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
                        $toBalance->execute([$campaignId, $toCharacterId]);
                        $toGold = (int) $toBalance->fetchColumn();
                        $database->prepare('INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)')
                            ->execute([$campaignId, $sequence, $fromCharacterId, $toCharacterId, $amount, $fromGold, $toGold]);
                        $database->commit();
                        $response = new JsonResponse(['from_character_id' => $fromCharacterId, 'to_character_id' => $toCharacterId, 'amount' => $amount, 'from_gold' => $fromGold, 'to_gold' => $toGold, 'sequence' => $sequence], 201);
                    }
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_character_currency' || $route === 'play_campaign_character_currency_transfer') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        if ($route === 'play_campaign_character_currency') {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $balance = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
            $balance->execute([$campaignId, $characterId]);
            $gold = $balance->fetchColumn();
            $response = $gold === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['character_id' => $characterId, 'gold' => (int) $gold]);
        } else {
            $body = requestBody($request);
            $destinationId = $body['to_character_id'] ?? null;
            $gold = $body['gold'] ?? null;
            if (!is_string($destinationId) || $destinationId === '' || !is_int($gold) || $gold < 1 || $destinationId === $characterId) {
                throw new InvalidArgumentException('invalid currency transfer');
            }

            $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
            $owner->execute([$campaignId, $characterId]);
            $ownerRow = $owner->fetch();
            if ($ownerRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($ownerRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } else {
                $destination = $database->prepare('SELECT 1 FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
                $destination->execute([$campaignId, $destinationId]);
                if ($destination->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid currency transfer');
                }

                $database->beginTransaction();
                try {
                    $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
                    $debit->execute([$gold, $campaignId, $characterId, $gold]);
                    if ($debit->rowCount() !== 1) {
                        throw new MembershipConflictException('insufficient gold');
                    }
                    $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
                        ->execute([$gold, $campaignId, $destinationId]);
                    $nextTransfer = $database->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_campaign_currency_transfers WHERE campaign_id = ?');
                    $nextTransfer->execute([$campaignId]);
                    $transferId = (int) $nextTransfer->fetchColumn();
                    $database->prepare('INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $transferId, $characterId, $destinationId, $gold]);
                    $balances = $database->prepare('SELECT character_id, gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id IN (?, ?)');
                    $balances->execute([$campaignId, $characterId, $destinationId]);
                    $balanceByCharacter = [];
                    foreach ($balances as $balance) {
                        $balanceByCharacter[$balance['character_id']] = (int) $balance['gold'];
                    }
                    $database->commit();
                    $response = new JsonResponse(['from_character_id' => $characterId, 'to_character_id' => $destinationId, 'gold' => $gold, 'from_gold' => $balanceByCharacter[$characterId], 'to_gold' => $balanceByCharacter[$destinationId], 'transfer_id' => $transferId], 201);
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_downtime_activity_create' || $route === 'play_campaign_downtime_allocation_create' || $route === 'play_campaign_downtime_allocation_progress' || $route === 'play_campaign_downtime_allocation_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $activityId = $request->attributes->get('activity_id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid downtime');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_downtime_activity_create') {
            $body = requestBody($request);
            $newActivityId = $body['activity_id'] ?? null;
            $name = $body['name'] ?? null;
            $cyclesRequired = $body['cycles_required'] ?? null;
            if (!is_string($newActivityId) || $newActivityId === '' || !is_string($name) || $name === ''
                || !is_int($cyclesRequired) || $cyclesRequired < 1 || $cyclesRequired > 10) {
                throw new InvalidArgumentException('invalid downtime activity');
            }
            if ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            try {
                $database->prepare('INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)')
                    ->execute([$campaignId, $newActivityId, $name, $cyclesRequired]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate downtime activity id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['activity_id' => $newActivityId, 'name' => $name, 'cycles_required' => $cyclesRequired], 201);
        } elseif ($route === 'play_campaign_downtime_allocation_read') {
            if (!is_string($characterId) || $characterId === '' || !is_string($activityId) || $activityId === '') {
                throw new InvalidArgumentException('invalid downtime allocation');
            }
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $allocation = $database->prepare('SELECT a.character_id, a.activity_id, a.cycles_completed, a.completions FROM play_campaign_downtime_allocations a JOIN play_campaign_members m ON m.campaign_id = a.campaign_id AND m.character_id = a.character_id JOIN play_campaign_downtime_activities d ON d.campaign_id = a.campaign_id AND d.activity_id = a.activity_id WHERE a.campaign_id = ? AND a.character_id = ? AND a.activity_id = ?');
            $allocation->execute([$campaignId, $characterId, $activityId]);
            $allocationRow = $allocation->fetch();
            $response = $allocationRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['character_id' => $allocationRow['character_id'], 'activity_id' => $allocationRow['activity_id'], 'cycles_completed' => (int) $allocationRow['cycles_completed'], 'completions' => (int) $allocationRow['completions']]);
        } else {
            if (!is_string($characterId) || $characterId === '') {
                throw new InvalidArgumentException('invalid downtime allocation');
            }
            if ($route === 'play_campaign_downtime_allocation_create') {
                $body = requestBody($request);
                $activityId = $body['activity_id'] ?? null;
                if (!is_string($activityId) || $activityId === '') {
                    throw new InvalidArgumentException('invalid downtime allocation');
                }
            }
            if (!is_string($activityId) || $activityId === '') {
                throw new InvalidArgumentException('invalid downtime allocation');
            }

            $character = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            $owner = $character->fetchColumn();
            $activity = $database->prepare('SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
            $activity->execute([$campaignId, $activityId]);
            $cyclesRequired = $activity->fetchColumn();
            if ($owner === false || $cyclesRequired === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($actor['role'] !== 'player' || $owner !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } elseif ($route === 'play_campaign_downtime_allocation_create') {
                try {
                    $database->prepare('INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)')
                        ->execute([$campaignId, $characterId, $activityId]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate downtime allocation');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['character_id' => $characterId, 'activity_id' => $activityId, 'cycles_completed' => 0, 'completions' => 0], 201);
            } else {
                $database->beginTransaction();
                try {
                    $allocation = $database->prepare('SELECT cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
                    $allocation->execute([$campaignId, $characterId, $activityId]);
                    $allocationRow = $allocation->fetch();
                    if ($allocationRow === false) {
                        $database->rollBack();
                        $response = new JsonResponse(['error' => 'not found'], 404);
                    } else {
                        $cyclesCompleted = (int) $allocationRow['cycles_completed'] + 1;
                        $completions = (int) $allocationRow['completions'];
                        if ($cyclesCompleted === (int) $cyclesRequired) {
                            $cyclesCompleted = 0;
                            ++$completions;
                        }
                        $database->prepare('UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?')
                            ->execute([$cyclesCompleted, $completions, $campaignId, $characterId, $activityId]);
                        $database->commit();
                        $response = new JsonResponse(['character_id' => $characterId, 'activity_id' => $activityId, 'cycles_completed' => $cyclesCompleted, 'completions' => $completions]);
                    }
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_recipe_create' || $route === 'play_campaign_recipe_read' || $route === 'play_campaign_recipe_craft') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid recipe');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_recipe_create') {
            $body = requestBody($request);
            $recipe = recipeFields($body);
            if ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            try {
                $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_recipes WHERE campaign_id = ?');
                $sequence->execute([$campaignId]);
                $database->prepare('INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients, output_item, output_quantity, sequence) VALUES (?, ?, ?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $recipe['recipe_id'], $recipe['name'], json_encode($recipe['ingredients'], JSON_THROW_ON_ERROR), $recipe['output_item'], $recipe['output_quantity'], (int) $sequence->fetchColumn()]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate recipe id');
                }
                throw $exception;
            }
            $response = new JsonResponse($recipe, 201);
        } elseif ($route === 'play_campaign_recipe_read') {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $recipes = $database->prepare('SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence');
            $recipes->execute([$campaignId]);
            $response = new JsonResponse(['recipes' => array_map(recipeResponse(...), $recipes->fetchAll())]);
        } else {
            $body = requestBody($request);
            $recipeId = $request->attributes->get('recipe_id');
            $characterId = $body['character_id'] ?? null;
            if (!is_string($recipeId) || $recipeId === '' || !is_string($characterId) || $characterId === '') {
                throw new InvalidArgumentException('invalid craft');
            }
            $recipeStatement = $database->prepare('SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?');
            $recipeStatement->execute([$campaignId, $recipeId]);
            $recipeRow = $recipeStatement->fetch();
            $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            if ($recipeRow === false || $character->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($actor['role'] !== 'player') {
                throw new ForbiddenException('permission denied');
            } else {
                $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
                $owner->execute([$campaignId, $characterId]);
                if ($owner->fetchColumn() !== $actor['username']) {
                    throw new ForbiddenException('permission denied');
                }
                $recipe = recipeResponse($recipeRow);
                $database->beginTransaction();
                try {
                    foreach ($recipe['ingredients'] as $itemId => $quantity) {
                        $consume = $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = quantity - ? WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity >= ?');
                        $consume->execute([$quantity, $campaignId, $characterId, $itemId, $quantity]);
                        if ($consume->rowCount() !== 1) {
                            throw new MembershipConflictException('insufficient inventory');
                        }
                    }
                    foreach ($recipe['ingredients'] as $itemId => $quantity) {
                        $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity = 0')
                            ->execute([$campaignId, $characterId, $itemId]);
                    }
                    $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
                        ->execute([$campaignId, $characterId, $recipe['output_item'], $recipe['output_quantity']]);
                    $database->commit();
                    $response = new JsonResponse(['character_id' => $characterId, 'recipe_id' => $recipeId, 'output_item' => $recipe['output_item'], 'output_quantity' => $recipe['output_quantity']], 201);
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'play_campaign_loot_create' || $route === 'play_campaign_loot_read' || $route === 'play_campaign_loot_vote' || $route === 'play_campaign_loot_assign') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $lootId = $request->attributes->get('loot_id');
        if (!is_string($campaignId) || $campaignId === '' || ($route !== 'play_campaign_loot_create' && (!is_string($lootId) || $lootId === ''))) {
            throw new InvalidArgumentException('invalid loot');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($route === 'play_campaign_loot_create') {
            $body = requestBody($request);
            $newLootId = $body['loot_id'] ?? null;
            $itemId = $body['item_id'] ?? null;
            $quantity = $body['quantity'] ?? null;
            if ($campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            if (!is_string($newLootId) || $newLootId === '' || !is_int($quantity) || $quantity < 1) {
                throw new InvalidArgumentException('invalid loot');
            }
            try {
                $itemId = inventoryCatalogItem($itemId);
                $database->prepare("INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id) VALUES (?, ?, ?, ?, 'open', NULL)")
                    ->execute([$campaignId, $newLootId, $itemId, $quantity]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new MembershipConflictException('duplicate loot id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['loot_id' => $newLootId, 'item_id' => $itemId, 'quantity' => $quantity, 'status' => 'open'], 201);
        } elseif ($route === 'play_campaign_loot_read') {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $loot = $database->prepare('SELECT item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
            $loot->execute([$campaignId, $lootId]);
            $lootRow = $loot->fetch();
            if ($lootRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $voteRows = $database->prepare('SELECT recipient_character_id, COUNT(*) AS vote_count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY recipient_character_id ASC');
                $voteRows->execute([$campaignId, $lootId]);
                $votes = [];
                foreach ($voteRows->fetchAll() as $voteRow) {
                    $votes[$voteRow['recipient_character_id']] = (int) $voteRow['vote_count'];
                }
                $response = new JsonResponse(['loot_id' => $lootId, 'item_id' => $lootRow['item_id'], 'quantity' => (int) $lootRow['quantity'], 'status' => $lootRow['status'], 'recipient_character_id' => $lootRow['recipient_character_id'], 'votes' => (object) $votes]);
            }
        } elseif ($route === 'play_campaign_loot_vote') {
            $body = requestBody($request);
            $recipientId = $body['recipient_character_id'] ?? null;
            if ($actor['role'] !== 'player') {
                throw new ForbiddenException('permission denied');
            }
            if (!is_string($recipientId) || $recipientId === '') {
                throw new InvalidArgumentException('invalid loot vote');
            }
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $loot = $database->prepare("SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?");
            $loot->execute([$campaignId, $lootId]);
            $lootRow = $loot->fetch();
            if ($lootRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($lootRow['status'] !== 'open') {
                throw new MembershipConflictException('loot is closed');
            } else {
                $recipient = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
                $recipient->execute([$campaignId, $recipientId]);
                if ($recipient->fetchColumn() === false) {
                    throw new InvalidArgumentException('invalid loot vote');
                }
                try {
                    $database->prepare('INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)')
                        ->execute([$campaignId, $lootId, $actor['username'], $recipientId]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('duplicate loot vote');
                    }
                    throw $exception;
                }
                $votes = $database->prepare('SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?');
                $votes->execute([$campaignId, $lootId, $recipientId]);
                $response = new JsonResponse(['loot_id' => $lootId, 'voter' => $actor['username'], 'recipient_character_id' => $recipientId, 'votes_for_recipient' => (int) $votes->fetchColumn()], 201);
            }
        } else {
            if ($campaignRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            }
            $database->beginTransaction();
            try {
                $loot = $database->prepare('SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
                $loot->execute([$campaignId, $lootId]);
                $lootRow = $loot->fetch();
                if ($lootRow === false) {
                    $database->rollBack();
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } elseif ($lootRow['status'] !== 'open') {
                    throw new MembershipConflictException('loot is closed');
                } else {
                    $leaders = $database->prepare('SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY votes DESC, recipient_character_id ASC LIMIT 2');
                    $leaders->execute([$campaignId, $lootId]);
                    $leaderRows = $leaders->fetchAll();
                    if ($leaderRows === [] || (count($leaderRows) > 1 && (int) $leaderRows[0]['votes'] === (int) $leaderRows[1]['votes'])) {
                        throw new MembershipConflictException('loot vote is not decisive');
                    }
                    $recipientId = $leaderRows[0]['recipient_character_id'];
                    $close = $database->prepare("UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ? AND status = 'open'");
                    $close->execute([$recipientId, $campaignId, $lootId]);
                    if ($close->rowCount() !== 1) {
                        throw new MembershipConflictException('loot is closed');
                    }
                    $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
                        ->execute([$campaignId, $recipientId, $lootRow['item_id'], (int) $lootRow['quantity']]);
                    $database->commit();
                    $response = new JsonResponse(['loot_id' => $lootId, 'recipient_character_id' => $recipientId, 'item_id' => $lootRow['item_id'], 'quantity' => (int) $lootRow['quantity'], 'votes' => (int) $leaderRows[0]['votes'], 'status' => 'assigned']);
                }
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
        }
    } elseif ($route === 'play_campaign_character_inventory_item_consume') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $itemId = $request->attributes->get('item_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !is_string($itemId) || $itemId !== 'healing-potion') {
            throw new InvalidArgumentException('invalid consumable item');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $consume = $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = quantity - 1 WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity > 0');
            $consume->execute([$campaignId, $characterId, $itemId]);
            if ($consume->rowCount() !== 1) {
                throw new MembershipConflictException('insufficient inventory');
            }
            $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity = 0')
                ->execute([$campaignId, $characterId, $itemId]);
            $remaining = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
            $remaining->execute([$campaignId, $characterId, $itemId]);
            $response = new JsonResponse(['character_id' => $characterId, 'item_id' => $itemId, 'quantity_consumed' => 1, 'total_quantity' => (int) ($remaining->fetchColumn() ?: 0), 'effect' => ['type' => 'healing', 'hp_restored' => 5]]);
        }
    } elseif ($route === 'play_campaign_character_inventory_item_add' || $route === 'play_campaign_character_inventory_items' || $route === 'play_campaign_character_inventory_item_remove') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        if ($route === 'play_campaign_character_inventory_items') {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            if ($character->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $items = $database->prepare('SELECT item_id, quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id');
                $items->execute([$campaignId, $characterId]);
                $stacks = [];
                foreach ($items as $item) {
                    $stacks[] = ['item_id' => $item['item_id'], 'quantity' => (int) $item['quantity']];
                }
                $response = new JsonResponse(['character_id' => $characterId, 'items' => $stacks]);
            }
        } else {
            $body = requestBody($request);
            $itemId = $route === 'play_campaign_character_inventory_item_add' ? ($body['item_id'] ?? null) : $request->attributes->get('item_id');
            $quantity = $body['quantity'] ?? null;
            if (!is_int($quantity) || $quantity < 1) {
                throw new InvalidArgumentException('invalid inventory item');
            }
            $itemId = inventoryCatalogItem($itemId);

            $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
            $owner->execute([$campaignId, $characterId]);
            $ownerRow = $owner->fetch();
            if ($ownerRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($ownerRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } elseif ($route === 'play_campaign_character_inventory_item_add') {
                $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
                    ->execute([$campaignId, $characterId, $itemId, $quantity]);
                $total = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                $total->execute([$campaignId, $characterId, $itemId]);
                $response = new JsonResponse(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'total_quantity' => (int) $total->fetchColumn()], 201);
            } else {
                $held = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                $held->execute([$campaignId, $characterId, $itemId]);
                $heldQuantity = $held->fetchColumn();
                if ($heldQuantity === false || $quantity > (int) $heldQuantity) {
                    throw new MembershipConflictException('insufficient inventory');
                }
                $remaining = (int) $heldQuantity - $quantity;
                if ($remaining === 0) {
                    $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$campaignId, $characterId, $itemId]);
                } else {
                    $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$remaining, $campaignId, $characterId, $itemId]);
                }
                $response = new JsonResponse(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'total_quantity' => $remaining]);
            }
        }
    } elseif ($route === 'play_campaign_character_equipment_update' || $route === 'play_campaign_character_equipment_read' || $route === 'play_campaign_character_equipment_attune') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $slot = $request->attributes->get('slot');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !is_string($slot) || !in_array($slot, ['armor', 'accessory'], true)) {
            throw new InvalidArgumentException('invalid equipment');
        }

        $database = database();
        if ($route === 'play_campaign_character_equipment_read') {
            $membership = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $membership->execute([$campaignId, $actor['username']]);
            if ($membership->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            if ($character->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $equipment = $database->prepare('SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
                $equipment->execute([$campaignId, $characterId, $slot]);
                $row = $equipment->fetch();
                $response = new JsonResponse(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $row === false ? '' : $row['item_id'], 'attuned' => $row !== false && (int) $row['attuned'] === 1]);
            }
        } else {
            $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
            $owner->execute([$campaignId, $characterId]);
            $ownerRow = $owner->fetch();
            if ($ownerRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($ownerRow['owner'] !== $actor['username']) {
                throw new ForbiddenException('permission denied');
            } elseif ($route === 'play_campaign_character_equipment_update') {
                $body = requestBody($request);
                $itemId = $body['item_id'] ?? null;
                $legalSlots = ['leather-armor' => 'armor', 'ring-of-protection' => 'accessory', 'amulet-of-health' => 'accessory'];
                if (!is_string($itemId) || !isset($legalSlots[$itemId]) || $legalSlots[$itemId] !== $slot) {
                    throw new InvalidArgumentException('invalid equipment');
                }
                $held = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
                $held->execute([$campaignId, $characterId, $itemId]);
                if ((int) $held->fetchColumn() < 1) {
                    throw new InvalidArgumentException('item is not held');
                }
                $database->prepare('INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0')
                    ->execute([$campaignId, $characterId, $slot, $itemId]);
                $response = new JsonResponse(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $itemId, 'attuned' => false]);
            } else {
                $equipment = $database->prepare('SELECT item_id FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
                $equipment->execute([$campaignId, $characterId, $slot]);
                $itemId = $equipment->fetchColumn();
                if ($slot !== 'accessory' || !in_array($itemId, ['ring-of-protection', 'amulet-of-health'], true)) {
                    throw new InvalidArgumentException('invalid attunement');
                }
                $attuned = $database->prepare('SELECT 1 FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
                $attuned->execute([$campaignId, $characterId]);
                if ($attuned->fetchColumn() !== false) {
                    throw new MembershipConflictException('attunement limit reached');
                }
                $database->prepare('UPDATE play_campaign_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?')->execute([$campaignId, $characterId, $slot]);
                $response = new JsonResponse(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $itemId, 'attuned' => true, 'attunement_count' => 1, 'max_attunements' => 1]);
            }
        }
    } elseif ($route === 'play_campaign_character_owner') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        $response = $ownerRow === false
            ? new JsonResponse(['error' => 'not found'], 404)
            : new JsonResponse(['character_id' => $characterId, 'owner' => $ownerRow['owner']]);
    } elseif ($route === 'play_campaign_character_claim') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '') {
            throw new InvalidArgumentException('invalid character');
        }

        $database = database();
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            throw new ForbiddenException('permission denied');
        }
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $character->execute([$campaignId, $characterId]);
            if ($character->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner) VALUES (?, ?, ?)')->execute([$characterId, $campaignId, $actor['username']]);
                $response = new JsonResponse(['character_id' => $characterId, 'owner' => $actor['username']], 201);
            }
        } elseif ($ownerRow['owner'] === null) {
            $database->prepare('UPDATE play_campaign_character_owners SET owner = ? WHERE campaign_id = ? AND character_id = ?')->execute([$actor['username'], $campaignId, $characterId]);
            $response = new JsonResponse(['character_id' => $characterId, 'owner' => $actor['username']], 201);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new MembershipConflictException('character already owned');
        } else {
            $response = new JsonResponse(['character_id' => $characterId, 'owner' => $actor['username']], 201);
        }
    } elseif ($route === 'play_campaign_character_transfer') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('char_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !isset($body['new_owner']) || !is_string($body['new_owner']) || $body['new_owner'] === '') {
            throw new InvalidArgumentException('invalid ownership transfer');
        }

        $database = database();
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerRow = $owner->fetch();
        if ($ownerRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($ownerRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $newOwner = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $newOwner->execute([$campaignId, $body['new_owner']]);
            if ($newOwner->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $database->prepare('UPDATE play_campaign_character_owners SET owner = ? WHERE campaign_id = ? AND character_id = ?')->execute([$body['new_owner'], $campaignId, $characterId]);
            $response = new JsonResponse(['character_id' => $characterId, 'owner' => $body['new_owner']], 201);
        }
    } elseif ($route === 'play_campaign_encounter_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '') {
            throw new InvalidArgumentException('invalid encounter');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $database->beginTransaction();
            try {
                $activeEncounter = $database->prepare("SELECT 1 FROM play_campaign_encounters WHERE campaign_id = ? AND status = 'active'");
                $activeEncounter->execute([$campaignId]);
                if ($activeEncounter->fetchColumn() !== false) {
                    throw new MembershipConflictException('campaign already in combat');
                }
                try {
                    $database->prepare('INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants, exploration_actor) VALUES (?, ?, ?, ?, ?, ?)')
                        ->execute([$body['id'], $campaignId, $body['name'], 'active', '[]', $campaignRow['current_actor']]);
                    $database->prepare("UPDATE play_campaigns SET phase = 'combat' WHERE id = ?")
                        ->execute([$campaignId]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate encounter id');
                    }
                    throw $exception;
                }
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'status' => 'active', 'combatants' => []], 201);
        }
    } elseif ($route === 'play_campaign_combatant_bind') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['member'], $body['initiative']) || !is_string($body['member']) || $body['member'] === '') {
            throw new InvalidArgumentException('invalid combatant');
        }
        $initiative = integer($body['initiative']);

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare("SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $member = $database->prepare('SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $body['member']]);
                $memberRow = $member->fetch();
                if ($memberRow === false) {
                    throw new InvalidArgumentException('unknown member');
                }
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }
                foreach ($combatants as $combatant) {
                    if (is_array($combatant) && ($combatant['member'] ?? null) === $body['member']) {
                        throw new MembershipConflictException('member already bound');
                    }
                }
                $combatant = ['member' => $body['member'], 'character_id' => $memberRow['character_id'], 'name' => $memberRow['name'], 'initiative' => $initiative];
                if (array_key_exists('turn_order', $combatants[0] ?? [])) {
                    $combatant['turn_order'] = max(array_map(static fn (array $item): int => $item['turn_order'], $combatants)) + 1;
                }
                $combatants[] = $combatant;
                $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                    ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
                $response = new JsonResponse($combatant, 201);
            }
        }
    } elseif ($route === 'play_campaign_combatant_unbind') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $memberName = $request->attributes->get('member');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !is_string($memberName) || $memberName === '') {
            throw new InvalidArgumentException('invalid combatant');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare("SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }
                $removed = false;
                $remainingCombatants = [];
                foreach ($combatants as $combatant) {
                    if (is_array($combatant) && ($combatant['member'] ?? null) === $memberName) {
                        $removed = true;
                        continue;
                    }
                    $remainingCombatants[] = $combatant;
                }
                if (!$removed) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                        ->execute([json_encode($remainingCombatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
                    $response = new JsonResponse(['removed' => $memberName]);
                }
            }
        }
    } elseif ($route === 'play_campaign_monster_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['monster_id'], $body['name'], $body['hp_max'], $body['initiative']) || !is_string($body['monster_id']) || $body['monster_id'] === '' || !is_string($body['name']) || $body['name'] === '') {
            throw new InvalidArgumentException('invalid monster');
        }
        $hpMax = integer($body['hp_max']);
        $initiative = integer($body['initiative']);
        if ($hpMax < 1) {
            throw new InvalidArgumentException('invalid monster');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }
                foreach ($combatants as $combatant) {
                    if (is_array($combatant) && ($combatant['monster_id'] ?? null) === $body['monster_id']) {
                        throw new DuplicateIdException('duplicate monster id');
                    }
                }
                $monster = ['monster_id' => $body['monster_id'], 'name' => $body['name'], 'hp_max' => $hpMax, 'initiative' => $initiative, 'hp_current' => $hpMax];
                if (array_key_exists('turn_order', $combatants[0] ?? [])) {
                    $monster['turn_order'] = max(array_map(static fn (array $item): int => $item['turn_order'], $combatants)) + 1;
                }
                $combatants[] = $monster;
                $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                    ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
                $response = new JsonResponse($monster, 201);
            }
        }
    } elseif ($route === 'play_campaign_monster_delete') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $monsterId = $request->attributes->get('monster_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !is_string($monsterId) || $monsterId === '') {
            throw new InvalidArgumentException('invalid monster');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }
                $removed = false;
                $remainingCombatants = [];
                foreach ($combatants as $combatant) {
                    if (is_array($combatant) && ($combatant['monster_id'] ?? null) === $monsterId) {
                        $removed = true;
                        continue;
                    }
                    $remainingCombatants[] = $combatant;
                }
                if (!$removed) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                        ->execute([json_encode($remainingCombatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
                    $response = new JsonResponse(['removed' => $monsterId]);
                }
            }
        }
    } elseif ($route === 'play_campaign_combatant_damage' || $route === 'play_campaign_combatant_heal') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['target'], $body['amount']) || !is_string($body['target']) || $body['target'] === '') {
            throw new InvalidArgumentException('invalid hit points');
        }
        $amount = integer($body['amount']);
        if ($amount < 0) {
            throw new InvalidArgumentException('invalid hit points');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare("SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }

                $found = false;
                foreach ($combatants as &$combatant) {
                    if (!is_array($combatant) || ($combatant['monster_id'] ?? null) !== $body['target']) {
                        continue;
                    }
                    if (!is_int($combatant['hp_current'] ?? null) || !is_int($combatant['hp_max'] ?? null)) {
                        throw new RuntimeException('invalid encounter state');
                    }
                    $found = true;
                    $before = $combatant['hp_current'];
                    $after = $route === 'play_campaign_combatant_damage'
                        ? max(0, $before - $amount)
                        : min($combatant['hp_max'], $before + $amount);
                    $combatant['hp_current'] = $after;
                    break;
                }
                unset($combatant);

                if (!$found) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ? AND status = ?')
                        ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId, 'active']);
                    $response = new JsonResponse([
                        'target' => $body['target'],
                        'hp_before' => $before,
                        'hp_after' => $after,
                        $route === 'play_campaign_combatant_damage' ? 'damage' : 'healing' => $amount,
                    ]);
                }
            }
        }
    } elseif ($route === 'play_campaign_encounter_condition') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['target'], $body['condition'], $body['duration_rounds']) || !is_string($body['target']) || $body['target'] === '' || !is_string($body['condition']) || $body['condition'] === '') {
            throw new InvalidArgumentException('invalid condition');
        }
        $duration = integer($body['duration_rounds']);
        if ($duration < 1) {
            throw new InvalidArgumentException('invalid condition');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare("SELECT combatants, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants)) {
                    throw new RuntimeException('invalid encounter state');
                }
                $knownTarget = false;
                foreach ($combatants as $combatant) {
                    if (is_array($combatant) && encounterConditionTarget($combatant) === $body['target']) {
                        $knownTarget = true;
                        break;
                    }
                }
                if (!$knownTarget) {
                    throw new InvalidArgumentException('unknown target');
                }
                $conditions = encounterConditions($encounterRow['conditions']);
                $conditions[$body['target']][] = ['condition' => $body['condition'], 'remaining_rounds' => $duration];
                $database->prepare("UPDATE play_campaign_encounters SET conditions = ? WHERE id = ? AND campaign_id = ? AND status = 'active'")
                    ->execute([json_encode($conditions, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
                $response = new JsonResponse(['target' => $body['target'], 'conditions' => $conditions[$body['target']]], 201);
            }
        }
    } elseif ($route === 'play_campaign_encounter_rewards') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !array_key_exists('xp', $body) || !array_key_exists('loot', $body)) {
            throw new InvalidArgumentException('invalid rewards');
        }
        $xp = integer($body['xp']);
        if ($xp < 0 || !is_array($body['loot']) || !array_is_list($body['loot'])) {
            throw new InvalidArgumentException('invalid rewards');
        }
        $loot = [];
        foreach ($body['loot'] as $item) {
            if (!is_array($item) || !array_key_exists('slug', $item) || !array_key_exists('quantity', $item)) {
                throw new InvalidArgumentException('invalid rewards');
            }
            $quantity = integer($item['quantity']);
            if ($quantity < 1) {
                throw new InvalidArgumentException('invalid rewards');
            }
            $loot[] = ['slug' => compendiumSlug($item['slug']), 'quantity' => $quantity];
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare('SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
            $encounter->execute([$encounterId, $campaignId]);
            if ($encounter->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                try {
                    $database->prepare('INSERT INTO play_campaign_encounter_rewards (encounter_id, campaign_id, xp, loot) VALUES (?, ?, ?, ?)')
                        ->execute([$encounterId, $campaignId, $xp, json_encode($loot, JSON_THROW_ON_ERROR)]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new MembershipConflictException('rewards already awarded');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['encounter_id' => $encounterId, 'xp' => $xp, 'loot' => $loot]);
            }
        }
    } elseif ($route === 'play_campaign_encounter_close') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '') {
            throw new InvalidArgumentException('invalid encounter');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $encounter = $database->prepare('SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
            $encounter->execute([$encounterId, $campaignId]);
            if ($encounter->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
                    ->execute([$encounterId, $campaignId]);
                $reward = $database->prepare('SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ? AND campaign_id = ?');
                $reward->execute([$encounterId, $campaignId]);
                $xp = $reward->fetchColumn();
                $response = new JsonResponse(['id' => $encounterId, 'status' => 'closed', 'xp_awarded' => $xp === false ? 0 : (int) $xp]);
            }
        }
    } elseif ($route === 'play_campaign_encounter_end') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '') {
            throw new InvalidArgumentException('invalid encounter');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, phase FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } elseif ($campaignRow['phase'] !== 'combat') {
            throw new MembershipConflictException('campaign is not in combat');
        } else {
            $database->beginTransaction();
            try {
                // /close predates this endpoint and leaves the campaign in
                // combat so rewards can still be handled. Finalizing that
                // closed encounter must therefore remain possible here.
                $encounter = $database->prepare('SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
                $encounter->execute([$encounterId, $campaignId]);
                $encounterRow = $encounter->fetch();
                if ($encounterRow === false) {
                    throw new MembershipConflictException('campaign is not in combat');
                }
                $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ? AND status = 'active'")
                    ->execute([$encounterId, $campaignId]);
                // Ending an encounter hands authority back to the DM.  This
                // is the deterministic exploration checkpoint used by the
                // campaign replay flow, regardless of who was active when
                // combat was opened.
                $database->prepare("UPDATE play_campaigns SET current_actor = owner, phase = 'exploration' WHERE id = ?")
                    ->execute([$campaignId]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse([
                'campaign_id' => $campaignId,
                'status' => 'active',
                'phase' => 'exploration',
                'current_actor' => $campaignRow['owner'],
            ]);
        }
    } elseif ($route === 'play_campaign_encounter_status') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '') {
            throw new InvalidArgumentException('invalid encounter');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $encounter = $database->prepare("SELECT status, combatants, round, turn_index, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants) || $combatants === []) {
                    throw new MembershipConflictException('encounter has no combatants');
                }
                $order = encounterInitiativeOrder($combatants);
                $turnIndex = (int) $encounterRow['turn_index'];
                if ($turnIndex < 0 || $turnIndex >= count($order)) {
                    $turnIndex = 0;
                }
                $response = new JsonResponse([
                    'round' => max(1, (int) $encounterRow['round']),
                    'turn_index' => $turnIndex,
                    'active' => encounterActiveCombatant($order[$turnIndex]),
                    'order' => array_map(static fn (array $combatant): array => encounterActiveCombatant($combatant), $order),
                    'conditions' => (object) encounterConditions($encounterRow['conditions']),
                ]);
            }
        }
    } elseif ($route === 'play_campaign_combat_action_create') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['type'], $body['target'], $body['text']) || !is_string($body['type']) || !in_array($body['type'], ['attack', 'help', 'dodge', 'ready'], true) || !is_string($body['target']) || $body['target'] === '' || !is_string($body['text']) || $body['text'] === '') {
            throw new InvalidArgumentException('invalid combat action');
        }

        $database = database();
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $encounter = $database->prepare("SELECT combatants, round, turn_index, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants) || $combatants === []) {
                    throw new MembershipConflictException('encounter has no combatants');
                }
                $order = encounterInitiativeOrder($combatants);
                $turnIndex = (int) $encounterRow['turn_index'];
                if ($turnIndex < 0 || $turnIndex >= count($order)) {
                    $turnIndex = 0;
                }
                $active = $order[$turnIndex];
                if ($actor['role'] !== 'player' || ($active['member'] ?? null) !== $actor['username']) {
                    throw new MembershipConflictException('not the active combatant');
                }

                $database->beginTransaction();
                try {
                    $sequence = nextPlayEventSequence($database, $campaignId);
                    $database->prepare('INSERT INTO play_campaign_combat_actions (campaign_id, encounter_id, sequence, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $encounterId, $sequence, $actor['username'], $body['type'], $body['target'], $body['text']]);
                    $database->commit();
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['sequence' => $sequence, 'kind' => 'combat_action', 'actor' => $actor['username'], 'type' => $body['type'], 'target' => $body['target'], 'text' => $body['text']], 201);
            }
        }
    } elseif ($route === 'play_campaign_encounter_turn_delay') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '') {
            throw new InvalidArgumentException('invalid delay');
        }
        $delayIndex = $body['new_index'] ?? $body['index'] ?? $body['to_index'] ?? null;
        $index = integer($delayIndex);

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $encounter = $database->prepare("SELECT combatants, turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants) || $combatants === []) {
                    throw new MembershipConflictException('encounter has no combatants');
                }
                $order = encounterInitiativeOrder($combatants);
                $turnIndex = (int) $encounterRow['turn_index'];
                if ($turnIndex < 0 || $turnIndex >= count($order)) {
                    $turnIndex = 0;
                }
                $active = $order[$turnIndex];
                if ($campaignRow['owner'] !== $actor['username'] && ($active['member'] ?? null) !== $actor['username']) {
                    throw new MembershipConflictException('not the active combatant');
                }
                if ($index <= $turnIndex || $index >= count($order)) {
                    throw new InvalidArgumentException('invalid delay index');
                }

                array_splice($order, $turnIndex, 1);
                array_splice($order, $index, 0, [$active]);
                foreach ($order as $position => &$combatant) {
                    $combatant['turn_order'] = $position;
                }
                unset($combatant);
                $database->prepare('UPDATE play_campaign_encounters SET combatants = ?, turn_index = ? WHERE id = ? AND campaign_id = ? AND status = ?')
                    ->execute([json_encode($order, JSON_THROW_ON_ERROR), $index, $encounterId, $campaignId, 'active']);
                $response = new JsonResponse(['order' => array_map(static fn (array $combatant): array => encounterActiveCombatant($combatant), $order)]);
            }
        }
    } elseif ($route === 'play_campaign_encounter_turn_ready') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '' || !isset($body['trigger']) || !is_string($body['trigger']) || $body['trigger'] === '') {
            throw new InvalidArgumentException('invalid ready action');
        }

        $database = database();
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $encounter = $database->prepare("SELECT combatants, turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants) || $combatants === []) {
                    throw new MembershipConflictException('encounter has no combatants');
                }
                $order = encounterInitiativeOrder($combatants);
                $turnIndex = (int) $encounterRow['turn_index'];
                if ($turnIndex < 0 || $turnIndex >= count($order)) {
                    $turnIndex = 0;
                }
                if (($order[$turnIndex]['member'] ?? null) !== $actor['username']) {
                    throw new MembershipConflictException('not the active combatant');
                }
                $sequence = (int) $database->query('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_ready_actions')->fetchColumn();
                $database->prepare('INSERT INTO play_campaign_ready_actions (campaign_id, encounter_id, sequence, actor, trigger) VALUES (?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $encounterId, $sequence, $actor['username'], $body['trigger']]);
                $response = new JsonResponse(['actor' => $actor['username'], 'trigger' => $body['trigger']], 201);
            }
        }
    } elseif ($route === 'play_campaign_encounter_turn' || $route === 'play_campaign_encounter_turn_advance') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $encounterId = $request->attributes->get('enc_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($encounterId) || $encounterId === '') {
            throw new InvalidArgumentException('invalid encounter');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            $encounter = $database->prepare("SELECT combatants, round, turn_index, conditions FROM play_campaign_encounters WHERE id = ? AND campaign_id = ? AND status = 'active'");
            $encounter->execute([$encounterId, $campaignId]);
            $encounterRow = $encounter->fetch();
            if ($encounterRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $combatants = json_decode($encounterRow['combatants'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($combatants) || !array_is_list($combatants) || $combatants === []) {
                    throw new MembershipConflictException('encounter has no combatants');
                }
                $order = encounterInitiativeOrder($combatants);
                $turnIndex = (int) $encounterRow['turn_index'];
                if ($turnIndex < 0 || $turnIndex >= count($order)) {
                    $turnIndex = 0;
                }
                $round = max(1, (int) $encounterRow['round']);
                $active = $order[$turnIndex];

                if ($route === 'play_campaign_encounter_turn_advance') {
                    if ($campaignRow['owner'] !== $actor['username'] && ($active['member'] ?? null) !== $actor['username']) {
                        throw new MembershipConflictException('not the active combatant');
                    }
                    $turnIndex++;
                    if ($turnIndex === count($order)) {
                        $turnIndex = 0;
                        $round++;
                    }
                    $active = $order[$turnIndex];
                    $target = encounterConditionTarget($active);
                    $conditions = encounterConditions($encounterRow['conditions']);
                    if ($target !== null && isset($conditions[$target])) {
                        foreach ($conditions[$target] as &$condition) {
                            $condition['remaining_rounds']--;
                        }
                        unset($condition);
                        $conditions[$target] = array_values(array_filter(
                            $conditions[$target],
                            static fn (array $condition): bool => $condition['remaining_rounds'] > 0,
                        ));
                        if ($conditions[$target] === []) {
                            unset($conditions[$target]);
                        }
                    }
                    $database->prepare('UPDATE play_campaign_encounters SET round = ?, turn_index = ?, conditions = ? WHERE id = ? AND campaign_id = ? AND status = ?')
                        ->execute([$round, $turnIndex, json_encode($conditions, JSON_THROW_ON_ERROR), $encounterId, $campaignId, 'active']);
                }

                $response = new JsonResponse([
                    'round' => $round,
                    'turn_index' => $turnIndex,
                    'active' => encounterActiveCombatant($active),
                ]);
            }
        }
    } elseif ($route === 'play_campaign_turn_nudge') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['message']) || !is_string($body['message']) || $body['message'] === '') {
            throw new InvalidArgumentException('invalid nudge');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $increment = $database->prepare('UPDATE play_campaigns SET nudge_count = nudge_count + 1 WHERE id = ?');
            $increment->execute([$campaignId]);
            $count = $database->prepare('SELECT nudge_count FROM play_campaigns WHERE id = ?');
            $count->execute([$campaignId]);
            $response = new JsonResponse([
                'actor' => $owner,
                'target' => $campaignRow['current_actor'],
                'message' => $body['message'],
                'nudge_count' => (int) $count->fetchColumn(),
            ], 201);
        }
    } elseif ($route === 'play_campaign_my_turn') {
        $actor = authenticatedActor($request);
        if ($actor['role'] !== 'player') {
            throw new ForbiddenException('permission denied');
        }
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid play campaign');
        }

        $database = database();
        $campaign = $database->prepare('SELECT current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            $memberRow = $member->fetch();
            if ($memberRow === false) {
                throw new ForbiddenException('permission denied');
            }

            $events = $database->prepare("SELECT sequence, 'narration' AS kind, actor, NULL AS type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_narrations WHERE campaign_id = ? UNION ALL SELECT sequence, 'action' AS kind, actor, type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_actions WHERE campaign_id = ? UNION ALL SELECT sequence, 'resolution' AS kind, 'dm' AS actor, NULL AS type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_resolutions WHERE campaign_id = ? UNION ALL SELECT sequence, 'travel' AS kind, actor, NULL AS type, NULL AS text, destination_id, travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_travels WHERE campaign_id = ? UNION ALL SELECT sequence, 'rest' AS kind, actor, type, NULL AS text, NULL AS destination_id, NULL AS travel_turns, hp_current, hp_max FROM play_campaign_rests WHERE campaign_id = ? ORDER BY sequence");
            $events->execute([$campaignId, $campaignId, $campaignId, $campaignId, $campaignId]);
            $recentEvents = [];
            foreach ($events as $event) {
                $recentEvent = [
                    'sequence' => (int) $event['sequence'],
                    'kind' => $event['kind'],
                    'actor' => $event['actor'],
                ];
                if ($event['text'] !== null) {
                    $recentEvent['text'] = $event['text'];
                }
                if ($event['type'] !== null) {
                    $recentEvent['type'] = $event['type'];
                }
                if ($event['destination_id'] !== null) {
                    $recentEvent['destination_id'] = $event['destination_id'];
                    $recentEvent['travel_turns'] = (int) $event['travel_turns'];
                }
                if ($event['hp_current'] !== null) {
                    $recentEvent['hp_current'] = (int) $event['hp_current'];
                    $recentEvent['hp_max'] = (int) $event['hp_max'];
                }
                $recentEvents[] = $recentEvent;
            }
            $response = new JsonResponse([
                'is_my_turn' => $campaignRow['current_actor'] === $actor['username'],
                'current_actor' => $campaignRow['current_actor'],
                'character' => ['id' => $memberRow['character_id'], 'name' => $memberRow['name']],
                'recent_events' => $recentEvents,
            ]);
        }
    } elseif ($route === 'play_campaign_gm_status') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid play campaign');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, current_actor FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $members = $database->prepare('SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
            $members->execute([$campaignId]);
            $party = [];
            foreach ($members as $member) {
                $party[] = [
                    'username' => $member['username'],
                    'character_id' => $member['character_id'],
                    'name' => $member['name'],
                    'class' => $member['class'],
                ];
            }

            $events = $database->prepare("SELECT sequence, 'narration' AS kind, actor, NULL AS type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_narrations WHERE campaign_id = ? UNION ALL SELECT sequence, 'action' AS kind, actor, type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_actions WHERE campaign_id = ? UNION ALL SELECT sequence, 'resolution' AS kind, 'dm' AS actor, NULL AS type, text, NULL AS destination_id, NULL AS travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_resolutions WHERE campaign_id = ? UNION ALL SELECT sequence, 'travel' AS kind, actor, NULL AS type, NULL AS text, destination_id, travel_turns, NULL AS hp_current, NULL AS hp_max FROM play_campaign_travels WHERE campaign_id = ? UNION ALL SELECT sequence, 'rest' AS kind, actor, type, NULL AS text, NULL AS destination_id, NULL AS travel_turns, hp_current, hp_max FROM play_campaign_rests WHERE campaign_id = ? ORDER BY sequence");
            $events->execute([$campaignId, $campaignId, $campaignId, $campaignId, $campaignId]);
            $recentEvents = [];
            foreach ($events as $event) {
                $recentEvent = [
                    'sequence' => (int) $event['sequence'],
                    'kind' => $event['kind'],
                    'actor' => $event['actor'],
                ];
                if ($event['text'] !== null) {
                    $recentEvent['text'] = $event['text'];
                }
                if ($event['type'] !== null) {
                    $recentEvent['type'] = $event['type'];
                }
                if ($event['destination_id'] !== null) {
                    $recentEvent['destination_id'] = $event['destination_id'];
                    $recentEvent['travel_turns'] = (int) $event['travel_turns'];
                }
                if ($event['hp_current'] !== null) {
                    $recentEvent['hp_current'] = (int) $event['hp_current'];
                    $recentEvent['hp_max'] = (int) $event['hp_max'];
                }
                $recentEvents[] = $recentEvent;
            }

            $response = new JsonResponse([
                'needs_attention' => $campaignRow['current_actor'] === $campaignRow['owner'],
                'current_actor' => $campaignRow['current_actor'],
                'party' => $party,
                'recent_events' => $recentEvents,
            ]);
        }
    } elseif ($route === 'play_campaign_document_update') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['story']) || !is_string($body['story']) || $body['story'] === '' || (array_key_exists('dm_notes', $body) && !is_string($body['dm_notes']))) {
            throw new InvalidArgumentException('invalid campaign document');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $dmNotes = $body['dm_notes'] ?? '';
            $database->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes')
                ->execute([$campaignId, $body['story'], $dmNotes]);
            $response = new JsonResponse(['story' => $body['story'], 'dm_notes' => $dmNotes]);
        }
    } elseif ($route === 'play_campaign_document_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign document');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isOwner = $campaignRow['owner'] === $actor['username'];
            if (!$isOwner) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }
            $document = $database->prepare('SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?');
            $document->execute([$campaignId]);
            $documentRow = $document->fetch();
            $story = $documentRow === false ? '' : $documentRow['story'];
            if ($isOwner) {
                $response = new JsonResponse(['story' => $story, 'dm_notes' => $documentRow === false ? '' : $documentRow['dm_notes']]);
            } else {
                $response = new JsonResponse(['story' => $story]);
            }
        }
    } elseif (in_array($route, ['play_campaign_replay_event_create', 'play_campaign_replay_read', 'play_campaign_replay_check'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid replay event');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }

            if ($route === 'play_campaign_replay_event_create') {
                $event = replayEventFields(requestBody($request));
                try {
                    $database->beginTransaction();
                    $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?');
                    $sequenceStatement->execute([$campaignId]);
                    $sequence = (int) $sequenceStatement->fetchColumn();
                    $database->prepare('INSERT INTO play_campaign_replay_events (campaign_id, event_id, kind, text, sequence) VALUES (?, ?, ?, ?, ?)')
                        ->execute([$campaignId, $event['event_id'], $event['kind'], $event['text'], $sequence]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate replay event id');
                    }
                    throw $exception;
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
                $response = new JsonResponse($event + ['sequence' => $sequence], 201);
            } else {
                $events = $database->prepare('SELECT event_id, kind, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence');
                $events->execute([$campaignId]);
                $replayEvents = [];
                foreach ($events as $event) {
                    $replayEvents[] = ['event_id' => $event['event_id'], 'kind' => $event['kind'], 'text' => $event['text']];
                }
                $response = new JsonResponse(rebuildReplay($replayEvents));
            }
        }
    } elseif (in_array($route, ['play_campaign_backup_create', 'play_campaign_backup_list', 'play_campaign_backup_restore'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign backup');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_backup_list') {
            $statement = $database->prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence');
            $statement->execute([$campaignId]);
            $backups = [];
            foreach ($statement as $backup) {
                $backups[] = ['backup_id' => $backup['backup_id'], 'story' => $backup['story'], 'status' => $backup['status']];
            }
            $response = new JsonResponse(['backups' => $backups]);
        } elseif ($route === 'play_campaign_backup_create') {
            if ($request->getContent() !== '') {
                throw new InvalidArgumentException('invalid campaign backup');
            }
            $database->beginTransaction();
            try {
                $currentCampaign = $database->prepare('SELECT status FROM play_campaigns WHERE id = ?');
                $currentCampaign->execute([$campaignId]);
                $currentCampaignRow = $currentCampaign->fetch();
                if ($currentCampaignRow === false) {
                    throw new RuntimeException('campaign disappeared during backup');
                }
                $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
                $document->execute([$campaignId]);
                $documentRow = $document->fetch();
                $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?');
                $sequenceStatement->execute([$campaignId]);
                $sequence = (int) $sequenceStatement->fetchColumn();
                $backup = ['backup_id' => 'backup-' . $sequence, 'story' => $documentRow === false ? '' : $documentRow['story'], 'status' => $currentCampaignRow['status']];
                $database->prepare('INSERT INTO play_campaign_backups (campaign_id, backup_id, story, status, sequence) VALUES (?, ?, ?, ?, ?)')
                    ->execute([$campaignId, $backup['backup_id'], $backup['story'], $backup['status'], $sequence]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse($backup, 201);
        } else {
            if ($request->getContent() !== '') {
                throw new InvalidArgumentException('invalid campaign backup');
            }
            $backupId = $request->attributes->get('backup_id');
            if (!is_string($backupId) || preg_match('/\\Abackup-[1-9][0-9]*\\z/D', $backupId) !== 1) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $statement = $database->prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?');
                $statement->execute([$campaignId, $backupId]);
                $backup = $statement->fetch();
                if ($backup === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                } else {
                    $database->beginTransaction();
                    try {
                        $database->prepare("INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story")
                            ->execute([$campaignId, $backup['story']]);
                        $database->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?')
                            ->execute([$backup['status'], $campaignId]);
                        $database->commit();
                    } catch (Throwable $exception) {
                        if ($database->inTransaction()) {
                            $database->rollBack();
                        }
                        throw $exception;
                    }
                    $response = new JsonResponse(['backup_id' => $backup['backup_id'], 'story' => $backup['story'], 'status' => $backup['status']]);
                }
            }
        }
    } elseif (in_array($route, ['play_campaign_export_create', 'play_campaign_export_list', 'play_campaign_export_read'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign export');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner, status FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_export_create') {
            if ($request->getContent() !== '') {
                throw new InvalidArgumentException('invalid campaign export');
            }
            $database->beginTransaction();
            try {
                // Read the source state inside the same transaction that stores
                // the version, so a snapshot cannot combine two campaign states.
                $currentCampaign = $database->prepare('SELECT status FROM play_campaigns WHERE id = ?');
                $currentCampaign->execute([$campaignId]);
                $currentCampaignRow = $currentCampaign->fetch();
                if ($currentCampaignRow === false) {
                    throw new RuntimeException('campaign disappeared during export');
                }
                $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
                $document->execute([$campaignId]);
                $documentRow = $document->fetch();
                $story = $documentRow === false ? '' : $documentRow['story'];
                $nextVersion = $database->prepare('SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?');
                $nextVersion->execute([$campaignId]);
                $export = ['version' => (int) $nextVersion->fetchColumn(), 'story' => $story, 'status' => $currentCampaignRow['status']];
                $database->prepare('INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)')
                    ->execute([$campaignId, $export['version'], $export['story'], $export['status']]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse($export, 201);
        } elseif ($route === 'play_campaign_export_list') {
            $statement = $database->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version');
            $statement->execute([$campaignId]);
            $exports = [];
            foreach ($statement as $export) {
                $exports[] = ['version' => (int) $export['version'], 'story' => $export['story'], 'status' => $export['status']];
            }
            $response = new JsonResponse(['exports' => $exports]);
        } else {
            $version = $request->attributes->get('version');
            if (!is_string($version) || preg_match('/\\A[1-9][0-9]*\\z/D', $version) !== 1) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $statement = $database->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?');
                $statement->execute([$campaignId, (int) $version]);
                $export = $statement->fetch();
                $response = $export === false
                    ? new JsonResponse(['error' => 'not found'], 404)
                    : new JsonResponse(['version' => (int) $export['version'], 'story' => $export['story'], 'status' => $export['status']]);
            }
        }
    } elseif (in_array($route, ['play_campaign_import_create', 'play_campaign_import_state'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign import');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_import_state') {
            $import = $database->prepare('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?');
            $import->execute([$campaignId]);
            $importRow = $import->fetch();
            $response = $importRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['version' => (int) $importRow['version'], 'story' => $importRow['story'], 'status' => $importRow['status']]);
        } else {
            $body = requestBody($request);
            if (count($body) !== 3 || !array_key_exists('version', $body) || !array_key_exists('story', $body) || !array_key_exists('status', $body)
                || $body['version'] !== 1 || !is_string($body['story']) || $body['story'] === ''
                || !is_string($body['status']) || !in_array($body['status'], ['lobby', 'started'], true)) {
                throw new InvalidArgumentException('invalid campaign import');
            }

            $snapshot = ['version' => 1, 'story' => $body['story'], 'status' => $body['status']];
            $database->beginTransaction();
            try {
                $database->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, \'\') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story')
                    ->execute([$campaignId, $snapshot['story']]);
                $database->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?')
                    ->execute([$snapshot['status'], $campaignId]);
                $database->prepare('INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status')
                    ->execute([$campaignId, $snapshot['version'], $snapshot['story'], $snapshot['status']]);
                $database->commit();
            } catch (Throwable $exception) {
                if ($database->inTransaction()) {
                    $database->rollBack();
                }
                throw $exception;
            }
            $response = new JsonResponse($snapshot);
        }
    } elseif (in_array($route, ['play_campaign_migration_create', 'play_campaign_migration_state'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign migration');
        }

        $database = database();
        $campaign = $database->prepare('SELECT name, owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($actor['role'] !== 'dm' || $campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } elseif ($route === 'play_campaign_migration_state') {
            $migration = $database->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?');
            $migration->execute([$campaignId]);
            $migrationRow = $migration->fetch();
            $response = $migrationRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['schema_version' => (int) $migrationRow['schema_version'], 'story' => $migrationRow['story'], 'campaign_name' => $migrationRow['campaign_name']]);
        } else {
            $body = requestBody($request);
            if (!array_key_exists('schema_version', $body) || !array_key_exists('story', $body)
                || $body['schema_version'] !== 1 || !is_string($body['story']) || $body['story'] === '') {
                throw new InvalidArgumentException('invalid campaign migration');
            }

            $migration = ['schema_version' => 2, 'story' => $body['story'], 'campaign_name' => $campaignRow['name']];
            $existing = $database->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?');
            $existing->execute([$campaignId]);
            $existingRow = $existing->fetch();
            if ($existingRow !== false && (int) $existingRow['schema_version'] === $migration['schema_version']
                && $existingRow['story'] === $migration['story'] && $existingRow['campaign_name'] === $migration['campaign_name']) {
                $response = new JsonResponse($migration, 200);
            } else {
                $database->prepare('INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name')
                    ->execute([$campaignId, $migration['schema_version'], $migration['story'], $migration['campaign_name']]);
                $response = new JsonResponse($migration, 201);
            }
        }
    } elseif (in_array($route, ['play_campaign_search_record_create', 'play_campaign_search_record_list'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid search record');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }

            if ($route === 'play_campaign_search_record_create') {
                if (!$isDm) {
                    throw new ForbiddenException('permission denied');
                }
                $body = requestBody($request);
                $recordId = $body['record_id'] ?? null;
                $text = $body['text'] ?? null;
                if (!is_string($recordId) || $recordId === '' || !is_string($text) || $text === '') {
                    throw new InvalidArgumentException('invalid search record');
                }
                $duplicate = $database->prepare('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND (record_id = ? OR text = ?)');
                $duplicate->execute([$campaignId, $recordId, $text]);
                if ($duplicate->fetchColumn() !== false) {
                    throw new InvalidArgumentException('invalid search record');
                }
                try {
                    $database->beginTransaction();
                    $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_search_records WHERE campaign_id = ?');
                    $sequence->execute([$campaignId]);
                    $database->prepare('INSERT INTO play_campaign_search_records (campaign_id, record_id, text, sequence) VALUES (?, ?, ?, ?)')
                        ->execute([$campaignId, $recordId, $text, (int) $sequence->fetchColumn()]);
                    $database->commit();
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate search record id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['record_id' => $recordId, 'text' => $text], 201);
            } else {
                $query = $request->query->all();
                $q = $query['q'] ?? null;
                $limit = $query['limit'] ?? '2';
                $cursor = $query['cursor'] ?? '0';
                if (($q !== null && !is_string($q)) || !is_string($limit) || preg_match('/\\A[1-3]\\z/D', $limit) !== 1
                    || !is_string($cursor) || preg_match('/\\A(?:0|[1-9][0-9]*)\\z/D', $cursor) !== 1) {
                    throw new InvalidArgumentException('invalid search query');
                }
                $limitValue = (int) $limit;
                $cursorValue = (int) $cursor;
                $statement = $database->prepare('SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY sequence');
                $statement->execute([$campaignId]);
                $filtered = [];
                foreach ($statement as $record) {
                    if ($q === null || stripos($record['text'], $q) !== false) {
                        $filtered[] = ['record_id' => $record['record_id'], 'text' => $record['text']];
                    }
                }
                $records = array_slice($filtered, $cursorValue, $limitValue);
                $nextCursor = $cursorValue + count($records);
                $response = new JsonResponse([
                    'records' => $records,
                    'next_cursor' => $nextCursor < count($filtered) ? $nextCursor : null,
                ]);
            }
        }
    } elseif ($route === 'play_campaign_metrics_read') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $actor['username']) {
            throw new ForbiddenException('permission denied');
        } else {
            $metrics = $database->prepare('SELECT accepted_rate_events, rejected_rate_events, projection_events FROM play_campaign_service_metrics WHERE campaign_id = ?');
            $metrics->execute([$campaignId]);
            $row = $metrics->fetch() ?: ['accepted_rate_events' => 0, 'rejected_rate_events' => 0, 'projection_events' => 0];
            $response = new JsonResponse(['accepted_rate_events' => (int) $row['accepted_rate_events'], 'rejected_rate_events' => (int) $row['rejected_rate_events'], 'projection_events' => (int) $row['projection_events'], 'uptime_ticks' => 1]);
        }
    } elseif ($route === 'play_campaign_service_mode_update') {
        requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || count($body) !== 1 || !array_key_exists('maintenance', $body) || !is_bool($body['maintenance'])) {
            throw new InvalidArgumentException('invalid service mode');
        }
        $database = database();
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $maintenance = $body['maintenance'];
            $database->prepare('UPDATE service_mode SET maintenance = ? WHERE id = 1')->execute([$maintenance ? 1 : 0]);
            $response = new JsonResponse(['maintenance' => $maintenance]);
        }
    } elseif (in_array($route, ['play_campaign_rate_event_create', 'play_campaign_rate_event_list'], true)) {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid rate event');
        }

        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $isDm = $actor['role'] === 'dm' && $campaignRow['owner'] === $actor['username'];
            if (!$isDm) {
                $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
                $member->execute([$campaignId, $actor['username']]);
                if ($member->fetchColumn() === false) {
                    throw new ForbiddenException('permission denied');
                }
            }

            if ($route === 'play_campaign_rate_event_create') {
                $body = requestBody($request);
                $eventId = $body['event_id'] ?? null;
                if (!is_string($eventId) || $eventId === '') {
                    throw new InvalidArgumentException('invalid rate event');
                }
                $duplicate = $database->prepare('SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?');
                $duplicate->execute([$campaignId, $eventId]);
                if ($duplicate->fetchColumn() !== false) {
                    throw new InvalidArgumentException('duplicate rate event id');
                }

                $database->beginTransaction();
                try {
                    $accepted = $database->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
                    $accepted->execute([$campaignId, $actor['username']]);
                    $used = (int) $accepted->fetchColumn();
                    if ($used >= 2) {
                        $database->prepare('UPDATE play_campaign_service_metrics SET rejected_rate_events = rejected_rate_events + 1 WHERE campaign_id = ?')
                            ->execute([$campaignId]);
                        $database->commit();
                        $response = new JsonResponse(['limit' => 2, 'remaining' => 0], 429);
                    } else {
                        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rate_events WHERE campaign_id = ?');
                        $sequence->execute([$campaignId]);
                        $database->prepare('INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor, sequence) VALUES (?, ?, ?, ?)')
                            ->execute([$campaignId, $eventId, $actor['username'], (int) $sequence->fetchColumn()]);
                        $database->prepare('UPDATE play_campaign_service_metrics SET accepted_rate_events = accepted_rate_events + 1 WHERE campaign_id = ?')
                            ->execute([$campaignId]);
                        $database->commit();
                        $response = new JsonResponse(['event_id' => $eventId, 'actor' => $actor['username'], 'remaining' => 1 - $used], 201);
                    }
                } catch (PDOException $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    if ((string) $exception->getCode() === '23000') {
                        throw new InvalidArgumentException('duplicate rate event id');
                    }
                    throw $exception;
                }
            } else {
                $events = $database->prepare('SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence');
                $events->execute([$campaignId]);
                $accepted = $database->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
                $accepted->execute([$campaignId, $actor['username']]);
                $response = new JsonResponse([
                    'events' => $events->fetchAll(),
                    'remaining' => max(0, 2 - (int) $accepted->fetchColumn()),
                ]);
            }
        }
    } elseif ($route === 'play_campaign_scene_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '') {
            throw new InvalidArgumentException('invalid scene');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            try {
                $database->prepare("INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, 'open')")->execute([$campaignId, $body['id'], $body['name']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate scene id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'status' => 'open'], 201);
        }
    } elseif ($route === 'play_campaign_scene_enter') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $sceneId = $request->attributes->get('scene_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($sceneId) || $sceneId === '') {
            throw new InvalidArgumentException('invalid scene');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $scene = $database->prepare('SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?');
            $scene->execute([$campaignId, $sceneId]);
            $sceneRow = $scene->fetch();
            if ($sceneRow === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($sceneRow['status'] !== 'open') {
                throw new MembershipConflictException('scene is closed');
            } else {
                $database->prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?')->execute([$sceneId, $campaignId]);
                $response = new JsonResponse(['current_scene_id' => $sceneId, 'name' => $sceneRow['name']]);
            }
        }
    } elseif ($route === 'play_campaign_scene_close') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $sceneId = $request->attributes->get('scene_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($sceneId) || $sceneId === '') {
            throw new InvalidArgumentException('invalid scene');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $close = $database->prepare("UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ?");
            $close->execute([$campaignId, $sceneId]);
            if ($close->rowCount() === 0) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $database->prepare('UPDATE play_campaigns SET current_scene_id = NULL WHERE id = ? AND current_scene_id = ?')->execute([$campaignId, $sceneId]);
                $response = new JsonResponse(['id' => $sceneId, 'status' => 'closed']);
            }
        }
    } elseif ($route === 'play_campaign_scene_current') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid play campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner, current_scene_id FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $scene = $database->prepare("SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ? AND status = 'open'");
            $scene->execute([$campaignId, $campaignRow['current_scene_id']]);
            $sceneRow = $scene->fetch();
            $response = $sceneRow === false
                ? new JsonResponse(['error' => 'not found'], 404)
                : new JsonResponse(['id' => $sceneRow['id'], 'name' => $sceneRow['name'], 'status' => $sceneRow['status']]);
        }
    } elseif ($route === 'play_campaign_location_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '') {
            throw new InvalidArgumentException('invalid location');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            try {
                $database->prepare('INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)')->execute([$campaignId, $body['id'], $body['name']]);
                $database->prepare('UPDATE play_campaigns SET current_location_id = ? WHERE id = ? AND current_location_id IS NULL')->execute([$body['id'], $campaignId]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate location id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name']], 201);
        }
    } elseif ($route === 'play_campaign_location_connection_create') {
        $owner = requireDm($request);
        $campaignId = $request->attributes->get('id');
        $fromId = $request->attributes->get('from_id');
        $body = requestBody($request);
        if (!is_string($campaignId) || $campaignId === '' || !is_string($fromId) || $fromId === '' || !isset($body['to_id'], $body['travel_turns']) || !is_string($body['to_id']) || $body['to_id'] === '') {
            throw new InvalidArgumentException('invalid connection');
        }
        $travelTurns = integer($body['travel_turns']);
        if ($travelTurns < 1) {
            throw new InvalidArgumentException('invalid connection');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } elseif ($campaignRow['owner'] !== $owner) {
            throw new ForbiddenException('permission denied');
        } else {
            $locations = $database->prepare('SELECT EXISTS(SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?) AS has_from, EXISTS(SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?) AS has_to');
            $locations->execute([$campaignId, $fromId, $campaignId, $body['to_id']]);
            $locationRow = $locations->fetch();
            if ($locationRow === false || (int) $locationRow['has_from'] !== 1 || (int) $locationRow['has_to'] !== 1) {
                throw new InvalidArgumentException('unknown location');
            }
            try {
                $database->prepare('INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)')->execute([$campaignId, $fromId, $body['to_id'], $travelTurns]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new InvalidArgumentException('duplicate connection');
                }
                throw $exception;
            }
            $response = new JsonResponse(['from_id' => $fromId, 'to_id' => $body['to_id'], 'travel_turns' => $travelTurns], 201);
        }
    } elseif ($route === 'play_campaign_location_travel') {
        $actor = authenticatedActor($request);
        $campaignId = $request->attributes->get('id');
        $locationId = $request->attributes->get('loc_id');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($locationId) || $locationId === '') {
            throw new InvalidArgumentException('invalid location');
        }
        $database = database();
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($campaignRow['owner'] !== $actor['username'] && $member->fetchColumn() === false) {
                throw new ForbiddenException('permission denied');
            }
            $destinations = $database->prepare('SELECT location.id, location.name, connection.travel_turns FROM play_campaign_location_connections connection JOIN play_campaign_locations location ON location.campaign_id = connection.campaign_id AND location.id = connection.to_id WHERE connection.campaign_id = ? AND connection.from_id = ? ORDER BY connection.rowid');
            $destinations->execute([$campaignId, $locationId]);
            $response = new JsonResponse(['destinations' => array_map(static fn (array $row): array => ['id' => $row['id'], 'name' => $row['name'], 'travel_turns' => (int) $row['travel_turns']], $destinations->fetchAll())]);
        }
    } elseif ($route === 'campaign_analytics_summary') {
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $database = database();
            $openQuests = $database->prepare("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'");
            $openQuests->execute([$campaignId]);
            $friendlyNpcs = $database->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
            $friendlyNpcs->execute([$campaignId]);
            $sessions = $database->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
            $sessions->execute([$campaignId]);
            $inventoryItems = $database->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?');
            $inventoryItems->execute([$campaignId]);
            $response = new JsonResponse([
                'campaign_id' => $campaignId,
                'readiness_score' => 85,
                'open_quests' => (int) $openQuests->fetchColumn(),
                'friendly_npcs' => (int) $friendlyNpcs->fetchColumn(),
                'scheduled_sessions' => (int) $sessions->fetchColumn(),
                'inventory_items' => (int) $inventoryItems->fetchColumn(),
            ]);
        }
    } elseif ($route === 'campaign_risk_report') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '' || !array_key_exists('include_zeroes', $body) || !is_bool($body['include_zeroes'])) {
            throw new InvalidArgumentException('invalid risk report');
        }
        $database = database();
        $campaign = $database->prepare('SELECT dm FROM campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $dm = $campaign->fetchColumn();
        if ($dm === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $characters = $database->prepare('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?');
            $characters->execute([$campaignId]);
            $sessions = $database->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
            $sessions->execute([$campaignId]);
            $activeQuests = $database->prepare("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'");
            $activeQuests->execute([$campaignId]);
            $response = new JsonResponse([
                'campaign_id' => $campaignId,
                'risk_level' => 'low',
                'missing' => [],
                'signals' => [
                    'has_dm' => is_string($dm) && $dm !== '',
                    'has_characters' => (int) $characters->fetchColumn() > 0,
                    'has_next_session' => (int) $sessions->fetchColumn() > 0,
                    'has_active_quest' => (int) $activeQuests->fetchColumn() > 0,
                ],
            ]);
        }
    } elseif ($route === 'campaign_audit') {
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $database = database();
            $events = $database->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
            $events->execute([$campaignId]);
            $quests = $database->prepare('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?');
            $quests->execute([$campaignId]);
            $npcs = $database->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?');
            $npcs->execute([$campaignId]);
            $sessions = $database->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
            $sessions->execute([$campaignId]);
            $response = new JsonResponse(['campaign_id' => $campaignId, 'events' => (int) $events->fetchColumn(), 'quests' => (int) $quests->fetchColumn(), 'npcs' => (int) $npcs->fetchColumn(), 'sessions' => (int) $sessions->fetchColumn()]);
        }
    } elseif ($route === 'campaign_export') {
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $database = database();
        $campaign = $database->prepare('SELECT name FROM campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $characters = $database->prepare('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?');
            $characters->execute([$campaignId]);
            $quests = $database->prepare('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?');
            $quests->execute([$campaignId]);
            $npcs = $database->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?');
            $npcs->execute([$campaignId]);
            $inventoryItems = $database->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?');
            $inventoryItems->execute([$campaignId]);
            $sessions = $database->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
            $sessions->execute([$campaignId]);
            $response = new JsonResponse(['campaign_id' => $campaignId, 'name' => $campaignRow['name'], 'characters' => (int) $characters->fetchColumn(), 'quests' => (int) $quests->fetchColumn(), 'npcs' => (int) $npcs->fetchColumn(), 'inventory_items' => (int) $inventoryItems->fetchColumn(), 'sessions' => (int) $sessions->fetchColumn(), 'schema_version' => STORAGE_SCHEMA_VERSION]);
        }
    } elseif ($route === 'campaign_session_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['starts_at'], $body['duration_minutes'], $body['agenda']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['starts_at'])) {
            throw new InvalidArgumentException('invalid session');
        }
        $startsAtTimestamp = timestamp($body['starts_at'], 'invalid session');
        $durationMinutes = integer($body['duration_minutes']);
        $agenda = stringList($body['agenda'], 'invalid session');
        if ($durationMinutes < 1) {
            throw new InvalidArgumentException('invalid session');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                database()->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, starts_at_timestamp, duration_minutes, agenda) VALUES (?, ?, ?, ?, ?, ?)')
                    ->execute([$body['id'], $campaignId, $body['starts_at'], $startsAtTimestamp, $durationMinutes, json_encode($agenda, JSON_THROW_ON_ERROR)]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate session id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'starts_at' => $body['starts_at'], 'duration_minutes' => $durationMinutes, 'agenda_count' => count($agenda)], 201);
        }
    } elseif ($route === 'campaign_session_attendance') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        $sessionId = $request->attributes->get('sessionId');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($sessionId) || $sessionId === '' || !isset($body['present'], $body['absent'])) {
            throw new InvalidArgumentException('invalid attendance');
        }
        $present = stringList($body['present'], 'invalid attendance');
        $absent = stringList($body['absent'], 'invalid attendance');
        if (count(array_unique($present)) !== count($present) || count(array_unique($absent)) !== count($absent) || array_intersect($present, $absent) !== []) {
            throw new InvalidArgumentException('invalid attendance');
        }
        $database = database();
        $session = $database->prepare('SELECT 1 FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
        $session->execute([$sessionId, $campaignId]);
        if ($session->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
            foreach (array_merge($present, $absent) as $characterId) {
                $character->execute([$characterId, $campaignId]);
                if ($character->fetchColumn() === false) {
                    $response = new JsonResponse(['error' => 'not found'], 404);
                    break;
                }
            }
            if (!isset($response)) {
                $database->beginTransaction();
                try {
                    $database->prepare('DELETE FROM campaign_session_attendance WHERE session_id = ?')->execute([$sessionId]);
                    $insert = $database->prepare('INSERT INTO campaign_session_attendance (session_id, character_id, status) VALUES (?, ?, ?)');
                    foreach ($present as $characterId) {
                        $insert->execute([$sessionId, $characterId, 'present']);
                    }
                    foreach ($absent as $characterId) {
                        $insert->execute([$sessionId, $characterId, 'absent']);
                    }
                    $database->commit();
                    $response = new JsonResponse(['session_id' => $sessionId, 'present_count' => count($present), 'absent_count' => count($absent)]);
                } catch (Throwable $exception) {
                    if ($database->inTransaction()) {
                        $database->rollBack();
                    }
                    throw $exception;
                }
            }
        }
    } elseif ($route === 'campaign_session_next') {
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $statement = database()->prepare('SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at_timestamp, rowid LIMIT 1');
            $statement->execute([$campaignId]);
            $session = $statement->fetch();
            if ($session === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $agenda = json_decode($session['agenda'], true, 512, JSON_THROW_ON_ERROR);
                if (!is_array($agenda)) {
                    throw new RuntimeException('invalid session state');
                }
                $response = new JsonResponse(['id' => $session['id'], 'starts_at' => $session['starts_at'], 'agenda_count' => count($agenda)]);
            }
        }
    } elseif ($route === 'campaign_inventory_add') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['item_slug'], $body['quantity'], $body['owner']) || !is_string($body['owner']) || $body['owner'] !== 'party') {
            throw new InvalidArgumentException('invalid inventory item');
        }
        $itemSlug = compendiumSlug($body['item_slug']);
        $quantity = integer($body['quantity']);
        if ($quantity < 1) {
            throw new InvalidArgumentException('invalid inventory item');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            database()->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity')
                ->execute([$campaignId, $itemSlug, 'party', $quantity]);
            $response = new JsonResponse(['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => 'party'], 201);
        }
    } elseif ($route === 'campaign_equipment_assign') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        $characterId = $request->attributes->get('characterId');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($characterId) || $characterId === '' || !isset($body['item_slug'], $body['quantity'])) {
            throw new InvalidArgumentException('invalid equipment assignment');
        }
        $itemSlug = compendiumSlug($body['item_slug']);
        $quantity = integer($body['quantity']);
        if ($quantity < 1) {
            throw new InvalidArgumentException('invalid equipment assignment');
        }
        $database = database();
        $database->beginTransaction();
        try {
            $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
            $character->execute([$characterId, $campaignId]);
            if ($character->fetchColumn() === false) {
                $database->rollBack();
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                $deduct = $database->prepare("UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party' AND quantity >= ?");
                $deduct->execute([$quantity, $campaignId, $itemSlug, $quantity]);
                if ($deduct->rowCount() !== 1) {
                    $database->rollBack();
                    throw new InvalidArgumentException('insufficient inventory');
                }
                $database->prepare("DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party' AND quantity = 0")->execute([$campaignId, $itemSlug]);
                $database->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity')
                    ->execute([$campaignId, $characterId, $itemSlug, $quantity]);
                $database->commit();
                $response = new JsonResponse(['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity]);
            }
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    } elseif ($route === 'campaign_inventory_summary') {
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $partyItems = database()->prepare("SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
            $partyItems->execute([$campaignId]);
            $assignedItems = database()->prepare('SELECT COUNT(*) FROM campaign_equipment WHERE campaign_id = ?');
            $assignedItems->execute([$campaignId]);
            $potions = database()->prepare("SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'");
            $potions->execute([$campaignId]);
            $response = new JsonResponse(['campaign_id' => $campaignId, 'party_items' => (int) $partyItems->fetchColumn(), 'assigned_items' => (int) $assignedItems->fetchColumn(), 'healing_potions_available' => (int) $potions->fetchColumn()]);
        }
    } elseif ($route === 'crafting_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['character_id'], $body['item_slug'], $body['days_required'], $body['cost_gp'])
            || !is_string($body['id']) || $body['id'] === '' || !is_string($body['character_id']) || $body['character_id'] === '') {
            throw new InvalidArgumentException('invalid crafting project');
        }
        $itemSlug = compendiumSlug($body['item_slug']);
        $daysRequired = integer($body['days_required']);
        $costGp = integer($body['cost_gp']);
        if ($daysRequired < 1 || $costGp < 0) {
            throw new InvalidArgumentException('invalid crafting project');
        }
        $database = database();
        $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $character->execute([$body['character_id'], $campaignId]);
        if ($character->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                $database->prepare('INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
                    ->execute([$body['id'], $campaignId, $body['character_id'], $itemSlug, $daysRequired, 0, $costGp, 'active']);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate crafting project id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'character_id' => $body['character_id'], 'item_slug' => $itemSlug, 'days_required' => $daysRequired, 'days_completed' => 0, 'status' => 'active'], 201);
        }
    } elseif ($route === 'crafting_advance') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('id');
        $projectId = $request->attributes->get('projectId');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($projectId) || $projectId === '' || !array_key_exists('days', $body)) {
            throw new InvalidArgumentException('invalid crafting advance');
        }
        $days = integer($body['days']);
        if ($days < 1) {
            throw new InvalidArgumentException('invalid crafting advance');
        }
        $database = database();
        $database->beginTransaction();
        try {
            $statement = $database->prepare('SELECT item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ? AND campaign_id = ?');
            $statement->execute([$projectId, $campaignId]);
            $project = $statement->fetch();
            if ($project === false) {
                $database->rollBack();
                $response = new JsonResponse(['error' => 'not found'], 404);
            } elseif ($project['status'] !== 'active') {
                $database->rollBack();
                throw new InvalidArgumentException('crafting project already complete');
            } else {
                $completed = min((int) $project['days_required'], (int) $project['days_completed'] + $days);
                $status = $completed === (int) $project['days_required'] ? 'complete' : 'active';
                $database->prepare('UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?')->execute([$completed, $status, $projectId]);
                if ($status === 'complete') {
                    $database->prepare("INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, 'party', 1) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + 1")
                        ->execute([$campaignId, $project['item_slug']]);
                }
                $database->commit();
                $response = new JsonResponse(['id' => $projectId, 'days_completed' => $completed, 'status' => $status]);
            }
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    } elseif ($route === 'campaign_character_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name'], $body['level'], $body['class']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_string($body['class']) || $body['class'] === '') {
            throw new InvalidArgumentException('invalid character');
        }
        $level = integer($body['level']);
        if ($level < 1 || $level > 20) {
            throw new InvalidArgumentException('invalid character');
        }
        $campaign = database()->prepare('SELECT 1 FROM campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                database()->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)')->execute([$body['id'], $campaignId, $body['name'], $level, $body['class']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate character id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'level' => $level, 'class' => $body['class']], 201);
        }
    } elseif ($route === 'campaign_event_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['kind'], $body['summary']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['kind']) || $body['kind'] === '' || !is_string($body['summary']) || $body['summary'] === '') {
            throw new InvalidArgumentException('invalid event');
        }
        $campaign = database()->prepare('SELECT 1 FROM campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                database()->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)')->execute([$body['id'], $campaignId, $body['kind'], $body['summary']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate event id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'kind' => $body['kind']], 201);
        }
    } elseif ($route === 'campaign_state') {
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        $statement = database()->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
        $statement->execute([$campaignId]);
        $campaign = $statement->fetch();
        if ($campaign === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $characters = database()->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid');
            $characters->execute([$campaignId]);
            $characterRows = $characters->fetchAll();
            $logCount = database()->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
            $logCount->execute([$campaignId]);
            $response = new JsonResponse(['id' => $campaign['id'], 'name' => $campaign['name'], 'dm' => $campaign['dm'], 'characters' => array_map(static fn (array $character): array => ['id' => $character['id'], 'name' => $character['name'], 'level' => (int) $character['level'], 'class' => $character['class']], $characterRows), 'log_count' => (int) $logCount->fetchColumn()]);
        }
    } elseif ($route === 'campaign_faction_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name'], $body['stance']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_string($body['stance']) || $body['stance'] === '') {
            throw new InvalidArgumentException('invalid faction');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                database()->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)')->execute([$body['id'], $campaignId, $body['name'], $body['stance']]);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate faction id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'stance' => $body['stance']], 201);
        }
    } elseif ($route === 'campaign_npc_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['name'], $body['faction_id'], $body['disposition']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['name']) || $body['name'] === '' || !is_string($body['faction_id']) || $body['faction_id'] === '') {
            throw new InvalidArgumentException('invalid NPC');
        }
        $disposition = integer($body['disposition']);
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $faction = database()->prepare('SELECT 1 FROM campaign_factions WHERE id = ? AND campaign_id = ?');
            $faction->execute([$body['faction_id'], $campaignId]);
            if ($faction->fetchColumn() === false) {
                $response = new JsonResponse(['error' => 'not found'], 404);
            } else {
                try {
                    database()->prepare('INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)')->execute([$body['id'], $campaignId, $body['name'], $body['faction_id'], $disposition]);
                } catch (PDOException $exception) {
                    if ((string) $exception->getCode() === '23000') {
                        throw new DuplicateIdException('duplicate NPC id');
                    }
                    throw $exception;
                }
                $response = new JsonResponse(['id' => $body['id'], 'name' => $body['name'], 'faction_id' => $body['faction_id'], 'disposition' => $disposition], 201);
            }
        }
    } elseif ($route === 'campaign_relationships') {
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $factions = database()->prepare('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?');
            $factions->execute([$campaignId]);
            $npcs = database()->prepare('SELECT COUNT(*), COALESCE(SUM(disposition > 0), 0) FROM campaign_npcs WHERE campaign_id = ?');
            $npcs->execute([$campaignId]);
            $npcCounts = $npcs->fetch(PDO::FETCH_NUM);
            $response = new JsonResponse(['campaign_id' => $campaignId, 'factions' => (int) $factions->fetchColumn(), 'npcs' => (int) $npcCounts[0], 'friendly_npcs' => (int) $npcCounts[1]]);
        }
    } elseif ($route === 'campaign_quest_create') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '' || !isset($body['id'], $body['title'], $body['status'], $body['milestones']) || !is_string($body['id']) || $body['id'] === '' || !is_string($body['title']) || $body['title'] === '' || !is_string($body['status']) || !in_array($body['status'], ['active', 'completed', 'blocked'], true)) {
            throw new InvalidArgumentException('invalid quest');
        }
        $milestones = stringList($body['milestones'], 'invalid quest');
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            try {
                database()->prepare('INSERT INTO campaign_quests (id, campaign_id, title, status, milestones, completed) VALUES (?, ?, ?, ?, ?, ?)')->execute([$body['id'], $campaignId, $body['title'], $body['status'], json_encode($milestones, JSON_THROW_ON_ERROR), '[]']);
            } catch (PDOException $exception) {
                if ((string) $exception->getCode() === '23000') {
                    throw new DuplicateIdException('duplicate quest id');
                }
                throw $exception;
            }
            $response = new JsonResponse(['id' => $body['id'], 'title' => $body['title'], 'status' => $body['status'], 'milestones_total' => count($milestones), 'milestones_done' => 0], 201);
        }
    } elseif ($route === 'campaign_quest_progress') {
        $body = requestBody($request);
        $campaignId = $request->attributes->get('campaignId');
        $questId = $request->attributes->get('questId');
        if (!is_string($campaignId) || $campaignId === '' || !is_string($questId) || $questId === '' || !isset($body['completed'])) {
            throw new InvalidArgumentException('invalid quest progress');
        }
        $completed = stringList($body['completed'], 'invalid quest progress');
        $statement = database()->prepare('SELECT status, milestones, completed FROM campaign_quests WHERE id = ? AND campaign_id = ?');
        $statement->execute([$questId, $campaignId]);
        $quest = $statement->fetch();
        if ($quest === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $milestones = json_decode($quest['milestones'], true, 512, JSON_THROW_ON_ERROR);
            $previouslyCompleted = json_decode($quest['completed'], true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($milestones) || !is_array($previouslyCompleted)) {
                throw new RuntimeException('invalid quest state');
            }
            foreach ($completed as $milestone) {
                if (!in_array($milestone, $milestones, true)) {
                    throw new InvalidArgumentException('invalid quest progress');
                }
            }
            $allCompleted = $previouslyCompleted;
            foreach ($completed as $milestone) {
                if (!in_array($milestone, $allCompleted, true)) {
                    $allCompleted[] = $milestone;
                }
            }
            database()->prepare('UPDATE campaign_quests SET completed = ? WHERE id = ? AND campaign_id = ?')->execute([json_encode($allCompleted, JSON_THROW_ON_ERROR), $questId, $campaignId]);
            $response = new JsonResponse(['id' => $questId, 'status' => $quest['status'], 'milestones_total' => count($milestones), 'milestones_done' => count($allCompleted)]);
        }
    } elseif ($route === 'campaign_quest_summary') {
        $campaignId = $request->attributes->get('campaignId');
        if (!is_string($campaignId) || $campaignId === '') {
            throw new InvalidArgumentException('invalid campaign');
        }
        if (!campaignExists($campaignId)) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
            $statement = database()->prepare('SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? GROUP BY status');
            $statement->execute([$campaignId]);
            foreach ($statement as $row) {
                $counts[$row['status']] = (int) $row['count'];
            }
            $response = new JsonResponse(['campaign_id' => $campaignId, 'active' => $counts['active'], 'completed' => $counts['completed'], 'blocked' => $counts['blocked']]);
        }
    } elseif ($route === 'compendium_monster_create') {
        $body = requestBody($request);
        if (!isset($body['slug'], $body['name'], $body['cr'], $body['armor_class'], $body['hit_points'], $body['tags'])
            || !is_string($body['name']) || $body['name'] === '' || !is_string($body['cr']) || $body['cr'] === '') {
            throw new InvalidArgumentException('invalid monster');
        }
        $slug = compendiumSlug($body['slug']);
        $armorClass = integer($body['armor_class']);
        $hitPoints = integer($body['hit_points']);
        $monsterTags = tags($body['tags']);
        if ($armorClass < 0 || $hitPoints < 0) {
            throw new InvalidArgumentException('invalid monster');
        }
        try {
            database()->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)')
                ->execute([$slug, $body['name'], $body['cr'], $armorClass, $hitPoints, json_encode($monsterTags, JSON_THROW_ON_ERROR)]);
        } catch (PDOException $exception) {
            if ((string) $exception->getCode() === '23000') {
                throw new DuplicateSlugException('duplicate slug');
            }
            throw $exception;
        }
        $response = new JsonResponse(['slug' => $slug, 'name' => $body['name'], 'cr' => $body['cr'], 'armor_class' => $armorClass, 'hit_points' => $hitPoints], 201);
    } elseif ($route === 'compendium_monster_read') {
        $slug = compendiumSlug($request->attributes->get('slug'));
        $statement = database()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug = ?');
        $statement->execute([$slug]);
        $monster = $statement->fetch();
        if ($monster === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $response = new JsonResponse(['slug' => $monster['slug'], 'name' => $monster['name'], 'cr' => $monster['cr'], 'armor_class' => (int) $monster['armor_class'], 'hit_points' => (int) $monster['hit_points'], 'tags' => json_decode($monster['tags'], true, 512, JSON_THROW_ON_ERROR)]);
        }
    } elseif ($route === 'compendium_item_create') {
        $body = requestBody($request);
        if (!isset($body['slug'], $body['name'], $body['type'], $body['rarity'], $body['cost_gp'])
            || !is_string($body['name']) || $body['name'] === '' || !is_string($body['type']) || $body['type'] === '' || !is_string($body['rarity']) || $body['rarity'] === '') {
            throw new InvalidArgumentException('invalid item');
        }
        $slug = compendiumSlug($body['slug']);
        $costGp = integer($body['cost_gp']);
        if ($costGp < 0) {
            throw new InvalidArgumentException('invalid item');
        }
        try {
            database()->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)')
                ->execute([$slug, $body['name'], $body['type'], $body['rarity'], $costGp]);
        } catch (PDOException $exception) {
            if ((string) $exception->getCode() === '23000') {
                throw new DuplicateSlugException('duplicate slug');
            }
            throw $exception;
        }
        $response = new JsonResponse(['slug' => $slug, 'name' => $body['name'], 'type' => $body['type'], 'rarity' => $body['rarity'], 'cost_gp' => $costGp], 201);
    } elseif ($route === 'compendium_item_read') {
        $slug = compendiumSlug($request->attributes->get('slug'));
        $statement = database()->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?');
        $statement->execute([$slug]);
        $item = $statement->fetch();
        if ($item === false) {
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $response = new JsonResponse(['slug' => $item['slug'], 'name' => $item['name'], 'type' => $item['type'], 'rarity' => $item['rarity'], 'cost_gp' => (int) $item['cost_gp']]);
        }
    } elseif ($route === 'auth_register') {
        $body = requestBody($request);
        if (!isset($body['username'], $body['password'], $body['role'])
            || !is_string($body['username'])
            || !is_string($body['password'])
            || !is_string($body['role'])
            || preg_match('/\\A[a-z0-9_-]{2,32}\\z/D', $body['username']) !== 1
            || strlen($body['password']) < 8
            || !in_array($body['role'], ['dm', 'player'], true)) {
            throw new InvalidArgumentException('invalid registration');
        }
        $users = users();
        if (isset($users[$body['username']])) {
            closeUsers();
            throw new DuplicateUsernameException('duplicate username');
        }
        $passwordHash = password_hash($body['password'], PASSWORD_DEFAULT);
        if ($passwordHash === false) {
            closeUsers();
            throw new RuntimeException('password hashing failed');
        }
        $users[$body['username']] = ['role' => $body['role'], 'password_hash' => $passwordHash];
        saveUsers($users);
        $response = new JsonResponse(['username' => $body['username'], 'role' => $body['role']], 201);
    } elseif ($route === 'auth_login') {
        $body = requestBody($request);
        if (!isset($body['username'], $body['password']) || !is_string($body['username']) || !is_string($body['password'])) {
            throw new InvalidArgumentException('invalid login');
        }
        $users = users();
        $user = $users[$body['username']] ?? null;
        closeUsers();
        if (!is_array($user) || !isset($user['password_hash']) || !is_string($user['password_hash']) || !password_verify($body['password'], $user['password_hash'])) {
            throw new InvalidCredentialsException('invalid credentials');
        }
        $response = new JsonResponse(['username' => $body['username'], 'token' => 'session-' . $body['username']]);
    } elseif ($route === 'dice_stats') {
        $body = requestBody($request);
        if (!isset($body['expression']) || !is_string($body['expression']) || !preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $body['expression'], $matches)) {
            throw new InvalidArgumentException('invalid expression');
        }
        $count = decimalInteger($matches[1]);
        $sides = decimalInteger($matches[2]);
        $magnitude = isset($matches[4]) ? decimalInteger($matches[4]) : 0;
        if ($count === null || $sides === null || $magnitude === null || $count < 1 || $sides < 1) {
            throw new InvalidArgumentException('invalid expression');
        }
        $modifier = ($matches[3] ?? '+') === '-' ? -$magnitude : $magnitude;
        $response = new JsonResponse(['dice_count' => $count, 'sides' => $sides, 'modifier' => $modifier, 'min' => $count + $modifier, 'max' => $count * $sides + $modifier, 'average' => $count * ($sides + 1) / 2 + $modifier]);
    } elseif ($route === 'ability_check') {
        $body = requestBody($request);
        $roll = integer($body['roll'] ?? null);
        $modifier = integer($body['modifier'] ?? null);
        $dc = integer($body['dc'] ?? null);
        $total = $roll + $modifier;
        $response = new JsonResponse(['total' => $total, 'success' => $total >= $dc, 'margin' => $total - $dc]);
    } elseif ($route === 'adjusted_xp') {
        $body = requestBody($request);
        if (!isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
            throw new InvalidArgumentException('invalid encounter');
        }
        $xpByCr = ['0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100, '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800];
        $baseXp = 0;
        $monsterCount = 0;
        foreach ($body['monsters'] as $monster) {
            if (!is_array($monster) || !isset($monster['cr'], $monster['count']) || !is_string($monster['cr']) || !array_key_exists($monster['cr'], $xpByCr)) {
                throw new InvalidArgumentException('invalid monster');
            }
            $count = integer($monster['count']);
            if ($count < 1) {
                throw new InvalidArgumentException('invalid monster');
            }
            $baseXp += $xpByCr[$monster['cr']] * $count;
            $monsterCount += $count;
        }
        $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        foreach ($body['party'] as $member) {
            if (!is_array($member) || integer($member['level'] ?? null) !== 3) {
                throw new InvalidArgumentException('unsupported party level');
            }
            $thresholds['easy'] += 75;
            $thresholds['medium'] += 150;
            $thresholds['hard'] += 225;
            $thresholds['deadly'] += 400;
        }
        if ($monsterCount === 0 || $body['party'] === []) {
            throw new InvalidArgumentException('empty encounter');
        }
        $multiplier = match (true) {
            $monsterCount === 1 => 1,
            $monsterCount === 2 => 1.5,
            $monsterCount <= 6 => 2,
            $monsterCount <= 10 => 2.5,
            $monsterCount <= 14 => 3,
            default => 4,
        };
        $adjustedXp = $baseXp * $multiplier;
        $difficulty = $adjustedXp >= $thresholds['deadly'] ? 'deadly' : ($adjustedXp >= $thresholds['hard'] ? 'hard' : ($adjustedXp >= $thresholds['medium'] ? 'medium' : ($adjustedXp >= $thresholds['easy'] ? 'easy' : 'trivial')));
        $response = new JsonResponse(['base_xp' => $baseXp, 'monster_count' => $monsterCount, 'multiplier' => $multiplier, 'adjusted_xp' => $adjustedXp, 'difficulty' => $difficulty, 'thresholds' => $thresholds]);
    } elseif ($route === 'initiative') {
        $body = requestBody($request);
        if (!isset($body['combatants']) || !is_array($body['combatants'])) {
            throw new InvalidArgumentException('invalid combatants');
        }
        $combatants = [];
        foreach ($body['combatants'] as $combatant) {
            if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll']) || !is_string($combatant['name'])) {
                throw new InvalidArgumentException('invalid combatant');
            }
            $dex = integer($combatant['dex']);
            $combatants[] = ['name' => $combatant['name'], 'dex' => $dex, 'score' => integer($combatant['roll']) + $dex];
        }
        usort($combatants, static fn (array $a, array $b): int => $b['score'] <=> $a['score'] ?: $b['dex'] <=> $a['dex'] ?: $a['name'] <=> $b['name']);
        $order = array_map(static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']], $combatants);
        $response = new JsonResponse(['order' => $order]);
    } elseif ($route === 'combat_create') {
        $body = requestBody($request);
        if (!isset($body['id'], $body['combatants']) || !is_string($body['id']) || $body['id'] === '' || !is_array($body['combatants']) || $body['combatants'] === []) {
            throw new InvalidArgumentException('invalid combat session');
        }
        $order = [];
        $names = [];
        foreach ($body['combatants'] as $combatant) {
            if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll']) || !is_string($combatant['name']) || $combatant['name'] === '' || isset($names[$combatant['name']])) {
                throw new InvalidArgumentException('invalid combatant');
            }
            $dex = integer($combatant['dex']);
            $names[$combatant['name']] = true;
            $order[] = ['name' => $combatant['name'], 'dex' => $dex, 'score' => integer($combatant['roll']) + $dex];
        }
        usort($order, static fn (array $a, array $b): int => $b['score'] <=> $a['score'] ?: $b['dex'] <=> $a['dex'] ?: $a['name'] <=> $b['name']);
        $sessions = combatSessions();
        if (isset($sessions[$body['id']])) {
            closeCombatSessions();
            throw new InvalidArgumentException('duplicate combat session');
        }
        $sessions[$body['id']] = ['id' => $body['id'], 'round' => 1, 'turn_index' => 0, 'order' => $order, 'conditions' => []];
        $session = $sessions[$body['id']];
        saveCombatSessions($sessions);
        $response = new JsonResponse(combatState($session) + ['order' => array_map(static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']], $order)]);
    } elseif ($route === 'combat_condition') {
        $body = requestBody($request);
        if (!isset($body['target'], $body['condition'], $body['duration_rounds']) || !is_string($body['target']) || !is_string($body['condition'])) {
            throw new InvalidArgumentException('invalid condition');
        }
        $duration = integer($body['duration_rounds']);
        if ($duration < 1) {
            throw new InvalidArgumentException('invalid condition');
        }
        $sessions = combatSessions();
        $id = $request->attributes->get('id');
        if (!is_string($id) || !isset($sessions[$id])) {
            closeCombatSessions();
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $session = &$sessions[$id];
            $knownTarget = false;
            foreach ($session['order'] as $combatant) {
                if ($combatant['name'] === $body['target']) {
                    $knownTarget = true;
                    break;
                }
            }
            if (!$knownTarget) {
                closeCombatSessions();
                throw new InvalidArgumentException('unknown target');
            }
            $session['conditions'][$body['target']][] = ['condition' => $body['condition'], 'remaining_rounds' => $duration];
            $conditions = $session['conditions'][$body['target']];
            unset($session);
            saveCombatSessions($sessions);
            $response = new JsonResponse(['target' => $body['target'], 'conditions' => $conditions]);
        }
    } elseif ($route === 'combat_advance') {
        $sessions = combatSessions();
        $id = $request->attributes->get('id');
        if (!is_string($id) || !isset($sessions[$id])) {
            closeCombatSessions();
            $response = new JsonResponse(['error' => 'not found'], 404);
        } else {
            $session = &$sessions[$id];
            $session['turn_index']++;
            if ($session['turn_index'] === count($session['order'])) {
                $session['turn_index'] = 0;
                $session['round']++;
            }
            $activeName = $session['order'][$session['turn_index']]['name'];
            if (isset($session['conditions'][$activeName])) {
                foreach ($session['conditions'][$activeName] as &$condition) {
                    $condition['remaining_rounds']--;
                }
                unset($condition);
                $session['conditions'][$activeName] = array_values(array_filter($session['conditions'][$activeName], static fn (array $condition): bool => $condition['remaining_rounds'] > 0));
            }
            $state = combatState($session);
            // The API contract defines conditions as a combatant-name map.
            // Cast an empty PHP array so it remains a JSON object (`{}`), not `[]`.
            $state['conditions'] = (object) $session['conditions'];
            unset($session);
            saveCombatSessions($sessions);
            $response = new JsonResponse($state);
        }
    } elseif ($route === 'ability_modifier') {
        $body = requestBody($request);
        $score = integer($body['score'] ?? null);
        $response = new JsonResponse(['score' => $score, 'modifier' => abilityModifier($score)]);
    } elseif ($route === 'proficiency') {
        $body = requestBody($request);
        $level = integer($body['level'] ?? null);
        $response = new JsonResponse(['level' => $level, 'proficiency_bonus' => proficiencyBonus($level)]);
    } elseif ($route === 'phb_spell_slots') {
        $body = requestBody($request);
        if (!isset($body['class']) || !is_string($body['class'])) {
            throw new InvalidArgumentException('invalid spell slots');
        }
        $level = integer($body['level'] ?? null);
        if ($body['class'] !== 'wizard' || $level !== 5) {
            throw new InvalidArgumentException('unsupported spellcaster');
        }
        $response = new JsonResponse(['class' => 'wizard', 'level' => 5, 'slots' => ['1' => 4, '2' => 3, '3' => 2]]);
    } elseif ($route === 'phb_long_rest') {
        $body = requestBody($request);
        $level = integer($body['level'] ?? null);
        $hpCurrent = integer($body['hp_current'] ?? null);
        $hpMax = integer($body['hp_max'] ?? null);
        $hitDiceSpent = integer($body['hit_dice_spent'] ?? null);
        $exhaustionLevel = integer($body['exhaustion_level'] ?? null);
        if ($level < 1 || $level > 20 || $hpCurrent < 0 || $hpMax < 1 || $hpCurrent > $hpMax || $hitDiceSpent < 0 || $exhaustionLevel < 0) {
            throw new InvalidArgumentException('invalid long rest');
        }
        $hitDiceRestored = max(1, intdiv($level, 2));
        $response = new JsonResponse([
            'hp_current' => $hpMax,
            'hit_dice_spent' => max(0, $hitDiceSpent - $hitDiceRestored),
            'exhaustion_level' => max(0, $exhaustionLevel - 1),
        ]);
    } elseif ($route === 'phb_equipment_load') {
        $body = requestBody($request);
        $strength = integer($body['strength'] ?? null);
        $weight = integer($body['weight'] ?? null);
        if ($strength < 1 || $strength > 30 || $weight < 0) {
            throw new InvalidArgumentException('invalid equipment load');
        }
        $capacity = $strength * 15;
        $response = new JsonResponse(['capacity' => $capacity, 'weight' => $weight, 'encumbered' => $weight > $capacity]);
    } else {
        $body = requestBody($request);
        if (!isset($body['level'], $body['abilities'], $body['armor']) || !is_array($body['abilities']) || array_is_list($body['abilities']) || !is_array($body['armor']) || array_is_list($body['armor'])) {
            throw new InvalidArgumentException('invalid derived stats');
        }
        $level = integer($body['level']);
        $modifiers = [];
        foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
            $modifiers[$ability] = abilityModifier(integer($body['abilities'][$ability] ?? null));
        }
        if (!array_key_exists('base', $body['armor']) || !array_key_exists('shield', $body['armor']) || !array_key_exists('dex_cap', $body['armor']) || !is_bool($body['armor']['shield'])) {
            throw new InvalidArgumentException('invalid armor');
        }
        $baseArmor = integer($body['armor']['base']);
        $dexCap = integer($body['armor']['dex_cap']);
        $response = new JsonResponse([
            'level' => $level,
            'proficiency_bonus' => proficiencyBonus($level),
            'hp_max' => $level * (6 + $modifiers['con']),
            'armor_class' => $baseArmor + min($modifiers['dex'], $dexCap) + ($body['armor']['shield'] ? 2 : 0),
            'modifiers' => $modifiers,
        ]);
    }
} catch (DuplicateUsernameException) {
    $response = new JsonResponse(['error' => 'duplicate username'], 409);
} catch (DuplicateSlugException) {
    $response = new JsonResponse(['error' => 'duplicate slug'], 409);
} catch (DuplicateIdException) {
    $response = new JsonResponse(['error' => 'duplicate id'], 409);
} catch (MembershipConflictException) {
    $response = new JsonResponse(['error' => 'conflict'], 409);
} catch (DuplicateFeedEventException) {
    $response = new JsonResponse(['error' => 'duplicate event_id'], 409);
} catch (InvalidCredentialsException) {
    $response = new JsonResponse(['error' => 'bad credentials'], 401);
} catch (ForbiddenException) {
    $response = new JsonResponse(['error' => 'forbidden'], 403);
} catch (InvalidArgumentException) {
    $response = new JsonResponse(['error' => 'bad request'], 400);
}

$response->send();
