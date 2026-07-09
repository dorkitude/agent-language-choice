import { createServer, IncomingMessage, ServerResponse } from "node:http";

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

function countMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function sendJson(res: ServerResponse, status: number, body: unknown) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => (data += chunk));
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function parseDiceExpression(expression: unknown): { count: number; sides: number; modifier: number } | null {
  if (typeof expression !== "string") return null;
  const match = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression.trim());
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  let modifier = 0;
  if (match[3] && match[4]) {
    modifier = parseInt(match[4], 10) * (match[3] === "-" ? -1 : 1);
  }
  if (count <= 0 || sides <= 0) return null;
  return { count, sides, modifier };
}

async function handleDiceStats(req: IncomingMessage, res: ServerResponse) {
  const body = await readBody(req);
  let parsed: any;
  try {
    parsed = JSON.parse(body);
  } catch {
    sendJson(res, 400, { error: "invalid json" });
    return;
  }
  const dice = parseDiceExpression(parsed?.expression);
  if (!dice) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }
  const { count, sides, modifier } = dice;
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;
  sendJson(res, 200, {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

async function handleAbilityCheck(req: IncomingMessage, res: ServerResponse) {
  const body = await readBody(req);
  let parsed: any;
  try {
    parsed = JSON.parse(body);
  } catch {
    sendJson(res, 400, { error: "invalid json" });
    return;
  }
  const { roll, modifier, dc } = parsed ?? {};
  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJson(res, 200, { total, success, margin });
}

async function handleAdjustedXp(req: IncomingMessage, res: ServerResponse) {
  const body = await readBody(req);
  let parsed: any;
  try {
    parsed = JSON.parse(body);
  } catch {
    sendJson(res, 400, { error: "invalid json" });
    return;
  }
  const party = parsed?.party;
  const monsters = parsed?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const m of monsters) {
    const cr = String(m?.cr);
    const count = Number(m?.count);
    const xp = CR_XP[cr];
    if (xp === undefined || !Number.isFinite(count)) {
      sendJson(res, 400, { error: "unsupported cr" });
      return;
    }
    baseXp += xp * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easy = 0;
  let medium = 0;
  let hard = 0;
  let deadly = 0;
  for (const p of party) {
    const level = Number(p?.level);
    const thresholds = LEVEL_THRESHOLDS[level];
    if (!thresholds) {
      sendJson(res, 400, { error: "unsupported level" });
      return;
    }
    easy += thresholds.easy;
    medium += thresholds.medium;
    hard += thresholds.hard;
    deadly += thresholds.deadly;
  }

  let difficulty = "trivial";
  if (adjustedXp >= deadly) difficulty = "deadly";
  else if (adjustedXp >= hard) difficulty = "hard";
  else if (adjustedXp >= medium) difficulty = "medium";
  else if (adjustedXp >= easy) difficulty = "easy";

  sendJson(res, 200, {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: { easy, medium, hard, deadly },
  });
}

async function handleInitiativeOrder(req: IncomingMessage, res: ServerResponse) {
  const body = await readBody(req);
  let parsed: any;
  try {
    parsed = JSON.parse(body);
  } catch {
    sendJson(res, 400, { error: "invalid json" });
    return;
  }
  const combatants = parsed?.combatants;
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const scored = combatants.map((c: any) => ({
    name: String(c?.name),
    dex: Number(c?.dex),
    score: Number(c?.roll) + Number(c?.dex),
  }));

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  sendJson(res, 200, {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}

const server = createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && req.url === "/v1/dice/stats") {
      await handleDiceStats(req, res);
      return;
    }
    if (req.method === "POST" && req.url === "/v1/checks/ability") {
      await handleAbilityCheck(req, res);
      return;
    }
    if (req.method === "POST" && req.url === "/v1/encounters/adjusted-xp") {
      await handleAdjustedXp(req, res);
      return;
    }
    if (req.method === "POST" && req.url === "/v1/initiative/order") {
      await handleInitiativeOrder(req, res);
      return;
    }
    sendJson(res, 404, { error: "not found" });
  } catch {
    sendJson(res, 400, { error: "bad request" });
  }
});

const port = parseInt(process.env.PORT ?? "3000", 10);
server.listen(port, "127.0.0.1", () => {
  console.log(`listening on 127.0.0.1:${port}`);
});
