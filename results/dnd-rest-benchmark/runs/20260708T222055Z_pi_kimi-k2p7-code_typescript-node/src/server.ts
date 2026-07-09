import http from "http";
import { URL } from "url";

const port = Number(process.env.PORT ?? "3000");

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

function multiplierForMonsterCount(n: number): number {
  if (n === 1) return 1;
  if (n === 2) return 1.5;
  if (n <= 6) return 2;
  if (n <= 10) return 2.5;
  if (n <= 14) return 3;
  return 4;
}

function parseBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      data += chunk;
    });
    req.on("end", () => {
      try {
        resolve(data === "" ? {} : JSON.parse(data));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res: http.ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function parseDiceExpression(expr: unknown): { dice_count: number; sides: number; modifier: number } | null {
  if (typeof expr !== "string") return null;
  const match = expr.match(/^(\d+)d(\d+)([+-]\d+)?$/);
  if (!match) return null;
  const dice_count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (dice_count <= 0 || sides <= 0) return null;
  return { dice_count, sides, modifier };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");

  if (req.method === "GET" && url.pathname === "/health") {
    sendJson(res, 200, { ok: true });
    return;
  }

  if (req.method !== "POST") {
    sendJson(res, 404, { error: "not found" });
    return;
  }

  let body: unknown;
  try {
    body = await parseBody(req);
  } catch {
    sendJson(res, 400, { error: "invalid JSON" });
    return;
  }

  if (url.pathname === "/v1/dice/stats") {
    const parsed = parseDiceExpression((body as Record<string, unknown>).expression);
    if (!parsed) {
      sendJson(res, 400, { error: "invalid expression" });
      return;
    }
    const { dice_count, sides, modifier } = parsed;
    const min = dice_count + modifier;
    const max = dice_count * sides + modifier;
    const average = Math.floor((min + max) / 2);
    sendJson(res, 200, {
      dice_count,
      sides,
      modifier,
      min,
      max,
      average,
    });
    return;
  }

  if (url.pathname === "/v1/checks/ability") {
    const b = body as Record<string, unknown>;
    const roll = Number(b.roll);
    const modifier = Number(b.modifier);
    const dc = Number(b.dc);
    if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
      sendJson(res, 400, { error: "invalid input" });
      return;
    }
    const total = roll + modifier;
    const success = total >= dc;
    const margin = total - dc;
    sendJson(res, 200, { total, success, margin });
    return;
  }

  if (url.pathname === "/v1/encounters/adjusted-xp") {
    const b = body as {
      party?: Array<{ level?: unknown }>;
      monsters?: Array<{ cr?: unknown; count?: unknown }>;
    };
    if (!Array.isArray(b.party) || !Array.isArray(b.monsters)) {
      sendJson(res, 400, { error: "invalid input" });
      return;
    }

    const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
    for (const member of b.party) {
      const level = Number(member.level);
      const t = LEVEL_THRESHOLDS[level];
      if (!t) {
        sendJson(res, 400, { error: "unsupported level" });
        return;
      }
      thresholds.easy += t.easy;
      thresholds.medium += t.medium;
      thresholds.hard += t.hard;
      thresholds.deadly += t.deadly;
    }

    let base_xp = 0;
    let monster_count = 0;
    for (const monster of b.monsters) {
      const cr = String(monster.cr);
      const xp = CR_XP[cr];
      if (xp === undefined) {
        sendJson(res, 400, { error: "unsupported CR" });
        return;
      }
      const count = Number(monster.count);
      if (!Number.isInteger(count) || count <= 0) {
        sendJson(res, 400, { error: "invalid monster count" });
        return;
      }
      base_xp += xp * count;
      monster_count += count;
    }

    const multiplier = multiplierForMonsterCount(monster_count);
    const adjusted_xp = base_xp * multiplier;

    let difficulty = "trivial";
    if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
    else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
    else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
    else if (adjusted_xp >= thresholds.easy) difficulty = "easy";

    sendJson(res, 200, {
      base_xp,
      monster_count,
      multiplier,
      adjusted_xp,
      difficulty,
      thresholds,
    });
    return;
  }

  if (url.pathname === "/v1/initiative/order") {
    const b = body as {
      combatants?: Array<{ name?: unknown; dex?: unknown; roll?: unknown }>;
    };
    if (!Array.isArray(b.combatants)) {
      sendJson(res, 400, { error: "invalid input" });
      return;
    }
    const order = b.combatants
      .map((c) => ({
        name: String(c.name ?? ""),
        dex: Number(c.dex ?? 0),
        roll: Number(c.roll ?? 0),
      }))
      .map((c) => ({ name: c.name, dex: c.dex, score: c.roll + c.dex }))
      .sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.dex !== a.dex) return b.dex - a.dex;
        return a.name.localeCompare(b.name);
      })
      .map((c) => ({ name: c.name, score: c.score }));
    sendJson(res, 200, { order });
    return;
  }

  sendJson(res, 404, { error: "not found" });
});

server.listen(port, "127.0.0.1", () => {
  // Server is ready.
});
