import { db } from "../storage/db.js";

export type Monster = {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

export type Item = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function isValidSlug(value: unknown): value is string {
  return typeof value === "string" && SLUG_PATTERN.test(value);
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function isTags(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function parseMonsterRow(row: Record<string, unknown>, tags: string[]): Monster | undefined {
  if (
    typeof row.slug !== "string" ||
    typeof row.name !== "string" ||
    typeof row.cr !== "string" ||
    typeof row.armor_class !== "number" ||
    typeof row.hit_points !== "number"
  ) {
    return undefined;
  }

  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags,
  };
}

function parseItemRow(row: Record<string, unknown>): Item | undefined {
  if (
    typeof row.slug !== "string" ||
    typeof row.name !== "string" ||
    typeof row.type !== "string" ||
    typeof row.rarity !== "string" ||
    typeof row.cost_gp !== "number"
  ) {
    return undefined;
  }

  return {
    slug: row.slug,
    name: row.name,
    type: row.type,
    rarity: row.rarity,
    cost_gp: row.cost_gp,
  };
}

export const monsters = {
  get(slug: string): Monster | undefined {
    const row = db()
      .prepare("SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?")
      .get(slug);

    if (row === undefined) {
      return undefined;
    }

    const tags = db()
      .prepare("SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY position ASC")
      .all(slug)
      .map((tagRow: Record<string, unknown>) => tagRow.tag)
      .filter((tag: unknown): tag is string => typeof tag === "string");

    return parseMonsterRow(row, tags);
  },

  has(slug: string): boolean {
    return this.get(slug) !== undefined;
  },

  create(monster: Monster): void {
    const connection = db();
    connection.exec("BEGIN");
    try {
      connection
        .prepare("INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)")
        .run(monster.slug, monster.name, monster.cr, monster.armor_class, monster.hit_points);

      const insertTag = connection.prepare(
        "INSERT INTO monster_tags (monster_slug, position, tag) VALUES (?, ?, ?)",
      );
      monster.tags.forEach((tag, index) => insertTag.run(monster.slug, index, tag));

      connection.exec("COMMIT");
    } catch (error) {
      connection.exec("ROLLBACK");
      throw error;
    }
  },
};

export const items = {
  get(slug: string): Item | undefined {
    const row = db()
      .prepare("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?")
      .get(slug);

    return row === undefined ? undefined : parseItemRow(row);
  },

  has(slug: string): boolean {
    return this.get(slug) !== undefined;
  },

  create(item: Item): void {
    db()
      .prepare("INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)")
      .run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
  },
};

export function monsterCreateResponse(monster: Monster) {
  return {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
  };
}
