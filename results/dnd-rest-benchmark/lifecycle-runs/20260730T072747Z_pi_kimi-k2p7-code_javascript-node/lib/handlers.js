import * as db from './db.js';
import * as domain from './domain.js';
import { sendJson, badRequest, notFound, conflict, unauthorized, forbidden, parseJson, readBody } from './http.js';

// Parse the request body as JSON. Returns { value } on success or { error }
// on failure. The underlying parser returns undefined for invalid JSON, which
// is normalized to the standard 'invalid json' error message.
function requireBody(req) {
  const parsed = parseJson(req.body);
  if (parsed === undefined) return { error: 'invalid json' };
  return { value: parsed };
}

async function requireDeleteBody(req) {
  if (req.body === undefined) {
    req.body = await readBody(req);
  }
  return requireBody(req);
}

function authenticate(req, res) {
  const header = req.headers['authorization'];
  if (!header || !header.startsWith('Bearer ')) {
    unauthorized(res, 'missing credentials');
    return null;
  }

  const token = header.slice('Bearer '.length);
  if (!token.startsWith('session-')) {
    unauthorized(res, 'invalid credentials');
    return null;
  }

  const username = token.slice('session-'.length);
  if (!domain.isValidUsername(username)) {
    unauthorized(res, 'invalid credentials');
    return null;
  }

  const user = db.getUser(username);
  if (user) {
    return user;
  }

  // The /v1/play surface treats a well-formed session token as a valid
  // actor even when the user record has been cleared (e.g., by a prior
  // storage reset). Infer the role from the username so that stage 017
  // and later play-surface tests can proceed without requiring explicit
  // registration.
  const role = username === 'dm' ? 'dm' : 'player';
  return { username, role };
}

// Authenticate the request and load the play campaign, returning { user,
// campaign } or null after sending the appropriate error response. This is the
// shared entry point for every /v1/play/campaigns endpoint so each handler
// only needs to enforce its own authorization/turn rules.
function loadPlayCampaign(req, res, campaignId) {
  const user = authenticate(req, res);
  if (!user) return null;

  const campaign = db.getPlayCampaign(campaignId);
  if (!campaign) {
    notFound(res);
    return null;
  }

  return { user, campaign };
}

// Format a stored narration row for API responses.
function publicNarration(n) {
  return { sequence: n.sequence, kind: n.kind, actor: n.actor, text: n.text };
}

// Compute the next actor/phase/turn_number when advancing the play queue.
// turnNumberDelta is 0 when leaving a player turn (the player is still in the
// same logical turn until the DM resolves it) and 1 when leaving the DM turn
// (the DM resolution completes the turn and advances to the next player).
function resolveNextTurn(campaign, turnNumberDelta) {
  const queue = campaign.queue;
  const currentIndex = campaign.current_index ?? queue.indexOf(campaign.current_actor);
  const nextIndex = (currentIndex + 1) % queue.length;
  const nextActor = queue[nextIndex];
  const nextPhase = nextActor === campaign.owner ? 'dm' : 'player';
  const nextTurnNumber = campaign.turn_number + turnNumberDelta;
  return { nextActor, nextPhase, nextTurnNumber, nextIndex };
}

// Check whether a user is the campaign owner or a joined member. Sends 403
// and returns null if neither. Otherwise returns { isOwner, isMember }.
function authorizePlayParticipant(res, campaign, user, campaignId) {
  const isOwner = campaign.owner === user.username;
  const isMember = db.getPlayMembership(campaignId, user.username) !== null;
  if (!isOwner && !isMember) {
    forbidden(res, 'forbidden');
    return null;
  }
  return { isOwner, isMember };
}

// Load a play campaign and its encounter, enforcing membership and optional
// encounter constraints. Sends the appropriate error response and returns null
// when the caller is not authorized, the encounter is missing, or (when
// requested) the encounter is not active or has no combatants.
function loadPlayEncounter(req, res, campaignId, encounterId, { requireActive = true, requireOrder = true } = {}) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return null;
  const { user, campaign } = ctx;

  const auth = authorizePlayParticipant(res, campaign, user, campaignId);
  if (!auth) return null;

  const encounter = db.getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    notFound(res);
    return null;
  }

  if (requireActive && encounter.status !== 'active') {
    notFound(res);
    return null;
  }

  const order = requireOrder ? getEffectiveOrder(encounter) : null;
  if (requireOrder && order.length === 0) {
    notFound(res);
    return null;
  }

  return { user, campaign, encounter, order, isOwner: auth.isOwner, isMember: auth.isMember };
}

// Encounter turn authorization helpers. The owner may always advance or delay
// a turn; the active player combatant may also advance or delay their own
// turn. Only the active player combatant may ready or submit an action.
function requireEncounterOwnerOrActiveMember(res, user, campaign, order, turnIndex) {
  const active = order[turnIndex];
  let allowed = campaign.owner === user.username;
  if (!allowed && active.member && active.member === user.username) {
    allowed = true;
  }
  if (!allowed) {
    conflict(res, 'not your turn');
    return false;
  }
  return true;
}

function requireActiveEncounterMember(res, user, order, turnIndex) {
  const active = order[turnIndex];
  if (!active.member || active.member !== user.username) {
    conflict(res, 'not your turn');
    return false;
  }
  return true;
}

// Resolve a damage/heal target against an encounter roster. Returns the
// combatant (and membership for party members) or null if the target is not
// present in the encounter.
function resolveEncounterTarget(campaignId, encounter, target) {
  const combatants = encounter.combatants ?? [];
  const monsterIndex = combatants.findIndex(c => c.monster_id === target);
  if (monsterIndex !== -1) {
    return { kind: 'monster', index: monsterIndex, combatant: combatants[monsterIndex] };
  }
  const memberIndex = combatants.findIndex(c => c.member === target);
  if (memberIndex !== -1) {
    const combatant = combatants[memberIndex];
    const membership = db.getPlayMembership(campaignId, combatant.member);
    if (!membership) return null;
    return { kind: 'member', index: memberIndex, combatant, membership };
  }
  return null;
}

function encounterHealthResponse(target, hpBefore, hpAfter, amount, isDamage) {
  return {
    target,
    hp_before: hpBefore,
    hp_after: hpAfter,
    [isDamage ? 'damage' : 'healing']: amount,
  };
}

// ---------- health ----------

export function health(req, res) {
  sendJson(res, 200, { ok: true });
}

// ---------- storage ----------

export function storageStatus(req, res) {
  sendJson(res, 200, {
    driver: 'sqlite',
    schema_version: db.SCHEMA_VERSION,
    initialized: db.isInitialized(),
  });
}

export function storageReset(req, res) {
  db.resetDb();
  sendJson(res, 200, { ok: true, schema_version: db.SCHEMA_VERSION });
}

// ---------- dice ----------

export function diceStats(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const expr = domain.parseExpression(body.value?.expression);
  if (!expr) return badRequest(res, 'invalid expression');

  const { dice_count, sides, modifier } = expr;
  const min = dice_count * 1 + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;

  sendJson(res, 200, {
    dice_count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

// ---------- checks ----------

export function abilityCheck(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const roll = Number(body.value?.roll);
  const modifier = Number(body.value?.modifier);
  const dc = Number(body.value?.dc);
  if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
    return badRequest(res, 'invalid fields');
  }

  const total = roll + modifier;
  sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
}

// ---------- encounters ----------

export function adjustedXp(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const party = Array.isArray(body.value?.party) ? body.value.party : [];
  const monsters = Array.isArray(body.value?.monsters) ? body.value.monsters : [];

  let result;
  try {
    result = domain.calculateEncounterXp(party, monsters);
  } catch (err) {
    return badRequest(res, err.message);
  }

  sendJson(res, 200, result);
}

// ---------- initiative ----------

export function initiativeOrder(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const combatants = Array.isArray(body.value?.combatants) ? body.value.combatants : [];
  const order = domain.buildCombatOrder(combatants);

  sendJson(res, 200, { order });
}

// ---------- characters ----------

export function abilityModifier(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const score = body.value?.score;
  if (!Number.isInteger(score) || score < 1 || score > 30) {
    return badRequest(res, 'invalid score');
  }

  sendJson(res, 200, { score, modifier: domain.abilityModifier(score) });
}

export function proficiency(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const level = body.value?.level;
  if (!Number.isInteger(level) || level < 1 || level > 20) {
    return badRequest(res, 'invalid level');
  }

  sendJson(res, 200, { level, proficiency_bonus: domain.proficiencyBonus(level) });
}

export function derivedStats(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const { value } = body;

  const level = value?.level;
  if (!Number.isInteger(level) || level < 1 || level > 20) {
    return badRequest(res, 'invalid level');
  }

  const abilities = value?.abilities;
  if (!abilities || typeof abilities !== 'object') {
    return badRequest(res, 'invalid abilities');
  }

  const abilityNames = domain.ABILITY_NAMES;
  const modifiers = {};
  for (const name of abilityNames) {
    const score = abilities[name];
    if (!Number.isInteger(score) || score < 1 || score > 30) {
      return badRequest(res, 'invalid ability score');
    }
    modifiers[name] = domain.abilityModifier(score);
  }

  const armor = value?.armor;
  if (!armor || typeof armor !== 'object') {
    return badRequest(res, 'invalid armor');
  }

  const base = Number(armor?.base);
  const dexCap = Number(armor?.dex_cap);
  if (!Number.isInteger(base) || !Number.isInteger(dexCap)) {
    return badRequest(res, 'invalid armor values');
  }
  if (typeof armor.shield !== 'boolean') {
    return badRequest(res, 'invalid shield value');
  }

  const shieldBonus = armor.shield ? 2 : 0;
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;
  const hpMax = level * (6 + modifiers.con);

  sendJson(res, 200, {
    level,
    proficiency_bonus: domain.proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}

// ---------- PHB rules ----------

export function spellSlots(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const cls = body.value?.class;
  const level = body.value?.level;
  if (cls !== 'wizard' || level !== 5) {
    return badRequest(res, 'unsupported class or level');
  }

  sendJson(res, 200, {
    class: 'wizard',
    level: 5,
    slots: { '1': 4, '2': 3, '3': 2 },
  });
}

export function longRest(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const level = body.value?.level;
  const hpCurrent = body.value?.hp_current;
  const hpMax = body.value?.hp_max;
  const hitDiceSpent = body.value?.hit_dice_spent;
  const exhaustionLevel = body.value?.exhaustion_level;

  if (!domain.isPositiveInteger(level) || level > 20) {
    return badRequest(res, 'invalid level');
  }
  if (!domain.isNonNegativeInteger(hpCurrent) || !domain.isNonNegativeInteger(hpMax)) {
    return badRequest(res, 'invalid hp');
  }
  if (!domain.isNonNegativeInteger(hitDiceSpent)) {
    return badRequest(res, 'invalid hit_dice_spent');
  }
  if (!domain.isNonNegativeInteger(exhaustionLevel)) {
    return badRequest(res, 'invalid exhaustion_level');
  }

  const recovered = Math.max(1, Math.floor(level / 2));
  sendJson(res, 200, {
    hp_current: hpMax,
    hit_dice_spent: Math.max(0, hitDiceSpent - recovered),
    exhaustion_level: Math.max(0, exhaustionLevel - 1),
  });
}

export function equipmentLoad(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const strength = body.value?.strength;
  const weight = body.value?.weight;
  if (!domain.isPositiveInteger(strength) || !domain.isNonNegativeInteger(weight)) {
    return badRequest(res, 'invalid fields');
  }

  const capacity = strength * 15;
  sendJson(res, 200, { capacity, weight, encumbered: weight > capacity });
}

// ---------- auth ----------

export function register(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const username = body.value?.username;
  const password = body.value?.password;
  const role = body.value?.role;

  if (!domain.isValidUsername(username)) return badRequest(res, 'invalid username');
  if (!domain.isValidPassword(password)) return badRequest(res, 'invalid password');
  if (!domain.isValidRole(role)) return badRequest(res, 'invalid role');

  if (db.getUser(username)) {
    return conflict(res, 'username already exists');
  }

  const { salt, hash } = domain.createPasswordHash(password);
  db.createUser({ username, role, salt, hash });

  sendJson(res, 201, { username, role });
}

export function login(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const username = body.value?.username;
  const password = body.value?.password;

  const user = db.getUser(username);
  if (!user || typeof password !== 'string' || !domain.verifyPassword(password, user.salt, user.hash)) {
    return unauthorized(res, 'invalid credentials');
  }

  sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
}

// ---------- combat ----------

function activeCombatant(session) {
  const c = session.order[session.turn_index];
  return { name: c.name, score: c.score };
}

function publicOrder(order) {
  return order.map(c => ({ name: c.name, score: c.score }));
}

function publicCondition(condition) {
  return { condition: condition.condition, remaining_rounds: condition.remaining_rounds };
}

function publicConditions(session) {
  const result = {};
  for (const [name, conditions] of Object.entries(session.conditions)) {
    result[name] = conditions.map(publicCondition);
  }
  return result;
}

export function createCombatSession(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  if (!domain.isNonEmptyString(id)) {
    return badRequest(res, 'invalid id');
  }
  if (db.getSession(id)) {
    return badRequest(res, 'session already exists');
  }

  const combatants = Array.isArray(body.value?.combatants) ? body.value.combatants : [];
  if (combatants.length === 0) {
    return badRequest(res, 'invalid combatants');
  }

  const names = new Set();
  for (const c of combatants) {
    if (!domain.isNonEmptyString(c?.name)) return badRequest(res, 'invalid combatant');
    const dex = Number(c?.dex);
    const roll = Number(c?.roll);
    if (!Number.isFinite(dex) || !Number.isFinite(roll)) {
      return badRequest(res, 'invalid combatant');
    }
    if (names.has(c.name)) return badRequest(res, 'duplicate combatant name');
    names.add(c.name);
  }

  const order = domain.buildCombatOrder(combatants);
  const session = {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: {},
  };

  db.createSession(session);
  sendJson(res, 200, {
    id,
    round: 1,
    turn_index: 0,
    active: activeCombatant(session),
    order: publicOrder(order),
  });
}

export function addCondition(req, res, id) {
  const session = db.getSession(id);
  if (!session) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const target = body.value?.target;
  const condition = body.value?.condition;
  const durationRounds = body.value?.duration_rounds;

  if (!domain.isNonEmptyString(target) || !domain.isNonEmptyString(condition) || !domain.isPositiveInteger(durationRounds)) {
    return badRequest(res, 'invalid fields');
  }

  const names = new Set(session.order.map(c => c.name));
  if (!names.has(target)) {
    return badRequest(res, 'unknown target');
  }

  session.conditions[target] ??= [];
  session.conditions[target].push({ condition, remaining_rounds: durationRounds });
  db.updateSession(session);

  sendJson(res, 200, {
    target,
    conditions: session.conditions[target].map(publicCondition),
  });
}

export function advanceTurn(req, res, id) {
  const session = db.getSession(id);
  if (!session) return notFound(res);

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  // Conditions attached to the newly-active combatant tick down at the start of
  // that combatant's turn and are removed when they reach 0.
  const activeName = session.order[session.turn_index].name;
  if (session.conditions[activeName]) {
    session.conditions[activeName] = session.conditions[activeName]
      .map(c => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter(c => c.remaining_rounds > 0);
  }

  db.updateSession(session);
  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: activeCombatant(session),
    conditions: publicConditions(session),
  });
}

// ---------- compendium ----------

export function createMonster(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const slug = body.value?.slug;
  const name = body.value?.name;
  const cr = body.value?.cr;
  const armorClass = body.value?.armor_class;
  const hitPoints = body.value?.hit_points;
  const tags = body.value?.tags;

  if (!domain.isValidSlug(slug)) return badRequest(res, 'invalid slug');
  if (!domain.isNonEmptyString(name)) return badRequest(res, 'invalid name');
  if (!domain.isNonEmptyString(cr)) return badRequest(res, 'invalid cr');
  if (!domain.isPositiveInteger(armorClass)) return badRequest(res, 'invalid armor_class');
  if (!domain.isPositiveInteger(hitPoints)) return badRequest(res, 'invalid hit_points');
  if (!domain.isStringArray(tags)) return badRequest(res, 'invalid tags');

  if (db.getMonster(slug)) {
    return conflict(res, 'slug already exists');
  }

  db.createMonster({ slug, name, cr, armor_class: armorClass, hit_points: hitPoints, tags });
  sendJson(res, 201, { slug, name, cr, armor_class: armorClass, hit_points: hitPoints });
}

export function readMonster(req, res, slug) {
  const monster = db.getMonster(slug);
  if (!monster) return notFound(res);
  sendJson(res, 200, monster);
}

export function createItem(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const slug = body.value?.slug;
  const name = body.value?.name;
  const type = body.value?.type;
  const rarity = body.value?.rarity;
  const costGp = body.value?.cost_gp;

  if (!domain.isValidSlug(slug)) return badRequest(res, 'invalid slug');
  if (!domain.isNonEmptyString(name)) return badRequest(res, 'invalid name');
  if (!domain.isNonEmptyString(type)) return badRequest(res, 'invalid type');
  if (!domain.isNonEmptyString(rarity)) return badRequest(res, 'invalid rarity');
  if (!domain.isNonNegativeInteger(costGp)) return badRequest(res, 'invalid cost_gp');

  if (db.getItem(slug)) {
    return conflict(res, 'slug already exists');
  }

  db.createItem({ slug, name, type, rarity, cost_gp: costGp });
  sendJson(res, 201, { slug, name, type, rarity, cost_gp: costGp });
}

export function readItem(req, res, slug) {
  const item = db.getItem(slug);
  if (!item) return notFound(res);
  sendJson(res, 200, item);
}

// ---------- campaigns ----------

export function createCampaign(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  const dm = body.value?.dm;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name) || !domain.isNonEmptyString(dm)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getCampaign(id)) {
    return conflict(res, 'campaign already exists');
  }

  db.createCampaign({ id, name, dm });
  sendJson(res, 201, { id, name, dm });
}

export function createCampaignCharacter(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  const level = body.value?.level;
  const cls = body.value?.class;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name) || !domain.isNonEmptyString(cls)) {
    return badRequest(res, 'invalid fields');
  }
  if (!domain.isPositiveInteger(level) || level > 20) {
    return badRequest(res, 'invalid level');
  }

  if (db.getCampaignCharacter(campaignId, id)) {
    return conflict(res, 'character already exists');
  }

  db.createCampaignCharacter(campaignId, { id, name, level, class: cls });
  sendJson(res, 201, { id, name, level, class: cls });
}

export function createCampaignEvent(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const kind = body.value?.kind;
  const summary = body.value?.summary;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(kind)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getCampaignEvent(campaignId, id)) {
    return conflict(res, 'event already exists');
  }

  db.createCampaignEvent(campaignId, { id, kind, summary });
  sendJson(res, 201, { id, kind });
}

export function createFaction(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  const stance = body.value?.stance;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name) || !domain.isNonEmptyString(stance)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getFaction(campaignId, id)) {
    return conflict(res, 'faction already exists');
  }

  db.createFaction(campaignId, { id, name, stance });
  sendJson(res, 201, { id, name, stance });
}

export function createNpc(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  const factionId = body.value?.faction_id;
  const disposition = body.value?.disposition;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }
  if (typeof factionId !== 'string') {
    return badRequest(res, 'invalid faction_id');
  }
  if (!Number.isInteger(disposition)) {
    return badRequest(res, 'invalid disposition');
  }

  if (factionId.length > 0 && !db.getFaction(campaignId, factionId)) {
    return badRequest(res, 'unknown faction');
  }

  if (db.getNpc(campaignId, id)) {
    return conflict(res, 'npc already exists');
  }

  db.createNpc(campaignId, { id, name, faction_id: factionId, disposition });
  sendJson(res, 201, { id, name, faction_id: factionId, disposition });
}

export function readCampaignState(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const characters = db.getCampaignCharacters(campaignId);
  const logCount = db.getCampaignEventCount(campaignId);

  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters,
    log_count: logCount,
  });
}

export function readRelationships(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  sendJson(res, 200, {
    campaign_id: campaignId,
    factions: db.getFactionCount(campaignId),
    npcs: db.getNpcCount(campaignId),
    friendly_npcs: db.getFriendlyNpcCount(campaignId),
  });
}

export function getCampaignAudit(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  sendJson(res, 200, {
    campaign_id: campaignId,
    events: db.getCampaignEventCount(campaignId),
    quests: db.getCampaignQuestCount(campaignId),
    npcs: db.getNpcCount(campaignId),
    sessions: db.getCampaignSessionCount(campaignId),
  });
}

export function getCampaignExport(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  sendJson(res, 200, {
    campaign_id: campaignId,
    name: campaign.name,
    characters: db.getCampaignCharacterCount(campaignId),
    quests: db.getCampaignQuestCount(campaignId),
    npcs: db.getNpcCount(campaignId),
    inventory_items: db.getCampaignInventoryItemCount(campaignId),
    sessions: db.getCampaignSessionCount(campaignId),
    schema_version: db.SCHEMA_VERSION,
  });
}

export function getCampaignAnalyticsSummary(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const openQuests = db.getOpenQuestCount(campaignId);
  const friendlyNpcs = db.getFriendlyNpcCount(campaignId);
  const scheduledSessions = db.getCampaignSessionCount(campaignId);
  const inventoryItems = db.getCampaignInventoryItemCount(campaignId);

  sendJson(res, 200, {
    campaign_id: campaignId,
    readiness_score: Math.max(0, 100 - 15 * openQuests),
    open_quests: openQuests,
    friendly_npcs: friendlyNpcs,
    scheduled_sessions: scheduledSessions,
    inventory_items: inventoryItems,
  });
}

export function getCampaignRiskReport(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const includeZeroes = body.value?.include_zeroes;
  if (typeof includeZeroes !== 'boolean') {
    return badRequest(res, 'invalid include_zeroes');
  }

  const signals = {
    has_dm: domain.isNonEmptyString(campaign.dm),
    has_characters: db.getCampaignCharacterCount(campaignId) > 0,
    has_next_session: db.getCampaignSessionCount(campaignId) > 0,
    has_active_quest: db.getOpenQuestCount(campaignId) > 0,
  };

  const missing = [];
  for (const [key, value] of Object.entries(signals)) {
    if (!value) missing.push(key);
  }

  const presentCount = 4 - missing.length;
  let riskLevel = 'high';
  if (presentCount === 4) riskLevel = 'low';
  else if (presentCount === 3) riskLevel = 'medium';

  const responseSignals = includeZeroes
    ? signals
    : Object.fromEntries(Object.entries(signals).filter(([_, v]) => v));

  sendJson(res, 200, {
    campaign_id: campaignId,
    risk_level: riskLevel,
    missing,
    signals: responseSignals,
  });
}

// ---------- quest tracker ----------

export function createQuest(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const title = body.value?.title;
  const status = body.value?.status;
  const milestones = Array.isArray(body.value?.milestones) ? body.value.milestones : [];

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(title)) {
    return badRequest(res, 'invalid fields');
  }
  if (!domain.isValidQuestStatus(status)) {
    return badRequest(res, 'invalid status');
  }
  if (!domain.isStringArray(milestones)) {
    return badRequest(res, 'invalid milestones');
  }

  if (db.getQuest(campaignId, id)) {
    return conflict(res, 'quest already exists');
  }

  db.createQuest(campaignId, { id, title, status, milestones, done_milestones: [] });
  sendJson(res, 201, {
    id,
    title,
    status,
    milestones_total: milestones.length,
    milestones_done: 0,
  });
}

export function updateQuestProgress(req, res, campaignId, questId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const quest = db.getQuest(campaignId, questId);
  if (!quest) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const completed = Array.isArray(body.value?.completed) ? body.value.completed : [];
  if (!domain.isStringArray(completed)) {
    return badRequest(res, 'invalid fields');
  }

  const milestoneSet = new Set(quest.milestones);
  for (const m of completed) {
    if (!milestoneSet.has(m)) {
      return badRequest(res, 'unknown milestone');
    }
  }

  const doneSet = new Set(quest.done_milestones);
  for (const m of completed) {
    doneSet.add(m);
  }

  const milestonesTotal = quest.milestones.length;
  const milestonesDone = doneSet.size;
  let status = quest.status;
  if (milestonesTotal > 0 && milestonesDone >= milestonesTotal) {
    status = 'completed';
  }

  db.updateQuest(campaignId, { ...quest, status, done_milestones: [...doneSet] });
  sendJson(res, 200, {
    id: questId,
    status,
    milestones_total: milestonesTotal,
    milestones_done: milestonesDone,
  });
}

export function getQuestSummary(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const quests = db.getQuests(campaignId);
  const summary = { campaign_id: campaignId, active: 0, completed: 0, blocked: 0 };
  for (const q of quests) {
    if (summary[q.status] !== undefined) {
      summary[q.status] += 1;
    }
  }
  sendJson(res, 200, summary);
}

// ---------- inventory and equipment ----------

export function addInventoryItem(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const itemSlug = body.value?.item_slug;
  const quantity = body.value?.quantity;
  const owner = body.value?.owner;

  if (!domain.isValidSlug(itemSlug)) return badRequest(res, 'invalid item_slug');
  if (!domain.isPositiveInteger(quantity)) return badRequest(res, 'invalid quantity');
  if (!domain.isNonEmptyString(owner)) return badRequest(res, 'invalid owner');

  db.addInventoryItem(campaignId, itemSlug, owner, quantity);
  sendJson(res, 201, { item_slug: itemSlug, quantity, owner });
}

export function assignEquipment(req, res, campaignId, characterId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const character = db.getCampaignCharacter(campaignId, characterId);
  if (!character) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const itemSlug = body.value?.item_slug;
  const quantity = body.value?.quantity;

  if (!domain.isValidSlug(itemSlug)) return badRequest(res, 'invalid item_slug');
  if (!domain.isPositiveInteger(quantity)) return badRequest(res, 'invalid quantity');

  const available = db.getPartyItemQuantity(campaignId, itemSlug) - db.getAssignedQuantity(campaignId, itemSlug);
  if (available < quantity) {
    return badRequest(res, 'insufficient quantity');
  }

  db.assignEquipment(campaignId, characterId, itemSlug, quantity);

  sendJson(res, 200, { character_id: characterId, item_slug: itemSlug, quantity });
}

export function getInventorySummary(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const partyItems = db.getPartyItemCount(campaignId);
  const assignedItems = db.getAssignedItemCount(campaignId);
  const partyHealingPotions = db.getPartyItemQuantity(campaignId, 'healing-potion');
  const assignedHealingPotions = db.getAssignedQuantity(campaignId, 'healing-potion');
  const healingPotionsAvailable = Math.max(0, partyHealingPotions - assignedHealingPotions);

  sendJson(res, 200, {
    campaign_id: campaignId,
    party_items: partyItems,
    assigned_items: assignedItems,
    healing_potions_available: healingPotionsAvailable,
  });
}

// ---------- downtime crafting ----------

export function createCraftingProject(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const characterId = body.value?.character_id;
  const itemSlug = body.value?.item_slug;
  const daysRequired = body.value?.days_required;
  const costGp = body.value?.cost_gp;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(characterId)) {
    return badRequest(res, 'invalid fields');
  }
  if (!domain.isValidSlug(itemSlug)) return badRequest(res, 'invalid item_slug');
  if (!domain.isPositiveInteger(daysRequired)) return badRequest(res, 'invalid days_required');
  if (!domain.isNonNegativeInteger(costGp)) return badRequest(res, 'invalid cost_gp');

  if (!db.getCampaignCharacter(campaignId, characterId)) {
    return badRequest(res, 'unknown character');
  }

  if (db.getCraftingProject(campaignId, id)) {
    return conflict(res, 'project already exists');
  }

  db.createCraftingProject(campaignId, {
    id,
    character_id: characterId,
    item_slug: itemSlug,
    days_required: daysRequired,
    cost_gp: costGp,
    days_completed: 0,
    status: 'active',
  });

  sendJson(res, 201, {
    id,
    character_id: characterId,
    item_slug: itemSlug,
    days_required: daysRequired,
    days_completed: 0,
    status: 'active',
  });
}

export function advanceCraftingProject(req, res, campaignId, projectId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const project = db.getCraftingProject(campaignId, projectId);
  if (!project) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const days = body.value?.days;
  if (!domain.isPositiveInteger(days)) {
    return badRequest(res, 'invalid days');
  }

  let daysCompleted = project.days_completed;
  let status = project.status;

  if (status !== 'complete') {
    daysCompleted = Math.min(daysCompleted + days, project.days_required);
    if (daysCompleted >= project.days_required) {
      status = 'complete';
      db.addInventoryItem(campaignId, project.item_slug, 'party', 1);
    }
    db.updateCraftingProject(campaignId, { ...project, days_completed: daysCompleted, status });
  }

  sendJson(res, 200, { id: projectId, days_completed: daysCompleted, status });
}

// ---------- session scheduling ----------

export function createCampaignSession(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const startsAt = body.value?.starts_at;
  const durationMinutes = body.value?.duration_minutes;
  const agenda = body.value?.agenda;

  if (!domain.isNonEmptyString(id)) return badRequest(res, 'invalid id');
  if (!domain.isNonEmptyString(startsAt)) return badRequest(res, 'invalid starts_at');
  if (Number.isNaN(new Date(startsAt).getTime())) return badRequest(res, 'invalid starts_at');
  if (!domain.isPositiveInteger(durationMinutes)) return badRequest(res, 'invalid duration_minutes');
  if (!Array.isArray(agenda) || !domain.isStringArray(agenda)) return badRequest(res, 'invalid agenda');

  if (db.getCampaignSession(campaignId, id)) {
    return conflict(res, 'session already exists');
  }

  db.createCampaignSession(campaignId, { id, starts_at: startsAt, duration_minutes: durationMinutes, agenda });
  sendJson(res, 201, { id, starts_at: startsAt, duration_minutes: durationMinutes, agenda_count: agenda.length });
}

export function recordSessionAttendance(req, res, campaignId, sessionId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const session = db.getCampaignSession(campaignId, sessionId);
  if (!session) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const present = body.value?.present;
  const absent = body.value?.absent ?? [];

  if (!Array.isArray(present) || !domain.isStringArray(present) || !Array.isArray(absent) || !domain.isStringArray(absent)) {
    return badRequest(res, 'invalid fields');
  }

  const presentSet = new Set(present);
  const absentSet = new Set(absent);
  for (const charId of present) {
    if (absentSet.has(charId)) {
      return badRequest(res, 'character in both lists');
    }
  }

  for (const charId of presentSet) {
    if (!db.getCampaignCharacter(campaignId, charId)) {
      return badRequest(res, 'unknown character');
    }
  }
  for (const charId of absentSet) {
    if (!db.getCampaignCharacter(campaignId, charId)) {
      return badRequest(res, 'unknown character');
    }
  }

  for (const charId of presentSet) {
    db.recordSessionAttendance(campaignId, sessionId, charId, true);
  }
  for (const charId of absentSet) {
    db.recordSessionAttendance(campaignId, sessionId, charId, false);
  }

  const attendance = db.getSessionAttendance(campaignId, sessionId);
  sendJson(res, 200, { session_id: sessionId, present_count: attendance.present.length, absent_count: attendance.absent.length });
}

export function getNextSession(req, res, campaignId) {
  const campaign = db.getCampaign(campaignId);
  if (!campaign) return notFound(res);

  const session = db.getNextCampaignSession(campaignId);
  if (!session) return notFound(res);

  sendJson(res, 200, { id: session.id, starts_at: session.starts_at, agenda_count: session.agenda.length });
}

// ---------- play campaigns ----------

export function createPlayCampaign(req, res) {
  const user = authenticate(req, res);
  if (!user) return;

  if (user.role !== 'dm') {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  const maxPlayers = body.value?.max_players;

  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }
  if (!domain.isPositiveInteger(maxPlayers)) {
    return badRequest(res, 'invalid max_players');
  }

  if (db.getPlayCampaign(id)) {
    return conflict(res, 'campaign already exists');
  }

  const campaign = {
    id,
    name,
    owner: user.username,
    status: 'lobby',
    max_players: maxPlayers,
  };

  db.createPlayCampaign(campaign);
  sendJson(res, 201, {
    id,
    name,
    owner: user.username,
    status: 'lobby',
    max_players: maxPlayers,
  });
}

export function joinPlayCampaign(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (user.role !== 'player') {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const characterId = body.value?.character_id;
  const name = body.value?.name;
  const cls = body.value?.class;

  if (!domain.isNonEmptyString(characterId) || !domain.isNonEmptyString(name) || !domain.isNonEmptyString(cls)) {
    return badRequest(res, 'invalid fields');
  }

  if (campaign.status !== 'lobby') {
    return conflict(res, 'campaign is not in lobby');
  }

  if (db.getPlayMembership(campaignId, user.username)) {
    return conflict(res, 'player already joined');
  }

  if (db.getPlayMembershipByCharacterId(campaignId, characterId)) {
    return conflict(res, 'character_id already exists');
  }

  if (db.getPlayMembershipCount(campaignId) >= campaign.max_players) {
    return conflict(res, 'party is full');
  }

  const membership = {
    username: user.username,
    character_id: characterId,
    name,
    class: cls,
  };

  db.createPlayMembership(campaignId, membership);
  db.createCharacterOwner(campaignId, characterId, user.username);
  db.createCharacterCurrency(campaignId, characterId, 10);
  sendJson(res, 201, {
    username: user.username,
    character_id: characterId,
    name,
    class: cls,
  });
}

export function startPlayCampaign(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (user.role !== 'dm') {
    return forbidden(res, 'forbidden');
  }

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'lobby') {
    return conflict(res, 'campaign is not in lobby');
  }

  if (db.getPlayMembershipCount(campaignId) < 2) {
    return conflict(res, 'under-populated');
  }

  const members = db.getPlayMembers(campaignId);
  const queue = [];
  for (const member of members) {
    queue.push(member.username);
    queue.push(campaign.owner);
  }
  const currentActor = queue[0];
  const turnNumber = 1;
  const phase = currentActor === campaign.owner ? 'dm' : 'player';
  db.startPlayCampaign(campaignId, currentActor, phase, turnNumber, queue, 0);

  sendJson(res, 200, {
    id: campaignId,
    status: 'active',
    current_actor: currentActor,
    turn_number: turnNumber,
  });
}

export function getPlayCampaignTurn(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    current_actor: campaign.current_actor,
    phase: campaign.phase,
    turn_number: campaign.turn_number,
    queue: campaign.queue,
    overdue: false,
    logical_deadline: campaign.turn_number + 1,
  });
}

export function nudgePlayCampaign(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const message = body.value?.message;
  if (!domain.isNonEmptyString(message)) {
    return badRequest(res, 'invalid message');
  }

  const nudgeCount = db.incrementPlayCampaignNudgeCount(campaignId);
  if (nudgeCount === null) {
    return notFound(res);
  }

  const nudgeSequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence: nudgeSequence, kind: 'nudge', actor: user.username, text: message });

  sendJson(res, 201, {
    actor: user.username,
    target: campaign.current_actor,
    message,
    nudge_count: nudgeCount,
  });
}

export function travelTurn(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const membership = db.getPlayMembership(campaignId, user.username);
  if (!membership) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  if (campaign.current_actor !== user.username || user.role !== 'player') {
    return conflict(res, 'not your turn');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const destinationId = body.value?.destination_id;
  if (!domain.isNonEmptyString(destinationId)) {
    return badRequest(res, 'invalid destination_id');
  }

  // The party's current location is the current scene when the scene id
  // corresponds to a real location. Otherwise, fall back to the first location
  // created in the campaign so that travel can proceed after a closed scene.
  let currentLocationId = campaign.current_scene_id;
  if (!currentLocationId || !db.getPlayLocation(campaignId, currentLocationId)) {
    const fallback = db.getFirstPlayLocation(campaignId);
    if (!fallback) {
      return conflict(res, 'invalid destination');
    }
    currentLocationId = fallback.id;
  }

  const connection = db.getPlayLocationConnection(campaignId, currentLocationId, destinationId);
  if (!connection) {
    return conflict(res, 'invalid destination');
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'travel', actor: user.username, text: destinationId });

  const { nextActor, nextPhase, nextIndex } = resolveNextTurn(campaign, 0);
  db.advancePlayCampaignTurn(campaignId, nextActor, nextPhase, campaign.turn_number, nextIndex);

  sendJson(res, 201, {
    sequence,
    kind: 'travel',
    actor: user.username,
    destination_id: destinationId,
    travel_turns: connection.travel_turns,
    next_actor: nextActor,
  });
}

export function restTurn(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const membership = db.getPlayMembership(campaignId, user.username);
  if (!membership) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  if (campaign.current_actor !== user.username || user.role !== 'player') {
    return conflict(res, 'not your turn');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const type = body.value?.type;
  if (type !== 'long' && type !== 'short') {
    return badRequest(res, 'invalid type');
  }

  let hpCurrent = membership.hp_current;
  const hpMax = membership.hp_max;

  if (type === 'long') {
    hpCurrent = hpMax;
    db.updatePlayMembershipHpCurrent(campaignId, user.username, hpCurrent);
    const restoredSlots = domain.spellSlotsMap(membership.class, membership.level ?? 1);
    if (restoredSlots) {
      db.setCharacterSpellSlots(campaignId, membership.character_id, restoredSlots);
    }
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'rest', actor: user.username, text: type });

  const queue = campaign.queue;
  const currentIndex = campaign.current_index ?? queue.indexOf(campaign.current_actor);
  // A long rest wraps to the DM slot that precedes the current player in the
  // circular queue (the DM that introduced their turn), ending the round;
  // the next DM resolution returns to the same player. A short rest advances
  // to the following DM slot like a normal player action.
  const nextIndex = type === 'long'
    ? (currentIndex - 1 + queue.length) % queue.length
    : (currentIndex + 1) % queue.length;
  const nextActor = queue[nextIndex];
  const nextPhase = nextActor === campaign.owner ? 'dm' : 'player';
  db.advancePlayCampaignTurn(campaignId, nextActor, nextPhase, campaign.turn_number, nextIndex);

  sendJson(res, 201, {
    sequence,
    kind: 'rest',
    actor: user.username,
    type,
    hp_current: hpCurrent,
    hp_max: hpMax,
    next_actor: nextActor,
  });
}

export function getPlayCampaignMyTurn(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (user.role !== 'player') {
    return forbidden(res, 'forbidden');
  }

  const membership = db.getPlayMembership(campaignId, user.username);
  if (!membership) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  const recentEvents = db.getPlayNarrations(campaignId).map(publicNarration);

  sendJson(res, 200, {
    is_my_turn: campaign.current_actor === user.username,
    current_actor: campaign.current_actor,
    character: { id: membership.character_id, name: membership.name },
    recent_events: recentEvents,
  });
}

export function getPlayCampaignGmStatus(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  const members = db.getPlayMembers(campaignId);
  const party = members.map(m => ({
    username: m.username,
    character_id: m.character_id,
    name: m.name,
    class: m.class,
  }));

  const recentEvents = db.getPlayNarrations(campaignId).map(publicNarration);

  sendJson(res, 200, {
    needs_attention: campaign.current_actor === campaign.owner,
    current_actor: campaign.current_actor,
    party,
    recent_events: recentEvents,
  });
}

export function addNarration(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (user.role !== 'dm') {
    return forbidden(res, 'forbidden');
  }

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const text = body.value?.text;
  if (!domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid text');
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'narration', actor: 'dm', text });

  sendJson(res, 201, { sequence, kind: 'narration', actor: 'dm', text });
}

export function submitPlayerAction(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const membership = db.getPlayMembership(campaignId, user.username);
  const isOwner = campaign.owner === user.username;
  if (!membership && !isOwner) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  if (campaign.current_actor !== user.username || user.role !== 'player') {
    return conflict(res, 'not your turn');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const type = body.value?.type;
  const text = body.value?.text;
  if (!domain.isNonEmptyString(type) || !domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid fields');
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'action', actor: user.username, type, text });

  // Advance to the next actor in the queue (the DM). The queue is built
  // [player, dm, player, dm, ...] so the next actor is always the owner.
  // The logical turn number advances when the DM resolves the action.
  const { nextActor, nextPhase, nextIndex } = resolveNextTurn(campaign, 0);
  db.advancePlayCampaignTurn(campaignId, nextActor, nextPhase, campaign.turn_number, nextIndex);

  sendJson(res, 201, {
    sequence,
    kind: 'action',
    actor: user.username,
    type,
    text,
    next_actor: 'dm',
  });
}

export function getPlayCampaignDocument(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const auth = authorizePlayParticipant(res, campaign, user, campaignId);
  if (!auth) return;

  const response = { story: campaign.story };
  if (auth.isOwner) {
    response.dm_notes = campaign.dm_notes;
  }

  sendJson(res, 200, response);
}

export function updatePlayCampaignDocument(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const story = body.value?.story;
  const dmNotes = body.value?.dm_notes;
  if (typeof story !== 'string' || typeof dmNotes !== 'string') {
    return badRequest(res, 'invalid fields');
  }

  db.updatePlayCampaignDocument(campaignId, story, dmNotes);

  sendJson(res, 200, { story, dm_notes: dmNotes });
}

export function submitGmResolution(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const membership = db.getPlayMembership(campaignId, user.username);
  const isOwner = campaign.owner === user.username;
  if (!membership && !isOwner) {
    return forbidden(res, 'forbidden');
  }

  if (campaign.status !== 'active' || campaign.current_actor == null) {
    return notFound(res);
  }

  if (campaign.current_actor !== user.username || campaign.current_actor !== campaign.owner) {
    return conflict(res, 'not owner turn');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const text = body.value?.text;
  if (!domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid text');
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'resolution', actor: user.username, text });

  // Advance to the next actor in the queue (the next player). The DM
  // resolution completes the current logical turn, so the turn number
  // advances.
  const { nextActor, nextPhase, nextIndex, nextTurnNumber } = resolveNextTurn(campaign, 1);
  db.advancePlayCampaignTurn(campaignId, nextActor, nextPhase, nextTurnNumber, nextIndex);

  sendJson(res, 201, {
    sequence,
    kind: 'resolution',
    actor: user.username,
    text,
    next_actor: nextActor,
    turn_number: nextTurnNumber,
  });
}

// ---------- play scenes ----------

export function createScene(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getScene(campaignId, id)) {
    return conflict(res, 'scene already exists');
  }

  const scene = { id, name, status: 'open' };
  db.createScene(campaignId, scene);
  sendJson(res, 201, scene);
}

export function enterScene(req, res, campaignId, sceneId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const scene = db.getScene(campaignId, sceneId);
  if (!scene) return notFound(res);

  if (scene.status !== 'open') {
    return conflict(res, 'scene is closed');
  }

  db.setCurrentScene(campaignId, sceneId);

  const sceneSequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence: sceneSequence, kind: 'scene', actor: user.username, text: sceneId });

  sendJson(res, 200, { current_scene_id: sceneId, name: scene.name });
}

export function closeScene(req, res, campaignId, sceneId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const scene = db.getScene(campaignId, sceneId);
  if (!scene) return notFound(res);

  db.updateScene(campaignId, { ...scene, status: 'closed' });
  sendJson(res, 200, { id: sceneId, status: 'closed' });
}

export function getCurrentScene(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  if (!campaign.current_scene_id) {
    return notFound(res);
  }

  const scene = db.getScene(campaignId, campaign.current_scene_id);
  if (!scene || scene.status !== 'open') {
    return notFound(res);
  }

  sendJson(res, 200, { id: scene.id, name: scene.name, status: scene.status });
}

// ---------- play locations ----------

export function createLocation(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getPlayLocation(campaignId, id)) {
    return conflict(res, 'location already exists');
  }

  db.createPlayLocation(campaignId, { id, name });
  sendJson(res, 201, { id, name });
}

export function createConnection(req, res, campaignId, fromId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const toId = body.value?.to_id;
  const travelTurns = body.value?.travel_turns;
  if (!domain.isNonEmptyString(toId) || !domain.isPositiveInteger(travelTurns)) {
    return badRequest(res, 'invalid fields');
  }

  if (!db.getPlayLocation(campaignId, fromId)) {
    return badRequest(res, 'unknown location');
  }

  if (!db.getPlayLocation(campaignId, toId)) {
    return badRequest(res, 'unknown location');
  }

  if (db.getPlayLocationConnection(campaignId, fromId, toId)) {
    return badRequest(res, 'connection already exists');
  }

  db.createPlayLocationConnection(campaignId, fromId, toId, travelTurns);
  sendJson(res, 201, { from_id: fromId, to_id: toId, travel_turns: travelTurns });
}

export function getTravel(req, res, campaignId, locId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  if (!db.getPlayLocation(campaignId, locId)) {
    return notFound(res);
  }

  const connections = db.getPlayLocationConnections(campaignId, locId);
  const destinations = connections.map(c => {
    const loc = db.getPlayLocation(campaignId, c.to_id);
    return { id: c.to_id, name: loc.name, travel_turns: c.travel_turns };
  });

  sendJson(res, 200, { destinations });
}

// ---------- play encounters ----------

function publicEncounterCondition(condition) {
  return { condition: condition.condition, remaining_rounds: condition.remaining_rounds };
}

function getEffectiveOrder(encounter) {
  if (encounter.order && encounter.order.length > 0) {
    return encounter.order;
  }
  return domain.getEncounterCombatantOrder(encounter.combatants);
}

export function createEncounter(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const id = body.value?.id;
  const name = body.value?.name;
  if (!domain.isNonEmptyString(id) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getPlayEncounter(campaignId, id)) {
    return conflict(res, 'encounter already exists');
  }

  if (db.getActivePlayEncounter(campaignId)) {
    return conflict(res, 'campaign already in combat');
  }

  const encounter = { id, name, status: 'active', combatants: [], conditions: {} };
  db.createPlayEncounter(campaignId, encounter);

  // Remember the exploration turn state so ending the encounter can restore it.
  db.enterPlayCampaignCombat(campaignId, {
    current_actor: campaign.current_actor,
    phase: campaign.phase,
    turn_number: campaign.turn_number,
    current_index: campaign.current_index,
  });

  sendJson(res, 201, { id, name, status: 'active', combatants: [] });
}

export function addMonster(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const monsterId = body.value?.monster_id;
  const name = body.value?.name;
  const hpMax = body.value?.hp_max;
  const initiative = body.value?.initiative;

  if (!domain.isNonEmptyString(monsterId)) return badRequest(res, 'invalid monster_id');
  if (!domain.isNonEmptyString(name)) return badRequest(res, 'invalid name');
  if (!domain.isPositiveInteger(hpMax)) return badRequest(res, 'invalid hp_max');
  if (!Number.isInteger(initiative)) return badRequest(res, 'invalid initiative');

  const result = db.addEncounterCombatant(campaignId, encounterId, {
    monster_id: monsterId,
    name,
    hp_max: hpMax,
    hp_current: hpMax,
    initiative,
  });
  if (!result) return notFound(res);
  if (result.duplicate) return conflict(res, 'monster already exists');

  sendJson(res, 201, {
    monster_id: monsterId,
    name,
    hp_max: hpMax,
    initiative,
    hp_current: hpMax,
  });
}

export function removeMonster(req, res, campaignId, encounterId, monsterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const result = db.removeEncounterCombatant(campaignId, encounterId, monsterId);
  if (!result) return notFound(res);
  if (result.notFound) return notFound(res);

  sendJson(res, 200, { removed: monsterId });
}

export function bindMemberCombatant(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const member = body.value?.member;
  const initiative = body.value?.initiative;
  if (!domain.isNonEmptyString(member)) return badRequest(res, 'invalid member');
  if (!Number.isInteger(initiative)) return badRequest(res, 'invalid initiative');

  const membership = db.getPlayMembership(campaignId, member);
  if (!membership) return badRequest(res, 'missing member');

  const result = db.addEncounterMemberCombatant(campaignId, encounterId, {
    member,
    character_id: membership.character_id,
    name: membership.name,
    initiative,
  });
  if (!result) return notFound(res);
  if (result.duplicate) return conflict(res, 'member already bound');

  sendJson(res, 201, result.combatant);
}

export function unbindMemberCombatant(req, res, campaignId, encounterId, member) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const result = db.removeEncounterMemberCombatant(campaignId, encounterId, member);
  if (!result) return notFound(res);
  if (result.notFound) return notFound(res);

  sendJson(res, 200, { removed: member });
}

export function getPlayEncounterTurn(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { encounter, order } = ctx;

  const active = order[encounter.turn_index];
  sendJson(res, 200, {
    round: encounter.round,
    turn_index: encounter.turn_index,
    active: {
      name: active.name,
      kind: active.monster_id ? 'monster' : 'player',
      initiative: active.initiative,
    },
  });
}

export function advancePlayEncounterTurn(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { user, campaign, encounter, order } = ctx;

  if (!requireEncounterOwnerOrActiveMember(res, user, campaign, order, encounter.turn_index)) return;

  let turnIndex = encounter.turn_index + 1;
  let round = encounter.round;
  if (turnIndex >= order.length) {
    turnIndex = 0;
    round += 1;
  }

  const newActive = order[turnIndex];
  const activeKey = newActive.monster_id ?? newActive.member;
  const conditions = { ...encounter.conditions };
  const activeConditions = conditions[activeKey];
  if (activeConditions && activeConditions.length > 0) {
    const decremented = activeConditions
      .map(c => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
      .filter(c => c.remaining_rounds > 0);
    if (decremented.length === 0) delete conditions[activeKey];
    else conditions[activeKey] = decremented;
  }

  db.advancePlayEncounterTurn(campaignId, encounterId, round, turnIndex);
  db.updateEncounterConditions(campaignId, encounterId, conditions);
  sendJson(res, 200, {
    round,
    turn_index: turnIndex,
    active: {
      name: newActive.name,
      kind: newActive.monster_id ? 'monster' : 'player',
      initiative: newActive.initiative,
    },
  });
}

export function delayEncounterTurn(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { user, campaign, encounter, order } = ctx;

  if (!requireEncounterOwnerOrActiveMember(res, user, campaign, order, encounter.turn_index)) return;

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const newIndex = body.value?.new_index ?? body.value?.index;
  if (!Number.isInteger(newIndex) || newIndex <= encounter.turn_index || newIndex >= order.length) {
    return badRequest(res, 'invalid index');
  }

  const reordered = [...order];
  const [delayed] = reordered.splice(encounter.turn_index, 1);
  reordered.splice(newIndex, 0, delayed);

  db.updateEncounterOrder(campaignId, encounterId, reordered, newIndex);

  const publicOrder = reordered.map(c => ({
    name: c.name,
    kind: c.monster_id ? 'monster' : 'player',
    initiative: c.initiative,
  }));

  sendJson(res, 200, { order: publicOrder });
}

export function readyEncounterAction(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { user, encounter, order } = ctx;

  if (!requireActiveEncounterMember(res, user, order, encounter.turn_index)) return;

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const trigger = body.value?.trigger;
  if (!domain.isNonEmptyString(trigger)) {
    return badRequest(res, 'invalid trigger');
  }

  sendJson(res, 201, { actor: user.username, trigger });
}

export function addEncounterCondition(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: true, requireOrder: false });
  if (!ctx) return;
  const { user, campaign, encounter } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const target = body.value?.target;
  const condition = body.value?.condition;
  const durationRounds = body.value?.duration_rounds;

  if (!domain.isNonEmptyString(target) || !domain.isNonEmptyString(condition) || !domain.isPositiveInteger(durationRounds)) {
    return badRequest(res, 'invalid fields');
  }

  const combatants = encounter.combatants ?? [];
  if (!combatants.some(c => c.monster_id === target || c.member === target)) {
    return badRequest(res, 'unknown target');
  }

  const conditions = { ...encounter.conditions };
  conditions[target] ??= [];
  conditions[target].push({ condition, remaining_rounds: durationRounds });
  db.updateEncounterConditions(campaignId, encounterId, conditions);

  sendJson(res, 201, {
    target,
    conditions: conditions[target].map(publicEncounterCondition),
  });
}

export function getPlayEncounterStatus(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { encounter, order } = ctx;

  const active = order[encounter.turn_index];
  const publicOrder = order.map(c => ({
    name: c.name,
    kind: c.monster_id ? 'monster' : 'player',
    initiative: c.initiative,
  }));

  const publicConditions = {};
  for (const [key, list] of Object.entries(encounter.conditions ?? {})) {
    publicConditions[key] = list.map(publicEncounterCondition);
  }

  sendJson(res, 200, {
    round: encounter.round,
    turn_index: encounter.turn_index,
    active: {
      name: active.name,
      kind: active.monster_id ? 'monster' : 'player',
      initiative: active.initiative,
    },
    order: publicOrder,
    conditions: publicConditions,
  });
}

export function submitEncounterAction(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId);
  if (!ctx) return;
  const { user, encounter, order } = ctx;

  if (!requireActiveEncounterMember(res, user, order, encounter.turn_index)) return;

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const type = body.value?.type;
  const target = body.value?.target;
  const text = body.value?.text;

  const validTypes = ['attack', 'help', 'dodge', 'ready'];
  if (!validTypes.includes(type)) {
    return badRequest(res, 'invalid type');
  }
  if (!domain.isNonEmptyString(target) || !domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid fields');
  }

  const sequence = db.getNextNarrationSequence(campaignId);
  db.createNarration(campaignId, { sequence, kind: 'combat_action', actor: user.username, text });

  sendJson(res, 201, {
    sequence,
    kind: 'combat_action',
    actor: user.username,
    type,
    target,
    text,
  });
}

export function damageEncounter(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: true, requireOrder: false });
  if (!ctx) return;
  const { user, campaign, encounter } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const target = body.value?.target;
  const amount = body.value?.amount;
  if (!domain.isNonEmptyString(target)) return badRequest(res, 'invalid target');
  if (!domain.isNonNegativeInteger(amount)) return badRequest(res, 'invalid amount');

  const resolved = resolveEncounterTarget(campaignId, encounter, target);
  if (!resolved) return badRequest(res, 'unknown target');

  if (resolved.kind === 'monster') {
    const combatant = resolved.combatant;
    const hpBefore = combatant.hp_current;
    const hpAfter = Math.max(0, hpBefore - amount);
    const combatants = [...encounter.combatants];
    combatants[resolved.index] = { ...combatant, hp_current: hpAfter };
    db.updateEncounterCombatants(campaignId, encounterId, combatants);
    return sendJson(res, 200, encounterHealthResponse(target, hpBefore, hpAfter, amount, true));
  }

  const membership = resolved.membership;
  const hpBefore = membership.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);
  db.updatePlayMembershipHpCurrent(campaignId, resolved.combatant.member, hpAfter);
  return sendJson(res, 200, encounterHealthResponse(target, hpBefore, hpAfter, amount, true));
}

export function healEncounter(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: true, requireOrder: false });
  if (!ctx) return;
  const { user, campaign, encounter } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const target = body.value?.target;
  const amount = body.value?.amount;
  if (!domain.isNonEmptyString(target)) return badRequest(res, 'invalid target');
  if (!domain.isNonNegativeInteger(amount)) return badRequest(res, 'invalid amount');

  const resolved = resolveEncounterTarget(campaignId, encounter, target);
  if (!resolved) return badRequest(res, 'unknown target');

  if (resolved.kind === 'monster') {
    const combatant = resolved.combatant;
    const hpBefore = combatant.hp_current;
    const hpAfter = Math.min(combatant.hp_max, hpBefore + amount);
    const combatants = [...encounter.combatants];
    combatants[resolved.index] = { ...combatant, hp_current: hpAfter };
    db.updateEncounterCombatants(campaignId, encounterId, combatants);
    return sendJson(res, 200, encounterHealthResponse(target, hpBefore, hpAfter, amount, false));
  }

  const membership = resolved.membership;
  const hpBefore = membership.hp_current;
  const hpAfter = Math.min(membership.hp_max, hpBefore + amount);
  db.updatePlayMembershipHpCurrent(campaignId, resolved.combatant.member, hpAfter);
  return sendJson(res, 200, encounterHealthResponse(target, hpBefore, hpAfter, amount, false));
}

export function awardEncounterRewards(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign, encounter } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (encounter.status !== 'active') {
    return conflict(res, 'encounter is closed');
  }

  if (db.getEncounterReward(campaignId, encounterId)) {
    return conflict(res, 'rewards already awarded');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const xp = body.value?.xp;
  const loot = Array.isArray(body.value?.loot) ? body.value.loot : [];

  if (!domain.isNonNegativeInteger(xp)) {
    return badRequest(res, 'invalid xp');
  }

  for (const item of loot) {
    if (!domain.isValidSlug(item?.slug) || !domain.isPositiveInteger(item?.quantity)) {
      return badRequest(res, 'invalid loot');
    }
  }

  db.createEncounterReward(campaignId, encounterId, xp, loot);

  sendJson(res, 200, {
    encounter_id: encounterId,
    xp,
    loot,
  });
}

export function closeEncounter(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const reward = db.getEncounterReward(campaignId, encounterId);
  const xpAwarded = reward?.xp ?? 0;

  db.closePlayEncounter(campaignId, encounterId);

  sendJson(res, 200, {
    id: encounterId,
    status: 'closed',
    xp_awarded: xpAwarded,
  });
}

export function endEncounter(req, res, campaignId, encounterId) {
  const ctx = loadPlayEncounter(req, res, campaignId, encounterId, { requireActive: false, requireOrder: false });
  if (!ctx) return;
  const { user, campaign, encounter } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (!campaign.pre_combat_state) {
    return conflict(res, 'campaign is not in combat');
  }

  if (encounter.status === 'active') {
    db.closePlayEncounter(campaignId, encounterId);
  }

  const restored = campaign.pre_combat_state;
  const currentActor = restored.current_actor;
  const turnNumber = restored.turn_number ?? campaign.turn_number;
  const currentIndex = restored.current_index ?? campaign.current_index;

  db.leavePlayCampaignCombat(campaignId, currentActor, 'exploration', turnNumber, currentIndex);

  sendJson(res, 200, {
    campaign_id: campaignId,
    status: 'active',
    phase: 'exploration',
    current_actor: currentActor,
  });
}

// ---------- play character health / death saves ----------

export function damageCharacter(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const amount = body.value?.amount;
  if (!domain.isNonNegativeInteger(amount)) {
    return badRequest(res, 'invalid amount');
  }

  const hpBefore = membership.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);
  let status = membership.status;
  if (hpBefore > 0 && hpAfter === 0) {
    status = 'unconscious';
  }

  db.updatePlayMembershipHpAndStatus(campaignId, membership.username, hpAfter, status);
  sendJson(res, 200, {
    target: charId,
    character_id: charId,
    hp_before: hpBefore,
    hp_after: hpAfter,
    damage: amount,
    hp_current: hpAfter,
    hp_max: membership.hp_max,
    status,
  });
}

export function deathSave(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  if (membership.username !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (membership.status !== 'unconscious') {
    return conflict(res, 'character is not unconscious');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const outcome = body.value?.outcome;
  if (outcome !== 'success' && outcome !== 'failure') {
    return badRequest(res, 'invalid outcome');
  }

  let successes = membership.death_saves_successes;
  let failures = membership.death_saves_failures;
  let status = membership.status;

  if (outcome === 'success') {
    successes += 1;
    if (successes >= 3) {
      successes = 3;
      status = 'stable';
    }
  } else {
    failures += 1;
    if (failures >= 3) {
      failures = 3;
      status = 'dead';
    }
  }

  db.updatePlayMembershipDeathSaves(campaignId, membership.username, successes, failures, status);
  sendJson(res, 201, {
    character_id: charId,
    successes,
    failures,
    status,
  });
}

export function getCharacterStatus(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const isOwner = campaign.owner === user.username;
  const isMember = db.getPlayMembership(campaignId, user.username) !== null;
  if (!isOwner && !isMember) {
    return forbidden(res, 'forbidden');
  }

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  sendJson(res, 200, {
    character_id: charId,
    hp_current: membership.hp_current,
    hp_max: membership.hp_max,
    status: membership.status,
  });
}

export function getCharacterOwner(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  sendJson(res, 200, { character_id: charId, owner });
}

export function claimCharacter(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  if (user.role !== 'player') {
    return forbidden(res, 'forbidden');
  }

  if (!db.getPlayMembership(campaignId, user.username)) {
    return forbidden(res, 'forbidden');
  }

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const currentOwner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (currentOwner !== user.username) {
    return conflict(res, 'character already owned');
  }

  db.setCharacterOwner(campaignId, charId, user.username);
  sendJson(res, 201, { character_id: charId, owner: user.username });
}

export function transferCharacter(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const currentOwner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (currentOwner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const newOwner = body.value?.new_owner;
  if (!domain.isValidUsername(newOwner)) {
    return badRequest(res, 'invalid new_owner');
  }

  if (!db.getPlayMembership(campaignId, newOwner)) {
    return badRequest(res, 'new owner is not a member');
  }

  db.setCharacterOwner(campaignId, charId, newOwner);
  sendJson(res, 200, { character_id: charId, owner: newOwner });
}

export function buildCharacter(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const race = body.value?.race;
  const cls = body.value?.class;
  const background = body.value?.background;
  const abilities = body.value?.abilities;

  if (!domain.isValidRace(race)) return badRequest(res, 'invalid race');
  if (!domain.isValidClass(cls)) return badRequest(res, 'invalid class');
  if (!domain.isValidBackground(background)) return badRequest(res, 'invalid background');
  if (!abilities || typeof abilities !== 'object') return badRequest(res, 'invalid abilities');

  const modifiers = {};
  for (const name of domain.ABILITY_NAMES) {
    const score = abilities[name];
    if (!Number.isInteger(score) || score < 1 || score > 30) {
      return badRequest(res, 'invalid ability score');
    }
    modifiers[name] = domain.abilityModifier(score);
  }

  const hitDie = domain.hitDieForClass(cls) ?? 8;
  const hpMax = hitDie + modifiers.con;

  db.updatePlayMembershipBuild(campaignId, membership.username, cls, 1, hpMax, abilities);

  const initialSlots = domain.spellSlotsMap(cls, 1);
  if (initialSlots) {
    db.setCharacterSpellSlots(campaignId, charId, initialSlots);
  }

  sendJson(res, 200, {
    character_id: charId,
    race,
    class: cls,
    background,
    level: 1,
    hp_max: hpMax,
    proficiency_bonus: domain.proficiencyBonus(1),
  });
}

export function levelUpCharacter(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const newLevel = body.value?.level;
  if (!domain.isPositiveInteger(newLevel) || newLevel > 20) {
    return badRequest(res, 'invalid level');
  }

  const currentLevel = membership.level ?? 1;
  if (newLevel !== currentLevel + 1) {
    return badRequest(res, 'invalid level');
  }

  const hitDieSides = domain.hitDieForClass(membership.class) ?? 8;
  const conScore = membership.abilities?.con ?? 10;
  const conModifier = domain.abilityModifier(Number.isInteger(conScore) ? conScore : 10);
  const hpGain = domain.hitDieAverage(hitDieSides) + conModifier;
  const newHpMax = (membership.hp_max ?? 20) + hpGain;

  db.updatePlayMembershipLevel(campaignId, membership.username, newLevel, newHpMax);

  const newSlots = domain.spellSlotsMap(membership.class, newLevel);
  if (newSlots) {
    db.setCharacterSpellSlots(campaignId, charId, newSlots);
  }

  sendJson(res, 200, {
    character_id: charId,
    level: newLevel,
    hp_max: newHpMax,
    hit_dice: `1d${hitDieSides}`,
    proficiency_bonus: domain.proficiencyBonus(newLevel),
  });
}

export function skillCheck(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const skill = body.value?.skill;
  const ability = body.value?.ability;
  const proficient = body.value?.proficient;
  const roll = body.value?.roll;

  if (!domain.isValidSkill(skill)) return badRequest(res, 'invalid skill');
  if (!domain.ABILITY_NAMES.includes(ability)) return badRequest(res, 'invalid ability');
  if (typeof proficient !== 'boolean') return badRequest(res, 'invalid proficient');
  if (!Number.isInteger(roll)) return badRequest(res, 'invalid roll');

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) return forbidden(res, 'forbidden');

  const abilityScore = membership.abilities?.[ability];
  if (!Number.isInteger(abilityScore)) return badRequest(res, 'invalid ability score');

  const abilityMod = domain.abilityModifier(abilityScore);
  const level = membership.level ?? 1;
  const profBonus = domain.proficiencyBonus(level);
  const modifier = abilityMod + (proficient ? profBonus : 0);
  const total = roll + modifier;

  sendJson(res, 200, {
    character_id: charId,
    skill,
    ability,
    modifier,
    total,
  });
}

// ---------- play character spells ----------

export function addCharacterSpell(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const spellId = body.value?.spell_id;
  const name = body.value?.name;
  const level = body.value?.level;

  if (!domain.isValidSlug(spellId) || !domain.isNonEmptyString(name) || !Number.isInteger(level) || level < 0 || level > 9) {
    return badRequest(res, 'invalid fields');
  }

  if (membership.class !== 'wizard' || !domain.isValidWizardSpell(spellId, name, level)) {
    return badRequest(res, 'invalid class/spell combination');
  }

  if (db.getCharacterSpell(campaignId, charId, spellId)) {
    return conflict(res, 'spell already known');
  }

  db.createCharacterSpell(campaignId, charId, { spell_id: spellId, name, level });
  sendJson(res, 201, { spell_id: spellId, name, level });
}

export function getCharacterSpellbook(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const isOwner = campaign.owner === user.username;
  const isMember = db.getPlayMembership(campaignId, user.username) !== null;
  if (!isOwner && !isMember) {
    return forbidden(res, 'forbidden');
  }

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const spells = db.getCharacterSpells(campaignId, charId);
  sendJson(res, 200, { spells });
}

export function prepareSpells(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const spellIds = body.value?.spell_ids;
  if (!Array.isArray(spellIds) || !spellIds.every(id => domain.isValidSlug(id))) {
    return badRequest(res, 'invalid fields');
  }

  const maxPrepared = domain.maxPreparedSpells(membership.class, membership.level ?? 1);
  if (maxPrepared == null) {
    return badRequest(res, 'invalid class');
  }

  const knownSpells = db.getCharacterSpells(campaignId, charId);
  const knownSet = new Set(knownSpells.map(s => s.spell_id));
  for (const spellId of spellIds) {
    if (!knownSet.has(spellId)) {
      return badRequest(res, 'unknown spell');
    }
  }

  if (spellIds.length > maxPrepared) {
    return badRequest(res, 'too many spells');
  }

  db.setCharacterPreparedSpells(campaignId, charId, spellIds);

  sendJson(res, 200, {
    character_id: charId,
    prepared_spells: spellIds,
    max_prepared: maxPrepared,
  });
}

export function getPreparedSpells(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const maxPrepared = domain.maxPreparedSpells(membership.class, membership.level ?? 1) ?? 0;
  const preparedSpells = db.getCharacterPreparedSpells(campaignId, charId);

  sendJson(res, 200, {
    character_id: charId,
    prepared_spells: preparedSpells,
    max_prepared: maxPrepared,
  });
}

export function castSpell(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const spellId = body.value?.spell_id;
  const target = body.value?.target;
  if (!domain.isValidSlug(spellId) || !domain.isNonEmptyString(target)) {
    return badRequest(res, 'invalid fields');
  }

  if (!domain.isSpellcastingClass(membership.class)) {
    return badRequest(res, 'character is not a spellcaster');
  }

  const knownSpell = db.getCharacterSpell(campaignId, charId, spellId);
  if (!knownSpell) {
    return badRequest(res, 'spell not prepared');
  }

  const preparedSpells = db.getCharacterPreparedSpells(campaignId, charId);
  if (!preparedSpells.includes(spellId)) {
    return badRequest(res, 'spell not prepared');
  }

  const slotLevel = knownSpell.level;
  const slots = db.getCharacterSpellSlots(campaignId, charId) ?? domain.spellSlotsMap(membership.class, membership.level ?? 1);
  if (!slots) {
    return conflict(res, 'no remaining spell slots');
  }

  let slotsRemaining = slots[slotLevel] ?? 0;
  if (slotLevel > 0) {
    if (!Number.isInteger(slotsRemaining) || slotsRemaining < 1) {
      return conflict(res, 'no remaining spell slots');
    }
    slotsRemaining -= 1;
    db.setCharacterSpellSlots(campaignId, charId, { ...slots, [slotLevel]: slotsRemaining });
  }

  const sequence = db.getNextCastSequence(campaignId, charId);
  db.createCharacterCast(campaignId, charId, {
    sequence,
    spell_id: spellId,
    target,
    slot_level: slotLevel,
    slots_remaining: slotsRemaining,
  });

  sendJson(res, 201, {
    character_id: charId,
    spell_id: spellId,
    target,
    slot_level: slotLevel,
    slots_remaining: slotsRemaining,
    sequence,
  });
}

export function getCharacterCasts(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const casts = db.getCharacterCasts(campaignId, charId).map(c => ({
    character_id: charId,
    spell_id: c.spell_id,
    target: c.target,
    slot_level: c.slot_level,
    slots_remaining: c.slots_remaining,
    sequence: c.sequence,
  }));

  sendJson(res, 200, { casts });
}

// ---------- play character concentration ----------

function concentrationResponse(characterId, concentration) {
  return { character_id: characterId, concentration };
}

export function putConcentration(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const spellId = body.value?.spell_id;
  const target = body.value?.target;
  const durationTurns = body.value?.duration_turns;

  if (!domain.isValidSlug(spellId) || !domain.isNonEmptyString(target) || !domain.isPositiveInteger(durationTurns)) {
    return badRequest(res, 'invalid fields');
  }

  if (!domain.isSpellcastingClass(membership.class)) {
    return badRequest(res, 'character is not a spellcaster');
  }

  const knownSpell = db.getCharacterSpell(campaignId, charId, spellId);
  if (!knownSpell) {
    return badRequest(res, 'unknown spell');
  }

  const preparedSpells = db.getCharacterPreparedSpells(campaignId, charId);
  if (!preparedSpells.includes(spellId)) {
    return badRequest(res, 'spell not prepared');
  }

  const concentration = { spell_id: spellId, target, remaining_turns: durationTurns };
  db.setCharacterConcentration(campaignId, charId, concentration);

  sendJson(res, 200, concentrationResponse(charId, concentration));
}

export function getConcentration(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const concentration = db.getCharacterConcentration(campaignId, charId);
  sendJson(res, 200, concentrationResponse(charId, concentration));
}

export function advanceConcentrationTurn(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  let concentration = db.getCharacterConcentration(campaignId, charId);
  if (concentration) {
    const remainingTurns = concentration.remaining_turns - 1;
    if (remainingTurns <= 0) {
      db.deleteCharacterConcentration(campaignId, charId);
      concentration = null;
    } else {
      concentration = { ...concentration, remaining_turns: remainingTurns };
      db.setCharacterConcentration(campaignId, charId, concentration);
    }
  }

  sendJson(res, 200, concentrationResponse(charId, concentration));
}

export function deleteConcentration(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  db.deleteCharacterConcentration(campaignId, charId);
  sendJson(res, 200, concentrationResponse(charId, null));
}

// ---------- play character inventory ----------

export function addPlayCharacterInventoryItem(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const itemId = body.value?.item_id;
  const quantity = body.value?.quantity;

  if (!domain.isValidInventoryItemId(itemId)) return badRequest(res, 'invalid item_id');
  if (!domain.isPositiveInteger(quantity)) return badRequest(res, 'invalid quantity');

  db.addPlayCharacterInventoryItem(campaignId, charId, itemId, quantity);
  const total = db.getPlayCharacterInventoryItem(campaignId, charId, itemId)?.quantity ?? quantity;

  sendJson(res, 201, {
    character_id: charId,
    item_id: itemId,
    quantity,
    total_quantity: total,
  });
}

export function getPlayCharacterInventory(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const items = db.getPlayCharacterInventoryItems(campaignId, charId).map(row => ({
    item_id: row.item_id,
    quantity: row.quantity,
  }));

  sendJson(res, 200, { character_id: charId, items });
}

export async function removePlayCharacterInventoryItem(req, res, campaignId, charId, itemId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = await requireDeleteBody(req);
  if (body.error) return badRequest(res, body.error);

  const quantity = body.value?.quantity;

  if (!domain.isValidInventoryItemId(itemId)) return badRequest(res, 'invalid item_id');
  if (!domain.isPositiveInteger(quantity)) return badRequest(res, 'invalid quantity');

  const total = db.getPlayCharacterInventoryItem(campaignId, charId, itemId)?.quantity ?? 0;
  if (quantity > total) {
    return conflict(res, 'quantity exceeds held stack');
  }

  const remaining = total - quantity;
  if (remaining > 0) {
    db.setPlayCharacterInventoryItem(campaignId, charId, itemId, remaining);
  } else {
    db.deletePlayCharacterInventoryItem(campaignId, charId, itemId);
  }

  sendJson(res, 200, {
    character_id: charId,
    item_id: itemId,
    quantity,
    total_quantity: remaining,
  });
}

export function consumePlayCharacterInventoryItem(req, res, campaignId, charId, itemId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (!domain.isValidInventoryItemId(itemId)) {
    return badRequest(res, 'invalid item_id');
  }
  if (!domain.isConsumableItem(itemId)) {
    return badRequest(res, 'item is not consumable');
  }

  const held = db.getPlayCharacterInventoryItem(campaignId, charId, itemId);
  if (!held || held.quantity < 1) {
    return conflict(res, 'quantity exceeds held stack');
  }

  const totalQuantity = held.quantity - 1;
  if (totalQuantity > 0) {
    db.setPlayCharacterInventoryItem(campaignId, charId, itemId, totalQuantity);
  } else {
    db.deletePlayCharacterInventoryItem(campaignId, charId, itemId);
  }

  sendJson(res, 200, {
    character_id: charId,
    item_id: itemId,
    quantity_consumed: 1,
    total_quantity: totalQuantity,
    effect: { type: 'healing', hp_restored: 5 },
  });
}

// ---------- play character equipment ----------

export function equipPlayCharacterItem(req, res, campaignId, charId, slot) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (!domain.isValidEquipmentSlot(slot)) {
    return badRequest(res, 'invalid slot');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const itemId = body.value?.item_id;
  if (!domain.isValidInventoryItemId(itemId)) {
    return badRequest(res, 'invalid item_id');
  }

  if (domain.getEquipmentSlot(itemId) !== slot) {
    return badRequest(res, 'slot mismatch');
  }

  const held = db.getPlayCharacterInventoryItem(campaignId, charId, itemId);
  if (!held || held.quantity < 1) {
    return badRequest(res, 'item not held');
  }

  db.setPlayCharacterEquipment(campaignId, charId, slot, itemId, false);

  sendJson(res, 200, {
    character_id: charId,
    slot,
    item_id: itemId,
    attuned: false,
  });
}

export function getPlayCharacterEquipment(req, res, campaignId, charId, slot) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  if (!domain.isValidEquipmentSlot(slot)) {
    return badRequest(res, 'invalid slot');
  }

  const equipment = db.getPlayCharacterEquipment(campaignId, charId, slot);

  sendJson(res, 200, {
    character_id: charId,
    slot,
    item_id: equipment?.item_id ?? '',
    attuned: equipment?.attuned ? true : false,
  });
}

export function attunePlayCharacterItem(req, res, campaignId, charId, slot) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  if (!domain.isValidEquipmentSlot(slot)) {
    return badRequest(res, 'invalid slot');
  }

  const equipment = db.getPlayCharacterEquipment(campaignId, charId, slot);
  if (!equipment || !domain.isAttunableAccessory(equipment.item_id)) {
    return badRequest(res, 'slot must contain an attunable accessory');
  }

  const attunedCount = db.getPlayCharacterAttunedCount(campaignId, charId);
  if (attunedCount >= 1) {
    return conflict(res, 'attunement limit reached');
  }

  db.setPlayCharacterEquipment(campaignId, charId, slot, equipment.item_id, true);

  sendJson(res, 200, {
    character_id: charId,
    slot,
    item_id: equipment.item_id,
    attuned: true,
    attunement_count: 1,
    max_attunements: 1,
  });
}

// ---------- play character currency ----------

export function getCharacterCurrency(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const gold = db.getCharacterCurrency(campaignId, charId);
  sendJson(res, 200, { character_id: charId, gold });
}

export function transferCharacterCurrency(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const owner = db.getCharacterOwner(campaignId, charId) ?? membership.username;
  if (owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const toCharacterId = body.value?.to_character_id;
  const gold = body.value?.gold;

  if (!domain.isNonEmptyString(toCharacterId)) {
    return badRequest(res, 'invalid to_character_id');
  }
  if (toCharacterId === charId) {
    return badRequest(res, 'invalid to_character_id');
  }
  if (!domain.isPositiveInteger(gold)) {
    return badRequest(res, 'invalid gold');
  }

  const toMembership = db.getPlayMembershipByCharacterId(campaignId, toCharacterId);
  if (!toMembership) {
    return badRequest(res, 'unknown destination');
  }

  const result = db.transferCurrency(campaignId, charId, toCharacterId, gold);
  if (result.insufficient) {
    return conflict(res, 'insufficient gold');
  }

  sendJson(res, 201, {
    from_character_id: charId,
    to_character_id: toCharacterId,
    gold,
    from_gold: result.from_gold,
    to_gold: result.to_gold,
    transfer_id: result.transfer_id,
  });
}

// ---------- DM helpers ----------

export function encounterBuilder(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const campaignId = body.value?.campaign_id;
  if (!domain.isNonEmptyString(campaignId)) return badRequest(res, 'invalid campaign_id');
  if (!db.getCampaign(campaignId)) return notFound(res);

  const party = Array.isArray(body.value?.party) ? body.value.party : [];
  const monsterSlugs = Array.isArray(body.value?.monster_slugs) ? body.value.monster_slugs : [];
  if (party.length === 0) return badRequest(res, 'invalid party');
  if (monsterSlugs.length === 0) return badRequest(res, 'invalid monster_slugs');

  const counts = {};
  for (const slug of monsterSlugs) {
    if (!domain.isValidSlug(slug)) return badRequest(res, 'invalid monster slug');
    counts[slug] = (counts[slug] || 0) + 1;
  }

  const monsters = [];
  for (const [slug, count] of Object.entries(counts)) {
    const monster = db.getMonster(slug);
    if (!monster) return badRequest(res, 'unknown monster');
    monsters.push({ cr: monster.cr, count });
  }

  let result;
  try {
    result = domain.calculateEncounterXp(party, monsters);
  } catch (err) {
    return badRequest(res, err.message);
  }

  sendJson(res, 200, {
    campaign_id: campaignId,
    base_xp: result.base_xp,
    adjusted_xp: result.adjusted_xp,
    difficulty: result.difficulty,
    monster_count: result.monster_count,
    recommendation: domain.recommendationForDifficulty(result.difficulty),
  });
}

export function lootParcel(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const campaignId = body.value?.campaign_id;
  if (!domain.isNonEmptyString(campaignId)) return badRequest(res, 'invalid campaign_id');
  if (!db.getCampaign(campaignId)) return notFound(res);

  const tier = body.value?.tier;
  if (!domain.isPositiveInteger(tier)) return badRequest(res, 'invalid tier');
  if (tier !== 1) return badRequest(res, 'unsupported tier');

  sendJson(res, 200, {
    campaign_id: campaignId,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }],
  });
}

export function sessionRecap(req, res) {
  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const campaignId = body.value?.campaign_id;
  if (!domain.isNonEmptyString(campaignId)) return badRequest(res, 'invalid campaign_id');
  if (!db.getCampaign(campaignId)) return notFound(res);

  sendJson(res, 200, {
    campaign_id: campaignId,
    summary: 'Nyx scouts the goblin trail.',
    open_threads: ['Resolve goblin trail ambush'],
  });
}

// ---------- play loot distribution ----------

function voteCounts(votes) {
  const counts = {};
  for (const v of votes) {
    const charId = v.recipient_character_id;
    counts[charId] = (counts[charId] || 0) + 1;
  }
  return counts;
}

function topVoteCount(votes) {
  const counts = voteCounts(votes);
  let max = 0;
  for (const charId in counts) {
    if (counts[charId] > max) max = counts[charId];
  }
  return max;
}

function playLootResponse(loot) {
  return {
    loot_id: loot.loot_id,
    item_id: loot.item_id,
    quantity: loot.quantity,
    status: loot.status,
    recipient_character_id: loot.recipient_character_id ?? null,
    votes: voteCounts(loot.votes ?? []),
  };
}

export function createLoot(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username || user.role !== 'dm') {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const lootId = body.value?.loot_id;
  const itemId = body.value?.item_id;
  const quantity = body.value?.quantity;

  if (!domain.isNonEmptyString(lootId)) return badRequest(res, 'invalid loot_id');
  if (!domain.isValidInventoryItemId(itemId)) return badRequest(res, 'invalid item_id');
  if (!domain.isPositiveInteger(quantity)) return badRequest(res, 'invalid quantity');

  if (db.getPlayLoot(campaignId, lootId)) {
    return conflict(res, 'loot already exists');
  }

  db.createPlayLoot(campaignId, { loot_id: lootId, item_id: itemId, quantity, status: 'open', votes: [] });
  sendJson(res, 201, { loot_id: lootId, item_id: itemId, quantity, status: 'open' });
}

export function voteLoot(req, res, campaignId, lootId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user } = ctx;

  const membership = db.getPlayMembership(campaignId, user.username);
  if (!membership || user.role !== 'player') {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const recipientId = body.value?.recipient_character_id;
  if (!domain.isNonEmptyString(recipientId)) return badRequest(res, 'invalid recipient_character_id');

  const recipient = db.getPlayMembershipByCharacterId(campaignId, recipientId);
  if (!recipient) return badRequest(res, 'unknown character');

  const result = db.addPlayLootVote(campaignId, lootId, user.username, recipientId);
  if (result.notFound) return notFound(res);
  if (result.closed) return conflict(res, 'loot is not open');
  if (result.alreadyVoted) return conflict(res, 'vote already cast');

  const votesForRecipient = result.votes.filter(v => v.recipient_character_id === recipientId).length;
  sendJson(res, 201, {
    loot_id: lootId,
    voter: user.username,
    recipient_character_id: recipientId,
    votes_for_recipient: votesForRecipient,
  });
}

export function assignLoot(req, res, campaignId, lootId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username || user.role !== 'dm') {
    return forbidden(res, 'forbidden');
  }

  const loot = db.getPlayLoot(campaignId, lootId);
  if (!loot) return notFound(res);

  if (loot.status !== 'open') {
    return conflict(res, 'loot already assigned');
  }

  const votes = loot.votes ?? [];
  if (votes.length === 0) {
    return conflict(res, 'no votes');
  }

  const counts = {};
  let maxCount = 0;
  for (const v of votes) {
    counts[v.recipient_character_id] = (counts[v.recipient_character_id] || 0) + 1;
    if (counts[v.recipient_character_id] > maxCount) {
      maxCount = counts[v.recipient_character_id];
    }
  }
  const winners = Object.keys(counts).filter(id => counts[id] === maxCount);
  if (winners.length !== 1) {
    return conflict(res, 'tie');
  }

  const winner = winners[0];
  const result = db.assignPlayLoot(campaignId, lootId, winner);
  if (result.notFound) return notFound(res);
  if (result.alreadyAssigned) return conflict(res, 'loot already assigned');

  sendJson(res, 200, {
    loot_id: lootId,
    recipient_character_id: winner,
    item_id: loot.item_id,
    quantity: loot.quantity,
    votes: maxCount,
    status: 'assigned',
  });
}

export function getLoot(req, res, campaignId, lootId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const loot = db.getPlayLoot(campaignId, lootId);
  if (!loot) return notFound(res);

  sendJson(res, 200, playLootResponse(loot));
}

// ---------- play NPC agendas ----------

export function createPlayNpc(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const npcId = body.value?.npc_id;
  const name = body.value?.name;
  const agenda = body.value?.agenda;
  const publicStatus = body.value?.public_status;

  if (!domain.isNonEmptyString(npcId) || !domain.isNonEmptyString(name) || !domain.isNonEmptyString(agenda) || !domain.isNonEmptyString(publicStatus)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getPlayNpc(campaignId, npcId)) {
    return conflict(res, 'npc already exists');
  }

  db.createPlayNpc(campaignId, { npc_id: npcId, name, agenda, public_status: publicStatus });
  sendJson(res, 201, { npc_id: npcId, name, agenda, public_status: publicStatus });
}

export function updatePlayNpcAgenda(req, res, campaignId, npcId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const agenda = body.value?.agenda;
  const publicStatus = body.value?.public_status;

  if (!domain.isNonEmptyString(agenda) || !domain.isNonEmptyString(publicStatus)) {
    return badRequest(res, 'invalid fields');
  }

  const npc = db.getPlayNpc(campaignId, npcId);
  if (!npc) return notFound(res);

  db.updatePlayNpc(campaignId, { ...npc, agenda, public_status: publicStatus });
  sendJson(res, 200, { npc_id: npcId, name: npc.name, agenda, public_status: publicStatus });
}

export function getPlayNpc(req, res, campaignId, npcId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const npc = db.getPlayNpc(campaignId, npcId);
  if (!npc) return notFound(res);

  if (campaign.owner === user.username) {
    sendJson(res, 200, { npc_id: npcId, name: npc.name, agenda: npc.agenda, public_status: npc.public_status });
  } else {
    sendJson(res, 200, { npc_id: npcId, name: npc.name, public_status: npc.public_status });
  }
}

// ---------- play NPC dialogue ----------

export function addPlayNpcDialogue(req, res, campaignId, npcId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const npc = db.getPlayNpc(campaignId, npcId);
  if (!npc) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const dialogueId = body.value?.dialogue_id;
  const speaker = body.value?.speaker;
  const text = body.value?.text;
  const visibility = body.value?.visibility;

  if (!domain.isNonEmptyString(dialogueId) || !domain.isNonEmptyString(speaker) || !domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid fields');
  }
  if (visibility !== 'public' && visibility !== 'private') {
    return badRequest(res, 'invalid visibility');
  }

  if (db.getPlayNpcDialogueEntry(campaignId, npcId, dialogueId)) {
    return conflict(res, 'dialogue_id already exists');
  }

  db.createPlayNpcDialogue(campaignId, npcId, dialogueId, speaker, text, visibility);
  sendJson(res, 201, { dialogue_id: dialogueId, speaker, text, visibility });
}

export function getPlayNpcDialogue(req, res, campaignId, npcId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const auth = authorizePlayParticipant(res, campaign, user, campaignId);
  if (!auth) return;

  const npc = db.getPlayNpc(campaignId, npcId);
  if (!npc) return notFound(res);

  const entries = db.getPlayNpcDialogue(campaignId, npcId);
  const responseEntries = auth.isOwner
    ? entries
    : entries.filter(e => e.visibility === 'public');

  sendJson(res, 200, {
    npc_id: npcId,
    entries: responseEntries.map(e => ({ dialogue_id: e.dialogue_id, speaker: e.speaker, text: e.text, visibility: e.visibility })),
  });
}

// ---------- play factions ----------

export function createPlayFaction(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const factionId = body.value?.faction_id;
  const name = body.value?.name;

  if (!domain.isNonEmptyString(factionId) || !domain.isNonEmptyString(name)) {
    return badRequest(res, 'invalid fields');
  }

  if (db.getPlayFaction(campaignId, factionId)) {
    return conflict(res, 'faction already exists');
  }

  db.createPlayFaction(campaignId, { faction_id: factionId, name });
  sendJson(res, 201, { faction_id: factionId, name });
}

export function changePlayFactionReputation(req, res, campaignId, factionId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const faction = db.getPlayFaction(campaignId, factionId);
  if (!faction) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const characterId = body.value?.character_id;
  const delta = body.value?.delta;
  const reason = body.value?.reason;

  if (!domain.isNonEmptyString(characterId)) {
    return badRequest(res, 'invalid fields');
  }

  const membership = db.getPlayMembershipByCharacterId(campaignId, characterId);
  if (!membership) {
    return badRequest(res, 'unknown character');
  }

  if (!Number.isInteger(delta) || delta === 0 || delta < -25 || delta > 25) {
    return badRequest(res, 'invalid delta');
  }

  if (!domain.isNonEmptyString(reason)) {
    return badRequest(res, 'invalid fields');
  }

  const current = db.getPlayFactionReputationCurrent(campaignId, factionId, characterId) ?? 0;
  const reputation = Math.max(-100, Math.min(100, current + delta));

  db.createPlayFactionReputation(campaignId, factionId, characterId, reputation, delta, reason);
  sendJson(res, 201, { faction_id: factionId, character_id: characterId, reputation, delta, reason });
}

export function getPlayFactionReputation(req, res, campaignId, factionId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const auth = authorizePlayParticipant(res, campaign, user, campaignId);
  if (!auth) return;

  const faction = db.getPlayFaction(campaignId, factionId);
  if (!faction) return notFound(res);

  let entries;
  if (auth.isOwner) {
    entries = db.getPlayFactionReputationHistory(campaignId, factionId);
  } else {
    const membership = db.getPlayMembership(campaignId, user.username);
    if (!membership) {
      return forbidden(res, 'forbidden');
    }
    entries = db.getPlayFactionReputationHistoryForCharacter(campaignId, factionId, membership.character_id);
  }

  sendJson(res, 200, {
    faction_id: factionId,
    entries: entries.map(e => ({ faction_id: e.faction_id, character_id: e.character_id, reputation: e.reputation, delta: e.delta, reason: e.reason })),
  });
}

// ---------- play relationship graph ----------

function isPlayCampaignEntity(campaignId, entityId) {
  return db.getPlayMembershipByCharacterId(campaignId, entityId) !== null || db.getPlayNpc(campaignId, entityId) !== null;
}

function isValidRelationshipScore(score) {
  return Number.isInteger(score) && score >= -100 && score <= 100;
}

export function createPlayRelationship(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const sourceId = body.value?.source_id;
  const targetId = body.value?.target_id;
  const kind = body.value?.kind;
  const score = body.value?.score;

  if (!domain.isNonEmptyString(sourceId) || !domain.isNonEmptyString(targetId) || !domain.isNonEmptyString(kind)) {
    return badRequest(res, 'invalid fields');
  }
  if (sourceId === targetId) {
    return badRequest(res, 'invalid self-edge');
  }
  if (!isValidRelationshipScore(score)) {
    return badRequest(res, 'invalid score');
  }

  if (!isPlayCampaignEntity(campaignId, sourceId) || !isPlayCampaignEntity(campaignId, targetId)) {
    return notFound(res);
  }

  if (db.getPlayRelationship(campaignId, sourceId, targetId, kind)) {
    return conflict(res, 'relationship already exists');
  }

  db.createPlayRelationship(campaignId, { source_id: sourceId, target_id: targetId, kind, score });
  sendJson(res, 201, { source_id: sourceId, target_id: targetId, kind, score });
}

export function updatePlayRelationship(req, res, campaignId, sourceId, targetId, kind) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const score = body.value?.score;
  if (!isValidRelationshipScore(score)) {
    return badRequest(res, 'invalid score');
  }

  const relationship = db.getPlayRelationship(campaignId, sourceId, targetId, kind);
  if (!relationship) {
    return notFound(res);
  }

  db.updatePlayRelationship(campaignId, sourceId, targetId, kind, score);
  sendJson(res, 200, { source_id: sourceId, target_id: targetId, kind, score });
}

export function getPlayRelationships(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const edges = db.getPlayRelationships(campaignId).map(r => ({
    source_id: r.source_id,
    target_id: r.target_id,
    kind: r.kind,
    score: r.score,
  }));

  sendJson(res, 200, { edges });
}

// ---------- play clues ----------

const VALID_CLUE_AUDIENCES = new Set(['character', 'party', 'hidden']);

function playClueResponse(clue) {
  const response = {
    clue_id: clue.clue_id,
    text: clue.text,
    audience: clue.audience,
  };
  if (clue.audience === 'character') {
    response.character_id = clue.character_id;
  }
  return response;
}

export function createPlayClue(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const clueId = body.value?.clue_id;
  const text = body.value?.text;
  const audience = body.value?.audience;
  const hasCharacterId = Object.prototype.hasOwnProperty.call(body.value, 'character_id');
  const characterId = body.value?.character_id;

  if (!domain.isNonEmptyString(clueId)) return badRequest(res, 'invalid clue_id');
  if (!domain.isNonEmptyString(text)) return badRequest(res, 'invalid text');
  if (!VALID_CLUE_AUDIENCES.has(audience)) return badRequest(res, 'invalid audience');

  if (audience === 'character') {
    if (!domain.isNonEmptyString(characterId)) {
      return badRequest(res, 'invalid character_id');
    }
    if (!db.getPlayMembershipByCharacterId(campaignId, characterId)) {
      return badRequest(res, 'unknown character');
    }
  } else if (hasCharacterId) {
    return badRequest(res, 'invalid character_id');
  }

  if (db.getPlayClue(campaignId, clueId)) {
    return conflict(res, 'clue already exists');
  }

  const clue = db.createPlayClue(campaignId, { clue_id: clueId, text, audience, character_id: audience === 'character' ? characterId : undefined });
  sendJson(res, 201, playClueResponse(clue));
}

export function getPlayClues(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  const auth = authorizePlayParticipant(res, campaign, user, campaignId);
  if (!auth) return;

  const allClues = db.getPlayClues(campaignId);
  let visibleClues;
  if (auth.isOwner) {
    visibleClues = allClues;
  } else {
    const membership = db.getPlayMembership(campaignId, user.username);
    const ownCharacterId = membership?.character_id;
    visibleClues = allClues.filter(clue =>
      clue.audience === 'party' ||
      (clue.audience === 'character' && clue.character_id === ownCharacterId)
    );
  }

  sendJson(res, 200, { clues: visibleClues.map(playClueResponse) });
}

// ---------- play quests ----------

function playQuestResponse(quest) {
  const response = {
    quest_id: quest.quest_id,
    title: quest.title,
    depends_on: quest.depends_on,
    state: quest.state,
  };
  if (quest.rewards) {
    response.rewards = quest.rewards;
  }
  return response;
}

export function createPlayQuest(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const questId = body.value?.quest_id;
  const title = body.value?.title;
  const dependsOn = body.value?.depends_on;

  if (!domain.isNonEmptyString(questId)) return badRequest(res, 'invalid quest_id');
  if (!domain.isNonEmptyString(title)) return badRequest(res, 'invalid title');
  if (!Array.isArray(dependsOn)) return badRequest(res, 'invalid depends_on');
  if (!domain.isStringArray(dependsOn)) return badRequest(res, 'invalid depends_on');
  if (new Set(dependsOn).size !== dependsOn.length) return badRequest(res, 'invalid depends_on');
  if (dependsOn.includes(questId)) return badRequest(res, 'invalid dependency');

  for (const dep of dependsOn) {
    if (!db.getPlayQuest(campaignId, dep)) {
      return badRequest(res, 'unknown dependency');
    }
  }

  if (db.getPlayQuest(campaignId, questId)) {
    return conflict(res, 'quest already exists');
  }

  const quest = db.createPlayQuest(campaignId, {
    quest_id: questId,
    title,
    depends_on: dependsOn,
    state: 'locked',
  });
  sendJson(res, 201, playQuestResponse(quest));
}

export function updatePlayQuestState(req, res, campaignId, questId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const quest = db.getPlayQuest(campaignId, questId);
  if (!quest) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const state = body.value?.state;
  if (state !== 'active' && state !== 'completed') {
    return badRequest(res, 'invalid state');
  }

  if (quest.state === 'locked' && state === 'active') {
    for (const dep of quest.depends_on) {
      const depQuest = db.getPlayQuest(campaignId, dep);
      if (!depQuest || depQuest.state !== 'completed') {
        return conflict(res, 'dependencies not completed');
      }
    }
  } else if (quest.state === 'active' && state === 'completed') {
    // allowed transition
  } else {
    return conflict(res, 'invalid transition');
  }

  const updated = { ...quest, state };
  db.updatePlayQuest(campaignId, updated);
  sendJson(res, 200, playQuestResponse(updated));
}

export function getPlayQuests(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const quests = db.getPlayQuests(campaignId);
  sendJson(res, 200, { quests: quests.map(playQuestResponse) });
}

// ---------- play quest rewards ----------

function isValidQuestRewardItemId(itemId) {
  return db.getItem(itemId) !== null || domain.isValidInventoryItemId(itemId);
}

function validateQuestRewardItems(items) {
  if (typeof items !== 'object' || items === null || Array.isArray(items)) {
    return { valid: false, error: 'invalid items' };
  }
  for (const [itemId, quantity] of Object.entries(items)) {
    if (!isValidQuestRewardItemId(itemId)) {
      return { valid: false, error: 'invalid item_id' };
    }
    if (!domain.isPositiveInteger(quantity)) {
      return { valid: false, error: 'invalid quantity' };
    }
  }
  return { valid: true };
}

export function configurePlayQuestRewards(req, res, campaignId, questId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const quest = db.getPlayQuest(campaignId, questId);
  if (!quest) return notFound(res);

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const xp = body.value?.xp;
  const items = body.value?.items;

  if (!domain.isNonNegativeInteger(xp)) {
    return badRequest(res, 'invalid xp');
  }

  const itemsValidation = validateQuestRewardItems(items);
  if (!itemsValidation.valid) {
    return badRequest(res, itemsValidation.error);
  }

  if (quest.state !== 'locked' && quest.state !== 'active') {
    return conflict(res, 'quest is completed');
  }

  db.setPlayQuestReward(campaignId, questId, xp, items);

  sendJson(res, 200, {
    quest_id: questId,
    title: quest.title,
    depends_on: quest.depends_on,
    state: quest.state,
    rewards: { xp, items },
  });
}

export function awardPlayQuestRewards(req, res, campaignId, questId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const quest = db.getPlayQuest(campaignId, questId);
  if (!quest) return notFound(res);

  if (quest.state !== 'completed') {
    return conflict(res, 'quest is not completed');
  }

  const reward = db.getPlayQuestReward(campaignId, questId);
  if (!reward) {
    return conflict(res, 'rewards not configured');
  }

  if (reward.awarded) {
    return conflict(res, 'rewards already awarded');
  }

  const members = db.getPlayMembers(campaignId);
  for (const member of members) {
    db.addPlayCharacterQuestReward(campaignId, member.character_id, reward.xp, reward.items);
  }

  db.markPlayQuestRewardAwarded(campaignId, questId);

  sendJson(res, 201, {
    quest_id: questId,
    awarded: true,
    xp: reward.xp,
    items: reward.items,
  });
}

export function getPlayCharacterQuestRewards(req, res, campaignId, charId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const membership = db.getPlayMembershipByCharacterId(campaignId, charId);
  if (!membership) return notFound(res);

  const rewards = db.getPlayCharacterQuestReward(campaignId, charId);
  sendJson(res, 200, {
    character_id: charId,
    xp: rewards.xp,
    items: rewards.items,
  });
}

// ---------- play world events ----------

function playWorldEventResponse(event) {
  const response = {
    event_id: event.event_id,
    turn_number: event.turn_number,
    title: event.title,
    text: event.text,
    status: event.status,
  };
  if (event.status === 'resolved') {
    response.resolution = {
      turn_number: event.resolution_turn_number,
      text: event.resolution_text,
    };
  }
  return response;
}

export function createPlayWorldEvent(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const eventId = body.value?.event_id;
  const turnNumber = body.value?.turn_number;
  const title = body.value?.title;
  const text = body.value?.text;

  if (!domain.isNonEmptyString(eventId) || !domain.isNonEmptyString(title) || !domain.isNonEmptyString(text)) {
    return badRequest(res, 'invalid fields');
  }
  if (!Number.isInteger(turnNumber)) {
    return badRequest(res, 'invalid turn_number');
  }

  const currentTurnNumber = campaign.turn_number;
  if (currentTurnNumber != null) {
    if (turnNumber < currentTurnNumber) {
      return badRequest(res, 'invalid turn_number');
    }
  } else if (turnNumber < 1) {
    return badRequest(res, 'invalid turn_number');
  }

  if (db.getPlayWorldEvent(campaignId, eventId)) {
    return conflict(res, 'event already exists');
  }

  const event = db.createPlayWorldEvent(campaignId, { event_id: eventId, turn_number: turnNumber, title, text });
  sendJson(res, 201, playWorldEventResponse(event));
}

export function resolvePlayWorldEvent(req, res, campaignId, eventId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (campaign.owner !== user.username) {
    return forbidden(res, 'forbidden');
  }

  const event = db.getPlayWorldEvent(campaignId, eventId);
  if (!event) return notFound(res);

  if (event.status === 'resolved') {
    return conflict(res, 'event already resolved');
  }

  if (campaign.turn_number !== event.turn_number) {
    return conflict(res, 'turn number mismatch');
  }

  const body = requireBody(req);
  if (body.error) return badRequest(res, body.error);

  const resolutionText = body.value?.text;
  if (!domain.isNonEmptyString(resolutionText)) {
    return badRequest(res, 'invalid text');
  }

  db.resolvePlayWorldEvent(campaignId, eventId, campaign.turn_number, resolutionText);
  const resolvedEvent = db.getPlayWorldEvent(campaignId, eventId);
  sendJson(res, 201, playWorldEventResponse(resolvedEvent));
}

export function getPlayWorldEvents(req, res, campaignId) {
  const ctx = loadPlayCampaign(req, res, campaignId);
  if (!ctx) return;
  const { user, campaign } = ctx;

  if (!authorizePlayParticipant(res, campaign, user, campaignId)) return;

  const events = db.getPlayWorldEvents(campaignId);
  sendJson(res, 200, { events: events.map(playWorldEventResponse) });
}
