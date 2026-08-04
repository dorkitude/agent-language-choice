import { db } from './db.js';

// Thin key/value wrappers around single-table stores. Records are stored as
// JSON blobs; callers own the shape of `record`/`session`.
//
// Nearly every table below fits one of three shapes, so the raw SQL for each
// shape is written once as a helper and individual stores just say which
// table/columns they use:
//   - keyedStore: single id -> JSON blob (e.g. `monsters` keyed by `slug`).
//   - *Scoped helpers: (campaign_id, id) -> JSON blob, optionally listable.
//   - ledgerStore: append-only rows with real columns (no update, no get).
// A few stores (`users`, `playCampaignEvents`,
// `playCampaignLocationConnections`) don't fit any shape cleanly and stay
// hand-written below.

function hasById(table, idCol, id) {
  return db.prepare(`SELECT 1 FROM ${table} WHERE ${idCol} = ?`).get(id) !== undefined;
}

function getById(table, idCol, id) {
  const row = db.prepare(`SELECT data FROM ${table} WHERE ${idCol} = ?`).get(id);
  return row ? JSON.parse(row.data) : undefined;
}

function setById(table, idCol, id, record) {
  db.prepare(`INSERT OR REPLACE INTO ${table} (${idCol}, data) VALUES (?, ?)`).run(id, JSON.stringify(record));
}

function keyedStore(table, idCol = 'id') {
  return {
    has: (id) => hasById(table, idCol, id),
    get: (id) => getById(table, idCol, id),
    set: (id, record) => setById(table, idCol, id, record),
  };
}

function hasScoped(table, idCol, campaignId, id) {
  return (
    db.prepare(`SELECT 1 FROM ${table} WHERE campaign_id = ? AND ${idCol} = ?`).get(campaignId, id) !== undefined
  );
}

function getScoped(table, idCol, campaignId, id) {
  const row = db.prepare(`SELECT data FROM ${table} WHERE campaign_id = ? AND ${idCol} = ?`).get(campaignId, id);
  return row ? JSON.parse(row.data) : undefined;
}

function setScoped(table, idCol, campaignId, id, record) {
  // `INSERT OR REPLACE` deletes and reinserts on conflict, which assigns a
  // new (larger) rowid to updated rows and corrupts the rowid-based
  // insertion order that `listScoped` relies on. Upsert via `ON CONFLICT`
  // instead so an update keeps its original rowid/position.
  db.prepare(
    `INSERT INTO ${table} (campaign_id, ${idCol}, data) VALUES (?, ?, ?)
     ON CONFLICT(campaign_id, ${idCol}) DO UPDATE SET data = excluded.data`
  ).run(campaignId, id, JSON.stringify(record));
}

function listScoped(table, campaignId, orderBy = 'rowid') {
  const rows = db.prepare(`SELECT data FROM ${table} WHERE campaign_id = ? ORDER BY ${orderBy}`).all(campaignId);
  return rows.map((row) => JSON.parse(row.data));
}

// An append-only ledger: rows are plain columns (not a JSON blob) and there
// is no update or get-by-id, only `add` and `listByCampaign`. `columns` must
// match the record fields 1:1, in insert order.
function ledgerStore(table, columns) {
  const insertCols = ['campaign_id', ...columns];
  const placeholders = insertCols.map(() => '?').join(', ');
  return {
    add(campaignId, record) {
      db.prepare(`INSERT INTO ${table} (${insertCols.join(', ')}) VALUES (${placeholders})`).run(
        campaignId,
        ...columns.map((col) => record[col])
      );
    },
    listByCampaign(campaignId) {
      return db
        .prepare(`SELECT ${columns.join(', ')} FROM ${table} WHERE campaign_id = ? ORDER BY rowid`)
        .all(campaignId);
    },
  };
}

// The one store with real columns instead of a JSON blob, since callers need
// to filter/select by username without deserializing every row.
export const users = {
  has(username) {
    return db.prepare('SELECT 1 FROM users WHERE username = ?').get(username) !== undefined;
  },
  get(username) {
    const row = db
      .prepare('SELECT username, role, password_hash AS passwordHash FROM users WHERE username = ?')
      .get(username);
    return row || undefined;
  },
  set(username, user) {
    db.prepare('INSERT OR REPLACE INTO users (username, role, password_hash) VALUES (?, ?, ?)').run(
      username,
      user.role,
      user.passwordHash
    );
  },
};

export const combatSessions = keyedStore('combat_sessions');
export const monsters = keyedStore('monsters', 'slug');
export const items = keyedStore('items', 'slug');
export const campaigns = keyedStore('campaigns');
export const playCampaigns = keyedStore('play_campaigns');

export const campaignCharacters = {
  has: (campaignId, id) => hasScoped('campaign_characters', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_characters', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_characters', campaignId),
};

export const campaignEvents = {
  has: (campaignId, id) => hasScoped('campaign_events', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_events', 'id', campaignId, id, record),
  countByCampaign(campaignId) {
    const row = db.prepare('SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?').get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('campaign_events', campaignId),
};

export const campaignQuests = {
  has: (campaignId, id) => hasScoped('campaign_quests', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('campaign_quests', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_quests', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_quests', campaignId),
};

export const campaignFactions = {
  has: (campaignId, id) => hasScoped('campaign_factions', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('campaign_factions', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_factions', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_factions', campaignId),
};

export const campaignInventory = ledgerStore('campaign_inventory', ['item_slug', 'owner', 'quantity']);
export const campaignEquipment = ledgerStore('campaign_equipment', ['character_id', 'item_slug', 'quantity']);

export const campaignCraftingProjects = {
  has: (campaignId, id) => hasScoped('campaign_crafting_projects', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('campaign_crafting_projects', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_crafting_projects', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_crafting_projects', campaignId),
};

export const campaignSessions = {
  has: (campaignId, id) => hasScoped('campaign_sessions', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('campaign_sessions', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_sessions', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_sessions', campaignId),
};

export const playCampaignMembers = {
  hasCharacter: (campaignId, characterId) =>
    hasScoped('play_campaign_members', 'character_id', campaignId, characterId),
  set: (campaignId, characterId, record) =>
    setScoped('play_campaign_members', 'character_id', campaignId, characterId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_members', campaignId),
};

// Sequence numbers are assigned by callers (see routes/play.js's
// `appendEvent`) and used as the list order, so this store can't reuse the
// plain `listScoped`/`rowid` helper.
export const playCampaignEvents = {
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  add(campaignId, record) {
    db.prepare('INSERT INTO play_campaign_events (campaign_id, sequence, data) VALUES (?, ?, ?)').run(
      campaignId,
      record.sequence,
      JSON.stringify(record)
    );
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_events', campaignId, 'sequence'),
};

export const playCampaignScenes = {
  has: (campaignId, id) => hasScoped('play_campaign_scenes', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('play_campaign_scenes', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('play_campaign_scenes', 'id', campaignId, id, record),
};

export const playCampaignLocations = {
  has: (campaignId, id) => hasScoped('play_campaign_locations', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('play_campaign_locations', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('play_campaign_locations', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_locations', campaignId),
};

// Composite-keyed on (from_id, to_id) — a location graph edge, not a single
// entity — so it doesn't fit the id-scoped helpers above.
export const playCampaignLocationConnections = {
  has(campaignId, fromId, toId) {
    return (
      db
        .prepare(
          'SELECT 1 FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?'
        )
        .get(campaignId, fromId, toId) !== undefined
    );
  },
  set(campaignId, fromId, toId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_location_connections (campaign_id, from_id, to_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, fromId, toId, JSON.stringify(record));
  },
  listByFrom(campaignId, fromId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? ORDER BY rowid'
      )
      .all(campaignId, fromId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

export const playCampaignEncounters = {
  has: (campaignId, id) => hasScoped('play_campaign_encounters', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('play_campaign_encounters', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('play_campaign_encounters', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_encounters', campaignId),
};

// Composite-keyed on (campaign_id, character_id, spell_id) — a character can
// know several spells, so this doesn't fit the single-id scoped helpers.
export const playCampaignSpells = {
  has(campaignId, characterId, spellId) {
    return (
      db
        .prepare(
          'SELECT 1 FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?'
        )
        .get(campaignId, characterId, spellId) !== undefined
    );
  },
  set(campaignId, characterId, spellId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_spells (campaign_id, character_id, spell_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, characterId, spellId, JSON.stringify(record));
  },
  listByCharacter(campaignId, characterId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid'
      )
      .all(campaignId, characterId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// Append-only per-character cast log, ordered by an in-character sequence
// number assigned by the caller (see routes/play.js's casts endpoint).
export const playCampaignCasts = {
  add(campaignId, characterId, record) {
    db.prepare(
      'INSERT INTO play_campaign_casts (campaign_id, character_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, characterId, record.sequence, JSON.stringify(record));
  },
  listByCharacter(campaignId, characterId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence'
      )
      .all(campaignId, characterId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// One row per character; a null `data` means no active concentration.
export const playCampaignConcentration = {
  get(campaignId, characterId) {
    const row = db
      .prepare('SELECT data FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?')
      .get(campaignId, characterId);
    if (!row || row.data === null) return null;
    return JSON.parse(row.data);
  },
  set(campaignId, characterId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_concentration (campaign_id, character_id, data) VALUES (?, ?, ?)'
    ).run(campaignId, characterId, record ? JSON.stringify(record) : null);
  },
};

// Composite-keyed on (campaign_id, character_id, item_id) — a character can
// hold several item stacks, so this doesn't fit the single-id scoped helpers.
export const playCampaignItems = {
  get(campaignId, characterId, itemId) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?'
      )
      .get(campaignId, characterId, itemId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, characterId, itemId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_items (campaign_id, character_id, item_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, characterId, itemId, JSON.stringify(record));
  },
  listByCharacter(campaignId, characterId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id'
      )
      .all(campaignId, characterId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// Composite-keyed on (campaign_id, character_id, slot) — a character has
// one equipped item per equipment slot.
export const playCampaignEquipment = {
  get(campaignId, characterId, slot) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?'
      )
      .get(campaignId, characterId, slot);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, characterId, slot, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_equipment (campaign_id, character_id, slot, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, characterId, slot, JSON.stringify(record));
  },
  listByCharacter(campaignId, characterId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_equipment WHERE campaign_id = ? AND character_id = ? ORDER BY slot'
      )
      .all(campaignId, characterId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// One row per character; holds the character's current gold balance.
export const playCampaignCurrency = {
  get(campaignId, characterId) {
    const row = db
      .prepare('SELECT data FROM play_campaign_currency WHERE campaign_id = ? AND character_id = ?')
      .get(campaignId, characterId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, characterId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_currency (campaign_id, character_id, data) VALUES (?, ?, ?)'
    ).run(campaignId, characterId, JSON.stringify(record));
  },
};

// Append-only per-campaign transfer ledger, ordered by a deterministic
// campaign-local transfer id assigned by the caller (see routes/play.js's
// currency transfer endpoint).
export const playCampaignTransfers = {
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_transfers WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_transfers (campaign_id, transfer_id, data) VALUES (?, ?, ?)'
    ).run(campaignId, record.transfer_id, JSON.stringify(record));
  },
};

// Append-only per-campaign ledger for the transactional currency transfer
// endpoint. Only successful transfers are ever inserted here (a simulated
// failure returns 500 before any row is written), ordered by a
// campaign-local sequence assigned by the caller.
export const playCampaignTransactionalTransfers = {
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_transactional_transfers WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, data) VALUES (?, ?, ?)'
    ).run(campaignId, record.sequence, JSON.stringify(record));
  },
  listByCampaign(campaignId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence'
      )
      .all(campaignId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// One row per loot record; the record itself is immutable except for the
// status/recipient/votes fields set once by the assign endpoint.
export const playCampaignLoot = {
  has: (campaignId, lootId) => hasScoped('play_campaign_loot', 'loot_id', campaignId, lootId),
  get: (campaignId, lootId) => getScoped('play_campaign_loot', 'loot_id', campaignId, lootId),
  set: (campaignId, lootId, record) => setScoped('play_campaign_loot', 'loot_id', campaignId, lootId, record),
};

// Composite-keyed on (campaign_id, loot_id, voter) — one immutable vote per
// player identity per loot record.
export const playCampaignLootVotes = {
  get(campaignId, lootId, voter) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?'
      )
      .get(campaignId, lootId, voter);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, lootId, voter, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_loot_votes (campaign_id, loot_id, voter, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, lootId, voter, JSON.stringify(record));
  },
  listByLoot(campaignId, lootId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? ORDER BY rowid'
      )
      .all(campaignId, lootId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

// One row per campaign NPC; the DM-only agenda field lives alongside the
// player-visible fields and is filtered out at the route layer for players.
export const playCampaignNpcs = {
  has: (campaignId, npcId) => hasScoped('play_campaign_npcs', 'npc_id', campaignId, npcId),
  get: (campaignId, npcId) => getScoped('play_campaign_npcs', 'npc_id', campaignId, npcId),
  set: (campaignId, npcId, record) => setScoped('play_campaign_npcs', 'npc_id', campaignId, npcId, record),
};

export const playCampaignNpcDialogue = {
  has(campaignId, npcId, dialogueId) {
    const row = db
      .prepare(
        'SELECT 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?'
      )
      .get(campaignId, npcId, dialogueId);
    return !!row;
  },
  set(campaignId, npcId, dialogueId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, npcId, dialogueId, JSON.stringify(record));
  },
  listByNpc(campaignId, npcId) {
    const rows = db
      .prepare(
        'SELECT data FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY rowid'
      )
      .all(campaignId, npcId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

export const playCampaignRelationships = {
  has(campaignId, sourceId, targetId, kind) {
    const row = db
      .prepare(
        'SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?'
      )
      .get(campaignId, sourceId, targetId, kind);
    return !!row;
  },
  get(campaignId, sourceId, targetId, kind) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?'
      )
      .get(campaignId, sourceId, targetId, kind);
    return row ? JSON.parse(row.data) : null;
  },
  set(campaignId, sourceId, targetId, kind, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, data) VALUES (?, ?, ?, ?, ?)'
    ).run(campaignId, sourceId, targetId, kind, JSON.stringify(record));
  },
  listByCampaign(campaignId) {
    const rows = db
      .prepare('SELECT data FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY rowid')
      .all(campaignId);
    return rows.map((row) => JSON.parse(row.data));
  },
};

export const playCampaignClues = {
  has: (campaignId, clueId) => hasScoped('play_campaign_clues', 'clue_id', campaignId, clueId),
  get: (campaignId, clueId) => getScoped('play_campaign_clues', 'clue_id', campaignId, clueId),
  set: (campaignId, clueId, record) => setScoped('play_campaign_clues', 'clue_id', campaignId, clueId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_clues', campaignId),
};

export const playCampaignQuests = {
  has: (campaignId, questId) => hasScoped('play_campaign_quests', 'quest_id', campaignId, questId),
  get: (campaignId, questId) => getScoped('play_campaign_quests', 'quest_id', campaignId, questId),
  set: (campaignId, questId, record) => setScoped('play_campaign_quests', 'quest_id', campaignId, questId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_quests', campaignId),
};

// Cumulative quest reward grants per character, accumulated as quest
// rewards are awarded. Independent of any per-quest reward configuration.
export const playCampaignCharacterRewards = {
  get(campaignId, characterId) {
    const row = db
      .prepare('SELECT data FROM play_campaign_character_rewards WHERE campaign_id = ? AND character_id = ?')
      .get(campaignId, characterId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, characterId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_character_rewards (campaign_id, character_id, data) VALUES (?, ?, ?)'
    ).run(campaignId, characterId, JSON.stringify(record));
  },
};

export const playCampaignWorldEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_world_events', 'event_id', campaignId, eventId),
  get: (campaignId, eventId) => getScoped('play_campaign_world_events', 'event_id', campaignId, eventId),
  set: (campaignId, eventId, record) =>
    setScoped('play_campaign_world_events', 'event_id', campaignId, eventId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_world_events', campaignId),
};

export const playCampaignCalendar = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_calendar WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_calendar (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

export const playCampaignSettlements = {
  has: (campaignId, settlementId) =>
    hasScoped('play_campaign_settlements', 'settlement_id', campaignId, settlementId),
  get: (campaignId, settlementId) =>
    getScoped('play_campaign_settlements', 'settlement_id', campaignId, settlementId),
  set: (campaignId, settlementId, record) =>
    setScoped('play_campaign_settlements', 'settlement_id', campaignId, settlementId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_settlements', campaignId),
};

// Composite-keyed on (campaign_id, settlement_id, shop_id) — shop ids are
// unique per settlement, not globally, so a shop must be looked up together
// with its containing settlement.
export const playCampaignShops = {
  get(campaignId, settlementId, shopId) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?'
      )
      .get(campaignId, settlementId, shopId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, settlementId, shopId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_shops (campaign_id, settlement_id, shop_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, settlementId, shopId, JSON.stringify(record));
  },
};

// Recipes are ordered by creation (rowid) so listings preserve the order in
// which the DM defined them.
export const playCampaignRecipes = {
  has: (campaignId, recipeId) => hasScoped('play_campaign_recipes', 'recipe_id', campaignId, recipeId),
  get: (campaignId, recipeId) => getScoped('play_campaign_recipes', 'recipe_id', campaignId, recipeId),
  set: (campaignId, recipeId, record) =>
    setScoped('play_campaign_recipes', 'recipe_id', campaignId, recipeId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_recipes', campaignId),
};

// Content records are ordered by creation (rowid) so listings preserve the
// order in which the DM authored them.
export const playCampaignContent = {
  has: (campaignId, contentId) => hasScoped('play_campaign_content', 'content_id', campaignId, contentId),
  get: (campaignId, contentId) => getScoped('play_campaign_content', 'content_id', campaignId, contentId),
  set: (campaignId, contentId, record) =>
    setScoped('play_campaign_content', 'content_id', campaignId, contentId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_content', campaignId),
};

export const playCampaignDowntimeActivities = {
  has: (campaignId, activityId) =>
    hasScoped('play_campaign_downtime_activities', 'activity_id', campaignId, activityId),
  get: (campaignId, activityId) =>
    getScoped('play_campaign_downtime_activities', 'activity_id', campaignId, activityId),
  set: (campaignId, activityId, record) =>
    setScoped('play_campaign_downtime_activities', 'activity_id', campaignId, activityId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_downtime_activities', campaignId),
};

// Composite-keyed on (campaign_id, character_id, activity_id) — a character
// can hold several recurring downtime allocations, so this doesn't fit the
// single-id scoped helpers.
export const playCampaignDowntimeAllocations = {
  get(campaignId, characterId, activityId) {
    const row = db
      .prepare(
        'SELECT data FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?'
      )
      .get(campaignId, characterId, activityId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, characterId, activityId, record) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, characterId, activityId, JSON.stringify(record));
  },
};

export const playCampaignFactions = {
  has: (campaignId, factionId) => hasScoped('play_campaign_factions', 'faction_id', campaignId, factionId),
  get: (campaignId, factionId) => getScoped('play_campaign_factions', 'faction_id', campaignId, factionId),
  set: (campaignId, factionId, record) =>
    setScoped('play_campaign_factions', 'faction_id', campaignId, factionId, record),
};

// Current reputation totals are a separate table from the history ledger:
// each accepted change updates the bounded running total here and appends an
// immutable row to the history ledger below.
export const playCampaignReputation = {
  getTotal(campaignId, factionId, characterId) {
    const row = db
      .prepare(
        'SELECT reputation FROM play_campaign_reputation_totals WHERE campaign_id = ? AND faction_id = ? AND character_id = ?'
      )
      .get(campaignId, factionId, characterId);
    return row ? row.reputation : 0;
  },
  setTotal(campaignId, factionId, characterId, reputation) {
    db.prepare(
      'INSERT OR REPLACE INTO play_campaign_reputation_totals (campaign_id, faction_id, character_id, reputation) VALUES (?, ?, ?, ?)'
    ).run(campaignId, factionId, characterId, reputation);
  },
  addHistory(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_reputation_history (campaign_id, faction_id, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(campaignId, record.faction_id, record.character_id, record.reputation, record.delta, record.reason);
  },
  listByFaction(campaignId, factionId) {
    return db
      .prepare(
        'SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY rowid'
      )
      .all(campaignId, factionId);
  },
};

export const campaignNpcs = {
  has: (campaignId, id) => hasScoped('campaign_npcs', 'id', campaignId, id),
  get: (campaignId, id) => getScoped('campaign_npcs', 'id', campaignId, id),
  set: (campaignId, id, record) => setScoped('campaign_npcs', 'id', campaignId, id, record),
  listByCampaign: (campaignId) => listScoped('campaign_npcs', campaignId),
};

// Notes are ordered by creation (rowid) so listings preserve authoring order.
export const playCampaignNotes = {
  has: (campaignId, noteId) => hasScoped('play_campaign_notes', 'note_id', campaignId, noteId),
  get: (campaignId, noteId) => getScoped('play_campaign_notes', 'note_id', campaignId, noteId),
  set: (campaignId, noteId, record) => setScoped('play_campaign_notes', 'note_id', campaignId, noteId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_notes', campaignId),
};

// Whispers are ordered by creation (rowid) so listings preserve send order.
export const playCampaignWhispers = {
  has: (campaignId, whisperId) => hasScoped('play_campaign_whispers', 'whisper_id', campaignId, whisperId),
  get: (campaignId, whisperId) => getScoped('play_campaign_whispers', 'whisper_id', campaignId, whisperId),
  set: (campaignId, whisperId, record) =>
    setScoped('play_campaign_whispers', 'whisper_id', campaignId, whisperId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_whispers', campaignId),
};

// Messages (party chat) are ordered by creation (rowid) so listings preserve send order.
export const playCampaignMessages = {
  has: (campaignId, messageId) => hasScoped('play_campaign_messages', 'message_id', campaignId, messageId),
  get: (campaignId, messageId) => getScoped('play_campaign_messages', 'message_id', campaignId, messageId),
  set: (campaignId, messageId, record) =>
    setScoped('play_campaign_messages', 'message_id', campaignId, messageId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_messages', campaignId),
};

// Invitations are ordered by creation (rowid) so listings preserve send order.
export const playCampaignInvitations = {
  has: (campaignId, invitationId) => hasScoped('play_campaign_invitations', 'invitation_id', campaignId, invitationId),
  get: (campaignId, invitationId) => getScoped('play_campaign_invitations', 'invitation_id', campaignId, invitationId),
  set: (campaignId, invitationId, record) =>
    setScoped('play_campaign_invitations', 'invitation_id', campaignId, invitationId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_invitations', campaignId),
};

// Delegations are keyed by username so granting is idempotent per-user;
// history of grants/revokes lives in the separate audit ledger below.
export const playCampaignDelegations = {
  get: (campaignId, username) => getScoped('play_campaign_delegations', 'username', campaignId, username),
  set: (campaignId, username, record) =>
    setScoped('play_campaign_delegations', 'username', campaignId, username, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_delegations', campaignId),
};

export const playCampaignDelegationAudit = ledgerStore('play_campaign_delegation_audit', [
  'username',
  'action',
  'powers',
]);

// Audit events are keyed by correlation_id so duplicates are rejected
// per-campaign; listings preserve creation (timestamp) order via rowid.
export const playCampaignAuditEvents = {
  has: (campaignId, correlationId) => hasScoped('play_campaign_audit_events', 'correlation_id', campaignId, correlationId),
  get: (campaignId, correlationId) => getScoped('play_campaign_audit_events', 'correlation_id', campaignId, correlationId),
  set: (campaignId, correlationId, record) =>
    setScoped('play_campaign_audit_events', 'correlation_id', campaignId, correlationId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_audit_events', campaignId),
};

// Projection events are keyed by event_id so duplicates are rejected
// per-campaign; listings are ordered by the caller-assigned `sequence`.
export const playCampaignProjectionEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_projection_events', 'event_id', campaignId, eventId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_projection_events (campaign_id, event_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.event_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_projection_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_projection_events', campaignId, 'sequence'),
};

// Idempotent events are keyed by event_id so duplicates are rejected
// per-campaign; listings are ordered by the caller-assigned `sequence`.
export const playCampaignIdempotentEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_idempotent_events', 'event_id', campaignId, eventId),
  get: (campaignId, eventId) => getScoped('play_campaign_idempotent_events', 'event_id', campaignId, eventId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_idempotent_events (campaign_id, event_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.event_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_idempotent_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_idempotent_events', campaignId, 'sequence'),
};

// Feed events are keyed by event_id so duplicates are rejected per-campaign;
// listings are ordered by the caller-assigned `sequence`.
export const playCampaignFeedEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_feed_events', 'event_id', campaignId, eventId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_feed_events (campaign_id, event_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.event_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_feed_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_feed_events', campaignId, 'sequence'),
};

// Idempotency keys are keyed by the caller-supplied key so replays of the
// same key resolve to the exact same stored event.
export const playCampaignIdempotencyKeys = {
  get: (campaignId, key) => getScoped('play_campaign_idempotency_keys', 'idempotency_key', campaignId, key),
  set: (campaignId, key, record) =>
    setScoped('play_campaign_idempotency_keys', 'idempotency_key', campaignId, key, record),
};

// Per-campaign safe-turn counter, defaulting to current_turn 1 when absent.
export const playCampaignSafeTurnState = {
  get: (campaignId) => getById('play_campaign_safe_turn_state', 'campaign_id', campaignId),
  set: (campaignId, record) => setById('play_campaign_safe_turn_state', 'campaign_id', campaignId, record),
};

// Accepted safe-turn submissions, keyed by submission_id so duplicates are
// rejected per-campaign; listings preserve acceptance order via rowid.
export const playCampaignSafeTurns = {
  has: (campaignId, submissionId) => hasScoped('play_campaign_safe_turns', 'submission_id', campaignId, submissionId),
  set: (campaignId, submissionId, record) =>
    setScoped('play_campaign_safe_turns', 'submission_id', campaignId, submissionId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_safe_turns', campaignId),
};

// Immutable per-campaign export snapshots, keyed by version; listings are
// ordered by ascending version.
export const playCampaignExports = {
  get: (campaignId, version) => getScoped('play_campaign_exports', 'version', campaignId, version),
  add(campaignId, record) {
    db.prepare('INSERT INTO play_campaign_exports (campaign_id, version, data) VALUES (?, ?, ?)').run(
      campaignId,
      record.version,
      JSON.stringify(record)
    );
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_exports WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_exports', campaignId, 'version'),
};

// Latest successfully imported snapshot per campaign, keyed by campaign_id.
export const playCampaignImports = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_imports WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_imports (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

// Latest successfully migrated schema state per campaign, keyed by campaign_id.
export const playCampaignMigrations = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_migrations WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_migrations (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

export const playCampaignSessionZero = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_session_zero WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_session_zero (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

export const playCampaignSearchRecords = {
  has: (campaignId, recordId) => hasScoped('play_campaign_search_records', 'record_id', campaignId, recordId),
  set: (campaignId, recordId, record) =>
    setScoped('play_campaign_search_records', 'record_id', campaignId, recordId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_search_records', campaignId),
};

export const playCampaignRateEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_rate_events', 'event_id', campaignId, eventId),
  set: (campaignId, eventId, record) =>
    setScoped('play_campaign_rate_events', 'event_id', campaignId, eventId, record),
  listByCampaign: (campaignId) => listScoped('play_campaign_rate_events', campaignId),
};

// Immutable per-campaign backup snapshots, keyed by backup_id; listings are
// ordered by creation sequence.
export const playCampaignBackups = {
  get: (campaignId, backupId) => getScoped('play_campaign_backups', 'backup_id', campaignId, backupId),
  add(campaignId, record) {
    db.prepare('INSERT INTO play_campaign_backups (campaign_id, backup_id, data) VALUES (?, ?, ?)').run(
      campaignId,
      record.backup_id,
      JSON.stringify(record)
    );
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_backups WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_backups', campaignId, 'rowid'),
};

// Replay events are keyed by event_id so duplicates are rejected
// per-campaign; listings are ordered by the caller-assigned `sequence`.
export const playCampaignReplayEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_replay_events', 'event_id', campaignId, eventId),
  get: (campaignId, eventId) => getScoped('play_campaign_replay_events', 'event_id', campaignId, eventId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_replay_events (campaign_id, event_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.event_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_replay_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_replay_events', campaignId, 'sequence'),
};

// One RNG seed per campaign; configuring a seed twice is rejected by the
// route layer, not this store.
export const playCampaignRngConfig = {
  get(campaignId) {
    const row = db.prepare('SELECT seed FROM play_campaign_rng_config WHERE campaign_id = ?').get(campaignId);
    return row ? row.seed : undefined;
  },
  set(campaignId, seed) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_rng_config (campaign_id, seed) VALUES (?, ?)').run(
      campaignId,
      seed
    );
  },
};

// RNG roll ledger entries are keyed by roll_id so duplicates are rejected
// per-campaign; listings are ordered by the caller-assigned `sequence`.
export const playCampaignRngRolls = {
  has: (campaignId, rollId) => hasScoped('play_campaign_rng_rolls', 'roll_id', campaignId, rollId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.roll_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_rng_rolls WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_rng_rolls', campaignId, 'sequence'),
};

// Moderation reports are keyed by report_id so duplicates are rejected
// per-campaign; listings preserve append order via rowid, and `set` updates
// preserve that rowid so the one allowed open->resolved transition doesn't
// reorder the list.
export const playCampaignModerationReports = {
  has: (campaignId, reportId) => hasScoped('play_campaign_moderation_reports', 'report_id', campaignId, reportId),
  get: (campaignId, reportId) => getScoped('play_campaign_moderation_reports', 'report_id', campaignId, reportId),
  set: (campaignId, reportId, record) =>
    setScoped('play_campaign_moderation_reports', 'report_id', campaignId, reportId, record),
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_moderation_reports WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_moderation_reports', campaignId),
};

// One safety boundary set per campaign; replacement is a full overwrite.
export const playCampaignSafetyBoundaries = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_safety_boundaries WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_safety_boundaries (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

// Safety events are keyed by event_id so duplicates are rejected
// per-campaign; listings are ordered by the caller-assigned `sequence`.
export const playCampaignSafetyEvents = {
  has: (campaignId, eventId) => hasScoped('play_campaign_safety_events', 'event_id', campaignId, eventId),
  add(campaignId, record) {
    db.prepare(
      'INSERT INTO play_campaign_safety_events (campaign_id, event_id, sequence, data) VALUES (?, ?, ?, ?)'
    ).run(campaignId, record.event_id, record.sequence, JSON.stringify(record));
  },
  countByCampaign(campaignId) {
    const row = db
      .prepare('SELECT COUNT(*) AS count FROM play_campaign_safety_events WHERE campaign_id = ?')
      .get(campaignId);
    return row ? row.count : 0;
  },
  listByCampaign: (campaignId) => listScoped('play_campaign_safety_events', campaignId, 'sequence'),
};

// One fixture seed record per campaign; seeding is idempotent, so `set` is a
// full overwrite of the same canonical state.
export const playCampaignFixtureSeeds = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_fixture_seeds WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_fixture_seeds (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};

export const playSpectatorTickets = keyedStore('play_spectator_tickets', 'spectator_id');

export const playCampaignMetrics = {
  get(campaignId) {
    const row = db.prepare('SELECT data FROM play_campaign_metrics WHERE campaign_id = ?').get(campaignId);
    return row ? JSON.parse(row.data) : undefined;
  },
  set(campaignId, record) {
    db.prepare('INSERT OR REPLACE INTO play_campaign_metrics (campaign_id, data) VALUES (?, ?)').run(
      campaignId,
      JSON.stringify(record)
    );
  },
};
