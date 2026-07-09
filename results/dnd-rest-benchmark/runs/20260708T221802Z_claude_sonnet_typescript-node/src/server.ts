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

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw.length === 0) return {};
  return JSON.parse(raw);
}

function handleDiceStats(body: any, res: ServerResponse): void {
  const expression = body?.expression;
  if (typeof expression !== "string") {
    sendJson(res, 400, { error: "expression must be a string" });
    return;
  }
  const match = expression.match(/^(\d+)d(\d+)([+-]\d+)?$/);
  if (!match) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }
  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (diceCount <= 0 || sides <= 0) {
    sendJson(res, 400, { error: "count and sides must be positive" });
    return;
  }
  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (1 + sides)) / 2 + modifier;
  sendJson(res, 200, {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}

function handleAbilityCheck(body: any, res: ServerResponse): void {
  const roll = body?.roll;
  const modifier = body?.modifier;
  const dc = body?.dc;
  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") {
    sendJson(res, 400, { error: "roll, modifier, and dc must be numbers" });
    return;
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJson(res, 200, { total, success, margin });
}

function handleAdjustedXp(body: any, res: ServerResponse): void {
  const party = body?.party;
  const monsters = body?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: "party and monsters must be arrays" });
    return;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const cr = String(monster?.cr);
    const count = monster?.count;
    if (!(cr in CR_XP) || typeof count !== "number") {
      sendJson(res, 400, { error: "invalid monster entry" });
      return;
    }
    baseXp += CR_XP[cr] * count;
    monsterCount += count;
  }

  const multiplier = countMultiplier(monsterCount);
  const adjustedXp = baseXp * multiplier;

  let easySum = 0;
  let mediumSum = 0;
  let hardSum = 0;
  let deadlySum = 0;
  for (const member of party) {
    const level = member?.level;
    const thresholds = LEVEL_THRESHOLDS[level];
    if (!thresholds) {
      sendJson(res, 400, { error: `unsupported party level ${level}` });
      return;
    }
    easySum += thresholds.easy;
    mediumSum += thresholds.medium;
    hardSum += thresholds.hard;
    deadlySum += thresholds.deadly;
  }

  let difficulty = "trivial";
  if (adjustedXp >= deadlySum) difficulty = "deadly";
  else if (adjustedXp >= hardSum) difficulty = "hard";
  else if (adjustedXp >= mediumSum) difficulty = "medium";
  else if (adjustedXp >= easySum) difficulty = "easy";

  sendJson(res, 200, {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds: { easy: easySum, medium: mediumSum, hard: hardSum, deadly: deadlySum },
  });
}

function handleInitiativeOrder(body: any, res: ServerResponse): void {
  const combatants = body?.combatants;
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: "combatants must be an array" });
    return;
  }
  const scored = combatants.map((c: any) => ({
    name: c?.name,
    dex: c?.dex,
    score: (c?.roll ?? 0) + (c?.dex ?? 0),
  }));
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return String(a.name).localeCompare(String(b.name));
  });
  sendJson(res, 200, {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}

const server = createServer(async (req, res) => {
  try {
    const url = req.url ?? "/";
    if (req.method === "GET" && url === "/health") {
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url === "/v1/dice/stats") {
      const body = await readBody(req);
      handleDiceStats(body, res);
      return;
    }
    if (req.method === "POST" && url === "/v1/checks/ability") {
      const body = await readBody(req);
      handleAbilityCheck(body, res);
      return;
    }
    if (req.method === "POST" && url === "/v1/encounters/adjusted-xp") {
      const body = await readBody(req);
      handleAdjustedXp(body, res);
      return;
    }
    if (req.method === "POST" && url === "/v1/initiative/order") {
      const body = await readBody(req);
      handleInitiativeOrder(body, res);
      return;
    }
    sendJson(res, 404, { error: "not found" });
  } catch (err) {
    sendJson(res, 400, { error: "invalid request" });
  }
});

const port = Number(process.env.PORT) || 3000;
server.listen(port, "127.0.0.1", () => {
  console.log(`listening on 127.0.0.1:${port}`);
});
