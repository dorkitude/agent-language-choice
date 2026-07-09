import { createServer, IncomingMessage, ServerResponse } from "node:http";

const PORT = Number(process.env.PORT ?? 0);

function sendJSON(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function badRequest(res: ServerResponse): void {
  sendJSON(res, 400, { error: "bad request" });
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw.trim() === "") return {};
  return JSON.parse(raw);
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// --- POST /v1/dice/stats ---
const DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/;

function diceStats(body: unknown, res: ServerResponse): void {
  if (!isObject(body) || typeof body.expression !== "string") return badRequest(res);
  const m = DICE_RE.exec(body.expression.trim());
  if (!m) return badRequest(res);
  const count = Number.parseInt(m[1], 10);
  const sides = Number.parseInt(m[2], 10);
  const modifier = m[3] !== undefined ? Number.parseInt(m[3], 10) : 0;
  if (!Number.isInteger(count) || !Number.isInteger(sides)) return badRequest(res);
  if (count <= 0 || sides <= 0) return badRequest(res);
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  sendJSON(res, 200, { dice_count: count, sides, modifier, min, max, average });
}

// --- POST /v1/checks/ability ---
function abilityCheck(body: unknown, res: ServerResponse): void {
  if (!isObject(body)) return badRequest(res);
  const { roll, modifier, dc } = body;
  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") {
    return badRequest(res);
  }
  const total = roll + modifier;
  sendJSON(res, 200, { total, success: total >= dc, margin: total - dc });
}

// --- POST /v1/encounters/adjusted-xp ---
const CR_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

function countMultiplier(monsterCount: number): number {
  if (monsterCount <= 1) return 1;
  if (monsterCount === 2) return 1.5;
  if (monsterCount <= 6) return 2;
  if (monsterCount <= 10) return 2.5;
  if (monsterCount <= 14) return 3;
  return 4;
}

function adjustedXP(body: unknown, res: ServerResponse): void {
  if (!isObject(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return badRequest(res);
  }

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of body.party) {
    if (!isObject(member) || typeof member.level !== "number") return badRequest(res);
    const t = LEVEL_THRESHOLDS[member.level];
    if (!t) return badRequest(res);
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let baseXP = 0;
  let monsterCount = 0;
  for (const mon of body.monsters) {
    if (!isObject(mon) || typeof mon.cr !== "string" || typeof mon.count !== "number") {
      return badRequest(res);
    }
    if (!Number.isInteger(mon.count) || mon.count < 0) return badRequest(res);
    const xp = CR_XP[mon.cr];
    if (xp === undefined) return badRequest(res);
    baseXP += xp * mon.count;
    monsterCount += mon.count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjusted = baseXP * multiplier;

  let difficulty = "trivial";
  if (adjusted >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted >= thresholds.hard) difficulty = "hard";
  else if (adjusted >= thresholds.medium) difficulty = "medium";
  else if (adjusted >= thresholds.easy) difficulty = "easy";

  sendJSON(res, 200, {
    base_xp: baseXP,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjusted,
    difficulty,
    thresholds,
  });
}

// --- POST /v1/initiative/order ---
function initiativeOrder(body: unknown, res: ServerResponse): void {
  if (!isObject(body) || !Array.isArray(body.combatants)) return badRequest(res);
  const combatants: { name: string; dex: number; score: number }[] = [];
  for (const c of body.combatants) {
    if (!isObject(c) || typeof c.name !== "string" || typeof c.dex !== "number" || typeof c.roll !== "number") {
      return badRequest(res);
    }
    combatants.push({ name: c.name, dex: c.dex, score: c.roll + c.dex });
  }
  combatants.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  sendJSON(res, 200, { order: combatants.map((c) => ({ name: c.name, score: c.score })) });
}

const server = createServer(async (req, res) => {
  try {
    const method = req.method ?? "GET";
    const url = (req.url ?? "").split("?")[0];

    if (method === "GET" && url === "/health") {
      return sendJSON(res, 200, { ok: true });
    }

    if (method === "POST") {
      let body: unknown;
      try {
        body = await readBody(req);
      } catch {
        return badRequest(res);
      }
      switch (url) {
        case "/v1/dice/stats":
          return diceStats(body, res);
        case "/v1/checks/ability":
          return abilityCheck(body, res);
        case "/v1/encounters/adjusted-xp":
          return adjustedXP(body, res);
        case "/v1/initiative/order":
          return initiativeOrder(body, res);
      }
    }

    sendJSON(res, 404, { error: "not found" });
  } catch {
    if (!res.headersSent) sendJSON(res, 500, { error: "internal error" });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  const addr = server.address();
  const port = typeof addr === "object" && addr ? addr.port : PORT;
  console.log(`listening on 127.0.0.1:${port}`);
});
