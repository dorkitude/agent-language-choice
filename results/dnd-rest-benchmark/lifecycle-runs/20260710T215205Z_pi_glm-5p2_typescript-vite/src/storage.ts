import { DatabaseSync } from 'node:sqlite'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

// ---------------------------------------------------------------------------
// SQLite-backed durable storage for game-world / game-state data.
//
// The database file (`game.db`) lives in the project root (one directory
// above this module). The schema is created on server startup and recreated
// by `resetStorage()`. All benchmark-created durable data (combat sessions,
// users) lives here so it survives process restarts and can be cleared on
// demand.
// ---------------------------------------------------------------------------

export const SCHEMA_VERSION = 1
export const STORAGE_DRIVER = 'sqlite'

const DB_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'game.db',
)

let db: DatabaseSync | null = null
let initialized = false

function getDb(): DatabaseSync {
  if (!db) {
    db = new DatabaseSync(DB_PATH)
  }
  return db
}

const TABLE_DDL: string[] = [
  `CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS combat_sessions (
    id TEXT PRIMARY KEY,
    round INTEGER NOT NULL,
    turn_index INTEGER NOT NULL,
    order_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    hash TEXT NOT NULL,
    salt TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS monsters (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cr TEXT NOT NULL,
    armor_class INTEGER NOT NULL,
    hit_points INTEGER NOT NULL,
    tags_json TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS items (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    rarity TEXT NOT NULL,
    cost_gp INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dm TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_characters (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    class TEXT NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS campaign_events (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL
  )`,
]

/** Create the schema if it does not already exist and stamp schema_version. */
export function initSchema(): void {
  const database = getDb()
  database.exec('BEGIN')
  try {
    for (const ddl of TABLE_DDL) database.exec(ddl)
    database
      .prepare('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)')
      .run('schema_version', String(SCHEMA_VERSION))
    database.exec('COMMIT')
    initialized = true
  } catch (err) {
    database.exec('ROLLBACK')
    throw err
  }
}

/** Idempotently ensure the schema is ready before handling any request. */
export function ensureSchema(): void {
  if (!initialized) initSchema()
}

// ---------------------------------------------------------------------------
// Combat sessions (durable game-state)
// ---------------------------------------------------------------------------

export interface OrderEntry {
  name: string
  score: number
}

export interface ConditionEntry {
  condition: string
  remaining_rounds: number
}

export interface StoredSession {
  id: string
  round: number
  turn_index: number
  order: OrderEntry[]
  conditions: Record<string, ConditionEntry[]>
}

interface SessionRow {
  id: string
  round: number
  turn_index: number
  order_json: string
  conditions_json: string
}

export function getSession(id: string): StoredSession | null {
  const row = getDb()
    .prepare(
      'SELECT id, round, turn_index, order_json, conditions_json ' +
        'FROM combat_sessions WHERE id = ?',
    )
    .get(id) as SessionRow | undefined
  if (!row) return null
  return {
    id: row.id,
    round: row.round,
    turn_index: row.turn_index,
    order: JSON.parse(row.order_json) as OrderEntry[],
    conditions: JSON.parse(row.conditions_json) as Record<
      string,
      ConditionEntry[]
    >,
  }
}

export function putSession(session: StoredSession): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO combat_sessions ' +
        '(id, round, turn_index, order_json, conditions_json) ' +
        'VALUES (?, ?, ?, ?, ?)',
    )
    .run(
      session.id,
      session.round,
      session.turn_index,
      JSON.stringify(session.order),
      JSON.stringify(session.conditions),
    )
}

// ---------------------------------------------------------------------------
// Users (durable auth data)
// ---------------------------------------------------------------------------

export interface StoredUser {
  username: string
  role: string
  hash: string
  salt: string
}

interface UserRow {
  username: string
  role: string
  hash: string
  salt: string
}

export function getUser(username: string): StoredUser | null {
  const row = getDb()
    .prepare('SELECT username, role, hash, salt FROM users WHERE username = ?')
    .get(username) as UserRow | undefined
  if (!row) return null
  return {
    username: row.username,
    role: row.role,
    hash: row.hash,
    salt: row.salt,
  }
}

export function putUser(user: StoredUser): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO users (username, role, hash, salt) ' +
        'VALUES (?, ?, ?, ?)',
    )
    .run(user.username, user.role, user.hash, user.salt)
}

// ---------------------------------------------------------------------------
// Compendium: monsters & items (durable game-world data)
// ---------------------------------------------------------------------------

export interface StoredMonster {
  slug: string
  name: string
  cr: string
  armor_class: number
  hit_points: number
  tags: string[]
}

export interface StoredItem {
  slug: string
  name: string
  type: string
  rarity: string
  cost_gp: number
}

interface MonsterRow {
  slug: string
  name: string
  cr: string
  armor_class: number
  hit_points: number
  tags_json: string
}

interface ItemRow {
  slug: string
  name: string
  type: string
  rarity: string
  cost_gp: number
}

export function getMonster(slug: string): StoredMonster | null {
  const row = getDb()
    .prepare(
      'SELECT slug, name, cr, armor_class, hit_points, tags_json ' +
        'FROM monsters WHERE slug = ?',
    )
    .get(slug) as MonsterRow | undefined
  if (!row) return null
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: JSON.parse(row.tags_json) as string[],
  }
}

export function putMonster(monster: StoredMonster): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO monsters ' +
        '(slug, name, cr, armor_class, hit_points, tags_json) ' +
        'VALUES (?, ?, ?, ?, ?, ?)',
    )
    .run(
      monster.slug,
      monster.name,
      monster.cr,
      monster.armor_class,
      monster.hit_points,
      JSON.stringify(monster.tags),
    )
}

export function getItem(slug: string): StoredItem | null {
  const row = getDb()
    .prepare(
      'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?',
    )
    .get(slug) as ItemRow | undefined
  if (!row) return null
  return {
    slug: row.slug,
    name: row.name,
    type: row.type,
    rarity: row.rarity,
    cost_gp: row.cost_gp,
  }
}

export function putItem(item: StoredItem): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO items (slug, name, type, rarity, cost_gp) ' +
        'VALUES (?, ?, ?, ?, ?)',
    )
    .run(item.slug, item.name, item.type, item.rarity, item.cost_gp)
}

// ---------------------------------------------------------------------------
// Campaign state (durable game-state: campaigns, characters, log events)
// ---------------------------------------------------------------------------

export interface StoredCampaign {
  id: string
  name: string
  dm: string
}

export interface StoredCharacter {
  id: string
  campaign_id: string
  name: string
  level: number
  class: string
}

export interface StoredEvent {
  id: string
  campaign_id: string
  kind: string
  summary: string
}

interface CampaignRow {
  id: string
  name: string
  dm: string
}

interface CharacterRow {
  id: string
  campaign_id: string
  name: string
  level: number
  class: string
}

interface EventRow {
  id: string
  campaign_id: string
  kind: string
  summary: string
}

export function getCampaign(id: string): StoredCampaign | null {
  const row = getDb()
    .prepare('SELECT id, name, dm FROM campaigns WHERE id = ?')
    .get(id) as CampaignRow | undefined
  if (!row) return null
  return { id: row.id, name: row.name, dm: row.dm }
}

export function putCampaign(campaign: StoredCampaign): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
    )
    .run(campaign.id, campaign.name, campaign.dm)
}

export function getCharacter(id: string): StoredCharacter | null {
  const row = getDb()
    .prepare(
      'SELECT id, campaign_id, name, level, class FROM campaign_characters ' +
        'WHERE id = ?',
    )
    .get(id) as CharacterRow | undefined
  if (!row) return null
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    name: row.name,
    level: row.level,
    class: row.class,
  }
}

export function putCharacter(character: StoredCharacter): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO campaign_characters ' +
        '(id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
    )
    .run(
      character.id,
      character.campaign_id,
      character.name,
      character.level,
      character.class,
    )
}

export function listCharacters(campaignId: string): StoredCharacter[] {
  const rows = getDb()
    .prepare(
      'SELECT id, campaign_id, name, level, class FROM campaign_characters ' +
        'WHERE campaign_id = ? ORDER BY rowid',
    )
    .all(campaignId) as unknown as CharacterRow[]
  return rows.map((r) => ({
    id: r.id,
    campaign_id: r.campaign_id,
    name: r.name,
    level: r.level,
    class: r.class,
  }))
}

export function getEvent(id: string): StoredEvent | null {
  const row = getDb()
    .prepare(
      'SELECT id, campaign_id, kind, summary FROM campaign_events ' +
        'WHERE id = ?',
    )
    .get(id) as EventRow | undefined
  if (!row) return null
  return {
    id: row.id,
    campaign_id: row.campaign_id,
    kind: row.kind,
    summary: row.summary,
  }
}

export function putEvent(event: StoredEvent): void {
  getDb()
    .prepare(
      'INSERT OR REPLACE INTO campaign_events ' +
        '(id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
    )
    .run(event.id, event.campaign_id, event.kind, event.summary)
}

export function countEvents(campaignId: string): number {
  const row = getDb()
    .prepare(
      'SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id = ?',
    )
    .get(campaignId) as { n: number } | undefined
  return row ? row.n : 0
}

export function listEvents(campaignId: string): StoredEvent[] {
  const rows = getDb()
    .prepare(
      'SELECT id, campaign_id, kind, summary FROM campaign_events ' +
        'WHERE campaign_id = ? ORDER BY rowid',
    )
    .all(campaignId) as unknown as EventRow[]
  return rows.map((r) => ({
    id: r.id,
    campaign_id: r.campaign_id,
    kind: r.kind,
    summary: r.summary,
  }))
}

// ---------------------------------------------------------------------------
// Storage status / reset
// ---------------------------------------------------------------------------

export function storageStatus(): {
  driver: string
  schema_version: number
  initialized: boolean
} {
  return {
    driver: STORAGE_DRIVER,
    schema_version: SCHEMA_VERSION,
    initialized,
  }
}

/** Drop and recreate every benchmark-created table; preserve process health. */
export function resetStorage(): void {
  const database = getDb()
  database.exec('BEGIN')
  try {
    database.exec('DROP TABLE IF EXISTS campaign_events')
    database.exec('DROP TABLE IF EXISTS campaign_characters')
    database.exec('DROP TABLE IF EXISTS campaigns')
    database.exec('DROP TABLE IF EXISTS combat_sessions')
    database.exec('DROP TABLE IF EXISTS users')
    database.exec('DROP TABLE IF EXISTS monsters')
    database.exec('DROP TABLE IF EXISTS items')
    database.exec('DROP TABLE IF EXISTS meta')
    database.exec('COMMIT')
  } catch (err) {
    database.exec('ROLLBACK')
    throw err
  }
  initSchema()
}
