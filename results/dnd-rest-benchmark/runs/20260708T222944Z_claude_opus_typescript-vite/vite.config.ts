import type { Plugin, ViteDevServer } from "vite";
import type { IncomingMessage, ServerResponse } from "node:http";

// ---- Domain logic -------------------------------------------------------

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

// Level -> [easy, medium, hard, deadly]
const LEVEL_THRESHOLDS: Record<number, [number, number, number, number]> = {
  3: [75, 150, 225, 400],
};

function countMultiplier(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

interface DiceResult {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
}

function parseDice(expression: unknown): DiceResult | null {
  if (typeof expression !== "string") return null;
  const m = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression.trim());
  if (!m) return null;
  const dice_count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  const modifier = m[3] ? parseInt(m[3], 10) : 0;
  if (dice_count <= 0 || sides <= 0) return null;
  const min = dice_count * 1 + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;
  return { dice_count, sides, modifier, min, max, average };
}

// ---- HTTP helpers -------------------------------------------------------

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(payload);
}

function readBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (raw.trim() === "") {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error("invalid json"));
      }
    });
    req.on("error", reject);
  });
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

// ---- Route handlers -----------------------------------------------------

function handleDiceStats(res: ServerResponse, body: any): void {
  const result = parseDice(body?.expression);
  if (!result) {
    sendJson(res, 400, { error: "invalid expression" });
    return;
  }
  sendJson(res, 200, result);
}

function handleAbilityCheck(res: ServerResponse, body: any): void {
  const { roll, modifier, dc } = body ?? {};
  if (!isFiniteNumber(roll) || !isFiniteNumber(modifier) || !isFiniteNumber(dc)) {
    sendJson(res, 400, { error: "roll, modifier and dc must be numbers" });
    return;
  }
  const total = roll + modifier;
  sendJson(res, 200, {
    total,
    success: total >= dc,
    margin: total - dc,
  });
}

function handleAdjustedXp(res: ServerResponse, body: any): void {
  const party = body?.party;
  const monsters = body?.monsters;
  if (!Array.isArray(party) || !Array.isArray(monsters)) {
    sendJson(res, 400, { error: "party and monsters must be arrays" });
    return;
  }

  let base_xp = 0;
  let monster_count = 0;
  for (const mon of monsters) {
    const cr = mon?.cr;
    const count = mon?.count;
    if (typeof cr !== "string" || !(cr in CR_XP)) {
      sendJson(res, 400, { error: `unsupported cr: ${String(cr)}` });
      return;
    }
    if (!isFiniteNumber(count) || !Number.isInteger(count) || count < 0) {
      sendJson(res, 400, { error: "monster count must be a non-negative integer" });
      return;
    }
    base_xp += CR_XP[cr] * count;
    monster_count += count;
  }

  const thresholdTotals = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const level = member?.level;
    if (!isFiniteNumber(level) || !(level in LEVEL_THRESHOLDS)) {
      sendJson(res, 400, { error: `unsupported party level: ${String(level)}` });
      return;
    }
    const [easy, medium, hard, deadly] = LEVEL_THRESHOLDS[level];
    thresholdTotals.easy += easy;
    thresholdTotals.medium += medium;
    thresholdTotals.hard += hard;
    thresholdTotals.deadly += deadly;
  }

  const multiplier = countMultiplier(monster_count);
  const adjusted_xp = base_xp * multiplier;

  let difficulty: "trivial" | "easy" | "medium" | "hard" | "deadly" = "trivial";
  if (adjusted_xp >= thresholdTotals.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholdTotals.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholdTotals.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholdTotals.easy) difficulty = "easy";

  sendJson(res, 200, {
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds: thresholdTotals,
  });
}

function handleInitiative(res: ServerResponse, body: any): void {
  const combatants = body?.combatants;
  if (!Array.isArray(combatants)) {
    sendJson(res, 400, { error: "combatants must be an array" });
    return;
  }

  const scored = [];
  for (const c of combatants) {
    const name = c?.name;
    const dex = c?.dex;
    const roll = c?.roll;
    if (typeof name !== "string" || !isFiniteNumber(dex) || !isFiniteNumber(roll)) {
      sendJson(res, 400, { error: "each combatant needs name, dex and roll" });
      return;
    }
    scored.push({ name, dex, roll, score: roll + dex });
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  sendJson(res, 200, {
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}

// ---- Plugin -------------------------------------------------------------

function dndApiPlugin(): Plugin {
  const configure = (server: ViteDevServer) => {
    server.middlewares.use(async (req, res, next) => {
      const url = (req.url ?? "").split("?")[0];
      const method = req.method ?? "GET";

      try {
        if (method === "GET" && url === "/health") {
          sendJson(res, 200, { ok: true });
          return;
        }

        if (method === "POST" && url.startsWith("/v1/")) {
          let body: unknown;
          try {
            body = await readBody(req);
          } catch {
            sendJson(res, 400, { error: "invalid json body" });
            return;
          }

          switch (url) {
            case "/v1/dice/stats":
              handleDiceStats(res, body);
              return;
            case "/v1/checks/ability":
              handleAbilityCheck(res, body);
              return;
            case "/v1/encounters/adjusted-xp":
              handleAdjustedXp(res, body);
              return;
            case "/v1/initiative/order":
              handleInitiative(res, body);
              return;
            default:
              next();
              return;
          }
        }

        next();
      } catch {
        if (!res.headersSent) sendJson(res, 500, { error: "internal error" });
      }
    });
  };

  return {
    name: "dnd-rest-api",
    configureServer: configure,
    configurePreviewServer: configure as any,
  };
}

export default {
  plugins: [dndApiPlugin()],
};
