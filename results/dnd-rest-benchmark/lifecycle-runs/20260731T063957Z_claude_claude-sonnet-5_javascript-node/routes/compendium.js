import { sendJson, parseJsonBody } from '../lib/http.js';
import { monsters, items } from '../lib/stores.js';

const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function registerCompendiumRoutes(router) {
  router.post('/v1/compendium/monsters', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const slug = body.data && body.data.slug;
    const name = body.data && body.data.name;
    const cr = body.data && body.data.cr;
    const armorClass = body.data && body.data.armor_class;
    const hitPoints = body.data && body.data.hit_points;
    const tags = body.data && body.data.tags;
    if (
      typeof slug !== 'string' ||
      !SLUG_RE.test(slug) ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof cr !== 'string' ||
      !Number.isInteger(armorClass) ||
      !Number.isInteger(hitPoints) ||
      (tags !== undefined && (!Array.isArray(tags) || !tags.every((t) => typeof t === 'string')))
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (monsters.has(slug)) {
      sendJson(res, 409, { error: 'monster already exists' });
      return;
    }
    const record = {
      slug,
      name,
      cr,
      armor_class: armorClass,
      hit_points: hitPoints,
      tags: tags || [],
    };
    monsters.set(slug, record);
    sendJson(res, 201, {
      slug: record.slug,
      name: record.name,
      cr: record.cr,
      armor_class: record.armor_class,
      hit_points: record.hit_points,
    });
  });

  router.get('/v1/compendium/monsters/:slug', (req, res, { slug }) => {
    const record = monsters.get(slug);
    if (!record) {
      sendJson(res, 404, { error: 'monster not found' });
      return;
    }
    sendJson(res, 200, record);
  });

  router.post('/v1/compendium/items', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const slug = body.data && body.data.slug;
    const name = body.data && body.data.name;
    const type = body.data && body.data.type;
    const rarity = body.data && body.data.rarity;
    const costGp = body.data && body.data.cost_gp;
    if (
      typeof slug !== 'string' ||
      !SLUG_RE.test(slug) ||
      typeof name !== 'string' ||
      name.length === 0 ||
      typeof type !== 'string' ||
      typeof rarity !== 'string' ||
      typeof costGp !== 'number'
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (items.has(slug)) {
      sendJson(res, 409, { error: 'item already exists' });
      return;
    }
    const record = {
      slug,
      name,
      type,
      rarity,
      cost_gp: costGp,
    };
    items.set(slug, record);
    sendJson(res, 201, record);
  });

  router.get('/v1/compendium/items/:slug', (req, res, { slug }) => {
    const record = items.get(slug);
    if (!record) {
      sendJson(res, 404, { error: 'item not found' });
      return;
    }
    sendJson(res, 200, record);
  });
}
