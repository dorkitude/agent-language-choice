import http from 'node:http';

type HandlerResult = { status: number; data: unknown };

const XP_BY_CR: Record<string, number> = {
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

type Thresholds = { easy: number; medium: number; hard: number; deadly: number };

const THRESHOLDS_BY_LEVEL: Record<number, Thresholds> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function multiplierForCount(n: number): number {
  if (n <= 1) return 1;
  if (n === 2) return 1.5;
  if (n <= 6) return 2;
  if (n <= 10) return 2.5;
  if (n <= 14) return 3;
  return 4;
}

function diceStats(body: any): HandlerResult {
  if (typeof body?.expression !== 'string') {
    return { status: 400, data: { error: 'invalid request' } };
  }
  const expr = body.expression.trim();
  const m = expr.match(/^(\d+)d(\d+)([+-]\d+)?$/);
  if (!m) {
    return { status: 400, data: { error: 'invalid expression' } };
  }
  const count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  if (count <= 0 || sides <= 0) {
    return { status: 400, data: { error: 'count and sides must be positive' } };
  }
  let modifier = 0;
  if (m[3]) {
    modifier = parseInt(m[3], 10);
  }
  const min = count + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  return {
    status: 200,
    data: { dice_count: count, sides, modifier, min, max, average },
  };
}

function abilityCheck(body: any): HandlerResult {
  const roll = Number(body?.roll);
  const modifier = Number(body?.modifier);
  const dc = Number(body?.dc);
  if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
    return { status: 400, data: { error: 'invalid request' } };
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  return { status: 200, data: { total, success, margin } };
}

function adjustedXp(body: any): HandlerResult {
  if (!body || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return { status: 400, data: { error: 'invalid request' } };
  }
  let baseXp = 0;
  let monsterCount = 0;
  for (const m of body.monsters) {
    const cr = String(m?.cr);
    const xp = XP_BY_CR[cr];
    if (xp === undefined) {
      return { status: 400, data: { error: `unknown cr: ${cr}` } };
    }
    const count = Number(m?.count);
    if (!Number.isFinite(count)) {
      return { status: 400, data: { error: 'invalid count' } };
    }
    baseXp += xp * count;
    monsterCount += count;
  }
  const multiplier = multiplierForCount(monsterCount);
  const adjusted = baseXp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;
  for (const p of body.party) {
    const level = Number(p?.level);
    if (!Number.isFinite(level)) {
      return { status: 400, data: { error: 'invalid level' } };
    }
    const t = THRESHOLDS_BY_LEVEL[level];
    if (t) {
      easy += t.easy;
      medium += t.medium;
      hard += t.hard;
      deadly += t.deadly;
    }
  }

  let difficulty: string;
  if (adjusted >= deadly) difficulty = 'deadly';
  else if (adjusted >= hard) difficulty = 'hard';
  else if (adjusted >= medium) difficulty = 'medium';
  else if (adjusted >= easy) difficulty = 'easy';
  else difficulty = 'trivial';

  return {
    status: 200,
    data: {
      base_xp: baseXp,
      monster_count: monsterCount,
      multiplier,
      adjusted_xp: adjusted,
      difficulty,
      thresholds: { easy, medium, hard, deadly },
    },
  };
}

function initiativeOrder(body: any): HandlerResult {
  if (!body || !Array.isArray(body.combatants)) {
    return { status: 400, data: { error: 'invalid request' } };
  }
  const list: { name: string; dex: number; roll: number; score: number }[] = [];
  for (const c of body.combatants) {
    const name = String(c?.name ?? '');
    const dex = Number(c?.dex ?? 0);
    const roll = Number(c?.roll ?? 0);
    if (!Number.isFinite(dex) || !Number.isFinite(roll)) {
      return { status: 400, data: { error: 'invalid combatant' } };
    }
    list.push({ name, dex, roll, score: roll + dex });
  }
  list.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    if (a.name < b.name) return -1;
    if (a.name > b.name) return 1;
    return 0;
  });
  return {
    status: 200,
    data: { order: list.map((c) => ({ name: c.name, score: c.score })) },
  };
}

function sendJson(res: http.ServerResponse, status: number, data: unknown): void {
  const body = JSON.stringify(data);
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(body);
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

async function handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const url = new URL(req.url ?? '', 'http://127.0.0.1');
  const path = url.pathname;
  const method = req.method ?? 'GET';

  if (method === 'GET' && path === '/health') {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (method === 'POST') {
    const text = await readBody(req);
    let body: any;
    try {
      body = text.length === 0 ? {} : JSON.parse(text);
    } catch {
      sendJson(res, 400, { error: 'invalid json' });
      return;
    }
    let result: HandlerResult;
    switch (path) {
      case '/v1/dice/stats':
        result = diceStats(body);
        break;
      case '/v1/checks/ability':
        result = abilityCheck(body);
        break;
      case '/v1/encounters/adjusted-xp':
        result = adjustedXp(body);
        break;
      case '/v1/initiative/order':
        result = initiativeOrder(body);
        break;
      default:
        sendJson(res, 404, { error: 'not found' });
        return;
    }
    sendJson(res, result.status, result.data);
    return;
  }

  sendJson(res, 404, { error: 'not found' });
}

const port = Number(process.env.PORT) || 3000;
const host = '127.0.0.1';

const server = http.createServer((req, res) => {
  handle(req, res).catch(() => {
    sendJson(res, 500, { error: 'internal server error' });
  });
});

server.listen(port, host, () => {
  console.error(`dnd-rest listening on http://${host}:${port}`);
});
