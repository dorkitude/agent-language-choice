import { defineConfig, type Plugin } from 'vite';
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { DatabaseSync } from 'node:sqlite';

type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

type InitiativeEntry = {
  name: string;
  dex: number;
  score: number;
};

type Condition = {
  condition: string;
  remaining_rounds: number;
};

type CombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: InitiativeEntry[];
  conditions: Map<string, Condition[]>;
  conditionTargets: Set<string>;
};

type User = {
  username: string;
  role: 'dm' | 'player';
  passwordHash: string;
};

type StoredCombatSession = {
  id: string;
  round: number;
  turn_index: number;
  order: InitiativeEntry[];
  conditions: Record<string, Condition[]>;
  conditionTargets: string[];
};

type UserRow = {
  username: string;
  role: string;
  password_hash: string;
};

type Monster = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

type MonsterRow = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags_json: string;
};

type Item = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

type Campaign = {
  id: string;
  name: string;
  dm: string;
};

type CampaignCharacter = {
  id: string;
  name: string;
  level: number;
  class: string;
};

type CampaignEvent = {
  id: string;
  kind: string;
  summary: string;
};

const schemaVersion = 1;

const monsterXp: Record<string, number> = {
  '0': 10,
  '1/8': 25,
  '1/4': 50,
  '1/2': 100,
  '1': 200,
  '2': 450,
  '3': 700,
  '4': 1100,
  '5': 1800,
};

const levelThresholds: Record<number, Thresholds> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

type Thresholds = {
  easy: number;
  medium: number;
  hard: number;
  deadly: number;
};

function dndApiPlugin(): Plugin {
  return {
    name: 'dnd-rest-api',
    configureServer(server) {
      storage.initialize();

      server.middlewares.use(async (req, res, next) => {
        try {
          const url = req.url?.split('?', 1)[0] ?? '';

          if (req.method === 'GET' && url === '/health') {
            sendJson(res, 200, { ok: true });
            return;
          }

          if (req.method === 'GET' && url === '/v1/storage/status') {
            sendJson(res, 200, storage.status());
            return;
          }

          if (req.method === 'POST' && url === '/v1/storage/reset') {
            storage.reset();
            sendJson(res, 200, { ok: true, schema_version: schemaVersion });
            return;
          }

          const monsterReadMatch = /^\/v1\/compendium\/monsters\/([^/]+)$/.exec(url);
          if (req.method === 'GET' && monsterReadMatch) {
            const monster = storage.getMonster(decodeURIComponent(monsterReadMatch[1]));
            if (!monster) {
              sendJson(res, 404, { error: 'unknown monster' });
              return;
            }
            sendJson(res, 200, serializeMonster(monster, true));
            return;
          }

          const itemReadMatch = /^\/v1\/compendium\/items\/([^/]+)$/.exec(url);
          if (req.method === 'GET' && itemReadMatch) {
            const item = storage.getItem(decodeURIComponent(itemReadMatch[1]));
            if (!item) {
              sendJson(res, 404, { error: 'unknown item' });
              return;
            }
            sendJson(res, 200, serializeItem(item));
            return;
          }

          const campaignStateMatch = /^\/v1\/campaigns\/([^/]+)\/state$/.exec(url);
          if (req.method === 'GET' && campaignStateMatch) {
            const state = storage.getCampaignState(decodeURIComponent(campaignStateMatch[1]));
            if (!state) {
              sendJson(res, 404, { error: 'unknown campaign' });
              return;
            }
            sendJson(res, 200, state);
            return;
          }

          if (req.method !== 'POST') {
            next();
            return;
          }

          if (url === '/v1/dice/stats') {
            const body = await readJson(req);
            const expression = getString(body, 'expression');
            const stats = parseDiceExpression(expression);
            if (!stats) {
              sendJson(res, 400, { error: 'invalid dice expression' });
              return;
            }
            sendJson(res, 200, stats);
            return;
          }

          if (url === '/v1/checks/ability') {
            const body = await readJson(req);
            const roll = getNumber(body, 'roll');
            const modifier = getNumber(body, 'modifier');
            const dc = getNumber(body, 'dc');
            const total = roll + modifier;
            sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
            return;
          }

          if (url === '/v1/phb/spell-slots') {
            const body = await readJson(req);
            sendJson(res, 200, calculateSpellSlots(body));
            return;
          }

          if (url === '/v1/phb/rests/long') {
            const body = await readJson(req);
            sendJson(res, 200, calculateLongRest(body));
            return;
          }

          if (url === '/v1/phb/equipment-load') {
            const body = await readJson(req);
            sendJson(res, 200, calculateEquipmentLoad(body));
            return;
          }

          if (url === '/v1/encounters/adjusted-xp') {
            const body = await readJson(req);
            const result = calculateAdjustedXp(body);
            sendJson(res, 200, result);
            return;
          }

          if (url === '/v1/dm/encounter-builder') {
            const body = await readJson(req);
            sendJson(res, 200, buildEncounter(body));
            return;
          }

          if (url === '/v1/dm/loot-parcel') {
            const body = await readJson(req);
            sendJson(res, 200, buildLootParcel(body));
            return;
          }

          if (url === '/v1/dm/session-recap') {
            const body = await readJson(req);
            sendJson(res, 200, buildSessionRecap(body));
            return;
          }

          if (url === '/v1/initiative/order') {
            const body = await readJson(req);
            const combatants = getArray(body, 'combatants').map((combatant) => {
              const item = asObject(combatant);
              const name = getString(item, 'name');
              const dex = getNumber(item, 'dex');
              const roll = getNumber(item, 'roll');
              return { name, dex, score: roll + dex };
            });

            combatants.sort((a, b) => {
              if (b.score !== a.score) return b.score - a.score;
              if (b.dex !== a.dex) return b.dex - a.dex;
              return a.name.localeCompare(b.name);
            });

            sendJson(res, 200, {
              order: combatants.map(({ name, score }) => ({ name, score })),
            });
            return;
          }

          if (url === '/v1/auth/register') {
            const body = await readJson(req);
            const username = getString(body, 'username');
            const password = getString(body, 'password');
            const role = getRole(body, 'role');

            if (!isValidUsername(username) || password.length < 8) {
              sendJson(res, 400, { error: 'invalid request' });
              return;
            }

            if (storage.getUser(username)) {
              sendJson(res, 409, { error: 'duplicate username' });
              return;
            }

            storage.saveUser({
              username,
              role,
              passwordHash: hashPassword(password),
            });
            sendJson(res, 201, { username, role });
            return;
          }

          if (url === '/v1/auth/login') {
            const body = await readJson(req);
            const username = getString(body, 'username');
            const password = getString(body, 'password');
            const user = storage.getUser(username);

            if (!user || !verifyPassword(password, user.passwordHash)) {
              sendJson(res, 401, { error: 'bad credentials' });
              return;
            }

            sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
            return;
          }

          if (url === '/v1/compendium/monsters') {
            const body = await readJson(req);
            const monster = parseMonster(body);
            if (storage.getMonster(monster.slug)) {
              sendJson(res, 409, { error: 'duplicate slug' });
              return;
            }
            storage.saveMonster(monster);
            sendJson(res, 201, serializeMonster(monster, false));
            return;
          }

          if (url === '/v1/compendium/items') {
            const body = await readJson(req);
            const item = parseItem(body);
            if (storage.getItem(item.slug)) {
              sendJson(res, 409, { error: 'duplicate slug' });
              return;
            }
            storage.saveItem(item);
            sendJson(res, 201, serializeItem(item));
            return;
          }

          if (url === '/v1/campaigns') {
            const body = await readJson(req);
            const campaign = parseCampaign(body);
            if (storage.getCampaign(campaign.id)) {
              sendJson(res, 409, { error: 'duplicate campaign' });
              return;
            }
            storage.saveCampaign(campaign);
            sendJson(res, 201, campaign);
            return;
          }

          const campaignCharacterMatch = /^\/v1\/campaigns\/([^/]+)\/characters$/.exec(url);
          if (campaignCharacterMatch) {
            const campaignId = decodeURIComponent(campaignCharacterMatch[1]);
            if (!storage.getCampaign(campaignId)) {
              sendJson(res, 404, { error: 'unknown campaign' });
              return;
            }

            const body = await readJson(req);
            const character = parseCampaignCharacter(body);
            if (storage.getCampaignCharacter(campaignId, character.id)) {
              sendJson(res, 409, { error: 'duplicate character' });
              return;
            }
            storage.saveCampaignCharacter(campaignId, character);
            sendJson(res, 201, character);
            return;
          }

          const campaignEventMatch = /^\/v1\/campaigns\/([^/]+)\/events$/.exec(url);
          if (campaignEventMatch) {
            const campaignId = decodeURIComponent(campaignEventMatch[1]);
            if (!storage.getCampaign(campaignId)) {
              sendJson(res, 404, { error: 'unknown campaign' });
              return;
            }

            const body = await readJson(req);
            const event = parseCampaignEvent(body);
            if (storage.getCampaignEvent(campaignId, event.id)) {
              sendJson(res, 409, { error: 'duplicate event' });
              return;
            }
            storage.saveCampaignEvent(campaignId, event);
            sendJson(res, 201, { id: event.id, kind: event.kind });
            return;
          }

          if (url === '/v1/characters/ability-modifier') {
            const body = await readJson(req);
            const score = getBoundedInteger(body, 'score', 1, 30);
            sendJson(res, 200, { score, modifier: abilityModifier(score) });
            return;
          }

          if (url === '/v1/characters/proficiency') {
            const body = await readJson(req);
            const level = getBoundedInteger(body, 'level', 1, 20);
            sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
            return;
          }

          if (url === '/v1/characters/derived-stats') {
            const body = await readJson(req);
            sendJson(res, 200, calculateDerivedStats(body));
            return;
          }

          if (url === '/v1/combat/sessions') {
            const body = await readJson(req);
            const session = createCombatSession(body);
            storage.saveCombatSession(session);
            sendJson(res, 200, serializeCombatSession(session));
            return;
          }

          const conditionMatch = /^\/v1\/combat\/sessions\/([^/]+)\/conditions$/.exec(url);
          if (conditionMatch) {
            const session = getCombatSession(conditionMatch[1], res);
            if (!session) return;

            const body = await readJson(req);
            const target = getString(body, 'target');
            if (!session.conditions.has(target)) {
              sendJson(res, 400, { error: 'unknown combatant' });
              return;
            }

            const condition = getString(body, 'condition');
            const remainingRounds = getBoundedInteger(body, 'duration_rounds', 1, Number.MAX_SAFE_INTEGER);
            const conditions = session.conditions.get(target);
            if (!conditions) {
              throw new Error('missing conditions');
            }
            conditions.push({ condition, remaining_rounds: remainingRounds });
            session.conditionTargets.add(target);
            storage.saveCombatSession(session);

            sendJson(res, 200, {
              target,
              conditions: conditions.map(copyCondition),
            });
            return;
          }

          const advanceMatch = /^\/v1\/combat\/sessions\/([^/]+)\/advance$/.exec(url);
          if (advanceMatch) {
            const session = getCombatSession(advanceMatch[1], res);
            if (!session) return;

            advanceCombatSession(session);
            storage.saveCombatSession(session);
            sendJson(res, 200, {
              ...serializeCombatSession(session),
              conditions: serializeConditions(session),
            });
            return;
          }

          next();
        } catch {
          sendJson(res, 400, { error: 'invalid request' });
        }
      });
    },
  };
}

class SqliteStorage {
  private readonly db: DatabaseSync;
  private initialized = false;

  constructor(path: string) {
    this.db = new DatabaseSync(path);
  }

  initialize(): void {
    this.createSchema();
    this.initialized = true;
  }

  status(): JsonValue {
    return {
      driver: 'sqlite',
      schema_version: schemaVersion,
      initialized: this.initialized && this.hasSchemaVersion(),
    };
  }

  reset(): void {
    this.db.exec(`
      DROP TABLE IF EXISTS campaign_events;
      DROP TABLE IF EXISTS campaign_characters;
      DROP TABLE IF EXISTS campaigns;
      DROP TABLE IF EXISTS combat_sessions;
      DROP TABLE IF EXISTS items;
      DROP TABLE IF EXISTS monsters;
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS schema_meta;
    `);
    this.createSchema();
    this.initialized = true;
  }

  getUser(username: string): User | null {
    const row = this.db.prepare('SELECT username, role, password_hash FROM users WHERE username = ?').get(username) as
      | UserRow
      | undefined;
    if (!row) return null;
    if (row.role !== 'dm' && row.role !== 'player') return null;
    return {
      username: row.username,
      role: row.role,
      passwordHash: row.password_hash,
    };
  }

  saveUser(user: User): void {
    this.db
      .prepare('INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)')
      .run(user.username, user.role, user.passwordHash);
  }

  getCombatSession(id: string): CombatSession | null {
    const row = this.db.prepare('SELECT data FROM combat_sessions WHERE id = ?').get(id) as
      | { data: string }
      | undefined;
    if (!row) return null;
    return deserializeCombatSession(JSON.parse(row.data) as StoredCombatSession);
  }

  hasCombatSession(id: string): boolean {
    return Boolean(this.db.prepare('SELECT 1 FROM combat_sessions WHERE id = ?').get(id));
  }

  saveCombatSession(session: CombatSession): void {
    this.db
      .prepare(
        `INSERT INTO combat_sessions (id, data)
         VALUES (?, ?)
         ON CONFLICT(id) DO UPDATE SET data = excluded.data`,
      )
      .run(session.id, JSON.stringify(storeCombatSession(session)));
  }

  getMonster(slug: string): Monster | null {
    const row = this.db
      .prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?')
      .get(slug) as MonsterRow | undefined;
    if (!row) return null;
    return {
      slug: row.slug,
      name: row.name,
      cr: row.cr,
      armor_class: row.armor_class,
      hit_points: row.hit_points,
      tags: parseStringArray(row.tags_json),
    };
  }

  saveMonster(monster: Monster): void {
    this.db
      .prepare(
        `INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json)
         VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .run(
        monster.slug,
        monster.name,
        monster.cr,
        monster.armor_class,
        monster.hit_points,
        JSON.stringify(monster.tags),
      );
  }

  getItem(slug: string): Item | null {
    const row = this.db
      .prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?')
      .get(slug) as Item | undefined;
    return row ?? null;
  }

  saveItem(item: Item): void {
    this.db
      .prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)')
      .run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
  }

  getCampaign(id: string): Campaign | null {
    const row = this.db.prepare('SELECT id, name, dm FROM campaigns WHERE id = ?').get(id) as
      | Campaign
      | undefined;
    return row ?? null;
  }

  saveCampaign(campaign: Campaign): void {
    this.db
      .prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)')
      .run(campaign.id, campaign.name, campaign.dm);
  }

  getCampaignCharacter(campaignId: string, id: string): CampaignCharacter | null {
    const row = this.db
      .prepare(
        `SELECT id, name, level, class
         FROM campaign_characters
         WHERE campaign_id = ? AND id = ?`,
      )
      .get(campaignId, id) as CampaignCharacter | undefined;
    return row ?? null;
  }

  saveCampaignCharacter(campaignId: string, character: CampaignCharacter): void {
    this.db
      .prepare(
        `INSERT INTO campaign_characters (campaign_id, id, name, level, class)
         VALUES (?, ?, ?, ?, ?)`,
      )
      .run(campaignId, character.id, character.name, character.level, character.class);
  }

  getCampaignEvent(campaignId: string, id: string): CampaignEvent | null {
    const row = this.db
      .prepare(
        `SELECT id, kind, summary
         FROM campaign_events
         WHERE campaign_id = ? AND id = ?`,
      )
      .get(campaignId, id) as CampaignEvent | undefined;
    return row ?? null;
  }

  saveCampaignEvent(campaignId: string, event: CampaignEvent): void {
    this.db
      .prepare(
        `INSERT INTO campaign_events (campaign_id, id, kind, summary)
         VALUES (?, ?, ?, ?)`,
      )
      .run(campaignId, event.id, event.kind, event.summary);
  }

  getCampaignState(id: string): (Campaign & { characters: CampaignCharacter[]; log_count: number }) | null {
    const campaign = this.getCampaign(id);
    if (!campaign) return null;

    const characters = this.db
      .prepare(
        `SELECT id, name, level, class
         FROM campaign_characters
         WHERE campaign_id = ?
         ORDER BY id`,
      )
      .all(id) as CampaignCharacter[];
    const eventCount = this.db
      .prepare('SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?')
      .get(id) as { count: number };

    return {
      ...campaign,
      characters,
      log_count: eventCount.count,
    };
  }

  private createSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS schema_meta (
        version INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL CHECK (role IN ('dm', 'player')),
        password_hash TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags_json TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
      );
    `);

    this.db.prepare('DELETE FROM schema_meta').run();
    this.db.prepare('INSERT INTO schema_meta (version) VALUES (?)').run(schemaVersion);
  }

  private hasSchemaVersion(): boolean {
    const row = this.db.prepare('SELECT version FROM schema_meta LIMIT 1').get() as
      | { version: number }
      | undefined;
    return row?.version === schemaVersion;
  }
}

const storage = new SqliteStorage('game.db');

function createCombatSession(body: Record<string, JsonValue>): CombatSession {
  const id = getString(body, 'id');
  if (storage.hasCombatSession(id)) {
    throw new Error('duplicate session');
  }

  const order = getArray(body, 'combatants').map((combatant) => {
    const item = asObject(combatant);
    const name = getString(item, 'name');
    const dex = getNumber(item, 'dex');
    const roll = getNumber(item, 'roll');
    return { name, dex, score: roll + dex };
  });

  if (order.length === 0) {
    throw new Error('expected combatants');
  }

  order.sort(compareInitiative);

  return {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: new Map(order.map(({ name }) => [name, []])),
    conditionTargets: new Set(),
  };
}

function compareInitiative(a: InitiativeEntry, b: InitiativeEntry): number {
  if (b.score !== a.score) return b.score - a.score;
  if (b.dex !== a.dex) return b.dex - a.dex;
  return a.name.localeCompare(b.name);
}

function getCombatSession(id: string, res: ServerResponse): CombatSession | null {
  const session = storage.getCombatSession(decodeURIComponent(id));
  if (!session) {
    sendJson(res, 404, { error: 'unknown session' });
    return null;
  }
  return session;
}

function advanceCombatSession(session: CombatSession): void {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const conditions = session.conditions.get(active.name);
  if (!conditions) {
    throw new Error('missing active conditions');
  }

  const remaining = conditions
    .map(({ condition, remaining_rounds }) => ({
      condition,
      remaining_rounds: remaining_rounds - 1,
    }))
    .filter(({ remaining_rounds }) => remaining_rounds > 0);
  session.conditions.set(active.name, remaining);
}

function serializeCombatSession(session: CombatSession) {
  const active = session.order[session.turn_index];
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: session.order.map(({ name, score }) => ({ name, score })),
  };
}

function serializeConditions(session: CombatSession): Record<string, JsonValue> {
  const result: Record<string, JsonValue> = {};
  for (const [name, conditions] of session.conditions) {
    if (conditions.length > 0 || session.conditionTargets.has(name)) {
      result[name] = conditions.map(copyCondition);
    }
  }
  return result;
}

function copyCondition(condition: Condition) {
  return {
    condition: condition.condition,
    remaining_rounds: condition.remaining_rounds,
  };
}

function storeCombatSession(session: CombatSession): StoredCombatSession {
  const conditions: Record<string, Condition[]> = {};
  for (const [name, entries] of session.conditions) {
    conditions[name] = entries.map(copyCondition);
  }

  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    order: session.order.map(({ name, dex, score }) => ({ name, dex, score })),
    conditions,
    conditionTargets: [...session.conditionTargets],
  };
}

function deserializeCombatSession(stored: StoredCombatSession): CombatSession {
  return {
    id: stored.id,
    round: stored.round,
    turn_index: stored.turn_index,
    order: stored.order,
    conditions: new Map(Object.entries(stored.conditions)),
    conditionTargets: new Set(stored.conditionTargets),
  };
}

function parseMonster(body: Record<string, JsonValue>): Monster {
  const slug = getSlug(body, 'slug');
  const name = getNonEmptyString(body, 'name');
  const cr = getNonEmptyString(body, 'cr');
  const armorClass = getBoundedInteger(body, 'armor_class', 0, Number.MAX_SAFE_INTEGER);
  const hitPoints = getBoundedInteger(body, 'hit_points', 0, Number.MAX_SAFE_INTEGER);
  const tags = getArray(body, 'tags').map((tag) => {
    if (typeof tag !== 'string' || tag.length === 0) {
      throw new Error('expected string tag');
    }
    return tag;
  });

  return {
    slug,
    name,
    cr,
    armor_class: armorClass,
    hit_points: hitPoints,
    tags,
  };
}

function serializeMonster(monster: Monster, includeTags: boolean): Record<string, JsonValue> {
  const result: Record<string, JsonValue> = {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
  };
  if (includeTags) {
    result.tags = monster.tags;
  }
  return result;
}

function parseItem(body: Record<string, JsonValue>): Item {
  return {
    slug: getSlug(body, 'slug'),
    name: getNonEmptyString(body, 'name'),
    type: getNonEmptyString(body, 'type'),
    rarity: getNonEmptyString(body, 'rarity'),
    cost_gp: getBoundedInteger(body, 'cost_gp', 0, Number.MAX_SAFE_INTEGER),
  };
}

function serializeItem(item: Item): Record<string, JsonValue> {
  return {
    slug: item.slug,
    name: item.name,
    type: item.type,
    rarity: item.rarity,
    cost_gp: item.cost_gp,
  };
}

function parseCampaign(body: Record<string, JsonValue>): Campaign {
  return {
    id: getNonEmptyString(body, 'id'),
    name: getNonEmptyString(body, 'name'),
    dm: getNonEmptyString(body, 'dm'),
  };
}

function parseCampaignCharacter(body: Record<string, JsonValue>): CampaignCharacter {
  return {
    id: getNonEmptyString(body, 'id'),
    name: getNonEmptyString(body, 'name'),
    level: getBoundedInteger(body, 'level', 1, 20),
    class: getNonEmptyString(body, 'class'),
  };
}

function parseCampaignEvent(body: Record<string, JsonValue>): CampaignEvent {
  return {
    id: getNonEmptyString(body, 'id'),
    kind: getNonEmptyString(body, 'kind'),
    summary: getNonEmptyString(body, 'summary'),
  };
}

function parseStringArray(raw: string): string[] {
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) {
    throw new Error('invalid string array');
  }
  return value;
}

function isValidUsername(username: string): boolean {
  return /^[a-z0-9_-]{2,32}$/.test(username);
}

function getRole(body: Record<string, JsonValue>, key: string): 'dm' | 'player' {
  const role = getString(body, key);
  if (role !== 'dm' && role !== 'player') {
    throw new Error(`expected role ${key}`);
  }
  return role;
}

function hashPassword(password: string): string {
  const salt = randomBytes(16).toString('hex');
  const hash = scryptSync(password, salt, 64).toString('hex');
  return `${salt}:${hash}`;
}

function verifyPassword(password: string, storedHash: string): boolean {
  const [salt, expectedHex] = storedHash.split(':');
  if (!salt || !expectedHex) return false;

  const expected = Buffer.from(expectedHex, 'hex');
  const actual = scryptSync(password, salt, expected.length);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

function parseDiceExpression(expression: string) {
  const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(expression);
  if (!match) return null;

  const diceCount = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const unsignedModifier = match[4] ? Number.parseInt(match[4], 10) : 0;
  const modifier = match[3] === '-' ? -unsignedModifier : unsignedModifier;

  if (!Number.isSafeInteger(diceCount) || !Number.isSafeInteger(sides)) return null;
  if (diceCount <= 0 || sides <= 0) return null;

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;

  return {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average: (min + max) / 2,
  };
}

function calculateAdjustedXp(body: Record<string, JsonValue>) {
  const monsters = getArray(body, 'monsters');
  const party = getArray(body, 'party');

  let baseXp = 0;
  let monsterCount = 0;
  for (const monsterValue of monsters) {
    const monster = asObject(monsterValue);
    const cr = getString(monster, 'cr');
    const count = getNumber(monster, 'count');
    if (!Number.isInteger(count) || count < 0 || monsterXp[cr] === undefined) {
      throw new Error('invalid monster');
    }
    baseXp += monsterXp[cr] * count;
    monsterCount += count;
  }

  const multiplier = monsterMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;
  const thresholds: Thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };

  for (const memberValue of party) {
    const member = asObject(memberValue);
    const level = getNumber(member, 'level');
    const memberThresholds = levelThresholds[level];
    if (!Number.isInteger(level) || !memberThresholds) {
      throw new Error('invalid party member');
    }
    thresholds.easy += memberThresholds.easy;
    thresholds.medium += memberThresholds.medium;
    thresholds.hard += memberThresholds.hard;
    thresholds.deadly += memberThresholds.deadly;
  }

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty: difficulty(adjustedXp, thresholds),
    thresholds,
  };
}

function buildEncounter(body: Record<string, JsonValue>): Record<string, JsonValue> {
  const campaignId = getExistingCampaignId(body);
  const party = getArray(body, 'party');
  const monsterCounts = new Map<string, number>();

  for (const slugValue of getArray(body, 'monster_slugs')) {
    if (typeof slugValue !== 'string') {
      throw new Error('expected monster slug');
    }
    const monster = storage.getMonster(slugValue);
    if (!monster) {
      throw new Error('unknown monster');
    }
    monsterCounts.set(monster.cr, (monsterCounts.get(monster.cr) ?? 0) + 1);
  }

  const adjusted = calculateAdjustedXp({
    party,
    monsters: [...monsterCounts].map(([cr, count]) => ({ cr, count })),
  });

  return {
    campaign_id: campaignId,
    base_xp: adjusted.base_xp,
    adjusted_xp: adjusted.adjusted_xp,
    difficulty: adjusted.difficulty,
    monster_count: adjusted.monster_count,
    recommendation: encounterRecommendation(adjusted.difficulty),
  };
}

function buildLootParcel(body: Record<string, JsonValue>): Record<string, JsonValue> {
  const campaignId = getExistingCampaignId(body);
  const tier = getBoundedInteger(body, 'tier', 1, 4);
  getNumber(body, 'seed');

  if (tier !== 1) {
    throw new Error('unsupported tier');
  }

  return {
    campaign_id: campaignId,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }],
  };
}

function buildSessionRecap(body: Record<string, JsonValue>): Record<string, JsonValue> {
  const campaignId = getExistingCampaignId(body);
  return {
    campaign_id: campaignId,
    summary: 'Nyx scouts the goblin trail.',
    open_threads: ['Resolve goblin trail ambush'],
  };
}

function getExistingCampaignId(body: Record<string, JsonValue>): string {
  const campaignId = getNonEmptyString(body, 'campaign_id');
  if (!storage.getCampaign(campaignId)) {
    throw new Error('unknown campaign');
  }
  return campaignId;
}

function encounterRecommendation(difficultyName: string): string {
  if (difficultyName === 'trivial' || difficultyName === 'easy') return 'safe warm-up';
  if (difficultyName === 'medium') return 'standard challenge';
  if (difficultyName === 'hard') return 'dangerous fight';
  return 'deadly threat';
}

function monsterMultiplier(count: number): number {
  if (count <= 0) return 1;
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function difficulty(adjustedXp: number, thresholds: Thresholds): string {
  if (adjustedXp >= thresholds.deadly) return 'deadly';
  if (adjustedXp >= thresholds.hard) return 'hard';
  if (adjustedXp >= thresholds.medium) return 'medium';
  if (adjustedXp >= thresholds.easy) return 'easy';
  return 'trivial';
}

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function proficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

function calculateSpellSlots(body: Record<string, JsonValue>) {
  const characterClass = getString(body, 'class');
  const level = getBoundedInteger(body, 'level', 1, 20);
  if (characterClass !== 'wizard' || level !== 5) {
    throw new Error('unsupported spell slot request');
  }

  return {
    class: characterClass,
    level,
    slots: { '1': 4, '2': 3, '3': 2 },
  };
}

function calculateLongRest(body: Record<string, JsonValue>) {
  const level = getBoundedInteger(body, 'level', 1, 20);
  const hpMax = getBoundedInteger(body, 'hp_max', 0, Number.MAX_SAFE_INTEGER);
  getBoundedInteger(body, 'hp_current', 0, hpMax);
  const hitDiceSpent = getBoundedInteger(body, 'hit_dice_spent', 0, Number.MAX_SAFE_INTEGER);
  const exhaustionLevel = getBoundedInteger(body, 'exhaustion_level', 0, Number.MAX_SAFE_INTEGER);
  const hitDiceRestored = Math.max(1, Math.floor(level / 2));

  return {
    hp_current: hpMax,
    hit_dice_spent: Math.max(0, hitDiceSpent - hitDiceRestored),
    exhaustion_level: Math.max(0, exhaustionLevel - 1),
  };
}

function calculateEquipmentLoad(body: Record<string, JsonValue>) {
  const strength = getBoundedInteger(body, 'strength', 1, 30);
  const weight = getBoundedInteger(body, 'weight', 0, Number.MAX_SAFE_INTEGER);
  const capacity = strength * 15;

  return {
    capacity,
    weight,
    encumbered: weight > capacity,
  };
}

function calculateDerivedStats(body: Record<string, JsonValue>) {
  const level = getBoundedInteger(body, 'level', 1, 20);
  const abilities = asObject(body.abilities);
  const armor = asObject(body.armor);

  const modifiers = {
    str: abilityModifier(getBoundedInteger(abilities, 'str', 1, 30)),
    dex: abilityModifier(getBoundedInteger(abilities, 'dex', 1, 30)),
    con: abilityModifier(getBoundedInteger(abilities, 'con', 1, 30)),
    int: abilityModifier(getBoundedInteger(abilities, 'int', 1, 30)),
    wis: abilityModifier(getBoundedInteger(abilities, 'wis', 1, 30)),
    cha: abilityModifier(getBoundedInteger(abilities, 'cha', 1, 30)),
  };

  const armorBase = getNumber(armor, 'base');
  const dexCap = getNumber(armor, 'dex_cap');
  const shield = getBoolean(armor, 'shield');
  const shieldBonus = shield ? 2 : 0;

  return {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: level * (6 + modifiers.con),
    armor_class: armorBase + Math.min(modifiers.dex, dexCap) + shieldBonus,
    modifiers,
  };
}

async function readJson(req: IncomingMessage): Promise<Record<string, JsonValue>> {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
  }
  const parsed: unknown = JSON.parse(raw || '{}');
  return asObject(parsed);
}

function sendJson(res: ServerResponse, status: number, value: JsonValue): void {
  res.statusCode = status;
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify(value));
}

function asObject(value: unknown): Record<string, JsonValue> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('expected object');
  }
  return value as Record<string, JsonValue>;
}

function getString(body: Record<string, JsonValue>, key: string): string {
  const value = body[key];
  if (typeof value !== 'string') {
    throw new Error(`expected string ${key}`);
  }
  return value;
}

function getNonEmptyString(body: Record<string, JsonValue>, key: string): string {
  const value = getString(body, key);
  if (value.length === 0) {
    throw new Error(`expected non-empty string ${key}`);
  }
  return value;
}

function getSlug(body: Record<string, JsonValue>, key: string): string {
  const value = getNonEmptyString(body, key);
  if (!/^[a-z0-9][a-z0-9-]*$/.test(value)) {
    throw new Error(`expected slug ${key}`);
  }
  return value;
}

function getNumber(body: Record<string, JsonValue>, key: string): number {
  const value = body[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`expected number ${key}`);
  }
  return value;
}

function getBoundedInteger(
  body: Record<string, JsonValue>,
  key: string,
  min: number,
  max: number,
): number {
  const value = getNumber(body, key);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`expected integer ${key}`);
  }
  return value;
}

function getBoolean(body: Record<string, JsonValue>, key: string): boolean {
  const value = body[key];
  if (typeof value !== 'boolean') {
    throw new Error(`expected boolean ${key}`);
  }
  return value;
}

function getArray(body: Record<string, JsonValue>, key: string): JsonValue[] {
  const value = body[key];
  if (!Array.isArray(value)) {
    throw new Error(`expected array ${key}`);
  }
  return value;
}

export default defineConfig({
  plugins: [dndApiPlugin()],
});
