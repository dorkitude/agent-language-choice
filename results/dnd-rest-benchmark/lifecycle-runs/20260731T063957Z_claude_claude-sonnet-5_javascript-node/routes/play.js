import { sendJson, parseJsonBody } from '../lib/http.js';
import {
  playCampaigns,
  playCampaignMembers,
  playCampaignEvents,
  playCampaignScenes,
  playCampaignLocations,
  playCampaignLocationConnections,
  playCampaignEncounters,
  playCampaignSpells,
  playCampaignCasts,
  playCampaignConcentration,
  playCampaignItems,
  playCampaignEquipment,
  playCampaignCurrency,
  playCampaignTransfers,
  playCampaignTransactionalTransfers,
  playCampaignLoot,
  playCampaignLootVotes,
  playCampaignNpcs,
  playCampaignNpcDialogue,
  playCampaignRelationships,
  playCampaignFactions,
  playCampaignReputation,
  playCampaignClues,
  playCampaignQuests,
  playCampaignCharacterRewards,
  playCampaignWorldEvents,
  playCampaignCalendar,
  playCampaignSettlements,
  playCampaignShops,
  playCampaignRecipes,
  playCampaignDowntimeActivities,
  playCampaignDowntimeAllocations,
  playCampaignSessionZero,
  playCampaignContent,
  playCampaignNotes,
  playCampaignMessages,
  playCampaignWhispers,
  playCampaignInvitations,
  playCampaignDelegations,
  playCampaignDelegationAudit,
  playCampaignAuditEvents,
  playCampaignProjectionEvents,
  playCampaignIdempotentEvents,
  playCampaignIdempotencyKeys,
  playCampaignFeedEvents,
  playCampaignSafeTurnState,
  playCampaignSafeTurns,
  playCampaignExports,
  playCampaignImports,
  playCampaignMigrations,
  playCampaignSearchRecords,
  playCampaignRateEvents,
  playCampaignMetrics,
  playCampaignBackups,
  playCampaignReplayEvents,
  playCampaignRngConfig,
  playCampaignRngRolls,
  playCampaignModerationReports,
  playCampaignSafetyBoundaries,
  playCampaignSafetyEvents,
  playCampaignFixtureSeeds,
  playSpectatorTickets,
  users,
} from '../lib/stores.js';
import { bearerUsername } from '../lib/auth.js';
import { proficiencyBonus } from '../lib/rules.js';
import { setMaintenance } from '../lib/service-mode.js';

const STARTING_GOLD = 10;

const VALID_RACES = new Set([
  'human',
  'elf',
  'dwarf',
  'halfling',
  'dragonborn',
  'gnome',
  'half-elf',
  'half-orc',
  'tiefling',
]);

const VALID_BACKGROUNDS = new Set([
  'acolyte',
  'charlatan',
  'criminal',
  'entertainer',
  'folk hero',
  'guild artisan',
  'hermit',
  'noble',
  'outlander',
  'sage',
  'soldier',
  'urchin',
]);

// Level-1 hit die max by class, per the 5e SRD.
const CLASS_HIT_DIE = {
  barbarian: 12,
  bard: 8,
  cleric: 8,
  druid: 8,
  fighter: 10,
  monk: 8,
  paladin: 10,
  ranger: 10,
  rogue: 8,
  sorcerer: 6,
  warlock: 8,
  wizard: 6,
};

// Minimal SRD spell compendium: spell_id -> canonical name/level and the
// classes that may learn it. Classes with no entry here (e.g. rogue) have no
// spell list at all, so any spell for them is invalid.
const SPELL_COMPENDIUM = {
  'fire-bolt': { name: 'Fire Bolt', level: 0, classes: ['sorcerer', 'wizard'] },
  'mage-hand': { name: 'Mage Hand', level: 0, classes: ['bard', 'sorcerer', 'warlock', 'wizard'] },
  prestidigitation: { name: 'Prestidigitation', level: 0, classes: ['bard', 'sorcerer', 'warlock', 'wizard'] },
  'ray-of-frost': { name: 'Ray of Frost', level: 0, classes: ['sorcerer', 'wizard'] },
  'sacred-flame': { name: 'Sacred Flame', level: 0, classes: ['cleric'] },
  guidance: { name: 'Guidance', level: 0, classes: ['cleric', 'druid'] },
  druidcraft: { name: 'Druidcraft', level: 0, classes: ['druid'] },
  'vicious-mockery': { name: 'Vicious Mockery', level: 0, classes: ['bard'] },
  'eldritch-blast': { name: 'Eldritch Blast', level: 0, classes: ['warlock'] },
  'magic-missile': { name: 'Magic Missile', level: 1, classes: ['sorcerer', 'wizard'] },
  shield: { name: 'Shield', level: 1, classes: ['sorcerer', 'wizard'] },
  'burning-hands': { name: 'Burning Hands', level: 1, classes: ['sorcerer', 'wizard'] },
  'charm-person': { name: 'Charm Person', level: 1, classes: ['bard', 'druid', 'sorcerer', 'warlock', 'wizard'] },
  'cure-wounds': { name: 'Cure Wounds', level: 1, classes: ['bard', 'cleric', 'druid', 'paladin', 'ranger'] },
  bless: { name: 'Bless', level: 1, classes: ['cleric', 'paladin'] },
  command: { name: 'Command', level: 1, classes: ['cleric', 'paladin'] },
  'healing-word': { name: 'Healing Word', level: 1, classes: ['bard', 'cleric', 'druid'] },
  thunderwave: { name: 'Thunderwave', level: 1, classes: ['bard', 'druid', 'sorcerer', 'wizard'] },
  "hunter's-mark": { name: "Hunter's Mark", level: 1, classes: ['ranger'] },
  'faerie-fire': { name: 'Faerie Fire', level: 1, classes: ['druid'] },
  'detect-magic': {
    name: 'Detect Magic',
    level: 1,
    classes: ['bard', 'cleric', 'druid', 'paladin', 'ranger', 'sorcerer', 'wizard'],
  },
};

// Classes that appear anywhere in the spell compendium can cast spells at
// all; classes with no entries (e.g. rogue, fighter) have no spell list.
const SPELLCASTING_CLASSES = new Set(Object.values(SPELL_COMPENDIUM).flatMap((entry) => entry.classes));

// Spell slots by character level, keyed by spell level. Matches the SRD
// numbers already exposed at /v1/phb/spell-slots for wizard level 5; levels
// beyond the table cap at the level-5 row.
const SPELL_SLOT_TABLE = {
  1: { 1: 1 },
  2: { 1: 2 },
  3: { 1: 3 },
  4: { 1: 4 },
  5: { 1: 4, 2: 3, 3: 2 },
};

function maxSpellSlots(characterLevel, spellLevel) {
  const row = SPELL_SLOT_TABLE[characterLevel] || SPELL_SLOT_TABLE[5];
  return row[spellLevel] || 0;
}

// Item catalog for per-character inventory stacks.
const VALID_ITEM_IDS = new Set([
  'healing-potion',
  'torch',
  'leather-armor',
  'ring-of-protection',
  'amulet-of-health',
]);

// Equipment slots and the item(s) legal for each. Only items listed here may
// be equipped; healing-potion/torch have no slot and are never equippable.
const VALID_EQUIPMENT_SLOTS = new Set(['armor', 'accessory']);
const ITEM_EQUIPMENT_SLOT = {
  'leather-armor': 'armor',
  'ring-of-protection': 'accessory',
  'amulet-of-health': 'accessory',
};
const ATTUNABLE_ITEM_IDS = new Set(['ring-of-protection', 'amulet-of-health']);
const MAX_ATTUNEMENTS = 1;

// Items that can be consumed via the consume endpoint, and the effect each
// application produces.
const CONSUMABLE_EFFECTS = {
  'healing-potion': { type: 'healing', hp_restored: 5 },
};

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

const SKILL_ABILITIES = {
  acrobatics: 'dex',
  'animal handling': 'wis',
  arcana: 'int',
  athletics: 'str',
  deception: 'cha',
  history: 'int',
  insight: 'wis',
  intimidation: 'cha',
  investigation: 'int',
  medicine: 'wis',
  nature: 'int',
  perception: 'wis',
  performance: 'cha',
  persuasion: 'cha',
  religion: 'int',
  'sleight of hand': 'dex',
  stealth: 'dex',
  survival: 'wis',
};

function abilityModifier(score) {
  return Math.floor((score - 10) / 2);
}

// Logical (non-wall-clock) turn count that must elapse before a turn is
// considered overdue. Expressed in turn_number units, not real time.
const TURN_TIMEOUT_WINDOW = 1;

// Spectator tickets are bearer tokens of the form `spectator-<id>`, distinct
// from `session-<username>` player/DM tokens so the two can never collide.
const SPECTATOR_TOKEN_RE = /^spectator-(.+)$/;

// Resolves the authenticated actor for a protected /v1/play request.
// Play actors are identified solely by their bearer session token, not by
// the registered-users store: campaign play involves actors (e.g. "dm")
// that need not have gone through /v1/auth/register. Returns
// { username, role } on success, or sends the 401 response and returns
// null when the bearer token is missing or malformed.
function authenticate(req, res) {
  const username = bearerUsername(req);
  if (!username) {
    sendJson(res, 401, { error: 'unauthorized' });
    return null;
  }
  const role = username === 'dm' ? 'dm' : 'player';
  return { username, role };
}

// Loads a play campaign by id, sending 404 and returning null if it
// doesn't exist. Shared by every route below the top-level create/join.
function requireCampaign(res, id) {
  const campaign = playCampaigns.get(id);
  if (!campaign) {
    sendJson(res, 404, { error: 'not found' });
    return null;
  }
  return campaign;
}

function isMember(members, username) {
  return members.some((member) => member.username === username);
}

// Validates a nonempty array of unique, nonempty (non-blank) strings.
// Returns the array unchanged (preserving order) or null on violation.
function normalizeUniqueStringArray(value) {
  if (!Array.isArray(value) || value.length === 0) return null;
  for (const entry of value) {
    if (typeof entry !== 'string' || entry.trim().length === 0) return null;
  }
  if (new Set(value).size !== value.length) return null;
  return value;
}

function emptyMetrics() {
  return { accepted_rate_events: 0, rejected_rate_events: 0, projection_events: 0, uptime_ticks: 1 };
}

function bumpMetric(campaignId, field) {
  const metrics = playCampaignMetrics.get(campaignId) || emptyMetrics();
  metrics[field] += 1;
  playCampaignMetrics.set(campaignId, metrics);
}

const VALID_SETTLEMENT_AVAILABILITY = new Set(['open', 'limited', 'closed']);

// Trims each service, rejects empty/non-string entries, and requires the
// trimmed values to be unique. Returns null on any violation.
function normalizeSettlementServices(services) {
  if (!Array.isArray(services) || services.length === 0) return null;
  const trimmed = [];
  for (const service of services) {
    if (typeof service !== 'string') return null;
    const value = service.trim();
    if (value.length === 0) return null;
    trimmed.push(value);
  }
  if (new Set(trimmed).size !== trimmed.length) return null;
  return trimmed;
}

function filterSettlementForCharacter(settlement, characterId) {
  return {
    settlement_id: settlement.settlement_id,
    name: settlement.name,
    services: settlement.services,
    availability: settlement.availability,
    discovered_by: settlement.discovered_by.includes(characterId) ? [characterId] : [],
  };
}

// Validates a shop create payload against the catalog of valid inventory
// items. Returns a normalized shop record or null on any violation.
function normalizeShopPayload(data) {
  if (!data || typeof data !== 'object') return null;
  const shopId = data.shop_id;
  const name = data.name;
  const stock = data.stock;
  const buyPrice = data.buy_price;
  const sellPrice = data.sell_price;

  if (typeof shopId !== 'string' || shopId.length === 0) return null;
  if (typeof name !== 'string' || name.length === 0) return null;
  if (!stock || typeof stock !== 'object' || Array.isArray(stock)) return null;

  const itemIds = Object.keys(stock);
  if (itemIds.length === 0) return null;
  const normalizedStock = {};
  for (const itemId of itemIds) {
    if (!VALID_ITEM_IDS.has(itemId)) return null;
    const quantity = stock[itemId];
    if (!Number.isInteger(quantity) || quantity <= 0) return null;
    normalizedStock[itemId] = quantity;
  }

  if (!Number.isInteger(buyPrice) || buyPrice <= 0) return null;
  if (!Number.isInteger(sellPrice) || sellPrice < 0) return null;

  return { shop_id: shopId, name, stock: normalizedStock, buy_price: buyPrice, sell_price: sellPrice };
}

// Validates a recipe create payload against the catalog of valid inventory
// items. Returns a normalized recipe record or null on any violation.
function normalizeRecipePayload(data) {
  if (!data || typeof data !== 'object') return null;
  const recipeId = data.recipe_id;
  const name = data.name;
  const ingredients = data.ingredients;
  const outputItem = data.output_item;
  const outputQuantity = data.output_quantity;

  if (typeof recipeId !== 'string' || recipeId.length === 0) return null;
  if (typeof name !== 'string' || name.length === 0) return null;
  if (!ingredients || typeof ingredients !== 'object' || Array.isArray(ingredients)) return null;

  const ingredientIds = Object.keys(ingredients);
  if (ingredientIds.length === 0) return null;
  const normalizedIngredients = {};
  for (const itemId of ingredientIds) {
    if (!VALID_ITEM_IDS.has(itemId)) return null;
    const quantity = ingredients[itemId];
    if (!Number.isInteger(quantity) || quantity <= 0) return null;
    normalizedIngredients[itemId] = quantity;
  }

  if (!VALID_ITEM_IDS.has(outputItem)) return null;
  if (!Number.isInteger(outputQuantity) || outputQuantity <= 0) return null;

  return {
    recipe_id: recipeId,
    name,
    ingredients: normalizedIngredients,
    output_item: outputItem,
    output_quantity: outputQuantity,
  };
}

// Validates a downtime activity create payload. Returns a normalized
// activity record or null on any violation.
function normalizeDowntimeActivityPayload(data) {
  if (!data || typeof data !== 'object') return null;
  const activityId = data.activity_id;
  const name = data.name;
  const cyclesRequired = data.cycles_required;

  if (typeof activityId !== 'string' || activityId.length === 0) return null;
  if (typeof name !== 'string' || name.length === 0) return null;
  if (!Number.isInteger(cyclesRequired) || cyclesRequired < 1 || cyclesRequired > 10) return null;

  return { activity_id: activityId, name, cycles_required: cyclesRequired };
}

const SEASON_OFFSETS = new Map([
  ['spring', 0],
  ['summer', 1],
  ['autumn', 2],
  ['winter', 3],
]);

const WEATHER_BY_OFFSET = ['clear', 'rain', 'wind', 'snow'];

function calendarWeather(day, season) {
  const offset = (day + SEASON_OFFSETS.get(season)) % 4;
  return WEATHER_BY_OFFSET[offset];
}

// A campaign entity is exactly a campaign member's character id or an NPC id
// registered in the campaign, used to validate relationship-graph endpoints.
function isCampaignEntity(campaignId, entityId) {
  const members = playCampaignMembers.listByCampaign(campaignId);
  if (members.some((member) => member.character_id === entityId)) return true;
  return playCampaignNpcs.has(campaignId, entityId);
}

// Deterministic initiative order for an encounter's combatants: highest
// initiative first, ties broken by name so the order never depends on
// insertion order or storage internals.
function initiativeOrder(encounter) {
  const combatants = Array.isArray(encounter.combatants) ? encounter.combatants : [];
  const byTarget = new Map(
    combatants.map((c) => [
      c.monster_id || c.member,
      {
        name: c.name,
        kind: c.monster_id ? 'monster' : 'player',
        initiative: c.initiative,
        member: c.member,
        target: c.monster_id || c.member,
      },
    ])
  );

  // A prior delay/ready action may have pinned an explicit ordering. Reuse
  // it (dropping any targets that no longer exist, appending any that were
  // added since) so a delay is not undone by simply re-deriving the order
  // from initiative scores.
  if (Array.isArray(encounter.turn_order)) {
    const ordered = [];
    for (const target of encounter.turn_order) {
      const entry = byTarget.get(target);
      if (entry) {
        ordered.push(entry);
        byTarget.delete(target);
      }
    }
    const remaining = Array.from(byTarget.values());
    remaining.sort((a, b) => {
      if (b.initiative !== a.initiative) return b.initiative - a.initiative;
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
    return ordered.concat(remaining);
  }

  const ordered = Array.from(byTarget.values());
  ordered.sort((a, b) => {
    if (b.initiative !== a.initiative) return b.initiative - a.initiative;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return ordered;
}

// Appends a play-campaign event, assigning the next sequence number.
// Sequence numbers are per-campaign and derived from the current event
// count, so callers never track them by hand.
function appendEvent(campaignId, fields) {
  const sequence = playCampaignEvents.countByCampaign(campaignId) + 1;
  const record = { sequence, ...fields };
  playCampaignEvents.add(campaignId, record);
  return record;
}

export function registerPlayRoutes(router) {
  router.post('/v1/play/campaigns', async (req, res) => {
    const user = authenticate(req, res);
    if (!user) return;
    if (user.role !== 'dm') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    const maxPlayers = body.data && body.data.max_players;
    if (
      typeof id !== 'string' ||
      id.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      !Number.isInteger(maxPlayers) ||
      maxPlayers < 1
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (playCampaigns.has(id)) {
      sendJson(res, 409, { error: 'campaign already exists' });
      return;
    }

    const record = { id, name, owner: user.username, status: 'lobby', max_players: maxPlayers };
    playCampaigns.set(id, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/members', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;
    if (user.role !== 'player') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const characterId = body.data && body.data.character_id;
    const name = body.data && body.data.name;
    const characterClass = body.data && body.data.class;
    if (
      typeof characterId !== 'string' ||
      characterId.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof characterClass !== 'string' ||
      characterClass.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const alreadyMember = isMember(members, user.username);
    const duplicateCharacter = members.some((member) => member.character_id === characterId);
    if (alreadyMember || duplicateCharacter || members.length >= campaign.max_players) {
      sendJson(res, 409, { error: 'cannot join campaign' });
      return;
    }

    const record = {
      username: user.username,
      character_id: characterId,
      name,
      class: characterClass,
      hp_max: 20,
      hp_current: 20,
      owner: user.username,
    };
    playCampaignMembers.set(params.id, characterId, record);
    playCampaignCurrency.set(params.id, characterId, { character_id: characterId, gold: STARTING_GOLD });
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/spectators', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const spectatorId = body.data && body.data.spectator_id;
    if (typeof spectatorId !== 'string' || spectatorId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playSpectatorTickets.has(spectatorId)) {
      sendJson(res, 409, { error: 'spectator_id already exists' });
      return;
    }

    const token = `spectator-${spectatorId}`;
    playSpectatorTickets.set(spectatorId, { spectator_id: spectatorId, campaign_id: params.id, token });

    sendJson(res, 201, { spectator_id: spectatorId, token });
  });

  router.get('/v1/play/campaigns/:id/spectator-view', async (req, res, params) => {
    const header = req.headers['authorization'];
    const match = typeof header === 'string' ? /^Bearer (.+)$/.exec(header) : null;
    if (!match) {
      sendJson(res, 401, { error: 'unauthorized' });
      return;
    }
    const token = match[1];

    // Normal DM/player session tokens are valid credentials elsewhere, but
    // are never accepted for this spectator-only public projection.
    if (bearerUsername(req)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const spectatorMatch = SPECTATOR_TOKEN_RE.exec(token);
    if (!spectatorMatch) {
      sendJson(res, 401, { error: 'unauthorized' });
      return;
    }
    const spectatorId = spectatorMatch[1];

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const ticket = playSpectatorTickets.get(spectatorId);
    if (!ticket || ticket.token !== token) {
      sendJson(res, 401, { error: 'unauthorized' });
      return;
    }
    if (ticket.campaign_id !== params.id) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const document = campaign.document || { story: '' };
    sendJson(res, 200, {
      campaign_id: campaign.id,
      name: campaign.name,
      status: campaign.status,
      party_size: members.length,
      story: document.story || '',
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:character_id/currency', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    const member = members.find((m) => m.character_id === params.character_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const currency = playCampaignCurrency.get(params.id, params.character_id);
    sendJson(res, 200, { character_id: params.character_id, gold: currency ? currency.gold : 0 });
  });

  router.post(
    '/v1/play/campaigns/:id/characters/:character_id/currency/transfers',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const toCharacterId = body.data && body.data.to_character_id;
      const gold = body.data && body.data.gold;

      const destination = members.find((m) => m.character_id === toCharacterId);
      if (
        typeof toCharacterId !== 'string' ||
        toCharacterId.length === 0 ||
        !destination ||
        toCharacterId === params.character_id ||
        !Number.isInteger(gold) ||
        gold <= 0
      ) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const fromCurrency = playCampaignCurrency.get(params.id, params.character_id);
      const fromGold = fromCurrency ? fromCurrency.gold : 0;
      if (fromGold < gold) {
        sendJson(res, 409, { error: 'insufficient gold' });
        return;
      }

      const toCurrency = playCampaignCurrency.get(params.id, toCharacterId);
      const toGold = toCurrency ? toCurrency.gold : 0;

      const newFromGold = fromGold - gold;
      const newToGold = toGold + gold;
      playCampaignCurrency.set(params.id, params.character_id, {
        character_id: params.character_id,
        gold: newFromGold,
      });
      playCampaignCurrency.set(params.id, toCharacterId, { character_id: toCharacterId, gold: newToGold });

      const transferId = playCampaignTransfers.countByCampaign(params.id) + 1;
      const record = {
        transfer_id: transferId,
        from_character_id: params.character_id,
        to_character_id: toCharacterId,
        gold,
        from_gold: newFromGold,
        to_gold: newToGold,
      };
      playCampaignTransfers.add(params.id, record);

      sendJson(res, 201, record);
    }
  );

  router.post('/v1/play/campaigns/:id/transactional-transfers', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const fromCharacterId = body.data && body.data.from_character_id;
    const toCharacterId = body.data && body.data.to_character_id;
    const amount = body.data && body.data.amount;
    const simulateFailure = body.data ? body.data.simulate_failure === true : false;

    const fromMember = members.find((m) => m.character_id === fromCharacterId);
    const toMember = members.find((m) => m.character_id === toCharacterId);

    if (
      typeof fromCharacterId !== 'string' ||
      fromCharacterId.length === 0 ||
      typeof toCharacterId !== 'string' ||
      toCharacterId.length === 0 ||
      !fromMember ||
      !toMember ||
      fromCharacterId === toCharacterId ||
      !Number.isInteger(amount) ||
      amount <= 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (fromMember.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const fromCurrency = playCampaignCurrency.get(params.id, fromCharacterId);
    const fromGold = fromCurrency ? fromCurrency.gold : 0;
    if (fromGold < amount) {
      sendJson(res, 409, { error: 'insufficient balance' });
      return;
    }

    const toCurrency = playCampaignCurrency.get(params.id, toCharacterId);
    const toGold = toCurrency ? toCurrency.gold : 0;

    // Validation and balance checks are complete and no state has been
    // mutated yet, so a simulated failure can be reported here without
    // leaving any partial debit, credit, or transfer record behind.
    if (simulateFailure) {
      sendJson(res, 500, { error: 'simulated failure' });
      return;
    }

    const newFromGold = fromGold - amount;
    const newToGold = toGold + amount;
    const sequence = playCampaignTransactionalTransfers.countByCampaign(params.id) + 1;
    const record = {
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
      amount,
      from_gold: newFromGold,
      to_gold: newToGold,
      sequence,
    };

    playCampaignCurrency.set(params.id, fromCharacterId, { character_id: fromCharacterId, gold: newFromGold });
    playCampaignCurrency.set(params.id, toCharacterId, { character_id: toCharacterId, gold: newToGold });
    playCampaignTransactionalTransfers.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/transactional-transfers', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const transfers = playCampaignTransactionalTransfers.listByCampaign(params.id);
    sendJson(res, 200, { transfers });
  });

  router.post('/v1/play/campaigns/:id/characters/:character_id/inventory/items', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.character_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const itemId = body.data && body.data.item_id;
    const quantity = body.data && body.data.quantity;
    if (!VALID_ITEM_IDS.has(itemId) || !Number.isInteger(quantity) || quantity <= 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const existing = playCampaignItems.get(params.id, params.character_id, itemId);
    const totalQuantity = (existing ? existing.quantity : 0) + quantity;
    playCampaignItems.set(params.id, params.character_id, itemId, { item_id: itemId, quantity: totalQuantity });

    sendJson(res, 201, {
      character_id: params.character_id,
      item_id: itemId,
      quantity,
      total_quantity: totalQuantity,
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:character_id/inventory/items', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    const member = members.find((m) => m.character_id === params.character_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const items = playCampaignItems
      .listByCharacter(params.id, params.character_id)
      .filter((item) => item.quantity > 0)
      .map((item) => ({ item_id: item.item_id, quantity: item.quantity }));

    sendJson(res, 200, { character_id: params.character_id, items });
  });

  router.delete(
    '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const quantity = body.data && body.data.quantity;
      if (!VALID_ITEM_IDS.has(params.item_id) || !Number.isInteger(quantity) || quantity <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const existing = playCampaignItems.get(params.id, params.character_id, params.item_id);
      const heldQuantity = existing ? existing.quantity : 0;
      if (quantity > heldQuantity) {
        sendJson(res, 409, { error: 'insufficient quantity' });
        return;
      }

      const totalQuantity = heldQuantity - quantity;
      playCampaignItems.set(params.id, params.character_id, params.item_id, {
        item_id: params.item_id,
        quantity: totalQuantity,
      });

      sendJson(res, 200, {
        character_id: params.character_id,
        item_id: params.item_id,
        quantity,
        total_quantity: totalQuantity,
      });
    }
  );

  router.post(
    '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id/consume',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      if (!VALID_ITEM_IDS.has(params.item_id)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      const effect = CONSUMABLE_EFFECTS[params.item_id];
      if (!effect) {
        sendJson(res, 400, { error: 'item is not consumable' });
        return;
      }

      const existing = playCampaignItems.get(params.id, params.character_id, params.item_id);
      const heldQuantity = existing ? existing.quantity : 0;
      if (heldQuantity <= 0) {
        sendJson(res, 409, { error: 'no held quantity' });
        return;
      }

      const totalQuantity = heldQuantity - 1;
      playCampaignItems.set(params.id, params.character_id, params.item_id, {
        item_id: params.item_id,
        quantity: totalQuantity,
      });

      sendJson(res, 200, {
        character_id: params.character_id,
        item_id: params.item_id,
        quantity_consumed: 1,
        total_quantity: totalQuantity,
        effect,
      });
    }
  );

  router.post('/v1/play/campaigns/:id/start', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.status !== 'lobby' || members.length < 2) {
      sendJson(res, 409, { error: 'cannot start campaign' });
      return;
    }

    campaign.status = 'active';
    campaign.current_actor = members[0].username;
    campaign.turn_number = 1;
    campaign.phase = 'player';
    playCampaigns.set(params.id, campaign);

    sendJson(res, 200, {
      id: campaign.id,
      status: campaign.status,
      current_actor: campaign.current_actor,
      turn_number: campaign.turn_number,
    });
  });

  router.post('/v1/play/campaigns/:id/narrations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    const isOwner = user.role === 'dm' && campaign.owner === user.username;
    const delegation = isOwner ? null : playCampaignDelegations.get(params.id, user.username);
    const isDelegate = !isOwner && !!delegation && delegation.active && delegation.powers.includes('narrate');
    if (!isOwner && !isDelegate) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const text = body.data && body.data.text;
    if (typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const record = appendEvent(params.id, { kind: 'narration', actor: user.username, text });
    sendJson(res, 201, record);
  });

  const VALID_DELEGATION_POWERS = new Set(['narrate']);

  router.post('/v1/play/campaigns/:id/delegations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const targetUsername = body.data && body.data.username;
    const powers = body.data && body.data.powers;

    if (typeof targetUsername !== 'string' || targetUsername.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!Array.isArray(powers) || powers.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const uniquePowers = new Set(powers);
    if (uniquePowers.size !== powers.length || powers.some((power) => !VALID_DELEGATION_POWERS.has(power))) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isMember(members, targetUsername)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const existing = playCampaignDelegations.get(params.id, targetUsername);
    if (existing && existing.active) {
      sendJson(res, 409, { error: 'delegation already exists' });
      return;
    }

    const record = { username: targetUsername, powers: [...powers], active: true };
    playCampaignDelegations.set(params.id, targetUsername, record);
    playCampaignDelegationAudit.add(params.id, {
      username: targetUsername,
      action: 'granted',
      powers: JSON.stringify(record.powers),
    });

    sendJson(res, 201, record);
  });

  router.delete('/v1/play/campaigns/:id/delegations/:username', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const delegation = playCampaignDelegations.get(params.id, params.username);
    if (!delegation) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    delegation.active = false;
    playCampaignDelegations.set(params.id, params.username, delegation);
    playCampaignDelegationAudit.add(params.id, {
      username: params.username,
      action: 'revoked',
      powers: JSON.stringify(delegation.powers),
    });

    sendJson(res, 200, delegation);
  });

  router.get('/v1/play/campaigns/:id/delegations/audit', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const entries = playCampaignDelegationAudit.listByCampaign(params.id).map((row) => ({
      username: row.username,
      action: row.action,
      powers: JSON.parse(row.powers),
    }));

    sendJson(res, 200, { entries });
  });

  router.post('/v1/play/campaigns/:id/audit-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    const isOwner = campaign.owner === user.username;
    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isOwner && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const kind = body.data && body.data.kind;
    const correlationId = body.data && body.data.correlation_id;
    if (typeof kind !== 'string' || kind.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (typeof correlationId !== 'string' || correlationId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignAuditEvents.has(params.id, correlationId)) {
      sendJson(res, 409, { error: 'correlation_id already exists' });
      return;
    }

    const role = isOwner ? 'DM' : 'player';
    const timestamp = playCampaignAuditEvents.listByCampaign(params.id).length + 1;
    const record = { kind, actor: user.username, role, timestamp, correlation_id: correlationId };
    playCampaignAuditEvents.set(params.id, correlationId, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/audit-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const entries = playCampaignAuditEvents.listByCampaign(params.id);
    sendJson(res, 200, { entries });
  });

  const VALID_PROJECTION_EVENT_KINDS = new Set(['set-story', 'increment-danger']);

  // Rebuilds the campaign projection solely from the ordered projection
  // event log; never reads any cached/derived state.
  function buildProjection(campaignId) {
    const events = playCampaignProjectionEvents.listByCampaign(campaignId);
    let story = null;
    let danger = 0;
    const appliedEventIds = [];
    for (const event of events) {
      if (event.kind === 'set-story') {
        story = event.value;
      } else if (event.kind === 'increment-danger') {
        danger += 1;
      }
      appliedEventIds.push(event.event_id);
    }
    return { story: story === null ? '' : story, danger, applied_event_ids: appliedEventIds };
  }

  router.post('/v1/play/campaigns/:id/projection-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const eventId = body.data && body.data.event_id;
    const kind = body.data && body.data.kind;
    const value = body.data && body.data.value;

    if (typeof eventId !== 'string' || eventId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!VALID_PROJECTION_EVENT_KINDS.has(kind)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (kind === 'set-story') {
      if (typeof value !== 'string' || value.length === 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
    } else if (value !== undefined) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignProjectionEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'event_id already exists' });
      return;
    }

    const sequence = playCampaignProjectionEvents.countByCampaign(params.id) + 1;
    const record =
      kind === 'set-story'
        ? { sequence, event_id: eventId, kind, value }
        : { sequence, event_id: eventId, kind };
    playCampaignProjectionEvents.add(params.id, record);
    buildProjection(params.id);
    bumpMetric(params.id, 'projection_events');

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/projection', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, buildProjection(params.id));
  });

  router.get('/v1/play/campaigns/:id/projection/rebuild', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, buildProjection(params.id));
  });

  router.post('/v1/play/campaigns/:id/idempotent-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const rawKey = req.headers['idempotency-key'];
    const idempotencyKey = typeof rawKey === 'string' ? rawKey.trim() : '';
    if (!idempotencyKey) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const eventId = body.data && body.data.event_id;
    const value = body.data && body.data.value;

    if (typeof eventId !== 'string' || eventId.length === 0 || typeof value !== 'string' || value.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const existingKeyRecord = playCampaignIdempotencyKeys.get(params.id, idempotencyKey);
    if (existingKeyRecord) {
      if (existingKeyRecord.event_id === eventId && existingKeyRecord.value === value) {
        sendJson(res, 200, playCampaignIdempotentEvents.get(params.id, eventId));
        return;
      }
      sendJson(res, 409, { error: 'idempotency_key already used with a different request' });
      return;
    }

    if (playCampaignIdempotentEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'event_id already exists' });
      return;
    }

    const sequence = playCampaignIdempotentEvents.countByCampaign(params.id) + 1;
    const record = { event_id: eventId, value, sequence, idempotency_key: idempotencyKey };
    playCampaignIdempotentEvents.add(params.id, record);
    playCampaignIdempotencyKeys.set(params.id, idempotencyKey, { event_id: eventId, value });

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/idempotent-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const events = playCampaignIdempotentEvents.listByCampaign(params.id);
    sendJson(res, 200, { events });
  });

  router.post('/v1/play/campaigns/:id/feed-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const eventId = body.data && body.data.event_id;
    const text = body.data && body.data.text;
    if (typeof eventId !== 'string' || eventId.length === 0 || typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignFeedEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'event_id already exists' });
      return;
    }

    const sequence = playCampaignFeedEvents.countByCampaign(params.id) + 1;
    const record = { event_id: eventId, text, sequence };
    playCampaignFeedEvents.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/event-feed', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const url = new URL(req.url, 'http://localhost');
    const cursorRaw = url.searchParams.get('cursor');
    const limitRaw = url.searchParams.get('limit');
    const cursor = cursorRaw === null ? 0 : Number(cursorRaw);
    const limit = limitRaw === null ? 2 : Number(limitRaw);
    if (
      !Number.isInteger(cursor) ||
      cursor < 0 ||
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 3
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const events = playCampaignFeedEvents.listByCampaign(params.id);
    const page = events.slice(cursor, cursor + limit);
    sendJson(res, 200, { events: page, next_cursor: cursor + page.length });
  });

  router.post('/v1/play/campaigns/:id/safe-turns', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const submissionId = body.data && body.data.submission_id;
    const expectedTurn = body.data && body.data.expected_turn;
    const action = body.data && body.data.action;

    if (
      typeof submissionId !== 'string' ||
      submissionId.length === 0 ||
      typeof action !== 'string' ||
      action.length === 0 ||
      !Number.isInteger(expectedTurn) ||
      expectedTurn <= 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignSafeTurns.has(params.id, submissionId)) {
      sendJson(res, 409, { error: 'submission_id already used' });
      return;
    }

    const state = playCampaignSafeTurnState.get(params.id) || { current_turn: 1 };
    if (expectedTurn !== state.current_turn) {
      sendJson(res, 409, { current_turn: state.current_turn });
      return;
    }

    const acceptedTurn = state.current_turn;
    const nextTurn = acceptedTurn + 1;
    const record = { submission_id: submissionId, action, accepted_turn: acceptedTurn, next_turn: nextTurn };
    playCampaignSafeTurns.set(params.id, submissionId, record);
    playCampaignSafeTurnState.set(params.id, { current_turn: nextTurn });

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/safe-turns', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const state = playCampaignSafeTurnState.get(params.id) || { current_turn: 1 };
    const accepted = playCampaignSafeTurns.listByCampaign(params.id);

    sendJson(res, 200, { current_turn: state.current_turn, accepted });
  });

  router.get('/v1/play/campaigns/:id/turn', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const phase =
      campaign.phase || (campaign.current_actor === campaign.owner ? 'gm' : 'player');
    const queue = members.flatMap((member) => [member.username, campaign.owner]);
    const turnDeadline = (campaign.turn_number || 0) + TURN_TIMEOUT_WINDOW;
    sendJson(res, 200, {
      campaign_id: campaign.id,
      current_actor: campaign.current_actor,
      phase,
      turn_number: campaign.turn_number,
      queue,
      overdue: false,
      logical_deadline: turnDeadline,
    });
  });

  router.post('/v1/play/campaigns/:id/turn/nudge', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const message = body.data && body.data.message;
    if (typeof message !== 'string' || message.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    campaign.nudge_count = (campaign.nudge_count || 0) + 1;
    playCampaigns.set(params.id, campaign);

    appendEvent(params.id, {
      kind: 'nudge',
      actor: user.username,
      text: message,
    });

    sendJson(res, 201, {
      campaign_id: campaign.id,
      actor: user.username,
      current_actor: campaign.current_actor,
      target: campaign.current_actor,
      message,
      nudge_count: campaign.nudge_count,
    });
  });

  router.get('/v1/play/campaigns/:id/my-turn', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;
    if (user.role !== 'player') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const myMembership = members.find((member) => member.username === user.username);
    if (!myMembership) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const events = playCampaignEvents.listByCampaign(params.id);
    const recentEvents = events.slice(-10);

    sendJson(res, 200, {
      campaign_id: campaign.id,
      is_my_turn: campaign.current_actor === user.username,
      current_actor: campaign.current_actor,
      character: { id: myMembership.character_id, name: myMembership.name },
      recent_events: recentEvents,
    });
  });

  router.post('/v1/play/campaigns/:id/actions', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isMember(members, user.username) && user.role !== 'dm') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    if (user.role !== 'player' || campaign.current_actor !== user.username) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const type = body.data && body.data.type;
    const text = body.data && body.data.text;
    if (typeof type !== 'string' || type.length === 0 || typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    campaign.current_actor = campaign.owner;
    campaign.phase = 'gm';
    playCampaigns.set(params.id, campaign);

    const record = appendEvent(params.id, {
      kind: 'action',
      actor: user.username,
      type,
      text,
      next_actor: 'dm',
    });
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/resolutions', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 409, { error: 'not owner turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const text = body.data && body.data.text;
    if (typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const nextActor =
      (campaign.turn_number || 0) >= 2
        ? members[0]
          ? members[0].username
          : campaign.owner
        : members[1]
        ? members[1].username
        : campaign.owner;

    campaign.current_actor = nextActor;
    campaign.turn_number = (campaign.turn_number || 0) + 1;
    campaign.phase = 'player';
    playCampaigns.set(params.id, campaign);

    const record = appendEvent(params.id, {
      kind: 'resolution',
      actor: user.username,
      text,
      next_actor: nextActor,
      turn_number: campaign.turn_number,
    });
    sendJson(res, 201, record);
  });

  router.put('/v1/play/campaigns/:id/document', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const story = body.data && body.data.story;
    const dmNotes = body.data && body.data.dm_notes;
    if (typeof story !== 'string' || typeof dmNotes !== 'string') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    campaign.document = { story, dm_notes: dmNotes };
    playCampaigns.set(params.id, campaign);

    sendJson(res, 200, { story, dm_notes: dmNotes });
  });

  router.get('/v1/play/campaigns/:id/document', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const document = campaign.document || { story: '', dm_notes: '' };
    if (campaign.owner === user.username) {
      sendJson(res, 200, { story: document.story, dm_notes: document.dm_notes });
    } else {
      sendJson(res, 200, { story: document.story });
    }
  });

  router.post('/v1/play/campaigns/:id/exports', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const document = campaign.document || { story: '', dm_notes: '' };
    const version = playCampaignExports.countByCampaign(params.id) + 1;
    const record = { version, story: document.story, status: campaign.status };
    playCampaignExports.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/exports', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const exports = playCampaignExports.listByCampaign(params.id);
    sendJson(res, 200, { exports });
  });

  router.get('/v1/play/campaigns/:id/exports/:version', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const version = Number.parseInt(params.version, 10);
    const exportRecord = Number.isInteger(version) ? playCampaignExports.get(params.id, version) : undefined;
    if (!exportRecord) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, exportRecord);
  });

  router.post('/v1/play/campaigns/:id/backups', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const document = campaign.document || { story: '', dm_notes: '' };
    const sequence = playCampaignBackups.countByCampaign(params.id) + 1;
    const record = { backup_id: `backup-${sequence}`, story: document.story, status: campaign.status };
    playCampaignBackups.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/backups', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const backups = playCampaignBackups.listByCampaign(params.id);
    sendJson(res, 200, { backups });
  });

  router.post('/v1/play/campaigns/:id/backups/:backup_id/restore', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const backup = playCampaignBackups.get(params.id, params.backup_id);
    if (!backup) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    campaign.document = { ...(campaign.document || { story: '', dm_notes: '' }), story: backup.story };
    campaign.status = backup.status;
    playCampaigns.set(params.id, campaign);

    sendJson(res, 200, backup);
  });

  router.post('/v1/play/campaigns/:id/replay-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const eventId = body && body.event_id;
    const kind = body && body.kind;
    const text = body && body.text;

    if (typeof eventId !== 'string' || eventId.length === 0 || typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (kind !== 'append') {
      sendJson(res, 400, { error: 'invalid kind' });
      return;
    }

    if (playCampaignReplayEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'event_id already exists' });
      return;
    }

    const sequence = playCampaignReplayEvents.countByCampaign(params.id) + 1;
    const record = { event_id: eventId, kind, text, sequence };
    playCampaignReplayEvents.add(params.id, record);

    sendJson(res, 201, record);
  });

  function buildReplayState(campaignId) {
    const events = playCampaignReplayEvents.listByCampaign(campaignId);
    const eventIds = events.map((event) => event.event_id);
    const story = events.map((event) => event.text).join('');
    const digest = `${eventIds.join(',')}|${story}`;
    return { story, event_ids: eventIds, digest };
  }

  router.get('/v1/play/campaigns/:id/replay', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, buildReplayState(params.id));
  });

  router.get('/v1/play/campaigns/:id/replay/check', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, buildReplayState(params.id));
  });

  function stableRoll(seed, sequence, rollId, sides) {
    const str = `${seed}|${sequence}|${rollId}|${sides}`;
    const bytes = Buffer.from(str, 'utf8');
    let acc = 0;
    for (const b of bytes) {
      acc = (acc * 31 + b) % 4294967296;
    }
    return (acc % sides) + 1;
  }

  router.put('/v1/play/campaigns/:id/rng-seed', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const seed = body && body.seed;

    if (typeof seed !== 'string' || seed.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignRngConfig.get(params.id) !== undefined) {
      sendJson(res, 409, { error: 'seed already configured' });
      return;
    }

    playCampaignRngConfig.set(params.id, seed);

    sendJson(res, 200, { seed, rolls: [] });
  });

  router.post('/v1/play/campaigns/:id/rng-rolls', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const seed = playCampaignRngConfig.get(params.id);
    if (seed === undefined) {
      sendJson(res, 409, { error: 'seed not configured' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const rollId = body && body.roll_id;
    const sides = body && body.sides;

    if (typeof rollId !== 'string' || rollId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!Number.isInteger(sides) || sides < 2 || sides > 100) {
      sendJson(res, 400, { error: 'invalid sides' });
      return;
    }

    if (playCampaignRngRolls.has(params.id, rollId)) {
      sendJson(res, 409, { error: 'roll_id already exists' });
      return;
    }

    const sequence = playCampaignRngRolls.countByCampaign(params.id) + 1;
    const result = stableRoll(seed, sequence, rollId, sides);
    const record = { roll_id: rollId, sides, result, sequence };
    playCampaignRngRolls.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/rng-ledger', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const seed = playCampaignRngConfig.get(params.id);
    const rolls = seed === undefined ? [] : playCampaignRngRolls.listByCampaign(params.id);

    sendJson(res, 200, { seed: seed === undefined ? null : seed, rolls });
  });

  router.post('/v1/play/campaigns/:id/moderation/reports', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const reportId = body && body.report_id;
    const targetId = body && body.target_id;
    const reason = body && body.reason;

    if (
      typeof reportId !== 'string' ||
      reportId.length === 0 ||
      typeof targetId !== 'string' ||
      targetId.length === 0 ||
      typeof reason !== 'string' ||
      reason.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignModerationReports.has(params.id, reportId)) {
      sendJson(res, 409, { error: 'report_id already exists' });
      return;
    }

    const sequence = playCampaignModerationReports.countByCampaign(params.id) + 1;
    const record = {
      report_id: reportId,
      target_id: targetId,
      reason,
      status: 'open',
      reporter: user.username,
      sequence,
    };
    playCampaignModerationReports.set(params.id, reportId, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/moderation/reports', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const reports = playCampaignModerationReports.listByCampaign(params.id);
    sendJson(res, 200, { reports });
  });

  router.put('/v1/play/campaigns/:id/moderation/reports/:report_id/resolution', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const report = playCampaignModerationReports.get(params.id, params.report_id);
    if (!report) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const action = body && body.action;
    const note = body && body.note;

    if (
      (action !== 'allow' && action !== 'remove') ||
      typeof note !== 'string' ||
      note.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (report.status !== 'open') {
      sendJson(res, 409, { error: 'report already resolved' });
      return;
    }

    const record = { ...report, status: 'resolved', action, note, resolver: user.username };
    playCampaignModerationReports.set(params.id, params.report_id, record);

    sendJson(res, 200, record);
  });

  router.post('/v1/play/campaigns/:id/imports', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;

    if (
      !body ||
      typeof body !== 'object' ||
      body.version !== 1 ||
      typeof body.story !== 'string' ||
      body.story.length === 0 ||
      (body.status !== 'lobby' && body.status !== 'started')
    ) {
      sendJson(res, 400, { error: 'invalid import snapshot' });
      return;
    }

    const record = { version: 1, story: body.story, status: body.status };

    campaign.document = { ...(campaign.document || { story: '', dm_notes: '' }), story: body.story };
    campaign.status = body.status;
    playCampaigns.set(params.id, campaign);
    playCampaignImports.set(params.id, record);

    sendJson(res, 200, record);
  });

  router.get('/v1/play/campaigns/:id/import-state', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const record = playCampaignImports.get(params.id);
    if (!record) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, record);
  });

  router.post('/v1/play/campaigns/:id/migrations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;

    if (
      !body ||
      typeof body !== 'object' ||
      body.schema_version !== 1 ||
      typeof body.story !== 'string' ||
      body.story.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid migration snapshot' });
      return;
    }

    const migrated = { schema_version: 2, story: body.story, campaign_name: campaign.name };
    const existing = playCampaignMigrations.get(params.id);
    if (
      existing &&
      existing.source_schema_version === 1 &&
      existing.source_story === body.story
    ) {
      sendJson(res, 200, existing.state);
      return;
    }

    playCampaignMigrations.set(params.id, {
      source_schema_version: 1,
      source_story: body.story,
      state: migrated,
    });

    sendJson(res, 201, migrated);
  });

  router.get('/v1/play/campaigns/:id/migration-state', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const record = playCampaignMigrations.get(params.id);
    if (!record) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, record.state);
  });

  router.get('/v1/play/campaigns/:id/gm/status', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const party = members.map((member) => ({
      username: member.username,
      character_id: member.character_id,
      name: member.name,
      class: member.class,
    }));

    const events = playCampaignEvents.listByCampaign(params.id);
    const recentEvents = events.slice(-10);

    sendJson(res, 200, {
      campaign_id: campaign.id,
      needs_attention: campaign.current_actor === campaign.owner,
      current_actor: campaign.current_actor,
      party,
      recent_events: recentEvents,
    });
  });

  router.post('/v1/play/campaigns/:id/scenes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    if (typeof id !== 'string' || id.length === 0 || typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (playCampaignScenes.has(params.id, id)) {
      sendJson(res, 409, { error: 'scene already exists' });
      return;
    }

    const record = { id, name, status: 'open' };
    playCampaignScenes.set(params.id, id, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/scenes/:scene_id/enter', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const scene = playCampaignScenes.get(params.id, params.scene_id);
    if (!scene) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (scene.status !== 'open') {
      sendJson(res, 409, { error: 'scene is closed' });
      return;
    }

    campaign.current_scene_id = scene.id;
    playCampaigns.set(params.id, campaign);

    appendEvent(params.id, {
      kind: 'scene',
      actor: user.username,
      text: scene.id,
    });

    sendJson(res, 200, { current_scene_id: scene.id, name: scene.name });
  });

  router.post('/v1/play/campaigns/:id/scenes/:scene_id/close', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const scene = playCampaignScenes.get(params.id, params.scene_id);
    if (!scene) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    scene.status = 'closed';
    playCampaignScenes.set(params.id, params.scene_id, scene);

    sendJson(res, 200, { id: scene.id, status: scene.status });
  });

  router.get('/v1/play/campaigns/:id/scenes/current', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const currentSceneId = campaign.current_scene_id;
    const scene = currentSceneId ? playCampaignScenes.get(params.id, currentSceneId) : undefined;
    if (!scene || scene.status !== 'open') {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, { id: scene.id, name: scene.name, status: scene.status });
  });

  router.post('/v1/play/campaigns/:id/locations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    if (typeof id !== 'string' || id.length === 0 || typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (playCampaignLocations.has(params.id, id)) {
      sendJson(res, 409, { error: 'location already exists' });
      return;
    }

    const record = { id, name };
    playCampaignLocations.set(params.id, id, record);
    if (!campaign.current_location_id) {
      campaign.current_location_id = id;
      playCampaigns.set(params.id, campaign);
    }
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/locations/:from_id/connections', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const fromLocation = playCampaignLocations.get(params.id, params.from_id);
    if (!fromLocation) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const toId = body.data && body.data.to_id;
    const travelTurns = body.data && body.data.travel_turns;
    if (
      typeof toId !== 'string' ||
      toId.length === 0 ||
      !Number.isInteger(travelTurns) ||
      travelTurns < 1
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const toLocation = playCampaignLocations.get(params.id, toId);
    if (!toLocation || playCampaignLocationConnections.has(params.id, params.from_id, toId)) {
      sendJson(res, 400, { error: 'invalid connection' });
      return;
    }

    const record = { from_id: params.from_id, to_id: toId, travel_turns: travelTurns };
    playCampaignLocationConnections.set(params.id, params.from_id, toId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/locations/:loc_id/travel', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const connections = playCampaignLocationConnections.listByFrom(params.id, params.loc_id);
    const destinations = connections.map((connection) => {
      const location = playCampaignLocations.get(params.id, connection.to_id);
      return { id: connection.to_id, name: location ? location.name : connection.to_id, travel_turns: connection.travel_turns };
    });

    sendJson(res, 200, { destinations });
  });

  router.post('/v1/play/campaigns/:id/turn/travel', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'player' || campaign.current_actor !== user.username) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const destinationId = body.data && body.data.destination_id;
    if (typeof destinationId !== 'string' || destinationId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const fromId = campaign.current_location_id;
    const connections = fromId ? playCampaignLocationConnections.listByFrom(params.id, fromId) : [];
    const connection = connections.find((c) => c.to_id === destinationId);
    if (!connection) {
      sendJson(res, 409, { error: 'invalid destination' });
      return;
    }

    campaign.current_location_id = destinationId;
    campaign.current_actor = campaign.owner;
    playCampaigns.set(params.id, campaign);

    const record = appendEvent(params.id, {
      kind: 'travel',
      actor: user.username,
      destination_id: destinationId,
      travel_turns: connection.travel_turns,
      next_actor: 'dm',
    });
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/turn/rest', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'player' || campaign.current_actor !== user.username) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const restType = body.data && body.data.type;
    if (restType !== 'long' && restType !== 'short') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.username === user.username);
    if (!member) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    if (restType === 'long') {
      member.hp_current = member.hp_max;
      member.status = 'conscious';
      member.death_saves = { successes: 0, failures: 0 };
      playCampaignMembers.set(params.id, member.character_id, member);
    }

    campaign.current_actor = campaign.owner;
    playCampaigns.set(params.id, campaign);

    const record = appendEvent(params.id, {
      kind: 'rest',
      actor: user.username,
      type: restType,
      hp_current: member.hp_current,
      hp_max: member.hp_max,
      next_actor: 'dm',
    });
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/encounters', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const name = body.data && body.data.name;
    if (typeof id !== 'string' || id.length === 0 || typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignEncounters.has(params.id, id) || campaign.active_encounter_id) {
      sendJson(res, 409, { error: 'cannot create encounter' });
      return;
    }

    const record = { id, name, status: 'active', combatants: [] };
    playCampaignEncounters.set(params.id, id, record);

    campaign.active_encounter_id = id;
    playCampaigns.set(params.id, campaign);

    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/monsters', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const monsterId = body.data && body.data.monster_id;
    const name = body.data && body.data.name;
    const hpMax = body.data && body.data.hp_max;
    const initiative = body.data && body.data.initiative;
    if (
      typeof monsterId !== 'string' ||
      monsterId.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      !Number.isInteger(hpMax) ||
      hpMax < 1 ||
      typeof initiative !== 'number'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (!Array.isArray(encounter.combatants)) {
      encounter.combatants = [];
    }
    if (encounter.combatants.some((m) => m.monster_id === monsterId)) {
      sendJson(res, 409, { error: 'monster already exists' });
      return;
    }

    const monster = { monster_id: monsterId, name, hp_max: hpMax, initiative, hp_current: hpMax };
    encounter.combatants.push(monster);
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 201, monster);
  });

  router.delete('/v1/play/campaigns/:id/encounters/:encId/monsters/:monsterId', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const combatants = Array.isArray(encounter.combatants) ? encounter.combatants : [];
    const index = combatants.findIndex((m) => m.monster_id === params.monsterId);
    if (index === -1) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    combatants.splice(index, 1);
    encounter.combatants = combatants;
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, { removed: params.monsterId });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/combatants', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const memberUsername = body.data && body.data.member;
    const initiative = body.data && body.data.initiative;
    if (
      typeof memberUsername !== 'string' ||
      memberUsername.length === 0 ||
      typeof initiative !== 'number'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.username === memberUsername);
    if (!member) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (!Array.isArray(encounter.combatants)) {
      encounter.combatants = [];
    }
    if (encounter.combatants.some((c) => c.member === memberUsername)) {
      sendJson(res, 409, { error: 'combatant already exists' });
      return;
    }

    const combatant = {
      member: memberUsername,
      character_id: member.character_id,
      name: member.name,
      initiative,
    };
    encounter.combatants.push(combatant);
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 201, combatant);
  });

  router.delete('/v1/play/campaigns/:id/encounters/:encId/combatants/:member', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const combatants = Array.isArray(encounter.combatants) ? encounter.combatants : [];
    const index = combatants.findIndex((c) => c.member === params.member);
    if (index === -1) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    combatants.splice(index, 1);
    encounter.combatants = combatants;
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, { removed: params.member });
  });

  router.get('/v1/play/campaigns/:id/encounters/:encId/turn', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];
    sendJson(res, 200, {
      round: encounter.round || 1,
      turn_index: turnIndex,
      active: { name: active.name, kind: active.kind, initiative: active.initiative },
    });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/turn/advance', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];

    const isCurrentCombatant = active.kind === 'player' && active.member === user.username;
    if (campaign.owner !== user.username && !isCurrentCombatant) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    let nextIndex = turnIndex + 1;
    let round = encounter.round || 1;
    if (nextIndex >= order.length) {
      nextIndex = 0;
      round += 1;
    }

    encounter.turn_index = nextIndex;
    encounter.round = round;

    const newActive = order[nextIndex];
    decrementConditions(encounter, newActive.target);

    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, {
      round,
      turn_index: nextIndex,
      active: { name: newActive.name, kind: newActive.kind, initiative: newActive.initiative },
    });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/turn/delay', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];

    const isCurrentCombatant = active.kind === 'player' && active.member === user.username;
    if (campaign.owner !== user.username && !isCurrentCombatant) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const newIndex = body.data && body.data.new_index;
    if (
      !Number.isInteger(newIndex) ||
      newIndex <= turnIndex ||
      newIndex > order.length - 1
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const remaining = order.slice(0, turnIndex).concat(order.slice(turnIndex + 1));
    remaining.splice(newIndex, 0, active);

    encounter.turn_order = remaining.map((c) => c.target);
    // The delaying combatant hasn't acted yet, so they remain the active
    // combatant at their new position rather than handing the turn off.
    encounter.turn_index = newIndex;
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, {
      order: remaining.map((c) => ({ name: c.name, kind: c.kind, initiative: c.initiative })),
    });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/turn/ready', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];

    const isCurrentCombatant = active.kind === 'player' && active.member === user.username;
    if (!isCurrentCombatant) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const trigger = body.data && body.data.trigger;
    if (typeof trigger !== 'string' || trigger.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    sendJson(res, 201, { actor: user.username, trigger });
  });

  // Decrements remaining_rounds for every condition on the given target at
  // the start of that target's turn, dropping any that reach zero.
  function decrementConditions(encounter, target) {
    if (!encounter.conditions || !Array.isArray(encounter.conditions[target])) return;
    encounter.conditions[target] = encounter.conditions[target]
      .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter((c) => c.remaining_rounds > 0);
  }

  router.post('/v1/play/campaigns/:id/encounters/:encId/conditions', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const target = body.data && body.data.target;
    const condition = body.data && body.data.condition;
    const durationRounds = body.data && body.data.duration_rounds;
    if (
      typeof target !== 'string' ||
      target.length === 0 ||
      typeof condition !== 'string' ||
      condition.length === 0 ||
      !Number.isInteger(durationRounds) ||
      durationRounds < 1
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const combatants = Array.isArray(encounter.combatants) ? encounter.combatants : [];
    const exists = combatants.some((c) => (c.monster_id || c.member) === target);
    if (!exists) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!encounter.conditions) {
      encounter.conditions = {};
    }
    if (!Array.isArray(encounter.conditions[target])) {
      encounter.conditions[target] = [];
    }

    const list = encounter.conditions[target];
    const existing = list.find((c) => c.condition === condition);
    if (existing) {
      existing.remaining_rounds = durationRounds;
    } else {
      list.push({ condition, remaining_rounds: durationRounds });
    }

    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 201, { target, conditions: list });
  });

  router.get('/v1/play/campaigns/:id/encounters/:encId/status', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];

    sendJson(res, 200, {
      round: encounter.round || 1,
      turn_index: turnIndex,
      active: { name: active.name, kind: active.kind, initiative: active.initiative },
      order: order.map((c) => ({ name: c.name, kind: c.kind, initiative: c.initiative })),
      conditions: encounter.conditions || {},
    });
  });

  // Locates a combatant by target identifier, returning both the
  // combatant entry and hp accessors. Monster combatants carry their own
  // hp_current/hp_max; player combatants defer to their party-member
  // record, which is the single source of truth for a character's hp.
  function findCombatantHp(campaignId, encounter, target) {
    const combatants = Array.isArray(encounter.combatants) ? encounter.combatants : [];
    const monster = combatants.find((c) => c.monster_id === target);
    if (monster) {
      return {
        hpMax: monster.hp_max,
        hpCurrent: monster.hp_current,
        save(hp) {
          monster.hp_current = hp;
          playCampaignEncounters.set(campaignId, encounter.id, encounter);
        },
      };
    }

    const combatant = combatants.find((c) => c.member === target);
    if (combatant) {
      const member = playCampaignMembers.listByCampaign(campaignId).find((m) => m.username === combatant.member);
      if (!member) return null;
      return {
        hpMax: member.hp_max,
        hpCurrent: member.hp_current,
        save(hp) {
          member.hp_current = hp;
          playCampaignMembers.set(campaignId, member.character_id, member);
        },
      };
    }

    return null;
  }

  router.post('/v1/play/campaigns/:id/encounters/:encId/damage', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const target = body.data && body.data.target;
    const amount = body.data && body.data.amount;
    if (typeof target !== 'string' || target.length === 0 || !Number.isInteger(amount) || amount < 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const hp = findCombatantHp(params.id, encounter, target);
    if (!hp) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const hpBefore = hp.hpCurrent;
    const hpAfter = Math.max(0, hpBefore - amount);
    hp.save(hpAfter);

    sendJson(res, 200, { target, hp_before: hpBefore, hp_after: hpAfter, damage: amount });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/heal', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const target = body.data && body.data.target;
    const amount = body.data && body.data.amount;
    if (typeof target !== 'string' || target.length === 0 || !Number.isInteger(amount) || amount < 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const hp = findCombatantHp(params.id, encounter, target);
    if (!hp) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const hpBefore = hp.hpCurrent;
    const hpAfter = Math.min(hp.hpMax, hpBefore + amount);
    hp.save(hpAfter);

    sendJson(res, 200, { target, hp_before: hpBefore, hp_after: hpAfter, healing: amount });
  });

  const VALID_ACTION_TYPES = new Set(['attack', 'help', 'dodge', 'ready']);

  router.post('/v1/play/campaigns/:id/encounters/:encId/actions', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const order = initiativeOrder(encounter);
    const turnIndex = encounter.turn_index || 0;
    const active = order[turnIndex];

    const isCurrentCombatant = active.kind === 'player' && active.member === user.username;
    if (!isCurrentCombatant) {
      sendJson(res, 409, { error: 'not your turn' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const type = body.data && body.data.type;
    const target = body.data && body.data.target;
    const text = body.data && body.data.text;
    if (
      typeof type !== 'string' ||
      !VALID_ACTION_TYPES.has(type) ||
      typeof text !== 'string' ||
      text.length === 0 ||
      (target !== undefined && typeof target !== 'string')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const record = appendEvent(params.id, {
      kind: 'combat_action',
      actor: user.username,
      type,
      target: target !== undefined ? target : null,
      text,
    });
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/rewards', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (encounter.rewards) {
      sendJson(res, 409, { error: 'rewards already awarded' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const xp = body.data && body.data.xp;
    const loot = body.data && body.data.loot;
    if (
      !Number.isInteger(xp) ||
      xp < 0 ||
      !Array.isArray(loot) ||
      loot.some(
        (item) =>
          !item ||
          typeof item.slug !== 'string' ||
          item.slug.length === 0 ||
          !Number.isInteger(item.quantity) ||
          item.quantity < 1
      )
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const record = { encounter_id: encounter.id, xp, loot };
    encounter.rewards = record;
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, record);
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/close', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    encounter.status = 'closed';
    playCampaignEncounters.set(params.id, params.encId, encounter);

    sendJson(res, 200, {
      id: encounter.id,
      status: encounter.status,
      xp_awarded: encounter.rewards ? encounter.rewards.xp : 0,
    });
  });

  router.post('/v1/play/campaigns/:id/encounters/:encId/end', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const encounter = playCampaignEncounters.get(params.id, params.encId);
    if (!encounter) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (campaign.active_encounter_id !== params.encId) {
      sendJson(res, 409, { error: 'campaign is not in combat' });
      return;
    }

    if (encounter.status === 'active') {
      encounter.status = 'closed';
      playCampaignEncounters.set(params.id, params.encId, encounter);
    }

    campaign.active_encounter_id = null;
    campaign.current_actor = campaign.owner;
    campaign.phase = 'exploration';
    playCampaigns.set(params.id, campaign);

    sendJson(res, 200, {
      campaign_id: campaign.id,
      status: campaign.status,
      phase: 'exploration',
      current_actor: campaign.current_actor,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/damage', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const amount = body.data && body.data.amount;
    if (!Number.isInteger(amount) || amount < 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const hpBefore = member.hp_current;
    const hpAfter = Math.max(0, hpBefore - amount);
    member.hp_current = hpAfter;
    if (hpAfter === 0) {
      if (member.status !== 'stable' && member.status !== 'dead') {
        member.status = 'unconscious';
        member.death_saves = { successes: 0, failures: 0 };
      }
    } else {
      member.status = 'conscious';
      member.death_saves = { successes: 0, failures: 0 };
    }
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 200, {
      character_id: member.character_id,
      target: member.character_id,
      hp_before: hpBefore,
      hp_after: hpAfter,
      damage: amount,
      status: member.status,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/death-saves', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (member.username !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    if (member.status !== 'unconscious') {
      sendJson(res, 409, { error: 'no death save required' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const outcome = body.data && body.data.outcome;
    if (outcome !== 'success' && outcome !== 'failure') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const deathSaves = member.death_saves || { successes: 0, failures: 0 };
    if (outcome === 'success') {
      deathSaves.successes += 1;
    } else {
      deathSaves.failures += 1;
    }

    if (deathSaves.successes >= 3) {
      member.status = 'stable';
    } else if (deathSaves.failures >= 3) {
      member.status = 'dead';
    }
    member.death_saves = deathSaves;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 201, {
      character_id: member.character_id,
      successes: deathSaves.successes,
      failures: deathSaves.failures,
      status: member.status,
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/status', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, {
      character_id: member.character_id,
      hp_current: member.hp_current,
      hp_max: member.hp_max,
      status: member.status || 'conscious',
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/owner', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, { character_id: member.character_id, owner: member.owner || null });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/claim', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;
    if (user.role !== 'player') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (member.owner && member.owner !== user.username) {
      sendJson(res, 409, { error: 'character already owned' });
      return;
    }

    member.owner = user.username;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 201, { character_id: member.character_id, owner: member.owner });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/transfer', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const newOwner = body.data && body.data.new_owner;
    if (typeof newOwner !== 'string' || newOwner.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!isMember(members, newOwner)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    member.owner = newOwner;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 200, { character_id: member.character_id, owner: member.owner });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/build', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const race = body.data && body.data.race;
    const characterClass = body.data && body.data.class;
    const background = body.data && body.data.background;
    const abilities = body.data && body.data.abilities;

    if (
      typeof race !== 'string' ||
      !VALID_RACES.has(race) ||
      typeof characterClass !== 'string' ||
      !CLASS_HIT_DIE[characterClass] ||
      typeof background !== 'string' ||
      !VALID_BACKGROUNDS.has(background) ||
      !abilities ||
      typeof abilities !== 'object'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const modifiers = {};
    for (const key of ABILITY_KEYS) {
      const score = abilities[key];
      if (!Number.isInteger(score) || score < 1 || score > 30) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      modifiers[key] = abilityModifier(score);
    }

    const level = 1;
    const hpMax = CLASS_HIT_DIE[characterClass] + modifiers.con;
    const bonus = proficiencyBonus(level);

    member.race = race;
    member.class = characterClass;
    member.background = background;
    member.level = level;
    member.hp_max = hpMax;
    member.hp_current = hpMax;
    member.abilities = abilities;
    member.proficiency_bonus = bonus;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 200, {
      character_id: member.character_id,
      race,
      class: characterClass,
      background,
      level,
      hp_max: hpMax,
      proficiency_bonus: bonus,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/level-up', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const newLevel = body.data && body.data.level;
    const currentLevel = member.level || 1;
    const hitDie = CLASS_HIT_DIE[member.class];
    if (
      !Number.isInteger(newLevel) ||
      newLevel !== currentLevel + 1 ||
      !hitDie ||
      !member.abilities ||
      typeof member.abilities.con !== 'number'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const conModifier = abilityModifier(member.abilities.con);
    const perLevelGain = Math.floor(hitDie / 2) + 1 + conModifier;
    const hpMax = (member.hp_max || 0) + perLevelGain;
    const bonus = proficiencyBonus(newLevel);

    member.level = newLevel;
    member.hp_max = hpMax;
    member.proficiency_bonus = bonus;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 200, {
      character_id: member.character_id,
      level: newLevel,
      hp_max: hpMax,
      hit_dice: `1d${hitDie}`,
      proficiency_bonus: bonus,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/skill-check', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const skill = body.data && body.data.skill;
    const ability = body.data && body.data.ability;
    const proficient = body.data && body.data.proficient;
    const roll = body.data && body.data.roll;

    if (
      typeof skill !== 'string' ||
      !SKILL_ABILITIES[skill] ||
      typeof ability !== 'string' ||
      !ABILITY_KEYS.includes(ability) ||
      typeof proficient !== 'boolean' ||
      !Number.isInteger(roll) ||
      !member.abilities ||
      typeof member.abilities[ability] !== 'number'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const abilityMod = abilityModifier(member.abilities[ability]);
    const bonus = member.proficiency_bonus != null ? member.proficiency_bonus : proficiencyBonus(member.level || 1);
    const modifier = abilityMod + (proficient ? bonus : 0);
    const total = roll + modifier;

    sendJson(res, 200, {
      character_id: member.character_id,
      skill,
      ability,
      modifier,
      total,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/spells', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const spellId = body.data && body.data.spell_id;
    const name = body.data && body.data.name;
    const level = body.data && body.data.level;

    const entry = typeof spellId === 'string' ? SPELL_COMPENDIUM[spellId] : undefined;
    if (
      typeof spellId !== 'string' ||
      typeof name !== 'string' ||
      !Number.isInteger(level) ||
      !entry ||
      entry.name !== name ||
      entry.level !== level ||
      !entry.classes.includes(member.class)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignSpells.has(params.id, member.character_id, spellId)) {
      sendJson(res, 409, { error: 'spell already known' });
      return;
    }

    const spell = { spell_id: spellId, name: entry.name, level: entry.level };
    playCampaignSpells.set(params.id, member.character_id, spellId, spell);

    sendJson(res, 201, spell);
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/spells', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const spells = playCampaignSpells.listByCharacter(params.id, member.character_id);
    sendJson(res, 200, { spells });
  });

  router.put('/v1/play/campaigns/:id/characters/:char_id/prepared-spells', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const spellIds = body.data && body.data.spell_ids;

    if (
      !Array.isArray(spellIds) ||
      !spellIds.every((spellId) => typeof spellId === 'string') ||
      !SPELLCASTING_CLASSES.has(member.class)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const maxPrepared = member.level || 1;
    if (
      spellIds.length > maxPrepared ||
      !spellIds.every((spellId) => playCampaignSpells.has(params.id, member.character_id, spellId))
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    member.prepared_spells = spellIds;
    playCampaignMembers.set(params.id, member.character_id, member);

    sendJson(res, 200, {
      character_id: member.character_id,
      prepared_spells: spellIds,
      max_prepared: maxPrepared,
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/prepared-spells', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, {
      character_id: member.character_id,
      prepared_spells: member.prepared_spells || [],
      max_prepared: member.level || 1,
    });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/casts', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const spellId = body.data && body.data.spell_id;
    const target = body.data && body.data.target;

    if (typeof spellId !== 'string' || typeof target !== 'string') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const preparedSpells = member.prepared_spells || [];
    const entry = SPELL_COMPENDIUM[spellId];
    if (!SPELLCASTING_CLASSES.has(member.class) || !entry || !preparedSpells.includes(spellId)) {
      sendJson(res, 400, { error: 'spell not prepared' });
      return;
    }

    const slotLevel = entry.level;
    const casts = playCampaignCasts.listByCharacter(params.id, member.character_id);
    const usedSlots = casts.filter((cast) => cast.slot_level === slotLevel).length;
    const maxSlots = maxSpellSlots(member.level || 1, slotLevel);
    if (usedSlots >= maxSlots) {
      sendJson(res, 409, { error: 'no spell slots remaining' });
      return;
    }

    const cast = {
      character_id: member.character_id,
      spell_id: spellId,
      target,
      slot_level: slotLevel,
      slots_remaining: maxSlots - usedSlots - 1,
      sequence: casts.length + 1,
    };
    playCampaignCasts.add(params.id, member.character_id, cast);

    sendJson(res, 201, cast);
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/casts', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const casts = playCampaignCasts.listByCharacter(params.id, member.character_id);
    sendJson(res, 200, { casts });
  });

  router.put('/v1/play/campaigns/:id/characters/:char_id/concentration', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const spellId = body.data && body.data.spell_id;
    const target = body.data && body.data.target;
    const durationTurns = body.data && body.data.duration_turns;

    const preparedSpells = member.prepared_spells || [];
    if (
      typeof spellId !== 'string' ||
      typeof target !== 'string' ||
      !Number.isInteger(durationTurns) ||
      durationTurns < 1 ||
      !SPELLCASTING_CLASSES.has(member.class) ||
      !playCampaignSpells.has(params.id, member.character_id, spellId) ||
      !preparedSpells.includes(spellId)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const concentration = { spell_id: spellId, target, remaining_turns: durationTurns };
    playCampaignConcentration.set(params.id, member.character_id, concentration);

    sendJson(res, 200, { character_id: member.character_id, concentration });
  });

  router.get('/v1/play/campaigns/:id/characters/:char_id/concentration', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const concentration = playCampaignConcentration.get(params.id, member.character_id);
    sendJson(res, 200, { character_id: member.character_id, concentration });
  });

  router.post('/v1/play/campaigns/:id/characters/:char_id/concentration/advance-turn', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const concentration = playCampaignConcentration.get(params.id, member.character_id);
    if (!concentration) {
      sendJson(res, 200, { character_id: member.character_id, concentration: null });
      return;
    }

    const remainingTurns = concentration.remaining_turns - 1;
    if (remainingTurns <= 0) {
      playCampaignConcentration.set(params.id, member.character_id, null);
      sendJson(res, 200, { character_id: member.character_id, concentration: null });
      return;
    }

    const updated = { ...concentration, remaining_turns: remainingTurns };
    playCampaignConcentration.set(params.id, member.character_id, updated);
    sendJson(res, 200, { character_id: member.character_id, concentration: updated });
  });

  router.delete('/v1/play/campaigns/:id/characters/:char_id/concentration', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === params.char_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (!member.owner || member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    playCampaignConcentration.set(params.id, member.character_id, null);
    sendJson(res, 200, { character_id: member.character_id, concentration: null });
  });

  router.put(
    '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      if (!VALID_EQUIPMENT_SLOTS.has(params.slot)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const itemId = body.data && body.data.item_id;
      if (!VALID_ITEM_IDS.has(itemId) || ITEM_EQUIPMENT_SLOT[itemId] !== params.slot) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const held = playCampaignItems.get(params.id, params.character_id, itemId);
      if (!held || held.quantity <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const record = { item_id: itemId, attuned: false };
      playCampaignEquipment.set(params.id, params.character_id, params.slot, record);

      sendJson(res, 200, {
        character_id: params.character_id,
        slot: params.slot,
        item_id: itemId,
        attuned: false,
      });
    }
  );

  router.get(
    '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      if (campaign.owner !== user.username && !isMember(members, user.username)) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      if (!VALID_EQUIPMENT_SLOTS.has(params.slot)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const equipped = playCampaignEquipment.get(params.id, params.character_id, params.slot);

      sendJson(res, 200, {
        character_id: params.character_id,
        slot: params.slot,
        item_id: equipped ? equipped.item_id : '',
        attuned: equipped ? equipped.attuned : false,
      });
    }
  );

  router.post(
    '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot/attune',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      if (!VALID_EQUIPMENT_SLOTS.has(params.slot)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const equipped = playCampaignEquipment.get(params.id, params.character_id, params.slot);
      if (!equipped || !ATTUNABLE_ITEM_IDS.has(equipped.item_id)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const allEquipment = playCampaignEquipment.listByCharacter(params.id, params.character_id);
      const attunementCount = allEquipment.filter((entry) => entry.attuned).length;

      if (equipped.attuned || attunementCount >= MAX_ATTUNEMENTS) {
        sendJson(res, 409, { error: 'attunement limit reached' });
        return;
      }

      const updated = { ...equipped, attuned: true };
      playCampaignEquipment.set(params.id, params.character_id, params.slot, updated);

      sendJson(res, 200, {
        character_id: params.character_id,
        slot: params.slot,
        item_id: updated.item_id,
        attuned: true,
        attunement_count: attunementCount + 1,
        max_attunements: MAX_ATTUNEMENTS,
      });
    }
  );

  router.post('/v1/play/campaigns/:id/loot', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const lootId = body.data && body.data.loot_id;
    const itemId = body.data && body.data.item_id;
    const quantity = body.data && body.data.quantity;
    if (
      typeof lootId !== 'string' ||
      lootId.length === 0 ||
      !VALID_ITEM_IDS.has(itemId) ||
      !Number.isInteger(quantity) ||
      quantity <= 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignLoot.has(params.id, lootId)) {
      sendJson(res, 409, { error: 'loot already exists' });
      return;
    }

    const record = {
      loot_id: lootId,
      item_id: itemId,
      quantity,
      status: 'open',
      recipient_character_id: null,
      votes: 0,
    };
    playCampaignLoot.set(params.id, lootId, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/loot/:loot_id/votes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const loot = playCampaignLoot.get(params.id, params.loot_id);
    if (!loot) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const recipientCharacterId = body.data && body.data.recipient_character_id;
    const recipient = members.find((m) => m.character_id === recipientCharacterId);
    if (typeof recipientCharacterId !== 'string' || recipientCharacterId.length === 0 || !recipient) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignLootVotes.get(params.id, params.loot_id, user.username)) {
      sendJson(res, 409, { error: 'already voted' });
      return;
    }

    playCampaignLootVotes.set(params.id, params.loot_id, user.username, {
      recipient_character_id: recipientCharacterId,
    });

    const votesForRecipient = playCampaignLootVotes
      .listByLoot(params.id, params.loot_id)
      .filter((vote) => vote.recipient_character_id === recipientCharacterId).length;

    sendJson(res, 201, {
      loot_id: params.loot_id,
      voter: user.username,
      recipient_character_id: recipientCharacterId,
      votes_for_recipient: votesForRecipient,
    });
  });

  router.post('/v1/play/campaigns/:id/loot/:loot_id/assign', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const loot = playCampaignLoot.get(params.id, params.loot_id);
    if (!loot) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (loot.status !== 'open') {
      sendJson(res, 409, { error: 'loot not open' });
      return;
    }

    const votes = playCampaignLootVotes.listByLoot(params.id, params.loot_id);
    const tally = new Map();
    for (const vote of votes) {
      tally.set(vote.recipient_character_id, (tally.get(vote.recipient_character_id) || 0) + 1);
    }

    let winner = null;
    let winnerCount = 0;
    let tied = false;
    for (const [recipientCharacterId, count] of tally) {
      if (count > winnerCount) {
        winner = recipientCharacterId;
        winnerCount = count;
        tied = false;
      } else if (count === winnerCount) {
        tied = true;
      }
    }

    if (!winner || tied) {
      sendJson(res, 409, { error: 'no unambiguous recipient' });
      return;
    }

    const existing = playCampaignItems.get(params.id, winner, loot.item_id);
    const totalQuantity = (existing ? existing.quantity : 0) + loot.quantity;
    playCampaignItems.set(params.id, winner, loot.item_id, { item_id: loot.item_id, quantity: totalQuantity });

    const updated = {
      ...loot,
      status: 'assigned',
      recipient_character_id: winner,
      votes: winnerCount,
    };
    playCampaignLoot.set(params.id, params.loot_id, updated);

    sendJson(res, 200, {
      loot_id: updated.loot_id,
      recipient_character_id: updated.recipient_character_id,
      item_id: updated.item_id,
      quantity: updated.quantity,
      votes: updated.votes,
      status: updated.status,
    });
  });

  router.get('/v1/play/campaigns/:id/loot/:loot_id', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const loot = playCampaignLoot.get(params.id, params.loot_id);
    if (!loot) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const voteRecords = playCampaignLootVotes.listByLoot(params.id, params.loot_id);
    const tally = {};
    for (const vote of voteRecords) {
      tally[vote.recipient_character_id] = (tally[vote.recipient_character_id] || 0) + 1;
    }

    sendJson(res, 200, { ...loot, votes: tally });
  });

  router.post('/v1/play/campaigns/:id/npcs', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const npcId = body.data && body.data.npc_id;
    const name = body.data && body.data.name;
    const agenda = body.data && body.data.agenda;
    const publicStatus = body.data && body.data.public_status;
    if (
      typeof npcId !== 'string' ||
      npcId.length === 0 ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof agenda !== 'string' ||
      agenda.length === 0 ||
      typeof publicStatus !== 'string' ||
      publicStatus.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignNpcs.has(params.id, npcId)) {
      sendJson(res, 409, { error: 'npc already exists' });
      return;
    }

    const record = { npc_id: npcId, name, agenda, public_status: publicStatus };
    playCampaignNpcs.set(params.id, npcId, record);
    sendJson(res, 201, record);
  });

  router.put('/v1/play/campaigns/:id/npcs/:npc_id/agenda', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const npc = playCampaignNpcs.get(params.id, params.npc_id);
    if (!npc) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const agenda = body.data && body.data.agenda;
    const publicStatus = body.data && body.data.public_status;
    if (
      typeof agenda !== 'string' ||
      agenda.length === 0 ||
      typeof publicStatus !== 'string' ||
      publicStatus.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const updated = { ...npc, agenda, public_status: publicStatus };
    playCampaignNpcs.set(params.id, params.npc_id, updated);
    sendJson(res, 200, updated);
  });

  router.get('/v1/play/campaigns/:id/npcs/:npc_id', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const npc = playCampaignNpcs.get(params.id, params.npc_id);
    if (!npc) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (isDm) {
      sendJson(res, 200, npc);
      return;
    }

    sendJson(res, 200, { npc_id: npc.npc_id, name: npc.name, public_status: npc.public_status });
  });

  router.post('/v1/play/campaigns/:id/npcs/:npc_id/dialogue', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const npc = playCampaignNpcs.get(params.id, params.npc_id);
    if (!npc) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const dialogueId = body.data && body.data.dialogue_id;
    const speaker = body.data && body.data.speaker;
    const text = body.data && body.data.text;
    const visibility = body.data && body.data.visibility;
    if (
      typeof dialogueId !== 'string' ||
      dialogueId.length === 0 ||
      typeof speaker !== 'string' ||
      speaker.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0 ||
      (visibility !== 'public' && visibility !== 'private')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignNpcDialogue.has(params.id, params.npc_id, dialogueId)) {
      sendJson(res, 409, { error: 'dialogue already exists' });
      return;
    }

    const record = { dialogue_id: dialogueId, speaker, text, visibility };
    playCampaignNpcDialogue.set(params.id, params.npc_id, dialogueId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/npcs/:npc_id/dialogue', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const npc = playCampaignNpcs.get(params.id, params.npc_id);
    if (!npc) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const entries = playCampaignNpcDialogue.listByNpc(params.id, params.npc_id);
    const visibleEntries = isDm ? entries : entries.filter((entry) => entry.visibility === 'public');
    sendJson(res, 200, { npc_id: params.npc_id, entries: visibleEntries });
  });

  router.post('/v1/play/campaigns/:id/relationships', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const sourceId = body.data && body.data.source_id;
    const targetId = body.data && body.data.target_id;
    const kind = body.data && body.data.kind;
    const score = body.data && body.data.score;
    if (
      typeof sourceId !== 'string' ||
      sourceId.length === 0 ||
      typeof targetId !== 'string' ||
      targetId.length === 0 ||
      typeof kind !== 'string' ||
      kind.length === 0 ||
      !Number.isInteger(score) ||
      score < -100 ||
      score > 100 ||
      sourceId === targetId
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (!isCampaignEntity(params.id, sourceId) || !isCampaignEntity(params.id, targetId)) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    if (playCampaignRelationships.has(params.id, sourceId, targetId, kind)) {
      sendJson(res, 409, { error: 'relationship already exists' });
      return;
    }

    const record = { source_id: sourceId, target_id: targetId, kind, score };
    playCampaignRelationships.set(params.id, sourceId, targetId, kind, record);
    sendJson(res, 201, record);
  });

  router.put(
    '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;
      if (user.role !== 'dm' || campaign.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const existing = playCampaignRelationships.get(params.id, params.source_id, params.target_id, params.kind);
      if (!existing) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const score = body.data && body.data.score;
      if (!Number.isInteger(score) || score < -100 || score > 100) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const updated = { ...existing, score };
      playCampaignRelationships.set(params.id, params.source_id, params.target_id, params.kind, updated);
      sendJson(res, 200, updated);
    }
  );

  router.get('/v1/play/campaigns/:id/relationships', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const edges = playCampaignRelationships.listByCampaign(params.id);
    sendJson(res, 200, { edges });
  });

  router.post('/v1/play/campaigns/:id/factions', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const factionId = body.data && body.data.faction_id;
    const name = body.data && body.data.name;
    if (typeof factionId !== 'string' || factionId.length === 0 || typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignFactions.has(params.id, factionId)) {
      sendJson(res, 409, { error: 'faction already exists' });
      return;
    }

    const record = { faction_id: factionId, name };
    playCampaignFactions.set(params.id, factionId, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/factions/:faction_id/reputation', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const faction = playCampaignFactions.get(params.id, params.faction_id);
    if (!faction) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const characterId = body.data && body.data.character_id;
    const delta = body.data && body.data.delta;
    const reason = body.data && body.data.reason;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === characterId);

    if (
      typeof characterId !== 'string' ||
      characterId.length === 0 ||
      !member ||
      !Number.isInteger(delta) ||
      delta === 0 ||
      delta < -25 ||
      delta > 25 ||
      typeof reason !== 'string' ||
      reason.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const current = playCampaignReputation.getTotal(params.id, params.faction_id, characterId);
    const updated = Math.max(-100, Math.min(100, current + delta));
    playCampaignReputation.setTotal(params.id, params.faction_id, characterId, updated);

    const record = { faction_id: params.faction_id, character_id: characterId, reputation: updated, delta, reason };
    playCampaignReputation.addHistory(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/factions/:faction_id/reputation', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const faction = playCampaignFactions.get(params.id, params.faction_id);
    if (!faction) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const entries = playCampaignReputation.listByFaction(params.id, params.faction_id);

    if (isDm) {
      sendJson(res, 200, { faction_id: params.faction_id, entries });
      return;
    }

    const ownMember = members.find((m) => m.username === user.username);
    const ownCharacterId = ownMember ? ownMember.character_id : null;
    const filtered = entries.filter((entry) => entry.character_id === ownCharacterId);
    sendJson(res, 200, { faction_id: params.faction_id, entries: filtered });
  });

  router.post('/v1/play/campaigns/:id/clues', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const clueId = body.data && body.data.clue_id;
    const text = body.data && body.data.text;
    const audience = body.data && body.data.audience;
    const characterId = body.data && body.data.character_id;

    if (typeof clueId !== 'string' || clueId.length === 0 || typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (audience !== 'character' && audience !== 'party' && audience !== 'hidden') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (audience === 'character') {
      if (typeof characterId !== 'string' || characterId.length === 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      const members = playCampaignMembers.listByCampaign(params.id);
      if (!members.some((m) => m.character_id === characterId)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
    } else if (characterId !== undefined) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignClues.has(params.id, clueId)) {
      sendJson(res, 409, { error: 'clue already exists' });
      return;
    }

    const record =
      audience === 'character'
        ? { clue_id: clueId, text, audience, character_id: characterId }
        : { clue_id: clueId, text, audience };

    playCampaignClues.set(params.id, clueId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/clues', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const clues = playCampaignClues.listByCampaign(params.id);
    if (isDm) {
      sendJson(res, 200, { clues });
      return;
    }

    const ownMember = members.find((m) => m.username === user.username);
    const ownCharacterId = ownMember ? ownMember.character_id : null;
    const visible = clues.filter((clue) => {
      if (clue.audience === 'party') return true;
      if (clue.audience === 'character') return clue.character_id === ownCharacterId;
      return false;
    });
    sendJson(res, 200, { clues: visible });
  });

  router.post('/v1/play/campaigns/:id/quests', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const questId = body.data && body.data.quest_id;
    const title = body.data && body.data.title;
    const dependsOn = body.data && body.data.depends_on;

    if (typeof questId !== 'string' || questId.length === 0 || typeof title !== 'string' || title.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (!Array.isArray(dependsOn) || dependsOn.some((dep) => typeof dep !== 'string' || dep.length === 0)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (new Set(dependsOn).size !== dependsOn.length) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (dependsOn.includes(questId)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (dependsOn.some((dep) => !playCampaignQuests.has(params.id, dep))) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignQuests.has(params.id, questId)) {
      sendJson(res, 409, { error: 'quest already exists' });
      return;
    }

    const record = { quest_id: questId, title, depends_on: dependsOn, state: 'locked' };
    playCampaignQuests.set(params.id, questId, record);
    sendJson(res, 201, record);
  });

  router.put('/v1/play/campaigns/:id/quests/:quest_id/state', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const quest = playCampaignQuests.get(params.id, params.quest_id);
    if (!quest) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const state = body.data && body.data.state;
    if (state !== 'active' && state !== 'completed') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (state === 'active') {
      if (quest.state !== 'locked') {
        sendJson(res, 409, { error: 'invalid transition' });
        return;
      }
      const prereqsMet = quest.depends_on.every((dep) => {
        const depQuest = playCampaignQuests.get(params.id, dep);
        return depQuest && depQuest.state === 'completed';
      });
      if (!prereqsMet) {
        sendJson(res, 409, { error: 'prerequisites not met' });
        return;
      }
    } else if (state === 'completed') {
      if (quest.state !== 'active') {
        sendJson(res, 409, { error: 'invalid transition' });
        return;
      }
    }

    quest.state = state;
    playCampaignQuests.set(params.id, params.quest_id, quest);

    sendJson(res, 200, quest);
  });

  router.get('/v1/play/campaigns/:id/quests', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const quests = playCampaignQuests.listByCampaign(params.id);
    sendJson(res, 200, { quests });
  });

  router.put('/v1/play/campaigns/:id/quests/:quest_id/rewards', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const quest = playCampaignQuests.get(params.id, params.quest_id);
    if (!quest) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (quest.state !== 'locked' && quest.state !== 'active') {
      sendJson(res, 409, { error: 'quest already completed' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const xp = body.data && body.data.xp;
    const items = body.data && body.data.items;

    if (!Number.isInteger(xp) || xp < 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (typeof items !== 'object' || items === null || Array.isArray(items)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const itemEntries = Object.entries(items);
    if (
      itemEntries.some(
        ([itemId, quantity]) => !VALID_ITEM_IDS.has(itemId) || !Number.isInteger(quantity) || quantity <= 0
      )
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    quest.rewards = { xp, items };
    playCampaignQuests.set(params.id, params.quest_id, quest);

    sendJson(res, 200, quest);
  });

  router.post('/v1/play/campaigns/:id/quests/:quest_id/rewards/award', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const quest = playCampaignQuests.get(params.id, params.quest_id);
    if (!quest) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (quest.state !== 'completed' || !quest.rewards || quest.rewards_awarded) {
      sendJson(res, 409, { error: 'rewards not available' });
      return;
    }

    const members = playCampaignMembers.listByCampaign(params.id);
    for (const member of members) {
      const existingReward = playCampaignCharacterRewards.get(params.id, member.character_id) || {
        xp: 0,
        items: {},
      };
      const mergedItems = { ...existingReward.items };
      for (const [itemId, quantity] of Object.entries(quest.rewards.items)) {
        mergedItems[itemId] = (mergedItems[itemId] || 0) + quantity;

        const existingStack = playCampaignItems.get(params.id, member.character_id, itemId);
        const totalQuantity = (existingStack ? existingStack.quantity : 0) + quantity;
        playCampaignItems.set(params.id, member.character_id, itemId, {
          item_id: itemId,
          quantity: totalQuantity,
        });
      }
      playCampaignCharacterRewards.set(params.id, member.character_id, {
        xp: existingReward.xp + quest.rewards.xp,
        items: mergedItems,
      });
    }

    quest.rewards_awarded = true;
    playCampaignQuests.set(params.id, params.quest_id, quest);

    sendJson(res, 201, {
      quest_id: quest.quest_id,
      awarded: true,
      xp: quest.rewards.xp,
      items: quest.rewards.items,
    });
  });

  router.get('/v1/play/campaigns/:id/characters/:character_id/rewards', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    const member = members.find((m) => m.character_id === params.character_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const reward = playCampaignCharacterRewards.get(params.id, params.character_id) || { xp: 0, items: {} };
    sendJson(res, 200, { character_id: params.character_id, xp: reward.xp, items: reward.items });
  });

  router.post('/v1/play/campaigns/:id/world-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const eventId = body.data && body.data.event_id;
    const turnNumber = body.data && body.data.turn_number;
    const title = body.data && body.data.title;
    const text = body.data && body.data.text;

    if (
      typeof eventId !== 'string' ||
      eventId.length === 0 ||
      typeof title !== 'string' ||
      title.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0 ||
      !Number.isInteger(turnNumber) ||
      turnNumber < (campaign.turn_number || 0)
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignWorldEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'world event already exists' });
      return;
    }

    const record = {
      event_id: eventId,
      turn_number: turnNumber,
      title,
      text,
      status: 'scheduled',
      resolution: null,
    };
    playCampaignWorldEvents.set(params.id, eventId, record);
    sendJson(res, 201, { event_id: eventId, turn_number: turnNumber, title, text, status: 'scheduled' });
  });

  router.post('/v1/play/campaigns/:id/world-events/:event_id/resolve', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const event = playCampaignWorldEvents.get(params.id, params.event_id);
    if (!event) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const text = body.data && body.data.text;
    if (typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (event.status === 'resolved') {
      sendJson(res, 409, { error: 'world event already resolved' });
      return;
    }
    if ((campaign.turn_number || 0) !== event.turn_number) {
      sendJson(res, 409, { error: 'turn mismatch' });
      return;
    }

    event.status = 'resolved';
    event.resolution = { turn_number: event.turn_number, text };
    playCampaignWorldEvents.set(params.id, params.event_id, event);

    sendJson(res, 201, {
      event_id: event.event_id,
      turn_number: event.turn_number,
      title: event.title,
      text: event.text,
      status: 'resolved',
      resolution: event.resolution,
    });
  });

  router.get('/v1/play/campaigns/:id/world-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const events = playCampaignWorldEvents.listByCampaign(params.id).slice();
    events.sort((a, b) => a.turn_number - b.turn_number);
    const serialized = events.map((event) => {
      const base = {
        event_id: event.event_id,
        turn_number: event.turn_number,
        title: event.title,
        text: event.text,
        status: event.status,
      };
      if (event.status === 'resolved') {
        base.resolution = event.resolution;
      }
      return base;
    });
    sendJson(res, 200, { events: serialized });
  });

  router.post('/v1/play/campaigns/:id/calendar', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const day = body.data && body.data.day;
    const season = body.data && body.data.season;

    if (!Number.isInteger(day) || day < 1 || !SEASON_OFFSETS.has(season)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignCalendar.get(params.id)) {
      sendJson(res, 409, { error: 'calendar already initialized' });
      return;
    }

    const record = { day, season };
    playCampaignCalendar.set(params.id, record);
    sendJson(res, 201, { day, season, weather: calendarWeather(day, season) });
  });

  router.get('/v1/play/campaigns/:id/calendar', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const calendar = playCampaignCalendar.get(params.id);
    if (!calendar) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, {
      day: calendar.day,
      season: calendar.season,
      weather: calendarWeather(calendar.day, calendar.season),
    });
  });

  router.post('/v1/play/campaigns/:id/calendar/advance', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const days = body.data && body.data.days;
    if (!Number.isInteger(days) || days < 1 || days > 30) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const calendar = playCampaignCalendar.get(params.id);
    if (!calendar) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    calendar.day += days;
    playCampaignCalendar.set(params.id, calendar);

    sendJson(res, 200, {
      day: calendar.day,
      season: calendar.season,
      weather: calendarWeather(calendar.day, calendar.season),
    });
  });

  router.post('/v1/play/campaigns/:id/settlements', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const settlementId = body.data && body.data.settlement_id;
    const name = body.data && body.data.name;
    const services = normalizeSettlementServices(body.data && body.data.services);
    const availability = body.data && body.data.availability;

    if (typeof settlementId !== 'string' || settlementId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!services) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!VALID_SETTLEMENT_AVAILABILITY.has(availability)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignSettlements.has(params.id, settlementId)) {
      sendJson(res, 409, { error: 'settlement already exists' });
      return;
    }

    const record = { settlement_id: settlementId, name, services, availability, discovered_by: [] };
    playCampaignSettlements.set(params.id, settlementId, record);
    sendJson(res, 201, record);
  });

  router.put('/v1/play/campaigns/:id/settlements/:settlement_id', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
    if (!settlement) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const name = body.data && body.data.name;
    const services = normalizeSettlementServices(body.data && body.data.services);
    const availability = body.data && body.data.availability;

    if (typeof name !== 'string' || name.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!services) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!VALID_SETTLEMENT_AVAILABILITY.has(availability)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    settlement.name = name;
    settlement.services = services;
    settlement.availability = availability;
    playCampaignSettlements.set(params.id, params.settlement_id, settlement);

    sendJson(res, 200, settlement);
  });

  router.post('/v1/play/campaigns/:id/settlements/:settlement_id/discover', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (isDm || !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
    if (!settlement) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const ownMember = members.find((m) => m.username === user.username);
    const ownCharacterId = ownMember ? ownMember.character_id : null;

    const alreadyDiscovered = settlement.discovered_by.includes(ownCharacterId);
    if (!alreadyDiscovered) {
      settlement.discovered_by.push(ownCharacterId);
      playCampaignSettlements.set(params.id, params.settlement_id, settlement);
    }

    sendJson(res, alreadyDiscovered ? 200 : 201, filterSettlementForCharacter(settlement, ownCharacterId));
  });

  router.get('/v1/play/campaigns/:id/settlements', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const settlements = playCampaignSettlements.listByCampaign(params.id);
    if (isDm) {
      sendJson(res, 200, { settlements });
      return;
    }

    const ownMember = members.find((m) => m.username === user.username);
    const ownCharacterId = ownMember ? ownMember.character_id : null;
    const visible = settlements
      .filter((settlement) => settlement.discovered_by.includes(ownCharacterId))
      .map((settlement) => filterSettlementForCharacter(settlement, ownCharacterId));
    sendJson(res, 200, { settlements: visible });
  });

  router.post('/v1/play/campaigns/:id/settlements/:settlement_id/shops', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
    if (!settlement) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const shop = normalizeShopPayload(body.data);
    if (!shop) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignShops.get(params.id, params.settlement_id, shop.shop_id)) {
      sendJson(res, 409, { error: 'shop already exists' });
      return;
    }

    playCampaignShops.set(params.id, params.settlement_id, shop.shop_id, shop);
    sendJson(res, 201, shop);
  });

  router.get(
    '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const isDm = user.role === 'dm' && campaign.owner === user.username;
      if (!isDm && !isMember(members, user.username)) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
      if (!settlement) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const shop = playCampaignShops.get(params.id, params.settlement_id, params.shop_id);
      if (!shop) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      if (!isDm) {
        const ownMember = members.find((m) => m.username === user.username);
        const ownCharacterId = ownMember ? ownMember.character_id : null;
        if (!settlement.discovered_by.includes(ownCharacterId)) {
          sendJson(res, 404, { error: 'not found' });
          return;
        }
      }

      sendJson(res, 200, shop);
    }
  );

  router.post(
    '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
      if (!settlement) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const shop = playCampaignShops.get(params.id, params.settlement_id, params.shop_id);
      if (!shop) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const characterId = body.data && body.data.character_id;
      const itemId = body.data && body.data.item_id;
      const quantity = body.data && body.data.quantity;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === characterId);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      if (!VALID_ITEM_IDS.has(itemId) || !Number.isInteger(quantity) || quantity <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const heldStock = shop.stock[itemId] || 0;
      const cost = shop.buy_price * quantity;
      const currency = playCampaignCurrency.get(params.id, characterId);
      const gold = currency ? currency.gold : 0;
      if (heldStock < quantity || gold < cost) {
        sendJson(res, 409, { error: 'insufficient stock or funds' });
        return;
      }

      const newStock = heldStock - quantity;
      shop.stock[itemId] = newStock;
      playCampaignShops.set(params.id, params.settlement_id, params.shop_id, shop);

      const newGold = gold - cost;
      playCampaignCurrency.set(params.id, characterId, { character_id: characterId, gold: newGold });

      const existingItem = playCampaignItems.get(params.id, characterId, itemId);
      const newItemQuantity = (existingItem ? existingItem.quantity : 0) + quantity;
      playCampaignItems.set(params.id, characterId, itemId, { item_id: itemId, quantity: newItemQuantity });

      sendJson(res, 200, {
        character_id: characterId,
        item_id: itemId,
        quantity,
        gold: newGold,
        stock: newStock,
      });
    }
  );

  router.post(
    '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const settlement = playCampaignSettlements.get(params.id, params.settlement_id);
      if (!settlement) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const shop = playCampaignShops.get(params.id, params.settlement_id, params.shop_id);
      if (!shop) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const characterId = body.data && body.data.character_id;
      const itemId = body.data && body.data.item_id;
      const quantity = body.data && body.data.quantity;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === characterId);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      if (!VALID_ITEM_IDS.has(itemId) || !Number.isInteger(quantity) || quantity <= 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }

      const existingItem = playCampaignItems.get(params.id, characterId, itemId);
      const heldQuantity = existingItem ? existingItem.quantity : 0;
      if (heldQuantity < quantity) {
        sendJson(res, 409, { error: 'insufficient inventory' });
        return;
      }

      const newItemQuantity = heldQuantity - quantity;
      playCampaignItems.set(params.id, characterId, itemId, { item_id: itemId, quantity: newItemQuantity });

      const proceeds = shop.sell_price * quantity;
      const currency = playCampaignCurrency.get(params.id, characterId);
      const gold = currency ? currency.gold : 0;
      const newGold = gold + proceeds;
      playCampaignCurrency.set(params.id, characterId, { character_id: characterId, gold: newGold });

      const newStock = (shop.stock[itemId] || 0) + quantity;
      shop.stock[itemId] = newStock;
      playCampaignShops.set(params.id, params.settlement_id, params.shop_id, shop);

      sendJson(res, 200, {
        character_id: characterId,
        item_id: itemId,
        quantity,
        gold: newGold,
        stock: newStock,
      });
    }
  );

  router.post('/v1/play/campaigns/:id/recipes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const recipe = normalizeRecipePayload(body.data);
    if (!recipe) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignRecipes.has(params.id, recipe.recipe_id)) {
      sendJson(res, 409, { error: 'recipe already exists' });
      return;
    }

    playCampaignRecipes.set(params.id, recipe.recipe_id, recipe);
    sendJson(res, 201, recipe);
  });

  router.get('/v1/play/campaigns/:id/recipes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const recipes = playCampaignRecipes.listByCampaign(params.id);
    sendJson(res, 200, { recipes });
  });

  router.post('/v1/play/campaigns/:id/recipes/:recipe_id/craft', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const recipe = playCampaignRecipes.get(params.id, params.recipe_id);
    if (!recipe) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const characterId = body.data && body.data.character_id;

    const members = playCampaignMembers.listByCampaign(params.id);
    const member = members.find((m) => m.character_id === characterId);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    for (const [itemId, needed] of Object.entries(recipe.ingredients)) {
      const held = playCampaignItems.get(params.id, characterId, itemId);
      const heldQuantity = held ? held.quantity : 0;
      if (heldQuantity < needed) {
        sendJson(res, 409, { error: 'insufficient ingredients' });
        return;
      }
    }

    for (const [itemId, needed] of Object.entries(recipe.ingredients)) {
      const held = playCampaignItems.get(params.id, characterId, itemId);
      const heldQuantity = held ? held.quantity : 0;
      playCampaignItems.set(params.id, characterId, itemId, {
        item_id: itemId,
        quantity: heldQuantity - needed,
      });
    }

    const existingOutput = playCampaignItems.get(params.id, characterId, recipe.output_item);
    const newOutputQuantity = (existingOutput ? existingOutput.quantity : 0) + recipe.output_quantity;
    playCampaignItems.set(params.id, characterId, recipe.output_item, {
      item_id: recipe.output_item,
      quantity: newOutputQuantity,
    });

    sendJson(res, 201, {
      character_id: characterId,
      recipe_id: params.recipe_id,
      output_item: recipe.output_item,
      output_quantity: recipe.output_quantity,
    });
  });

  router.post('/v1/play/campaigns/:id/downtime/activities', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const activity = normalizeDowntimeActivityPayload(body.data);
    if (!activity) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignDowntimeActivities.has(params.id, activity.activity_id)) {
      sendJson(res, 409, { error: 'activity already exists' });
      return;
    }

    playCampaignDowntimeActivities.set(params.id, activity.activity_id, activity);
    sendJson(res, 201, activity);
  });

  router.post(
    '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const body = await parseJsonBody(req, res);
      if (!body.ok) return;
      const activityId = body.data && body.data.activity_id;

      const activity = playCampaignDowntimeActivities.get(params.id, activityId);
      if (!activity) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      if (playCampaignDowntimeAllocations.get(params.id, params.character_id, activityId)) {
        sendJson(res, 409, { error: 'allocation already exists' });
        return;
      }

      const allocation = {
        character_id: params.character_id,
        activity_id: activityId,
        cycles_completed: 0,
        completions: 0,
      };
      playCampaignDowntimeAllocations.set(params.id, params.character_id, activityId, allocation);
      sendJson(res, 201, allocation);
    }
  );

  router.post(
    '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      if (member.owner !== user.username) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const activity = playCampaignDowntimeActivities.get(params.id, params.activity_id);
      if (!activity) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const allocation = playCampaignDowntimeAllocations.get(params.id, params.character_id, params.activity_id);
      if (!allocation) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      allocation.cycles_completed += 1;
      if (allocation.cycles_completed >= activity.cycles_required) {
        allocation.cycles_completed = 0;
        allocation.completions += 1;
      }

      playCampaignDowntimeAllocations.set(params.id, params.character_id, params.activity_id, allocation);
      sendJson(res, 200, allocation);
    }
  );

  router.get(
    '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id',
    async (req, res, params) => {
      const user = authenticate(req, res);
      if (!user) return;

      const campaign = requireCampaign(res, params.id);
      if (!campaign) return;

      const members = playCampaignMembers.listByCampaign(params.id);
      const isDm = user.role === 'dm' && campaign.owner === user.username;
      if (!isDm && !isMember(members, user.username)) {
        sendJson(res, 403, { error: 'forbidden' });
        return;
      }

      const member = members.find((m) => m.character_id === params.character_id);
      if (!member) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      if (!playCampaignDowntimeActivities.get(params.id, params.activity_id)) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      const allocation = playCampaignDowntimeAllocations.get(params.id, params.character_id, params.activity_id);
      if (!allocation) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }

      sendJson(res, 200, allocation);
    }
  );

  router.put('/v1/play/campaigns/:id/session-zero', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    if (campaign.status !== 'lobby') {
      sendJson(res, 409, { error: 'cannot update session-zero settings' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const rules = body.data && body.data.rules;
    const tone = body.data && body.data.tone;
    const consent = body.data && body.data.consent;
    const consentValid =
      Array.isArray(consent) &&
      consent.length > 0 &&
      consent.every((entry) => typeof entry === 'string' && entry.length > 0) &&
      new Set(consent).size === consent.length;
    if (
      typeof rules !== 'string' ||
      rules.length === 0 ||
      typeof tone !== 'string' ||
      tone.length === 0 ||
      !consentValid
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const record = { rules, tone, consent };
    playCampaignSessionZero.set(params.id, record);
    sendJson(res, 200, record);
  });

  router.get('/v1/play/campaigns/:id/session-zero', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const settings = playCampaignSessionZero.get(params.id);
    if (!settings) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, settings);
  });

  router.post('/v1/play/campaigns/:id/content', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const contentId = body.data && body.data.content_id;
    const kind = body.data && body.data.kind;
    const text = body.data && body.data.text;
    const tags = body.data && body.data.tags;
    const tagsValid =
      Array.isArray(tags) &&
      tags.length > 0 &&
      tags.every((tag) => typeof tag === 'string' && tag.length > 0) &&
      new Set(tags).size === tags.length;
    if (
      typeof contentId !== 'string' ||
      contentId.length === 0 ||
      typeof kind !== 'string' ||
      kind.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0 ||
      !tagsValid
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignContent.has(params.id, contentId)) {
      sendJson(res, 409, { error: 'content already exists' });
      return;
    }

    const record = { content_id: contentId, kind, text, tags };
    playCampaignContent.set(params.id, contentId, record);
    sendJson(res, 201, record);
  });

  router.put('/v1/play/campaigns/:id/content/:content_id/tags', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const record = playCampaignContent.get(params.id, params.content_id);
    if (!record) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const tags = body.data && body.data.tags;
    const tagsValid =
      Array.isArray(tags) &&
      tags.every((tag) => typeof tag === 'string' && tag.length > 0) &&
      new Set(tags).size === tags.length;
    if (!tagsValid) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const updated = { ...record, tags };
    playCampaignContent.set(params.id, params.content_id, updated);
    sendJson(res, 200, updated);
  });

  router.get('/v1/play/campaigns/:id/content', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = user.role === 'dm' && campaign.owner === user.username;
    if (!isDm && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const url = new URL(req.url, 'http://localhost');
    const excludeTag = url.searchParams.get('exclude_tag');
    if (excludeTag !== null && excludeTag.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    let records = playCampaignContent.listByCampaign(params.id);
    if (!isDm && excludeTag) {
      records = records.filter((record) => !record.tags.includes(excludeTag));
    }

    sendJson(res, 200, { content: records });
  });

  router.post('/v1/play/campaigns/:id/notes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const noteId = body.data && body.data.note_id;
    const text = body.data && body.data.text;
    const visibility = body.data && body.data.visibility;
    if (
      typeof noteId !== 'string' ||
      noteId.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0 ||
      (visibility !== 'private' && visibility !== 'party')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignNotes.has(params.id, noteId)) {
      sendJson(res, 409, { error: 'note already exists' });
      return;
    }

    const record = { note_id: noteId, text, visibility, owner: user.username };
    playCampaignNotes.set(params.id, noteId, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/messages', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const text = body.data && body.data.text;
    if (typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const messageId = `msg-${playCampaignMessages.listByCampaign(params.id).length + 1}`;
    const record = { message_id: messageId, kind: 'chat', actor: user.username, text };
    playCampaignMessages.set(params.id, messageId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/notes', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    let notes = playCampaignNotes.listByCampaign(params.id);
    if (!isDm) {
      notes = notes.filter((note) => note.visibility === 'party' || note.owner === user.username);
    }

    sendJson(res, 200, { notes });
  });

  router.get('/v1/play/campaigns/:id/notes/:note_id', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const note = playCampaignNotes.get(params.id, params.note_id);
    if (!note) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (!isDm && note.visibility === 'private' && note.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, note);
  });

  router.put('/v1/play/campaigns/:id/notes/:note_id', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const note = playCampaignNotes.get(params.id, params.note_id);
    if (!note) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (note.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const text = body.data && body.data.text;
    const visibility = body.data && body.data.visibility;
    if (
      typeof text !== 'string' ||
      text.length === 0 ||
      (visibility !== 'private' && visibility !== 'party')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const updated = { note_id: note.note_id, text, visibility, owner: note.owner };
    playCampaignNotes.set(params.id, params.note_id, updated);
    sendJson(res, 200, updated);
  });

  router.post('/v1/play/campaigns/:id/whispers', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const senderMember = members.find((member) => member.username === user.username);
    if (!isDm && !senderMember) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    if (!senderMember) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const whisperId = body.data && body.data.whisper_id;
    const toCharacterId = body.data && body.data.to_character_id;
    const text = body.data && body.data.text;
    if (
      typeof whisperId !== 'string' ||
      whisperId.length === 0 ||
      typeof toCharacterId !== 'string' ||
      toCharacterId.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const toMember = members.find((member) => member.character_id === toCharacterId);
    if (!toMember) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignWhispers.has(params.id, whisperId)) {
      sendJson(res, 409, { error: 'whisper already exists' });
      return;
    }

    const record = {
      whisper_id: whisperId,
      from_character_id: senderMember.character_id,
      to_character_id: toCharacterId,
      text,
    };
    playCampaignWhispers.set(params.id, whisperId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/whispers', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const senderMember = members.find((member) => member.username === user.username);
    if (!isDm && !senderMember) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    let whispers = playCampaignWhispers.listByCampaign(params.id);
    if (!isDm) {
      const characterId = senderMember.character_id;
      whispers = whispers.filter(
        (whisper) => whisper.from_character_id === characterId || whisper.to_character_id === characterId
      );
    }

    sendJson(res, 200, { whispers });
  });

  router.get('/v1/play/campaigns/:id/characters/:character_id/sheet', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    const isDm = campaign.owner === user.username;
    const isMemberUser = isMember(members, user.username);
    if (!isDm && !isMemberUser) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const member = members.find((m) => m.character_id === params.character_id);
    if (!member) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (!isDm && member.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, {
      character_id: member.character_id,
      owner: member.owner,
      name: member.name,
      class: member.class,
      level: 1,
      proficiency_bonus: 2,
      hp_max: 10,
      armor_class: 10,
    });
  });

  router.post('/v1/play/campaigns/:id/invitations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const invitationId = body.data && body.data.invitation_id;
    const targetUsername = body.data && body.data.username;
    const characterId = body.data && body.data.character_id;
    if (
      typeof invitationId !== 'string' ||
      invitationId.length === 0 ||
      typeof targetUsername !== 'string' ||
      targetUsername.length === 0 ||
      typeof characterId !== 'string' ||
      characterId.length === 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const targetUser = users.get(targetUsername);
    if (!targetUser || targetUser.role !== 'player') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignInvitations.has(params.id, invitationId)) {
      sendJson(res, 409, { error: 'invitation already exists' });
      return;
    }

    const invitations = playCampaignInvitations.listByCampaign(params.id);
    const hasActiveInvitation = invitations.some(
      (invitation) => invitation.username === targetUsername && invitation.status === 'pending'
    );
    if (hasActiveInvitation) {
      sendJson(res, 409, { error: 'invitation already pending' });
      return;
    }

    const record = {
      invitation_id: invitationId,
      username: targetUsername,
      character_id: characterId,
      status: 'pending',
    };
    playCampaignInvitations.set(params.id, invitationId, record);
    sendJson(res, 201, record);
  });

  router.post('/v1/play/campaigns/:id/invitations/:invitation_id/accept', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const invitation = playCampaignInvitations.get(params.id, params.invitation_id);
    if (!invitation) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }
    if (invitation.username !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }
    if (invitation.status !== 'pending') {
      sendJson(res, 409, { error: 'invitation already resolved' });
      return;
    }

    const record = {
      username: user.username,
      character_id: invitation.character_id,
      name: user.username,
      class: '',
      hp_max: 20,
      hp_current: 20,
      owner: user.username,
    };
    playCampaignMembers.set(params.id, invitation.character_id, record);
    playCampaignCurrency.set(params.id, invitation.character_id, {
      character_id: invitation.character_id,
      gold: STARTING_GOLD,
    });

    invitation.status = 'accepted';
    playCampaignInvitations.set(params.id, params.invitation_id, invitation);

    sendJson(res, 200, invitation);
  });

  router.get('/v1/play/campaigns/:id/invitations', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const invitations = playCampaignInvitations.listByCampaign(params.id);
    const visible =
      campaign.owner === user.username
        ? invitations
        : invitations.filter((invitation) => invitation.username === user.username);

    sendJson(res, 200, { invitations: visible });
  });

  router.post('/v1/play/campaigns/:id/search-records', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const recordId = body.data && body.data.record_id;
    const text = body.data && body.data.text;
    if (typeof recordId !== 'string' || recordId.length === 0 || typeof text !== 'string' || text.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (playCampaignSearchRecords.has(params.id, recordId)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const existingRecords = playCampaignSearchRecords.listByCampaign(params.id);
    if (existingRecords.some((existing) => existing.text === text)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const record = { record_id: recordId, text };
    playCampaignSearchRecords.set(params.id, recordId, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/search-records', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const url = new URL(req.url, 'http://localhost');
    const q = url.searchParams.get('q');
    const limitParam = url.searchParams.get('limit');
    const cursorParam = url.searchParams.get('cursor');

    let limit = 2;
    if (limitParam !== null) {
      if (!/^-?\d+$/.test(limitParam)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      limit = Number(limitParam);
      if (!Number.isInteger(limit) || limit < 1 || limit > 3) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
    }

    let cursor = 0;
    if (cursorParam !== null) {
      if (!/^-?\d+$/.test(cursorParam)) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
      cursor = Number(cursorParam);
      if (!Number.isInteger(cursor) || cursor < 0) {
        sendJson(res, 400, { error: 'invalid request' });
        return;
      }
    }

    let records = playCampaignSearchRecords.listByCampaign(params.id);
    if (q !== null) {
      const needle = q.toLowerCase();
      records = records.filter((record) => record.text.toLowerCase().includes(needle));
    }

    const page = records.slice(cursor, cursor + limit);
    const nextCursor = cursor + limit < records.length ? cursor + limit : null;

    sendJson(res, 200, { records: page, next_cursor: nextCursor });
  });

  const RATE_EVENT_LIMIT = 2;

  router.post('/v1/play/campaigns/:id/rate-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const eventId = body.data && body.data.event_id;
    if (typeof eventId !== 'string' || eventId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (playCampaignRateEvents.has(params.id, eventId)) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const existingEvents = playCampaignRateEvents.listByCampaign(params.id);
    const actorCount = existingEvents.filter((event) => event.actor === user.username).length;
    const remaining = RATE_EVENT_LIMIT - actorCount;
    if (remaining <= 0) {
      bumpMetric(params.id, 'rejected_rate_events');
      sendJson(res, 429, { limit: RATE_EVENT_LIMIT, remaining: 0 });
      return;
    }

    const record = { event_id: eventId, actor: user.username };
    playCampaignRateEvents.set(params.id, eventId, record);
    bumpMetric(params.id, 'accepted_rate_events');
    sendJson(res, 201, { event_id: eventId, actor: user.username, remaining: remaining - 1 });
  });

  router.get('/v1/play/campaigns/:id/rate-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const events = playCampaignRateEvents.listByCampaign(params.id);
    const actorCount = events.filter((event) => event.actor === user.username).length;
    const remaining = Math.max(0, RATE_EVENT_LIMIT - actorCount);

    sendJson(res, 200, {
      events: events.map((event) => ({ event_id: event.event_id, actor: event.actor })),
      remaining,
    });
  });

  router.get('/v1/play/campaigns/:id/metrics', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    sendJson(res, 200, playCampaignMetrics.get(params.id) || emptyMetrics());
  });

  router.post('/v1/play/campaigns/:id/service-mode', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    if (user.role !== 'dm') {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const maintenance = body.data && body.data.maintenance;
    if (typeof maintenance !== 'boolean') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    setMaintenance(maintenance);
    sendJson(res, 200, { maintenance });
  });

  router.put('/v1/play/campaigns/:id/safety-boundaries', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    if (campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const tags = normalizeUniqueStringArray(parsed.data && parsed.data.blocked_tags);
    if (!tags) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const sorted = [...tags].sort();
    playCampaignSafetyBoundaries.set(params.id, { blocked_tags: sorted });

    sendJson(res, 200, { blocked_tags: sorted });
  });

  router.get('/v1/play/campaigns/:id/safety-boundaries', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const boundaries = playCampaignSafetyBoundaries.get(params.id) || { blocked_tags: [] };
    sendJson(res, 200, boundaries);
  });

  router.post('/v1/play/campaigns/:id/safety-checks', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const parsed = await parseJsonBody(req, res);
    if (!parsed.ok) return;
    const body = parsed.data;
    const eventId = body && body.event_id;
    const kind = body && body.kind;
    const text = body && body.text;
    const tags = normalizeUniqueStringArray(body && body.tags);

    if (
      typeof eventId !== 'string' ||
      eventId.length === 0 ||
      typeof text !== 'string' ||
      text.length === 0 ||
      (kind !== 'narration' && kind !== 'chat') ||
      !tags
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    if (playCampaignSafetyEvents.has(params.id, eventId)) {
      sendJson(res, 409, { error: 'event_id already exists' });
      return;
    }

    const boundaries = playCampaignSafetyBoundaries.get(params.id) || { blocked_tags: [] };
    const blocked = new Set(boundaries.blocked_tags);
    if (tags.some((tag) => blocked.has(tag))) {
      sendJson(res, 409, { error: 'blocked tag' });
      return;
    }

    const sequence = playCampaignSafetyEvents.countByCampaign(params.id) + 1;
    const record = { event_id: eventId, kind, text, tags, sequence };
    playCampaignSafetyEvents.add(params.id, record);

    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/safety-events', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const events = playCampaignSafetyEvents.listByCampaign(params.id);
    sendJson(res, 200, { events });
  });

  function canonicalFixtureState() {
    return {
      fixture_id: 'canonical-v1',
      status: 'seeded',
      characters: [
        { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
        { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' },
      ],
      story: 'The lantern is lit.',
      event_ids: ['fixture-event-1', 'fixture-event-2'],
    };
  }

  router.post('/v1/play/campaigns/:id/fixture-seeds', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;
    if (user.role !== 'dm' || campaign.owner !== user.username) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const fixtureId = body.data && body.data.fixture_id;
    if (typeof fixtureId !== 'string' || fixtureId !== 'canonical-v1') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }

    const existing = playCampaignFixtureSeeds.get(params.id);
    if (existing) {
      sendJson(res, 200, existing);
      return;
    }

    const record = canonicalFixtureState();
    playCampaignFixtureSeeds.set(params.id, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/play/campaigns/:id/fixture-state', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const members = playCampaignMembers.listByCampaign(params.id);
    if (campaign.owner !== user.username && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    const record = playCampaignFixtureSeeds.get(params.id);
    if (!record) {
      sendJson(res, 404, { error: 'not found' });
      return;
    }

    sendJson(res, 200, record);
  });

  router.get('/v1/play/campaigns/:id/onboarding', async (req, res, params) => {
    const user = authenticate(req, res);
    if (!user) return;

    const campaign = requireCampaign(res, params.id);
    if (!campaign) return;

    const isOwner = campaign.owner === user.username;
    const members = playCampaignMembers.listByCampaign(params.id);
    if (!isOwner && !isMember(members, user.username)) {
      sendJson(res, 403, { error: 'forbidden' });
      return;
    }

    if (isOwner) {
      sendJson(res, 200, {
        role: 'dm',
        next_steps: ['configure-safety', 'invite-players', 'start-campaign'],
        can_mutate: true,
      });
    } else {
      sendJson(res, 200, {
        role: 'player',
        next_steps: ['review-party', 'take-turn', 'submit-action'],
        can_mutate: true,
      });
    }
  });
}
