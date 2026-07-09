import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const HOST = "127.0.0.1";
const PORT = Number.parseInt(process.env.PORT ?? "3000", 10);

type JsonObject = Record<string, unknown>;

const crXp: Record<string, number> = {
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

const level3Thresholds = {
  easy: 75,
  medium: 150,
  hard: 225,
  deadly: 400,
};

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function sendJson(response: ServerResponse, statusCode: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  response.end(payload);
}

function badRequest(response: ServerResponse): void {
  sendJson(response, 400, { error: "bad_request" });
}

function notFound(response: ServerResponse): void {
  sendJson(response, 404, { error: "not_found" });
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (raw.length === 0) {
    throw new Error("empty body");
  }
  return JSON.parse(raw);
}

function handleDiceStats(body: unknown): unknown | null {
  if (!isObject(body) || typeof body.expression !== "string") {
    return null;
  }

  const match = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/.exec(body.expression);
  if (match === null) {
    return null;
  }

  const diceCount = Number.parseInt(match[1], 10);
  const sides = Number.parseInt(match[2], 10);
  const modifierMagnitude = match[4] === undefined ? 0 : Number.parseInt(match[4], 10);
  const modifier = match[3] === "-" ? -modifierMagnitude : modifierMagnitude;

  if (diceCount <= 0 || sides <= 0) {
    return null;
  }

  return {
    dice_count: diceCount,
    sides,
    modifier,
    min: diceCount + modifier,
    max: diceCount * sides + modifier,
    average: diceCount * ((sides + 1) / 2) + modifier,
  };
}

function handleAbilityCheck(body: unknown): unknown | null {
  if (!isObject(body) || !isFiniteNumber(body.roll) || !isFiniteNumber(body.modifier) || !isFiniteNumber(body.dc)) {
    return null;
  }

  const total = body.roll + body.modifier;
  return {
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  };
}

function monsterMultiplier(count: number): number | null {
  if (!Number.isInteger(count) || count <= 0) {
    return null;
  }
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

function handleAdjustedXp(body: unknown): unknown | null {
  if (!isObject(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    return null;
  }

  let partySize = 0;
  for (const member of body.party) {
    if (!isObject(member) || member.level !== 3) {
      return null;
    }
    partySize += 1;
  }

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of body.monsters) {
    if (!isObject(monster) || typeof monster.cr !== "string" || !isFiniteNumber(monster.count)) {
      return null;
    }
    const xp = crXp[monster.cr];
    if (xp === undefined || !Number.isInteger(monster.count) || monster.count <= 0) {
      return null;
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const multiplier = monsterMultiplier(monsterCount);
  if (multiplier === null) {
    return null;
  }

  const thresholds = {
    easy: level3Thresholds.easy * partySize,
    medium: level3Thresholds.medium * partySize,
    hard: level3Thresholds.hard * partySize,
    deadly: level3Thresholds.deadly * partySize,
  };
  const adjustedXp = baseXp * multiplier;
  let difficulty = "trivial";
  if (adjustedXp >= thresholds.easy) difficulty = "easy";
  if (adjustedXp >= thresholds.medium) difficulty = "medium";
  if (adjustedXp >= thresholds.hard) difficulty = "hard";
  if (adjustedXp >= thresholds.deadly) difficulty = "deadly";

  return {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier,
    adjusted_xp: adjustedXp,
    difficulty,
    thresholds,
  };
}

function handleInitiativeOrder(body: unknown): unknown | null {
  if (!isObject(body) || !Array.isArray(body.combatants)) {
    return null;
  }

  const combatants = body.combatants.map((combatant) => {
    if (!isObject(combatant) || typeof combatant.name !== "string" || !isFiniteNumber(combatant.dex) || !isFiniteNumber(combatant.roll)) {
      return null;
    }
    return {
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    };
  });

  if (combatants.some((combatant) => combatant === null)) {
    return null;
  }

  const order = combatants
    .sort((left, right) => right!.score - left!.score || right!.dex - left!.dex || left!.name.localeCompare(right!.name))
    .map((combatant) => ({
      name: combatant!.name,
      score: combatant!.score,
    }));

  return { order };
}

function routePost(pathname: string, body: unknown): unknown | null | undefined {
  if (pathname === "/v1/dice/stats") return handleDiceStats(body);
  if (pathname === "/v1/checks/ability") return handleAbilityCheck(body);
  if (pathname === "/v1/encounters/adjusted-xp") return handleAdjustedXp(body);
  if (pathname === "/v1/initiative/order") return handleInitiativeOrder(body);
  return undefined;
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://${HOST}`);

  if (request.method === "GET" && url.pathname === "/health") {
    sendJson(response, 200, { ok: true });
    return;
  }

  if (request.method !== "POST") {
    notFound(response);
    return;
  }

  let body: unknown;
  try {
    body = await readJson(request);
  } catch {
    badRequest(response);
    return;
  }

  const result = routePost(url.pathname, body);
  if (result === undefined) {
    notFound(response);
    return;
  }
  if (result === null) {
    badRequest(response);
    return;
  }

  sendJson(response, 200, result);
});

server.listen(PORT, HOST);
